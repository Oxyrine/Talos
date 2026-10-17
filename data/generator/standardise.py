"""Python mirror of sql/10_standardise.sql name rules.

The generator uses it to check that planted cases land where the plan says (for example,
that a hero record without IDs is within edit distance 2 of its registry name). The SQL
stays the source of truth; tests/test_generator.py keeps the two in step on samples.
"""

from __future__ import annotations

import re

from data.generator.vocab import ABBREVIATION_EXPANSIONS

_LEGAL = r"\b(PRIVATE|PVT|LIMITED|LTD|P|PLC|LLP|CO|COMPANY|CORPORATION|CORPN|INC|M S)\b"
_HONORIFICS = r"^((SHREE|SHRI|SRI|THE|NEW|M S) )+"


def name_std(raw: str) -> str:
    n = " " + re.sub(r"[^A-Z0-9]+", " ", raw.upper()) + " "
    for short, full in ABBREVIATION_EXPANSIONS.items():
        n = re.sub(rf"\b{short}\b", full, n)
    n = re.sub(_LEGAL, " ", n)
    return re.sub(r" +", " ", n).strip()


def first_token(std: str) -> str:
    stripped = re.sub(_HONORIFICS, "", std)
    m = re.search(r"[A-Z0-9]+", stripped)
    return m.group(0) if m else ""


def edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def name_sim(a_raw: str, b_raw: str) -> float:
    a, b = name_std(a_raw), name_std(b_raw)
    return 1 - edit_distance(a, b) / max(len(a), len(b), 1)
