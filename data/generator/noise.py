"""Name noise families. Each is a pure function (name, rng) -> name.

MISSING_ID is not a name family: it drops PAN / CIN and lives in generate.py.
"""

from __future__ import annotations

import random
import re

from data.generator.vocab import ABBREVIATIONS, TRANSLITERATIONS

# Tokens that make up legal suffixes; TYPO, OCR and WORD_ORDER leave them alone.
SUFFIX_TOKENS = {"PRIVATE", "LIMITED", "PVT", "LTD", "P.", "P", "PLC", "LLP", "M/S"}

_OCR_SWAPS = (("O", "0"), ("o", "0"), ("I", "1"), ("i", "1"), ("S", "5"), ("s", "5"), ("B", "8"), ("rn", "m"))


def _core_positions(tokens: list[str]) -> list[int]:
    return [i for i, t in enumerate(tokens) if t.upper() not in SUFFIX_TOKENS and len(t) >= 4]


def abbrev(name: str, rng: random.Random) -> str:
    """Private -> Pvt, Limited -> Ltd, Textiles -> Tex ... (every applicable word)."""
    out = []
    for tok in name.split(" "):
        out.append(ABBREVIATIONS.get(tok, tok))
    abbreviated = " ".join(out)
    if abbreviated == name:
        return name
    # "Pvt Ltd" also appears as "P. Ltd" in the books.
    if "Pvt Ltd" in abbreviated and rng.random() < 0.3:
        abbreviated = abbreviated.replace("Pvt Ltd", "P. Ltd")
    return abbreviated


def typo(name: str, rng: random.Random) -> str:
    """One character insert, delete, substitute or transpose in a non-suffix token."""
    tokens = name.split(" ")
    positions = _core_positions(tokens)
    if not positions:
        return name
    i = rng.choice(positions)
    tok = tokens[i]
    j = rng.randrange(1, len(tok) - 1)  # never the first letter, so the phonetic key survives
    op = rng.choice(("insert", "delete", "substitute", "transpose"))
    letter = rng.choice("abcdefghijklmnopqrstuvwxyz")
    if tok.isupper():
        letter = letter.upper()
    if op == "insert":
        tok = tok[:j] + letter + tok[j:]
    elif op == "delete":
        tok = tok[:j] + tok[j + 1:]
    elif op == "substitute":
        if tok[j].lower() == letter.lower():
            letter = "x" if letter.lower() != "x" else "z"
        tok = tok[:j] + letter + tok[j + 1:]
    else:
        if j + 1 < len(tok):
            tok = tok[:j] + tok[j + 1] + tok[j] + tok[j + 2:]
        else:
            tok = tok[:j - 1] + tok[j] + tok[j - 1]
    tokens[i] = tok
    return " ".join(tokens)


def ocr(name: str, rng: random.Random) -> str:
    """One OCR confusion (O/0, I/1, S/5, B/8, rn/m) in a non-suffix token."""
    tokens = name.split(" ")
    positions = _core_positions(tokens)
    rng.shuffle(positions)
    for i in positions:
        tok = tokens[i]
        options = [(a, b) for a, b in _OCR_SWAPS if a in tok[1:]]
        if options:
            a, b = rng.choice(options)
            k = tok.index(a, 1)
            tokens[i] = tok[:k] + b + tok[k + len(a):]
            return " ".join(tokens)
    return name


def ocr_pan(pan: str, rng: random.Random) -> str:
    """OCR damage on a PAN: a digit read as a letter, which makes the format invalid."""
    digit_to_letter = {"0": "O", "1": "I", "5": "S", "8": "B"}
    idx = [k for k in range(5, 9) if pan[k] in digit_to_letter]
    if not idx:
        k = rng.randrange(5, 9)
        return pan[:k] + "O" + pan[k + 1:]
    k = rng.choice(idx)
    return pan[:k] + digit_to_letter[pan[k]] + pan[k + 1:]


def translit(name: str, rng: random.Random) -> str:
    """Lakshmi <-> Laxmi, Kaveri <-> Cauvery, Shree <-> Shri <-> Sri ... (unseen in dev)."""
    pairs = list(TRANSLITERATIONS) + [(b, a) for a, b in TRANSLITERATIONS]
    rng.shuffle(pairs)
    for a, b in pairs:
        pattern = rf"\b{re.escape(a)}\b"
        if re.search(pattern, name):
            return re.sub(pattern, b, name, count=1)
    return name


def word_order(name: str, rng: random.Random) -> str:
    """Swap the first two non-suffix tokens ("Sunrise Textiles" -> "Textiles Sunrise")."""
    tokens = name.split(" ")
    core = [i for i, t in enumerate(tokens) if t.upper() not in SUFFIX_TOKENS]
    if len(core) < 2:
        return name
    a, b = core[0], core[1]
    tokens[a], tokens[b] = tokens[b], tokens[a]
    return " ".join(tokens)


FAMILY_FUNCS = {
    "ABBREV": abbrev,
    "TYPO": typo,
    "OCR": ocr,
    "TRANSLIT": translit,
    "WORD_ORDER": word_order,
}
