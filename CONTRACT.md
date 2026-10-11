# CONTRACT.md — Frozen Interface Specification (Talos)

> **Status:** FROZEN  
> **Date:** Saturday 11 October 2026, 20:00 IST  
> **Sign-off:** Track A (Exasol & Data), Track B (AI & Orchestration), Track C (Product, Web App & Story)  
> **Rule:** No breaking modifications to DDL, view schemas, verdict schemas, or service signatures without mutual sign-off and an entry in `docs/DECISIONS.md`.

---

## 1. Exasol DDL

All table and view names are fully qualified with their schema. Financial amounts are `DECIMAL(18,2)` INR, percentages `DECIMAL(7,4)`, and timestamps `TIMESTAMP` UTC.

### 1.1 Raw Books (`02_raw.sql`)
Append-only snapshots. One load per book per business date.

```sql
CREATE TABLE RAW_LOS.CUSTOMER (
  cust_id VARCHAR(20) NOT NULL,
  cust_name VARCHAR(200) NOT NULL,
  pan VARCHAR(12),
  cin VARCHAR(24),
  address VARCHAR(400),
  city VARCHAR(60),
  state_code VARCHAR(2),
  group_code VARCHAR(20),            -- Stale annual group map (reported baseline)
  director_dins VARCHAR(200),        -- ';'-joined 8-digit DINs
  business_date DATE NOT NULL,
  load_id VARCHAR(32) NOT NULL,
  loaded_at TIMESTAMP NOT NULL
);

CREATE TABLE RAW_LOS.LOAN (
  loan_id VARCHAR(20) NOT NULL,
  cust_id VARCHAR(20) NOT NULL,
  product VARCHAR(20) NOT NULL,      -- TERM_LOAN | WORKING_CAPITAL | CC_OD
  sanctioned_amt DECIMAL(18,2) NOT NULL,
  outstanding_amt DECIMAL(18,2) NOT NULL,
  business_date DATE NOT NULL,
  load_id VARCHAR(32) NOT NULL,
  loaded_at TIMESTAMP NOT NULL
);

CREATE TABLE RAW_LOS.DEPENDENCY (
  cust_id VARCHAR(20) NOT NULL,
  depends_on_cust_id VARCHAR(20) NOT NULL,
  share_pct DECIMAL(5,2) NOT NULL,   -- % of cust's revenue from / output to other (credit appraisal)
  noted_on DATE NOT NULL,
  business_date DATE NOT NULL,
  load_id VARCHAR(32) NOT NULL,
  loaded_at TIMESTAMP NOT NULL
);

CREATE TABLE RAW_TREASURY.HOLDING (
  holding_id VARCHAR(20) NOT NULL,
  issuer_ref VARCHAR(20) NOT NULL,
  issuer_name VARCHAR(200) NOT NULL,
  pan VARCHAR(12),
  cin VARCHAR(24),
  lei VARCHAR(24),
  address VARCHAR(400),
  city VARCHAR(60),
  state_code VARCHAR(2),
  instrument VARCHAR(10) NOT NULL,   -- NCD | CP | BOND
  carrying_value DECIMAL(18,2) NOT NULL,
  business_date DATE NOT NULL,
  load_id VARCHAR(32) NOT NULL,
  loaded_at TIMESTAMP NOT NULL
);

CREATE TABLE RAW_GUARANTEE.GUARANTEE (
  guarantee_id VARCHAR(20) NOT NULL,
  party_ref VARCHAR(20) NOT NULL,
  party_name VARCHAR(200) NOT NULL,
  pan VARCHAR(12),
  cin VARCHAR(24),
  address VARCHAR(400),
  city VARCHAR(60),
  state_code VARCHAR(2),
  kind VARCHAR(4) NOT NULL,          -- FIN | PERF
  amount DECIMAL(18,2) NOT NULL,
  expiry_date DATE,
  business_date DATE NOT NULL,
  load_id VARCHAR(32) NOT NULL,
  loaded_at TIMESTAMP NOT NULL
);

CREATE TABLE RAW_COLLATERAL.PLEDGE (
  pledge_id VARCHAR(20) NOT NULL,
  pledgor_ref VARCHAR(20) NOT NULL,
  pledgor_name VARCHAR(200) NOT NULL,
  pan VARCHAR(12),
  cin VARCHAR(24),
  address VARCHAR(400),
  city VARCHAR(60),
  state_code VARCHAR(2),
  security_type VARCHAR(12) NOT NULL,
  pledge_value DECIMAL(18,2) NOT NULL,
  linked_loan_id VARCHAR(20),
  business_date DATE NOT NULL,
  load_id VARCHAR(32) NOT NULL,
  loaded_at TIMESTAMP NOT NULL
);

CREATE TABLE RAW_REGISTRY.ENTITY_FILING (
  cin VARCHAR(24) NOT NULL,
  pan VARCHAR(12),
  lei VARCHAR(24),
  entity_name VARCHAR(200) NOT NULL,
  address VARCHAR(400),
  city VARCHAR(60),
  state_code VARCHAR(2),
  incorporated_on DATE,
  director_dins VARCHAR(200),
  filed_on DATE NOT NULL,
  load_id VARCHAR(32) NOT NULL,
  loaded_at TIMESTAMP NOT NULL
);

CREATE TABLE RAW_REGISTRY.OWNERSHIP_EDGE (
  holder_cin VARCHAR(24) NOT NULL,
  held_cin VARCHAR(24) NOT NULL,
  stake_pct DECIMAL(7,4) NOT NULL,
  control_flag BOOLEAN NOT NULL,
  effective_from DATE NOT NULL,
  filed_on DATE NOT NULL,
  load_id VARCHAR(32) NOT NULL,
  loaded_at TIMESTAMP NOT NULL
);
```

