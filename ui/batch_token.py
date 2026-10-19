"""ui/batch_token.py: HMAC token that binds a batch review form to the sample it was issued for.

The token carries (user, batch, seed, sha256 of the sorted proposal ids, expiry) and is signed
with a key derived from TALOS_SESSION_SECRET, so a reviewer cannot submit a seed or sample they
were not shown, and a token issued to one reviewer is useless to another.
"""

from __future__ import annotations

import hashlib
import hmac
import time

from ui.auth import get_secret

TOKEN_TTL_SECONDS = 900  # 15 minutes


def _sample_hash(proposal_ids: list[str]) -> str:
    return hashlib.sha256(",".join(sorted(proposal_ids)).encode("utf-8")).hexdigest()


def _sign(payload: str) -> str:
    return hmac.new(get_secret("batch"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def generate_batch_token(user_id: str, batch_id: str, seed: int, proposal_ids: list[str]) -> str:
    """Issue an HMAC token for user_id, batch_id, seed and the sample, valid for 15 minutes."""
    expires_at = int(time.time()) + TOKEN_TTL_SECONDS
    payload = f"{user_id}:{batch_id}:{seed}:{_sample_hash(proposal_ids)}:{expires_at}"
    return f"{payload}:{_sign(payload)}"


def verify_batch_token(token: str, user_id: str, batch_id: str, proposal_ids: list[str]) -> int:
    """Verify the token and return its seed. Raise ValueError on tamper, mismatch or expiry."""
    # user ids are e-mail style names with no colon; rsplit keeps a stray colon from shifting fields
    try:
        u, b, seed_str, phash, exp_str, sig = token.rsplit(":", 5)
        expires_at = int(exp_str)
        seed = int(seed_str)
    except ValueError:
        raise ValueError("Malformed batch verification token.") from None

    payload = f"{u}:{b}:{seed_str}:{phash}:{exp_str}"
    if not hmac.compare_digest(_sign(payload), sig):
        raise ValueError("Batch verification signature mismatch.")
    if u != user_id or b != batch_id:
        raise ValueError("Batch token user or batch mismatch.")
    if expires_at < time.time():
        raise ValueError("Batch verification token has expired (15-minute window).")
    if phash != _sample_hash(proposal_ids):
        raise ValueError("Batch proposals have changed since token issuance.")
    return seed
