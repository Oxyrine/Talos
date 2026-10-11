"""Master vocabulary, geography, and nomenclature tables for synthetic generation.

This module provides deterministic stems, sectors, legal suffixes, honorific stoplists,
and state-city-pincode geographic mappings for Indian corporate entities.
"""

from dataclasses import dataclass

# -------------------------------------------------------------------------
# Corporate Name Stems (>= 120 unique stems)
# -------------------------------------------------------------------------
STEMS: tuple[str, ...] = (
    "Sunrise",
    "Kaveri",
    "Narmada",
    "Deccan",
    "Konark",
    "Vindhya",
    "Sahyadri",
    "Ashoka",
    "Lakshmi",
    "Ganesh",
    "Bharat",
    "Himalaya",
    "Indus",
    "Meghna",
    "Godavari",
    "Krishna",
    "Mahanadi",
    "Brahmaputra",
    "Tapti",
    "Yamuna",
    "Ganga",
    "Sabarmati",
    "Saraswati",
    "Gomti",
    "Chambal",
    "Betwa",
    "Mandovi",
    "Zuari",
    "Teesta",
    "Beas",
    "Chenab",
    "Jhelum",
    "Ravi",
    "Sutlej",
    "Aravalli",
    "Nilgiri",
    "Satpura",
    "Shivalik",
    "WesternGhat",
    "EasternGhat",
    "Malabar",
    "Coromandel",
    "Kutch",
    "Saurashtra",
    "Marwar",
    "Mewar",
    "Bundelkhand",
    "Rohilkhand",
    "Avadh",
    "Magadh",
    "Anga",
    "Vanga",
    "Kalinga",
    "Chola",
    "Pandya",
    "Chera",
    "Pallava",
    "Maurya",
    "Gupta",
    "Vardhana",
    "Rashtrakuta",
    "Chalukya",
    "Hoysala",
    "Kakatiya",
    "Vijayanagar",
    "Maratha",
    "Peshwa",
    "Rajput",
    "Parmar",
    "Chauhan",
    "Solanki",
    "Tomar",
    "Rathore",
    "Sisodia",
    "Scindia",
    "Holkar",
    "Gaekwad",
    "Bhonsle",
    "Wodeyar",
    "Travancore",
    "Cochin",
    "Mysore",
    "Hyderabad",
    "Baroda",
    "Gwalior",
    "Indore",
    "Jaipur",
    "Jodhpur",
    "Udaipur",
    "Bikaner",
    "Kota",
    "Alwar",
    "Bharatpur",
    "Rewa",
    "Bhopal",
    "Nagpur",
    "Pune",
    "Thane",
    "Nashik",
    "Surat",
    "Vadodara",
    "Rajkot",
    "Ahmedabad",
    "Coimbatore",
    "Madurai",
    "Tiruchirappalli",
    "Salem",
    "Mangalore",
    "Hubli",
    "Belgaum",
    "Warangal",
    "Nizamabad",
    "Karimnagar",
    "Visakhapatnam",
    "Vijayawada",
    "Guntur",
    "Asansol",
    "Siliguri",
    "Durgapur",
    "Kanpur",
    "Lucknow",
    "Varanasi",
    "Agra",
    "Prayagraj",
    "Meerut",
    "Bareilly",
    "Aligarh",
    "Moradabad",
    "Gorakhpur",
)

# -------------------------------------------------------------------------
# Industry Sectors (>= 40 unique sectors)
# -------------------------------------------------------------------------
SECTORS: tuple[str, ...] = (
    "Textiles",
    "Steels",
    "Agro Foods",
    "Pharmaceuticals",
    "Infra Projects",
    "Logistics",
    "Polymers",
    "Cements",
    "Power",
    "Finvest",
    "Realty",
    "Chemicals",
    "Auto Components",
    "Paper Mills",
    "Minerals",
    "Energy",
    "Renewables",
    "Fertilizers",
    "Engineering",
    "Electronics",
    "Packaging",
    "Hospitality",
    "Mining",
    "Heavy Electricals",
    "Shipbuilders",
    "Cables",
    "Sugar Mills",
    "Glass",
    "Ceramics",
    "Refineries",
    "Telecom",
    "Beverages",
    "Precision Tools",
    "Castings",
    "Forgings",
    "Tubes",
    "Wires",
    "Dyes",
    "Synthetic Fibres",
    "Industrial Gases",
)

# -------------------------------------------------------------------------
# Legal Suffix Styles
# -------------------------------------------------------------------------
LEGAL_SUFFIXES_PVT: tuple[str, ...] = (
    "Private Limited",
    "Pvt Ltd",
    "P. Ltd",
)

LEGAL_SUFFIXES_PUB: tuple[str, ...] = (
    "Limited",
    "Ltd",
)

# Honorific stoplist: fixed domain knowledge stripped during standardization
HONORIFIC_STOPLIST: tuple[str, ...] = (
    "SHREE",
    "SHRI",
    "SRI",
    "THE",
    "NEW",
    "M S",
)

