"""orchestrator/pipeline.py: End-to-end matching pipeline and report publication orchestrator."""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from pyexasol import ExaConnection

from orchestrator.db import REPO_ROOT, connect, run_sql_file
from orchestrator.policy import policy_in_force
from orchestrator.replay import compute_output_hash, get_git_code_version


@dataclass(frozen=True)
class RunResult:
    run_id: str
    output_hash: str | None
    status: Literal["OK", "LP_ABORTED"]
    lp_passes: int
    row_count: int


def _resolve_latest_load_id(
    conn: ExaConnection,
    table: str,
    date_col: str | None,
    business_date: str,
    known_at: str,
) -> str:
    """Find the latest load_id for a given raw table."""
    if date_col:
        q = f"""
        SELECT load_id FROM {table}
        WHERE {date_col} = {{business_date}} AND loaded_at <= {{known_at}}
        ORDER BY loaded_at DESC, load_id DESC
        LIMIT 1
        """
        params = {"business_date": business_date, "known_at": known_at}
    else:
        q = f"""
        SELECT load_id FROM {table}
        WHERE loaded_at <= {{known_at}}
        ORDER BY loaded_at DESC, load_id DESC
        LIMIT 1
        """
        params = {"known_at": known_at}

    stmt = conn.execute(q, query_params=params)
    row = stmt.fetchone()
    if not row or not row.get("load_id"):
        raise ValueError(f"Could not resolve active load_id from {table} for {business_date} (known_at {known_at}).")
    return str(row["load_id"])


