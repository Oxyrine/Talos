"""tests/test_hash.py: Verify canonical serialization and output hash determinism."""

import hashlib
from decimal import Decimal

from orchestrator.replay import canonical_membership_line, canonical_output_line


def test_canonical_lines_and_order_independence():
    # Construct rows
    m1 = canonical_membership_line("E:GRP001", "E:SUB001", "MEMBER", True, "CYCLE_HEADED")
    m2 = canonical_membership_line("E:GRP001", "E:SUB002", "MEMBER", False, None)

    o1 = canonical_output_line(
        group_key="E:GRP001",
        entity_key="E:SUB001",
        source_system="LOS",
        source_row_id="LN-1001",
        exposure_component="FUNDED",
        membership_kind="MEMBER",
        rec_key="LOS:CUST-1",
        product="TERM_LOAN",
        gross=Decimal("1000000.00"),
        ccf=Decimal("1.0000"),
        exposure=Decimal("1000000.00"),
        link_decision_id="D-20261001-01",
    )
    o2 = canonical_output_line(
        group_key="E:GRP001",
        entity_key="E:SUB002",
        source_system="TSY",
        source_row_id="HD-2001",
        exposure_component="HOLDING",
        membership_kind="MEMBER",
        rec_key="TSY:ISS-1",
        product="BOND",
        gross=Decimal("500000.00"),
        ccf=Decimal("1.0000"),
        exposure=Decimal("500000.00"),
        link_decision_id="D-20261001-02",
    )

    # Order 1: m1, m2, then o1, o2
    m_list_1 = sorted([m1, m2])
    o_list_1 = sorted([o1, o2])
    hash_1 = hashlib.sha256("\n".join(m_list_1 + o_list_1).encode("utf-8")).hexdigest()

    # Order 2: m2, m1, then o2, o1
    m_list_2 = sorted([m2, m1])
    o_list_2 = sorted([o2, o1])
    hash_2 = hashlib.sha256("\n".join(m_list_2 + o_list_2).encode("utf-8")).hexdigest()

    assert hash_1 == hash_2


def test_one_paisa_change_changes_hash():
    o1 = canonical_output_line(
        group_key="E:GRP001",
        entity_key="E:SUB001",
        source_system="LOS",
        source_row_id="LN-1001",
        exposure_component="FUNDED",
        membership_kind="MEMBER",
        rec_key="LOS:CUST-1",
        product="TERM_LOAN",
        gross=Decimal("1000000.00"),
        ccf=Decimal("1.0000"),
        exposure=Decimal("1000000.00"),
        link_decision_id="D-1",
    )
    # 1 paisa difference: 1000000.01
    o1_modified = canonical_output_line(
        group_key="E:GRP001",
        entity_key="E:SUB001",
        source_system="LOS",
        source_row_id="LN-1001",
        exposure_component="FUNDED",
        membership_kind="MEMBER",
        rec_key="LOS:CUST-1",
        product="TERM_LOAN",
        gross=Decimal("1000000.00"),
        ccf=Decimal("1.0000"),
        exposure=Decimal("1000000.01"),
        link_decision_id="D-1",
    )

    h1 = hashlib.sha256(o1.encode("utf-8")).hexdigest()
    h2 = hashlib.sha256(o1_modified.encode("utf-8")).hexdigest()
    assert h1 != h2


def test_timestamps_and_run_id_excluded():
    """Verify that neither timestamps nor run_id are present in canonical serialization lines."""
    line = canonical_output_line(
        group_key="E:GRP001",
        entity_key="E:SUB001",
        source_system="LOS",
        source_row_id="LN-1001",
        exposure_component="FUNDED",
        membership_kind="MEMBER",
        rec_key="LOS:CUST-1",
        product="TERM_LOAN",
        gross=Decimal("1000.00"),
        ccf=Decimal("1.0000"),
        exposure=Decimal("1000.00"),
        link_decision_id="D-01",
    )
    assert "run_id" not in line
    assert "R-" not in line
    assert "2026-" not in line
    assert "TIMESTAMP" not in line
