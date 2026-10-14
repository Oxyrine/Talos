"""tests/test_packet_privacy.py: Verify LLM judge evaluation packets contain zero PII or financial amounts."""

import json

import pytest

from orchestrator.judge import CIN_REGEX, PAN_REGEX, build_privacy_safe_packet


def test_packet_has_no_raw_pan_or_cin_or_address_or_amounts():
    packet = build_privacy_safe_packet(
        pair_id="PAIR-001",
        name_a_std="KAVERI AGRO FOODS",
        name_b_std="KAVERI AGRO FOODS PRIVATE LIMITED",
        pincode_a="560001",
        pincode_b="560001",
        district_a="BENGALURU",
        district_b="BENGALURU",
        id_status={"PAN": "agree", "CIN": "missing", "LEI": "missing"},
        director_overlap=1,
        source_a="LOS",
        source_b="REG",
    )

    packet_str = json.dumps(packet)

    # 1. No PAN regex match
    assert not PAN_REGEX.search(packet_str)

    # 2. No CIN regex match
    assert not CIN_REGEX.search(packet_str)

    # 3. No address fields (street, road, line, etc.)
    forbidden_keys = {"address", "address_raw", "street", "road", "amount", "rupee", "exposure", "gross"}
    for k in packet:
        assert k.lower() not in forbidden_keys


def test_packet_rejects_raw_pan():
    with pytest.raises(ValueError, match="Privacy violation"):
        build_privacy_safe_packet(
            pair_id="PAIR-002",
            name_a_std="ABCDE1234F CORP",  # Embedded PAN format
            name_b_std="KAVERI AGRO",
            pincode_a="560001",
            pincode_b="560001",
            district_a="BENGALURU",
            district_b="BENGALURU",
            id_status={},
            director_overlap=0,
            source_a="LOS",
            source_b="REG",
        )


def test_packet_rejects_raw_cin():
    with pytest.raises(ValueError, match="Privacy violation"):
        build_privacy_safe_packet(
            pair_id="PAIR-003",
            name_a_std="KAVERI AGRO",
            name_b_std="U12345MH2020PTC123456 HOLDINGS",  # Embedded CIN format
            pincode_a="560001",
            pincode_b="560001",
            district_a="BENGALURU",
            district_b="BENGALURU",
            id_status={},
            director_overlap=0,
            source_a="LOS",
            source_b="REG",
        )
