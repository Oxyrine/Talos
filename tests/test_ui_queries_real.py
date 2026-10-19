"""tests/test_ui_queries_real.py: the non-mock path of ui/queries.py against a fake connection.

No Exasol is needed. These catch the mistakes that only show up with a real database:
rows are dicts (connect() sets fetch_dict), the reader may only touch REPORT, and
decide/batch_decide/rule/batch_sample all require business_date.
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from ui import queries
from ui.batch_token import generate_batch_token


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchval(self):
        return next(iter(self.rows[0].values())) if self.rows else None


class FakeConn:
    """Answers by substring of the SQL; records every statement so tests can check what was touched."""

    def __init__(self, answers):
        self.answers = answers
        self.sql = []

    def execute(self, sql, query_params=None):
        self.sql.append(sql)
        for needle, rows in self.answers.items():
            if needle in sql:
                return FakeResult(rows)
        raise AssertionError(f"unexpected SQL: {sql[:120]}")

    def close(self):
        pass


@pytest.fixture(autouse=True)
def real_mode(monkeypatch):
    monkeypatch.delenv("TALOS_MOCK", raising=False)
    monkeypatch.setenv("TALOS_SESSION_SECRET", "s" * 40)


def use(monkeypatch, answers):
    conn = FakeConn(answers)
    monkeypatch.setattr(queries, "_get_reader_connection", lambda: conn)
    return conn


def test_reader_only_touches_report(monkeypatch):
    conn = use(monkeypatch, {
        "V_LATEST_RUN": [{"run_id": "R-1", "known_at": "2026-10-06"}],
        "V_GROUP_EXPOSURE": [],
        "GROUP BY batch_id": [],
        "SELECT COUNT(*)": [{"c": 0}],
        "V_PROPOSAL_QUEUE": [],
        "V_CURRENT_RUN": [{"run_id": "R-1", "business_date": "2026-09-30"}],
    })
    queries.get_board_data()
    queries.get_queue_data()
    for sql in conn.sql:
        assert "GOV." not in sql.replace("REPORT.", "") and "GRAPH." not in sql and "RESOLVE." not in sql


def test_board_clamps_hidden_and_marks_unresolved(monkeypatch):
    def group(key, limit, reported, flags="", breach=False, large=False):
        return {
            "group_key": key, "group_name": key, "head_entity_key": key, "member_count": 3,
            "reported_exposure": Decimal(reported), "limit_exposure": None if limit is None else Decimal(limit),
            "capital_base": Decimal("4200000000"), "utilisation_pct": Decimal("10"),
            "is_large": large, "is_breach": breach, "group_flags": flags,
            "hidden_exposure": None if limit is None else Decimal(limit) - Decimal(reported), "headroom": Decimal("0"),
        }

    conn = use(monkeypatch, {
        "V_LATEST_RUN": [{"run_id": "R-1", "known_at": "x"}],
        # lone unlinked records are aggregated, not listed
        "SUM(limit_exposure)": [{"n": 2, "amt": Decimal("5000000")}],
        "V_GROUP_EXPOSURE": [
            group("E:A", "1120000000", "400000000", breach=True, large=True),
            group("E:B", "312000000", "400000000"),  # Talos below reported: hidden must clamp to 0
            group("R:GRP-X", None, "364000000", flags="NOT_LINKED"),  # reported group not linked yet
        ],
    })
    board = queries.get_board_data()
    by_key = {g["group_key"]: g for g in board["groups"]}
    assert board["kpi"]["hidden_exposure"] == Decimal("720000000")
    assert by_key["E:B"]["hidden_exposure"] == 0
    assert by_key["R:GRP-X"]["limit_exposure"] is None
    assert by_key["R:GRP-X"]["reported_exposure"] == Decimal("364000000")
    assert board["kpi"]["breaches_count"] == 1
    assert board["kpi"]["unassigned_exposure"] == Decimal("5000000")
    assert board["unlinked_records"] == 2
    assert (board["group_count"], board["pending_count"]) == (3, 1)
    listing = next(q for q in conn.sql if "group_key NOT LIKE 'U:%'" in q)
    assert "reported_exposure > 0" in listing


def test_board_lists_only_the_top_groups(monkeypatch):
    rows = [{
        "group_key": f"R:G{i}", "group_name": f"G{i}", "head_entity_key": f"R:G{i}", "member_count": 1,
        "reported_exposure": Decimal(i), "limit_exposure": None, "capital_base": Decimal("4200000000"),
        "utilisation_pct": None, "is_large": False, "is_breach": False, "group_flags": "NOT_LINKED",
        "hidden_exposure": None, "headroom": None,
    } for i in range(1, queries.BOARD_ROWS + 51)]
    use(monkeypatch, {
        "V_LATEST_RUN": [{"run_id": "R-1", "known_at": "x"}],
        "SUM(limit_exposure)": [{"n": 0, "amt": None}],
        "V_GROUP_EXPOSURE": rows,
    })
    board = queries.get_board_data()
    assert board["group_count"] == queries.BOARD_ROWS + 50
    assert len(board["groups"]) == queries.BOARD_ROWS
    # before review every hidden delta is 0, so the order falls back to the reported figure
    assert board["groups"][0]["group_key"] == f"R:G{queries.BOARD_ROWS + 50}"


def test_queue_excludes_batch_members_and_reads_batches_from_the_view(monkeypatch):
    conn = use(monkeypatch, {
        "GROUP BY batch_id": [{"batch_id": "B-OWN-1", "batch_kind": "OWNERSHIP", "total_count": 3540, "sample_count": 71}],
        "SELECT COUNT(*)": [{"c": 1}],
        "LIMIT": [{
            "proposal_id": "P-1", "kind": "RECORD_LINK", "subject_key": "k", "tier": "T1", "tier_reason": "r",
            "warning": None, "rupee_impact": Decimal("1"), "crosses_limit": True, "crosses_le": False,
            "group_before_pct": Decimal("18"), "group_after_pct": Decimal("26.7"), "group_name": "Sunrise",
            "evidence_json": "{}",
        }],
    })
    q = queries.get_queue_data()
    assert q["batches"][0]["sample_count"] == 71
    assert q["proposals"][0]["crosses_limit"] == 1
    assert any("batch_id IS NULL OR batch_failed" in s for s in conn.sql)


def test_decisions_pass_business_date(monkeypatch):
    use(monkeypatch, {
        "V_CURRENT_RUN": [{"run_id": "R-9", "business_date": "2026-09-30"}],
        "V_LATEST_RUN": [{"run_id": "R-9", "known_at": "x"}],
        "V_GROUP_EXPOSURE": [],
    })
    seen = {}

    def fake(name):
        def _f(*args, **kwargs):
            seen[name] = kwargs
            return SimpleNamespace(decision_id="D-1", decision="BATCH_APPROVE")
        return _f

    import orchestrator.decide as decide_mod

    monkeypatch.setattr(decide_mod, "decide", fake("decide"))
    monkeypatch.setattr(decide_mod, "batch_decide", fake("batch_decide"))
    monkeypatch.setattr(decide_mod, "rule", fake("rule"))

    queries.execute_decision("P-1", "APPROVE", "ok", "rev", "APPROVER")
    queries.execute_ruling("P-2", "JOINT", None, "ok", "rev", "APPROVER")
    token = generate_batch_token("rev", "B-1", 99, ["P-3"])
    queries.execute_batch("B-1", 0, token, {"P-3": True}, "ok", "rev", "APPROVER")

    assert seen["decide"]["business_date"] == "2026-09-30"
    assert seen["rule"]["business_date"] == "2026-09-30"
    assert seen["batch_decide"]["business_date"] == "2026-09-30"
    assert seen["batch_decide"]["seed"] == 99  # from the signed token, not the form


def test_batch_rejects_a_sample_the_token_was_not_issued_for(monkeypatch):
    token = generate_batch_token("rev", "B-1", 99, ["P-3"])
    with pytest.raises(ValueError, match="changed"):
        queries.execute_batch("B-1", 99, token, {"P-3": True, "P-EXTRA": True}, "ok", "rev", "APPROVER")
    with pytest.raises(ValueError, match="mismatch"):
        queries.execute_batch("B-1", 99, token, {"P-3": True}, "ok", "someone-else", "APPROVER")


def test_pipeline_reduction_ratio_is_shown_as_a_percentage(monkeypatch):
    use(monkeypatch, {
        "V_PIPELINE_TIMING": [],
        "V_CANDIDATE_PATHS": [],
        "V_TIER_COUNTS": [{"tier": "T0", "n": 3}],
        "V_PIPELINE_SUMMARY": [{
            "total_book_records": 25000, "total_reg_entities": 4000, "total_candidates": 731543,
            "settled_in_sql_pct": Decimal("95.6"), "sent_to_model_pct": Decimal("0"),
            "reduction_ratio": Decimal("0.992685"),  # REPORT.V_PIPELINE_SUMMARY stores a 0..1 ratio
        }],
    })
    summary = queries.get_pipeline_data()["summary"]
    assert summary["reduction_ratio"] == Decimal("99.2685")


def test_queue_shows_live_impact_for_cards_filed_before_linking(monkeypatch):
    card = {
        "proposal_id": "P-OWN", "kind": "OWNERSHIP", "subject_key": "k", "tier": "T1", "tier_reason": "r",
        "warning": None, "rupee_impact": Decimal("0"), "delta_amt": Decimal("364000000"),
        "crosses_limit": True, "crosses_le": False, "group_before_pct": Decimal("18"),
        "group_after_pct": Decimal("26.7"), "group_name": "Sunrise", "evidence_json": "{}",
    }
    use(monkeypatch, {"GROUP BY batch_id": [], "SELECT COUNT(*)": [{"c": 1}], "LIMIT": [card]})
    assert queries.get_queue_data()["proposals"][0]["rupee_impact"] == Decimal("364000000")
