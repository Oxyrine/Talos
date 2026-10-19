"""tests/test_ui_routes.py: Comprehensive route smoke tests, 5-stage hero state machine tests, and 503 checks."""

import pytest
from starlette.testclient import TestClient

from ui.app import app
from ui.auth import COOKIE_NAME, SessionUser, create_session_token
from ui.mock_data import get_mock_state, reset_mock_state


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("TALOS_MOCK", "1")
    reset_mock_state()


@pytest.fixture
def client(mock_env):
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def approver_client(mock_env):
    c = TestClient(app, follow_redirects=False)
    user = SessionUser(username="reviewer@talos.internal", role="APPROVER")
    token = create_session_token(user)
    c.cookies.set(COOKIE_NAME, token)
    return c


def test_unauthenticated_redirects(client):
    """Verify protected routes redirect unauthenticated users to /signin."""
    for path in ["/", "/board", "/queue", "/lineage/group/GRP-017", "/pipeline", "/audit"]:
        res = client.get(path)
        assert res.status_code == 303, f"Expected 303 for {path}, got {res.status_code}"
        assert res.headers["location"] == "/signin"


def test_auth_workflow(client):
    """Verify sign in, session cookie creation, and sign out."""
    # 1. Signin page
    res = client.get("/signin")
    assert res.status_code == 200
    assert "Sign In" in res.text

    # 2. Invalid password
    res = client.post(
        "/signin",
        data={"username": "reviewer@talos.internal", "password": "wrongpassword"},
        headers={"Origin": "http://testserver"},
    )
    assert res.status_code == 401
    assert "Invalid reviewer credentials." in res.text

    # 3. Valid login
    res = client.post(
        "/signin",
        data={"username": "reviewer@talos.internal", "password": "talos"},
        headers={"Origin": "http://testserver"},
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/board"
    assert COOKIE_NAME in res.cookies

    # 4. Signout
    res = client.post(
        "/signout",
        headers={"Origin": "http://testserver"},
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/signin"


def test_5_stage_hero_walkthrough(approver_client):
    """Test full 5-stage hero state machine down to the paisa."""
    # --- Step 0: Baseline ---
    res = approver_client.get("/board")
    assert res.status_code == 200
    assert "0" in res.text  # 0 breaches
    assert "₹40.0 cr" in res.text  # Reported
    assert "—" in res.text  # Talos is unlinked

    # Check queue has 2 batches
    q_res = approver_client.get("/queue")
    assert q_res.status_code == 200
    assert "Exact-ID Record Links Batch" in q_res.text
    assert "Corroborated Ownership Edges Batch" in q_res.text

    # --- Step 1: Approve T0 Record Links Batch ---
    # Fetch batch page to retrieve seed and token
    b_res = approver_client.get("/queue/batch/B-REC-2026101101")
    assert b_res.status_code == 200
    assert "seed" in b_res.text
    assert "token" in b_res.text

    # Submit batch approval
    state = get_mock_state()
    seed = state.active_batch_seeds["B-REC-2026101101"]
    from ui.batch_token import generate_batch_token
    sample_ids = [f"P-REC-SMP-{i:03d}" for i in range(1, 97)]
    token = generate_batch_token("reviewer@talos.internal", "B-REC-2026101101", seed, sample_ids)

    post_data = {
        "seed": str(seed),
        "token": token,
        "reason": "T0 batch sample verified",
    }
    for pid in sample_ids:
        post_data[f"pair_{pid}"] = "APPROVE"

    res = approver_client.post(
        "/queue/batch/B-REC-2026101101",
        data=post_data,
        headers={"Origin": "http://testserver"},
    )
    assert res.status_code == 303

    # Verify Step 1 numbers: Sunrise Head alone = ₹31.2 cr (7.4%), 0 breaches, hidden clamped at 0
    res = approver_client.get("/board")
    assert "₹31.2 cr" in res.text
    assert "7.4%" in res.text

    # --- Step 2: Approve Corroborated Ownership Batch ---
    b_own_res = approver_client.get("/queue/batch/B-OWN-2026101101")
    assert b_own_res.status_code == 200

    seed_own = state.active_batch_seeds["B-OWN-2026101101"]
    sample_own_ids = [f"P-OWN-SMP-{i:03d}" for i in range(1, 72)]
    token_own = generate_batch_token("reviewer@talos.internal", "B-OWN-2026101101", seed_own, sample_own_ids)

    post_own_data = {
        "seed": str(seed_own),
        "token": token_own,
        "reason": "Corroborated ownership edges verified",
    }
    for pid in sample_own_ids:
        post_own_data[f"pair_{pid}"] = "APPROVE"

    res = approver_client.post(
        "/queue/batch/B-OWN-2026101101",
        data=post_own_data,
        headers={"Origin": "http://testserver"},
    )
    assert res.status_code == 303

    # Verify Step 2 numbers: Sunrise Group = ₹58.2 cr (13.9%), Crosses 10% Line (Amber), Hidden = +₹18.2 cr
    res = approver_client.get("/board")
    assert "₹58.2 cr" in res.text
    assert "13.9%" in res.text
    assert "+₹18.2 cr" in res.text
    assert "Large exposure" in res.text

    # --- Step 3: Individual T1 Cards Approved + T3 Rejected ---
    # Approve Guarantee (+₹17.4 cr) -> moves to Step 3 (₹75.6 cr)
    res = approver_client.post(
        "/proposals/P-REC-GTE-SUNRISE-TRUE/decision",
        data={"decision": "APPROVE", "reason": "Bank Guarantee facility confirmed via address and fuzzy match"},
        headers={"Origin": "http://testserver"},
    )
    assert res.status_code == 200
    assert "✓ LINK APPROVED" in res.text

    # Reject T3 ID conflict
    res = approver_client.post(
        "/proposals/P-REC-GTE-SUNRISE-CONFLICT/decision",
        data={"decision": "REJECT", "reason": "Decoy entity ID-Name conflict rejected"},
        headers={"Origin": "http://testserver"},
    )
    assert res.status_code == 200
    assert "✗ LINK REJECTED" in res.text

    # Verify Step 3 numbers: Sunrise Group = ₹75.6 cr (18.0%), Hidden = +₹35.6 cr
    res = approver_client.get("/board")
    assert "₹75.6 cr" in res.text
    assert "18.0%" in res.text
    assert "+₹35.6 cr" in res.text

    # --- Step 4: Approve Ownership Link Sunrise -> HoldCo ---
    res = approver_client.post(
        "/proposals/P-OWN-SUNRISE-HOLDCO/decision",
        data={"decision": "APPROVE", "reason": "100% equity holding in HoldCo confirmed via MCA filing"},
        headers={"Origin": "http://testserver"},
    )
    assert res.status_code == 200

    # Verify Step 4 numbers: Sunrise Group = ₹112.0 cr (26.7%), LIMIT BREACH (> ₹105.0 cr)!
    res = approver_client.get("/board")
    assert "₹112.0 cr" in res.text
    assert "26.7%" in res.text
    assert "+₹72.0 cr" in res.text
    assert "Limit breach" in res.text


def test_jv_ruling_routes(approver_client):
    """Verify JV ruling screen and submission."""
    res = approver_client.get("/rulings/P-RULING-JV-01")
    assert res.status_code == 200
    assert "Joint Venture Control Ruling" in res.text
    assert "JOINT" in res.text

    res = approver_client.post(
        "/rulings/P-RULING-JV-01",
        data={
            "ruling": "JOINT",
            "reason": "50-50 equity joint control verified under LEF §5.3",
        },
        headers={"Origin": "http://testserver"},
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/queue"


def test_lineage_and_audit_routes(approver_client):
    """Verify lineage group, rows, pipeline, and audit replay."""
    # Lineage group
    res = approver_client.get("/lineage/group/GRP-017")
    assert res.status_code == 200
    assert "Recursive Graph Ownership Traversal" in res.text
    assert "Consolidated Group Members" in res.text

    # Lineage entity
    res = approver_client.get("/lineage/entity/ENT-017-001")
    assert res.status_code == 200
    assert "Exposure component" in res.text

    # Lineage rows
    res = approver_client.get("/lineage/rows?group_key=GRP-017")
    assert res.status_code == 200
    assert "Row-Level Exposure Lineage" in res.text

    # Pipeline diagnostics
    res = approver_client.get("/pipeline")
    assert res.status_code == 200
    assert "Pipeline Diagnostics & Match Funnel" in res.text
    assert "Execution Timing by Stage" in res.text

    # Audit log
    res = approver_client.get("/audit")
    assert res.status_code == 200
    assert "Audit Trail & Cryptographic Replay Log" in res.text

    # Replay verification endpoint
    res = approver_client.post(
        "/audit/replay/RUN-001",
        headers={"Origin": "http://testserver"},
    )
    assert res.status_code == 200
    assert "REPLAY MATCH" in res.text


def test_db_unavailable_when_mock_disabled(monkeypatch):
    """Verify HTTP 503 is returned when TALOS_MOCK is unset and DB is unavailable (no silent fallback)."""
    monkeypatch.delenv("TALOS_MOCK", raising=False)
    monkeypatch.setenv("TALOS_SESSION_SECRET", "x" * 40)
    client = TestClient(app, follow_redirects=False)

    user = SessionUser(username="reviewer@talos.internal", role="APPROVER")
    token = create_session_token(user)
    client.cookies.set(COOKIE_NAME, token)

    res = client.get("/board")
    assert res.status_code == 503
    assert "503 Service Unavailable" in res.text
    assert "Exasol database unavailable (TALOS_MOCK is not enabled)" in res.text
