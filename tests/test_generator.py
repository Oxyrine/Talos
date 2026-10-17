"""tests/test_generator.py: the synthetic world is deterministic and plants what the spec says."""

from __future__ import annotations

from collections import Counter

import pyarrow.parquet as pq
import pytest

from data.generator import plant
from data.generator.generate import generate
from data.generator.noise import abbrev, ocr, ocr_pan, typo, word_order
from data.generator.profiles import resolve, seed_from_commit
from data.generator.standardise import edit_distance, name_std


@pytest.fixture(scope="module")
def dev(tmp_path_factory):
    out = tmp_path_factory.mktemp("dev")
    manifest = generate("dev", out)
    return out, manifest


def table(out, name):
    return pq.read_table(out / f"{name}.parquet").to_pylist()


def test_same_seed_same_rows(tmp_path):
    a = generate("tiny", tmp_path / "a")
    b = generate("tiny", tmp_path / "b")
    assert {k: v["sha256"] for k, v in a["tables"].items()} == {k: v["sha256"] for k, v in b["tables"].items()}


def test_different_seed_different_rows(tmp_path):
    a = generate("tiny", tmp_path / "a")
    b = generate("tiny", tmp_path / "b", seed=8)
    assert a["tables"]["raw/los_customer"]["sha256"] != b["tables"]["raw/los_customer"]["sha256"]


def test_test_profile_needs_a_seed():
    with pytest.raises(ValueError):
        resolve("test", None, None, None)
    prof, seed, _ = resolve("test", None, None, "deadbeef")
    assert seed == seed_from_commit("deadbeef")
    assert "TRANSLIT" in prof.name_families and "WORD_ORDER" in prof.name_families


def test_base_counts(dev):
    out, m = dev
    t = m["tables"]
    assert t["raw/entity_filing"]["rows"] == 4000
    assert t["truth/gt_record_entity"]["rows"] == 25000
    books = Counter(r["rec_key"].split(":")[0] for r in table(out, "truth/gt_record_entity"))
    assert books == {"LOS": 7000, "TSY": 5000, "GTE": 6000, "COL": 7000}
    groups = [r for r in table(out, "truth/gt_group") if r["group_no"] <= 400]
    assert len(groups) == 400


def test_planted_counts_exact(dev):
    out, _ = dev
    kinds = Counter(r["kind"] for r in table(out, "truth/gt_plant"))
    expected = {
        "REGISTRY_ONLY_PARENT": 60, "DIAMOND": 20, "CYCLE": 5, "ROOTLESS_CYCLE": 3, "JV": 10, "INTERDEP": 20,
        "DECOY": 30, "ID_NAME_CONFLICT": 12, "HIDDEN_BREACH": 6, "LATE_CORRECTION": 15, "POLICY_CHANGE": 1,
        "SELF_OWNING": 2,
    }
    assert dict(kinds) == expected
    rulings = Counter(r["ruling"] for r in table(out, "truth/gt_jv_ruling"))
    assert rulings == {"SINGLE": 3, "JOINT": 4, "NONE": 2, "CONNECTED": 1}
    minority = [e for e in table(out, "truth/gt_edge") if e["control_type"] == "MINORITY" and e["holder_entity_key"] != e["held_entity_key"]]
    assert len(minority) >= 300


def test_multi_spelling_share(dev):
    out, _ = dev
    name_fams = {"ABBREV", "TYPO", "OCR", "TRANSLIT", "WORD_ORDER"}
    noisy = {r["entity_key"] for r in table(out, "truth/gt_record_entity")
             if r["noise_families"] and name_fams & set(r["noise_families"].split(","))}
    assert abs(len(noisy) / 4000 - 0.40) <= 0.02


def test_missing_id_share(dev):
    out, _ = dev
    for name, ref in (("raw/treasury_holding", "issuer_ref"), ("raw/guarantee", "party_ref")):
        rows = {r[ref]: r for r in table(out, name) if r["load_id"].endswith("20260930-01")}
        missing = sum(1 for r in rows.values() if r["pan"] is None and r["cin"] is None)
        assert abs(missing / len(rows) - 0.30) <= 0.02, name


def test_hero_figures_to_the_paisa(dev):
    _, m = dev
    assert m["hero_checkpoints"] == {
        "reported": "40 cr", "t0_head_only": "31.2 cr", "after_ownership_batch": "58.2 cr",
        "holdco_group": "36.4 cr", "after_t1": "75.6 cr", "after_holdco_link": "112 cr",
    }
    assert round(plant.pct(plant.HERO_CHECKPOINTS["reported"]), 1) == 9.5
    assert round(plant.pct(plant.HERO_CHECKPOINTS["after_t1"]), 1) == 18.0
    assert round(plant.pct(plant.HERO_CHECKPOINTS["after_holdco_link"]), 1) == 26.7


def test_no_canonical_name_collisions_except_decoys(dev):
    out, _ = dev
    names = Counter(r["canonical_name"] for r in table(out, "truth/gt_entity") if r["role"] != "DECOY")
    assert [n for n, c in names.items() if c > 1] == []


def test_registry_ids_unique_and_well_formed(dev):
    import re

    out, _ = dev
    filings = table(out, "raw/entity_filing")
    cins = [f["cin"] for f in filings]
    pans = [f["pan"] for f in filings if f["pan"]]
    assert len(set(cins)) == len(cins) and len(set(pans)) == len(pans)
    assert all(re.fullmatch(r"[LU][0-9]{5}[A-Z]{2}[0-9]{4}(PLC|PTC)[0-9]{6}", c) for c in cins)
    assert all(re.fullmatch(r"[A-Z]{3}C[A-Z][0-9]{4}[A-Z]", p) for p in pans)


def test_incoming_stakes_at_most_100(dev):
    out, _ = dev
    total: Counter = Counter()
    for e in table(out, "raw/ownership_edge"):
        total[e["held_cin"]] += e["stake_pct"]
    assert max(total.values()) <= 100


def test_late_corrections_only_in_bd3_reload(dev):
    out, _ = dev
    loans = table(out, "raw/los_loan")
    v1 = {r["loan_id"]: r["outstanding_amt"] for r in loans if r["load_id"] == "LOS-20260930-01"}
    v2 = {r["loan_id"]: r["outstanding_amt"] for r in loans if r["load_id"] == "LOS-20260930-02"}
    assert v1.keys() == v2.keys()
    assert sum(1 for k in v1 if v1[k] != v2[k]) == plant.COUNTS["LATE_CORRECTION_LOS"]


def test_noise_families_are_pure_and_bounded():
    import random

    name = "Sunrise Textiles Private Limited"
    assert abbrev(name, random.Random(1)) in ("Sunrise Tex Pvt Ltd", "Sunrise Tex P. Ltd")
    assert name_std(abbrev(name, random.Random(1))) == name_std(name)
    for seed in range(50):
        assert 1 <= edit_distance(name_std(typo(name, random.Random(seed))), name_std(name)) <= 2  # transpose = 2
        assert 1 <= edit_distance(name_std(ocr(name, random.Random(seed))), name_std(name)) <= 2
    assert word_order(name, random.Random(0)) == "Textiles Sunrise Private Limited"
    damaged = ocr_pan("ABCCS1058Z", random.Random(0))
    assert damaged != "ABCCS1058Z" and not damaged[5:9].isdigit()
