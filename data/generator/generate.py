"""Synthetic world generator: entities, registry, four lending books, planted cases, truth.

    talos generate --profile dev --out data/out/dev

writes one Parquet file per raw table (raw/), the truth tables (truth/) and manifest.json.
Everything is drawn from random.Random(seed), and every set is sorted before it is
iterated, so the same seed and code give the same rows on any machine. The manifest
records a SHA-256 of each table's canonical rows (DEV-16).
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import string
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from data.generator import plant
from data.generator.noise import FAMILY_FUNCS, ocr_pan
from data.generator.plant import CAPITAL_BD3, HERO_BUCKETS, HERO_CHECKPOINTS
from data.generator.profiles import Profile, resolve
from data.generator.standardise import edit_distance, name_sim, name_std
from data.generator.vocab import SECTORS, STATE_CODES, STATES_GEO, STEMS

BUSINESS_DATES = (date(2026, 7, 31), date(2026, 8, 31), date(2026, 9, 30))
BD3 = BUSINESS_DATES[2]
CORRECTION_AT = datetime(2026, 10, 6, 10, 0, 0)
REG_LOAD_ID = "REG-20260731-01"
REG_LOADED_AT = datetime(2026, 8, 2, 6, 0, 0)
HEAD_WORDS = ("Industries", "Holdings", "Enterprises", "Group")
ROAD_WORDS = ("MG", "Station", "Temple", "Mill", "Canal", "Market", "Ring", "Lake", "Fort", "Church",
              "Park", "College", "Hospital", "Bazaar", "Nehru", "Gandhi", "Tilak", "Patel", "Ambedkar")
PRODUCTS = ("TERM_LOAN", "WORKING_CAPITAL", "CC_OD")
INSTRUMENTS = ("NCD", "CP", "BOND")
SECURITY_TYPES = ("SHARES", "PROPERTY", "FD", "MACHINERY", "RECEIVABLES")
MISSING_ID_RATE = {"LOS": 0.05, "TSY": 0.30, "GTE": 0.30, "COL": 0.15}
BOOK_PREFIX = {"LOS": "LOS-C", "TSY": "TSY-I", "GTE": "GTE-P", "COL": "COL-P"}


def load_id(book: str, bd: date, n: int = 1) -> str:
    return f"{book}-{bd:%Y%m%d}-{n:02d}"


def loaded_at(bd: date) -> datetime:
    return datetime.combine(bd + timedelta(days=2), datetime.min.time()) + timedelta(hours=6)


def r100(x: float) -> int:
    return max(100, int(round(x / 100.0)) * 100)


@dataclass
class Entity:
    idx: int
    group_no: int
    role: str
    family: str
    name: str
    public: bool
    state: str = ""
    city: str = ""
    pincode: str = ""
    address: str = ""
    pan: str = ""
    cin: str = ""
    lei: str | None = None
    dins: list[str] = field(default_factory=list)
    parent: int | None = None
    stake: Decimal | None = None
    depth: int = 0
    group_code: str | None = None
    filing_has_pan: bool = True
    exposure: int = 0
    tags: set[str] = field(default_factory=set)

    @property
    def key(self) -> str:
        return f"E:{self.cin}"


@dataclass
class Group:
    no: int
    family: str
    kind: str                     # NORMAL | HERO | CYCLE_ROOTLESS | CYCLE_ATTACHED | JV
    home_state: str
    members: list[int] = field(default_factory=list)
    head: int = -1
    code: str | None = None
    target: int = 0
    capped: bool = False
    hidden_breach: str | None = None   # None | RO | INTERDEP | HERO
    family_key: str = ""


@dataclass
class Record:
    book: str
    ref: str
    ent: int
    name: str = ""
    pan: str | None = None
    cin: str | None = None
    lei: str | None = None
    address: str = ""
    city: str = ""
    state: str = ""
    families: list[str] = field(default_factory=list)
    group_code: str | None = None
    dins: str | None = None
    bucket: str | None = None      # hero bucket
    forced_ids: str | None = None  # "PAN+CIN" | "PAN" | "CIN" | "NONE" | None (random)
    primary: bool = False

    @property
    def rec_key(self) -> str:
        return f"{self.book}:{self.ref}"


@dataclass
class Fact:
    book: str
    fact_id: str
    rec: Record
    kind: str          # loan product | instrument | FIN/PERF | security type
    exposure: int = 0  # BD3 target exposure in rupees (0 for pledges)
    amounts: dict = field(default_factory=dict)   # (bd, load_no) -> amount tuple


class World:
    def __init__(self, prof: Profile, seed: int, scale: float):
        self.prof = prof
        self.seed = seed
        self.scale = scale
        self.rng = random.Random(seed)
        self.n_groups = max(60, round(400 * scale))
        self.n_entities = max(600, round(4000 * scale))
        self.entities: list[Entity] = []
        self.groups: dict[int, Group] = {}
        self.records: list[Record] = []
        self.facts: list[Fact] = []
        self.edges: list[dict] = []        # registry ownership edges
        self.dependencies: list[dict] = []
        self.plants: list[tuple[str, str, str]] = []
        self.gt_edges: list[tuple[str, str, str, str | None, bool]] = []
        self.jv_rulings: list[tuple[str, str, str | None]] = []
        self.truth_links: list[tuple[int, int, str]] = []   # (entity a, entity b, kind) admitted in truth
        self.jv_attrib: list[tuple[int, int]] = []          # (jv entity, controller entity)
        self.corrections: dict[str, float] = {}             # fact_id -> factor at BD3 load -02
        self._pans: set[str] = set()
        self._head_prefixes: set[str] = set()
        self._cin_serials: set[int] = set()
        self._dins: set[str] = set()
        self._names: set[str] = set()
        self._ref_counter: Counter = Counter()

    # ------------------------------------------------------------------ ids
    def new_pan(self, initial: str, unique_prefix: bool = False) -> str:
        rng = self.rng
        while True:
            pan = ("".join(rng.choice(string.ascii_uppercase) for _ in range(3)) + "C" + initial
                   + f"{rng.randrange(10000):04d}" + rng.choice(string.ascii_uppercase))
            if pan in self._pans or (unique_prefix and pan[:5] in self._head_prefixes):
                continue
            self._pans.add(pan)
            if unique_prefix:
                self._head_prefixes.add(pan[:5])
            return pan

    def new_cin(self, public: bool, state: str) -> str:
        rng = self.rng
        while True:
            serial = rng.randrange(1, 999999)
            if serial not in self._cin_serials:
                self._cin_serials.add(serial)
                break
        nic = rng.randrange(10000, 99999)
        year = rng.randrange(1975, 2021)
        return f"{'L' if public else 'U'}{nic:05d}{state}{year}{'PLC' if public else 'PTC'}{serial:06d}"

    def new_lei(self) -> str:
        rng = self.rng
        return "".join(rng.choice(string.ascii_uppercase + string.digits) for _ in range(18)) + f"{rng.randrange(100):02d}"

    def new_din(self) -> str:
        while True:
            d = f"{self.rng.randrange(10**7, 10**8)}"
            if d not in self._dins:
                self._dins.add(d)
                return d

    def next_ref(self, book: str) -> str:
        self._ref_counter[book] += 1
        return f"{BOOK_PREFIX[book]}-{self._ref_counter[book]:06d}"

    def next_fact_id(self, kind: str) -> str:
        self._ref_counter[kind] += 1
        return f"{kind}-{self._ref_counter[kind]:06d}"

    # ------------------------------------------------------------ geography
    def place(self, e: Entity, state: str) -> None:
        rng = self.rng
        geo = STATES_GEO[state]
        city = rng.choice(geo.cities)
        e.state = state
        e.city = city.city_name
        e.pincode = str(rng.randint(city.pincode_start, city.pincode_end))
        e.address = f"{rng.randint(1, 250)}, {rng.choice(ROAD_WORDS)} Road, {e.city} - {e.pincode}"

    def branch_address(self, e: Entity) -> tuple[str, str, str]:
        rng = self.rng
        while True:
            state = rng.choice(STATE_CODES)
            city = rng.choice(STATES_GEO[state].cities)
            if city.city_name != e.city:
                break
        pin = rng.randint(city.pincode_start, city.pincode_end)
        return f"{rng.randint(1, 250)}, {rng.choice(ROAD_WORDS)} Road, {city.city_name} - {pin}", city.city_name, state

    # ---------------------------------------------------------------- world
    def add_entity(self, group: Group, role: str, name: str, public: bool, state: str) -> Entity:
        if name in self._names:
            raise AssertionError(f"canonical name collision: {name}")
        self._names.add(name)
        e = Entity(idx=len(self.entities), group_no=group.no, role=role, family=group.family, name=name, public=public)
        self.place(e, state)
        e.pan = self.new_pan(group.family[0].upper(), unique_prefix=(role == "HEAD"))
        e.cin = self.new_cin(public, e.state)
        if self.rng.random() < 0.25:
            e.lei = self.new_lei()
        self.entities.append(e)
        group.members.append(e.idx)
        return e

    def build_groups(self) -> None:
        rng = self.rng
        n = self.n_groups
        hero_no = plant.HERO_GROUP_NO
        group_nos = list(range(1, n + 1))
        others = [g for g in group_nos if g != hero_no]
        cycle_nos = sorted(rng.sample(others, plant.COUNTS["CYCLE"]))
        rootless = set(cycle_nos[: plant.COUNTS["ROOTLESS_CYCLE"]])

        sizes: dict[int, int] = {}
        for g in group_nos:
            if g == hero_no:
                sizes[g] = 9
            elif g in cycle_nos:
                sizes[g] = 3
            else:
                sizes[g] = min(25, max(3, int(round(rng.lognormvariate(math.log(8.6), 0.55)))))
        target = self.n_entities - plant.COUNTS["JV"]
        adjustable = [g for g in group_nos if g != hero_no and g not in cycle_nos]
        while sum(sizes.values()) != target:
            g = rng.choice(adjustable)
            if sum(sizes.values()) < target and sizes[g] < 25:
                sizes[g] += 1
            elif sum(sizes.values()) > target and sizes[g] > 3:
                sizes[g] -= 1

        # Families share one stem across up to four groups (one per head word) with disjoint
        # sector pools, so every canonical name is unique and siblings share a single word,
        # as real group names do. Two-word families are used only once stems run out (scale).
        stems = [s for s in STEMS if s != plant.HERO_FAMILY]
        rng.shuffle(stems)
        self.family_sectors: dict[str, list[str]] = {}
        self.family_head_word: dict[str, str] = {}
        stem_state = {s: {"sectors": rng.sample(SECTORS, len(SECTORS)), "heads": list(HEAD_WORDS)} for s in stems}
        pairs = [f"{a} {b}" for a in stems for b in stems if a != b]
        rng.shuffle(pairs)
        pair_iter = iter(pairs)
        cursor = 0

        def take_family(size: int) -> str:
            nonlocal cursor
            for k in range(len(stems)):
                stem = stems[(cursor + k) % len(stems)]
                st = stem_state[stem]
                if st["heads"] and len(st["sectors"]) >= size - 1:
                    cursor = (cursor + k + 1) % len(stems)
                    word = st["heads"].pop(0)
                    key = f"{stem}#{word}"
                    self.family_head_word[key] = word
                    self.family_sectors[key] = [st["sectors"].pop() for _ in range(size - 1)]
                    return key
            family = next(pair_iter)
            key = f"{family}#{rng.choice(HEAD_WORDS)}"
            self.family_head_word[key] = key.split("#")[1]
            self.family_sectors[key] = rng.sample(SECTORS, size - 1)
            return key

        for g in group_nos:
            fam_key = plant.HERO_FAMILY if g == hero_no else take_family(sizes[g] + (1 if g in cycle_nos else 0))
            family = fam_key.split("#")[0]
            kind = "HERO" if g == hero_no else ("CYCLE_ROOTLESS" if g in rootless else ("CYCLE_ATTACHED" if g in cycle_nos else "NORMAL"))
            grp = Group(no=g, family=family, kind=kind, home_state=rng.choice(STATE_CODES))
            grp.family_key = fam_key
            self.groups[g] = grp
            if kind == "HERO":
                self.build_hero(grp)
            elif kind.startswith("CYCLE"):
                self.build_cycle(grp)
            else:
                self.build_tree(grp, sizes[g])
            self.assign_dins(grp)

    def member_state(self, grp: Group) -> str:
        return grp.home_state if self.rng.random() < 0.8 else self.rng.choice(STATE_CODES)

    def build_tree(self, grp: Group, size: int) -> None:
        rng = self.rng
        word = self.family_head_word[grp.family_key]
        head = self.add_entity(grp, "HEAD", f"{grp.family} {word} Limited", True, grp.home_state)
        grp.head = head.idx
        grp.code = f"GRP-{head.pan[:5]}"
        sectors = self.family_sectors[grp.family_key]
        for sector in sectors:
            parents = [m for m in grp.members if self.entities[m].depth < 6]
            parent = self.entities[rng.choice(parents)]
            e = self.add_entity(grp, "SUB", f"{grp.family} {sector} Private Limited", False, self.member_state(grp))
            e.parent = parent.idx
            e.depth = parent.depth + 1
            e.stake = Decimal(rng.randint(51, 100))

    def build_hero(self, grp: Group) -> None:
        rng = self.rng
        head = self.add_entity(grp, "HEAD", f"{grp.family} Industries Limited", True, grp.home_state)
        grp.head = head.idx
        grp.code = f"GRP-{head.pan[:5]}"
        sectors = rng.sample([s for s in SECTORS if s != "Finvest"], 6)
        parents = [0, 0, 0, 0, 1, 2]   # S1..S4 under the head, S5 under S1, S6 under S2
        subs: list[Entity] = []
        for sector, p in zip(sectors, parents):
            parent = head if p == 0 else subs[p - 1]
            e = self.add_entity(grp, "SUB", f"{grp.family} {sector} Private Limited", False, grp.home_state)
            e.parent, e.depth, e.stake = parent.idx, parent.depth + 1, Decimal(rng.randint(60, 100))
            e.tags.add("HERO_SUB")
            subs.append(e)
        subs[2].filing_has_pan = False          # S3: registry filing without PAN (same-PAN beat)
        subs[2].tags.add("HERO_SG")
        holdco = self.add_entity(grp, "SUB", f"{grp.family} Holdings Limited", True, grp.home_state)
        holdco.parent, holdco.depth, holdco.stake = head.idx, 1, Decimal(74)
        holdco.tags |= {"HOLDCO", "REGISTRY_ONLY"}
        holdsub = self.add_entity(grp, "SUB", f"{grp.family} Finvest Private Limited", False, grp.home_state)
        holdsub.parent, holdsub.depth, holdsub.stake = holdco.idx, 2, Decimal(100)
        holdsub.tags.add("HOLDSUB")
        hc_code = f"GRP-{holdco.pan[:5]}"
        self._head_prefixes.add(holdco.pan[:5])
        for m in grp.members:
            self.entities[m].group_code = grp.code
        holdco.group_code = hc_code
        holdsub.group_code = hc_code
        grp.hidden_breach = "HERO"

    def build_cycle(self, grp: Group) -> None:
        sectors = self.family_sectors[grp.family_key]
        ents = [self.add_entity(grp, "SUB", f"{grp.family} {s} Private Limited", False, grp.home_state) for s in sectors]
        for i, e in enumerate(ents):
            e.parent = ents[i - 1].idx     # C -> A, A -> B, B -> C
            e.stake = Decimal(51)
            e.tags.add("CYCLE")
        grp.head = ents[0].idx            # provisional; truth head is the largest exposure
        grp.code = f"GRP-{ents[0].pan[:5]}"

    def assign_dins(self, grp: Group) -> None:
        pool = [self.new_din() for _ in range(max(3, round(len(grp.members) * 1.3)))]
        for m in grp.members:
            e = self.entities[m]
            e.dins = sorted(self.rng.sample(pool, self.rng.randint(1, min(4, len(pool)))))

    # ---------------------------------------------------------------- plants
    def normal_groups(self, exclude: set[int]) -> list[Group]:
        return [g for no, g in sorted(self.groups.items()) if g.kind == "NORMAL" and no not in exclude]

    def plant_cases(self) -> None:
        rng = self.rng
        used: set[int] = {plant.HERO_GROUP_NO}

        # Group codes for ordinary groups: every member is on the stale LOS map ...
        for g in self.groups.values():
            if g.kind != "HERO":
                for m in g.members:
                    self.entities[m].group_code = g.code

        # Hidden breaches: 3 through a registry-only subsidiary, 2 through interdependence.
        big = [g for g in self.normal_groups(used) if len(g.members) >= 6]
        hb = rng.sample(big, 5)
        for g in hb[:3]:
            g.hidden_breach = "RO"
        for g in hb[3:]:
            g.hidden_breach = "INTERDEP"
        used |= {g.no for g in hb}

        # Registry-only parents: leaves left off the LOS map. HoldCo is the hero's.
        ro: list[Entity] = [e for e in self.entities if "HOLDCO" in e.tags]
        for g in hb[:3]:
            ro.append(self.pick_leaf(g))
        pool = self.normal_groups(used)
        rng.shuffle(pool)
        need = plant.COUNTS["REGISTRY_ONLY_PARENT"] - len(ro)
        i = 0
        while need > 0:
            g = pool[i % len(pool)]
            i += 1
            leaf = self.pick_leaf(g, avoid={e.idx for e in ro})
            if leaf is not None:
                ro.append(leaf)
                need -= 1
        for e in ro:
            e.tags.add("REGISTRY_ONLY")
            if "HOLDCO" not in e.tags:
                e.group_code = None
            parent = self.entities[e.parent]
            self.plants.append(("REGISTRY_ONLY_PARENT", f"CONTROL:{parent.key}>{e.key}",
                                "OWNERSHIP proposal; the subsidiary joins the group once approved"))

        reserved = {e.idx for e in self.entities if e.tags & {"REGISTRY_ONLY", "CYCLE"}}

        # Interdependence partners for the two INTERDEP hidden breaches, then 18 more pairs.
        free = [g for g in self.normal_groups(used)]
        rng.shuffle(free)
        free_iter = iter(free)
        interdep_pairs: list[tuple[Entity, Entity, Group, Group]] = []
        for g in hb[3:]:
            partner = next(free_iter)
            partner.capped = True
            used.add(partner.no)
            interdep_pairs.append((self.entities[rng.choice(partner.members)], self.entities[rng.choice(g.members)], partner, g))
        for _ in range(plant.COUNTS["INTERDEP"] - 2):
            ga, gb = next(free_iter), next(free_iter)
            ga.capped = gb.capped = True
            used |= {ga.no, gb.no}
            interdep_pairs.append((self.entities[rng.choice(ga.members)], self.entities[rng.choice(gb.members)], ga, gb))
        for holder, held, _, _ in interdep_pairs:
            self.add_dependency(held, holder, plant_kind="INTERDEP")

        # Cycles attached below an outside parent through an interdependence edge.
        for g in [g for g in self.groups.values() if g.kind == "CYCLE_ATTACHED"]:
            parent_group = next(free_iter)
            parent_group.capped = True
            used.add(parent_group.no)
            p = self.entities[parent_group.head]
            a = self.entities[g.members[0]]
            self.add_dependency(a, p, plant_kind="CYCLE_ATTACH")
            self.plants.append(("CYCLE", a.key, f"cycle hangs below {p.key}; component intact"))
        for g in [g for g in self.groups.values() if g.kind == "CYCLE_ROOTLESS"]:
            a = self.entities[g.members[0]]
            self.plants.append(("CYCLE", a.key, "three-entity cycle; component intact"))
            self.plants.append(("ROOTLESS_CYCLE", a.key, "group present, flagged CYCLE_HEADED, head = largest exposure"))

        # Diamonds (DEV-15): X held 60% by B, plus an interdependence edge from C, same group.
        diamond_groups = 0
        for g in self.normal_groups(used):
            if diamond_groups == plant.COUNTS["DIAMOND"]:
                break
            for x_idx in sorted(g.members):
                x = self.entities[x_idx]
                if x.parent is None or x.parent == g.head or x.idx in reserved or self.children(x.idx):
                    continue
                b = self.entities[x.parent]
                cands = [m for m in g.members if m not in (x.idx, b.idx) and m not in reserved]
                if not cands:
                    continue
                c = self.entities[rng.choice(cands)]
                x.stake = Decimal(60)
                x.tags.add("DIAMOND")
                self.add_dependency(x, c, plant_kind="DIAMOND")
                self.plants.append(("DIAMOND", x.key, f"held 60% by {b.key} and interdependent with {c.key}; counted once"))
                used.add(g.no)
                diamond_groups += 1
                break

        # Joint ventures: two holders at 50% each, both with control_flag.
        jv_group_no = self.n_groups
        rulings = list(plant.JV_RULINGS)
        for ruling in rulings:
            ga, gb = next(free_iter), next(free_iter)
            ga.capped = gb.capped = True
            used |= {ga.no, gb.no}
            a, b = self.entities[ga.head], self.entities[rng.choice(gb.members)]
            jv_group_no += 1
            jg = Group(no=jv_group_no, family=f"{ga.family.split()[0]} {gb.family.split()[0]}", kind="JV", home_state=a.state)
            self.groups[jv_group_no] = jg
            jv = self.add_entity(jg, "JV", f"{jg.family} Ventures Private Limited", False, a.state)
            jv.dins = sorted(set(a.dins[:1] + b.dins[:1]))
            jg.head = jv.idx
            jv.group_code = None
            jv.tags.add("JV")
            eff = self.random_date(date(2018, 1, 1), date(2026, 3, 31))
            for h in (a, b):
                self.edges.append(self.edge(h, jv, Decimal(50), True, eff))
            controller = a if ruling == "SINGLE" else None
            self.jv_rulings.append((jv.key, ruling, controller.key if controller else None))
            if ruling == "SINGLE":
                jv.group_no = ga.no
                self.truth_links.append((a.idx, jv.idx, "CONTROL"))
                self.gt_edges += [(a.key, jv.key, "CONTROL", "MAJORITY", True), (b.key, jv.key, "CONTROL", "MINORITY", False)]
            elif ruling in ("JOINT", "CONNECTED"):
                self.jv_attrib += [(jv.idx, a.idx), (jv.idx, b.idx)]
                self.gt_edges += [(a.key, jv.key, "CONTROL", "JOINT", False), (b.key, jv.key, "CONTROL", "JOINT", False)]
                if ruling == "CONNECTED":
                    self.truth_links.append((a.idx, b.idx, "INTERDEP"))
                    self.gt_edges.append((a.key, b.key, "INTERDEP", None, True))
            else:
                self.gt_edges += [(a.key, jv.key, "CONTROL", "UNKNOWN", False), (b.key, jv.key, "CONTROL", "UNKNOWN", False)]
            self.plants.append(("JV", f"JV:{jv.key}", f"CONTROL_RULING proposal, UNASSIGNED until ruled; truth {ruling}"))

        # Decoys: L renamed to within edit distance 2 of T (8 identical); different state,
        # different group, no shared IDs.
        decoy_pool = [e for e in self.entities if e.role == "SUB" and e.group_no not in {g.no for g in hb}
                      and e.group_no != plant.HERO_GROUP_NO and not (e.tags & {"REGISTRY_ONLY", "CYCLE", "DIAMOND", "JV"})]
        rng.shuffle(decoy_pool)
        decoys = 0
        taken: set[int] = set()
        for t in decoy_pool:
            if decoys == plant.COUNTS["DECOY"]:
                break
            if t.idx in taken:
                continue
            for cand in decoy_pool:
                if (cand.idx in taken or cand.idx == t.idx or cand.group_no == t.group_no or cand.state == t.state):
                    continue
                identical = decoys < plant.COUNTS["DECOY_IDENTICAL"]
                new_name = t.name if identical else self.near_name(t.name)
                if new_name is None or (not identical and new_name in self._names):
                    continue
                self._names.discard(cand.name)
                if not identical:
                    self._names.add(new_name)
                cand.name = new_name
                cand.role = "DECOY"
                cand.tags.add("DECOY")
                t.tags.add("DECOY_TARGET")
                taken |= {cand.idx, t.idx}
                self.plants.append(("DECOY", cand.key, f"no record of {cand.key} links to {t.key}, and vice versa"))
                decoys += 1
                break

        # Minority cross-group edges and self-owning entities (data quality).
        candidates = [e for e in self.entities if e.parent is not None and e.stake is not None and e.stake <= 90
                      and not (e.tags & {"JV", "CYCLE"}) and e.group_no != plant.HERO_GROUP_NO]
        holders = [e for e in self.entities if e.role in ("HEAD", "SUB") and e.group_no != plant.HERO_GROUP_NO]
        minority_in: Counter = Counter()
        added = 0
        while added < plant.COUNTS["MINORITY_EDGE"]:
            held = rng.choice(candidates)
            holder = rng.choice(holders)
            room = 100 - int(held.stake) - minority_in[held.idx]
            if holder.group_no == held.group_no or room < 5:
                continue
            stake = Decimal(rng.randint(5, min(49, room)))
            minority_in[held.idx] += int(stake)
            self.edges.append(self.edge(holder, held, stake, False, self.random_date(date(2015, 1, 1), date(2026, 6, 30))))
            self.gt_edges.append((holder.key, held.key, "CONTROL", "MINORITY", False))
            added += 1
        for e in rng.sample([c for c in candidates if minority_in[c.idx] == 0], plant.COUNTS["SELF_OWNING"]):
            self.edges.append(self.edge(e, e, Decimal(rng.randint(1, 4)), False, self.random_date(date(2019, 1, 1), date(2026, 6, 30))))
            self.gt_edges.append((e.key, e.key, "CONTROL", "MINORITY", False))
            self.plants.append(("SELF_OWNING", e.key, "not proposed; listed as SELF_OWNING data quality"))
            minority_in[e.idx] += 1

        # Tree and cycle edges (majority, control_flag), all in truth.
        for e in self.entities:
            if e.parent is not None and "JV" not in e.tags:
                parent = self.entities[e.parent]
                self.edges.append(self.edge(parent, e, e.stake, True, self.random_date(date(2010, 1, 1), date(2026, 6, 30))))
                self.truth_links.append((parent.idx, e.idx, "CONTROL"))
                self.gt_edges.append((parent.key, e.key, "CONTROL", "MAJORITY", True))

        self.hidden_breach_groups = hb

    def children(self, idx: int) -> list[int]:
        return [e.idx for e in self.entities if e.parent == idx]

    def pick_leaf(self, g: Group, avoid: set[int] | None = None) -> Entity | None:
        avoid = avoid or set()
        leaves = [m for m in g.members if m != g.head and not self.children(m) and m not in avoid
                  and self.entities[m].parent is not None and "REGISTRY_ONLY" not in self.entities[self.entities[m].parent].tags]
        return self.entities[self.rng.choice(sorted(leaves))] if leaves else None

    def near_name(self, name: str) -> str | None:
        """Change one or two letters inside the first word (the family), keep the rest."""
        tokens = name.split(" ")
        word = tokens[0]
        for _ in range(20):
            w = list(word)
            for _ in range(self.rng.randint(1, 2)):
                k = self.rng.randrange(1, len(w))
                w[k] = self.rng.choice("aeiouyrnlst")
            cand = " ".join(["".join(w)] + tokens[1:])
            if cand != name and 1 <= edit_distance(name_std(cand), name_std(name)) <= 2:
                return cand
        return None

    def random_date(self, lo: date, hi: date) -> date:
        return lo + timedelta(days=self.rng.randint(0, (hi - lo).days))

    def edge(self, holder: Entity, held: Entity, stake: Decimal, control: bool, eff: date) -> dict:
        return {"holder_cin": holder.cin, "held_cin": held.cin, "stake_pct": Decimal(stake).quantize(Decimal("0.0001")),
                "control_flag": control, "effective_from": eff,
                "filed_on": min(eff + timedelta(days=self.rng.randint(0, 60)), date(2026, 7, 15))}

    def add_dependency(self, held: Entity, holder: Entity, plant_kind: str) -> None:
        """held's LOS customer depends on holder's LOS customer (resolved later)."""
        share = Decimal(self.rng.randint(55, 90))
        self.dependencies.append({"held": held.idx, "holder": holder.idx, "share": share,
                                  "noted_on": self.random_date(date(2025, 4, 1), date(2026, 6, 30)), "plant": plant_kind})
        self.truth_links.append((holder.idx, held.idx, "INTERDEP"))
        self.gt_edges.append((holder.key, held.key, "INTERDEP", None, True))
        if plant_kind == "INTERDEP":
            self.plants.append(("INTERDEP", f"INTERDEP:{holder.key}>{held.key}", "INTERDEP proposal (human only)"))

    # --------------------------------------------------------------- records
    def build_records(self) -> None:
        rng = self.rng
        s = self.scale
        quotas = {"LOS": round(7000 * s), "TSY": round(5000 * s), "GTE": round(6000 * s), "COL": round(7000 * s)}

        self.build_hero_records()
        hero_ents = {e.idx for e in self.entities if e.group_no == plant.HERO_GROUP_NO and "JV" not in e.tags}
        for e in self.entities:
            if e.idx not in hero_ents:
                self.records.append(Record("LOS", self.next_ref("LOS"), e.idx, primary=True))
        self.plant_id_conflicts()

        have = Counter(r.book for r in self.records)
        weights_ents = [e for e in self.entities if e.idx not in hero_ents]
        weights = [rng.lognormvariate(0, 0.8) * (0.15 if "JV" in e.tags else 1.0) for e in weights_ents]
        for book in ("LOS", "TSY", "GTE", "COL"):
            k = quotas[book] - have[book]
            for e in rng.choices(weights_ents, weights=weights, k=max(0, k)):
                self.records.append(Record(book, self.next_ref(book), e.idx))

        self.assign_ids()
        self.assign_names()

    def build_hero_records(self) -> None:
        ents = [e for e in self.entities if e.group_no == plant.HERO_GROUP_NO and "JV" not in e.tags]
        head = ents[0]
        subs = [e for e in ents if "HERO_SUB" in e.tags]
        holdco = next(e for e in ents if "HOLDCO" in e.tags)
        holdsub = next(e for e in ents if "HOLDSUB" in e.tags)

        def rec(book: str, e: Entity, ids: str, bucket: str | None, primary: bool = False) -> Record:
            r = Record(book, self.next_ref(book), e.idx, forced_ids=ids, bucket=bucket, primary=primary)
            self.records.append(r)
            return r

        rec("LOS", head, "PAN+CIN", "HEAD:REPORTED", primary=True)
        rec("LOS", head, "PAN+CIN", "HEAD:REPORTED")
        rec("TSY", head, "PAN", "HEAD:REPORTED")
        rec("GTE", head, "PAN+CIN", "HEAD:REPORTED")
        rec("TSY", head, "CIN", "HEAD:CIN_ONLY")
        rec("TSY", head, "NONE", "HEAD:T1")
        rec("GTE", head, "NONE", "HEAD:T1")
        rec("COL", head, "PAN", None)
        for i, sub in enumerate(subs):
            rec("LOS", sub, "PAN+CIN", "SUBS:REPORTED", primary=True)
            if i in (0, 1):
                rec("GTE", sub, "PAN", "SUBS:REPORTED")
            if i == 3:
                rec("TSY", sub, "PAN+CIN", "SUBS:REPORTED")
            if i in (0, 1, 4):
                rec("TSY", sub, "CIN", "SUBS:CIN_ONLY")
            if i == 0:
                rec("TSY", sub, "NONE", "SUBS:T1")
            if i == 3:
                rec("GTE", sub, "NONE", "SUBS:T1")
            if i == 4:
                rec("TSY", sub, "NONE", "SUBS:T1")
            if i == 1:
                rec("COL", sub, "CIN", None)
        rec("LOS", holdco, "PAN+CIN", "HOLDCO:REPORTED", primary=True)
        rec("LOS", holdco, "PAN+CIN", "HOLDCO:REPORTED")
        rec("TSY", holdco, "PAN", "HOLDCO:REPORTED")
        rec("LOS", holdsub, "PAN+CIN", "HOLDSUB:REPORTED", primary=True)
        rec("GTE", holdsub, "PAN", "HOLDSUB:REPORTED")

    def plant_id_conflicts(self) -> None:
        """Twelve treasury / guarantee records keyed with an unrelated entity's valid PAN."""
        rng = self.rng
        hb_nos = {g.no for g in self.hidden_breach_groups} | {plant.HERO_GROUP_NO}
        unrelated_pool = [e for e in self.entities if e.group_no not in hb_nos and not (e.tags & {"JV", "DECOY", "DECOY_TARGET"})]
        true_pool = [e for e in self.entities if e.group_no not in hb_nos and e.role == "SUB"
                     and not (e.tags & {"DECOY", "DECOY_TARGET", "JV"})]
        sg = next(e for e in self.entities if "HERO_SG" in e.tags)
        targets = [sg] + rng.sample(true_pool, plant.COUNTS["ID_NAME_CONFLICT"] - 1)
        for i, true_e in enumerate(targets):
            while True:
                u = rng.choice(unrelated_pool)
                if u.group_no != true_e.group_no and u.family.split()[0] != true_e.family.split()[0] \
                        and name_sim(u.name, true_e.name) < 0.45:
                    break
            book = "GTE" if i == 0 or rng.random() < 0.5 else "TSY"
            r = Record(book, self.next_ref(book), true_e.idx, forced_ids="WRONG_PAN",
                       bucket="SUBS:T1" if i == 0 else None)
            r.pan = u.pan
            r.tags = {"ID_NAME_CONFLICT"}   # type: ignore[attr-defined]
            self.records.append(r)
            pair_key = hashlib.sha256(f"{r.rec_key}|REG:{u.cin}".encode()).hexdigest()[:16]
            self.plants.append(("ID_NAME_CONFLICT", pair_key, f"{r.rec_key} carries the PAN of {u.key}; expect T3 ID_NAME_CONFLICT"))

    def assign_ids(self) -> None:
        rng = self.rng
        by_book: dict[str, list[Record]] = defaultdict(list)
        for r in self.records:
            by_book[r.book].append(r)
        for book, recs in sorted(by_book.items()):
            forced_missing = sum(1 for r in recs if r.forced_ids == "NONE")
            free = [r for r in recs if r.forced_ids is None and not r.primary]
            need = max(0, round(MISSING_ID_RATE[book] * len(recs)) - forced_missing)
            missing = set(id(r) for r in rng.sample(free, min(need, len(free))))
            for r in recs:
                e = self.entities[r.ent]
                pattern = r.forced_ids
                if pattern == "WRONG_PAN":
                    continue
                if pattern is None:
                    if id(r) in missing:
                        pattern = "NONE"
                    elif r.primary:
                        pattern = "PAN+CIN" if rng.random() < 0.7 else "PAN"
                    else:
                        roll = rng.random()
                        pattern = "PAN+CIN" if roll < 0.55 else ("PAN" if roll < 0.80 else "CIN")
                    if "HERO_SG" in e.tags and pattern != "NONE":
                        pattern = "PAN+CIN"
                r.pan = e.pan if "PAN" in pattern else None
                r.cin = e.cin if "CIN" in pattern else None
                if book == "TSY" and e.lei and pattern != "NONE" and rng.random() < 0.5:
                    r.lei = e.lei
                if "MISSING_ID" not in r.families and pattern == "NONE":
                    r.families.append("MISSING_ID")
        # OCR damage on 8 PANs of records that also carry a CIN.
        cands = [r for r in self.records if r.pan and r.cin and r.forced_ids is None and not r.primary
                 and self.entities[r.ent].group_no != plant.HERO_GROUP_NO]
        for r in rng.sample(cands, 8):
            r.pan = ocr_pan(r.pan, rng)
            r.families.append("OCR_PAN")

    def assign_names(self) -> None:
        rng = self.rng
        fams = list(self.prof.name_families)
        protected_groups = {g.no for g in self.hidden_breach_groups} | {plant.HERO_GROUP_NO}
        by_ent: dict[int, list[Record]] = defaultdict(list)
        for r in self.records:
            by_ent[r.ent].append(r)
        ent_ids = sorted(by_ent)
        noisy = set(rng.sample(ent_ids, round(0.40 * len(self.entities))))
        for idx in ent_ids:
            e = self.entities[idx]
            recs = by_ent[idx]
            noisy_recs = set()
            if idx in noisy:
                noisy_recs = {id(r) for r in rng.sample(recs, min(len(recs), rng.randint(1, 2)))}
            for r in recs:
                r.address, r.city, r.state = e.address, e.city, e.state
                if (r.pan or r.cin) and r.forced_ids is None:
                    if rng.random() < 0.10 and not (e.tags & {"DECOY", "DECOY_TARGET"}) and e.group_no not in protected_groups:
                        r.address, r.city, r.state = self.branch_address(e)
                base = self.suffix_variant(e)
                if id(r) in noisy_recs:
                    base = self.apply_noise(base, e, r, fams)
                if r.book != "LOS" or not r.primary:
                    if rng.random() < 0.03 and e.group_no not in protected_groups:
                        base = "M/s " + base
                r.name = base
                if r.book == "LOS":
                    r.group_code = e.group_code
                    r.dins = ";".join(e.dins)

    def suffix_variant(self, e: Entity) -> str:
        if e.public:
            core = e.name.removesuffix(" Limited")
            return f"{core} {self.rng.choice(('Limited', 'Ltd', 'Limited'))}"
        core = e.name.removesuffix(" Private Limited")
        return f"{core} {self.rng.choice(('Private Limited', 'Private Limited', 'Pvt Ltd', 'P. Ltd'))}"

    def apply_noise(self, name: str, e: Entity, r: Record, fams: list[str]) -> str:
        """Apply one family; protected records keep the registry name within edit distance 2."""
        protected = e.group_no == plant.HERO_GROUP_NO or any(g.no == e.group_no for g in self.hidden_breach_groups)
        order = list(fams)
        self.rng.shuffle(order)
        for fam in order:
            out = FAMILY_FUNCS[fam](name, self.rng)
            if out == name:
                continue
            if name_std(out) == name_std(name) and fam != "ABBREV":
                continue
            if protected and edit_distance(name_std(out), name_std(e.name)) > 2:
                continue
            r.families.append(fam)
            return out
        return name

    # ----------------------------------------------------------------- facts
    def build_facts(self) -> None:
        rng = self.rng
        s = self.scale
        recs = {b: [r for r in self.records if r.book == b] for b in ("LOS", "TSY", "GTE", "COL")}
        for r in recs["LOS"]:
            self.facts.append(Fact("LOS", self.next_fact_id("LOS-L"), r, rng.choice(PRODUCTS)))
        hero_los = [r for r in recs["LOS"] if r.bucket]
        extra = round(10000 * s) - len(recs["LOS"])
        for r in rng.choices([r for r in recs["LOS"] if not r.bucket], k=max(0, extra - len(hero_los))):
            self.facts.append(Fact("LOS", self.next_fact_id("LOS-L"), r, rng.choice(PRODUCTS)))
        for r in hero_los:   # the hero's LOS customers hold two loans each
            self.facts.append(Fact("LOS", self.next_fact_id("LOS-L"), r, rng.choice(PRODUCTS)))
        for r in recs["TSY"]:
            self.facts.append(Fact("TSY", self.next_fact_id("TSY-H"), r, rng.choice(INSTRUMENTS)))
        for r in rng.choices([r for r in recs["TSY"] if not r.bucket], k=max(0, round(6000 * s) - len(recs["TSY"]))):
            self.facts.append(Fact("TSY", self.next_fact_id("TSY-H"), r, rng.choice(INSTRUMENTS)))
        for r in recs["GTE"]:
            kind = "FIN" if rng.random() < 0.6 else "PERF"
            if r.bucket == "HEAD:T1":
                kind = "PERF"
            self.facts.append(Fact("GTE", self.next_fact_id("GTE-G"), r, kind))
        for r in recs["COL"]:
            self.facts.append(Fact("COL", self.next_fact_id("COL-G"), r, rng.choice(SECURITY_TYPES)))
        self.facts.sort(key=lambda f: (f.book, f.fact_id))

    # ------------------------------------------------------------ exposures
    def set_targets(self) -> None:
        rng = self.rng
        C = CAPITAL_BD3
        normal = [g for g in self.groups.values() if g.kind == "NORMAL" and not g.hidden_breach]
        free_large = [g for g in normal if not g.capped]
        n_large = min(30, max(5, round(30 * self.scale)), len(free_large))
        large = set(g.no for g in rng.sample(free_large, n_large))
        for g in self.groups.values():
            if g.kind == "HERO":
                continue
            if g.hidden_breach == "RO":
                g.target = r100(C * rng.uniform(0.27, 0.33))
            elif g.hidden_breach == "INTERDEP":
                g.target = r100(C * rng.uniform(0.19, 0.21))
            elif g.kind == "JV":
                g.target = r100(C * rng.uniform(0.001, 0.004))
            elif g.no in large:
                g.target = r100(C * rng.uniform(0.10, 0.20))
            elif g.capped or g.kind.startswith("CYCLE"):
                g.target = r100(C * min(0.07, rng.lognormvariate(math.log(0.02), 0.6)))
            else:
                g.target = r100(C * min(0.09, rng.lognormvariate(math.log(0.025), 0.7)))
        # Partners of the INTERDEP hidden breaches lift the combined group to 26-35%.
        for g in self.hidden_breach_groups[3:]:
            dep = next(d for d in self.dependencies if self.entities[d["held"]].group_no == g.no)
            partner = self.groups[self.entities[dep["holder"]].group_no]
            partner.target = r100(C * rng.uniform(0.08, 0.10))

    def allocate_entity_exposure(self) -> None:
        rng = self.rng
        for g in sorted(self.groups.values(), key=lambda g: g.no):
            if g.kind == "HERO":
                continue
            members = [self.entities[m] for m in g.members]
            fixed: dict[int, int] = {}
            if g.hidden_breach == "RO":
                ro = next(e for e in members if "REGISTRY_ONLY" in e.tags)
                fixed[ro.idx] = r100(g.target * 0.36)
            elif g.hidden_breach == "INTERDEP":
                # The head must outweigh the whole partner group (<= 10%), so it stays head
                # once the interdependence edge merges the two.
                fixed[g.head] = r100(g.target * 0.60)
            rest = [e for e in members if e.idx not in fixed]
            weights = []
            for e in rest:
                w = rng.lognormvariate(0, 0.6)
                if e.idx == g.head:
                    w *= 3.0
                weights.append(w)
            remaining = g.target - sum(fixed.values())
            total_w = sum(weights)
            alloc = [r100(remaining * w / total_w) for w in weights]
            alloc[0] += remaining - sum(alloc)
            for e, x in zip(rest, alloc):
                e.exposure = max(100, x)
            for idx, x in fixed.items():
                self.entities[idx].exposure = x

    def assign_fact_amounts(self) -> None:
        rng = self.rng
        by_ent: dict[int, list[Fact]] = defaultdict(list)
        hero_buckets: dict[str, list[Fact]] = defaultdict(list)
        for f in self.facts:
            if f.book == "COL":
                continue
            if f.rec.bucket:
                hero_buckets[f.rec.bucket].append(f)
            else:
                by_ent[f.rec.ent].append(f)
        for ent_idx, facts in sorted(by_ent.items()):
            self.split(self.entities[ent_idx].exposure, facts)
        for bucket, facts in sorted(hero_buckets.items()):
            who, kind = bucket.split(":")
            self.split(HERO_BUCKETS[who][kind], facts)
        for f in self.facts:
            if f.book == "COL":
                f.exposure = 0
        # Gross amounts per fact at BD3; then drift for BD1 / BD2 and the BD3 corrections.
        loan_ids = defaultdict(list)
        for f in self.facts:
            if f.book == "LOS":
                loan_ids[f.rec.ent].append(f.fact_id)
        for f in self.facts:
            if f.book == "LOS":
                out, undrawn = self.loan_split(f.exposure)
                f.amounts["base"] = (out + undrawn, out)
            elif f.book == "TSY":
                f.amounts["base"] = (f.exposure,)
            elif f.book == "GTE":
                f.amounts["base"] = (f.exposure if f.kind == "FIN" else 2 * f.exposure,)
            else:
                linked = loan_ids.get(f.rec.ent)
                f.amounts["linked"] = rng.choice(sorted(linked)) if linked else None
                f.amounts["base"] = (r100(CAPITAL_BD3 * rng.uniform(0.0005, 0.01)),)

    def split(self, total: int, facts: list[Fact]) -> None:
        if not facts:
            raise AssertionError("exposure with no fact to carry it")
        weights = [self.rng.uniform(0.5, 1.5) for _ in facts]
        tw = sum(weights)
        parts = [max(100, int(total * w / tw) // 100 * 100) for w in weights]
        parts[-1] += total - sum(parts)
        if parts[-1] <= 0:
            raise AssertionError("split produced a non-positive part")
        for f, x in zip(facts, parts):
            f.exposure = x

    def loan_split(self, x: int) -> tuple[int, int]:
        """outstanding + 0.2 * undrawn == x exactly, with undrawn a multiple of 500."""
        r = self.rng.uniform(0.55, 1.0)
        sanctioned = x / (0.2 + 0.8 * r)
        undrawn = int((1 - r) * sanctioned // 500) * 500
        out = x - undrawn // 5
        return out, undrawn

    def plan_corrections(self) -> None:
        rng = self.rng
        small = {g.no for g in self.groups.values() if g.kind == "NORMAL" and not g.hidden_breach
                 and not g.capped and g.target < 0.04 * CAPITAL_BD3}
        los = [f for f in self.facts if f.book == "LOS" and self.entities[f.rec.ent].group_no in small]
        gte = [f for f in self.facts if f.book == "GTE" and self.entities[f.rec.ent].group_no in small]
        for f in rng.sample(los, plant.COUNTS["LATE_CORRECTION_LOS"]) + rng.sample(gte, plant.COUNTS["LATE_CORRECTION_GTE"]):
            factor = rng.uniform(0.05, 0.40) * rng.choice((-1, 1))
            self.corrections[f.fact_id] = factor
            self.plants.append(("LATE_CORRECTION", f"{f.book}:{f.fact_id}",
                                f"changed {factor:+.0%} in load -02; reports known before 2026-10-06 10:00 use -01"))
        self.plants.append(("POLICY_CHANGE", "CAPITAL_BASE_INR", "BD2 uses 400 cr, BD3 uses 420 cr"))

    def amounts_at(self, f: Fact, bd: date, load_no: int) -> tuple:
        """Gross amounts of a fact as loaded for (business date, load number)."""
        base = f.amounts["base"]
        if bd == BD3:
            if load_no == 2 and f.fact_id in self.corrections:
                k = 1 + self.corrections[f.fact_id]
                if f.book == "LOS":
                    sanc, out = base
                    new_out = r100(out * k)
                    return (new_out + (sanc - out), new_out)
                return (r100(base[0] * k) if f.kind != "PERF" else 2 * r100(base[0] * k / 2),)
            return base
        drift = random.Random(f"{self.seed}|{f.fact_id}|{bd}").uniform(-0.03, 0.03)
        if f.book == "LOS":
            sanc, out = base
            new_out = r100(out * (1 + drift))
            undrawn = int((sanc - out) * (1 + drift) // 500) * 500
            return (new_out + undrawn, new_out)
        if f.book == "GTE" and f.kind == "PERF":
            return (2 * r100(base[0] * (1 + drift) / 2),)
        return (r100(base[0] * (1 + drift)),)

    @staticmethod
    def exposure_of(f: Fact, amounts: tuple) -> int:
        if f.book == "LOS":
            sanc, out = amounts
            return out + (sanc - out) // 5
        if f.book == "TSY":
            return amounts[0]
        if f.book == "GTE":
            return amounts[0] if f.kind == "FIN" else amounts[0] // 2
        return 0

    # ------------------------------------------------------------ truth & checks
    def entity_exposure_bd3(self) -> dict[int, int]:
        out: dict[int, int] = defaultdict(int)
        for f in self.facts:
            out[f.rec.ent] += self.exposure_of(f, self.amounts_at(f, BD3, 2))
        return out

    def components(self, links: list[tuple[int, int, str]]) -> dict[int, int]:
        parent = list(range(len(self.entities)))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for a, b, _ in links:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
        return {e.idx: find(e.idx) for e in self.entities}

    def truth_heads(self, comp: dict[int, int], expo: dict[int, int]) -> dict[int, int]:
        """Talos head rule per component: uncontrolled first, then largest exposure, then key."""
        controlled = {b for a, b, k in self.truth_links if k == "CONTROL" and comp[a] == comp[b] and a != b}
        members: dict[int, list[int]] = defaultdict(list)
        for idx, root in comp.items():
            members[root].append(idx)
        heads = {}
        for root, ms in members.items():
            heads[root] = sorted(ms, key=lambda m: (m in controlled, -expo[m], self.entities[m].key))[0]
        return heads

    def reported_bd3(self) -> dict[str, int]:
        """Mirror of sql/63_reported_baseline.sql on the final BD3 loads."""
        los = sorted((r for r in self.records if r.book == "LOS"), key=lambda r: r.ref)
        code_of = {r.ref: (r.group_code or f"C:{r.ref}") for r in los}
        by_pan: dict[str, str] = {}
        for r in los:
            if r.pan:
                by_pan.setdefault(r.pan.strip().upper(), r.ref)
        out: dict[str, int] = defaultdict(int)
        for f in self.facts:
            x = self.exposure_of(f, self.amounts_at(f, BD3, 2))
            if f.book == "LOS":
                out[code_of[f.rec.ref]] += x
            elif f.book in ("TSY", "GTE"):
                cust = by_pan.get((f.rec.pan or "").strip().upper())
                out[code_of[cust] if cust else f"SA:{f.book}:{f.rec.ref}"] += x
        return out

    def check(self) -> dict:
        C = CAPITAL_BD3
        expo = self.entity_exposure_bd3()
        for e in self.entities:
            e.exposure = expo[e.idx]
        comp = self.components(self.truth_links)
        heads = self.truth_heads(comp, expo)
        limit: dict[int, int] = defaultdict(int)
        for idx, root in comp.items():
            limit[root] += expo[idx]
        for jv, ctrl in self.jv_attrib:
            if comp[jv] != comp[ctrl]:
                limit[comp[ctrl]] += expo[jv]
        reported = self.reported_bd3()

        hb_roots = {comp[g.head]: g for g in self.hidden_breach_groups}
        hero = self.groups[plant.HERO_GROUP_NO]
        hb_roots[comp[hero.head]] = hero
        for root, total in limit.items():
            if root in hb_roots:
                g = hb_roots[root]
                assert 0.26 * C <= total <= 0.35 * C, f"hidden breach group {g.no} at {plant.pct(total):.1f}%"
                assert reported.get(g.code, 0) < 0.25 * C, f"hidden breach group {g.no} reported over the limit"
                assert heads[root] == g.head, f"hidden breach group {g.no}: head would not be the group head"
            else:
                assert total <= 0.24 * C, f"non-breach component at {plant.pct(total):.1f}% ({self.entities[root].key})"

        # Hero checkpoints, to the paisa.
        hero_ents = [self.entities[m] for m in hero.members]
        holdco_side = {e.idx for e in hero_ents if e.tags & {"HOLDCO", "HOLDSUB"}}

        def bucket_sum(pred) -> int:
            return sum(self.exposure_of(f, self.amounts_at(f, BD3, 2)) for f in self.facts
                       if f.book != "COL" and f.rec.bucket and pred(f))

        cp = {
            "reported": reported[hero.code],
            "t0_head_only": bucket_sum(lambda f: f.rec.bucket in ("HEAD:REPORTED", "HEAD:CIN_ONLY")),
            "after_ownership_batch": bucket_sum(lambda f: f.rec.bucket.split(":")[1] in ("REPORTED", "CIN_ONLY")
                                                and f.rec.ent not in holdco_side),
            "holdco_group": bucket_sum(lambda f: f.rec.ent in holdco_side),
            "after_t1": bucket_sum(lambda f: f.rec.ent not in holdco_side),
            "after_holdco_link": limit[comp[hero.head]],
        }
        for k, v in HERO_CHECKPOINTS.items():
            assert cp[k] == v, f"hero checkpoint {k}: {cp[k]} != {v}"

        names = Counter(e.name for e in self.entities if e.role != "DECOY")
        dup = [n for n, c in names.items() if c > 1]
        assert not dup, f"non-decoy canonical name collisions: {dup[:3]}"

        self.truth_comp, self.truth_head_of, self.truth_limit = comp, heads, limit
        return {k: str(Decimal(v) / 100 / 100000) + " cr" for k, v in cp.items()}

    # --------------------------------------------------------------- output
    def rows(self) -> dict[str, tuple[pa.Schema, list[tuple]]]:
        d182 = pa.decimal128(18, 2)
        out: dict[str, tuple[pa.Schema, list[tuple]]] = {}

        def money(x: int) -> Decimal:
            return Decimal(x).quantize(Decimal("0.01"))

        s_cust = pa.schema([("cust_id", pa.string()), ("cust_name", pa.string()), ("pan", pa.string()), ("cin", pa.string()),
                            ("address", pa.string()), ("city", pa.string()), ("state_code", pa.string()),
                            ("group_code", pa.string()), ("director_dins", pa.string()), ("business_date", pa.date32()),
                            ("load_id", pa.string()), ("loaded_at", pa.timestamp("us"))])
        s_loan = pa.schema([("loan_id", pa.string()), ("cust_id", pa.string()), ("product", pa.string()),
                            ("sanctioned_amt", d182), ("outstanding_amt", d182), ("business_date", pa.date32()),
                            ("load_id", pa.string()), ("loaded_at", pa.timestamp("us"))])
        s_dep = pa.schema([("cust_id", pa.string()), ("depends_on_cust_id", pa.string()), ("share_pct", pa.decimal128(5, 2)),
                           ("noted_on", pa.date32()), ("business_date", pa.date32()), ("load_id", pa.string()),
                           ("loaded_at", pa.timestamp("us"))])
        s_tsy = pa.schema([("holding_id", pa.string()), ("issuer_ref", pa.string()), ("issuer_name", pa.string()),
                           ("pan", pa.string()), ("cin", pa.string()), ("lei", pa.string()), ("address", pa.string()),
                           ("city", pa.string()), ("state_code", pa.string()), ("instrument", pa.string()),
                           ("carrying_value", d182), ("business_date", pa.date32()), ("load_id", pa.string()),
                           ("loaded_at", pa.timestamp("us"))])
        s_gte = pa.schema([("guarantee_id", pa.string()), ("party_ref", pa.string()), ("party_name", pa.string()),
                           ("pan", pa.string()), ("cin", pa.string()), ("address", pa.string()), ("city", pa.string()),
                           ("state_code", pa.string()), ("kind", pa.string()), ("amount", d182), ("expiry_date", pa.date32()),
                           ("business_date", pa.date32()), ("load_id", pa.string()), ("loaded_at", pa.timestamp("us"))])
        s_col = pa.schema([("pledge_id", pa.string()), ("pledgor_ref", pa.string()), ("pledgor_name", pa.string()),
                           ("pan", pa.string()), ("cin", pa.string()), ("address", pa.string()), ("city", pa.string()),
                           ("state_code", pa.string()), ("security_type", pa.string()), ("pledge_value", d182),
                           ("linked_loan_id", pa.string()), ("business_date", pa.date32()), ("load_id", pa.string()),
                           ("loaded_at", pa.timestamp("us"))])

        loads = [(bd, 1, loaded_at(bd)) for bd in BUSINESS_DATES]
        corr = (BD3, 2, CORRECTION_AT)
        primary_cust = {r.ent: r.ref for r in self.records if r.book == "LOS" and r.primary}
        cust_rows, loan_rows, dep_rows, tsy_rows, gte_rows, col_rows = [], [], [], [], [], []
        los_recs = sorted((r for r in self.records if r.book == "LOS"), key=lambda r: r.ref)
        facts_by_book = defaultdict(list)
        for f in self.facts:
            facts_by_book[f.book].append(f)
        background = self.background_dependencies(primary_cust)
        for bd, n, at in loads + [corr]:
            lid_los = load_id("LOS", bd, n)
            for r in los_recs:
                cust_rows.append((r.ref, r.name, r.pan, r.cin, r.address, r.city, r.state, r.group_code, r.dins, bd, lid_los, at))
            for f in facts_by_book["LOS"]:
                sanc, out_amt = self.amounts_at(f, bd, n)
                loan_rows.append((f.fact_id, f.rec.ref, f.kind, money(sanc), money(out_amt), bd, lid_los, at))
            for d in sorted(self.dependencies, key=lambda d: (d["held"], d["holder"])) + background:
                dep_rows.append((primary_cust[d["held"]], primary_cust[d["holder"]], d["share"], d["noted_on"], bd, lid_los, at))
            if n == 1:
                lid = load_id("TSY", bd)
                for f in facts_by_book["TSY"]:
                    r = f.rec
                    tsy_rows.append((f.fact_id, r.ref, r.name, r.pan, r.cin, r.lei, r.address, r.city, r.state, f.kind,
                                     money(self.amounts_at(f, bd, 1)[0]), bd, lid, at))
                lid = load_id("COL", bd)
                for f in facts_by_book["COL"]:
                    r = f.rec
                    col_rows.append((f.fact_id, r.ref, r.name, r.pan, r.cin, r.address, r.city, r.state, f.kind,
                                     money(self.amounts_at(f, bd, 1)[0]), f.amounts["linked"], bd, lid, at))
            lid = load_id("GTE", bd, n)
            for f in facts_by_book["GTE"]:
                r = f.rec
                expiry = date(2027 + int(f.fact_id[-1]) % 3, 3, 31)
                gte_rows.append((f.fact_id, r.ref, r.name, r.pan, r.cin, r.address, r.city, r.state, f.kind,
                                 money(self.amounts_at(f, bd, n)[0]), expiry, bd, lid, at))
        out["raw/los_customer"] = (s_cust, cust_rows)
        out["raw/los_loan"] = (s_loan, loan_rows)
        out["raw/los_dependency"] = (s_dep, dep_rows)
        out["raw/treasury_holding"] = (s_tsy, tsy_rows)
        out["raw/guarantee"] = (s_gte, gte_rows)
        out["raw/pledge"] = (s_col, col_rows)

        s_fil = pa.schema([("cin", pa.string()), ("pan", pa.string()), ("lei", pa.string()), ("entity_name", pa.string()),
                           ("address", pa.string()), ("city", pa.string()), ("state_code", pa.string()),
                           ("incorporated_on", pa.date32()), ("director_dins", pa.string()), ("filed_on", pa.date32()),
                           ("load_id", pa.string()), ("loaded_at", pa.timestamp("us"))])
        fil_rows = []
        for e in self.entities:
            inc = date(int(e.cin[8:12]), 1 + e.idx % 12, 1 + e.idx % 28)
            fil_rows.append((e.cin, e.pan if e.filing_has_pan else None, e.lei, e.name, e.address, e.city, e.state, inc,
                             ";".join(e.dins), date(2026, 6, 30), REG_LOAD_ID, REG_LOADED_AT))
        out["raw/entity_filing"] = (s_fil, fil_rows)
        s_edge = pa.schema([("holder_cin", pa.string()), ("held_cin", pa.string()), ("stake_pct", pa.decimal128(7, 4)),
                            ("control_flag", pa.bool_()), ("effective_from", pa.date32()), ("filed_on", pa.date32()),
                            ("load_id", pa.string()), ("loaded_at", pa.timestamp("us"))])
        out["raw/ownership_edge"] = (s_edge, [(x["holder_cin"], x["held_cin"], x["stake_pct"], x["control_flag"],
                                               x["effective_from"], x["filed_on"], REG_LOAD_ID, REG_LOADED_AT)
                                              for x in sorted(self.edges, key=lambda x: (x["held_cin"], x["holder_cin"]))])
        s_pin = pa.schema([("pincode", pa.string()), ("district", pa.string()), ("state_code", pa.string())])
        pin_rows = [(str(p), c.city_name, st) for st in STATE_CODES for c in STATES_GEO[st].cities
                    for p in range(c.pincode_start, c.pincode_end + 1)]
        out["raw/pincode_district"] = (s_pin, pin_rows)

        # Truth
        comp, heads = self.truth_comp, self.truth_head_of
        hb_nos = {g.no for g in self.hidden_breach_groups} | {plant.HERO_GROUP_NO}
        s_ent = pa.schema([("entity_key", pa.string()), ("group_no", pa.int32()), ("role", pa.string()), ("canonical_name", pa.string())])
        ent_rows = []
        for e in self.entities:
            role = e.role
            g = self.groups.get(e.group_no)
            if g and g.kind.startswith("CYCLE"):
                role = "HEAD" if heads[comp[e.idx]] == e.idx else "SUB"
            ent_rows.append((e.key, e.group_no, role, e.name))
        out["truth/gt_entity"] = (s_ent, ent_rows)
        s_rec = pa.schema([("rec_key", pa.string()), ("entity_key", pa.string()), ("noise_families", pa.string())])
        out["truth/gt_record_entity"] = (s_rec, [(r.rec_key, self.entities[r.ent].key, ",".join(r.families) or None)
                                                 for r in sorted(self.records, key=lambda r: r.rec_key)])
        s_grp = pa.schema([("group_no", pa.int32()), ("head_entity_key", pa.string()), ("los_group_code", pa.string()),
                           ("is_hidden_breach", pa.bool_()), ("is_hero", pa.bool_())])
        grp_rows = []
        for no, g in sorted(self.groups.items()):
            head = self.entities[g.head]
            if g.kind == "CYCLE_ROOTLESS":
                head = self.entities[heads[comp[g.head]]]   # every member is controlled: largest exposure
            if g.kind == "JV" and self.entities[g.head].group_no != no:
                continue   # SINGLE ruling: the JV sits in its controller's group
            grp_rows.append((no, head.key, g.code, no in hb_nos, no == plant.HERO_GROUP_NO))
        out["truth/gt_group"] = (s_grp, grp_rows)
        s_gte_ = pa.schema([("holder_entity_key", pa.string()), ("held_entity_key", pa.string()), ("edge_kind", pa.string()),
                            ("control_type", pa.string()), ("admitted", pa.bool_())])
        out["truth/gt_edge"] = (s_gte_, sorted(self.gt_edges, key=lambda t: (t[1], t[0], t[2])))
        s_jv = pa.schema([("held_entity_key", pa.string()), ("ruling", pa.string()), ("controller_entity_key", pa.string())])
        out["truth/gt_jv_ruling"] = (s_jv, list(self.jv_rulings))
        s_pl = pa.schema([("plant_id", pa.string()), ("kind", pa.string()), ("subject_key", pa.string()), ("expected", pa.string())])
        counters: Counter = Counter()
        pl_rows = []
        for g in [self.groups[plant.HERO_GROUP_NO]] + self.hidden_breach_groups:
            self.plants.append(("HIDDEN_BREACH", self.entities[g.head].key,
                                f"true exposure {plant.pct(self.truth_limit[comp[g.head]]):.1f}% of capital; reported under 25%"))
        for kind, subject, expected in self.plants:
            counters[kind] += 1
            abbrev = "".join(w[0] for w in kind.split("_"))
            pl_rows.append((f"{abbrev}-{counters[kind]:03d}", kind, subject, expected[:200]))
        out["truth/gt_plant"] = (s_pl, pl_rows)
        return out

    def background_dependencies(self, primary_cust: dict[int, str]) -> list[dict]:
        """Credit-memo dependencies below the interdependence threshold (never proposed)."""
        rng = random.Random(f"{self.seed}|deps")
        ents = sorted(primary_cust)
        rows = []
        for _ in range(round(200 * self.scale)):
            a, b = rng.sample(ents, 2)
            rows.append({"held": a, "holder": b, "share": Decimal(rng.randint(5, 45)),
                         "noted_on": date(2025, 4, 1) + timedelta(days=rng.randint(0, 450))})
        return rows

    def build(self) -> dict:
        self.build_groups()
        self.plant_cases()
        self.build_records()
        self.build_facts()
        self.set_targets()
        self.allocate_entity_exposure()
        self.assign_fact_amounts()
        self.plan_corrections()
        return self.check()


def canonical_hash(rows: list[tuple]) -> str:
    h = hashlib.sha256()
    for row in sorted(repr(r) for r in rows):
        h.update(row.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def generate(profile: str = "dev", out_dir: str | Path = "data/out/dev", scale: float | None = None,
             seed: int | None = None, seed_from_commit: str | None = None) -> dict:
    """Build the world for a profile, assert the planted figures, and write Parquet + manifest."""
    prof, eff_seed, eff_scale = resolve(profile, scale, seed, seed_from_commit)
    world = World(prof, eff_seed, eff_scale)
    hero = world.build()
    tables = world.rows()

    out = Path(out_dir)
    manifest = {"profile": prof.name, "seed": eff_seed, "scale": eff_scale, "seed_from_commit": seed_from_commit,
                "name_families": list(prof.name_families), "hero_checkpoints": hero, "tables": {}}
    for name, (schema, rows) in sorted(tables.items()):
        path = out / f"{name}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        cols = list(zip(*rows)) if rows else [[] for _ in schema]
        table = pa.Table.from_arrays([pa.array(list(c), type=f.type) for c, f in zip(cols, schema)], schema=schema)
        pq.write_table(table, path)
        manifest["tables"][name] = {"rows": len(rows), "sha256": canonical_hash(rows)}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return manifest
