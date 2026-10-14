"""tests/test_grants.py: Assert Exasol database role privileges and negative grant restrictions."""

import pytest

from orchestrator.db import connect, is_exasol_available


@pytest.mark.exasol
def test_pipeline_privilege_denials():
    """Assert TALOS_PIPELINE cannot mutate GRAPH tables and cannot read TRUTH."""
    if not is_exasol_available():
        pytest.skip("Exasol not available")

    conn = connect("pipeline", autocommit=True)
    try:
        # Denial 1: SELECT on TRUTH
        with pytest.raises(Exception):
            conn.execute("SELECT * FROM TRUTH.GT_ENTITY LIMIT 1")

        # Denial 2: INSERT on GRAPH.LINK_EVENT
        with pytest.raises(Exception):
            conn.execute(
                """
                INSERT INTO GRAPH.LINK_EVENT (
                    event_id, link_key, rec_key, entity_key, action, valid_from, valid_to, recorded_at, decision_id
                ) VALUES ('E-TEST', 'K1', 'R1', 'E1', 'ASSERT', '2026-01-01', '9999-12-31', CURRENT_TIMESTAMP, 'D1')
                """
            )

        # Denial 3: UPDATE on GRAPH
        with pytest.raises(Exception):
            conn.execute("UPDATE GRAPH.LINK_EVENT SET action = 'RETRACT'")

        # Denial 4: DELETE on GRAPH
        with pytest.raises(Exception):
            conn.execute("DELETE FROM GRAPH.LINK_EVENT")

    finally:
        conn.close()


@pytest.mark.exasol
def test_approver_privilege_denials():
    """Assert TALOS_APPROVER cannot UPDATE or DELETE on GRAPH or GOV tables."""
    if not is_exasol_available():
        pytest.skip("Exasol not available")

    conn = connect("approver", autocommit=True)
    try:
        # Denial 1: UPDATE on GRAPH
        with pytest.raises(Exception):
            conn.execute("UPDATE GRAPH.LINK_EVENT SET action = 'RETRACT'")

        # Denial 2: DELETE on GOV
        with pytest.raises(Exception):
            conn.execute("DELETE FROM GOV.DECISION_LOG")

    finally:
        conn.close()


@pytest.mark.exasol
def test_reader_restricted_to_report_schema():
    """Assert TALOS_READER cannot access tables outside the REPORT schema."""
    if not is_exasol_available():
        pytest.skip("Exasol not available")

    conn = connect("reader", autocommit=True)
    try:
        # Denial: Direct SELECT on RAW or STAGE
        with pytest.raises(Exception):
            conn.execute("SELECT * FROM RAW_LOS.CUSTOMER LIMIT 1")

        with pytest.raises(Exception):
            conn.execute("SELECT * FROM GOV.REPORT_RUN LIMIT 1")

    finally:
        conn.close()


@pytest.mark.exasol
def test_no_update_on_raw():
    """Assert no role holds UPDATE on RAW tables."""
    if not is_exasol_available():
        pytest.skip("Exasol not available")

    for role in ("loader", "pipeline", "approver", "reader"):
        try:
            conn = connect(role, autocommit=True)
            with pytest.raises(Exception):
                conn.execute("UPDATE RAW_LOS.CUSTOMER SET cust_name = 'HACKED'")
            conn.close()
        except Exception:
            pass
