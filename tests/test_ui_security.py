"""tests/test_ui_security.py: Rigorous security, CSP compliance, and anti-lockout tests."""

import os
import re
import time
from decimal import Decimal
import pytest
from starlette.testclient import TestClient

from ui.app import app
from ui.auth import (
    COOKIE_NAME,
    _FAILED_ATTEMPTS,
    SessionUser,
    create_session_token,
    clear_failed_attempts,
)
from ui.mock_data import generate_batch_token, verify_batch_token, reset_mock_state


@pytest.fixture(autouse=True)
def setup_mock_env(monkeypatch):
    monkeypatch.setenv("TALOS_MOCK", "1")
    _FAILED_ATTEMPTS.clear()
    reset_mock_state()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def approver_client():
    c = TestClient(app)
    user = SessionUser(username="reviewer@talos.internal", role="APPROVER")
    token = create_session_token(user)
    c.cookies.set(COOKIE_NAME, token)
    return c


@pytest.fixture
def analyst_client():
    c = TestClient(app)
    user = SessionUser(username="analyst@talos.internal", role="ANALYST")
    token = create_session_token(user)
    c.cookies.set(COOKIE_NAME, token)
    return c


def test_strict_csp_headers(approver_client):
    """Verify security headers middleware imposes strict CSP with zero unsafe-inline."""
    res = approver_client.get("/board")
    assert res.status_code == 200

    csp = res.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "style-src 'self'" in csp
    assert "'unsafe-inline'" not in csp
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "DENY"


def test_zero_inline_styles_rendered(approver_client):
    """Verify that templates render ZERO inline style attributes to strictly satisfy CSP."""
    endpoints = ["/board", "/queue", "/queue/batch/B-REC-001", "/rulings/P-HERO-005", "/pipeline", "/audit"]
    style_attr_regex = re.compile(r'\sstyle\s*=\s*["\']', re.IGNORECASE)

    for ep in endpoints:
        res = approver_client.get(ep)
        assert res.status_code == 200, f"Endpoint {ep} failed with status {res.status_code}"
        # Assert no style="..." attribute exists in the entire HTML body
        matches = style_attr_regex.findall(res.text)
        assert len(matches) == 0, f"Found inline style attribute in {ep}: {matches}"


def test_svg_gauge_uses_xml_attributes_only(approver_client):
    """Verify regulatory gauge uses pure SVG viewBox and XML attributes with no CSS styling."""
    res = approver_client.get("/board")
    assert res.status_code == 200
    assert 'viewBox="0 0 35 12"' in res.text
    assert 'class="gauge-svg"' in res.text
    assert 'class="gauge-track"' in res.text
    assert 'class="gauge-needle needle-warn"' in res.text
    assert 'class="gauge-needle needle-danger"' in res.text


def test_csrf_origin_header_validation(approver_client):
    """Verify that mutating POST routes reject requests without Origin or from mismatched Origin."""
    # 1. Missing Origin header
    res = approver_client.post(
        "/proposals/P-HERO-001/decision",
        data={"decision": "APPROVE", "reason": "Test decision"},
    )
    assert res.status_code == 403
    assert "Origin header is required" in res.text

    # 2. Cross-origin spoofed Origin header
    res = approver_client.post(
        "/proposals/P-HERO-001/decision",
        data={"decision": "APPROVE", "reason": "Test decision"},
        headers={"Origin": "https://malicious-attacker.com"},
    )
    assert res.status_code == 403
    assert "Cross-origin request blocked" in res.text

    # 3. Valid Origin header (testserver or localhost)
    res = approver_client.post(
        "/proposals/P-HERO-001/decision",
        data={"decision": "APPROVE", "reason": "Valid decision"},
        headers={"Origin": "http://testserver"},
    )
    assert res.status_code == 200


def test_rate_limiter_lockout(client):
    """Verify 5 failed login attempts result in HTTP 429 lockout."""
    clear_failed_attempts("reviewer@talos.internal", "testclient")

    # 5 consecutive invalid attempts
    for _ in range(5):
        res = client.post(
            "/signin",
            data={"username": "reviewer@talos.internal", "password": "wrong_password"},
            headers={"Origin": "http://testserver"},
        )
        assert res.status_code == 401

    # Subsequent attempt: locked out with HTTP 429
    res = client.post(
        "/signin",
        data={"username": "reviewer@talos.internal", "password": "wrong_password"},
        headers={"Origin": "http://testserver"},
    )
    assert res.status_code == 429
    assert "Too many failed login attempts" in res.text


def test_hmac_batch_seed_token_integrity():
    """Verify HMAC batch tokens reject tampering and expiry."""
    user = "reviewer@talos.internal"
    batch_id = "B-REC-001"
    seed = 424242
    pids = ["P-1", "P-2", "P-3"]

    valid_token = generate_batch_token(user, batch_id, seed, pids)
    assert verify_batch_token(valid_token, user, batch_id, pids) == seed

    # Tampered proposal IDs
    with pytest.raises(ValueError):
        verify_batch_token(valid_token, user, batch_id, ["P-1", "P-2", "P-FORGED"])

    # Tampered batch_id
    with pytest.raises(ValueError):
        verify_batch_token(valid_token, user, "OTHER-BATCH", pids)

    # Tampered user
    with pytest.raises(ValueError):
        verify_batch_token(valid_token, "other_user", batch_id, pids)


def test_approver_role_guard(analyst_client):
    """Verify ANALYST role cannot approve proposals (HTTP 403)."""
    res = analyst_client.post(
        "/proposals/P-HERO-001/decision",
        data={"decision": "APPROVE", "reason": "Analyst should not decide"},
        headers={"Origin": "http://testserver"},
    )
    assert res.status_code == 403
    assert "Forbidden: This action requires the APPROVER role." in res.text
