"""tests/test_fixtures_db.py: membership and replay fixtures against a live Exasol.

The module resets the database, seeds the initial policy and loads
sql/fixtures/membership_replay.sql as SYS, then publishes runs as TALOS_PIPELINE at chosen
(business_date, known_at) points. Expected membership and exposure are written out per case.
WARNING: this wipes every Talos schema (like `talos reset`).
"""

from __future__ import annotations

import argparse
from decimal import Decimal

import pytest

from orchestrator.db import REPO_ROOT, connect, is_exasol_available, run_sql_file

pytestmark = pytest.mark.exasol

MANIFEST = {
    "load_ids": {
        "LOS": "FX-LOS-20260930-02",
        "TSY": "FX-TSY-20260930-01",
        "GTE": "FX-GTE-20260930-01",
        "COL": "FX-COL-20260930-01",
        "REG": "FX-REG-01",
    },
    "policy_event_ids": {},
}


def E(name: str) -> str:
    return f"E:FX-{name}"


@pytest.fixture(scope="module")
def fx():
    if not is_exasol_available():
        pytest.skip("Exasol not available")
    from orchestrator.cli import _cmd_reset
    from orchestrator.loader import seed_policy_events

    assert _cmd_reset(argparse.Namespace(force=False)) == 0
    conn = connect("sys", autocommit=True)
    try:
        seed_policy_events(conn)
        run_sql_file(conn, REPO_ROOT / "sql" / "fixtures" / "membership_replay.sql")
    finally:
        conn.close()
    return True


def publish(business_date: str, known_at: str, manifest: dict | None = MANIFEST):
    from orchestrator.pipeline import publish_run

    res = publish_run(business_date=business_date, known_at=known_at, manifest=manifest)
    assert res.status == "OK"
    return res


def membership(run_id: str) -> dict[str, dict]:
    """entity_key -> {group, head, flags, kinds: {kind: group set}}"""
    conn = connect("pipeline")
    try:
        rows = conn.execute(
            "SELECT group_key, entity_key, membership_kind, is_head, group_flags FROM GOV.RUN_MEMBERSHIP WHERE run_id = {r}",
            query_params={"r": run_id},
        ).fetchall()
    finally:
        conn.close()
    out: dict[str, dict] = {}
    for r in rows:
        d = out.setdefault(r["entity_key"], {"attributed_to": set()})
        if r["membership_kind"] == "MEMBER":
            d.update(group=r["group_key"], head=r["is_head"], flags=r["group_flags"])
        else:
            d["attributed_to"].add(r["group_key"])
    return out


def group_exposure(run_id: str) -> dict[str, tuple[Decimal, Decimal]]:
    """group_key -> (book exposure, limit exposure)"""
    conn = connect("pipeline")
    try:
        rows = conn.execute(
            """SELECT group_key,
                      SUM(CASE WHEN membership_kind = 'MEMBER' THEN exposure_amount ELSE 0 END) AS book,
                      SUM(exposure_amount) AS lim
               FROM GOV.RUN_OUTPUT WHERE run_id = {r} GROUP BY group_key""",
            query_params={"r": run_id},
        ).fetchall()
    finally:
        conn.close()
    return {r["group_key"]: (Decimal(str(r["book"])), Decimal(str(r["lim"]))) for r in rows}


def record_entity(run_id: str, rec_key: str) -> str | None:
    conn = connect("pipeline")
    try:
        return conn.execute(
            "SELECT MIN(entity_key) FROM GOV.RUN_OUTPUT WHERE run_id = {r} AND rec_key = {k} AND membership_kind = 'MEMBER'",
            query_params={"r": run_id, "k": rec_key},
        ).fetchval()
    finally:
        conn.close()


@pytest.fixture(scope="module")
def main_run(fx):
    return publish("2026-09-30", "2026-10-11 00:00:00")


def test_diamond_counted_once(main_run):
    m = membership(main_run.run_id)
    for n in ("DIA_P", "DIA_B", "DIA_C", "DIA_X"):
        assert m[E(n)]["group"] == E("DIA_P")
    assert m[E("DIA_P")]["head"] is True
    assert group_exposure(main_run.run_id)[E("DIA_P")] == (Decimal(1000), Decimal(1000))


def test_rootless_cycle_is_one_group_headed_by_largest(main_run):
    m = membership(main_run.run_id)
    for n in ("CYC_A", "CYC_B", "CYC_C"):
        assert m[E(n)]["group"] == E("CYC_B")
        assert m[E(n)]["flags"] == "CYCLE_HEADED"
    assert m[E("CYC_B")]["head"] is True
    assert group_exposure(main_run.run_id)[E("CYC_B")][0] == Decimal(60)


def test_self_owning_entity_stands_alone(main_run):
    m = membership(main_run.run_id)
    assert m[E("SELF_S")]["group"] == E("SELF_S")
    assert m[E("SELF_S")]["head"] is True
    assert m[E("SELF_S")]["flags"] is None


def test_six_level_chain_converges(main_run):
    m = membership(main_run.run_id)
    members = [k for k, v in m.items() if v.get("group") == E("CH_0")]
    assert len(members) == 7
    assert main_run.lp_passes <= 8   # six hops plus the pass that changes nothing


def test_minority_edge_never_merges(main_run):
    m = membership(main_run.run_id)
    assert m[E("MIN_1")]["group"] == E("MIN_1")
    assert m[E("MIN_2")]["group"] == E("MIN_2")


def test_pending_ruling_is_unassigned(main_run):
    m = membership(main_run.run_id)
    assert m[E("PEND_J")]["group"] == E("PEND_J")
    assert m[E("PEND_J")]["flags"] == "UNASSIGNED"


