"""tests/test_formatting.py: Unit tests for Indian currency, percentage, and gauge formatting."""

from decimal import Decimal
import pytest

from ui.formatting import inr_cr, inr_full, percentage, gauge_bar_width, gauge_bar_class, parse_evidence


def test_inr_cr_formatting():
    # Standard plan requirement: 1120000000.00 -> ₹112.0 cr
    assert inr_cr(Decimal("1120000000.00")) == "₹112.0 cr"
    assert inr_cr(Decimal("400000000.00")) == "₹40.0 cr"
    assert inr_cr(Decimal("582000000.00")) == "₹58.2 cr"
    assert inr_cr(Decimal("312000000.00")) == "₹31.2 cr"
    assert inr_cr(Decimal("0.00")) == "₹0.0 cr"
    assert inr_cr(None) == "—"

    # Multi-decimal support
    assert inr_cr(Decimal("1120000000.00"), decimals=2) == "₹112.00 cr"
    assert inr_cr(Decimal("582000000.00"), decimals=2) == "₹58.20 cr"


def test_inr_full_indian_grouping():
    # Standard plan requirement: 1234567.89 -> ₹12,34,567.89
    assert inr_full(Decimal("1234567.89")) == "₹12,34,567.89"
    assert inr_full(Decimal("1000")) == "₹1,000.00"
    assert inr_full(Decimal("100")) == "₹100.00"
    assert inr_full(Decimal("0")) == "₹0.00"
    assert inr_full(Decimal("10000000.00")) == "₹1,00,00,000.00"
    assert inr_full(Decimal("1120000000.00")) == "₹1,12,00,00,000.00"
    assert inr_full(None) == "—"

    # Negative amounts
    assert inr_full(Decimal("-50000.50")) == "-₹50,000.50"


def test_percentage():
    assert percentage(Decimal("26.67")) == "26.7%"
    assert percentage(Decimal("7.43")) == "7.4%"
    assert percentage(Decimal("13.86")) == "13.9%"
    assert percentage(None) == "—"
    assert percentage(Decimal("26.666"), decimals=2) == "26.67%"


def test_gauge_bar_calculations():
    assert gauge_bar_width(0) == 0.0
    assert gauge_bar_width(7.43) == 7.4
    assert gauge_bar_width(26.67) == 26.7
    assert gauge_bar_width(50.0) == 35.0  # Clamped at 35 max
    assert gauge_bar_width(None) == 0.0

    assert gauge_bar_class(7.43) == "gauge-bar"
    assert gauge_bar_class(13.86) == "gauge-bar gauge-warn"
    assert gauge_bar_class(26.67) == "gauge-bar gauge-danger"
    assert gauge_bar_class(None) == "gauge-bar"


def test_parse_evidence():
    data = {"rule": "EXACT_PAN", "score": 1.0}
    res = parse_evidence(data)
    assert res["rule"] == "EXACT_PAN"
    assert res["score"] == 1.0
    assert "book" in res
    assert "registry" in res
    assert parse_evidence("invalid json") == {"book": {}, "registry": {}}
    assert parse_evidence(None) == {"book": {}, "registry": {}}
