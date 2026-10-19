"""ui/formatting.py: Institutional currency and percentage formatting for Talos.

Adheres strictly to Indian numbering system (Lakhs and Crores) with Decimal precision
and ROUND_HALF_UP rounding rules.
"""

from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal
from typing import Any


def to_decimal(val: Any) -> Decimal | None:
    """Safely convert any numeric value or string to Decimal."""
    if val is None:
        return None
    if isinstance(val, Decimal):
        return val
    try:
        # Convert float via str to prevent binary float representation noise
        return Decimal(str(val))
    except Exception:
        return None


def inr_cr(val: Any, decimals: int = 1) -> str:
    """Format an amount in rupees as crores (₹X.X cr).

    1 crore = 10,000,000 rupees (10^7).
    Rounds using ROUND_HALF_UP.
    Returns '—' if val is None.
    """
    d = to_decimal(val)
    if d is None:
        return "—"

    cr_amount = d / Decimal("10000000")
    quantizer = Decimal("1." + "0" * decimals) if decimals > 0 else Decimal("1")
    rounded = cr_amount.quantize(quantizer, rounding=ROUND_HALF_UP)
    return f"₹{rounded:.{decimals}f} cr"


def inr_full(val: Any) -> str:
    """Format an amount in rupees with exact Indian comma notation (₹X,XX,XXX.XX).

    Grouping:
    - 3 digits for hundreds
    - 2 digits for thousands, lakhs, crores, etc.
    Rounds paisa using ROUND_HALF_UP.
    Returns '—' if val is None.
    """
    d = to_decimal(val)
    if d is None:
        return "—"

    is_negative = d < 0
    abs_d = abs(d).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    s = f"{abs_d:.2f}"
    int_part, frac_part = s.split(".")

    if len(int_part) <= 3:
        formatted_int = int_part
    else:
        last3 = int_part[-3:]
        rest = int_part[:-3]
        chunks = []
        while len(rest) > 2:
            chunks.append(rest[-2:])
            rest = rest[:-2]
        if rest:
            chunks.append(rest)
        formatted_int = ",".join(reversed(chunks)) + "," + last3

    prefix = "-₹" if is_negative else "₹"
    return f"{prefix}{formatted_int}.{frac_part}"


def percentage(val: Any, decimals: int = 1) -> str:
    """Format a percentage value (e.g., 26.67 -> '26.7%')."""
    d = to_decimal(val)
    if d is None:
        return "—"

    quantizer = Decimal("1." + "0" * decimals) if decimals > 0 else Decimal("1")
    rounded = d.quantize(quantizer, rounding=ROUND_HALF_UP)
    return f"{rounded:.{decimals}f}%"


def parse_evidence(val: Any) -> dict[str, Any]:
    """Parse JSON evidence string or pass through dict, guaranteeing book and registry dicts."""
    res: dict[str, Any] = {}
    if isinstance(val, dict):
        res = dict(val)
    elif isinstance(val, str):
        try:
            parsed = json.loads(val)
            if isinstance(parsed, dict):
                res = parsed
        except Exception:
            res = {}

    if "book" not in res or not isinstance(res["book"], dict):
        res["book"] = {}
    if "registry" not in res or not isinstance(res["registry"], dict):
        res["registry"] = {}
    _normalise_pipeline_evidence(res)
    return res


_ID_WORDS = {"agree": "matches registry", "conflict": "conflicts with registry"}


def _normalise_pipeline_evidence(ev: dict[str, Any]) -> None:
    """Map the flat evidence_json written by sql/70 and sql/71 onto the book/registry shape
    the card templates read. Evidence that already has the nested shape is left alone."""
    book = ev["book"]
    if "name_a_raw" in ev and not book:  # RECORD_LINK
        ids = ev.get("id_status") or {}
        status = ids.get("PAN") if ids.get("PAN") in _ID_WORDS else (ids.get("CIN") if ids.get("CIN") in _ID_WORDS else None)
        word = _ID_WORDS.get(status or "")
        ev["book"] = {
            "source": ev.get("source_a"),
            "raw_name": ev.get("name_a_raw"),
            "pan": word,
            "address": ", ".join(p for p in (ev.get("city_a"), ev.get("state_a"), ev.get("pincode_a")) if p),
        }
        ev["registry"] = {
            "entity_name": ev.get("name_b_raw"),
            "pan": word,
            "address": ", ".join(p for p in (ev.get("city_b"), ev.get("state_b"), ev.get("pincode_b")) if p),
        }
    elif ev.get("kind") == "OWNERSHIP" and not book:
        strip = lambda k: str(k or "").removeprefix("E:")  # noqa: E731
        ev["book"] = {
            "holder_name": ev.get("holder_name"),
            "holder_cin": strip(ev.get("holder_entity_key")),
            "stake_pct": f"{ev['stake_pct']}%" if ev.get("stake_pct") is not None else None,
            "held_name": ev.get("held_name"),
            "held_cin": strip(ev.get("held_entity_key")),
        }
        ev["registry"] = {"filing_date": ev.get("filed_on")}
    elif ev.get("kind") == "CONTROL_RULING" and "holder_a" not in ev:
        stakes = ev.get("stakes") or {}
        shown = [f"{k.removeprefix('E:')} ({stakes[k]}%)" if k in stakes else k.removeprefix("E:") for k in ev.get("holders") or []]
        ev["held_entity"] = ev.get("held_name")
        ev["holder_a"] = shown[0] if shown else None
        ev["holder_b"] = ", ".join(shown[1:]) or None


def gauge_bar_width(util: Any) -> float:
    """Compute gauge fill width (0 to 35 units, 1 unit = 1% capital base)."""
    d = to_decimal(util)
    if d is None:
        return 0.0
    val = float(d)
    return round(min(35.0, max(0.0, val)), 1)


def gauge_bar_class(util: Any) -> str:
    """Determine CSS class for SVG gauge bar based on regulatory thresholds."""
    d = to_decimal(util)
    if d is None:
        return "gauge-bar"
    val = float(d)
    if val > 25.0:
        return "gauge-bar gauge-danger"
    elif val >= 10.0:
        return "gauge-bar gauge-warn"
    return "gauge-bar"
