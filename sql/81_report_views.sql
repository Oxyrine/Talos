-- 81_report_views.sql: everything the web screens and the Exasol MCP server read.
-- TALOS_READER holds SELECT on REPORT only; these views run with their owner's rights.
-- Run-scoped views carry run_id and is_latest. Policy values are those in force for the
-- run's (business_date, known_at), so a replayed or back-dated run shows its own limits.

-- Latest successful, non-replay run per business date.
CREATE OR REPLACE VIEW REPORT.V_LATEST_RUN AS
SELECT run_id, business_date, known_at, code_version, output_hash, row_count, lp_passes, status, finished_at
FROM GOV.REPORT_RUN
WHERE status = 'OK' AND replay_of IS NULL
QUALIFY ROW_NUMBER() OVER (PARTITION BY business_date ORDER BY finished_at DESC, run_id DESC) = 1;

-- The single newest run across business dates: what the queue measures live impact against.
CREATE OR REPLACE VIEW REPORT.V_CURRENT_RUN AS
SELECT run_id, business_date, known_at
FROM GOV.REPORT_RUN
WHERE status = 'OK' AND replay_of IS NULL
QUALIFY ROW_NUMBER() OVER (ORDER BY finished_at DESC, run_id DESC) = 1;

CREATE OR REPLACE VIEW REPORT.V_RUNS AS
SELECT r.run_id, r.business_date, r.known_at, r.code_version, r.output_hash, r.status, r.replay_of,
       r.started_at, r.finished_at, r.row_count, r.lp_passes, r.load_ids_json, r.policy_event_ids_json,
       CASE WHEN l.run_id IS NULL THEN FALSE ELSE TRUE END AS is_latest
FROM GOV.REPORT_RUN r
LEFT JOIN REPORT.V_LATEST_RUN l ON l.run_id = r.run_id;

-- Policy values in force for each run (same rule as orchestrator/policy.py).
CREATE OR REPLACE VIEW REPORT.V_RUN_POLICY AS
SELECT run_id,
       MAX(CASE WHEN policy_key = 'CAPITAL_BASE_INR' THEN value_num END) AS capital_base,
       MAX(CASE WHEN policy_key = 'GROUP_LIMIT_PCT' THEN value_num END) AS group_limit_pct,
       MAX(CASE WHEN policy_key = 'LE_LINE_PCT' THEN value_num END) AS le_line_pct,
       MAX(CASE WHEN policy_key = 'T0_SAMPLE_PCT' THEN value_num END) AS t0_sample_pct,
       MAX(CASE WHEN policy_key = 'T0_SAMPLE_MIN' THEN value_num END) AS t0_sample_min,
       MAX(CASE WHEN policy_key = 'OWN_SAMPLE_PCT' THEN value_num END) AS own_sample_pct,
       MAX(CASE WHEN policy_key = 'OWN_SAMPLE_MIN' THEN value_num END) AS own_sample_min
FROM (
  SELECT r.run_id, p.policy_key, p.value_num
  FROM GOV.REPORT_RUN r
  JOIN GOV.POLICY_EVENT p
    ON p.recorded_at <= r.known_at AND p.effective_from <= r.business_date AND r.business_date < p.effective_to
  QUALIFY ROW_NUMBER() OVER (PARTITION BY r.run_id, p.policy_key ORDER BY p.recorded_at DESC, p.event_id DESC) = 1
)
GROUP BY run_id;

-- Display names: registry name for E: entities, the book record's own name for U: ones.
CREATE OR REPLACE VIEW REPORT.V_ENTITY_NAME AS
SELECT 'E:' || cin AS entity_key, entity_name
FROM RAW_REGISTRY.ENTITY_FILING
QUALIFY ROW_NUMBER() OVER (PARTITION BY cin ORDER BY loaded_at DESC, load_id DESC) = 1
UNION ALL
SELECT 'U:' || rec_key, name_raw
FROM STAGE.RECORD_STD
WHERE side = 'BOOK';

