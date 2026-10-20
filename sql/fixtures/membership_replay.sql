-- sql/fixtures/membership_replay.sql: tiny hand-built world for the DB tests
-- (tests/test_fixtures_db.py). Loaded as SYS after `talos reset` and the initial policy
-- events. Every entity has one LOS customer FXC-<name> with one fully drawn loan, so its
-- exposure equals the loan amount in rupees. Entity keys are E:FX-<name>.
--
-- Membership cases (all events recorded 2026-10-01, valid from 2026-01-01):
--   DIA   diamond: P->B, P->C majority; B->X 60%; interdependence C->X. X counted once.
--   CYC   rootless 3-cycle A->B->C->A. Head = largest exposure (B), CYCLE_HEADED.
--   SELF  self-owning edge S->S: never admitted, S is its own uncontrolled head.
--   CH    six-level chain CH0->...->CH6: 7 members.
--   MIN   minority edge M1->M2: never merges.
--   PEND  CONTROL_RULING proposal filed, no ruling: UNASSIGNED.
--   REJ   CONTROL_RULING proposal rejected: a terminal decision, so not UNASSIGNED.
--   SUP   CONTROL_RULING re-filed on 5 Sep and ruled on 6 Sep; the older proposal is never
--         decided but is superseded, so not UNASSIGNED after the ruling (UNASSIGNED before).
--   JVS / JVJ / JVN / JVC   joint ventures ruled SINGLE / JOINT / NONE / CONNECTED; the
--         CONNECTED controllers' link is approved only on 2026-10-10.
-- Replay cases:
--   RP    the product spec's worked example: assert from 1 Jan (recorded 5 Jan); retract
--         1-28 Feb (recorded 5 Mar).
--   OV    overlapping edge events: MAJORITY from 1 Jan; MINORITY for June only (recorded later).
--   LATE  link approved 20 Oct, effective 1 Oct.
--   LC    late balance correction: loan 1,000,000 in load -01, 1,250,000 in load -02.

INSERT INTO RAW_REGISTRY.ENTITY_FILING (cin, pan, lei, entity_name, address, city, state_code,
                                        incorporated_on, director_dins, filed_on, load_id, loaded_at)
SELECT 'FX-' || n, NULL, NULL, 'Fixture ' || n || ' Limited', '1, Fixture Road, Mumbai - 400001', 'Mumbai', 'MH',
       '2000-01-01', NULL, '2025-12-31', 'FX-REG-01', '2026-01-01 00:00:00'
FROM (
  SELECT 'DIA_P' AS n FROM DUAL UNION ALL SELECT 'DIA_B' FROM DUAL UNION ALL SELECT 'DIA_C' FROM DUAL UNION ALL SELECT 'DIA_X' FROM DUAL
  UNION ALL SELECT 'CYC_A' FROM DUAL UNION ALL SELECT 'CYC_B' FROM DUAL UNION ALL SELECT 'CYC_C' FROM DUAL
  UNION ALL SELECT 'SELF_S' FROM DUAL
  UNION ALL SELECT 'CH_0' FROM DUAL UNION ALL SELECT 'CH_1' FROM DUAL UNION ALL SELECT 'CH_2' FROM DUAL UNION ALL SELECT 'CH_3' FROM DUAL
  UNION ALL SELECT 'CH_4' FROM DUAL UNION ALL SELECT 'CH_5' FROM DUAL UNION ALL SELECT 'CH_6' FROM DUAL
  UNION ALL SELECT 'MIN_1' FROM DUAL UNION ALL SELECT 'MIN_2' FROM DUAL
  UNION ALL SELECT 'PEND_J' FROM DUAL UNION ALL SELECT 'REJ_J' FROM DUAL UNION ALL SELECT 'SUP_J' FROM DUAL
  UNION ALL SELECT 'JVS_A' FROM DUAL UNION ALL SELECT 'JVS_B' FROM DUAL UNION ALL SELECT 'JVS_J' FROM DUAL
  UNION ALL SELECT 'JVJ_A' FROM DUAL UNION ALL SELECT 'JVJ_B' FROM DUAL UNION ALL SELECT 'JVJ_J' FROM DUAL
  UNION ALL SELECT 'JVN_A' FROM DUAL UNION ALL SELECT 'JVN_B' FROM DUAL UNION ALL SELECT 'JVN_J' FROM DUAL
  UNION ALL SELECT 'JVC_A' FROM DUAL UNION ALL SELECT 'JVC_B' FROM DUAL UNION ALL SELECT 'JVC_J' FROM DUAL
  UNION ALL SELECT 'RP_E' FROM DUAL UNION ALL SELECT 'OV_A' FROM DUAL UNION ALL SELECT 'OV_B' FROM DUAL
  UNION ALL SELECT 'LATE_E' FROM DUAL UNION ALL SELECT 'LC_E' FROM DUAL
);

