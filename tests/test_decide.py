"""tests/test_decide.py: Unit tests for decide, batch_decide, and rule safety checks."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from orchestrator.decide import (
    BatchProtectedError,
    ProposalConflictError,
    Reviewer,
    _record_batch_seed,
    batch_decide,
    decide,
    rule,
)


class MockStmt:
    def __init__(self, rows=None, val=None):
        self._rows = rows or []
        self._val = val

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def fetchval(self):
        return self._val


class MockConnection:
    def __init__(self):
        self.executed: list[tuple[str, dict[str, Any] | None]] = []
        self.committed = False
        self.rolled_back = False

    def execute(self, query: str, query_params: dict[str, Any] | None = None):
        normalized = " ".join(query.strip().split())
        self.executed.append((normalized, query_params))

        # 1. Terminal decision check
        if "FROM GOV.DECISION_COVERS c JOIN GOV.DECISION_LOG d" in normalized:
            # By default no terminal decision
            return MockStmt(rows=[])

        # 2. Batch failed check
        if "SELECT 1 FROM GOV.DECISION_LOG WHERE batch_id" in normalized:
            return MockStmt(rows=[])

        # 3. Entity exists check
        if "SELECT 1 FROM GRAPH.ENTITY WHERE entity_key" in normalized:
            return MockStmt(rows=[])

        # 4. Check active ASSERT
        if "SELECT entity_key FROM ( SELECT entity_key, action" in normalized:
            return MockStmt(rows=[])

        return MockStmt(rows=[])

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


REVIEWER = Reviewer(name="TEST_REVIEWER", role="APPROVER")


def test_decide_batch_protected_guard():
    """An individual proposal belonging to an active batch (e.g. B-OWN-...) cannot be decided individually."""
    conn = MockConnection()

    # Proposal query returns an ownership proposal with batch_id
    def mock_exec(query, query_params=None):
        normalized = " ".join(query.strip().split())
        conn.executed.append((normalized, query_params))
        if "FROM GOV.PROPOSAL" in normalized and "proposal_id" in (query_params or {}):
            return MockStmt(rows=[{
                "proposal_id": "P-001",
                "kind": "OWNERSHIP",
                "tier": "T0",
                "subject_key": "CONTROL:E:H1>E:H2",
                "rec_key": None,
                "entity_key": None,
                "holder_entity_key": "E:H1",
                "held_entity_key": "E:H2",
                "batch_id": "B-OWN-2026-001",
                "evidence_json": "{}",
                "evidence_hash": "hash123",
            }])
        if "FROM GOV.DECISION_COVERS" in normalized:
            return MockStmt(rows=[])
        if "SELECT 1 FROM GOV.DECISION_LOG WHERE batch_id" in normalized:
            return MockStmt(rows=[])
        return MockStmt(rows=[])

    conn.execute = mock_exec

    with pytest.raises(BatchProtectedError) as exc_info:
        decide(
            proposal_id="P-001",
            decision="APPROVE",
            reason="Individual approve attempt on batch member",
            reviewer=REVIEWER,
            business_date="2026-09-30",
            conn=conn,
        )
    assert "belongs to active batch B-OWN-2026-001" in str(exc_info.value)


def test_decide_missing_endpoints_raises():
    """OWNERSHIP proposals with missing endpoints must raise ValueError."""
    conn = MockConnection()

    def mock_exec(query, query_params=None):
        normalized = " ".join(query.strip().split())
        conn.executed.append((normalized, query_params))
        if "FROM GOV.PROPOSAL" in normalized:
            return MockStmt(rows=[{
                "proposal_id": "P-002",
                "kind": "OWNERSHIP",
                "tier": "T1",
                "subject_key": "CONTROL:E:H1>",
                "rec_key": None,
                "entity_key": None,
                "holder_entity_key": "E:H1",
                "held_entity_key": "",  # Empty held endpoint
                "batch_id": None,
                "evidence_json": "{}",
                "evidence_hash": "hash123",
            }])
        return MockStmt(rows=[])

    conn.execute = mock_exec

    with pytest.raises(ValueError) as exc_info:
        decide(
            proposal_id="P-002",
            decision="APPROVE",
            reason="Approve ownership",
            reviewer=REVIEWER,
            business_date="2026-09-30",
            conn=conn,
        )
    assert "missing required endpoints" in str(exc_info.value)


def test_decide_reads_real_stake_and_date():
    """Ownership event must read true stake_pct and effective_from from proposal evidence."""
    conn = MockConnection()

    ev_json = json.dumps({"stake_pct": 74.5, "effective_from": "2025-06-01"})

    def mock_exec(query, query_params=None):
        normalized = " ".join(query.strip().split())
        conn.executed.append((normalized, query_params))
        if "FROM GOV.PROPOSAL" in normalized:
            return MockStmt(rows=[{
                "proposal_id": "P-003",
                "kind": "OWNERSHIP",
                "tier": "T1",
                "subject_key": "CONTROL:E:H1>E:H2",
                "rec_key": None,
                "entity_key": None,
                "holder_entity_key": "E:H1",
                "held_entity_key": "E:H2",
                "batch_id": None,
                "evidence_json": ev_json,
                "evidence_hash": "hash789",
            }])
        return MockStmt(rows=[])

    conn.execute = mock_exec

    with patch("orchestrator.pipeline.publish_run") as mock_pub:
        mock_pub.return_value = MagicMock(run_id="R-TEST")
        decide(
            proposal_id="P-003",
            decision="APPROVE",
            reason="Valid ownership approval",
            reviewer=REVIEWER,
            business_date="2026-09-30",
            conn=conn,
        )

    # Find INSERT INTO GRAPH.OWNERSHIP_EVENT
    event_inserts = [
        (q, p) for q, p in conn.executed
        if "INSERT INTO GRAPH.OWNERSHIP_EVENT" in q
    ]
    assert len(event_inserts) == 1
    _, params = event_inserts[0]
    assert params["stake_pct"] == 74.5
    assert params["valid_from"] == "2025-06-01"
    assert params["holder_entity_key"] == "E:H1"
    assert params["held_entity_key"] == "E:H2"


def test_decide_missing_stake_raises():
    """OWNERSHIP proposals missing stake_pct must raise ValueError (no fallback to 100)."""
    conn = MockConnection()
    ev_json = json.dumps({"effective_from": "2025-06-01"})  # Missing stake_pct!

    def mock_exec(query, query_params=None):
        normalized = " ".join(query.strip().split())
        conn.executed.append((normalized, query_params))
        if "FROM GOV.PROPOSAL" in normalized:
            return MockStmt(rows=[{
                "proposal_id": "P-NO-STAKE",
                "kind": "OWNERSHIP",
                "tier": "T1",
                "subject_key": "CONTROL:E:H1>E:H2",
                "rec_key": None,
                "entity_key": None,
                "holder_entity_key": "E:H1",
                "held_entity_key": "E:H2",
                "batch_id": None,
                "evidence_json": ev_json,
                "evidence_hash": "hash789",
            }])
        return MockStmt(rows=[])

    conn.execute = mock_exec

    with pytest.raises(ValueError) as exc_info:
        decide(
            proposal_id="P-NO-STAKE",
            decision="APPROVE",
            reason="Valid ownership approval attempt",
            reviewer=REVIEWER,
            business_date="2026-09-30",
            conn=conn,
        )
    assert "missing required 'stake_pct'" in str(exc_info.value)


def test_decide_missing_effective_from_raises():
    """OWNERSHIP proposals missing effective_from must raise ValueError (no fallback to 0001-01-01)."""
    conn = MockConnection()
    ev_json = json.dumps({"stake_pct": 80.0})  # Missing effective_from!

    def mock_exec(query, query_params=None):
        normalized = " ".join(query.strip().split())
        conn.executed.append((normalized, query_params))
        if "FROM GOV.PROPOSAL" in normalized:
            return MockStmt(rows=[{
                "proposal_id": "P-NO-DATE",
                "kind": "OWNERSHIP",
                "tier": "T1",
                "subject_key": "CONTROL:E:H1>E:H2",
                "rec_key": None,
                "entity_key": None,
                "holder_entity_key": "E:H1",
                "held_entity_key": "E:H2",
                "batch_id": None,
                "evidence_json": ev_json,
                "evidence_hash": "hash789",
            }])
        return MockStmt(rows=[])

    conn.execute = mock_exec

    with pytest.raises(ValueError) as exc_info:
        decide(
            proposal_id="P-NO-DATE",
            decision="APPROVE",
            reason="Valid ownership approval attempt",
            reviewer=REVIEWER,
            business_date="2026-09-30",
            conn=conn,
        )
    assert "missing required 'effective_from'" in str(exc_info.value)


def test_decide_invalid_json_raises():
    """Proposals with corrupt evidence_json must raise ValueError."""
    conn = MockConnection()

    def mock_exec(query, query_params=None):
        normalized = " ".join(query.strip().split())
        conn.executed.append((normalized, query_params))
        if "FROM GOV.PROPOSAL" in normalized:
            return MockStmt(rows=[{
                "proposal_id": "P-CORRUPT",
                "kind": "OWNERSHIP",
                "tier": "T1",
                "subject_key": "CONTROL:E:H1>E:H2",
                "rec_key": None,
                "entity_key": None,
                "holder_entity_key": "E:H1",
                "held_entity_key": "E:H2",
                "batch_id": None,
                "evidence_json": "{not valid json",
                "evidence_hash": "hash789",
            }])
        return MockStmt(rows=[])

    conn.execute = mock_exec

    with pytest.raises(ValueError) as exc_info:
        decide(
            proposal_id="P-CORRUPT",
            decision="APPROVE",
            reason="Approval attempt with bad json",
            reviewer=REVIEWER,
            business_date="2026-09-30",
            conn=conn,
        )
    assert "evidence_json is invalid JSON" in str(exc_info.value)


def test_batch_decide_empty_verdicts_rejected():
    """batch_decide with verdicts={} must raise ValueError and NOT approve the batch."""
    conn = MockConnection()

    proposals = [
        {"proposal_id": f"P-{i:03d}", "kind": "RECORD_LINK", "subject_key": f"R{i}>E{i}",
         "rec_key": f"R{i}", "entity_key": f"E{i}", "holder_entity_key": None,
         "held_entity_key": None, "evidence_json": "{}", "evidence_hash": "h"}
        for i in range(5)
    ]

    def mock_exec(query, query_params=None):
        normalized = " ".join(query.strip().split())
        conn.executed.append((normalized, query_params))
        if "FROM GOV.PROPOSAL" in normalized and "batch_id" in (query_params or {}):
            return MockStmt(rows=proposals)
        return MockStmt(rows=[])

    conn.execute = mock_exec

    with patch("orchestrator.decide.policy_in_force") as mock_pif:
        mock_pif.return_value = ({"T0_SAMPLE_PCT": 20, "T0_SAMPLE_MIN": 2}, {})
        with pytest.raises(ValueError) as exc_info:
            batch_decide(
                batch_id="B-REC-001",
                seed=42,
                verdicts={},  # Empty verdicts!
                reason="Attempting empty verdicts approval",
                reviewer=REVIEWER,
                business_date="2026-09-30",
                conn=conn,
            )
    assert "do not match expected sample IDs" in str(exc_info.value)


def test_batch_decide_made_up_id_rejected():
    """batch_decide with made-up IDs must raise ValueError."""
    conn = MockConnection()

    proposals = [
        {"proposal_id": f"P-{i:03d}", "kind": "RECORD_LINK", "subject_key": f"R{i}>E{i}",
         "rec_key": f"R{i}", "entity_key": f"E{i}", "holder_entity_key": None,
         "held_entity_key": None, "evidence_json": "{}", "evidence_hash": "h"}
        for i in range(5)
    ]

    def mock_exec(query, query_params=None):
        normalized = " ".join(query.strip().split())
        conn.executed.append((normalized, query_params))
        if "FROM GOV.PROPOSAL" in normalized and "batch_id" in (query_params or {}):
            return MockStmt(rows=proposals)
        return MockStmt(rows=[])

    conn.execute = mock_exec

    with patch("orchestrator.decide.policy_in_force") as mock_pif:
        mock_pif.return_value = ({"T0_SAMPLE_PCT": 20, "T0_SAMPLE_MIN": 2}, {})
        with pytest.raises(ValueError) as exc_info:
            batch_decide(
                batch_id="B-REC-001",
                seed=42,
                verdicts={"P-MADE-UP": True, "P-FAKE-2": True},
                reason="Attempting made-up IDs approval",
                reviewer=REVIEWER,
                business_date="2026-09-30",
                conn=conn,
            )
    assert "do not match expected sample IDs" in str(exc_info.value)


def test_batch_decide_single_insert_covers_no_update():
    """batch_decide executes a single INSERT INTO GOV.DECISION_COVERS with CASE WHEN and zero UPDATEs."""
    conn = MockConnection()

    proposals = [
        {"proposal_id": f"P-{i:03d}", "kind": "RECORD_LINK", "subject_key": f"R{i}>E{i}",
         "rec_key": f"R{i}", "entity_key": f"E{i}", "holder_entity_key": None,
         "held_entity_key": None, "evidence_json": "{}", "evidence_hash": "h"}
        for i in range(5)
    ]

    def mock_exec(query, query_params=None):
        normalized = " ".join(query.strip().split())
        conn.executed.append((normalized, query_params))
        if "FROM GOV.PROPOSAL" in normalized and "batch_id" in (query_params or {}):
            return MockStmt(rows=proposals)
        return MockStmt(rows=[])

    conn.execute = mock_exec

    # Set up seed and expected sample: with seed=42, sample size is 2
    import random
    rng = random.Random(42)
    sampled = set(rng.sample([p["proposal_id"] for p in proposals], 2))
    verdicts = {pid: True for pid in sampled}

    with patch("orchestrator.decide.policy_in_force") as mock_pif, \
         patch("orchestrator.pipeline.publish_run") as mock_pub:
        mock_pif.return_value = ({"T0_SAMPLE_PCT": 20, "T0_SAMPLE_MIN": 2}, {})
        mock_pub.return_value = MagicMock(run_id="R-TEST")

        batch_decide(
            batch_id="B-REC-COVERS",
            seed=42,
            verdicts=verdicts,
            reason="Approval with single append-only covers insert",
            reviewer=REVIEWER,
            business_date="2026-09-30",
            conn=conn,
        )

    # Verify no UPDATE on GOV.DECISION_COVERS
    update_stmts = [q for q, _ in conn.executed if "UPDATE GOV.DECISION_COVERS" in q]
    assert len(update_stmts) == 0, f"Expected 0 UPDATEs on GOV.DECISION_COVERS, found: {update_stmts}"

    # Verify single INSERT into GOV.DECISION_COVERS with CASE WHEN
    covers_inserts = [q for q, _ in conn.executed if "INSERT INTO GOV.DECISION_COVERS" in q]
    assert len(covers_inserts) == 1
    assert "CASE WHEN p.proposal_id IN" in covers_inserts[0]


def test_batch_decide_seed_mismatch_rejected():
    """batch_decide rejects a seed that differs from the one recorded by batch_sample."""
    conn = MockConnection()
    _record_batch_seed("B-REC-SEED-CHECK", 12345)

    with pytest.raises(ValueError) as exc_info:
        batch_decide(
            batch_id="B-REC-SEED-CHECK",
            seed=99999,  # Mismatched seed!
            verdicts={},
            reason="Seed mismatch attempt",
            reviewer=REVIEWER,
            business_date="2026-09-30",
            conn=conn,
        )
    assert "does not match active sample seed 12345" in str(exc_info.value)


def test_rule_wrong_proposal_kind():
    """rule() on a non-CONTROL_RULING proposal must raise ValueError."""
    conn = MockConnection()

    def mock_exec(query, query_params=None):
        normalized = " ".join(query.strip().split())
        conn.executed.append((normalized, query_params))
        if "FROM GOV.PROPOSAL" in normalized:
            return MockStmt(rows=[{
                "proposal_id": "P-RL-01",
                "kind": "RECORD_LINK",
                "held_entity_key": "E:HELD",
                "evidence_json": "{}",
                "evidence_hash": "h123",
            }])
        return MockStmt(rows=[])

    conn.execute = mock_exec

    with pytest.raises(ValueError) as exc_info:
        rule(
            proposal_id="P-RL-01",
            ruling="SINGLE",
            controller="E:CTRL",
            reason="Rule on record link",
            reviewer=REVIEWER,
            business_date="2026-09-30",
            conn=conn,
        )
    assert "is of kind 'RECORD_LINK', not 'CONTROL_RULING'" in str(exc_info.value)


def test_rule_single_requires_controller_in_holders():
    """SINGLE ruling requires controller to be one of the declared holders."""
    conn = MockConnection()

    ev_json = json.dumps({
        "holders": ["E:HOLDER_A", "E:HOLDER_B"],
        "effective_from": "2026-01-01",
        "stakes": {"E:HOLDER_A": 50.0, "E:HOLDER_B": 50.0},
    })

    def mock_exec(query, query_params=None):
        normalized = " ".join(query.strip().split())
        conn.executed.append((normalized, query_params))
        if "FROM GOV.PROPOSAL" in normalized:
            return MockStmt(rows=[{
                "proposal_id": "P-JV-01",
                "kind": "CONTROL_RULING",
                "held_entity_key": "E:JV_CORP",
                "evidence_json": ev_json,
                "evidence_hash": "h123",
            }])
        return MockStmt(rows=[])

    conn.execute = mock_exec

    with pytest.raises(ValueError) as exc_info:
        rule(
            proposal_id="P-JV-01",
            ruling="SINGLE",
            controller="E:STRANGER",
            reason="Rule controller not in holders",
            reviewer=REVIEWER,
            business_date="2026-09-30",
            conn=conn,
        )
    assert "is not one of the declared holders" in str(exc_info.value)


def test_rule_missing_stake_raises():
    """rule() raises ValueError if any declared holder lacks stake in evidence."""
    conn = MockConnection()

    ev_json = json.dumps({
        "holders": ["E:H1", "E:H2"],
        "effective_from": "2026-01-01",
        # Missing stake_pct or stakes mapping!
    })

    def mock_exec(query, query_params=None):
        normalized = " ".join(query.strip().split())
        conn.executed.append((normalized, query_params))
        if "FROM GOV.PROPOSAL" in normalized:
            return MockStmt(rows=[{
                "proposal_id": "P-JV-NOSTAKE",
                "kind": "CONTROL_RULING",
                "held_entity_key": "E:JV_CORP",
                "evidence_json": ev_json,
                "evidence_hash": "h123",
            }])
        return MockStmt(rows=[])

    conn.execute = mock_exec

    with pytest.raises(ValueError) as exc_info:
        rule(
            proposal_id="P-JV-NOSTAKE",
            ruling="JOINT",
            controller=None,
            reason="Joint ruling attempt without stakes",
            reviewer=REVIEWER,
            business_date="2026-09-30",
            conn=conn,
        )
    assert "missing required 'stake_pct'" in str(exc_info.value)


def test_rule_reads_stake_from_evidence():
    """rule() writes each holder's actual stake from evidence rather than hardcoded 100/50/0."""
    conn = MockConnection()

    ev_json = json.dumps({
        "holders": ["E:H1", "E:H2"],
        "effective_from": "2026-01-01",
        "stakes": {"E:H1": 60.0, "E:H2": 40.0},
    })

    def mock_exec(query, query_params=None):
        normalized = " ".join(query.strip().split())
        conn.executed.append((normalized, query_params))
        if "FROM GOV.PROPOSAL" in normalized:
            return MockStmt(rows=[{
                "proposal_id": "P-JV-REALSTAKE",
                "kind": "CONTROL_RULING",
                "held_entity_key": "E:JV_CORP",
                "evidence_json": ev_json,
                "evidence_hash": "h123",
            }])
        return MockStmt(rows=[])

    conn.execute = mock_exec

    with patch("orchestrator.pipeline.publish_run") as mock_pub:
        mock_pub.return_value = MagicMock(run_id="R-TEST")
        rule(
            proposal_id="P-JV-REALSTAKE",
            ruling="SINGLE",
            controller="E:H1",
            reason="Controller has majority share",
            reviewer=REVIEWER,
            business_date="2026-09-30",
            conn=conn,
        )

    ownership_inserts = [
        (q, p) for q, p in conn.executed
        if "INSERT INTO GRAPH.OWNERSHIP_EVENT" in q
    ]
    assert len(ownership_inserts) == 2
    # First holder E:H1 has 60.0 stake
    assert ownership_inserts[0][1]["holder_entity_key"] == "E:H1"
    assert ownership_inserts[0][1]["stake_pct"] == 60.0
    # Second holder E:H2 has 40.0 stake
    assert ownership_inserts[1][1]["holder_entity_key"] == "E:H2"
    assert ownership_inserts[1][1]["stake_pct"] == 40.0


