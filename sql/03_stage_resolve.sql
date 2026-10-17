-- 03_stage_resolve.sql: derived working tables, rebuilt by every talos match / publish.
-- Nothing here is evidence. Candidate pairs are always (book record, registry filing):
-- rec_a is the BOOK side and rec_b the REG side.

CREATE TABLE IF NOT EXISTS STAGE.PINCODE_DISTRICT (
  pincode VARCHAR(6) NOT NULL,
  district VARCHAR(60) NOT NULL,
  state_code VARCHAR(2) NOT NULL
);

CREATE TABLE IF NOT EXISTS STAGE.RECORD_STD (
  rec_key VARCHAR(40) NOT NULL,      -- LOS:cust_id | TSY:issuer_ref | GTE:party_ref | COL:pledgor_ref | REG:cin
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
  director_tok VARCHAR(2000),        -- semicolon-joined HASH_SHA256('DIN:' || din)
  DISTRIBUTE BY rec_key
);

CREATE TABLE IF NOT EXISTS STAGE.RECORD_ID_TOKEN (
  rec_key VARCHAR(40) NOT NULL,
  side VARCHAR(4) NOT NULL,
  id_type VARCHAR(8) NOT NULL,
  token VARCHAR(64) NOT NULL,
  DISTRIBUTE BY token
);

CREATE TABLE IF NOT EXISTS STAGE.RECORD_BLOCK_KEY (
  rec_key VARCHAR(40) NOT NULL,
  side VARCHAR(4) NOT NULL,
  pass_name VARCHAR(4) NOT NULL,
  block_key VARCHAR(220) NOT NULL,
  DISTRIBUTE BY block_key
);

CREATE TABLE IF NOT EXISTS STAGE.BLOCK_DROPPED (
  pass_name VARCHAR(4) NOT NULL,
  block_key VARCHAR(220) NOT NULL,
  book_n DECIMAL(9) NOT NULL,
  reg_n DECIMAL(9) NOT NULL
);

CREATE TABLE IF NOT EXISTS RESOLVE.CANDIDATE_PAIR (
  pair_key VARCHAR(16) NOT NULL,
  rec_a VARCHAR(40) NOT NULL,        -- always BOOK side
  rec_b VARCHAR(40) NOT NULL,        -- always REG side
  via VARCHAR(40) NOT NULL,          -- EXACT_PAN | EXACT_CIN+PAN | P1,P3 ...
  name_dist DECIMAL(5) NOT NULL,
  DISTRIBUTE BY rec_a
);

CREATE TABLE IF NOT EXISTS RESOLVE.PAIR_SCORE (
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
  tier VARCHAR(20) NOT NULL,         -- T0..T3, DISCARD_ID_CONFLICT, DISCARD_LOW_SCORE
  tier_reason VARCHAR(40) NOT NULL,
  DISTRIBUTE BY rec_a
);

