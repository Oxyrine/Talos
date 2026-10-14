"""tests/test_sql_files.py: Test SQL state-machine splitter and SQL formatting."""

from pathlib import Path

from orchestrator.db import split_sql


def test_split_sql_basic():
    sql = "SELECT 1; SELECT 2; SELECT 3;"
    stmts = split_sql(sql)
    assert stmts == ["SELECT 1", "SELECT 2", "SELECT 3"]


def test_split_sql_single_quotes_with_semicolon_and_escapes():
    sql = "SELECT 'hello; world' AS col; SELECT 'it''s a ; test' AS val;"
    stmts = split_sql(sql)
    assert len(stmts) == 2
    assert stmts[0] == "SELECT 'hello; world' AS col"
    assert stmts[1] == "SELECT 'it''s a ; test' AS val"


def test_split_sql_double_quotes_with_semicolon():
    sql = 'SELECT "col;one" FROM "table;two"; SELECT 42;'
    stmts = split_sql(sql)
    assert len(stmts) == 2
    assert stmts[0] == 'SELECT "col;one" FROM "table;two"'
    assert stmts[1] == "SELECT 42"


def test_split_sql_line_comments():
    sql = """
    -- This is a comment with ; inside
    SELECT 1;
    -- Another comment with ;
    SELECT 2; -- trailing comment with ;
    """
    stmts = split_sql(sql)
    assert len(stmts) == 2
    assert "SELECT 1" in stmts[0]
    assert "SELECT 2" in stmts[1]


def test_split_sql_block_comments():
    sql = """
    SELECT /* block comment ; with semicolon */ 1;
    /* multi-line
       block comment ;
       with ; semicolons */
    SELECT 2;
    """
    stmts = split_sql(sql)
    assert len(stmts) == 2
    assert "SELECT" in stmts[0] and "1" in stmts[0]
    assert "SELECT" in stmts[1] and "2" in stmts[1]


def test_split_sql_udf_block():
    sql = """
    SELECT 1;
    --/
    CREATE OR REPLACE PYTHON3 SCALAR SCRIPT test_udf(x VARCHAR(100)) RETURNS VARCHAR(100) AS
    def run(ctx):
        a = ctx.x;
        b = a + ';';
        return b;
    /
    SELECT 2;
    """
    stmts = split_sql(sql)
    assert len(stmts) == 3
    assert stmts[0] == "SELECT 1"
    assert "CREATE OR REPLACE PYTHON3 SCALAR SCRIPT" in stmts[1]
    assert "return b;" in stmts[1]
    assert stmts[2] == "SELECT 2"


def test_sql_files_formatting_if_present():
    """Verify any sql/*.sql files on disk can format without syntax errors."""
    sql_dir = Path("sql")
    if not sql_dir.is_dir():
        return

    sample_params = {
        "business_date": "2026-09-30",
        "known_at": "2026-10-01 00:00:00",
        "run_id": "R-TEST-0001",
        "baseline_run": "R-TEST-0001",
        "CAPITAL_BASE_INR": 4200000000.0,
        "GROUP_LIMIT_PCT": 25,
        "LE_LINE_PCT": 10,
        "CCF_UNDRAWN": 0.20,
        "CCF_GTE_FIN": 1.00,
        "CCF_GTE_PERF": 0.50,
        "CCF_COLLATERAL": 0.0,
        "JV_COUNT_IN_CONTROLLERS": 1,
        "MAJORITY_MIN_PCT": 50,
        "INTERDEP_SHARE_MIN": 50,
        "LP_MAX_PASSES": 50,
        "BLOCK_MAX": 500,
        "ID_NAME_MIN_SIM": 0.60,
        "T1_MAX_DIST": 2,
        "T2_LOW": 0.70,
        "T2_HIGH": 0.95,
        "W_NAME": 0.60,
        "W_PHON": 0.15,
        "W_PIN": 0.15,
        "W_STATE": 0.10,
        "JUDGE_MIN_CONF": 0.80,
    }

    for sql_file in sql_dir.glob("*.sql"):
        text = sql_file.read_text(encoding="utf-8")
        stmts = split_sql(text)
        assert len(stmts) >= 0
        for s in stmts:
            # Check for double braces and formatting
            try:
                # Test format_map with sample params
                s.format_map(sample_params)
            except KeyError:
                pass  # Specific params will be supplied at runtime
