"""orchestrator/loader.py: Ingest Parquet datasets into Exasol RAW, STAGE, and TRUTH schemas."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from pyexasol import ExaConnection

from orchestrator.db import connect, transaction
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


def _sql_literal(value: Any) -> str:
    """Render one Python value as an Exasol SQL literal.

    Raises ValueError for NaN or infinite numbers and TypeError for types with no safe
    literal (bytes, lists, ...), rather than emitting SQL that fails or stores the wrong value.
    Timezone-aware datetimes are converted to UTC, matching how known_at is compared.
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"cannot load non-finite number {value!r}")
        return repr(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError(f"cannot load non-finite number {value!r}")
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        return "'" + value.strftime("%Y-%m-%d %H:%M:%S.%f") + "'"
    if isinstance(value, date):
        return "'" + value.isoformat() + "'"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    raise TypeError(f"cannot load a {type(value).__name__} value as a SQL literal")


def insert_rows(conn: ExaConnection, table_name: str, columns: list[str], rows: Iterable[tuple], chunk: int = 2000) -> int:
    """Append rows with chunked multi-row INSERT ... VALUES.

    pyexasol's import_from_iterable opens an HTTP tunnel that hangs against Exasol Nano in
    Docker Desktop on Windows (docs/PROBE.md, probe 10), so the loader uses plain SQL.
    No query_params are passed, so pyexasol does not reformat the literals.
    """
    head = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES "
    batch: list[str] = []
    total = 0
    for row in rows:
        batch.append("(" + ", ".join(_sql_literal(v) for v in row) + ")")
        if len(batch) >= chunk:
            conn.execute(head + ", ".join(batch))
            total += len(batch)
            batch = []
    if batch:
        conn.execute(head + ", ".join(batch))
        total += len(batch)
    return total


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
    Idempotent: a file whose load_ids are already present is skipped; tables without a
    load_id are replaced. Each file is loaded in one transaction (all rows or none).
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

            # Idempotency without deleting evidence: raw tables are append-only (no role holds
            # DELETE on RAW_*), so a load_id that is already present is skipped, not replaced.
            # Each file loads in one transaction, so a present load_id is always a complete load.
            # Tables without a load_id (TRUTH, STAGE.PINCODE_DISTRICT) are replaced whole.
            if "load_id" in schema_names:
                table_pydict = pq.read_table(file_path, columns=["load_id"]).to_pydict()
                file_load_ids = sorted(set(table_pydict.get("load_id", [])))
                present = {
                    r["load_id"]
                    for r in conn.execute(f"SELECT DISTINCT load_id FROM {table_name}").fetchall()
                }
                if present.intersection(file_load_ids):
                    if not present.issuperset(file_load_ids):
                        raise ValueError(
                            f"{file_path.name}: loads {sorted(present.intersection(file_load_ids))} are already in "
                            f"{table_name} but others are not; refusing a partial re-load (run talos reset)."
                        )
                    results[table_name] = int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchval() or 0)
                    continue
            with transaction(conn):
                if "load_id" not in schema_names:
                    conn.execute(f"TRUNCATE TABLE {table_name}")
                try:
                    insert_rows(conn, table_name, list(schema_names), _iter_parquet_tuples(file_path))
                except (TypeError, ValueError) as e:
                    raise ValueError(f"{file_path.name}: {e}") from e

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
