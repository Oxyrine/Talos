-- 04_graph_gov.sql: append-only evidence. No role holds UPDATE or DELETE on these tables.

CREATE TABLE IF NOT EXISTS GRAPH.LINK_EVENT (
  event_id VARCHAR(48) NOT NULL,
  link_key VARCHAR(100) NOT NULL,    -- rec_key || '>' || entity_key
  rec_key VARCHAR(40) NOT NULL,
  entity_key VARCHAR(48) NOT NULL,
  "ACTION" VARCHAR(8) NOT NULL,        -- ASSERT | RETRACT | DNL
  evidence_hash VARCHAR(64),
  valid_from DATE NOT NULL,
  valid_to DATE NOT NULL,
  recorded_at TIMESTAMP NOT NULL,
  decision_id VARCHAR(40) NOT NULL,
  proposal_id VARCHAR(16)
);

CREATE TABLE IF NOT EXISTS GRAPH.OWNERSHIP_EVENT (
  event_id VARCHAR(48) NOT NULL,
  edge_key VARCHAR(100) NOT NULL,    -- kind || ':' || holder || '>' || held
  holder_entity_key VARCHAR(48) NOT NULL,
  held_entity_key VARCHAR(48) NOT NULL,
  edge_kind VARCHAR(10) NOT NULL,    -- CONTROL | INTERDEP
  control_type VARCHAR(10),          -- MAJORITY | JOINT | MINORITY | UNKNOWN (NULL for INTERDEP)
  status VARCHAR(10) NOT NULL,       -- PROPOSED | CONFIRMED | AMBIGUOUS | REJECTED
  stake_pct DECIMAL(7,4),
  "ACTION" VARCHAR(8) NOT NULL,        -- ASSERT | RETRACT
  evidence_hash VARCHAR(64),
  valid_from DATE NOT NULL,
  valid_to DATE NOT NULL,
  recorded_at TIMESTAMP NOT NULL,
  decision_id VARCHAR(40) NOT NULL,
  proposal_id VARCHAR(16)
);

CREATE TABLE IF NOT EXISTS GRAPH.RULING_EVENT (
  event_id VARCHAR(48) NOT NULL,
  ruling_key VARCHAR(60) NOT NULL,   -- 'JV:' || held_entity_key
  held_entity_key VARCHAR(48) NOT NULL,
  ruling VARCHAR(10) NOT NULL,       -- SINGLE | JOINT | NONE | CONNECTED
  controller_entity_key VARCHAR(48), -- SINGLE only
  valid_from DATE NOT NULL,
  valid_to DATE NOT NULL,
  recorded_at TIMESTAMP NOT NULL,
  decision_id VARCHAR(40) NOT NULL,
  proposal_id VARCHAR(16)
);

CREATE TABLE IF NOT EXISTS GRAPH.ENTITY (
  entity_key VARCHAR(48) NOT NULL,
  cin VARCHAR(24),
  display_name VARCHAR(200),
  first_published_at TIMESTAMP NOT NULL,
  decision_id VARCHAR(40) NOT NULL
);

CREATE TABLE IF NOT EXISTS GOV.PROPOSAL (
  proposal_id VARCHAR(16) NOT NULL,  -- 'P-' || first 12 hex of HASH_SHA256(kind || subject_key || evidence_hash)
  kind VARCHAR(16) NOT NULL,         -- RECORD_LINK | OWNERSHIP | INTERDEP | CONTROL_RULING | CONTROLLER_LINK
  subject_key VARCHAR(100) NOT NULL, -- link_key | edge_key | ruling_key
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
  batch_id VARCHAR(16),              -- B-REC-... (T0 record links) | B-OWN-... (corroborated ownership)
  filed_at TIMESTAMP NOT NULL,
  filed_by_run VARCHAR(40),
  pipeline_version VARCHAR(48)
);

CREATE TABLE IF NOT EXISTS GOV.DECISION_LOG (
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
  sample_json VARCHAR(200000),       -- 5% of ~20k T0 links is ~1,000 ids (DEV-36)
  covered_count DECIMAL(9)
);

CREATE TABLE IF NOT EXISTS GOV.DECISION_COVERS (
  decision_id VARCHAR(40) NOT NULL,
  proposal_id VARCHAR(16) NOT NULL,
  in_sample BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS GOV.POLICY_EVENT (
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

CREATE TABLE IF NOT EXISTS GOV.REPORT_RUN (
  run_id VARCHAR(40) NOT NULL,       -- 'R-' || yyyymmddHHMMSS || '-' || 4 hex
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

CREATE TABLE IF NOT EXISTS GOV.RUN_MEMBERSHIP (
  run_id VARCHAR(40) NOT NULL,
  group_key VARCHAR(48) NOT NULL,
  entity_key VARCHAR(48) NOT NULL,
  membership_kind VARCHAR(16) NOT NULL,  -- MEMBER | JV_ATTRIBUTION
  is_head BOOLEAN NOT NULL,
  group_flags VARCHAR(80),
  DISTRIBUTE BY run_id
);

CREATE TABLE IF NOT EXISTS GOV.RUN_OUTPUT (
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

CREATE TABLE IF NOT EXISTS GOV.RUN_REPORTED (
  run_id VARCHAR(40) NOT NULL,
  reported_group VARCHAR(40) NOT NULL,
  reported_exposure DECIMAL(18,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS GOV.PIPELINE_TIMING (
  job_id VARCHAR(40) NOT NULL,
  stage VARCHAR(40) NOT NULL,
  rows_affected DECIMAL(12),
  seconds DECIMAL(9,3),
  started_at TIMESTAMP NOT NULL
);
