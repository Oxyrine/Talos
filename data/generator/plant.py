"""Planted hard cases: counts, the hero group's figures, and the checks the generator
asserts before it writes a single file. Every planted case is also written to
TRUTH.GT_PLANT so the evaluator can score it.
"""

from __future__ import annotations

CR = 10_000_000          # one crore, in rupees
CAPITAL_BD3 = 420 * CR   # eligible capital in force for BD3 (the mid-period change)
CAPITAL_BD12 = 400 * CR
GROUP_LIMIT = CAPITAL_BD3 * 25 // 100
LE_LINE = CAPITAL_BD3 * 10 // 100

# Base counts (kept at these values for every scale; spec section 5.3).
COUNTS = {
    "REGISTRY_ONLY_PARENT": 60,
    "DIAMOND": 20,
    "CYCLE": 5,
    "ROOTLESS_CYCLE": 3,
    "JV": 10,
    "INTERDEP": 20,
    "DECOY": 30,
    "DECOY_IDENTICAL": 8,
    "ID_NAME_CONFLICT": 12,
    "HIDDEN_BREACH": 6,
    "LATE_CORRECTION_LOS": 10,
    "LATE_CORRECTION_GTE": 5,
    "POLICY_CHANGE": 1,
    "MINORITY_EDGE": 300,
    "SELF_OWNING": 2,
}

JV_RULINGS = ("SINGLE", "SINGLE", "SINGLE", "JOINT", "JOINT", "JOINT", "JOINT", "NONE", "NONE", "CONNECTED")

HERO_GROUP_NO = 17
HERO_FAMILY = "Sunrise"

# Hero group, BD3 known after the corrections (CONTRACT.md section 6.4), in rupees.
# Buckets say how each slice of exposure reaches Talos:
#   REPORTED  LOS rows and treasury / guarantee rows whose PAN matches an LOS customer (T0)
#   CIN_ONLY  treasury rows keyed by CIN only: T0, but invisible to the PAN VLOOKUP
#   T1        treasury / guarantee rows with no usable ID: T1 on name + pincode
HERO_BUCKETS = {
    "HEAD": {"REPORTED": 22 * CR, "CIN_ONLY": 92 * CR // 10, "T1": 9 * CR},
    "SUBS": {"REPORTED": 18 * CR, "CIN_ONLY": 9 * CR, "T1": 84 * CR // 10},
    "HOLDCO": {"REPORTED": 26 * CR},
    "HOLDSUB": {"REPORTED": 104 * CR // 10},
}

HERO_CHECKPOINTS = {
    "reported": 40 * CR,          # step 0: LOS map with exact-PAN consolidation (9.5%)
    "t0_head_only": 312 * CR // 10,   # step 1: T0 batch approved, head alone
    "after_ownership_batch": 582 * CR // 10,  # step 2: corroborated B-OWN batch approved
    "holdco_group": 364 * CR // 10,
    "after_t1": 756 * CR // 10,   # step 3: T1 cards approved, T3 same-PAN card rejected (18.0%)
    "after_holdco_link": 112 * CR,    # step 4: registry-only HoldCo edge approved (26.7%)
}


def pct(amount: int, capital: int = CAPITAL_BD3) -> float:
    return 100.0 * amount / capital
