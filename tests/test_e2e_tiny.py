"""tests/test_e2e_tiny.py: End-to-end integration test on tiny profile with live Exasol."""

import pytest

from orchestrator.db import is_exasol_available


@pytest.mark.exasol
def test_e2e_tiny_workflow():
    if not is_exasol_available():
        pytest.skip("Exasol not available")

    from eval.metrics import compute_metrics
    from eval.oracle import run_oracle
    from orchestrator.loader import load
    from orchestrator.pipeline import match
    from orchestrator.replay import replay

    # Step 1: Check loader with tiny data or seed
    out_dir = "data/out/tiny"
    try:
        from data.generator.generate import generate
        generate(profile="tiny", out_dir=out_dir, scale=0.2)
    except ImportError:
        pytest.skip("Generator not available yet")

    load_res = load(out_dir)
    assert len(load_res) > 0

    # Step 2: Match
    baseline = match("2026-09-30")
    assert baseline.status == "OK"
    assert baseline.output_hash is not None

    # Step 3: Oracle
    dec_stats = run_oracle(business_date="2026-09-30")
    assert isinstance(dec_stats, dict)

    # Step 4: Replay
    rep_res = replay(baseline.run_id)
    assert rep_res.matches is True

    # Step 5: Metrics
    metrics = compute_metrics(profile="tiny")
    assert "reduction_ratio" in metrics
    assert "replay_fidelity" in metrics
    assert metrics["replay_fidelity"] == 1.0