---

### 1.2 STAGE & RESOLVE (`03_stage_resolve.sql`)
Rebuilt every match run. Derived working structures.

```sql
CREATE TABLE STAGE.RECORD_STD (
  rec_key VARCHAR(40) NOT NULL,      -- 'LOS:cust_id' | 'TSY:issuer_ref' | 'GTE:party_ref' | 'COL:pledgor_ref' | 'REG:cin'
  side VARCHAR(4) NOT NULL,          -- BOOK | REG
  source_system VARCHAR(4) NOT NULL,
  source_ref VARCHAR(24) NOT NULL,
  name_raw VARCHAR(200),
  name_std VARCHAR(200),
  name_nospace VARCHAR(200),
  first_token VARCHAR(60),
  soundex_first VARCHAR(8),
  cologne_first VARCHAR(60),
  address_raw VARCHAR(400),
  city VARCHAR(60),
  district VARCHAR(60),
  state_code VARCHAR(2),
  pincode VARCHAR(6),
  pan_raw VARCHAR(12),
  cin_raw VARCHAR(24),
  lei_raw VARCHAR(24),
  director_tok VARCHAR(2000),        -- ';'-joined HASH_SHA256('DIN:'||din)
  DISTRIBUTE BY rec_key
);

CREATE TABLE STAGE.RECORD_ID_TOKEN (
  rec_key VARCHAR(40) NOT NULL,
  side VARCHAR(4) NOT NULL,
  id_type VARCHAR(8) NOT NULL,
  token VARCHAR(64) NOT NULL,
  DISTRIBUTE BY token
);

CREATE TABLE STAGE.RECORD_BLOCK_KEY (
  rec_key VARCHAR(40) NOT NULL,
  side VARCHAR(4) NOT NULL,
  pass_name VARCHAR(4) NOT NULL,
  block_key VARCHAR(220) NOT NULL,
  DISTRIBUTE BY block_key
);

CREATE TABLE STAGE.BLOCK_DROPPED (
  pass_name VARCHAR(4) NOT NULL,
  block_key VARCHAR(220) NOT NULL,
  book_n DECIMAL(9) NOT NULL,
  reg_n DECIMAL(9) NOT NULL
);

CREATE TABLE RESOLVE.CANDIDATE_PAIR (
  pair_key VARCHAR(16) NOT NULL,
  rec_a VARCHAR(40) NOT NULL,        -- Always BOOK side
  rec_b VARCHAR(40) NOT NULL,        -- Always REG side
  via VARCHAR(40) NOT NULL,          -- 'EXACT_PAN' | 'P1,P2'
  name_dist DECIMAL(5) NOT NULL,
  DISTRIBUTE BY rec_a
);

CREATE TABLE RESOLVE.PAIR_SCORE (
  pair_key VARCHAR(16) NOT NULL,
  rec_a VARCHAR(40) NOT NULL,
  rec_b VARCHAR(40) NOT NULL,
  via VARCHAR(40) NOT NULL,
  name_dist DECIMAL(5) NOT NULL,
  name_sim DOUBLE NOT NULL,
  phon_eq DECIMAL(1) NOT NULL,
  pin_eq DECIMAL(1) NOT NULL,
  state_eq DECIMAL(1) NOT NULL,
  id_agree DECIMAL(1) NOT NULL,
  id_conflict DECIMAL(1) NOT NULL,
  conflict_types VARCHAR(20),
  composite DOUBLE NOT NULL,
  tier VARCHAR(20) NOT NULL,         -- Widened from VARCHAR(2) for marker tiers (DISCARD_ID_CONFLICT, DISCARD_LOW_SCORE)
  tier_reason VARCHAR(40) NOT NULL
);

CREATE TABLE RESOLVE.LLM_VERDICT (
  pair_key VARCHAR(16) NOT NULL,
  packet_hash VARCHAR(64) NOT NULL,
  model VARCHAR(80) NOT NULL,
  raw_response VARCHAR(4000),
  decision VARCHAR(10),
  confidence DECIMAL(4,3),
  evidence_used VARCHAR(200),
  rationale VARCHAR(400),
  valid BOOLEAN NOT NULL,
  invalid_reason VARCHAR(200),
  latency_ms DECIMAL(9),
  called_at TIMESTAMP NOT NULL
);

CREATE TABLE RESOLVE.W_RECORD_ENTITY_RUN (
  rec_key VARCHAR(40) NOT NULL,
  entity_key VARCHAR(48) NOT NULL,
  decision_id VARCHAR(40) NOT NULL,
  proposal_id VARCHAR(16) NOT NULL
);

CREATE TABLE RESOLVE.W_EDGE_RUN (
  edge_key VARCHAR(100) NOT NULL,
  holder_key VARCHAR(48) NOT NULL,
  held_key VARCHAR(48) NOT NULL,
  edge_kind VARCHAR(10) NOT NULL,
  control_type VARCHAR(10),
  status VARCHAR(10) NOT NULL,
  stake_pct DECIMAL(7,4),
  decision_id VARCHAR(40) NOT NULL
);

CREATE TABLE RESOLVE.W_ENTITY_RUN (
  entity_key VARCHAR(48) NOT NULL,
  display_name VARCHAR(200)
);

CREATE TABLE RESOLVE.W_ENTITY_EXPOSURE_RUN (
  entity_key VARCHAR(48) NOT NULL,
  exposure DECIMAL(18,2) NOT NULL
);

CREATE TABLE RESOLVE.W_COMPONENT_RUN (
  entity_id VARCHAR(48) NOT NULL,
  label VARCHAR(48) NOT NULL,
  DISTRIBUTE BY entity_id
);
```

