"""tests/test_loader_db.py: a raw file loads completely or not at all, against a live Exasol."""

from __future__ import annotations

import functools
import uuid
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from orchestrator.db import connect, is_exasol_available

pytestmark = pytest.mark.exasol


def _customer_file(tmp_path: Path, load_id: str, bad_last_row: bool) -> Path:
    """A RAW_LOS.CUSTOMER parquet with 12 rows of one load; optionally the last row cannot be inserted."""
    from data.generator.generate import generate

    gen_dir = tmp_path / "gen"
    generate(profile="tiny", out_dir=str(gen_dir), scale=0.2)
    src = next(p for p in gen_dir.rglob("*.parquet") if p.stem.lower() in ("customer", "los_customer"))
    table = pq.read_table(src).slice(0, 12)
    table = table.set_column(table.schema.get_field_index("load_id"), "load_id", pa.array([load_id] * 12))
    if bad_last_row:
        ids = table.column("cust_id").to_pylist()
        ids[-1] = "X" * 5000  # longer than the cust_id column: the final INSERT chunk fails
        table = table.set_column(table.schema.get_field_index("cust_id"), "cust_id", pa.array(ids))
    out = tmp_path / ("bad" if bad_last_row else "good") / src.relative_to(gen_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out)
    return out.parents[len(src.relative_to(gen_dir).parts) - 1]


def _count(load_id: str) -> int:
    conn = connect("loader")
    try:
        return int(conn.execute("SELECT COUNT(*) FROM RAW_LOS.CUSTOMER WHERE load_id = {l}",
                                query_params={"l": load_id}).fetchval())
    finally:
        conn.close()


def test_failed_file_load_leaves_nothing_and_reload_is_complete(tmp_path, monkeypatch):
    if not is_exasol_available():
        pytest.skip("Exasol not available")
    import orchestrator.loader as loader

    # Small chunks, so the file takes several INSERT statements and the bad row is in a later one.
    monkeypatch.setattr(loader, "insert_rows", functools.partial(loader.insert_rows, chunk=5))
    load_id = "TEST-ATOMIC-" + uuid.uuid4().hex[:8]

    with pytest.raises(Exception):
        loader.load(_customer_file(tmp_path, load_id, bad_last_row=True), seed_policy=False)
    assert _count(load_id) == 0, "a failed file must not leave a partial load behind"

    loader.load(_customer_file(tmp_path, load_id, bad_last_row=False), seed_policy=False)
    assert _count(load_id) == 12