CREATE OR REPLACE VIEW REPORT.V_GROUP_EXPOSURE AS
WITH mem AS (
  SELECT run_id, group_key, COUNT(*) AS member_count, MAX(group_flags) AS group_flags
  FROM GOV.RUN_MEMBERSHIP
  WHERE membership_kind = 'MEMBER'
  GROUP BY run_id, group_key
),
outp AS (
  SELECT run_id, group_key,
         SUM(CASE WHEN membership_kind = 'MEMBER' THEN exposure_amount ELSE 0 END) AS book_exposure,
         SUM(exposure_amount) AS limit_exposure
  FROM GOV.RUN_OUTPUT
  GROUP BY run_id, group_key
),
los_cust AS (
  SELECT cust_id, group_code
  FROM RAW_LOS.CUSTOMER
  QUALIFY ROW_NUMBER() OVER (PARTITION BY cust_id ORDER BY loaded_at DESC, load_id DESC) = 1
),
head_code AS (
  -- the most frequent group_code among the head entity's linked LOS records in the run
  SELECT run_id, group_key, group_code
  FROM (
    SELECT o.run_id, o.group_key, c.group_code, COUNT(*) AS votes
    FROM GOV.RUN_OUTPUT o
    JOIN los_cust c ON o.rec_key = 'LOS:' || c.cust_id
    WHERE o.source_system = 'LOS' AND o.membership_kind = 'MEMBER'
      AND o.entity_key = o.group_key AND o.group_key LIKE 'E:%' AND c.group_code IS NOT NULL
    GROUP BY o.run_id, o.group_key, c.group_code
  )
  QUALIFY ROW_NUMBER() OVER (PARTITION BY run_id, group_key ORDER BY votes DESC, group_code) = 1
),
base AS (
  SELECT m.run_id, m.group_key, m.member_count, m.group_flags,
         COALESCE(o.book_exposure, 0) AS book_exposure,
         COALESCE(o.limit_exposure, 0) AS limit_exposure,
         p.capital_base, p.group_limit_pct, p.le_line_pct,
         CASE WHEN m.group_key LIKE 'U:%' THEN NULL ELSE COALESCE(rr.reported_exposure, 0) END AS reported_exposure,
         hc.group_code AS reported_group
  FROM mem m
  LEFT JOIN outp o ON o.run_id = m.run_id AND o.group_key = m.group_key
  LEFT JOIN REPORT.V_RUN_POLICY p ON p.run_id = m.run_id
  LEFT JOIN head_code hc ON hc.run_id = m.run_id AND hc.group_key = m.group_key
  LEFT JOIN GOV.RUN_REPORTED rr ON rr.run_id = m.run_id AND rr.reported_group = hc.group_code
)
SELECT b.run_id,
       CASE WHEN l.run_id IS NULL THEN FALSE ELSE TRUE END AS is_latest,
       b.group_key,
       COALESCE(n.entity_name, b.group_key) AS group_name,
       b.group_key AS head_entity_key,
       b.member_count,
       b.book_exposure,
       b.limit_exposure,
       b.capital_base,
       CAST(100 * b.limit_exposure / b.capital_base AS DECIMAL(9,4)) AS utilisation_pct,
       CASE WHEN 100 * b.limit_exposure / b.capital_base >= b.le_line_pct THEN TRUE ELSE FALSE END AS is_large,
       CASE WHEN 100 * b.limit_exposure / b.capital_base > b.group_limit_pct THEN TRUE ELSE FALSE END AS is_breach,
       b.group_flags,
       b.reported_exposure,
       b.reported_group,
       b.limit_exposure - b.reported_exposure AS hidden_exposure,
       CAST(b.capital_base * b.group_limit_pct / 100 AS DECIMAL(18,2)) - b.limit_exposure AS headroom
FROM base b
LEFT JOIN REPORT.V_LATEST_RUN l ON l.run_id = b.run_id
LEFT JOIN REPORT.V_ENTITY_NAME n ON n.entity_key = b.group_key;

