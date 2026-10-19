"""ui/mock_data.py: In-memory contract-compliant mock engine and state machine.

Operates strictly when TALOS_MOCK=1 is set in the environment.
Simulates the exact 5-stage hero journey for Sunrise Industries (Group 17) to the paisa:
- Step 0 (Baseline): Reported = ₹40.00 cr, Talos = "—", 0 breaches.
- Step 1 (T0 Batch): Sunrise Head alone = ₹31.20 cr (7.43%), under 10% line.
- Step 2 (Corroborated Batch): Sunrise Group = ₹58.20 cr (13.86%, crosses 10% line). HoldCo = ₹36.40 cr.
- Step 3 (T1 Approved + T3 Rejected): Sunrise Group = ₹75.60 cr (18.00%).
- Step 4 (Ownership Sunrise -> HoldCo): Sunrise Group = ₹112.00 cr (26.67%, BREACH > ₹105.00 cr).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

CAPITAL_BASE = Decimal("4200000000.00")  # ₹420.00 cr
GROUP_LIMIT_AMT = Decimal("1050000000.00")  # ₹105.00 cr (25%)
LARGE_EXPOSURE_AMT = Decimal("420000000.00")  # ₹42.00 cr (10%)


@dataclass
class MockState:
    step: int = 0  # 0 to 4
    decided_proposals: dict[str, dict[str, Any]] = field(default_factory=dict)
    active_batch_seeds: dict[str, int] = field(default_factory=dict)
    rulings: dict[str, dict[str, Any]] = field(default_factory=dict)


_STATE = MockState()


def get_mock_state() -> MockState:
    return _STATE


def reset_mock_state() -> None:
    global _STATE
    _STATE = MockState()


# -------------------------------------------------------------------------
# HMAC Seed Token Security
# -------------------------------------------------------------------------
_TOKEN_SECRET = b"talos_batch_seed_token_secret_key_32"


def generate_batch_token(user_id: str, batch_id: str, seed: int, proposal_ids: list[str]) -> str:
    """Issue HMAC token encoding user_id, batch_id, seed, proposal_hash, and 15m expiry."""
    expires_at = int(time.time()) + 900
    sorted_hash = hashlib.sha256(",".join(sorted(proposal_ids)).encode("utf-8")).hexdigest()
    payload = f"{user_id}:{batch_id}:{seed}:{sorted_hash}:{expires_at}"
    sig = hmac.new(_TOKEN_SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def verify_batch_token(token: str, user_id: str, batch_id: str, proposal_ids: list[str]) -> int:
    """Verify HMAC token and return seed. Raise ValueError on tamper or expiry."""
    try:
        u, b, seed_str, phash, exp_str, sig = token.split(":")
    except ValueError:
        raise ValueError("Malformed batch verification token.")

    if u != user_id or b != batch_id:
        raise ValueError("Batch token user or batch mismatch.")

    if int(exp_str) < time.time():
        raise ValueError("Batch verification token has expired (15-minute window).")

    expected_phash = hashlib.sha256(",".join(sorted(proposal_ids)).encode("utf-8")).hexdigest()
    if phash != expected_phash:
        raise ValueError("Batch proposals have changed since token issuance.")

    payload = f"{u}:{b}:{seed_str}:{phash}:{exp_str}"
    expected_sig = hmac.new(_TOKEN_SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_sig, sig):
        raise ValueError("Batch verification signature mismatch.")

    return int(seed_str)


# -------------------------------------------------------------------------
# Board Data Generation
# -------------------------------------------------------------------------
def get_mock_board_data(business_date: str = "2026-09-30", sort: str = "hidden", view: str = "talos") -> dict[str, Any]:
    state = get_mock_state()

    # Sunrise Group Metrics across the 5 steps
    sunrise_reported = Decimal("400000000.00")  # ₹40.00 cr

    if state.step == 0:
        sunrise_talos = None
        sunrise_hidden = Decimal("0.00")
        sunrise_util = Decimal("0.00")
        sunrise_breach = False
        sunrise_large = False
        breaches_count = 0
        large_count = 0
        hidden_exposure_total = Decimal("0.00")
    elif state.step == 1:
        sunrise_talos = Decimal("312000000.00")  # ₹31.20 cr (head entity alone)
        sunrise_hidden = Decimal("0.00")  # Clamped: max(0, 31.2 - 40.0)
        sunrise_util = (sunrise_talos / CAPITAL_BASE) * Decimal("100")
        sunrise_breach = False
        sunrise_large = False
        breaches_count = 0
        large_count = 0
        hidden_exposure_total = Decimal("0.00")
    elif state.step == 2:
        sunrise_talos = Decimal("582000000.00")  # ₹58.20 cr (group forms)
        sunrise_hidden = sunrise_talos - sunrise_reported  # +₹18.20 cr
        sunrise_util = (sunrise_talos / CAPITAL_BASE) * Decimal("100")
        sunrise_breach = False
        sunrise_large = True  # Crosses 10%
        breaches_count = 0
        large_count = 1
        hidden_exposure_total = sunrise_hidden
    elif state.step == 3:
        sunrise_talos = Decimal("756000000.00")  # ₹75.60 cr
        sunrise_hidden = sunrise_talos - sunrise_reported  # +₹35.60 cr
        sunrise_util = (sunrise_talos / CAPITAL_BASE) * Decimal("100")
        sunrise_breach = False
        sunrise_large = True
        breaches_count = 0
        large_count = 1
        hidden_exposure_total = sunrise_hidden
    else:  # step >= 4
        sunrise_talos = Decimal("1120000000.00")  # ₹112.00 cr (BREACH)
        sunrise_hidden = sunrise_talos - sunrise_reported  # +₹72.00 cr
        sunrise_util = (sunrise_talos / CAPITAL_BASE) * Decimal("100")
        sunrise_breach = True
        sunrise_large = True
        breaches_count = 1
        large_count = 1
        hidden_exposure_total = sunrise_hidden

    groups = [
        {
            "group_key": "E:L17110MH2018PLC000017",
            "group_name": "Sunrise Industries Group",
            "head_entity_key": "E:L17110MH2018PLC000017",
            "member_count": 8 if state.step >= 4 else (6 if state.step >= 2 else 1),
            "reported_exposure": sunrise_reported,
            "limit_exposure": sunrise_talos,
            "hidden_exposure": sunrise_hidden,
            "capital_base": CAPITAL_BASE,
            "utilisation_pct": sunrise_util,
            "is_large": sunrise_large,
            "is_breach": sunrise_breach,
            "group_flags": "",
            "headroom": max(Decimal("0"), GROUP_LIMIT_AMT - (sunrise_talos or Decimal("0"))),
        },
        {
            "group_key": "E:U24100GJ2015PLC000042",
            "group_name": "Kaveri Chemicals Group",
            "head_entity_key": "E:U24100GJ2015PLC000042",
            "member_count": 5,
            "reported_exposure": Decimal("380000000.00"),
            "limit_exposure": Decimal("380000000.00"),
            "hidden_exposure": Decimal("0.00"),
            "capital_base": CAPITAL_BASE,
            "utilisation_pct": Decimal("9.05"),
            "is_large": False,
            "is_breach": False,
            "group_flags": "",
            "headroom": GROUP_LIMIT_AMT - Decimal("380000000.00"),
        },
        {
            "group_key": "E:U45200DL2019PLC000088",
            "group_name": "Deccan Infra Group",
            "head_entity_key": "E:U45200DL2019PLC000088",
            "member_count": 4,
            "reported_exposure": Decimal("290000000.00"),
            "limit_exposure": Decimal("290000000.00"),
            "hidden_exposure": Decimal("0.00"),
            "capital_base": CAPITAL_BASE,
            "utilisation_pct": Decimal("6.90"),
            "is_large": False,
            "is_breach": False,
            "group_flags": "",
            "headroom": GROUP_LIMIT_AMT - Decimal("290000000.00"),
        },
    ]

    # HoldCo group appears at Step 2 and merges into Sunrise at Step 4
    if 2 <= state.step < 4:
        holdco_exp = Decimal("364000000.00")
        groups.append({
            "group_key": "E:U65990MH2020PTC000999",
            "group_name": "Sunrise Finvest Group",
            "head_entity_key": "E:U65990MH2020PTC000999",
            "member_count": 3,
            "reported_exposure": Decimal("0.00"),  # Reported under different map
            "limit_exposure": holdco_exp,
            "hidden_exposure": holdco_exp,
            "capital_base": CAPITAL_BASE,
            "utilisation_pct": (holdco_exp / CAPITAL_BASE) * Decimal("100"),
            "is_large": False,
            "is_breach": False,
            "group_flags": "",
            "headroom": GROUP_LIMIT_AMT - holdco_exp,
        })
        hidden_exposure_total += holdco_exp

    # Sorting
    if sort == "util":
        groups.sort(key=lambda g: g["utilisation_pct"], reverse=True)
    elif sort == "hidden":
        groups.sort(key=lambda g: g["hidden_exposure"], reverse=True)
    else:
        groups.sort(key=lambda g: g["limit_exposure"] or Decimal("0"), reverse=True)

    return {
        "run_id": f"R-20261011120000-step{state.step}",
        "business_date": business_date,
        "known_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
        "kpi": {
            "hidden_exposure": hidden_exposure_total,
            "breaches_count": breaches_count,
            "large_count": large_count,
            "unassigned_exposure": Decimal("54200000.00") if state.step < 4 else Decimal("0.00"),
        },
        "groups": groups,
    }


# -------------------------------------------------------------------------
# Proposal Queue Data Generation
# -------------------------------------------------------------------------
def get_mock_queue_data(page: int = 1, per_page: int = 25, tier: str = "", kind: str = "") -> dict[str, Any]:
    state = get_mock_state()

    # Active batches (disappear when approved)
    batches = []
    if state.step < 1 and (not kind or kind == "RECORD_LINK"):
        batches.append({
            "batch_id": "B-REC-2026101101",
            "batch_kind": "RECORD_LINK",
            "title": "Exact-ID Record Links Batch",
            "desc": "1,912 Exact-ID matches waiting. Review a representative sample of 96 to approve.",
            "total_count": 1912,
            "sample_count": 96,
        })
    if state.step < 2 and (not kind or kind == "OWNERSHIP"):
        batches.append({
            "batch_id": "B-OWN-2026101101",
            "batch_kind": "OWNERSHIP",
            "title": "Corroborated Ownership Edges Batch",
            "desc": "3,540 routine registry ownership edges corroborated by LOS customer codes. Review sample of 71 to approve.",
            "total_count": 3540,
            "sample_count": 71,
        })

    # Individual cards
    all_cards = []

    # Card 1: Uncorroborated Ownership Sunrise -> HoldCo (The Breach Maker)
    p_own = "P-OWN-SUNRISE-HOLDCO"
    if p_own not in state.decided_proposals:
        all_cards.append({
            "proposal_id": p_own,
            "kind": "OWNERSHIP",
            "subject_key": "CONTROL:E:L17110MH2018PLC000017>E:U65990MH2020PTC000999",
            "tier": "T1",
            "tier_reason": "REGISTRY_PARENT_EDGE",
            "rupee_impact": Decimal("364000000.00"),
            "crosses_limit": 1 if state.step == 3 else 0,
            "crosses_le": 0,
            "group_before_pct": Decimal("18.00") if state.step >= 3 else Decimal("13.86"),
            "group_after_pct": Decimal("26.67"),
            "group_name": "Sunrise Industries Group",
            "headline": "Approving moves Sunrise Industries Group from 18.0% to 26.7% of capital (crosses 25% limit) by acquiring Sunrise Finvest group (₹36.40 cr).",
            "evidence_json": json.dumps({
                "book": {
                    "source": "REGISTRY",
                    "holder_cin": "L17110MH2018PLC000017",
                    "holder_name": "Sunrise Industries Limited",
                    "held_cin": "U65990MH2020PTC000999",
                    "held_name": "Sunrise Finvest Private Limited",
                    "stake_pct": "100.00%",
                    "control_flag": True,
                },
                "registry": {
                    "filing_date": "2026-06-15",
                    "mca_status": "Active",
                    "note": "Ownership edge absent in bank LOS customer group code.",
                },
                "id_status": {"CIN": "agree", "PAN": "agree"},
            }),
        })

    # Card 2: Hero T1 Guarantee Card (Legitimate Guarantee)
    p_t1_gte = "P-REC-GTE-SUNRISE-TRUE"
    if p_t1_gte not in state.decided_proposals:
        all_cards.append({
            "proposal_id": p_t1_gte,
            "kind": "RECORD_LINK",
            "subject_key": "GTE:GTE-009841>E:L17110MH2018PLC000017",
            "tier": "T1",
            "tier_reason": "STRONG_NAME_PIN",
            "rupee_impact": Decimal("174000000.00"),
            "crosses_limit": 0,
            "crosses_le": 1 if state.step == 2 else 0,
            "group_before_pct": Decimal("13.86"),
            "group_after_pct": Decimal("18.00"),
            "group_name": "Sunrise Industries Group",
            "headline": "Approving consolidates Sunrise Guarantee book (+₹17.40 cr) into Sunrise Industries Group.",
            "evidence_json": json.dumps({
                "book": {
                    "source": "GTE",
                    "raw_name": "Sunrise Inds Ltd (Mumbai Br)",
                    "std_name": "SUNRISE INDUSTRIES",
                    "address": "42 Nariman Point, Mumbai - 400021",
                    "pan": None,
                    "cin": None,
                },
                "registry": {
                    "entity_name": "Sunrise Industries Limited",
                    "std_name": "SUNRISE INDUSTRIES",
                    "cin": "L17110MH2018PLC000017",
                    "pan": "AAACS1234F",
                    "city": "Mumbai",
                    "pincode": "400021",
                },
                "id_status": {"PAN": "missing", "CIN": "missing"},
                "metrics": {"name_sim": 0.94, "pin_match": True, "state_match": True},
            }),
        })

    # Card 3: Hero T3 Conflict Card (Same-PAN Mismatch Beat)
    p_t3_gte = "P-REC-GTE-SUNRISE-CONFLICT"
    if p_t3_gte not in state.decided_proposals:
        all_cards.append({
            "proposal_id": p_t3_gte,
            "kind": "RECORD_LINK",
            "subject_key": "GTE:GTE-009841>E:U24100GJ2015PLC000042",
            "tier": "T3",
            "tier_reason": "ID_NAME_CONFLICT",
            "rupee_impact": Decimal("174000000.00"),
            "crosses_limit": 0,
            "crosses_le": 0,
            "group_before_pct": Decimal("9.05"),
            "group_after_pct": Decimal("13.19"),
            "group_name": "Kaveri Chemicals Group",
            "headline": "CAUTION: Keyed with Kaveri Chemicals PAN, but borrower name is Sunrise Inds Ltd. Reject false link.",
            "evidence_json": json.dumps({
                "book": {
                    "source": "GTE",
                    "raw_name": "Sunrise Inds Ltd",
                    "std_name": "SUNRISE INDUSTRIES",
                    "pan": "AAACK9999K",  # Kaveri PAN mistakenly entered in LOS
                },
                "registry": {
                    "entity_name": "Kaveri Chemicals Limited",
                    "std_name": "KAVERI CHEMICALS",
                    "cin": "U24100GJ2015PLC000042",
                    "pan": "AAACK9999K",
                    "city": "Ahmedabad",
                },
                "id_status": {"PAN": "conflict_name"},
                "metrics": {"name_sim": 0.21, "pin_match": False, "state_match": False},
            }),
        })

    # Card 4: JV 50/50 Control Ruling
    p_jv = "P-RULING-JV-01"
    if p_jv not in state.rulings:
        all_cards.append({
            "proposal_id": p_jv,
            "kind": "CONTROL_RULING",
            "subject_key": "JV:E:U45200MH2021PTC000555",
            "tier": "T2",
            "tier_reason": "DUAL_50PCT_HOLDERS",
            "rupee_impact": Decimal("54200000.00"),
            "crosses_limit": 0,
            "crosses_le": 0,
            "group_before_pct": Decimal("0.00"),
            "group_after_pct": Decimal("0.00"),
            "group_name": "Konark Deccan Infra JV",
            "headline": "50/50 Joint Venture between Konark Steels (50%) and Deccan Infra (50%). Live ruling required.",
            "evidence_json": json.dumps({
                "held_entity": "Konark Deccan Infra JV Private Limited",
                "holder_a": "Konark Steels Limited (50.00% - Control Flag)",
                "holder_b": "Deccan Infra Limited (50.00% - Control Flag)",
                "exposure": "₹5.42 cr",
            }),
        })

    # Filter by tier and kind
    filtered = all_cards
    if tier:
        filtered = [c for c in filtered if c["tier"] == tier]
    if kind:
        filtered = [c for c in filtered if c["kind"] == kind]

    # Rank: crosses_limit DESC, crosses_le DESC, rupee_impact DESC
    filtered.sort(key=lambda c: (c["crosses_limit"], c["crosses_le"], c["rupee_impact"]), reverse=True)

    # Server-side pagination
    total_items = len(filtered)
    total_pages = max(1, math.ceil(total_items / per_page))
    page = min(max(1, page), total_pages)
    start_idx = (page - 1) * per_page
    paginated_cards = filtered[start_idx : start_idx + per_page]

    return {
        "batches": batches,
        "proposals": paginated_cards,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total_items": total_items,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        },
    }


# -------------------------------------------------------------------------
# Batch Sample Review Data
# -------------------------------------------------------------------------
def get_mock_batch_data(batch_id: str, user_name: str) -> dict[str, Any]:
    state = get_mock_state()

    is_rec = "REC" in batch_id
    total_count = 1912 if is_rec else 3540
    sample_count = 96 if is_rec else 71

    seed = state.active_batch_seeds.get(batch_id)
    if seed is None:
        seed = secrets.randbits(31)
        state.active_batch_seeds[batch_id] = seed

    # Generate sample items
    sample_items = []
    proposal_ids = []
    for i in range(sample_count):
        pid = f"{batch_id}-PAIR-{i+1:04d}"
        proposal_ids.append(pid)
        sample_items.append({
            "proposal_id": pid,
            "source_a": "LOS:C-00" + str(1000 + i),
            "name_a": f"Borrower Unit {i+1} Pvt Ltd",
            "pan_a": f"AAACB{i+1:04d}F",
            "source_b": "REG:U" + str(2000 + i),
            "name_b": f"Borrower Unit {i+1} Private Limited",
            "pan_b": f"AAACB{i+1:04d}F",
            "status": "EXACT_PAN Match",
        })

    token = generate_batch_token(user_name, batch_id, seed, proposal_ids)

    return {
        "batch_id": batch_id,
        "batch_kind": "RECORD_LINK" if is_rec else "OWNERSHIP",
        "title": "Exact-ID Record Links" if is_rec else "Corroborated Ownership Edges",
        "total_count": total_count,
        "sample_count": sample_count,
        "seed": seed,
        "token": token,
        "items": sample_items,
    }


# -------------------------------------------------------------------------
# Decision Execution
# -------------------------------------------------------------------------
def execute_mock_decision(proposal_id: str, decision: str, reason: str, reviewer_name: str) -> dict[str, Any]:
    state = get_mock_state()

    state.decided_proposals[proposal_id] = {
        "decision": decision,
        "reason": reason,
        "reviewer": reviewer_name,
        "decided_at": datetime.now(UTC).isoformat(),
    }

    # Advance state machine based on decisions
    if proposal_id == "P-REC-GTE-SUNRISE-TRUE" and decision == "APPROVE":
        if state.step < 3:
            state.step = 3
    elif proposal_id == "P-OWN-SUNRISE-HOLDCO" and decision == "APPROVE":
        state.step = 4

    board = get_mock_board_data()
    return {
        "proposal_id": proposal_id,
        "decision": decision,
        "kpi": board["kpi"],
    }


def execute_mock_batch(
    batch_id: str,
    seed: int,
    token: str,
    verdicts: dict[str, bool],
    reason: str,
    reviewer_name: str,
) -> dict[str, Any]:
    state = get_mock_state()

    # Advance step on batch approvals
    if "REC" in batch_id:
        if all(verdicts.values()):
            if state.step < 1:
                state.step = 1
    elif "OWN" in batch_id:
        if all(verdicts.values()):
            if state.step < 2:
                state.step = 2

    board = get_mock_board_data()
    return {
        "batch_id": batch_id,
        "status": "BATCH_APPROVE" if all(verdicts.values()) else "BATCH_FAILED",
        "kpi": board["kpi"],
    }


def execute_mock_ruling(
    proposal_id: str,
    ruling: str,
    controller: str | None,
    reason: str,
    reviewer_name: str,
) -> dict[str, Any]:
    state = get_mock_state()
    state.rulings[proposal_id] = {
        "ruling": ruling,
        "controller": controller,
        "reason": reason,
        "reviewer": reviewer_name,
        "decided_at": datetime.now(UTC).isoformat(),
    }
    board = get_mock_board_data()
    return {
        "proposal_id": proposal_id,
        "ruling": ruling,
        "kpi": board["kpi"],
    }


# -------------------------------------------------------------------------
# Lineage, Pipeline, and Audit Data
# -------------------------------------------------------------------------
def get_mock_lineage_group_data(group_key: str, run_id: str | None = None) -> dict[str, Any]:
    state = get_mock_state()
    is_latest = (run_id is None or "step" not in run_id or int(run_id.split("step")[-1]) == state.step)

    # Ownership tree nodes
    tree_nodes = [
        {"entity_name": "Sunrise Industries Limited", "depth": 0, "is_head": True, "stake_pct": "Head", "closes_cycle": False},
        {"entity_name": "Sunrise Textiles Private Limited", "depth": 1, "is_head": False, "stake_pct": "100.0%", "closes_cycle": False},
        {"entity_name": "Sunrise Agro Foods Private Limited", "depth": 1, "is_head": False, "stake_pct": "74.5%", "closes_cycle": False},
        {"entity_name": "Sunrise Steels Private Limited", "depth": 2, "is_head": False, "stake_pct": "51.0%", "closes_cycle": False},
    ]

    if state.step >= 4:
        tree_nodes.extend([
            {"entity_name": "Sunrise Finvest Private Limited (HoldCo)", "depth": 1, "is_head": False, "stake_pct": "100.0%", "closes_cycle": False},
            {"entity_name": "Sunrise Infra Projects Private Limited", "depth": 2, "is_head": False, "stake_pct": "100.0%", "closes_cycle": False},
            {"entity_name": "Sunrise Logistics Private Limited", "depth": 2, "is_head": False, "stake_pct": "60.0%", "closes_cycle": False},
        ])

    # Members list
    members = [
        {"entity_key": "E:L17110MH2018PLC000017", "entity_name": "Sunrise Industries Limited", "exposure": Decimal("312000000.00"), "books": "LOS, TSY"},
        {"entity_key": "E:U17110MH2019PTC000018", "entity_name": "Sunrise Textiles Private Limited", "exposure": Decimal("150000000.00"), "books": "LOS"},
        {"entity_key": "E:U15100GJ2020PTC000019", "entity_name": "Sunrise Agro Foods Private Limited", "exposure": Decimal("120000000.00"), "books": "LOS"},
        {"entity_key": "E:U27100MH2021PTC000020", "entity_name": "Sunrise Steels Private Limited", "exposure": Decimal("174000000.00"), "books": "GTE"},
    ]

    return {
        "group_key": group_key,
        "group_name": "Sunrise Industries Group",
        "run_id": run_id or f"R-20261011120000-step{state.step}",
        "is_latest": is_latest,
        "tree_nodes": tree_nodes if is_latest else [],
        "members": members,
    }


def get_mock_lineage_rows_data(group_key: str, source: str = "", product: str = "", run_id: str | None = None) -> list[dict[str, Any]]:
    return [
        {
            "entity_name": "Sunrise Industries Limited",
            "source_system": "LOS",
            "source_row_id": "LN-2026-00194",
            "product": "TERM_LOAN",
            "component": "FUNDED",
            "gross_amount": Decimal("250000000.00"),
            "ccf": Decimal("1.0000"),
            "exposure_amount": Decimal("250000000.00"),
            "proposal_id": "P-REC-T0-0012",
            "decision_id": "D-20261011120000-0001",
            "reviewer": "Aakash A",
            "decided_at": "2026-10-11 12:00:00",
            "tier": "T0",
        },
        {
            "entity_name": "Sunrise Industries Limited",
            "source_system": "TSY",
            "source_row_id": "CP-2026-00042",
            "product": "CP",
            "component": "HOLDING",
            "gross_amount": Decimal("62000000.00"),
            "ccf": Decimal("1.0000"),
            "exposure_amount": Decimal("62000000.00"),
            "proposal_id": "P-REC-T0-0013",
            "decision_id": "D-20261011120000-0002",
            "reviewer": "Aakash A",
            "decided_at": "2026-10-11 12:00:00",
            "tier": "T0",
        },
        {
            "entity_name": "Sunrise Steels Private Limited",
            "source_system": "GTE",
            "source_row_id": "GTE-2026-009841",
            "product": "FIN",
            "component": "GTE_FIN",
            "gross_amount": Decimal("174000000.00"),
            "ccf": Decimal("1.0000"),
            "exposure_amount": Decimal("174000000.00"),
            "proposal_id": "P-REC-GTE-SUNRISE-TRUE",
            "decision_id": "D-20261011120500-0008",
            "reviewer": "Aakash A",
            "decided_at": "2026-10-11 12:05:00",
            "tier": "T1",
        },
    ]


def get_mock_pipeline_data() -> dict[str, Any]:
    return {
        "job_id": "JOB-MATCH-20261011",
        "timings": [
            {"stage": "10_standardise", "rows": 29000, "seconds": 1.42},
            {"stage": "20_id_tokens_exact", "rows": 38400, "seconds": 0.85},
            {"stage": "30_block_keys", "rows": 87000, "seconds": 1.12},
            {"stage": "31_candidates_blocked", "rows": 24500, "seconds": 2.05},
            {"stage": "40_score_tier", "rows": 24500, "seconds": 1.95},
            {"stage": "51_components_init", "rows": 4000, "seconds": 0.22},
            {"stage": "52_components_pass", "rows": 3800, "seconds": 1.84},
            {"stage": "60_entity_exposure", "rows": 29000, "seconds": 0.65},
            {"stage": "62_run_output", "rows": 29000, "seconds": 0.95},
        ],
        "paths": [
            {"via_path": "EXACT_PAN", "count": 18200},
            {"via_path": "EXACT_CIN", "count": 2100},
            {"via_path": "P1 (Soundex+State)", "count": 3200},
            {"via_path": "P2 (Soundex+PIN)", "count": 1000},
        ],
        "tiers": [
            {"tier": "T0 (Exact ID)", "count": 1912},
            {"tier": "T1 (Strong Name/PIN)", "count": 4720},
            {"tier": "T2 (Grey Band)", "count": 84},
            {"tier": "T3 (Conflict)", "count": 12},
            {"tier": "DISCARD_LOW_SCORE", "count": 17772},
        ],
        "summary": {
            "total_book_records": 25000,
            "total_reg_entities": 4000,
            "total_candidates": 24500,
            "settled_in_sql_pct": Decimal("100.0"),  # 0% external model with stub
            "sent_to_model_pct": Decimal("0.0"),
            "reduction_ratio": Decimal("99.975"),
        },
    }


def get_mock_audit_data() -> list[dict[str, Any]]:
    state = get_mock_state()
    return [
        {
            "run_id": f"R-20261011120000-step{state.step}",
            "business_date": "2026-09-30",
            "known_at": "2026-10-11 12:00:00",
            "code_version": "f654528",
            "output_hash": "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            "status": "OK",
            "replay_of": None,
        },
        {
            "run_id": "R-20260831120000-0001",
            "business_date": "2026-08-31",
            "known_at": "2026-09-02 06:00:00",
            "code_version": "b631e20",
            "output_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "status": "OK",
            "replay_of": None,
        },
    ]