-- Exposure per entity (rupees). One customer and one fully drawn loan each.
CREATE OR REPLACE TABLE STAGE.FX_AMOUNTS AS
SELECT * FROM (
  SELECT 'DIA_P' AS n, 100 AS amt FROM DUAL UNION ALL SELECT 'DIA_B', 200 FROM DUAL UNION ALL SELECT 'DIA_C', 300 FROM DUAL
  UNION ALL SELECT 'DIA_X', 400 FROM DUAL
  UNION ALL SELECT 'CYC_A', 10 FROM DUAL UNION ALL SELECT 'CYC_B', 30 FROM DUAL UNION ALL SELECT 'CYC_C', 20 FROM DUAL
  UNION ALL SELECT 'SELF_S', 50 FROM DUAL
  UNION ALL SELECT 'CH_0', 1 FROM DUAL UNION ALL SELECT 'CH_1', 1 FROM DUAL UNION ALL SELECT 'CH_2', 1 FROM DUAL
  UNION ALL SELECT 'CH_3', 1 FROM DUAL UNION ALL SELECT 'CH_4', 1 FROM DUAL UNION ALL SELECT 'CH_5', 1 FROM DUAL
  UNION ALL SELECT 'CH_6', 1 FROM DUAL
  UNION ALL SELECT 'MIN_1', 70 FROM DUAL UNION ALL SELECT 'MIN_2', 80 FROM DUAL
  UNION ALL SELECT 'PEND_J', 90 FROM DUAL UNION ALL SELECT 'REJ_J', 91 FROM DUAL UNION ALL SELECT 'SUP_J', 92 FROM DUAL
  UNION ALL SELECT 'JVS_A', 1000 FROM DUAL UNION ALL SELECT 'JVS_B', 2000 FROM DUAL UNION ALL SELECT 'JVS_J', 500 FROM DUAL
  UNION ALL SELECT 'JVJ_A', 1000 FROM DUAL UNION ALL SELECT 'JVJ_B', 2000 FROM DUAL UNION ALL SELECT 'JVJ_J', 500 FROM DUAL
  UNION ALL SELECT 'JVN_A', 1000 FROM DUAL UNION ALL SELECT 'JVN_B', 2000 FROM DUAL UNION ALL SELECT 'JVN_J', 500 FROM DUAL
  UNION ALL SELECT 'JVC_A', 1000 FROM DUAL UNION ALL SELECT 'JVC_B', 2000 FROM DUAL UNION ALL SELECT 'JVC_J', 500 FROM DUAL
  UNION ALL SELECT 'RP_E', 5 FROM DUAL UNION ALL SELECT 'OV_A', 600 FROM DUAL UNION ALL SELECT 'OV_B', 700 FROM DUAL
  UNION ALL SELECT 'LATE_E', 9 FROM DUAL UNION ALL SELECT 'LC_E', 1000000 FROM DUAL
);

INSERT INTO RAW_LOS.CUSTOMER (cust_id, cust_name, pan, cin, address, city, state_code, group_code,
                              director_dins, business_date, load_id, loaded_at)