CREATE OR REPLACE VIEW REPORT.V_ENTITY_EXPOSURE AS
SELECT o.run_id,
       CASE WHEN l.run_id IS NULL THEN FALSE ELSE TRUE END AS is_latest,
       o.entity_key,
       COALESCE(n.entity_name, o.entity_key) AS entity_name,
       o.group_key,
       SUM(o.exposure_amount) AS book_exposure,
       SUM(CASE WHEN o.exposure_component = 'FUNDED' THEN o.exposure_amount ELSE 0 END) AS funded_amt,
       SUM(CASE WHEN o.exposure_component = 'UNDRAWN' THEN o.exposure_amount ELSE 0 END) AS undrawn_amt,
       SUM(CASE WHEN o.exposure_component = 'HOLDING' THEN o.exposure_amount ELSE 0 END) AS holding_amt,
       SUM(CASE WHEN o.exposure_component = 'GTE_FIN' THEN o.exposure_amount ELSE 0 END) AS gte_fin_amt,
       SUM(CASE WHEN o.exposure_component = 'GTE_PERF' THEN o.exposure_amount ELSE 0 END) AS gte_perf_amt,
       MIN(ge.first_published_at) AS published_at
FROM GOV.RUN_OUTPUT o
LEFT JOIN REPORT.V_LATEST_RUN l ON l.run_id = o.run_id
LEFT JOIN REPORT.V_ENTITY_NAME n ON n.entity_key = o.entity_key
LEFT JOIN GRAPH.ENTITY ge ON ge.entity_key = o.entity_key
WHERE o.membership_kind = 'MEMBER'
GROUP BY o.run_id, l.run_id, o.entity_key, n.entity_name, o.group_key;

-- Every figure back to its source row, the proposal that linked it and who decided.
CREATE OR REPLACE VIEW REPORT.V_LINEAGE AS
WITH dlog AS (
  SELECT decision_id, reviewer, reviewer_role, decided_at, decision FROM GOV.DECISION_LOG
)
SELECT o.run_id,
       CASE WHEN l.run_id IS NULL THEN FALSE ELSE TRUE END AS is_latest,
       o.group_key, o.entity_key,
       COALESCE(n.entity_name, o.entity_key) AS entity_name,
       o.membership_kind, o.source_system, o.source_row_id, o.exposure_component, o.rec_key, o.product,
       o.gross_amount, o.ccf, o.exposure_amount,
       o.link_proposal_id, o.link_decision_id,
       d.reviewer, d.reviewer_role, d.decided_at, d.decision,
       p.tier, p.tier_reason
FROM GOV.RUN_OUTPUT o
LEFT JOIN REPORT.V_LATEST_RUN l ON l.run_id = o.run_id
LEFT JOIN REPORT.V_ENTITY_NAME n ON n.entity_key = o.entity_key
LEFT JOIN dlog d ON d.decision_id = o.link_decision_id
LEFT JOIN GOV.PROPOSAL p ON p.proposal_id = o.link_proposal_id;

CREATE OR REPLACE VIEW REPORT.V_BREACHES AS
SELECT run_id, is_latest, group_key, group_name, limit_exposure, utilisation_pct, is_breach, is_large,
       CASE WHEN is_breach THEN 'BREACH' ELSE 'LARGE_EXPOSURE' END AS crossing_type,
       reported_exposure, hidden_exposure, headroom, group_flags
FROM REPORT.V_GROUP_EXPOSURE
WHERE is_breach OR is_large;

-- OLAP cube: by group, group x entity, group x book, group x product, and book overall.
CREATE OR REPLACE VIEW REPORT.V_EXPOSURE_CUBE AS
SELECT o.run_id, o.group_key, o.entity_key, o.source_system, o.product,
       SUM(CASE WHEN o.membership_kind = 'MEMBER' THEN o.exposure_amount ELSE 0 END) AS book_exposure,
       SUM(o.exposure_amount) AS limit_exposure,
       GROUPING(o.group_key) AS g_group,
       GROUPING(o.entity_key) AS g_entity,
       GROUPING(o.source_system) AS g_source,
       GROUPING(o.product) AS g_product,
       CASE
         WHEN GROUPING(o.group_key) = 1 THEN 'SOURCE'
         WHEN GROUPING(o.entity_key) = 0 THEN 'GROUP_ENTITY'
         WHEN GROUPING(o.source_system) = 0 THEN 'GROUP_SOURCE'
         WHEN GROUPING(o.product) = 0 THEN 'GROUP_PRODUCT'
         ELSE 'GROUP'
       END AS cube_level
