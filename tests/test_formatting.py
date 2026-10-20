"""tests/test_formatting.py: Unit tests for Indian currency, percentage, and gauge formatting."""

from decimal import Decimal

from ui.formatting import (
    gauge_bar_class,
    gauge_bar_width,
    inr_cr,
    inr_full,
    parse_evidence,
    percentage,
)


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


def test_parse_evidence_maps_pipeline_shapes():
    """sql/70 and sql/71 write flat evidence_json; the card templates read book/registry."""
    from ui.formatting import parse_evidence

    link = parse_evidence(
        '{"source_a":"LOS","name_a_raw":"Sunrise Inds Pvt Ltd","name_b_raw":"Sunrise Industries Limited",'
        '"city_a":"Mumbai","state_a":"MH","pincode_a":"400001","id_status":{"PAN":"agree","CIN":"missing","LEI":"missing"}}'
    )
    assert link["book"]["source"] == "LOS"
    assert link["book"]["raw_name"] == "Sunrise Inds Pvt Ltd"
    assert link["registry"]["entity_name"] == "Sunrise Industries Limited"
    assert link["book"]["pan"] == "matches registry"
    assert link["registry"]["pan"] == "matches registry"  # no entity_key: falls back to the status word

    keyed = parse_evidence('{"source_a":"TSY","name_a_raw":"A","name_b_raw":"A Ltd","entity_key":"E:U17110MH2018PLC000017",'
                           '"id_status":{"PAN":"missing","CIN":"missing","LEI":"missing"}}')
    assert keyed["registry"]["pan"] == "CIN U17110MH2018PLC000017"
    assert keyed["book"]["pan"] is None  # the book record carries no ID: the card says "Not provided"

    own = parse_evidence(
        '{"kind":"OWNERSHIP","holder_entity_key":"E:U1","held_entity_key":"E:U2","holder_name":"A","held_name":"B","stake_pct":100.0}'
    )
    assert own["book"]["holder_cin"] == "U1" and own["book"]["stake_pct"] == "100.0%"

    jv = parse_evidence('{"kind":"CONTROL_RULING","held_name":"JV","holders":["E:U1","E:U2"],"stakes":{"E:U1":50.0,"E:U2":50.0}}')
    assert jv["held_entity"] == "JV" and jv["holder_a"] == "U1 (50.0%)" and jv["holder_b"] == "U2 (50.0%)"