-- Loan-book group codes (the "reported" side of the board): FXG-DIA on the diamond's parent; FXG-B on a
-- diamond member that is not the head (carried by no Talos group); FXG-SPLIT on two separate Talos groups.
SELECT 'FXC-' || n, 'Fixture ' || n || ' Limited', NULL, 'FX-' || n, NULL, 'Mumbai', 'MH',
       CASE n WHEN 'DIA_P' THEN 'FXG-DIA' WHEN 'DIA_B' THEN 'FXG-B' WHEN 'MIN_1' THEN 'FXG-SPLIT' WHEN 'MIN_2' THEN 'FXG-SPLIT' END,
       NULL,
       '2026-09-30', l.load_id, l.loaded_at
FROM STAGE.FX_AMOUNTS
CROSS JOIN (SELECT 'FX-LOS-20260930-01' AS load_id, CAST('2026-10-02 06:00:00' AS TIMESTAMP) AS loaded_at FROM DUAL
            UNION ALL SELECT 'FX-LOS-20260930-02', CAST('2026-10-06 10:00:00' AS TIMESTAMP) FROM DUAL) l;

INSERT INTO RAW_LOS.LOAN (loan_id, cust_id, product, sanctioned_amt, outstanding_amt, business_date, load_id, loaded_at)
SELECT 'FXL-' || n, 'FXC-' || n, 'TERM_LOAN',
       CASE WHEN n = 'LC_E' AND l.load_id LIKE '%-02' THEN 1250000 ELSE amt END,
       CASE WHEN n = 'LC_E' AND l.load_id LIKE '%-02' THEN 1250000 ELSE amt END,
       '2026-09-30', l.load_id, l.loaded_at
FROM STAGE.FX_AMOUNTS
CROSS JOIN (SELECT 'FX-LOS-20260930-01' AS load_id, CAST('2026-10-02 06:00:00' AS TIMESTAMP) AS loaded_at FROM DUAL
            UNION ALL SELECT 'FX-LOS-20260930-02', CAST('2026-10-06 10:00:00' AS TIMESTAMP) FROM DUAL) l;

-- One inert row in each other book so every load resolves.
INSERT INTO RAW_TREASURY.HOLDING VALUES ('FXH-1', 'FXI-1', 'Fixture Issuer', NULL, NULL, NULL, NULL, NULL, NULL,
  'CP', 0, '2026-09-30', 'FX-TSY-20260930-01', '2026-10-02 06:00:00');
INSERT INTO RAW_GUARANTEE.GUARANTEE VALUES ('FXG-1', 'FXP-1', 'Fixture Party', NULL, NULL, NULL, NULL, NULL, 'FIN', 0,
  NULL, '2026-09-30', 'FX-GTE-20260930-01', '2026-10-02 06:00:00');
INSERT INTO RAW_COLLATERAL.PLEDGE VALUES ('FXP-1', 'FXQ-1', 'Fixture Pledgor', NULL, NULL, NULL, NULL, NULL, 'FD', 0, NULL,
  '2026-09-30', 'FX-COL-20260930-01', '2026-10-02 06:00:00');

-- Every fixture customer is linked to its entity from 1 Jan (recorded 1 Jan), except the
-- replay cases, which carry their own events below.
INSERT INTO GRAPH.LINK_EVENT (event_id, link_key, rec_key, entity_key, "ACTION", evidence_hash, valid_from, valid_to,
                              recorded_at, decision_id, proposal_id)
SELECT 'FXEV-L-' || n, 'LOS:FXC-' || n || '>E:FX-' || n, 'LOS:FXC-' || n, 'E:FX-' || n, 'ASSERT', NULL,
       '2026-01-01', '9999-12-31', '2026-01-01 00:00:00', 'FXD-LINK-' || n, 'FXP-L-' || n
FROM STAGE.FX_AMOUNTS
WHERE n NOT IN ('RP_E', 'LATE_E');

INSERT INTO GRAPH.LINK_EVENT (event_id, link_key, rec_key, entity_key, "ACTION", evidence_hash, valid_from, valid_to,
                              recorded_at, decision_id, proposal_id)
