-- 63_reported_baseline.sql: "what the source systems say", from the same loads and CCFs,
-- raw data only. LOS facts go to the customer's stale group_code (else C:<cust_id>);
-- treasury and guarantee facts go to the LOS customer whose PAN matches exactly (the
-- spreadsheet VLOOKUP; lowest cust_id on ties), else stand alone as SA:<book>:<ref>.

INSERT INTO GOV.RUN_REPORTED (run_id, reported_group, reported_exposure)
WITH cust AS (
  SELECT cust_id, pan, COALESCE(group_code, 'C:' || cust_id) AS code
  FROM RAW_LOS.CUSTOMER
  WHERE load_id = {los_load_id}
),
pan_map AS (
  SELECT UPPER(TRIM(pan)) AS pan_key, code
  FROM cust
  WHERE pan IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (PARTITION BY UPPER(TRIM(pan)) ORDER BY cust_id) = 1
),
other_pan AS (
  SELECT 'TSY' AS source_system, holding_id AS source_row_id, issuer_ref AS book_ref, pan
  FROM RAW_TREASURY.HOLDING WHERE load_id = {tsy_load_id}
  UNION ALL
  SELECT 'GTE', guarantee_id, party_ref, pan
  FROM RAW_GUARANTEE.GUARANTEE WHERE load_id = {gte_load_id}
),
assigned AS (
  SELECT c.code AS reported_group, f.exposure_amount
  FROM RESOLVE.W_FACT_RUN f
  JOIN cust c ON f.rec_key = 'LOS:' || c.cust_id
  WHERE f.source_system = 'LOS'
  UNION ALL
  SELECT COALESCE(pm.code, 'SA:' || o.source_system || ':' || o.book_ref), f.exposure_amount
  FROM RESOLVE.W_FACT_RUN f
  JOIN other_pan o ON o.source_system = f.source_system AND o.source_row_id = f.source_row_id
  LEFT JOIN pan_map pm ON pm.pan_key = UPPER(TRIM(o.pan))
)
SELECT {run_id}, reported_group, SUM(exposure_amount)
FROM assigned
GROUP BY reported_group;
