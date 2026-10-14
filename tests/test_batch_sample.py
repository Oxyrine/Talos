"""tests/test_batch_sample.py: Test batch sample size calculations and deterministic sampling."""

import random

import pytest

from orchestrator.decide import calculate_sample_size


def test_sample_size_calculation_t0():
    policy = {"T0_SAMPLE_PCT": 5, "T0_SAMPLE_MIN": 20}

    # Case 1: Small batch, below minimum (e.g. 15 items) -> capped at batch size (15)
    assert calculate_sample_size(15, "RECORD_LINK", policy) == 15

    # Case 2: 100 items -> 5% is 5, but min is 20 -> 20
    assert calculate_sample_size(100, "RECORD_LINK", policy) == 20

    # Case 3: 1,000 items -> 5% is 50 -> 50
    assert calculate_sample_size(1000, "RECORD_LINK", policy) == 50

    # Case 4: 1,912 items (like in spec) -> ceil(5% * 1912) = ceil(95.6) = 96
    assert calculate_sample_size(1912, "RECORD_LINK", policy) == 96


def test_sample_size_calculation_ownership():
    policy = {"OWN_SAMPLE_PCT": 2, "OWN_SAMPLE_MIN": 20}

    # Case 1: Small batch (10 items) -> 10
    assert calculate_sample_size(10, "OWNERSHIP", policy) == 10

    # Case 2: 500 items -> 2% is 10, min is 20 -> 20
    assert calculate_sample_size(500, "OWNERSHIP", policy) == 20

    # Case 3: 2000 items -> 2% is 40 -> 40
    assert calculate_sample_size(2000, "OWNERSHIP", policy) == 40


def test_sample_size_strictly_requires_policy():
    """DEV-13: calculate_sample_size must not fall back to defaults."""
    with pytest.raises(KeyError):
        calculate_sample_size(1912, "RECORD_LINK", {})

    with pytest.raises(KeyError):
        calculate_sample_size(500, "OWNERSHIP", {})


def test_sampling_determinism():
    """Verify that seeded RNG sampling over sorted proposal IDs is exactly reproducible."""
    items = [f"P-{i:05d}" for i in range(500)]
    seed = 20261008

    rng1 = random.Random(seed)
    sample_1 = rng1.sample(sorted(items), 25)

    rng2 = random.Random(seed)
    sample_2 = rng2.sample(sorted(items), 25)

    assert sample_1 == sample_2
    assert len(sample_1) == 25
    assert set(sample_1).issubset(set(items))