FROM GOV.RUN_OUTPUT o
GROUP BY GROUPING SETS ((o.run_id, o.group_key), (o.run_id, o.group_key, o.entity_key),
                        (o.run_id, o.group_key, o.source_system), (o.run_id, o.group_key, o.product),
                        (o.run_id, o.source_system));

-- Ownership paths below each head of the newest run, over the confirmed control edges in
-- force today. Display only: membership never depends on it. closes_cycle marks the
-- edge that closes a cycle.
CREATE OR REPLACE VIEW REPORT.V_OWNERSHIP_PATH AS
SELECT CONNECT_BY_ROOT holder_key AS root_key,
       held_key AS entity_key,
       held_name,
       LEVEL AS depth,
       SYS_CONNECT_BY_PATH(held_name, ' > ') AS ownership_path,
       CONNECT_BY_ISCYCLE AS closes_cycle,
       control_type,
       stake_pct
FROM (
  SELECT e.holder_key, e.held_key, e.held_name, e.control_type, e.stake_pct,
         CASE WHEN h.group_key IS NULL THEN 0 ELSE 1 END AS from_head
  FROM GRAPH.V_CONTROL_EDGE e
  LEFT JOIN (
    SELECT DISTINCT group_key
    FROM GOV.RUN_MEMBERSHIP
    WHERE run_id IN (SELECT run_id FROM REPORT.V_CURRENT_RUN) AND membership_kind = 'MEMBER'
  ) h ON h.group_key = e.holder_key
)
CONNECT BY NOCYCLE PRIOR held_key = holder_key
START WITH from_head = 1;