def test_rule_connected_short_reason_raises():
    """CONNECTED ruling requires at least 20 chars of evidence text."""
    conn = MockConnection()
    with pytest.raises(ValueError) as exc_info:
        rule(
            proposal_id="P-JV-01",
            ruling="CONNECTED",
            controller=None,
            reason="Too short",  # < 20 chars
            reviewer=REVIEWER,
            business_date="2026-09-30",
            conn=conn,
        )
    assert "at least 20 characters" in str(exc_info.value)


def test_rule_connected_inserts_proposal_via_pipeline():
    """CONNECTED ruling files CONTROLLER_LINK proposal via pipeline role and respects edge kind."""
    conn = MockConnection()
    pipeline_conn = MockConnection()

    ev_json = json.dumps({
        "holders": ["E:H1", "E:H2"],
        "effective_from": "2026-01-01",
        "stake_pct": 50.0,
    })

    def mock_exec(query, query_params=None):
        normalized = " ".join(query.strip().split())
        conn.executed.append((normalized, query_params))
        if "FROM GOV.PROPOSAL" in normalized:
            return MockStmt(rows=[{
                "proposal_id": "P-JV-02",
                "kind": "CONTROL_RULING",
                "held_entity_key": "E:JV_TARGET",
                "evidence_json": ev_json,
                "evidence_hash": "h999",
            }])
        return MockStmt(rows=[])

    conn.execute = mock_exec

    with patch("orchestrator.decide.connect") as mock_connect, \
         patch("orchestrator.pipeline.publish_run") as mock_pub:
        mock_connect.return_value = pipeline_conn
        mock_pub.return_value = MagicMock(run_id="R-TEST")

        rule(
            proposal_id="P-JV-02",
            ruling="CONNECTED",
            controller=None,
            reason="Extensive evidence of common family management and financial control.",
            reviewer=REVIEWER,
            business_date="2026-09-30",
            connected_edge_kind="INTERDEP",
            conn=conn,
        )

    # Check mock_connect was called with "pipeline"
    mock_connect.assert_called_with("pipeline", autocommit=True)

    # Check pipeline_conn executed INSERT INTO GOV.PROPOSAL
    prop_inserts = [
        (q, p) for q, p in pipeline_conn.executed
        if "INSERT INTO GOV.PROPOSAL" in q
    ]
    assert len(prop_inserts) == 1
    _, params = prop_inserts[0]
    assert params["subject_key"] == "INTERDEP:E:H1>E:H2"
    assert "INTERDEP" in params["evidence_json"]


