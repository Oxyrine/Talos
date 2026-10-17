-- 50_asof_links_edges.sql: the run's inputs, as of ({business_date}, {known_at}).
-- The replay rule, per key: among events already recorded at known_at whose
-- [valid_from, valid_to) covers business_date, the latest recorded one wins. A later
-- event therefore overrides an earlier one only where their intervals overlap.

TRUNCATE TABLE RESOLVE.W_RECORD_ENTITY_RUN;

INSERT INTO RESOLVE.W_RECORD_ENTITY_RUN (rec_key, entity_key, decision_id, proposal_id)
SELECT rec_key, entity_key, decision_id, proposal_id
FROM (
  SELECT *
  FROM GRAPH.LINK_EVENT
  WHERE recorded_at <= {known_at} AND valid_from <= {business_date} AND {business_date} < valid_to
  QUALIFY ROW_NUMBER() OVER (PARTITION BY link_key ORDER BY recorded_at DESC, event_id DESC) = 1
)
WHERE "ACTION" = 'ASSERT'
QUALIFY ROW_NUMBER() OVER (PARTITION BY rec_key ORDER BY decision_id DESC) = 1;   -- guard: one entity per record

TRUNCATE TABLE RESOLVE.W_EDGE_RUN;

INSERT INTO RESOLVE.W_EDGE_RUN (edge_key, holder_key, held_key, edge_kind, control_type, status, stake_pct, decision_id)
SELECT edge_key, holder_entity_key, held_entity_key, edge_kind, control_type, status, stake_pct, decision_id
FROM (
  SELECT *
  FROM GRAPH.OWNERSHIP_EVENT
  WHERE recorded_at <= {known_at} AND valid_from <= {business_date} AND {business_date} < valid_to
  QUALIFY ROW_NUMBER() OVER (PARTITION BY edge_key ORDER BY recorded_at DESC, event_id DESC) = 1
)
WHERE "ACTION" = 'ASSERT';

-- Exposure-bearing facts of the chosen loads, with the policy CCFs in force.
-- Collateral carries identity only (CCF_COLLATERAL = 0), so pledges are omitted.
TRUNCATE TABLE RESOLVE.W_FACT_RUN;

INSERT INTO RESOLVE.W_FACT_RUN (rec_key, source_system, source_row_id, exposure_component, product,
                                gross_amount, ccf, exposure_amount)
SELECT 'LOS:' || cust_id, 'LOS', loan_id, 'FUNDED', product, outstanding_amt, 1, outstanding_amt
FROM RAW_LOS.LOAN
WHERE load_id = {los_load_id} AND outstanding_amt > 0
UNION ALL
SELECT 'LOS:' || cust_id, 'LOS', loan_id, 'UNDRAWN', product, sanctioned_amt - outstanding_amt,
       CAST({CCF_UNDRAWN} AS DECIMAL(6,4)),
       ROUND((sanctioned_amt - outstanding_amt) * CAST({CCF_UNDRAWN} AS DECIMAL(6,4)), 2)
FROM RAW_LOS.LOAN
WHERE load_id = {los_load_id} AND sanctioned_amt > outstanding_amt
UNION ALL
SELECT 'TSY:' || issuer_ref, 'TSY', holding_id, 'HOLDING', instrument, carrying_value, 1, carrying_value
FROM RAW_TREASURY.HOLDING
WHERE load_id = {tsy_load_id}
UNION ALL
SELECT 'GTE:' || party_ref, 'GTE', guarantee_id, 'GTE_' || kind, kind, amount,
       CASE kind WHEN 'FIN' THEN CAST({CCF_GTE_FIN} AS DECIMAL(6,4)) ELSE CAST({CCF_GTE_PERF} AS DECIMAL(6,4)) END,
       ROUND(amount * CASE kind WHEN 'FIN' THEN CAST({CCF_GTE_FIN} AS DECIMAL(6,4))
                                ELSE CAST({CCF_GTE_PERF} AS DECIMAL(6,4)) END, 2)
FROM RAW_GUARANTEE.GUARANTEE
WHERE load_id = {gte_load_id};

-- Entities of the run: registry entities of the chosen REG load, any linked or edge
-- endpoint, and a pseudo-entity U:<rec_key> for every book record with facts and no link.
TRUNCATE TABLE RESOLVE.W_ENTITY_RUN;

INSERT INTO RESOLVE.W_ENTITY_RUN (entity_key, display_name)
WITH reg AS (
  SELECT 'E:' || cin AS entity_key, entity_name
  FROM RAW_REGISTRY.ENTITY_FILING
  WHERE load_id = {reg_load_id}
  QUALIFY ROW_NUMBER() OVER (PARTITION BY cin ORDER BY loaded_at DESC, filed_on DESC) = 1
),
k AS (
  SELECT entity_key FROM reg
  UNION SELECT entity_key FROM RESOLVE.W_RECORD_ENTITY_RUN
  UNION SELECT holder_key FROM RESOLVE.W_EDGE_RUN
  UNION SELECT held_key FROM RESOLVE.W_EDGE_RUN
  UNION SELECT 'U:' || f.rec_key
        FROM RESOLVE.W_FACT_RUN f
        LEFT JOIN RESOLVE.W_RECORD_ENTITY_RUN l ON l.rec_key = f.rec_key
        WHERE l.rec_key IS NULL
)
SELECT k.entity_key, COALESCE(reg.entity_name, ge.display_name, s.name_raw, k.entity_key)
FROM k
LEFT JOIN reg ON reg.entity_key = k.entity_key
LEFT JOIN GRAPH.ENTITY ge ON ge.entity_key = k.entity_key
LEFT JOIN STAGE.RECORD_STD s ON k.entity_key = 'U:' || s.rec_key;