---

### 1.3 GRAPH & GOV (`04_graph_gov.sql`)
Append-only governance records and admitted graph events.

```sql
CREATE TABLE GRAPH.LINK_EVENT (
  event_id VARCHAR(48) NOT NULL,
  link_key VARCHAR(100) NOT NULL,    -- rec_key||'>'||entity_key
  rec_key VARCHAR(40) NOT NULL,
  entity_key VARCHAR(48) NOT NULL,
  action VARCHAR(8) NOT NULL,        -- ASSERT | RETRACT | DNL
  evidence_hash VARCHAR(64),
  valid_from DATE NOT NULL,
  valid_to DATE NOT NULL,
  recorded_at TIMESTAMP NOT NULL,
  decision_id VARCHAR(40) NOT NULL,
  proposal_id VARCHAR(16)
);

CREATE TABLE GRAPH.OWNERSHIP_EVENT (
  event_id VARCHAR(48) NOT NULL,
  edge_key VARCHAR(100) NOT NULL,    -- kind||':'||holder||'>'||held
  holder_entity_key VARCHAR(48) NOT NULL,
  held_entity_key VARCHAR(48) NOT NULL,
  edge_kind VARCHAR(10) NOT NULL,    -- CONTROL | INTERDEP
  control_type VARCHAR(10),          -- MAJORITY | JOINT | MINORITY | UNKNOWN
  status VARCHAR(10) NOT NULL,       -- PROPOSED | CONFIRMED | AMBIGUOUS | REJECTED
  stake_pct DECIMAL(7,4),
  action VARCHAR(8) NOT NULL,        -- ASSERT | RETRACT
  evidence_hash VARCHAR(64),
  valid_from DATE NOT NULL,
  valid_to DATE NOT NULL,
  recorded_at TIMESTAMP NOT NULL,
  decision_id VARCHAR(40) NOT NULL,
  proposal_id VARCHAR(16)
);

CREATE TABLE GRAPH.RULING_EVENT (
  event_id VARCHAR(48) NOT NULL,
  ruling_key VARCHAR(60) NOT NULL,   -- 'JV:'||held_entity_key
  held_entity_key VARCHAR(48) NOT NULL,
  ruling VARCHAR(10) NOT NULL,       -- SINGLE | JOINT | NONE | CONNECTED
  controller_entity_key VARCHAR(48),
  valid_from DATE NOT NULL,
  valid_to DATE NOT NULL,
  recorded_at TIMESTAMP NOT NULL,
  decision_id VARCHAR(40) NOT NULL,
  proposal_id VARCHAR(16)
);

CREATE TABLE GRAPH.ENTITY (
  entity_key VARCHAR(48) NOT NULL,
  cin VARCHAR(24),
  display_name VARCHAR(200),
  first_published_at TIMESTAMP NOT NULL,
  decision_id VARCHAR(40) NOT NULL
);

CREATE TABLE GOV.PROPOSAL (
  proposal_id VARCHAR(16) NOT NULL,
  kind VARCHAR(16) NOT NULL,         -- RECORD_LINK | OWNERSHIP | INTERDEP | CONTROL_RULING | CONTROLLER_LINK
  subject_key VARCHAR(100) NOT NULL,
  pair_key VARCHAR(16),
  rec_key VARCHAR(40),
  entity_key VARCHAR(48),
  holder_entity_key VARCHAR(48),
  held_entity_key VARCHAR(48),
  tier VARCHAR(20),
  tier_reason VARCHAR(40),
  warning VARCHAR(200),
  evidence_json VARCHAR(20000) NOT NULL,
  evidence_hash VARCHAR(64) NOT NULL,
  rupee_impact DECIMAL(18,2) NOT NULL,
  batch_id VARCHAR(16),              -- 'B-REC-...' for T0 or 'B-OWN-...' for corroborated ownership
  filed_at TIMESTAMP NOT NULL,
  filed_by_run VARCHAR(40),
  pipeline_version VARCHAR(48)
);

CREATE TABLE GOV.DECISION_LOG (
  decision_id VARCHAR(40) NOT NULL,
  decision VARCHAR(14) NOT NULL,     -- APPROVE | REJECT | DEFER | BATCH_APPROVE | BATCH_FAILED | RULING
  proposal_id VARCHAR(16),
  batch_id VARCHAR(16),
  ruling VARCHAR(10),
  reason VARCHAR(2000) NOT NULL,
  reviewer VARCHAR(80) NOT NULL,
  reviewer_role VARCHAR(12) NOT NULL,
  decided_at TIMESTAMP NOT NULL,
  batch_seed DECIMAL(10),
  sample_json VARCHAR(20000),
  covered_count DECIMAL(9)
);

CREATE TABLE GOV.DECISION_COVERS (
  decision_id VARCHAR(40) NOT NULL,
  proposal_id VARCHAR(16) NOT NULL,
  in_sample BOOLEAN NOT NULL
);

CREATE TABLE GOV.POLICY_EVENT (
  event_id VARCHAR(48) NOT NULL,
  policy_key VARCHAR(40) NOT NULL,
  value_num DECIMAL(24,6),
  value_text VARCHAR(200),
  effective_from DATE NOT NULL,
  effective_to DATE NOT NULL,
  recorded_at TIMESTAMP NOT NULL,
  recorded_by VARCHAR(80) NOT NULL,
  note VARCHAR(400)
);

CREATE TABLE GOV.REPORT_RUN (
  run_id VARCHAR(40) NOT NULL,
  business_date DATE NOT NULL,
  known_at TIMESTAMP NOT NULL,
  load_ids_json VARCHAR(2000) NOT NULL,
  policy_event_ids_json VARCHAR(4000) NOT NULL,
  code_version VARCHAR(48) NOT NULL,
  output_hash VARCHAR(64),
  row_count DECIMAL(12),
  lp_passes DECIMAL(4),
  status VARCHAR(12) NOT NULL,       -- OK | LP_ABORTED
  replay_of VARCHAR(40),
  started_at TIMESTAMP NOT NULL,
  finished_at TIMESTAMP
);

CREATE TABLE GOV.RUN_MEMBERSHIP (
  run_id VARCHAR(40) NOT NULL,
  group_key VARCHAR(48) NOT NULL,
  entity_key VARCHAR(48) NOT NULL,
  membership_kind VARCHAR(16) NOT NULL,  -- MEMBER | JV_ATTRIBUTION
  is_head BOOLEAN NOT NULL,
  group_flags VARCHAR(80),
  DISTRIBUTE BY run_id
);

CREATE TABLE GOV.RUN_OUTPUT (
  run_id VARCHAR(40) NOT NULL,
  group_key VARCHAR(48) NOT NULL,
  entity_key VARCHAR(48) NOT NULL,
  membership_kind VARCHAR(16) NOT NULL,
  source_system VARCHAR(4) NOT NULL,
  source_row_id VARCHAR(24) NOT NULL,
  exposure_component VARCHAR(8) NOT NULL, -- FUNDED | UNDRAWN | HOLDING | GTE_FIN | GTE_PERF
  rec_key VARCHAR(40) NOT NULL,
  product VARCHAR(20),
  gross_amount DECIMAL(18,2) NOT NULL,
  ccf DECIMAL(6,4) NOT NULL,
  exposure_amount DECIMAL(18,2) NOT NULL,
  link_decision_id VARCHAR(40),
  link_proposal_id VARCHAR(16),
  DISTRIBUTE BY run_id
);

CREATE TABLE GOV.RUN_REPORTED (
  run_id VARCHAR(40) NOT NULL,
  reported_group VARCHAR(40) NOT NULL,
  reported_exposure DECIMAL(18,2) NOT NULL
);

CREATE TABLE GOV.PIPELINE_TIMING (
  job_id VARCHAR(40) NOT NULL,
  stage VARCHAR(40) NOT NULL,
  rows_affected DECIMAL(12),
  seconds DECIMAL(9,3),
  started_at TIMESTAMP NOT NULL
);
```