def test_decide_already_has_terminal_decision():
    """decide() raises ProposalConflictError when proposal already has an APPROVE/REJECT decision."""
    conn = MockConnection()

    def mock_exec(query, query_params=None):
        normalized = " ".join(query.strip().split())
        conn.executed.append((normalized, query_params))
        if "FROM GOV.PROPOSAL" in normalized:
            return MockStmt(rows=[{
                "proposal_id": "P-TERM-01",
                "kind": "RECORD_LINK",
                "tier": "T1",
                "subject_key": "R1>E1",
                "rec_key": "R1",
                "entity_key": "E1",
                "holder_entity_key": None,
                "held_entity_key": None,
                "batch_id": None,
                "evidence_json": "{}",
                "evidence_hash": "h",
            }])
        if "FROM GOV.DECISION_COVERS" in normalized:
            return MockStmt(rows=[{"decision": "APPROVE"}])
        return MockStmt(rows=[])

    conn.execute = mock_exec

    with pytest.raises(ProposalConflictError) as exc_info:
        decide(
            proposal_id="P-TERM-01",
            decision="APPROVE",
            reason="Duplicate decide attempt",
            reviewer=REVIEWER,
            business_date="2026-09-30",
            conn=conn,
        )
    assert "already has a terminal decision" in str(exc_info.value)


def test_rule_already_has_terminal_ruling():
    """rule() raises ProposalConflictError when proposal already has a terminal decision."""
    conn = MockConnection()

    def mock_exec(query, query_params=None):
        normalized = " ".join(query.strip().split())
        conn.executed.append((normalized, query_params))
        if "FROM GOV.PROPOSAL" in normalized:
            return MockStmt(rows=[{
                "proposal_id": "P-JV-TERM",
                "kind": "CONTROL_RULING",
                "held_entity_key": "E:HELD",
                "evidence_json": json.dumps({"holders": ["E:H1", "E:H2"], "effective_from": "2026-01-01", "stake_pct": 50.0}),
                "evidence_hash": "h",
            }])
        if "FROM GOV.DECISION_COVERS" in normalized:
            return MockStmt(rows=[{"decision": "RULING"}])
        return MockStmt(rows=[])

    conn.execute = mock_exec

    with pytest.raises(ProposalConflictError) as exc_info:
        rule(
            proposal_id="P-JV-TERM",
            ruling="SINGLE",
            controller="E:H1",
            reason="Duplicate ruling attempt",
            reviewer=REVIEWER,
            business_date="2026-09-30",
            conn=conn,
        )
    assert "already has a terminal decision" in str(exc_info.value)
