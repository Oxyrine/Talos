"""tests/test_evidence_json_db.py: the JSON-escaping expression used in proposal evidence, run on Exasol."""

from __future__ import annotations

import json
import re

import pytest

from orchestrator.db import REPO_ROOT, connect, is_exasol_available

pytestmark = pytest.mark.exasol

BACKSLASH = chr(92)
NASTY = 'KOCHI "WEST"' + BACKSLASH + 'ward' + chr(10) + 'line' + chr(9) + 'tab'


def _escape_expressions() -> set[str]:
    exprs: set[str] = set()
    for name in ("70_propose_record_links.sql", "71_propose_edges.sql"):
        text = (REPO_ROOT / "sql" / name).read_text(encoding="utf-8")
        exprs |= set(re.findall(r"REPLACE\(REPLACE\(REGEXP_REPLACE\(COALESCE\((.+?), ''\).*?'\\\"'\)", text))
    return exprs


def test_every_escape_wraps_one_column():
    assert len(_escape_expressions()) >= 15


def test_escape_expression_yields_valid_json():
    if not is_exasol_available():
        pytest.skip("Exasol not available")
    text = (REPO_ROOT / "sql" / "70_propose_record_links.sql").read_text(encoding="utf-8")
    m = re.search(r"REPLACE\(REPLACE\(REGEXP_REPLACE\(COALESCE\(a\.city, ''\).*?'\\\"'\)", text)
    assert m, "escape expression for a.city not found"
    expr = m.group(0).replace("a.city", "x")
    conn = connect("sys", autocommit=True)
    try:
        # Braces are doubled because pyexasol formats the statement with query_params.
        sql = "SELECT '{{\"v\":\"' || " + expr + " || '\"}}' AS j FROM (SELECT {x} AS x FROM DUAL)"
        doc = conn.execute(sql, query_params={"x": NASTY}).fetchval()
    finally:
        conn.close()
    assert json.loads(doc)["v"] == 'KOCHI "WEST"' + BACKSLASH + 'ward line tab'