---

### 1.4 TRUTH (`05_truth.sql`)
Accessible solely by `TALOS_LOADER` and `TALOS_EVAL`.

```sql
CREATE TABLE TRUTH.GT_ENTITY (
  entity_key VARCHAR(48),
  group_no DECIMAL(5),
  role VARCHAR(12),
  canonical_name VARCHAR(200)
);

CREATE TABLE TRUTH.GT_RECORD_ENTITY (
  rec_key VARCHAR(40),
  entity_key VARCHAR(48),
  noise_families VARCHAR(80)
);

CREATE TABLE TRUTH.GT_GROUP (
  group_no DECIMAL(5),
  head_entity_key VARCHAR(48),
  los_group_code VARCHAR(20),
  is_hidden_breach BOOLEAN,
  is_hero BOOLEAN
);

CREATE TABLE TRUTH.GT_EDGE (
  holder_entity_key VARCHAR(48),
  held_entity_key VARCHAR(48),
  edge_kind VARCHAR(10),
  control_type VARCHAR(10),
  admitted BOOLEAN
);

CREATE TABLE TRUTH.GT_JV_RULING (
  held_entity_key VARCHAR(48),
  ruling VARCHAR(10),
  controller_entity_key VARCHAR(48)
);

CREATE TABLE TRUTH.GT_PLANT (
  plant_id VARCHAR(20),
  kind VARCHAR(24),
  subject_key VARCHAR(100),
  expected VARCHAR(200)
);
```

