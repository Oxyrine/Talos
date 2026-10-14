"""orchestrator/judge.py: LLM Judge for T2 candidate pairs with privacy filtering and schema validation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pyexasol import ExaConnection

from orchestrator.db import connect
from orchestrator.policy import load_thresholds

ALLOWED_EVIDENCE_TOKENS = {
    "name_tokens",
    "pincode",
    "district",
    "id_status",
    "director_overlap",
    "source_systems",
}

PAN_REGEX = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
CIN_REGEX = re.compile(r"\b[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}\b")


def build_privacy_safe_packet(
    pair_id: str,
    name_a_std: str,
    name_b_std: str,
    pincode_a: str | None,
    pincode_b: str | None,
    district_a: str | None,
    district_b: str | None,
    id_status: dict[str, str],
    director_overlap: int,
    source_a: str,
    source_b: str,
) -> dict[str, Any]:
    """Construct an LLM evaluation packet stripped of raw PAN, CIN, full addresses, and monetary amounts."""
    # Ensure id_status is standard
    clean_id_status = {
        "PAN": id_status.get("PAN", "missing"),
        "CIN": id_status.get("CIN", "missing"),
        "LEI": id_status.get("LEI", "missing"),
    }

    packet = {
        "pair_id": pair_id,
        "name_a_std": name_a_std,
        "name_b_std": name_b_std,
        "pincode_a": pincode_a or "",
        "pincode_b": pincode_b or "",
        "district_a": district_a or "",
        "district_b": district_b or "",
        "id_status": clean_id_status,
        "director_overlap": int(director_overlap),
        "source_a": source_a,
        "source_b": source_b,
    }

    # Verify packet privacy invariants
    packet_str = json.dumps(packet)
    if PAN_REGEX.search(packet_str) or CIN_REGEX.search(packet_str):
        raise ValueError("Privacy violation: raw PAN or CIN detected in packet.")

    return packet


def compute_packet_hash(packet: dict[str, Any]) -> str:
    """Compute deterministic SHA-256 hash of privacy packet."""
    canonical = json.dumps(packet, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_verdict(
    raw_response: str,
    packet: dict[str, Any],
    min_confidence: float = 0.80,
) -> dict[str, Any]:
    """Validate LLM response strictly against frozen schema.

    Returns normalized verdict dict with valid, invalid_reason, and effective decision.
    """
    pair_id = packet["pair_id"]
    try:
        data = json.loads(raw_response)
    except Exception as e:
        return {
            "pair_id": pair_id,
            "decision": "unsure",
            "confidence": 0.0,
            "evidence_used": "",
            "rationale": "",
            "valid": False,
            "invalid_reason": f"Malformed JSON: {e}",
        }

    if not isinstance(data, dict):
        return {
            "pair_id": pair_id,
            "decision": "unsure",
            "confidence": 0.0,
            "evidence_used": "",
            "rationale": "",
            "valid": False,
            "invalid_reason": "Response is not a JSON object",
        }

    # Strict key check: exactly the 5 declared keys, no extra keys
    expected_keys = {"pair_id", "decision", "confidence", "evidence_used", "rationale"}
    if set(data.keys()) != expected_keys:
        return {
            "pair_id": pair_id,
            "decision": "unsure",
            "confidence": 0.0,
            "evidence_used": "",
            "rationale": "",
            "valid": False,
            "invalid_reason": f"Keys mismatch. Expected {expected_keys}, got {set(data.keys())}",
        }

    if data["pair_id"] != pair_id:
        return {
            "pair_id": pair_id,
            "decision": "unsure",
            "confidence": 0.0,
            "evidence_used": "",
            "rationale": "",
            "valid": False,
            "invalid_reason": f"pair_id mismatch: expected {pair_id}, got {data['pair_id']}",
        }

    decision = str(data["decision"]).lower()
    if decision not in ("same", "different", "unsure"):
        return {
            "pair_id": pair_id,
            "decision": "unsure",
            "confidence": 0.0,
            "evidence_used": "",
            "rationale": "",
            "valid": False,
            "invalid_reason": f"Invalid decision value: {decision}",
        }

    try:
        confidence = float(data["confidence"])
        if not (0.0 <= confidence <= 1.0):
            raise ValueError
    except Exception:
        return {
            "pair_id": pair_id,
            "decision": "unsure",
            "confidence": 0.0,
            "evidence_used": "",
            "rationale": "",
            "valid": False,
            "invalid_reason": f"Confidence {data.get('confidence')} not in [0.0, 1.0]",
        }

    evidence = data["evidence_used"]
    if not isinstance(evidence, list):
        return {
            "pair_id": pair_id,
            "decision": "unsure",
            "confidence": confidence,
            "evidence_used": "",
            "rationale": "",
            "valid": False,
            "invalid_reason": "evidence_used must be a list",
        }

    if not set(evidence).issubset(ALLOWED_EVIDENCE_TOKENS):
        unknown = set(evidence) - ALLOWED_EVIDENCE_TOKENS
        return {
            "pair_id": pair_id,
            "decision": "unsure",
            "confidence": confidence,
            "evidence_used": ",".join(str(e) for e in evidence),
            "rationale": "",
            "valid": False,
            "invalid_reason": f"Unknown evidence tokens: {unknown}",
        }

    rationale = str(data.get("rationale", "")).strip()
    words = rationale.split()
    if len(words) > 40:
        return {
            "pair_id": pair_id,
            "decision": "unsure",
            "confidence": confidence,
            "evidence_used": ",".join(evidence),
            "rationale": rationale[:400],
            "valid": False,
            "invalid_reason": f"Rationale exceeded 40 words ({len(words)} words)",
        }

    # Schema valid!
    # If confidence < min_confidence, valid is True but effective decision treated as unsure
    effective_decision = decision
    if confidence < min_confidence and decision == "same":
        effective_decision = "unsure"

    return {
        "pair_id": pair_id,
        "decision": effective_decision,
        "confidence": confidence,
        "evidence_used": ",".join(evidence),
        "rationale": rationale,
        "valid": True,
        "invalid_reason": None,
    }


def stub_provider(packet: dict[str, Any]) -> str:
    """Deterministic stub provider returning valid 'unsure' verdict."""
    return json.dumps(
        {
            "pair_id": packet["pair_id"],
            "decision": "unsure",
            "confidence": 0.50,
            "evidence_used": ["name_tokens"],
            "rationale": "Deterministic stub provider always returns unsure verdict.",
        }
    )


PROVIDERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "stub": stub_provider,
}


async def evaluate_pair_async(
    packet: dict[str, Any],
    model: str = "stub",
    timeout: float = 20.0,
    min_confidence: float = 0.80,
    semaphore: asyncio.Semaphore | None = None,
) -> tuple[dict[str, Any], str, float]:
    """Execute model evaluation with concurrency control and timeout.

    Returns (validated_verdict, raw_response, latency_ms).
    """
    if semaphore is None:
        semaphore = asyncio.Semaphore(8)

    provider_fn = PROVIDERS.get(model, stub_provider)
    t0 = time.time()

    async with semaphore:
        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(provider_fn, packet),
                timeout=timeout,
            )
        except TimeoutError:
            latency = (time.time() - t0) * 1000
            return (
                {
                    "pair_id": packet["pair_id"],
                    "decision": "unsure",
                    "confidence": 0.0,
                    "evidence_used": "",
                    "rationale": "",
                    "valid": False,
                    "invalid_reason": f"Timeout after {timeout}s",
                },
                "",
                latency,
            )
        except Exception as e:
            latency = (time.time() - t0) * 1000
            return (
                {
                    "pair_id": packet["pair_id"],
                    "decision": "unsure",
                    "confidence": 0.0,
                    "evidence_used": "",
                    "rationale": "",
                    "valid": False,
                    "invalid_reason": f"Provider error: {e}",
                },
                "",
                latency,
            )

    latency = (time.time() - t0) * 1000
    validated = validate_verdict(raw, packet, min_confidence=min_confidence)
    return validated, raw, latency


def run_t2(conn: ExaConnection | None = None) -> int:
    """Evaluate T2 candidate pairs and log results to RESOLVE.LLM_VERDICT.

    Connects as TALOS_PIPELINE if conn is None.
    Skips pairs already present in RESOLVE.LLM_VERDICT with identical packet_hash and model.
    """
    close_conn = False
    if conn is None:
        conn = connect("pipeline", autocommit=True)
        close_conn = True

    model_config = os.environ.get("TALOS_JUDGE", "stub")
    thresholds = load_thresholds()
    min_conf = float(thresholds.get("JUDGE_MIN_CONF", 0.80))

    try:
        # Check if table exists
        stmt = conn.execute(
            """
            SELECT p.pair_key, ra.name_std as name_a, rb.name_std as name_b,
                   ra.pincode as pin_a, rb.pincode as pin_b,
                   ra.district as dist_a, rb.district as dist_b,
                   ra.source_system as src_a, rb.source_system as src_b,
                   p.conflict_types, p.id_agree, p.id_conflict
            FROM RESOLVE.PAIR_SCORE p
            JOIN STAGE.RECORD_STD ra ON p.rec_a = ra.rec_key
            JOIN STAGE.RECORD_STD rb ON p.rec_b = rb.rec_key
            WHERE p.tier = 'T2'
            """
        )
        t2_rows = stmt.fetchall()
        if not t2_rows:
            return 0

        packets: list[tuple[dict[str, Any], str, str]] = []
        for r in t2_rows:
            pair_k = r["pair_key"] if isinstance(r, dict) else r[0]
            name_a = r["name_a"] if isinstance(r, dict) else r[1]
            name_b = r["name_b"] if isinstance(r, dict) else r[2]
            pin_a = r["pin_a"] if isinstance(r, dict) else r[3]
            pin_b = r["pin_b"] if isinstance(r, dict) else r[4]
            dist_a = r["dist_a"] if isinstance(r, dict) else r[5]
            dist_b = r["dist_b"] if isinstance(r, dict) else r[6]
            src_a = r["src_a"] if isinstance(r, dict) else r[7]
            src_b = r["src_b"] if isinstance(r, dict) else r[8]

            id_status = {"PAN": "missing", "CIN": "missing", "LEI": "missing"}
            pkt = build_privacy_safe_packet(
                pair_id=pair_k,
                name_a_std=name_a or "",
                name_b_std=name_b or "",
                pincode_a=pin_a,
                pincode_b=pin_b,
                district_a=dist_a,
                district_b=dist_b,
                id_status=id_status,
                director_overlap=0,
                source_a=src_a or "BOOK",
                source_b=src_b or "REG",
            )
            pkt_hash = compute_packet_hash(pkt)
            packets.append((pkt, pkt_hash, pair_k))

        # Check existing cache
        existing_stmt = conn.execute(
            """
            SELECT packet_hash FROM RESOLVE.LLM_VERDICT
            WHERE model = {model}
            """,
            query_params={"model": model_config},
        )
        cached_hashes = {
            r["packet_hash"] if isinstance(r, dict) else r[0] for r in existing_stmt.fetchall()
        }

        to_evaluate = [p for p in packets if p[1] not in cached_hashes]
        if not to_evaluate:
            return 0

        async def _run_all():
            sem = asyncio.Semaphore(8)
            tasks = [
                evaluate_pair_async(
                    packet=pkt,
                    model=model_config,
                    min_confidence=min_conf,
                    semaphore=sem,
                )
                for pkt, _, _ in to_evaluate
            ]
            return await asyncio.gather(*tasks)

        results = asyncio.run(_run_all())

        now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        insert_sql = """
        INSERT INTO RESOLVE.LLM_VERDICT (
            pair_key, packet_hash, model, raw_response, decision,
            confidence, evidence_used, rationale, valid, invalid_reason,
            latency_ms, called_at
        ) VALUES (
            {pair_key}, {packet_hash}, {model}, {raw_response}, {decision},
            {confidence}, {evidence_used}, {rationale}, {valid}, {invalid_reason},
            {latency_ms}, {called_at}
        )
        """

        for (pkt, pkt_h, pair_k), (validated, raw_res, latency) in zip(to_evaluate, results):
            conn.execute(
                insert_sql,
                query_params={
                    "pair_key": pair_k,
                    "packet_hash": pkt_h,
                    "model": model_config,
                    "raw_response": raw_res[:4000],
                    "decision": validated["decision"],
                    "confidence": round(validated["confidence"], 3),
                    "evidence_used": validated["evidence_used"][:200],
                    "rationale": validated["rationale"][:400],
                    "valid": validated["valid"],
                    "invalid_reason": validated["invalid_reason"],
                    "latency_ms": int(latency),
                    "called_at": now_str,
                },
            )

        return len(to_evaluate)

    except Exception:
        return 0
    finally:
        if close_conn:
            conn.close()