-- Open proposals with live impact against the newest run. Ranked by the UI on
-- crosses_limit DESC, crosses_le DESC, delta_amt DESC.
CREATE OR REPLACE VIEW REPORT.V_PROPOSAL_QUEUE AS
WITH lr AS (
  SELECT c.run_id, p.capital_base, p.group_limit_pct, p.le_line_pct,
         p.t0_sample_pct, p.t0_sample_min, p.own_sample_pct, p.own_sample_min
  FROM REPORT.V_CURRENT_RUN c
  JOIN REPORT.V_RUN_POLICY p ON p.run_id = c.run_id
),
term AS (
  SELECT DISTINCT c.proposal_id
  FROM GOV.DECISION_COVERS c
  JOIN GOV.DECISION_LOG d ON d.decision_id = c.decision_id
  WHERE d.decision IN ('APPROVE', 'REJECT', 'BATCH_APPROVE', 'RULING')
),
open_p AS (
  SELECT p.*
  FROM GOV.PROPOSAL p
  LEFT JOIN term t ON t.proposal_id = p.proposal_id
  WHERE t.proposal_id IS NULL
),
failed AS (
  SELECT DISTINCT batch_id FROM GOV.DECISION_LOG WHERE decision = 'BATCH_FAILED'
),
batches AS (
  SELECT batch_id, COUNT(*) AS total FROM open_p WHERE batch_id IS NOT NULL GROUP BY batch_id
),
gm AS (
  SELECT m.entity_key, m.group_key
  FROM GOV.RUN_MEMBERSHIP m JOIN lr ON lr.run_id = m.run_id
  WHERE m.membership_kind = 'MEMBER'
),
gx AS (
  SELECT o.group_key, SUM(o.exposure_amount) AS amt
  FROM GOV.RUN_OUTPUT o JOIN lr ON lr.run_id = o.run_id
  GROUP BY o.group_key
),
rx AS (
  SELECT o.rec_key, MIN(o.group_key) AS group_key, SUM(o.exposure_amount) AS amt
  FROM GOV.RUN_OUTPUT o JOIN lr ON lr.run_id = o.run_id
  WHERE o.membership_kind = 'MEMBER'
  GROUP BY o.rec_key
),
imp AS (
  SELECT q.proposal_id,
         CASE WHEN q.kind = 'RECORD_LINK' THEN gt.group_key ELSE g1.group_key END AS target_group,
         COALESCE(CASE WHEN q.kind = 'RECORD_LINK' THEN xt.amt ELSE x1.amt END, 0) AS before_amt,
         CASE
           WHEN q.kind = 'RECORD_LINK' THEN
             CASE WHEN rx.group_key IS NULL OR rx.group_key = gt.group_key THEN 0 ELSE COALESCE(rx.amt, 0) END
           WHEN q.kind = 'CONTROL_RULING' THEN 0
           ELSE CASE WHEN g1.group_key IS NULL OR g2.group_key IS NULL OR g1.group_key = g2.group_key THEN 0
                     ELSE COALESCE(x2.amt, 0) END
         END AS delta_amt,
         CASE WHEN q.kind = 'CONTROL_RULING' THEN COALESCE(x2.amt, 0) END AS jv_amt
  FROM open_p q
  LEFT JOIN gm gt ON gt.entity_key = q.entity_key
  LEFT JOIN gx xt ON xt.group_key = gt.group_key
  LEFT JOIN rx ON rx.rec_key = q.rec_key
  LEFT JOIN gm g1 ON g1.entity_key = COALESCE(q.holder_entity_key, q.held_entity_key)
  LEFT JOIN gx x1 ON x1.group_key = g1.group_key
  LEFT JOIN gm g2 ON g2.entity_key = q.held_entity_key
  LEFT JOIN gx x2 ON x2.group_key = g2.group_key
)
SELECT q.proposal_id, q.kind, q.subject_key, q.pair_key, q.rec_key, q.entity_key,
       q.holder_entity_key, q.held_entity_key, q.tier, q.tier_reason, q.warning, q.evidence_json,
       q.rupee_impact, q.batch_id,
       CASE WHEN q.batch_id IS NULL THEN NULL
            WHEN q.batch_id LIKE 'B-OWN-%' THEN 'OWNERSHIP' ELSE 'RECORD_LINK' END AS batch_kind,
       CASE WHEN q.batch_id IS NULL OR f.batch_id IS NOT NULL THEN NULL ELSE b.total END AS batch_total_count,
       CASE WHEN q.batch_id IS NULL OR f.batch_id IS NOT NULL THEN NULL
            WHEN q.batch_id LIKE 'B-OWN-%'
              THEN LEAST(b.total, GREATEST(lr.own_sample_min, CEIL(lr.own_sample_pct * b.total / 100)))
            ELSE LEAST(b.total, GREATEST(lr.t0_sample_min, CEIL(lr.t0_sample_pct * b.total / 100)))
       END AS batch_sample_count,
       CASE WHEN f.batch_id IS NULL THEN FALSE ELSE TRUE END AS batch_failed,
       CAST(100 * i.before_amt / lr.capital_base AS DECIMAL(9,4)) AS group_before_pct,
       CAST(100 * (i.before_amt + i.delta_amt) / lr.capital_base AS DECIMAL(9,4)) AS group_after_pct,
       CASE WHEN 100 * i.before_amt / lr.capital_base < lr.le_line_pct
             AND 100 * (i.before_amt + i.delta_amt) / lr.capital_base >= lr.le_line_pct THEN TRUE ELSE FALSE END AS crosses_le,
       CASE WHEN 100 * i.before_amt / lr.capital_base <= lr.group_limit_pct
             AND 100 * (i.before_amt + i.delta_amt) / lr.capital_base > lr.group_limit_pct THEN TRUE ELSE FALSE END AS crosses_limit,
       i.before_amt AS group_before_amt,
       i.before_amt + i.delta_amt AS group_after_amt,
       COALESCE(i.jv_amt, i.delta_amt) AS delta_amt,
       i.target_group AS group_key,
       COALESCE(n.entity_name, i.target_group) AS group_name,
       q.filed_at