---

## 2. Policy Keys & Units (`GOV.POLICY_EVENT`)

Percentages are stored strictly as whole numbers:

| Key | Unit / Type | Dev / Default Value | Purpose |
|---|---|---|---|
| `CAPITAL_BASE_INR` | INR Amount | 4,000,000,000.00 (₹400 cr, moves to ₹420 cr on 2026-09-01) | Eligible capital denominator |
| `GROUP_LIMIT_PCT` | Whole % | 25 | Regulatory limit for connected group (25%) |
| `LE_LINE_PCT` | Whole % | 10 | Large exposure reporting line (10%) |
| `T0_SAMPLE_PCT` | Whole % | 5 | Sample review percentage for exact-ID record links (5%) |
| `T0_SAMPLE_MIN` | Integer Count | 20 | Minimum sampled pairs for T0 record link batch |
| `OWN_SAMPLE_PCT` | Whole % | 2 | Sample review percentage for corroborated ownership batch (2%) |
| `OWN_SAMPLE_MIN` | Integer Count | 20 | Minimum sampled pairs for corroborated ownership batch |
| `CCF_UNDRAWN` | Decimal CCF | 0.20 | Credit Conversion Factor for undrawn sanctioned limits |
| `CCF_GTE_FIN` | Decimal CCF | 1.00 | CCF for financial guarantees |
| `CCF_GTE_PERF` | Decimal CCF | 0.50 | CCF for performance guarantees |
| `CCF_COLLATERAL` | Decimal CCF | 0.00 | Collateral carries identity only; exposure CCF is 0 |
| `JV_COUNT_IN_CONTROLLERS` | Integer Flag | 1 | If 1, JV exposure is attributed to each controlling parent |
| `MAJORITY_MIN_PCT` | Whole % | 50 | Equity threshold for majority control edge |
| `INTERDEP_SHARE_MIN` | Whole % | 50 | Minimum credit dependency share threshold |
| `LP_MAX_PASSES` | Integer Count | 50 | Maximum Label Propagation convergence iterations |
| `BLOCK_MAX` | Integer Count | 500 | Max records per block before dropping oversize candidate keys |

### 2.1 Matching thresholds