VALUES
  ('FXEV-RP-1', 'LOS:FXC-RP_E>E:FX-RP_E', 'LOS:FXC-RP_E', 'E:FX-RP_E', 'ASSERT', NULL, '2026-01-01', '9999-12-31',
   '2026-01-05 00:00:00', 'FXD-RP-1', 'FXP-RP'),
  ('FXEV-RP-2', 'LOS:FXC-RP_E>E:FX-RP_E', 'LOS:FXC-RP_E', 'E:FX-RP_E', 'RETRACT', NULL, '2026-02-01', '2026-03-01',
   '2026-03-05 00:00:00', 'FXD-RP-2', 'FXP-RP'),
  ('FXEV-LATE', 'LOS:FXC-LATE_E>E:FX-LATE_E', 'LOS:FXC-LATE_E', 'E:FX-LATE_E', 'ASSERT', NULL, '2026-10-01', '9999-12-31',
   '2026-10-20 00:00:00', 'FXD-LATE', 'FXP-LATE');

INSERT INTO GRAPH.OWNERSHIP_EVENT (event_id, edge_key, holder_entity_key, held_entity_key, edge_kind, control_type, status,
                                   stake_pct, "ACTION", evidence_hash, valid_from, valid_to, recorded_at, decision_id, proposal_id)
SELECT 'FXEV-O-' || k, e_kind || ':E:FX-' || h || '>E:FX-' || d, 'E:FX-' || h, 'E:FX-' || d, e_kind, c_type, status,
       stake, 'ASSERT', NULL, valid_from, valid_to, recorded_at, 'FXD-O-' || k, NULL