# -------------------------------------------------------------------------
# Standard Abbreviations (Dev Noise & Standardization Chain)
# -------------------------------------------------------------------------
ABBREVIATIONS: dict[str, str] = {
    "Private": "Pvt",
    "Limited": "Ltd",
    "Textiles": "Tex",
    "Industries": "Inds",
    "Engineering": "Engg",
    "Manufacturing": "Mfg",
    "Pharmaceuticals": "Pharma",
    "Chemicals": "Chem",
    "International": "Intl",
    "Infrastructure": "Infra",
}

# Reverse mapping for expansion: e.g. TEX -> TEXTILES
ABBREVIATION_EXPANSIONS: dict[str, str] = {
    v.upper(): k.upper() for k, v in ABBREVIATIONS.items()
}

# Transliteration pairs for test profile unseen noise
TRANSLITERATIONS: tuple[tuple[str, str], ...] = (
    ("Lakshmi", "Laxmi"),
    ("Ganesh", "Ganesha"),
    ("Agarwal", "Aggarwal"),
    ("Kaveri", "Cauvery"),
    ("Vishnu", "Vishnoo"),
    ("Shree", "Shri"),
    ("Shri", "Sri"),
)

# -------------------------------------------------------------------------
# Geographic Master Data (9 States, Cities, and Pincode Ranges)
# -------------------------------------------------------------------------
@dataclass(frozen=True)
class CityGeo:
    city_name: str
    pincode_start: int
    pincode_end: int


@dataclass(frozen=True)
class StateGeo:
    state_code: str
    state_name: str
    cities: tuple[CityGeo, ...]


STATES_GEO: dict[str, StateGeo] = {
    "MH": StateGeo(
        state_code="MH",
        state_name="Maharashtra",
        cities=(
            CityGeo("Mumbai", 400001, 400099),
            CityGeo("Pune", 411001, 411060),
            CityGeo("Nagpur", 440001, 440037),
            CityGeo("Nashik", 422001, 422013),
            CityGeo("Thane", 400601, 400615),
        ),
    ),
    "GJ": StateGeo(
        state_code="GJ",
        state_name="Gujarat",
        cities=(
            CityGeo("Ahmedabad", 380001, 380061),
            CityGeo("Surat", 395001, 395010),
            CityGeo("Vadodara", 390001, 390025),
            CityGeo("Rajkot", 360001, 360007),
            CityGeo("Bhavnagar", 364001, 364005),
        ),
    ),
    "TN": StateGeo(
        state_code="TN",
        state_name="Tamil Nadu",
        cities=(
            CityGeo("Chennai", 600001, 600120),
            CityGeo("Coimbatore", 641001, 641046),
            CityGeo("Madurai", 625001, 625020),
            CityGeo("Tiruchirappalli", 620001, 620026),
            CityGeo("Salem", 636001, 636016),
        ),
    ),
    "KA": StateGeo(
        state_code="KA",
        state_name="Karnataka",
        cities=(
            CityGeo("Bengaluru", 560001, 560100),
            CityGeo("Mysuru", 570001, 570030),
            CityGeo("Hubballi", 580020, 580032),
            CityGeo("Mangaluru", 575001, 575020),
            CityGeo("Belagavi", 590001, 590019),
        ),
    ),
    "DL": StateGeo(
        state_code="DL",
        state_name="Delhi",
        cities=(
            CityGeo("New Delhi", 110001, 110025),
            CityGeo("North Delhi", 110006, 110054),
            CityGeo("South Delhi", 110016, 110070),
            CityGeo("West Delhi", 110015, 110065),
            CityGeo("East Delhi", 110091, 110096),
        ),
    ),
    "WB": StateGeo(
        state_code="WB",
        state_name="West Bengal",
        cities=(
            CityGeo("Kolkata", 700001, 700100),
            CityGeo("Howrah", 711101, 711114),
            CityGeo("Durgapur", 713201, 713218),
            CityGeo("Asansol", 713301, 713306),
            CityGeo("Siliguri", 734001, 734008),
        ),
    ),
    "TG": StateGeo(
        state_code="TG",
        state_name="Telangana",
        cities=(
            CityGeo("Hyderabad", 500001, 500095),
            CityGeo("Secunderabad", 500003, 500026),
            CityGeo("Warangal", 506001, 506015),
            CityGeo("Nizamabad", 503001, 503003),
            CityGeo("Karimnagar", 505001, 505005),
        ),
    ),
    "RJ": StateGeo(
        state_code="RJ",
        state_name="Rajasthan",
        cities=(
            CityGeo("Jaipur", 302001, 302039),
            CityGeo("Jodhpur", 342001, 342028),
            CityGeo("Udaipur", 313001, 313004),
            CityGeo("Kota", 324001, 324010),
            CityGeo("Bikaner", 334001, 334006),
        ),
    ),
    "UP": StateGeo(
        state_code="UP",
        state_name="Uttar Pradesh",
        cities=(
            CityGeo("Noida", 201301, 201318),
            CityGeo("Kanpur", 208001, 208027),
            CityGeo("Lucknow", 226001, 226030),
            CityGeo("Varanasi", 221001, 221011),
            CityGeo("Agra", 282001, 282010),
        ),
    ),
}

# Sorted list of states for deterministic iteration
STATE_CODES: tuple[str, ...] = tuple(sorted(STATES_GEO.keys()))