Matching thresholds are scores in the range 0 to 1 (not percentages, so the whole-number rule above does not apply). `policy/thresholds.json` is the source file. `talos load` writes each key to `GOV.POLICY_EVENT` as a policy event (effective from 2026-04-01), so a replay reads the value that was in force. They are frozen and committed before the test dataset is generated.

| Key | Value | Purpose |
|---|---|---|
| `ID_NAME_MIN_SIM` | 0.60 | Below this name similarity, a shared ID is an ID-name conflict (T3) |
| `T1_MAX_DIST` | 2 | Maximum edit distance for T1 when the pincode also matches |
| `T2_LOW` | 0.70 | Composite score below this is discarded (`DISCARD_LOW_SCORE`) |
| `T2_HIGH` | 0.95 | Composite score at or above this is T1; between `T2_LOW` and this is T2 |
| `W_NAME`, `W_PHON`, `W_PIN`, `W_STATE` | 0.60, 0.15, 0.15, 0.10 | Composite score weights (sum to 1.00) |
| `JUDGE_MIN_CONF` | 0.80 | Minimum model confidence for a `same` verdict to count as a recommendation |

---

## 3. REPORT View Schemas (Consumed by UI & MCP via `TALOS_READER`)

All queries run by `ui/queries.py` execute as `TALOS_READER` against the `REPORT` schema.

### 3.1 Core Reporting Views (`81_report_views.sql`)
1. **`REPORT.V_LATEST_RUN`**
   `run_id, business_date, known_at, code_version, output_hash, row_count, lp_passes, status, finished_at`
2. **`REPORT.V_GROUP_EXPOSURE`**
   `run_id, is_latest, group_key, group_name, head_entity_key, member_count, book_exposure, limit_exposure, capital_base, utilisation_pct, is_large, is_breach, group_flags, reported_exposure, hidden_exposure, headroom`
3. **`REPORT.V_ENTITY_EXPOSURE`**
   `run_id, is_latest, entity_key, entity_name, group_key, book_exposure, funded_amt, undrawn_amt, holding_amt, gte_fin_amt, gte_perf_amt, published_at`
4. **`REPORT.V_LINEAGE`**
   `run_id, is_latest, group_key, entity_key, entity_name, source_system, source_row_id, exposure_component, rec_key, product, gross_amount, ccf, exposure_amount, link_proposal_id, link_decision_id, reviewer, decided_at, tier`
5. **`REPORT.V_BREACHES`**
   `run_id, is_latest, group_key, group_name, limit_exposure, utilisation_pct, is_breach, is_large, crossing_type`
6. **`REPORT.V_OWNERSHIP_PATH`** (Reflects current confirmed edges; used for latest run display only)
   `root_key, entity_key, held_name, depth, ownership_path, closes_cycle, control_type, stake_pct`
7. **`REPORT.V_PROPOSAL_QUEUE`**
   `proposal_id, kind, subject_key, pair_key, rec_key, entity_key, holder_entity_key, held_entity_key, tier, tier_reason, warning, evidence_json, rupee_impact, batch_id, batch_kind, batch_total_count, batch_sample_count, group_before_pct, group_after_pct, crosses_le, crosses_limit, group_name, filed_at`
8. **`REPORT.V_DECISIONS`**
   `decision_id, decision, proposal_id, batch_id, ruling, reason, reviewer, reviewer_role, decided_at, covered_count`
9. **`REPORT.V_RUNS`**
   `run_id, business_date, known_at, code_version, output_hash, status, replay_of, started_at, finished_at`
10. **`REPORT.V_GROUP_CHANGES`**
    `run_id_a, run_id_b, group_key, group_name, exposure_a, exposure_b, delta_amt, delta_pct`

### 3.2 Diagnostic Views (`81_report_views.sql`)
Scoped strictly to the latest match execution:
1. **`REPORT.V_PIPELINE_TIMING`**
   `job_id, stage, rows_affected, seconds, started_at`
2. **`REPORT.V_CANDIDATE_PATHS`**
   `via_path, candidate_count, is_dropped_block`
3. **`REPORT.V_TIER_COUNTS`**
   `tier, count` (aggregates `T0`, `T1`, `T2`, `T3`, `DISCARD_ID_CONFLICT`, `DISCARD_LOW_SCORE`)
4. **`REPORT.V_PIPELINE_SUMMARY`**
   `total_book_records, total_reg_entities, total_candidates, settled_in_sql_pct, sent_to_model_pct, reduction_ratio`

---

## 4. LLM Verdict Schema (§7)