FROM (
  SELECT '01' AS k, 'DIA_P' AS h, 'DIA_B' AS d, 'CONTROL' AS e_kind, 'MAJORITY' AS c_type, 'CONFIRMED' AS status, 100 AS stake,
         CAST('2026-01-01' AS DATE) AS valid_from, CAST('9999-12-31' AS DATE) AS valid_to, CAST('2026-10-01 00:00:00' AS TIMESTAMP) AS recorded_at FROM DUAL
  UNION ALL SELECT '02', 'DIA_P', 'DIA_C', 'CONTROL', 'MAJORITY', 'CONFIRMED', 100, DATE '2026-01-01', DATE '9999-12-31', TIMESTAMP '2026-10-01 00:00:00' FROM DUAL
  UNION ALL SELECT '03', 'DIA_B', 'DIA_X', 'CONTROL', 'MAJORITY', 'CONFIRMED', 60, DATE '2026-01-01', DATE '9999-12-31', TIMESTAMP '2026-10-01 00:00:00' FROM DUAL
  UNION ALL SELECT '04', 'DIA_C', 'DIA_X', 'INTERDEP', NULL, 'CONFIRMED', 70, DATE '2026-01-01', DATE '9999-12-31', TIMESTAMP '2026-10-01 00:00:00' FROM DUAL
  UNION ALL SELECT '05', 'CYC_A', 'CYC_B', 'CONTROL', 'MAJORITY', 'CONFIRMED', 51, DATE '2026-01-01', DATE '9999-12-31', TIMESTAMP '2026-10-01 00:00:00' FROM DUAL
  UNION ALL SELECT '06', 'CYC_B', 'CYC_C', 'CONTROL', 'MAJORITY', 'CONFIRMED', 51, DATE '2026-01-01', DATE '9999-12-31', TIMESTAMP '2026-10-01 00:00:00' FROM DUAL
  UNION ALL SELECT '07', 'CYC_C', 'CYC_A', 'CONTROL', 'MAJORITY', 'CONFIRMED', 51, DATE '2026-01-01', DATE '9999-12-31', TIMESTAMP '2026-10-01 00:00:00' FROM DUAL
  UNION ALL SELECT '08', 'SELF_S', 'SELF_S', 'CONTROL', 'MAJORITY', 'CONFIRMED', 60, DATE '2026-01-01', DATE '9999-12-31', TIMESTAMP '2026-10-01 00:00:00' FROM DUAL
  UNION ALL SELECT '09', 'CH_0', 'CH_1', 'CONTROL', 'MAJORITY', 'CONFIRMED', 90, DATE '2026-01-01', DATE '9999-12-31', TIMESTAMP '2026-10-01 00:00:00' FROM DUAL
  UNION ALL SELECT '10', 'CH_1', 'CH_2', 'CONTROL', 'MAJORITY', 'CONFIRMED', 90, DATE '2026-01-01', DATE '9999-12-31', TIMESTAMP '2026-10-01 00:00:00' FROM DUAL
  UNION ALL SELECT '11', 'CH_2', 'CH_3', 'CONTROL', 'MAJORITY', 'CONFIRMED', 90, DATE '2026-01-01', DATE '9999-12-31', TIMESTAMP '2026-10-01 00:00:00' FROM DUAL
  UNION ALL SELECT '12', 'CH_3', 'CH_4', 'CONTROL', 'MAJORITY', 'CONFIRMED', 90, DATE '2026-01-01', DATE '9999-12-31', TIMESTAMP '2026-10-01 00:00:00' FROM DUAL
  UNION ALL SELECT '13', 'CH_4', 'CH_5', 'CONTROL', 'MAJORITY', 'CONFIRMED', 90, DATE '2026-01-01', DATE '9999-12-31', TIMESTAMP '2026-10-01 00:00:00' FROM DUAL
  UNION ALL SELECT '14', 'CH_5', 'CH_6', 'CONTROL', 'MAJORITY', 'CONFIRMED', 90, DATE '2026-01-01', DATE '9999-12-31', TIMESTAMP '2026-10-01 00:00:00' FROM DUAL
  UNION ALL SELECT '15', 'MIN_1', 'MIN_2', 'CONTROL', 'MINORITY', 'CONFIRMED', 30, DATE '2026-01-01', DATE '9999-12-31', TIMESTAMP '2026-10-01 00:00:00' FROM DUAL
  UNION ALL SELECT '16', 'JVS_A', 'JVS_J', 'CONTROL', 'MAJORITY', 'CONFIRMED', 50, DATE '2026-01-01', DATE '9999-12-31', TIMESTAMP '2026-10-01 00:00:00' FROM DUAL
  UNION ALL SELECT '17', 'JVS_B', 'JVS_J', 'CONTROL', 'MINORITY', 'CONFIRMED', 50, DATE '2026-01-01', DATE '9999-12-31', TIMESTAMP '2026-10-01 00:00:00' FROM DUAL
  UNION ALL SELECT '18', 'JVJ_A', 'JVJ_J', 'CONTROL', 'JOINT', 'CONFIRMED', 50, DATE '2026-01-01', DATE '9999-12-31', TIMESTAMP '2026-10-01 00:00:00' FROM DUAL
  UNION ALL SELECT '19', 'JVJ_B', 'JVJ_J', 'CONTROL', 'JOINT', 'CONFIRMED', 50, DATE '2026-01-01', DATE '9999-12-31', TIMESTAMP '2026-10-01 00:00:00' FROM DUAL
  UNION ALL SELECT '20', 'JVN_A', 'JVN_J', 'CONTROL', 'UNKNOWN', 'REJECTED', 50, DATE '2026-01-01', DATE '9999-12-31', TIMESTAMP '2026-10-01 00:00:00' FROM DUAL
  UNION ALL SELECT '21', 'JVN_B', 'JVN_J', 'CONTROL', 'UNKNOWN', 'REJECTED', 50, DATE '2026-01-01', DATE '9999-12-31', TIMESTAMP '2026-10-01 00:00:00' FROM DUAL
  UNION ALL SELECT '22', 'JVC_A', 'JVC_J', 'CONTROL', 'JOINT', 'CONFIRMED', 50, DATE '2026-01-01', DATE '9999-12-31', TIMESTAMP '2026-10-01 00:00:00' FROM DUAL
  UNION ALL SELECT '23', 'JVC_B', 'JVC_J', 'CONTROL', 'JOINT', 'CONFIRMED', 50, DATE '2026-01-01', DATE '9999-12-31', TIMESTAMP '2026-10-01 00:00:00' FROM DUAL
  UNION ALL SELECT '24', 'JVC_A', 'JVC_B', 'INTERDEP', NULL, 'CONFIRMED', 60, DATE '2026-01-01', DATE '9999-12-31', TIMESTAMP '2026-10-10 00:00:00' FROM DUAL
  UNION ALL SELECT '25', 'OV_A', 'OV_B', 'CONTROL', 'MAJORITY', 'CONFIRMED', 60, DATE '2026-01-01', DATE '9999-12-31', TIMESTAMP '2026-02-01 00:00:00' FROM DUAL
  UNION ALL SELECT '26', 'OV_A', 'OV_B', 'CONTROL', 'MINORITY', 'CONFIRMED', 30, DATE '2026-06-01', DATE '2026-07-01', TIMESTAMP '2026-07-15 00:00:00' FROM DUAL
);

