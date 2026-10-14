"""tests/test_verdict.py: Strict schema validation tests for LLM judge verdicts."""

import json

from orchestrator.judge import validate_verdict

SAMPLE_PACKET = {
    "pair_id": "PAIR-1234",
    "name_a_std": "SUNRISE TEXTILES",
    "name_b_std": "SUNRISE TEXTILES PRIVATE LIMITED",
    "pincode_a": "400001",
    "pincode_b": "400001",
    "district_a": "MUMBAI",
    "district_b": "MUMBAI",
    "id_status": {"PAN": "missing", "CIN": "missing", "LEI": "missing"},
    "director_overlap": 0,
    "source_a": "LOS",
    "source_b": "REG",
}


def test_valid_verdict():
    response = json.dumps({
        "pair_id": "PAIR-1234",
        "decision": "same",
        "confidence": 0.95,
        "evidence_used": ["name_tokens", "pincode"],
        "rationale": "Identical stem and matching pincode."
    })
    v = validate_verdict(response, SAMPLE_PACKET, min_confidence=0.80)
    assert v["valid"] is True
    assert v["decision"] == "same"
    assert v["confidence"] == 0.95
    assert v["invalid_reason"] is None


def test_verdict_extra_key_rejected():
    response = json.dumps({
        "pair_id": "PAIR-1234",
        "decision": "same",
        "confidence": 0.95,
        "evidence_used": ["name_tokens"],
        "rationale": "Matching name.",
        "extra_field": "disallowed"
    })
    v = validate_verdict(response, SAMPLE_PACKET)
    assert v["valid"] is False
    assert v["decision"] == "unsure"
    assert "Keys mismatch" in v["invalid_reason"]


def test_verdict_invalid_decision():
    response = json.dumps({
        "pair_id": "PAIR-1234",
        "decision": "maybe",
        "confidence": 0.50,
        "evidence_used": ["name_tokens"],
        "rationale": "Not sure."
    })
    v = validate_verdict(response, SAMPLE_PACKET)
    assert v["valid"] is False
    assert v["decision"] == "unsure"
    assert "Invalid decision value" in v["invalid_reason"]


def test_verdict_out_of_vocabulary_evidence():
    response = json.dumps({
        "pair_id": "PAIR-1234",
        "decision": "same",
        "confidence": 0.85,
        "evidence_used": ["name_tokens", "hallucinated_feature"],
        "rationale": "Good match."
    })
    v = validate_verdict(response, SAMPLE_PACKET)
    assert v["valid"] is False
    assert v["decision"] == "unsure"
    assert "Unknown evidence tokens" in v["invalid_reason"]


def test_verdict_long_rationale_rejected():
    long_rationale = "word " * 45  # 45 words > 40 words
    response = json.dumps({
        "pair_id": "PAIR-1234",
        "decision": "same",
        "confidence": 0.90,
        "evidence_used": ["name_tokens"],
        "rationale": long_rationale.strip()
    })
    v = validate_verdict(response, SAMPLE_PACKET)
    assert v["valid"] is False
    assert v["decision"] == "unsure"
    assert "exceeded 40 words" in v["invalid_reason"]


def test_verdict_pair_id_mismatch():
    response = json.dumps({
        "pair_id": "DIFFERENT-ID",
        "decision": "same",
        "confidence": 0.90,
        "evidence_used": ["name_tokens"],
        "rationale": "Matching names."
    })
    v = validate_verdict(response, SAMPLE_PACKET)
    assert v["valid"] is False
    assert v["decision"] == "unsure"
    assert "pair_id mismatch" in v["invalid_reason"]


def test_verdict_malformed_json():
    response = "Not JSON at all!"
    v = validate_verdict(response, SAMPLE_PACKET)
    assert v["valid"] is False
    assert v["decision"] == "unsure"
    assert "Malformed JSON" in v["invalid_reason"]


def test_verdict_low_confidence_marked_valid_but_treated_unsure():
    """Schema is valid, but confidence < JUDGE_MIN_CONF: valid=True, effective decision=unsure."""
    response = json.dumps({
        "pair_id": "PAIR-1234",
        "decision": "same",
        "confidence": 0.65,  # Below 0.80
        "evidence_used": ["name_tokens"],
        "rationale": "Low confidence match."
    })
    v = validate_verdict(response, SAMPLE_PACKET, min_confidence=0.80)
    assert v["valid"] is True
    assert v["confidence"] == 0.65
    assert v["decision"] == "unsure"
