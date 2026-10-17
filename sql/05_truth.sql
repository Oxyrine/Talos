-- 05_truth.sql: ground truth written by the generator. The pipeline cannot read it;
-- only TALOS_LOADER (writes) and TALOS_EVAL (reads) hold privileges on TRUTH.

CREATE TABLE IF NOT EXISTS TRUTH.GT_ENTITY (
  entity_key VARCHAR(48),
  group_no DECIMAL(5),
  role VARCHAR(12),                  -- HEAD | SUB | JV | DECOY | STANDALONE
  canonical_name VARCHAR(200)
);

CREATE TABLE IF NOT EXISTS TRUTH.GT_RECORD_ENTITY (
  rec_key VARCHAR(40),
  entity_key VARCHAR(48),
  noise_families VARCHAR(80)
);

CREATE TABLE IF NOT EXISTS TRUTH.GT_GROUP (
  group_no DECIMAL(5),
  head_entity_key VARCHAR(48),
  los_group_code VARCHAR(20),
  is_hidden_breach BOOLEAN,
  is_hero BOOLEAN
);

CREATE TABLE IF NOT EXISTS TRUTH.GT_EDGE (
  holder_entity_key VARCHAR(48),
  held_entity_key VARCHAR(48),
  edge_kind VARCHAR(10),
  control_type VARCHAR(10),
  admitted BOOLEAN
);

CREATE TABLE IF NOT EXISTS TRUTH.GT_JV_RULING (
  held_entity_key VARCHAR(48),
  ruling VARCHAR(10),
  controller_entity_key VARCHAR(48)
);

CREATE TABLE IF NOT EXISTS TRUTH.GT_PLANT (
  plant_id VARCHAR(20),
  kind VARCHAR(24),
  subject_key VARCHAR(100),
  expected VARCHAR(200)
);
