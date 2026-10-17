"""tests/test_grants.py: Assert Exasol database role privileges, positive controls, and negative grant restrictions."""

import pytest

from orchestrator.db import connect, is_exasol_available


def _assert_tables_exist(table_names: list[str]) -> bool:
    """Check with sys whether target tables are present in the test database."""
    try:
        conn = connect("sys", autocommit=True)
    except Exception:
        return False
    try:
        for tbl in table_names:
            conn.execute(f"SELECT 1 FROM {tbl} LIMIT 1")
        return True
    except Exception:
        return False
    finally:
        conn.close()


def _assert_privilege_denied(callable_query, expected_table: str):
    """Assert that execution fails specifically due to insufficient privileges, not a missing table."""
    try:
        callable_query()
        pytest.fail(f"Query succeeded unexpectedly; privilege was not denied on {expected_table}.")
    except Exception as e:
        msg = str(e).lower()
        if "not found" in msg or "does not exist" in msg:
            pytest.fail(f"Test failed vacuously: {expected_table} was not found on database: {e}")
        assert any(
            term in msg
            for term in ("privilege", "authorization", "denied", "access", "permission", "not allowed", "read-only")
        ), f"Expected privilege denial on {expected_table}, but got unexpected error: {e}"


@pytest.mark.exasol
def test_pipeline_privilege_denials():
    """Assert TALOS_PIPELINE has positive access to RAW/STAGE but cannot mutate GRAPH or read TRUTH."""
    if not is_exasol_available():
        pytest.skip("Exasol not available")

    required = ["RAW_LOS.CUSTOMER", "TRUTH.GT_ENTITY", "GRAPH.LINK_EVENT"]
    if not _assert_tables_exist(required):
        pytest.skip(f"Required tables {required} not initialized in database")

    conn = connect("pipeline", autocommit=True)
    try:
        # Positive control: PIPELINE can read RAW_LOS.CUSTOMER
        conn.execute("SELECT COUNT(*) FROM RAW_LOS.CUSTOMER")

        # Negative control 1: SELECT on TRUTH
        _assert_privilege_denied(
            lambda: conn.execute("SELECT * FROM TRUTH.GT_ENTITY LIMIT 1"),
            "TRUTH.GT_ENTITY",
        )

        # Negative control 2: INSERT on GRAPH.LINK_EVENT
        _assert_privilege_denied(
            lambda: conn.execute(
                """
                INSERT INTO GRAPH.LINK_EVENT (
                    event_id, link_key, rec_key, entity_key, "ACTION", valid_from, valid_to, recorded_at, decision_id
                ) VALUES ('E-TEST', 'K1', 'R1', 'E1', 'ASSERT', '2026-01-01', '9999-12-31', CURRENT_TIMESTAMP, 'D1')
                """
            ),
            "GRAPH.LINK_EVENT",
        )

        # Negative control 3: UPDATE on GRAPH
        _assert_privilege_denied(
            lambda: conn.execute("""UPDATE GRAPH.LINK_EVENT SET "ACTION" = 'RETRACT'"""),
            "GRAPH.LINK_EVENT",
        )

        # Negative control 4: DELETE on GRAPH
        _assert_privilege_denied(
            lambda: conn.execute("DELETE FROM GRAPH.LINK_EVENT"),
            "GRAPH.LINK_EVENT",
        )

    finally:
        conn.close()


@pytest.mark.exasol
def test_approver_privilege_denials():
    """Assert TALOS_APPROVER has positive access to GOV.PROPOSAL but cannot UPDATE or DELETE GRAPH/GOV tables."""
    if not is_exasol_available():
        pytest.skip("Exasol not available")

    required = ["GOV.PROPOSAL", "GRAPH.LINK_EVENT", "GOV.DECISION_LOG"]
    if not _assert_tables_exist(required):
        pytest.skip(f"Required tables {required} not initialized in database")

    conn = connect("approver", autocommit=True)
    try:
        # Positive control: APPROVER can read GOV.PROPOSAL
        conn.execute("SELECT COUNT(*) FROM GOV.PROPOSAL")

        # Negative control 1: UPDATE on GRAPH
        _assert_privilege_denied(
            lambda: conn.execute("""UPDATE GRAPH.LINK_EVENT SET "ACTION" = 'RETRACT'"""),
            "GRAPH.LINK_EVENT",
        )

        # Negative control 2: DELETE on GOV
        _assert_privilege_denied(
            lambda: conn.execute("DELETE FROM GOV.DECISION_LOG"),
            "GOV.DECISION_LOG",
        )

    finally:
        conn.close()


@pytest.mark.exasol
def test_reader_restricted_to_report_schema():
    """Assert TALOS_READER can read REPORT views but cannot access RAW or GOV tables."""
    if not is_exasol_available():
        pytest.skip("Exasol not available")

    required = ["REPORT.V_DECISION_AUDIT_LOG", "RAW_LOS.CUSTOMER", "GOV.REPORT_RUN"]
    if not _assert_tables_exist(required):
        pytest.skip(f"Required tables {required} not initialized in database")

    conn = connect("reader", autocommit=True)
    try:
        # Positive control: READER can access REPORT views
        conn.execute("SELECT COUNT(*) FROM REPORT.V_DECISION_AUDIT_LOG")

        # Negative control 1: SELECT on RAW
        _assert_privilege_denied(
            lambda: conn.execute("SELECT * FROM RAW_LOS.CUSTOMER LIMIT 1"),
            "RAW_LOS.CUSTOMER",
        )

        # Negative control 2: SELECT on GOV
        _assert_privilege_denied(
            lambda: conn.execute("SELECT * FROM GOV.REPORT_RUN LIMIT 1"),
            "GOV.REPORT_RUN",
        )

    finally:
        conn.close()


@pytest.mark.exasol
def test_no_update_on_raw():
    """Assert no role holds UPDATE on RAW tables, with positive SELECT control."""
    if not is_exasol_available():
        pytest.skip("Exasol not available")

    required = ["RAW_LOS.CUSTOMER"]
    if not _assert_tables_exist(required):
        pytest.skip(f"Required tables {required} not initialized in database")

    for role in ("loader", "pipeline", "approver", "reader", "eval"):
        conn = connect(role, autocommit=True)
        try:
            # Positive control where the role may read RAW_LOS (approver and reader may not)
            if role in ("loader", "pipeline", "eval"):
                conn.execute("SELECT COUNT(*) FROM RAW_LOS.CUSTOMER")

            # Negative control: UPDATE is denied
            _assert_privilege_denied(
                lambda: conn.execute("UPDATE RAW_LOS.CUSTOMER SET cust_name = 'HACKED'"),
                "RAW_LOS.CUSTOMER",
            )
        finally:
            conn.close()