CREATE TABLE IF NOT EXISTS RESOLVE.LLM_VERDICT (
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

CREATE TABLE IF NOT EXISTS RESOLVE.W_RECORD_ENTITY_RUN (
  rec_key VARCHAR(40) NOT NULL,
  entity_key VARCHAR(48) NOT NULL,
  decision_id VARCHAR(40) NOT NULL,
  proposal_id VARCHAR(16)
);

CREATE TABLE IF NOT EXISTS RESOLVE.W_EDGE_RUN (
  edge_key VARCHAR(100) NOT NULL,
  holder_key VARCHAR(48) NOT NULL,
  held_key VARCHAR(48) NOT NULL,
  edge_kind VARCHAR(10) NOT NULL,
  control_type VARCHAR(10),
  status VARCHAR(10) NOT NULL,
  stake_pct DECIMAL(7,4),
  decision_id VARCHAR(40) NOT NULL
);

CREATE TABLE IF NOT EXISTS RESOLVE.W_ENTITY_RUN (
  entity_key VARCHAR(48) NOT NULL,
  display_name VARCHAR(200)
);

-- One row per exposure-bearing fact for the run's loads (stage 60). Stage 62 reads it
-- back so the fact rule is written once.
CREATE TABLE IF NOT EXISTS RESOLVE.W_FACT_RUN (
  rec_key VARCHAR(40) NOT NULL,
  source_system VARCHAR(4) NOT NULL,
  source_row_id VARCHAR(24) NOT NULL,
  exposure_component VARCHAR(8) NOT NULL,
  product VARCHAR(20),
  gross_amount DECIMAL(18,2) NOT NULL,
  ccf DECIMAL(6,4) NOT NULL,
  exposure_amount DECIMAL(18,2) NOT NULL,
  DISTRIBUTE BY rec_key
);

CREATE TABLE IF NOT EXISTS RESOLVE.W_ENTITY_EXPOSURE_RUN (
  entity_key VARCHAR(48) NOT NULL,
  exposure DECIMAL(18,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS RESOLVE.W_COMPONENT_RUN (
  entity_id VARCHAR(48) NOT NULL,
  label VARCHAR(48) NOT NULL,
  DISTRIBUTE BY entity_id
);   -- the ONLY table the pipeline ever UPDATEs

-- Admitted edges for the current run, both directions. It reads the per-run working table
-- because Exasol views cannot take business_date / known_at parameters.
CREATE OR REPLACE VIEW RESOLVE.V_ADMITTED_EDGE_UNDIRECTED AS
SELECT holder_key AS a, held_key AS b
FROM RESOLVE.W_EDGE_RUN
WHERE status = 'CONFIRMED'
  AND (control_type = 'MAJORITY' OR edge_kind = 'INTERDEP')
  AND holder_key <> held_key
UNION ALL
SELECT held_key AS a, holder_key AS b
FROM RESOLVE.W_EDGE_RUN
WHERE status = 'CONFIRMED'
  AND (control_type = 'MAJORITY' OR edge_kind = 'INTERDEP')
  AND holder_key <> held_key;

-- Final tier per pair after the judge. The stub provider is not a model, so its verdicts
-- are ignored and its T2 pairs keep the recommendation "no model verdict".
--   T2 + latest real verdict unsure or invalid  -> T3 LLM_UNSURE
--   T2 + same on a pair with an ID conflict      -> T3 LLM_SAME_OVERRULED
--   T2 + same / different                         -> stays T2 with the recommendation
CREATE OR REPLACE VIEW RESOLVE.V_PAIR_TIER_FINAL AS
WITH v AS (
  SELECT pair_key, model, decision, confidence, valid
  FROM RESOLVE.LLM_VERDICT
  WHERE model <> 'stub'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY pair_key ORDER BY called_at DESC, packet_hash DESC) = 1
)
SELECT p.pair_key, p.rec_a, p.rec_b, p.via, p.name_dist, p.name_sim, p.phon_eq, p.pin_eq,
       p.state_eq, p.id_agree, p.id_conflict, p.conflict_types, p.composite,
       p.tier AS base_tier,
       CASE
         WHEN p.tier = 'T2' AND v.pair_key IS NOT NULL
              AND (v.valid = FALSE OR v.decision = 'unsure') THEN 'T3'
         WHEN p.tier = 'T2' AND v.decision = 'same' AND p.id_conflict = 1 THEN 'T3'
         ELSE p.tier
       END AS tier,
       CASE
         WHEN p.tier = 'T2' AND v.pair_key IS NOT NULL
              AND (v.valid = FALSE OR v.decision = 'unsure') THEN 'LLM_UNSURE'
         WHEN p.tier = 'T2' AND v.decision = 'same' AND p.id_conflict = 1 THEN 'LLM_SAME_OVERRULED'
         ELSE p.tier_reason
       END AS tier_reason,
       CASE
         WHEN p.tier <> 'T2' THEN NULL
         WHEN v.pair_key IS NULL THEN 'no model verdict'
         WHEN v.valid = TRUE AND v.decision IN ('same', 'different')
           THEN 'model: ' || v.decision || ' (' || CAST(v.confidence AS VARCHAR(10)) || ')'
         ELSE 'model: unsure'
       END AS recommendation,
       v.model AS verdict_model,
       v.decision AS verdict_decision,
       v.confidence AS verdict_confidence
FROM RESOLVE.PAIR_SCORE p
LEFT JOIN v ON v.pair_key = p.pair_key;