FROM open_p q
CROSS JOIN lr
JOIN imp i ON i.proposal_id = q.proposal_id
LEFT JOIN batches b ON b.batch_id = q.batch_id
LEFT JOIN failed f ON f.batch_id = q.batch_id
LEFT JOIN REPORT.V_ENTITY_NAME n ON n.entity_key = i.target_group;

CREATE OR REPLACE VIEW REPORT.V_DECISIONS AS
SELECT decision_id, decision, proposal_id, batch_id, ruling, reason, reviewer, reviewer_role,
       decided_at, covered_count, batch_seed
FROM GOV.DECISION_LOG;

-- Decision log joined to what each decision was about (screen 4 and the grants test).
CREATE OR REPLACE VIEW REPORT.V_DECISION_AUDIT_LOG AS
SELECT d.decision_id, d.decision, d.proposal_id, d.batch_id, d.ruling, d.reason, d.reviewer,
       d.reviewer_role, d.decided_at, d.covered_count, d.batch_seed, d.sample_json,
       p.kind, p.subject_key, p.tier, p.tier_reason, p.rupee_impact
FROM GOV.DECISION_LOG d
LEFT JOIN GOV.PROPOSAL p ON p.proposal_id = d.proposal_id;

-- Group figure change between consecutive runs of the same business date (the copilot
-- chains these to explain a change over any span).
CREATE OR REPLACE VIEW REPORT.V_GROUP_CHANGES AS
WITH runs AS (
  SELECT run_id, business_date,
         LAG(run_id) OVER (PARTITION BY business_date ORDER BY finished_at, run_id) AS prev_run_id
  FROM GOV.REPORT_RUN
  WHERE status = 'OK' AND replay_of IS NULL
),
gx AS (
  SELECT run_id, group_key, SUM(exposure_amount) AS amt
  FROM GOV.RUN_OUTPUT
  GROUP BY run_id, group_key
),
pairs AS (
  SELECT r.prev_run_id AS run_id_a, r.run_id AS run_id_b, b.group_key, a.amt AS exposure_a, b.amt AS exposure_b
  FROM runs r
  JOIN gx b ON b.run_id = r.run_id
  LEFT JOIN gx a ON a.run_id = r.prev_run_id AND a.group_key = b.group_key
  WHERE r.prev_run_id IS NOT NULL
  UNION ALL
  SELECT r.prev_run_id, r.run_id, a.group_key, a.amt, CAST(NULL AS DECIMAL(18,2))
  FROM runs r
  JOIN gx a ON a.run_id = r.prev_run_id
  LEFT JOIN gx b ON b.run_id = r.run_id AND b.group_key = a.group_key
  WHERE b.group_key IS NULL
)
SELECT p.run_id_a, p.run_id_b, p.group_key, COALESCE(n.entity_name, p.group_key) AS group_name,
       COALESCE(p.exposure_a, 0) AS exposure_a, COALESCE(p.exposure_b, 0) AS exposure_b,
       COALESCE(p.exposure_b, 0) - COALESCE(p.exposure_a, 0) AS delta_amt,
       CASE WHEN COALESCE(p.exposure_a, 0) = 0 THEN NULL
            ELSE CAST(100 * (COALESCE(p.exposure_b, 0) - p.exposure_a) / p.exposure_a AS DECIMAL(9,2)) END AS delta_pct
FROM pairs p
LEFT JOIN REPORT.V_ENTITY_NAME n ON n.entity_key = p.group_key
WHERE COALESCE(p.exposure_b, 0) <> COALESCE(p.exposure_a, 0);

-- ---------------------------------------------------------------- diagnostics (/pipeline)

CREATE OR REPLACE VIEW REPORT.V_PIPELINE_TIMING AS
SELECT t.job_id, t.stage, t.rows_affected, t.seconds, t.started_at
FROM GOV.PIPELINE_TIMING t
JOIN (
  SELECT job_id FROM GOV.PIPELINE_TIMING
  QUALIFY ROW_NUMBER() OVER (ORDER BY started_at DESC, job_id DESC) = 1
) j ON j.job_id = t.job_id;

