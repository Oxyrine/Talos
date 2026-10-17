"""Generator profiles: dev, test, scale and tiny."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

DEV_FAMILIES: tuple[str, ...] = ("ABBREV", "TYPO", "OCR")
TEST_FAMILIES: tuple[str, ...] = ("ABBREV", "TYPO", "OCR", "TRANSLIT", "WORD_ORDER")


@dataclass(frozen=True)
class Profile:
    name: str
    seed: int | None          # None: the seed must come from --seed or --seed-from-commit
    name_families: tuple[str, ...]
    scale: float


PROFILES: dict[str, Profile] = {
    "dev": Profile("dev", 20261008, DEV_FAMILIES, 1.0),
    "test": Profile("test", None, TEST_FAMILIES, 1.0),
    "scale": Profile("scale", 20261008, DEV_FAMILIES, 10.0),
    "tiny": Profile("tiny", 7, DEV_FAMILIES, 0.2),
}


def seed_from_commit(commit_sha: str) -> int:
    """The held-out test seed: int(sha256(freeze_commit_sha)[:8], 16)."""
    return int(hashlib.sha256(commit_sha.strip().encode("utf-8")).hexdigest()[:8], 16)


def resolve(profile: str, scale: float | None, seed: int | None, seed_commit: str | None) -> tuple[Profile, int, float]:
    """Return (profile, seed, scale) after applying command-line overrides."""
    if profile not in PROFILES:
        raise ValueError(f"Unknown profile {profile!r}; expected one of {sorted(PROFILES)}")
    prof = PROFILES[profile]
    if seed_commit:
        seed = seed_from_commit(seed_commit)
    if seed is None:
        seed = prof.seed
    if seed is None:
        raise ValueError("The test profile needs --seed-from-commit <freeze sha> (or --seed).")
    # The CLI passes scale=1.0 by default; only an explicit non-default overrides the profile.
    eff_scale = prof.scale if scale in (None, 1.0) else float(scale)
    return prof, seed, eff_scale