-- A control ruling that has been filed but not decided: PEND_J is UNASSIGNED.
INSERT INTO GOV.PROPOSAL (proposal_id, kind, subject_key, held_entity_key, tier, tier_reason, evidence_json,
                          evidence_hash, rupee_impact, filed_at)
VALUES ('FXP-PEND', 'CONTROL_RULING', 'JV:E:FX-PEND_J', 'E:FX-PEND_J', 'T3', 'AMBIGUOUS_CONTROL',
        '{{"holders":[]}}', 'fx', 0, '2026-09-01 00:00:00');

-- REJ_J: the ruling proposal was rejected. SUP_J: re-filed with new evidence, the newer one ruled.
INSERT INTO GOV.PROPOSAL (proposal_id, kind, subject_key, held_entity_key, tier, tier_reason, evidence_json,
                          evidence_hash, rupee_impact, filed_at)
SELECT 'FXP-REJ', 'CONTROL_RULING', 'JV:E:FX-REJ_J', 'E:FX-REJ_J', 'T3', 'AMBIGUOUS_CONTROL',
       '{{"holders":[]}}', 'fx', 0, TIMESTAMP '2026-09-01 00:00:00' FROM DUAL
UNION ALL SELECT 'FXP-SUP-OLD', 'CONTROL_RULING', 'JV:E:FX-SUP_J', 'E:FX-SUP_J', 'T3', 'AMBIGUOUS_CONTROL',
       '{{"holders":["old"]}}', 'fx-old', 0, TIMESTAMP '2026-09-01 00:00:00' FROM DUAL
UNION ALL SELECT 'FXP-SUP-NEW', 'CONTROL_RULING', 'JV:E:FX-SUP_J', 'E:FX-SUP_J', 'T3', 'AMBIGUOUS_CONTROL',
       '{{"holders":["new"]}}', 'fx-new', 0, TIMESTAMP '2026-09-05 00:00:00' FROM DUAL;

INSERT INTO GOV.DECISION_LOG (decision_id, decision, proposal_id, ruling, reason, reviewer, reviewer_role, decided_at)
SELECT 'FXD-REJ', 'REJECT', 'FXP-REJ', CAST(NULL AS VARCHAR(10)), 'fixture: rejected', 'fixture', 'APPROVER',
       TIMESTAMP '2026-09-02 00:00:00' FROM DUAL
UNION ALL SELECT 'FXD-SUP', 'RULING', 'FXP-SUP-NEW', 'NONE', 'fixture: no control', 'fixture', 'APPROVER',
       TIMESTAMP '2026-09-06 00:00:00' FROM DUAL;

INSERT INTO GOV.DECISION_COVERS (decision_id, proposal_id, in_sample)
SELECT 'FXD-REJ', 'FXP-REJ', TRUE FROM DUAL
UNION ALL SELECT 'FXD-SUP', 'FXP-SUP-NEW', TRUE FROM DUAL;

DROP TABLE STAGE.FX_AMOUNTS;

-- The seeded policy starts on 2026-04-01; the replay cases run on earlier business dates,
-- so the same values are also put in force for 2025-01-01 .. 2026-04-01.
INSERT INTO GOV.POLICY_EVENT (event_id, policy_key, value_num, value_text, effective_from, effective_to,
                              recorded_at, recorded_by, note)
SELECT SUBSTR(event_id, 1, 40) || '-FX', policy_key, value_num, value_text, '2025-01-01', '2026-04-01',
       '2025-01-01 00:00:00', 'fixture', 'fixture: policy before 2026-04-01'
FROM GOV.POLICY_EVENT
WHERE effective_from = '2026-04-01';