Evaluated only on T2 candidate pairs:
```json
{
  "pair_id": "string (matches packet)",
  "decision": "same" | "different" | "unsure",
  "confidence": 0.000,
  "evidence_used": ["name_tokens", "pincode", "district", "id_status", "director_overlap", "source_systems"],
  "rationale": "string <= 40 words"
}
```
Any extra key, invalid field, or out-of-vocabulary evidence token causes the verdict to be recorded with `valid = FALSE` and treated as `unsure`. A schema-valid verdict with confidence below `JUDGE_MIN_CONF` is recorded with `valid = TRUE` but its effective decision is `unsure`, so the audit statistics separate malformed output from low confidence.

---

## 5. Python Orchestrator Service Signatures (§9.2)

### 5.1 Exceptions
```python
class BatchProtectedError(Exception):
    """Raised when an individual decision is attempted on a proposal belonging to an active batch."""
    pass

class ProposalConflictError(Exception):
    """Raised when a proposal already has a terminal decision (HTTP 409)."""
    pass

class UnauthorizedReviewerError(Exception):
    """Raised when an action requires APPROVER role but reviewer is ANALYST (HTTP 403)."""
    pass
```

### 5.1a Result types
```python
@dataclass(frozen=True)
class Reviewer:
    name: str                                   # shown in the decision log
    role: Literal["APPROVER", "ANALYST"]        # only APPROVER may decide

@dataclass(frozen=True)
class DecisionResult:
    decision_id: str                            # 'D-...'
    decision: str                               # APPROVE | REJECT | DEFER | BATCH_APPROVE | BATCH_FAILED | RULING
    proposal_ids: tuple[str, ...]               # every proposal the decision covers
    decided_at: datetime                        # UTC, the same value as recorded_at on the events
    published_run_id: str | None                # run published after the commit, if any

@dataclass(frozen=True)
class BatchSample:
    batch_id: str
    batch_kind: Literal["RECORD_LINK", "OWNERSHIP"]
    seed: int                                   # secrets.randbits(31)
    sample_ids: tuple[str, ...]                 # random.Random(seed).sample(sorted(covered_ids), k)
    covered_ids: tuple[str, ...]                # every proposal in the batch, sorted
    total_count: int
    sample_count: int

@dataclass(frozen=True)
class RunResult:
    run_id: str                                 # 'R-...'
    output_hash: str | None                     # None when status is LP_ABORTED
    status: Literal["OK", "LP_ABORTED"]
    lp_passes: int
    row_count: int

@dataclass(frozen=True)
class ReplayResult:
    original_run_id: str
    replay_run_id: str
    original_hash: str
    replay_hash: str
    matches: bool                               # original_hash == replay_hash
    code_version_differs: bool                  # replayed on different code than the original
```

### 5.2 Signatures
```python
def connect(
    role: Literal["sys", "loader", "pipeline", "approver", "reader", "eval"],
    autocommit: bool = True
) -> pyexasol.ExaConnection:
    """Connect to Exasol Nano using role credentials and Circe TLS patches."""
    ...

def split_sql(text: str) -> list[str]:
    """Split SQL text by ';' outside quotes, comments, and '--/ ... /' UDF blocks."""
    ...

def run_sql_file(conn: pyexasol.ExaConnection, path: str, **params) -> list[int]:
    """Execute SQL file with pyexasol query_params and return statement row counts."""
    ...

def calculate_sample_size(batch_total: int, batch_kind: str, policy: dict) -> int:
    """Compute sample size using integer ceiling: -(-pct * batch_total // 100)."""
    if batch_kind == "OWNERSHIP":
        pct = policy["OWN_SAMPLE_PCT"]
        min_k = policy["OWN_SAMPLE_MIN"]
    else:
        pct = policy["T0_SAMPLE_PCT"]
        min_k = policy["T0_SAMPLE_MIN"]
    calculated = -(-pct * batch_total // 100)
    return min(batch_total, max(min_k, calculated))

def decide(
    proposal_id: str,
    decision: Literal["APPROVE", "REJECT", "DEFER"],
    reason: str,
    reviewer: Reviewer
) -> DecisionResult:
    """
    Execute decision in TALOS_APPROVER transaction.
    Raises BatchProtectedError if proposal has active batch_id.
    """
    ...

def batch_sample(batch_id: str) -> BatchSample:
    """Deterministic sample using secrets.randbits(31) seed over sorted proposal IDs."""
    ...

def batch_decide(
    batch_id: str,
    seed: int,
    verdicts: dict[str, bool],
    reason: str,
    reviewer: Reviewer
) -> DecisionResult:
    """
    All True -> BATCH_APPROVE (writes LINK_EVENTs / OWNERSHIP_EVENTs).
    Any False -> BATCH_FAILED (rejected pairs get DNL; remainder returned to individual cards).
    """
    ...

def rule(
    proposal_id: str,
    ruling: Literal["SINGLE", "JOINT", "NONE", "CONNECTED"],
    controller: str | None,
    reason: str,
    reviewer: Reviewer
) -> DecisionResult:
    """Resolve 50/50 Joint Venture ambiguity with atomic event generation."""
    ...

def publish_run(
    business_date: date,
    known_at: datetime | None = None,
    manifest: dict | None = None,
    replay_of: str | None = None
) -> RunResult:
    """Rebuild working state, execute Label Propagation, write GOV.RUN_*, and compute hash."""
    ...

def replay(run_id: str) -> ReplayResult:
    """In-process execution of publish_run using historical manifest, asserting hash match."""
    ...
```

