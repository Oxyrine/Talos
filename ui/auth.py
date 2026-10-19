"""ui/auth.py: Authentication, rate limiting, and session security for Talos."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

REPO_ROOT = Path(__file__).resolve().parent.parent
REVIEWERS_FILE = REPO_ROOT / ".talos" / "reviewers.json"

COOKIE_NAME = "talos_session"
SESSION_MAX_AGE = 86400  # 24 hours
RATE_LIMIT_MAX_ATTEMPTS = 5
RATE_LIMIT_WINDOW_SECONDS = 900  # 15 minutes

# In-memory tracking for rate limiting: key -> list of timestamp floats
_FAILED_ATTEMPTS: dict[str, list[float]] = {}


@dataclass(frozen=True)
class SessionUser:
    username: str
    role: Literal["APPROVER", "ANALYST"]


def get_session_serializer() -> URLSafeTimedSerializer:
    secret = os.environ.get("TALOS_SESSION_SECRET")
    if not secret:
        # Fallback to local default if not set
        secret = "talos_dev_secret_replace_in_production_32chars"
    return URLSafeTimedSerializer(secret)


def is_mock_mode() -> bool:
    """Return True strictly if TALOS_MOCK=1 is set in the environment."""
    return os.environ.get("TALOS_MOCK") == "1"


def get_client_ip(request: Request) -> str:
    """Extract client IP address reliably."""
    client = request.client
    return client.host if client else "127.0.0.1"


def check_rate_limit(username: str, ip: str) -> None:
    """Raise HTTP 429 if username + IP exceeds failed attempts in the window."""
    key = f"{username}:{ip}"
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS

    # Clean old attempts
    attempts = [t for t in _FAILED_ATTEMPTS.get(key, []) if t > cutoff]
    _FAILED_ATTEMPTS[key] = attempts

    if len(attempts) >= RATE_LIMIT_MAX_ATTEMPTS:
        retry_after = int(RATE_LIMIT_WINDOW_SECONDS - (now - attempts[0]))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed login attempts. Account temporarily locked. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(max(1, retry_after))},
        )


def record_failed_attempt(username: str, ip: str) -> None:
    """Record a failed login attempt for username + IP."""
    key = f"{username}:{ip}"
    now = time.time()
    if key not in _FAILED_ATTEMPTS:
        _FAILED_ATTEMPTS[key] = []
    _FAILED_ATTEMPTS[key].append(now)


def clear_failed_attempts(username: str, ip: str) -> None:
    """Clear failed attempts upon successful login."""
    key = f"{username}:{ip}"
    _FAILED_ATTEMPTS.pop(key, None)


def verify_reviewer(username: str, password: str, client_ip: str) -> SessionUser | None:
    """Verify reviewer credentials via scrypt against .talos/reviewers.json."""
    check_rate_limit(username, client_ip)

    # 1. Mock Mode Bypass (Strictly when TALOS_MOCK=1)
    if is_mock_mode() and username == "reviewer@talos.internal" and password == "talos":
        clear_failed_attempts(username, client_ip)
        return SessionUser(username="reviewer@talos.internal", role="APPROVER")

    # 2. Production Scrypt Verification
    if not REVIEWERS_FILE.is_file():
        record_failed_attempt(username, client_ip)
        return None

    try:
        data = json.loads(REVIEWERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        record_failed_attempt(username, client_ip)
        return None

    user_record = data.get(username)
    if not user_record:
        record_failed_attempt(username, client_ip)
        return None

    salt = bytes.fromhex(user_record["salt"])
    expected_hash = bytes.fromhex(user_record["hash"])

    computed_hash = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=16384,
        r=8,
        p=1,
    )

    if hmac.compare_digest(expected_hash, computed_hash):
        clear_failed_attempts(username, client_ip)
        return SessionUser(
            username=user_record["name"],
            role=user_record.get("role", "ANALYST"),
        )
    else:
        record_failed_attempt(username, client_ip)
        return None


def verify_origin(request: Request) -> None:
    """Reject mutating requests if Origin header is missing or does not match server host."""
    origin = request.headers.get("origin")
    if not origin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Origin header is required for state-mutating requests.",
        )

    parsed_origin = urlparse(origin)
    server_host = request.headers.get("host") or ""
    server_hostname = server_host.split(":")[0]

    # Check host match
    if parsed_origin.hostname not in (server_hostname, "127.0.0.1", "localhost"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: Cross-origin request blocked (Origin: {origin}).",
        )


def create_session_token(user: SessionUser) -> str:
    """Encode session user into signed token."""
    serializer = get_session_serializer()
    return serializer.dumps({
        "username": user.username,
        "role": user.role,
        "created_at": datetime.now(UTC).isoformat(),
    })


def get_current_user_optional(request: Request) -> SessionUser | None:
    """Retrieve SessionUser from cookie, returning None if unauthenticated."""
    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie:
        return None

    serializer = get_session_serializer()
    try:
        data = serializer.loads(cookie, max_age=SESSION_MAX_AGE)
        return SessionUser(username=data["username"], role=data["role"])
    except (BadSignature, SignatureExpired, KeyError):
        return None


def require_auth(request: Request) -> SessionUser:
    """Dependency requiring valid authentication. Redirects HTML requests to /signin."""
    user = get_current_user_optional(request)
    if not user:
        if request.headers.get("hx-request") == "true":
            # For HTMX requests, issue HX-Redirect header
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"HX-Redirect": "/signin"},
                detail="Authentication required",
            )
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/signin"},
            detail="Redirect to signin",
        )
    return user


def require_approver(user: SessionUser = Depends(require_auth)) -> SessionUser:
    """Dependency requiring APPROVER role."""
    if user.role != "APPROVER":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: This action requires the APPROVER role.",
        )
    return user