CREATE OR REPLACE VIEW REPORT.V_CANDIDATE_PATHS AS
SELECT 'EXACT' AS via_path, COUNT(*) AS candidate_count, FALSE AS is_dropped_block
FROM RESOLVE.CANDIDATE_PAIR WHERE via LIKE 'EXACT%'
UNION ALL
SELECT 'P1', COUNT(*), FALSE FROM RESOLVE.CANDIDATE_PAIR WHERE via NOT LIKE 'EXACT%' AND INSTR(via, 'P1') > 0
UNION ALL
SELECT 'P2', COUNT(*), FALSE FROM RESOLVE.CANDIDATE_PAIR WHERE via NOT LIKE 'EXACT%' AND INSTR(via, 'P2') > 0
UNION ALL
SELECT 'P3', COUNT(*), FALSE FROM RESOLVE.CANDIDATE_PAIR WHERE via NOT LIKE 'EXACT%' AND INSTR(via, 'P3') > 0
UNION ALL
SELECT pass_name, COUNT(*), TRUE FROM STAGE.BLOCK_DROPPED GROUP BY pass_name;

CREATE OR REPLACE VIEW REPORT.V_TIER_COUNTS AS
SELECT tier, COUNT(*) AS count
FROM RESOLVE.V_PAIR_TIER_FINAL
GROUP BY tier;

CREATE OR REPLACE VIEW REPORT.V_PIPELINE_SUMMARY AS
WITH s AS (
  SELECT SUM(CASE WHEN side = 'BOOK' THEN 1 ELSE 0 END) AS book_n,
         SUM(CASE WHEN side = 'REG' THEN 1 ELSE 0 END) AS reg_n
  FROM STAGE.RECORD_STD
),
c AS (SELECT COUNT(*) AS cand_n FROM RESOLVE.CANDIDATE_PAIR),
t AS (
  SELECT SUM(CASE WHEN tier IN ('T0', 'T1') THEN 1 ELSE 0 END) AS settled,
         SUM(CASE WHEN tier IN ('T0', 'T1', 'T2', 'T3') THEN 1 ELSE 0 END) AS tiered,
         SUM(CASE WHEN base_tier = 'T2' THEN 1 ELSE 0 END) AS t2_n
  FROM RESOLVE.V_PAIR_TIER_FINAL
),
v AS (
  SELECT COUNT(DISTINCT pair_key) AS judged FROM RESOLVE.LLM_VERDICT WHERE model <> 'stub'
)
SELECT s.book_n AS total_book_records,
       s.reg_n AS total_reg_entities,
       c.cand_n AS total_candidates,
       CAST(CASE WHEN t.tiered = 0 THEN NULL ELSE 100.0 * t.settled / t.tiered END AS DECIMAL(7,3)) AS settled_in_sql_pct,
       CAST(CASE WHEN t.tiered = 0 THEN NULL ELSE 100.0 * LEAST(v.judged, t.t2_n) / t.tiered END AS DECIMAL(7,3)) AS sent_to_model_pct,
       CAST(CASE WHEN s.book_n * s.reg_n = 0 THEN NULL ELSE 1 - CAST(c.cand_n AS DOUBLE) / (s.book_n * s.reg_n) END AS DECIMAL(9,6)) AS reduction_ratio,
       t.t2_n AS grey_band_pairs
FROM s CROSS JOIN c CROSS JOIN t CROSS JOIN v;

-- Data-quality findings that are not proposals: self-owning registry edges.
CREATE OR REPLACE VIEW REPORT.V_DATA_QUALITY AS
SELECT 'SELF_OWNING' AS issue, 'E:' || held_cin AS subject_key,
       'Registry lists the entity as holding ' || CAST(stake_pct AS VARCHAR(12)) || '% of itself' AS detail,
       load_id
FROM RAW_REGISTRY.OWNERSHIP_EDGE
WHERE holder_cin = held_cin;