---

## 6. Generator & Modeling Invariants

1. **Incoming Stakes Invariant**:
   For every entity $H$, the sum of all incoming equity ownership stakes strictly satisfies:
   $$\sum_{P \to H} \text{stake\_pct} \le 100.00\%$$
2. **Redefined Diamond Case**:
   Entity $X$ is held $60.00\%$ by Entity $B$ (majority control), plus has an approved customer credit dependency edge from Entity $C$ (share $\ge 50\%$). Both $B$ and $C$ belong to the same parent group. Exposure of $X$ is admitted via two paths and aggregated exactly once.
3. **Corroborated Ownership Batch**:
   Registry edges where holder and held entity share the same reported LOS `group_code` are grouped into batch `B-OWN-` and approved via sample verification. Only the 60 `REGISTRY_ONLY_PARENT` edges, 10 JVs, 20 standard interdependencies, and 20 diamond interdependencies (~110 total cards) enter individual review.
4. **Hero Group 5-Stage Checkpoints (Paisa-Asserted in `calc.py`)**:
   - Step 0 (Baseline): Reported ₹40,00,00,000.00; Talos = `—`
   - Step 1 (T0 Batch): Reported ₹40,00,00,000.00; Talos = ₹31,20,00,000.00 (Head company alone, no edges yet)
   - Step 2 (Corroborated Batch): Reported ₹40,00,00,000.00; Talos = ₹58,20,00,000.00; HoldCo = ₹36,40,00,000.00 (Crosses 10% line)
   - Step 3 (T1 / T3): Reported ₹40,00,00,000.00; Talos = ₹75,60,00,000.00; HoldCo = ₹36,40,00,000.00
   - Step 4 (Ownership): Reported ₹40,00,00,000.00; Talos = ₹112,00,00,000.00 (Breaches 25% limit)

---

## 7. Roles & Privileges (`sql/06_roles_grants.sql`)

Users are created by `talos init` as SYS. No role holds `UPDATE` or `DELETE` on any `RAW_*`, `GRAPH` or `GOV` table. The only `UPDATE` in the system is on `RESOLVE.W_COMPONENT_RUN`, which is a transient working table and not evidence.

| User | Used by | Privileges |
|---|---|---|
| `TALOS_LOADER` | `talos load` | `CREATE SESSION`. `INSERT` on every `RAW_*` table, every `TRUTH` table, and `GOV.POLICY_EVENT`. |
| `TALOS_PIPELINE` | `talos match`, `talos publish`, `talos replay`, the judge | `SELECT` on `RAW_*`, `GRAPH`, `GOV`. `SELECT, INSERT, DELETE` on `STAGE` and `RESOLVE` (rebuilt each run). `UPDATE` on `RESOLVE.W_COMPONENT_RUN` only. `INSERT` on `GOV.PROPOSAL`, `GOV.REPORT_RUN`, `GOV.RUN_MEMBERSHIP`, `GOV.RUN_OUTPUT`, `GOV.RUN_REPORTED`, `GOV.PIPELINE_TIMING`. Nothing on `GRAPH` except `SELECT`. Nothing on `TRUTH`. |
| `TALOS_APPROVER` | `decide()`, `batch_decide()`, `rule()` | `SELECT` on `STAGE`, `RESOLVE`, `GRAPH`, `GOV`, `RAW_REGISTRY`. `INSERT` on `GRAPH.LINK_EVENT`, `GRAPH.OWNERSHIP_EVENT`, `GRAPH.RULING_EVENT`, `GRAPH.ENTITY`, `GOV.DECISION_LOG`, `GOV.DECISION_COVERS`, `GOV.POLICY_EVENT`. |
| `TALOS_READER` | web console, Exasol MCP server | `SELECT` on the `REPORT` schema only. Views run with owner rights, so no base-table grants are needed. |
| `TALOS_EVAL` | `talos eval` | `SELECT` on everything, including `TRUTH`. |

The `test_grants` test (`pytest -m exasol`) asserts every row of this table, including the denials.
