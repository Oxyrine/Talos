"""The held-out test profile has no default seed, so `talos eval --profile test` must be able to take one."""

import pytest

from data.generator.profiles import resolve, seed_from_commit
from orchestrator.cli import main


def test_test_profile_needs_a_freeze_commit():
    with pytest.raises(ValueError, match="seed-from-commit"):
        resolve("test", None, None, None)
    _, seed, _ = resolve("test", None, None, "abc123")
    assert seed == seed_from_commit("abc123")


def test_eval_accepts_seed_from_commit(capsys):
    with pytest.raises(SystemExit):
        main(["eval", "--help"])
    assert "--seed-from-commit" in capsys.readouterr().out
