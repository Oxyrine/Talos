"""Unit tests for generator vocabulary and geographic definitions."""

from data.generator.vocab import (
    ABBREVIATION_EXPANSIONS,
    ABBREVIATIONS,
    HONORIFIC_STOPLIST,
    SECTORS,
    STATE_CODES,
    STATES_GEO,
    STEMS,
)


def test_stems_count_and_uniqueness():
    assert len(STEMS) >= 120
    assert len(STEMS) == len(set(STEMS)), "Stems must be distinct"
    assert "Sunrise" in STEMS
    assert "Kaveri" in STEMS
    assert "Narmada" in STEMS


def test_sectors_count_and_uniqueness():
    assert len(SECTORS) >= 40
    assert len(SECTORS) == len(set(SECTORS)), "Sectors must be distinct"
    assert "Textiles" in SECTORS
    assert "Steels" in SECTORS
    assert "Agro Foods" in SECTORS


def test_honorific_stoplist():
    required = {"SHREE", "SHRI", "SRI", "THE", "NEW", "M S"}
    assert required.issubset(set(HONORIFIC_STOPLIST))


def test_abbreviations_mapping():
    assert ABBREVIATIONS["Private"] == "Pvt"
    assert ABBREVIATIONS["Limited"] == "Ltd"
    assert ABBREVIATION_EXPANSIONS["TEX"] == "TEXTILES"
    assert ABBREVIATION_EXPANSIONS["ENGG"] == "ENGINEERING"


def test_states_geo_master():
    assert len(STATE_CODES) == 9
    assert set(STATE_CODES) == {"MH", "GJ", "TN", "KA", "DL", "WB", "TG", "RJ", "UP"}

    for state_code in STATE_CODES:
        geo = STATES_GEO[state_code]
        assert geo.state_code == state_code
        assert len(geo.cities) >= 3, f"{state_code} must have at least 3 cities"
        for city in geo.cities:
            assert len(str(city.pincode_start)) == 6
            assert len(str(city.pincode_end)) == 6
            assert city.pincode_start <= city.pincode_end