def test_jv_single_joins_controller(main_run):
    m = membership(main_run.run_id)
    assert m[E("JVS_J")]["group"] == E("JVS_A")
    assert m[E("JVS_B")]["group"] == E("JVS_B")


def test_jv_joint_attributed_to_both_controllers_counted_once_in_books(main_run):
    m = membership(main_run.run_id)
    assert m[E("JVJ_J")]["group"] == E("JVJ_J")
    assert m[E("JVJ_J")]["attributed_to"] == {E("JVJ_A"), E("JVJ_B")}
    g = group_exposure(main_run.run_id)
    assert g[E("JVJ_A")] == (Decimal(1000), Decimal(1500))
    assert g[E("JVJ_B")] == (Decimal(2000), Decimal(2500))
    assert g[E("JVJ_J")] == (Decimal(500), Decimal(500))


def test_jv_none_standalone(main_run):
    m = membership(main_run.run_id)
    assert m[E("JVN_J")]["group"] == E("JVN_J")
    assert m[E("JVN_J")]["attributed_to"] == set()


def test_jv_connected_merges_only_after_controller_link(fx):
    before = membership(publish("2026-09-30", "2026-10-05 00:00:00").run_id)
    assert before[E("JVC_A")]["group"] == E("JVC_A")
    assert before[E("JVC_B")]["group"] == E("JVC_B")
    assert before[E("JVC_J")]["attributed_to"] == {E("JVC_A"), E("JVC_B")}
    after = membership(publish("2026-09-30", "2026-10-11 00:00:00").run_id)
    assert after[E("JVC_A")]["group"] == after[E("JVC_B")]["group"] == E("JVC_B")
    assert after[E("JVC_J")]["group"] == E("JVC_J")
    assert after[E("JVC_J")]["attributed_to"] == {E("JVC_B")}


def test_replay_worked_example(fx):
    """Assert from 1 Jan; retract 1-28 Feb recorded 5 Mar (product spec, Replay)."""
    rec = "LOS:FXC-RP_E"
    known_after = "2026-03-10 00:00:00"
    assert record_entity(publish("2026-01-15", known_after).run_id, rec) == E("RP_E")
    assert record_entity(publish("2026-02-15", known_after).run_id, rec) == f"U:{rec}"
    assert record_entity(publish("2026-03-15", known_after).run_id, rec) == E("RP_E")
    assert record_entity(publish("2026-02-15", "2026-03-01 00:00:00").run_id, rec) == E("RP_E")


def test_overlapping_events_later_wins_only_inside_overlap(fx):
    m_june = membership(publish("2026-06-15", "2026-08-01 00:00:00").run_id)
    assert m_june[E("OV_B")]["group"] == E("OV_B")
    m_aug = membership(publish("2026-08-15", "2026-08-01 00:00:00").run_id)
    assert m_aug[E("OV_B")]["group"] == E("OV_A")
    m_june_before = membership(publish("2026-06-15", "2026-07-01 00:00:00").run_id)
    assert m_june_before[E("OV_B")]["group"] == E("OV_A")


def test_link_approved_later_is_absent_from_earlier_known_at(fx):
    rec = "LOS:FXC-LATE_E"
    assert record_entity(publish("2026-10-05", "2026-10-15 00:00:00").run_id, rec) == f"U:{rec}"
    assert record_entity(publish("2026-10-05", "2026-10-21 00:00:00").run_id, rec) == E("LATE_E")


def test_late_balance_correction_by_known_at(fx):
    before = publish("2026-09-30", "2026-10-05 00:00:00", manifest=None)
    after = publish("2026-09-30", "2026-10-07 00:00:00", manifest=None)
    assert group_exposure(before.run_id)[E("LC_E")][0] == Decimal(1_000_000)
    assert group_exposure(after.run_id)[E("LC_E")][0] == Decimal(1_250_000)


def test_backdated_correction_keeps_signed_run_replayable(fx):
    from orchestrator.replay import replay

    signed = publish("2026-09-30", "2026-10-11 00:00:00")
    conn = connect("sys", autocommit=True)
    try:
        conn.execute(
            """INSERT INTO GRAPH.LINK_EVENT (event_id, link_key, rec_key, entity_key, "ACTION", evidence_hash,
                                             valid_from, valid_to, recorded_at, decision_id, proposal_id)
               VALUES ('FXEV-BACK', 'LOS:FXC-DIA_X>E:FX-DIA_X', 'LOS:FXC-DIA_X', 'E:FX-DIA_X', 'RETRACT', NULL,
                       '2026-01-01', '9999-12-31', '2026-10-12 00:00:00', 'FXD-BACK', 'FXP-BACK')"""
        )
    finally:
        conn.close()
    res = replay(signed.run_id)
    assert res.matches, (res.original_hash, res.replay_hash)
    newer = publish("2026-09-30", "2026-10-13 00:00:00")
    assert newer.output_hash != signed.output_hash


def test_policy_change_capital_base(fx):
    from orchestrator.policy import policy_in_force

    conn = connect("pipeline")
    try:
        assert policy_in_force(conn, "2026-08-31", "2026-10-15 00:00:00")[0]["CAPITAL_BASE_INR"] == 4_000_000_000
        assert policy_in_force(conn, "2026-09-30", "2026-10-15 00:00:00")[0]["CAPITAL_BASE_INR"] == 4_200_000_000
        assert policy_in_force(conn, "2026-09-30", "2026-09-10 00:00:00")[0]["CAPITAL_BASE_INR"] == 4_000_000_000
    finally:
        conn.close()
