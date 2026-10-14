"""orchestrator/replay.py: Canonical output hashing and report replay verification."""

from __future__ import annotations

import decimal
import hashlib
import json
import subprocess
from dataclasses import dataclass
from decimal import Decimal

from pyexasol import ExaConnection

from orchestrator.db import connect


@dataclass(frozen=True)
class ReplayResult:
    original_run_id: str
    replay_run_id: str
    original_hash: str
    replay_hash: str
    matches: bool
    code_version_differs: bool


def get_git_code_version() -> str:
    """Get current git HEAD commit SHA, suffixed with '-dirty' if uncommitted changes exist."""
    try:
        head_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        status_out = subprocess.check_output(
            ["git", "status", "--porcelain"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        if status_out:
            return f"{head_sha}-dirty"
        return head_sha
    except Exception:
        return "unknown"


def canonical_membership_line(
    group_key: str,
    entity_key: str,
    membership_kind: str,
    is_head: bool | int | str,
    group_flags: str | None,
) -> str:
    """Format a single RUN_MEMBERSHIP canonical line:

    M|group_key|entity_key|membership_kind|is_head|group_flags
    """
    head_str = "TRUE" if is_head in (True, 1, "TRUE", "true", "1") else "FALSE"
    flags_str = str(group_flags) if group_flags is not None else ""
    return f"M|{group_key}|{entity_key}|{membership_kind}|{head_str}|{flags_str}"


def canonical_output_line(
    group_key: str,
    entity_key: str,
    source_system: str,
    source_row_id: str,
    exposure_component: str,
    membership_kind: str,
    rec_key: str,
    product: str | None,
    gross: Decimal | float | str,
    ccf: Decimal | float | str,
    exposure: Decimal | float | str,
    link_decision_id: str | None,
) -> str:
    """Format a single RUN_OUTPUT canonical line:

    O|group_key|entity_key|source_system|source_row_id|exposure_component|membership_kind|rec_key|product|gross:.2f|ccf:.4f|exposure:.2f|link_decision_id
    """
    prod_str = str(product) if product is not None else ""
    dec_id_str = str(link_decision_id) if link_decision_id is not None else ""

    q_gross = Decimal(str(gross)).quantize(Decimal("0.01"), rounding=decimal.ROUND_HALF_UP)
    q_ccf = Decimal(str(ccf)).quantize(Decimal("0.0001"), rounding=decimal.ROUND_HALF_UP)
    q_exp = Decimal(str(exposure)).quantize(Decimal("0.01"), rounding=decimal.ROUND_HALF_UP)

    return (
        f"O|{group_key}|{entity_key}|{source_system}|{source_row_id}|{exposure_component}|"
        f"{membership_kind}|{rec_key}|{prod_str}|{q_gross:.2f}|{q_ccf:.4f}|{q_exp:.2f}|{dec_id_str}"
    )


def compute_output_hash(conn: ExaConnection, run_id: str) -> tuple[str, int]:
    """Compute deterministic canonical SHA-256 hash of report run output and membership.

    Excludes run_id and timestamps. Uses exact Decimal quantization.
    Returns (sha256_hex, row_count).
    """
    # 1. Fetch RUN_MEMBERSHIP rows where exposure > 0 or is_head = TRUE
    # Joined with exposure sum from RUN_OUTPUT
    mem_query = """
    SELECT m.group_key, m.entity_key, m.membership_kind, m.is_head, m.group_flags,
           COALESCE(SUM(o.exposure_amount), 0) AS total_exp
    FROM GOV.RUN_MEMBERSHIP m
    LEFT JOIN GOV.RUN_OUTPUT o
      ON m.run_id = o.run_id
     AND m.group_key = o.group_key
     AND m.entity_key = o.entity_key
    WHERE m.run_id = {run_id}
    GROUP BY m.group_key, m.entity_key, m.membership_kind, m.is_head, m.group_flags
    HAVING m.is_head = TRUE OR COALESCE(SUM(o.exposure_amount), 0) > 0
    """
    mem_rows = conn.execute(mem_query, query_params={"run_id": run_id}).fetchall()

    m_lines: list[str] = []
    for r in mem_rows:
        if isinstance(r, dict):
            g_key = r["group_key"]
            e_key = r["entity_key"]
            m_kind = r["membership_kind"]
            i_head = r["is_head"]
            g_flags = r["group_flags"]
        else:
            g_key, e_key, m_kind, i_head, g_flags, _ = r
        m_lines.append(canonical_membership_line(g_key, e_key, m_kind, i_head, g_flags))

    m_lines.sort()

    # 2. Fetch RUN_OUTPUT rows
    out_query = """
    SELECT group_key, entity_key, source_system, source_row_id, exposure_component,
           membership_kind, rec_key, product, gross_amount, ccf, exposure_amount,
           link_decision_id
    FROM GOV.RUN_OUTPUT
    WHERE run_id = {run_id}
    """
    out_rows = conn.execute(out_query, query_params={"run_id": run_id}).fetchall()

    o_lines: list[str] = []
    for r in out_rows:
        if isinstance(r, dict):
            g_key = r["group_key"]
            e_key = r["entity_key"]
            src_sys = r["source_system"]
            src_row = r["source_row_id"]
            exp_comp = r["exposure_component"]
            m_kind = r["membership_kind"]
            rec_k = r["rec_key"]
            prod = r["product"]
            gross = r["gross_amount"]
            ccf = r["ccf"]
            exp_amt = r["exposure_amount"]
            dec_id = r["link_decision_id"]
        else:
            g_key, e_key, src_sys, src_row, exp_comp, m_kind, rec_k, prod, gross, ccf, exp_amt, dec_id = r

        o_lines.append(
            canonical_output_line(
                g_key, e_key, src_sys, src_row, exp_comp, m_kind, rec_k, prod, gross, ccf, exp_amt, dec_id
            )
        )

    o_lines.sort()

    # Combine M lines then O lines, joined by \n
    all_lines = m_lines + o_lines
    canonical_payload = "\n".join(all_lines)
    output_hash = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
    row_count = len(out_rows)

    return output_hash, row_count


def replay(run_id: str, conn: ExaConnection | None = None) -> ReplayResult:
    """Re-run publish_run using the saved REPORT_RUN manifest and verify output hash."""
    from orchestrator.pipeline import publish_run

    close_conn = False
    if conn is None:
        conn = connect("pipeline", autocommit=True)
        close_conn = True

    try:
        stmt = conn.execute(
            """
            SELECT run_id, business_date, known_at, load_ids_json, policy_event_ids_json,
                   code_version, output_hash, status
            FROM GOV.REPORT_RUN
            WHERE run_id = {run_id}
            """,
            query_params={"run_id": run_id},
        )
        row = stmt.fetchone()
        if not row:
            raise ValueError(f"Run {run_id} not found in GOV.REPORT_RUN")

        if isinstance(row, dict):
            bd = row["business_date"]
            known_at = row["known_at"]
            load_ids_json = row["load_ids_json"]
            policy_event_ids_json = row["policy_event_ids_json"]
            orig_code_version = row["code_version"]
            orig_hash = row["output_hash"]
        else:
            _, bd, known_at, load_ids_json, policy_event_ids_json, orig_code_version, orig_hash, _ = row

        manifest = {
            "load_ids": json.loads(load_ids_json) if isinstance(load_ids_json, str) else load_ids_json,
            "policy_event_ids": json.loads(policy_event_ids_json)
            if isinstance(policy_event_ids_json, str)
            else policy_event_ids_json,
        }

        # Re-run publish_run as replay
        replay_result = publish_run(
            business_date=bd,
            known_at=known_at,
            manifest=manifest,
            replay_of=run_id,
            conn=conn,
        )

        current_code_version = get_git_code_version()
        code_differs = (orig_code_version != current_code_version)
        matches = (orig_hash == replay_result.output_hash)

        return ReplayResult(
            original_run_id=run_id,
            replay_run_id=replay_result.run_id,
            original_hash=orig_hash or "",
            replay_hash=replay_result.output_hash or "",
            matches=matches,
            code_version_differs=code_differs,
        )
    finally:
        if close_conn:
            conn.close()