def _record_timing(
    conn: ExaConnection,
    job_id: str,
    stage: str,
    rows_affected: int,
    seconds: float,
    started_at: datetime,
) -> None:
    """Record execution duration and row count in GOV.PIPELINE_TIMING."""
    started_str = started_at.strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        INSERT INTO GOV.PIPELINE_TIMING (
            job_id, stage, rows_affected, seconds, started_at
        ) VALUES (
            {job_id}, {stage}, {rows_affected}, {seconds}, {started_at}
        )
        """,
        query_params={
            "job_id": job_id,
            "stage": stage,
            "rows_affected": rows_affected,
            "seconds": round(seconds, 3),
            "started_at": started_str,
        },
    )


def publish_run(
    business_date: date | str,
    known_at: datetime | str | None = None,
    manifest: dict | None = None,
    replay_of: str | None = None,
    conn: ExaConnection | None = None,
    sql_dir: str | Path | None = None,
) -> RunResult:
    """Rebuild working state, execute Label Propagation, write GOV.RUN_*, and compute hash.

    Connects as TALOS_PIPELINE if conn is None.
    Raises FileNotFoundError if required SQL files are missing.
    """
    close_conn = False
    if conn is None:
        conn = connect("pipeline", autocommit=True)
        close_conn = True

    if sql_dir is None:
        sql_path = REPO_ROOT / "sql"
    else:
        sql_path = Path(sql_dir)
        if not sql_path.is_absolute():
            sql_path = REPO_ROOT / sql_path

    if not sql_path.is_dir():
        raise FileNotFoundError(f"SQL directory not found at {sql_path}")

    started_at = datetime.now(UTC)
    bd_str = business_date.isoformat() if isinstance(business_date, date) else str(business_date)
    if known_at is None:
        known_dt = started_at
        known_str = known_dt.strftime("%Y-%m-%d %H:%M:%S")
    elif isinstance(known_at, datetime):
        known_dt = known_at
        known_str = known_dt.strftime("%Y-%m-%d %H:%M:%S")
    else:
        known_str = str(known_at)

    now_tag = started_at.strftime("%Y%m%d%H%M%S")
    rand_hex = secrets.token_hex(2)
    run_id = f"R-{now_tag}-{rand_hex}"

    try:
        # Resolve load IDs and policy events
        if manifest:
            load_ids = manifest.get("load_ids", {})
            policy_event_ids = manifest.get("policy_event_ids", {})
            policy_values, _ = policy_in_force(conn, bd_str, known_str)
        else:
            load_ids = {
                "LOS": _resolve_latest_load_id(conn, "RAW_LOS.CUSTOMER", "business_date", bd_str, known_str),
                "TSY": _resolve_latest_load_id(conn, "RAW_TREASURY.HOLDING", "business_date", bd_str, known_str),
                "GTE": _resolve_latest_load_id(conn, "RAW_GUARANTEE.GUARANTEE", "business_date", bd_str, known_str),
                "COL": _resolve_latest_load_id(conn, "RAW_COLLATERAL.PLEDGE", "business_date", bd_str, known_str),
                "REG": _resolve_latest_load_id(conn, "RAW_REGISTRY.ENTITY_FILING", None, bd_str, known_str),
            }
            policy_values, policy_event_ids = policy_in_force(conn, bd_str, known_str)

        lp_max_passes = int(policy_values.get("LP_MAX_PASSES", 50))
        code_version = get_git_code_version()

        params: dict[str, Any] = {
            "business_date": bd_str,
            "known_at": known_str,
            "run_id": run_id,
            "baseline_run": run_id,
            "los_load_id": load_ids.get("LOS", ""),
            "tsy_load_id": load_ids.get("TSY", ""),
            "gte_load_id": load_ids.get("GTE", ""),
            "col_load_id": load_ids.get("COL", ""),
            "reg_load_id": load_ids.get("REG", ""),
            **policy_values,
        }

        # 1. Required stage: 50_asof_links_edges.sql & 51_components_init.sql
        run_sql_file(conn, sql_path / "50_asof_links_edges.sql", **params)
        run_sql_file(conn, sql_path / "51_components_init.sql", **params)

        # 2. Required stage: Loop 52_components_pass.sql
        converged = False
        lp_passes = 0
        pass_file = sql_path / "52_components_pass.sql"
        while lp_passes < lp_max_passes:
            lp_passes += 1
            rowcounts = run_sql_file(conn, pass_file, **params)
            total_mod = sum(rc for rc in rowcounts if rc > 0)
            if total_mod == 0:
                converged = True
                break

        if not converged:
            finished_at = datetime.now(UTC)
            conn.execute(
                """
                INSERT INTO GOV.REPORT_RUN (
                    run_id, business_date, known_at, load_ids_json, policy_event_ids_json,
                    code_version, output_hash, row_count, lp_passes, status, replay_of,
                    started_at, finished_at
                ) VALUES (
                    {run_id}, {business_date}, {known_at}, {load_ids_json}, {policy_event_ids_json},
                    {code_version}, NULL, 0, {lp_passes}, 'LP_ABORTED', {replay_of},
                    {started_at}, {finished_at}
                )
                """,
                query_params={
                    "run_id": run_id,
                    "business_date": bd_str,
                    "known_at": known_str,
                    "load_ids_json": json.dumps(load_ids),
                    "policy_event_ids_json": json.dumps(policy_event_ids),
                    "code_version": code_version,
                    "lp_passes": lp_passes,
                    "replay_of": replay_of,
                    "started_at": started_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "finished_at": finished_at.strftime("%Y-%m-%d %H:%M:%S"),
                },
            )
            return RunResult(
                run_id=run_id,
                output_hash=None,
                status="LP_ABORTED",
                lp_passes=lp_passes,
                row_count=0,
            )

        # 3. Post-component stages: 60, 61, 62, 63
        for step in ["60_entity_exposure.sql", "61_membership.sql", "62_run_output.sql", "63_reported_baseline.sql"]:
            run_sql_file(conn, sql_path / step, **params)

        # 4. Hash and row count computation
        output_hash, row_count = compute_output_hash(conn, run_id)
        finished_at = datetime.now(UTC)

        # 5. Insert successful run record
        conn.execute(
            """
            INSERT INTO GOV.REPORT_RUN (
                run_id, business_date, known_at, load_ids_json, policy_event_ids_json,
                code_version, output_hash, row_count, lp_passes, status, replay_of,
                started_at, finished_at
            ) VALUES (
                {run_id}, {business_date}, {known_at}, {load_ids_json}, {policy_event_ids_json},
                {code_version}, {output_hash}, {row_count}, {lp_passes}, 'OK', {replay_of},
                {started_at}, {finished_at}
            )
            """,
            query_params={
                "run_id": run_id,
                "business_date": bd_str,
                "known_at": known_str,
                "load_ids_json": json.dumps(load_ids),
                "policy_event_ids_json": json.dumps(policy_event_ids),
                "code_version": code_version,
                "output_hash": output_hash,
                "row_count": row_count,
                "lp_passes": lp_passes,
                "replay_of": replay_of,
                "started_at": started_at.strftime("%Y-%m-%d %H:%M:%S"),
                "finished_at": finished_at.strftime("%Y-%m-%d %H:%M:%S"),
            },
        )

        return RunResult(
            run_id=run_id,
            output_hash=output_hash,
            status="OK",
            lp_passes=lp_passes,
            row_count=row_count,
        )

    finally:
        if close_conn:
            conn.close()


def match(
    business_date: date | str,
    known_at: datetime | str | None = None,
    conn: ExaConnection | None = None,
    sql_dir: str | Path | None = None,
) -> RunResult:
    """Execute the full matching pipeline and file new proposals.

    Connects as TALOS_PIPELINE if conn is None.
    Raises FileNotFoundError if required pipeline SQL files are missing.
    """
    from orchestrator.judge import run_t2

    close_conn = False
    if conn is None:
        conn = connect("pipeline", autocommit=True)
        close_conn = True

    if sql_dir is None:
        sql_path = REPO_ROOT / "sql"
    else:
        sql_path = Path(sql_dir)
        if not sql_path.is_absolute():
            sql_path = REPO_ROOT / sql_path

    if not sql_path.is_dir():
        raise FileNotFoundError(f"SQL directory not found at {sql_path}")

    bd_str = business_date.isoformat() if isinstance(business_date, date) else str(business_date)
    if known_at is None:
        known_dt = datetime.now(UTC)
        known_str = known_dt.strftime("%Y-%m-%d %H:%M:%S")
    elif isinstance(known_at, datetime):
        known_dt = known_at
        known_str = known_dt.strftime("%Y-%m-%d %H:%M:%S")
    else:
        known_str = str(known_at)

    job_id = f"J-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(2)}"

    def _execute_stage(stage_name: str, sql_file_names: list[str], **kwargs) -> int:
        t0 = time.time()
        start_time = datetime.now(UTC)
        total_rows = 0
        for f_name in sql_file_names:
            p = sql_path / f_name
            rcs = run_sql_file(conn, p, **kwargs)
            total_rows += sum(rc for rc in rcs if rc > 0)
        dur = time.time() - t0
        _record_timing(conn, job_id, stage_name, total_rows, dur, start_time)
        return total_rows

    try:
        policy_values, _ = policy_in_force(conn, bd_str, known_str)
        stage_params: dict[str, Any] = {
            "business_date": bd_str,
            "known_at": known_str,
            **policy_values,
        }

        # 1. 10_standardise.sql
        _execute_stage("10_standardise", ["10_standardise.sql"], **stage_params)

        # 2. 20_id_tokens_exact.sql
        _execute_stage("20_id_tokens_exact", ["20_id_tokens_exact.sql"], **stage_params)

        # 3. 30_block_keys.sql & 31_candidates_blocked.sql
        _execute_stage("30_31_blocking", ["30_block_keys.sql", "31_candidates_blocked.sql"], **stage_params)

        # 4. 40_score_tier.sql
        _execute_stage("40_score_tier", ["40_score_tier.sql"], **stage_params)

        # 5. judge.run_t2() + 41_apply_verdicts.sql
        t_judge_start = datetime.now(UTC)
        t0_j = time.time()
        run_t2(conn=conn)
        _execute_stage("41_apply_verdicts", ["41_apply_verdicts.sql"], **stage_params)
        dur_j = time.time() - t0_j
        _record_timing(conn, job_id, "judge_t2", 0, dur_j, t_judge_start)

        # 6. baseline_run = publish_run(business_date, known_at)
        baseline_run = publish_run(
            business_date=bd_str,
            known_at=known_str,
            conn=conn,
            sql_dir=sql_path,
        )

        stage_params["baseline_run"] = baseline_run.run_id

        # 7. 70_propose_record_links.sql
        _execute_stage("70_propose_record_links", ["70_propose_record_links.sql"], **stage_params)

        # 8. 71_propose_edges.sql
        _execute_stage("71_propose_edges", ["71_propose_edges.sql"], **stage_params)

        return baseline_run

    finally:
        if close_conn:
            conn.close()
