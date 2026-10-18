"""tests/test_pipeline_helpers.py: known_at parsing, filing time, identifier-token key, SQL literals."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from orchestrator.db import REPO_ROOT, get_id_token_key
from orchestrator.loader import _sql_literal
from orchestrator.pipeline import _filed_at_after, normalize_known_at


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-01 06:00:00", "2026-10-01 06:00:00"),
        ("2026-10-01T06:00:00", "2026-10-01 06:00:00"),
        ("2026-10-01", "2026-10-01 00:00:00"),
        ("2026-10-01 06:00:00.000000", "2026-10-01 06:00:00"),
        ("2026-10-01 06:00:00.250000", "2026-10-01 06:00:00.250000"),
        ("2026-10-01T11:30:00+05:30", "2026-10-01 06:00:00"),
        (datetime(2026, 10, 1, 6, 0), "2026-10-01 06:00:00"),
        (datetime(2026, 10, 1, 11, 30, tzinfo=timezone(timedelta(hours=5, minutes=30))), "2026-10-01 06:00:00"),
        (date(2026, 10, 1), "2026-10-01 00:00:00"),
    ],
)
def test_normalize_known_at(value, expected):
    assert normalize_known_at(value) == expected


def test_normalize_known_at_rejects_garbage():
    with pytest.raises(ValueError, match="not an ISO date"):
        normalize_known_at("yesterday")


def test_normalize_known_at_default():
    assert normalize_known_at(None, default=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)) == "2026-01-02 03:04:05"


def test_filed_at_is_after_known_at():
    past = "2026-01-01 00:00:00"
    assert _filed_at_after(past) > past
    future = (datetime.now(UTC) + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    assert _filed_at_after(future) == (datetime.fromisoformat(future) + timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
    assert _filed_at_after("2099-01-01 00:00:00.500000") == "2099-01-01 00:00:01"


def test_id_token_key_required(monkeypatch):
    monkeypatch.setattr("orchestrator.db.load_env_file", lambda *a, **k: None)
    monkeypatch.delenv("TALOS_ID_TOKEN_KEY", raising=False)
    with pytest.raises(RuntimeError, match="talos init"):
        get_id_token_key()
    monkeypatch.setenv("TALOS_ID_TOKEN_KEY", "short")
    with pytest.raises(RuntimeError):
        get_id_token_key()
    monkeypatch.setenv("TALOS_ID_TOKEN_KEY", "k" * 32)
    assert get_id_token_key() == "k" * 32


def test_id_tokens_are_keyed_and_kept_out_of_evidence():
    tokens_sql = Path(REPO_ROOT / "sql" / "20_id_tokens_exact.sql").read_text(encoding="utf-8")
    for id_type in ("PAN", "CIN", "LEI"):
        assert f"HASH_SHA256({{id_token_key}} || '|{id_type}:' || v)" in tokens_sql
        assert f"HASH_SHA256('{id_type}:'" not in tokens_sql
    assert "id_tokens" not in Path(REPO_ROOT / "sql" / "70_propose_record_links.sql").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "NULL"),
        (True, "TRUE"),
        (3, "3"),
        (0.1, "0.1"),
        (Decimal("12.50"), "12.50"),
        ("O'Brien", "'O''Brien'"),
        (date(2026, 9, 30), "'2026-09-30'"),
        (datetime(2026, 9, 30, 1, 2, 3), "'2026-09-30 01:02:03.000000'"),
        (datetime(2026, 9, 30, 6, 32, 3, tzinfo=timezone(timedelta(hours=5, minutes=30))), "'2026-09-30 01:02:03.000000'"),
    ],
)
def test_sql_literal(value, expected):
    assert _sql_literal(value) == expected


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, Decimal("NaN")])
def test_sql_literal_rejects_non_finite(value):
    with pytest.raises(ValueError, match="non-finite"):
        _sql_literal(value)


@pytest.mark.parametrize("value", [b"\x00\x01", [1, 2], {"a": 1}])
def test_sql_literal_rejects_unsupported_types(value):
    with pytest.raises(TypeError):
        _sql_literal(value)
