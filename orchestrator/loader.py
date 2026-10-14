"""orchestrator/loader.py: Ingest Parquet datasets into Exasol RAW, STAGE, and TRUTH schemas."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from pyexasol import ExaConnection

from orchestrator.db import connect
from orchestrator.policy import load_thresholds

TABLE_TARGETS: dict[str, str] = {
    "customer": "RAW_LOS.CUSTOMER",
    "los_customer": "RAW_LOS.CUSTOMER",
    "raw_los_customer": "RAW_LOS.CUSTOMER",
    "loan": "RAW_LOS.LOAN",
    "los_loan": "RAW_LOS.LOAN",
    "raw_los_loan": "RAW_LOS.LOAN",
    "dependency": "RAW_LOS.DEPENDENCY",
    "los_dependency": "RAW_LOS.DEPENDENCY",
    "raw_los_dependency": "RAW_LOS.DEPENDENCY",
    "holding": "RAW_TREASURY.HOLDING",
    "treasury_holding": "RAW_TREASURY.HOLDING",
    "raw_treasury_holding": "RAW_TREASURY.HOLDING",
    "guarantee": "RAW_GUARANTEE.GUARANTEE",
    "raw_guarantee": "RAW_GUARANTEE.GUARANTEE",
    "pledge": "RAW_COLLATERAL.PLEDGE",
    "raw_collateral_pledge": "RAW_COLLATERAL.PLEDGE",
    "entity_filing": "RAW_REGISTRY.ENTITY_FILING",
    "raw_registry_entity_filing": "RAW_REGISTRY.ENTITY_FILING",
    "ownership_edge": "RAW_REGISTRY.OWNERSHIP_EDGE",
    "raw_registry_ownership_edge": "RAW_REGISTRY.OWNERSHIP_EDGE",
    "pincode_district": "STAGE.PINCODE_DISTRICT",
    "gt_entity": "TRUTH.GT_ENTITY",
    "gt_record_entity": "TRUTH.GT_RECORD_ENTITY",
    "gt_group": "TRUTH.GT_GROUP",
    "gt_edge": "TRUTH.GT_EDGE",
    "gt_jv_ruling": "TRUTH.GT_JV_RULING",
    "gt_plant": "TRUTH.GT_PLANT",
}


def _iter_parquet_tuples(file_path: Path) -> Iterable[tuple[Any, ...]]:
    """Stream Parquet row batches as tuples of Python primitives."""
    parquet_file = pq.ParquetFile(file_path)
    for batch in parquet_file.iter_batches():
        pydict = batch.to_pydict()
        cols = [pydict[name] for name in batch.schema.names]
        num_rows = len(batch)
        for i in range(num_rows):
            yield tuple(col[i] for col in cols)


def resolve_target_table(file_path: Path) -> str | None:
    """Resolve destination Exasol table name from a parquet file path."""
    stem = file_path.stem.lower()
    if stem in TABLE_TARGETS:
        return TABLE_TARGETS[stem]

    # Try parent_dir_stem
    parent_stem = f"{file_path.parent.name}_{stem}".lower()
    if parent_stem in TABLE_TARGETS:
        return TABLE_TARGETS[parent_stem]

    # Try direct uppercase match (e.g. RAW_LOS.CUSTOMER.parquet)
    if "." in stem:
        schema, table = stem.split(".", 1)
        return f"{schema.upper()}.{table.upper()}"

    return None


def seed_policy_events(conn: ExaConnection) -> int:
    """Seed initial GOV.POLICY_EVENT rows from spec and policy/thresholds.json."""
    thresholds = load_thresholds()

    initial_events: list[dict[str, Any]] = [
        # CAPITAL_BASE_INR initial
        {
            "key": "CAPITAL_BASE_INR",
            "val_num": 4_000_000_000.00,
            "val_txt": None,
            "effective_from": "2026-04-01",
            "effective_to": "9999-12-31",
            "recorded_at": "2026-04-05 00:00:00",
            "note": "Initial eligible capital base (₹400 cr)",
        },
        # Mid-period capital base change effective 2026-09-01
        {
            "key": "CAPITAL_BASE_INR",
            "val_num": 4_200_000_000.00,
            "val_txt": None,
            "effective_from": "2026-09-01",
            "effective_to": "9999-12-31",
            "recorded_at": "2026-09-12 00:00:00",
            "note": "Mid-period capital base revision (₹420 cr)",
        },
        # Regulatory limits and CCFs
        {
            "key": "GROUP_LIMIT_PCT",
            "val_num": 25,
            "val_txt": None,
            "effective_from": "2026-04-01",
            "effective_to": "9999-12-31",
            "recorded_at": "2026-04-05 00:00:00",
            "note": "RBI group limit percentage (25%)",
        },
        {
            "key": "LE_LINE_PCT",
            "val_num": 10,
            "val_txt": None,
            "effective_from": "2026-04-01",
            "effective_to": "9999-12-31",
            "recorded_at": "2026-04-05 00:00:00",
            "note": "Large exposure reporting line (10%)",
        },
        {
            "key": "CCF_UNDRAWN",
            "val_num": 0.20,
            "val_txt": None,
            "effective_from": "2026-04-01",
            "effective_to": "9999-12-31",
            "recorded_at": "2026-04-05 00:00:00",
            "note": "CCF for undrawn commitments",
        },
        {
            "key": "CCF_GTE_FIN",
            "val_num": 1.00,
            "val_txt": None,
            "effective_from": "2026-04-01",
            "effective_to": "9999-12-31",
            "recorded_at": "2026-04-05 00:00:00",
            "note": "CCF for financial guarantees",
        },
        {
            "key": "CCF_GTE_PERF",
            "val_num": 0.50,
            "val_txt": None,
            "effective_from": "2026-04-01",
            "effective_to": "9999-12-31",
            "recorded_at": "2026-04-05 00:00:00",
            "note": "CCF for performance guarantees",
        },
        {
            "key": "CCF_COLLATERAL",
            "val_num": 0.00,
            "val_txt": None,
            "effective_from": "2026-04-01",
            "effective_to": "9999-12-31",
            "recorded_at": "2026-04-05 00:00:00",
            "note": "Collateral identity only (0 CCF)",
        },
        {
            "key": "JV_COUNT_IN_CONTROLLERS",
            "val_num": 1,
            "val_txt": None,
            "effective_from": "2026-04-01",
            "effective_to": "9999-12-31",
            "recorded_at": "2026-04-05 00:00:00",
            "note": "Attribute JV exposure to controlling parents",
        },
        {
            "key": "MAJORITY_MIN_PCT",
            "val_num": 50,
            "val_txt": None,
            "effective_from": "2026-04-01",
            "effective_to": "9999-12-31",
            "recorded_at": "2026-04-05 00:00:00",
            "note": "Majority control threshold (>50%)",
        },
        {
            "key": "INTERDEP_SHARE_MIN",
            "val_num": 50,
            "val_txt": None,
            "effective_from": "2026-04-01",
            "effective_to": "9999-12-31",
            "recorded_at": "2026-04-05 00:00:00",
            "note": "Credit interdependence minimum share (50%)",
        },
        {
            "key": "T0_SAMPLE_PCT",
            "val_num": 5,
            "val_txt": None,
            "effective_from": "2026-04-01",
            "effective_to": "9999-12-31",
            "recorded_at": "2026-04-05 00:00:00",
            "note": "Sample percentage for T0 record link batch",
        },
        {
            "key": "T0_SAMPLE_MIN",
            "val_num": 20,
            "val_txt": None,
            "effective_from": "2026-04-01",
            "effective_to": "9999-12-31",
            "recorded_at": "2026-04-05 00:00:00",
            "note": "Minimum sample size for T0 batch",
        },
        {
            "key": "OWN_SAMPLE_PCT",
            "val_num": 2,
            "val_txt": None,
            "effective_from": "2026-04-01",
            "effective_to": "9999-12-31",
            "recorded_at": "2026-04-05 00:00:00",
            "note": "Sample percentage for corroborated ownership batch",
        },
        {
            "key": "OWN_SAMPLE_MIN",
            "val_num": 20,
            "val_txt": None,
            "effective_from": "2026-04-01",
            "effective_to": "9999-12-31",
            "recorded_at": "2026-04-05 00:00:00",
            "note": "Minimum sample size for ownership batch",
        },
        {
            "key": "LP_MAX_PASSES",
            "val_num": 50,
            "val_txt": None,
            "effective_from": "2026-04-01",
            "effective_to": "9999-12-31",
            "recorded_at": "2026-04-05 00:00:00",
            "note": "Max label propagation passes",
        },
        {
            "key": "BLOCK_MAX",
            "val_num": 500,
            "val_txt": None,
            "effective_from": "2026-04-01",
            "effective_to": "9999-12-31",
            "recorded_at": "2026-04-05 00:00:00",
            "note": "Maximum block member count before dropping",
        },
    ]

    # Add matching thresholds
    for t_key, t_val in thresholds.items():
        initial_events.append(
            {
                "key": t_key,
                "val_num": float(t_val),
                "val_txt": None,
                "effective_from": "2026-04-01",
                "effective_to": "9999-12-31",
                "recorded_at": "2026-04-05 00:00:00",
                "note": f"Matching threshold {t_key}",
            }
        )

    # Read existing event_ids to avoid duplicates
    existing_stmt = conn.execute("SELECT event_id FROM GOV.POLICY_EVENT")
    existing_ids = {
        (r["event_id"] if isinstance(r, dict) else r[0])
        for r in existing_stmt.fetchall()
    }

    rows_inserted = 0
    insert_sql = """
    INSERT INTO GOV.POLICY_EVENT (
        event_id, policy_key, value_num, value_text,
        effective_from, effective_to, recorded_at, recorded_by, note
    ) VALUES (
        {event_id}, {policy_key}, {value_num}, {value_text},
        {effective_from}, {effective_to}, {recorded_at}, {recorded_by}, {note}
    )
    """

    for ev in initial_events:
        # Build deterministic event_id
        seed_str = f"{ev['key']}|{ev['effective_from']}|{ev['recorded_at']}"
        h = hashlib.sha256(seed_str.encode("utf-8")).hexdigest()[:12]
        event_id = f"PE-{ev['key'][:20]}-{h}"

        if event_id in existing_ids:
            continue

        conn.execute(
            insert_sql,
            query_params={
                "event_id": event_id,
                "policy_key": ev["key"],
                "value_num": ev["val_num"],
                "value_text": ev["val_txt"],
                "effective_from": ev["effective_from"],
                "effective_to": ev["effective_to"],
                "recorded_at": ev["recorded_at"],
                "recorded_by": "generator",
                "note": ev["note"],
            },
        )
        existing_ids.add(event_id)
        rows_inserted += 1

    return rows_inserted


def load(
    directory: str | Path,
    conn: ExaConnection | None = None,
    seed_policy: bool = True,
) -> dict[str, int]:
    """Load Parquet files from directory into Exasol tables.

    Connects as TALOS_LOADER if conn is None.
    Idempotent: deletes matching load_ids or truncates table before loading.
    Returns mapping of table_name -> row_count.
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"Target directory {directory} does not exist.")

    close_conn = False
    if conn is None:
        conn = connect("loader", autocommit=True)
        close_conn = True

    results: dict[str, int] = {}
    try:
        parquet_files = sorted(directory.rglob("*.parquet"))
        for file_path in parquet_files:
            table_name = resolve_target_table(file_path)
            if not table_name:
                continue

            parquet_file = pq.ParquetFile(file_path)
            schema_names = parquet_file.schema.names

            # Idempotency: avoid doubling rows on re-load
            if "load_id" in schema_names:
                table_pydict = pq.read_table(file_path, columns=["load_id"]).to_pydict()
                file_load_ids = set(table_pydict.get("load_id", []))
                for lid in file_load_ids:
                    conn.execute(
                        f"DELETE FROM {table_name} WHERE load_id = {{lid}}",
                        query_params={"lid": lid},
                    )
            else:
                conn.execute(f"TRUNCATE TABLE {table_name}")

            row_iter = _iter_parquet_tuples(file_path)
            conn.import_from_iterable(row_iter, table_name)

            # Count rows
            stmt = conn.execute(f"SELECT COUNT(*) FROM {table_name}")
            val = stmt.fetchval()
            results[table_name] = int(val) if val is not None else 0

        if seed_policy:
            seeded = seed_policy_events(conn)
            results["GOV.POLICY_EVENT"] = seeded

        return results
    finally:
        if close_conn:
            conn.close()
