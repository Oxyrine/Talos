-- 71_propose_edges.sql: ownership, control-ruling and interdependence proposals.
-- Registry edges come from the latest RAW_REGISTRY.OWNERSHIP_EDGE load known at {known_at}.
-- Per held entity H, an incoming edge qualifies when stake_pct > MAJORITY_MIN_PCT or it
-- carries control_flag (self-owning edges never qualify; see REPORT.V_DATA_QUALITY):
--   exactly one qualifying holder with stake > MAJORITY_MIN_PCT  -> OWNERSHIP (MAJORITY)
--   two or more, or one at or below the line on control_flag    -> one CONTROL_RULING for H
--   neither                                                     -> not proposed (minority)
-- Corroborated ownership (DEV-12): holder and held map to the same LOS group_code through
-- their PAN or CIN. Those proposals share the sampled batch B-OWN-<hash>; the rest are
-- individual cards. rupee_impact = the held side's group exposure in the baseline run when
-- it sits in a different group from the holder.

INSERT INTO GOV.PROPOSAL (proposal_id, kind, subject_key, pair_key, rec_key, entity_key,
                          holder_entity_key, held_entity_key, tier, tier_reason, warning,
                          evidence_json, evidence_hash, rupee_impact, batch_id, filed_at,
                          filed_by_run, pipeline_version)
WITH reg_load AS (
  SELECT load_id
  FROM (SELECT DISTINCT load_id, loaded_at FROM RAW_REGISTRY.OWNERSHIP_EDGE WHERE loaded_at <= {known_at})
  QUALIFY ROW_NUMBER() OVER (ORDER BY loaded_at DESC, load_id DESC) = 1
),
los_load AS (
  SELECT load_id
  FROM (SELECT DISTINCT load_id, loaded_at FROM RAW_LOS.CUSTOMER
        WHERE business_date = {business_date} AND loaded_at <= {known_at})
  QUALIFY ROW_NUMBER() OVER (ORDER BY loaded_at DESC, load_id DESC) = 1
),
oe AS (
  SELECT e.* FROM RAW_REGISTRY.OWNERSHIP_EDGE e JOIN reg_load l ON l.load_id = e.load_id
),
fil AS (
  SELECT cin, pan, entity_name
  FROM RAW_REGISTRY.ENTITY_FILING
  WHERE loaded_at <= {known_at}
  QUALIFY ROW_NUMBER() OVER (PARTITION BY cin ORDER BY loaded_at DESC, load_id DESC) = 1
),
cust AS (
  SELECT c.cust_id, UPPER(TRIM(c.pan)) AS pan_key, UPPER(TRIM(c.cin)) AS cin_key, c.group_code
  FROM RAW_LOS.CUSTOMER c JOIN los_load l ON l.load_id = c.load_id
  WHERE c.group_code IS NOT NULL
),
code_votes AS (
  SELECT f.cin, c.group_code FROM fil f JOIN cust c ON c.pan_key = UPPER(TRIM(f.pan))
  UNION ALL
  SELECT f.cin, c.group_code FROM fil f JOIN cust c ON c.cin_key = f.cin
),
ecode AS (
  SELECT cin, group_code
  FROM (SELECT cin, group_code, COUNT(*) AS votes FROM code_votes GROUP BY cin, group_code)
  QUALIFY ROW_NUMBER() OVER (PARTITION BY cin ORDER BY votes DESC, group_code) = 1
),
q AS (
  SELECT oe.*
  FROM oe
  WHERE oe.holder_cin <> oe.held_cin
    AND (oe.stake_pct > CAST({MAJORITY_MIN_PCT} AS DECIMAL(7,4)) OR oe.control_flag = TRUE)
),
qn AS (
  SELECT q.*, COUNT(*) OVER (PARTITION BY held_cin) AS n_holders FROM q
),
own AS (
  SELECT qn.holder_cin, qn.held_cin, qn.stake_pct, qn.control_flag, qn.effective_from, qn.filed_on, qn.load_id,
         ch.group_code AS holder_code, cd.group_code AS held_code,
         CASE WHEN ch.group_code IS NOT NULL AND ch.group_code = cd.group_code THEN 1 ELSE 0 END AS corroborated,
         fh.entity_name AS holder_name, fd.entity_name AS held_name
  FROM qn
  LEFT JOIN ecode ch ON ch.cin = qn.holder_cin
  LEFT JOIN ecode cd ON cd.cin = qn.held_cin
  LEFT JOIN fil fh ON fh.cin = qn.holder_cin
  LEFT JOIN fil fd ON fd.cin = qn.held_cin
  WHERE qn.n_holders = 1 AND qn.stake_pct > CAST({MAJORITY_MIN_PCT} AS DECIMAL(7,4))
),
ev AS (
  SELECT own.*,
         'CONTROL:E:' || holder_cin || '>E:' || held_cin AS subject_key,
         '{{"kind":"OWNERSHIP","holder_entity_key":"E:' || REPLACE(REPLACE(REGEXP_REPLACE(COALESCE(holder_cin, ''), '[\x00-\x1f]', ' '), '\', '\\'), '"', '\"') || '","held_entity_key":"E:' || REPLACE(REPLACE(REGEXP_REPLACE(COALESCE(held_cin, ''), '[\x00-\x1f]', ' '), '\', '\\'), '"', '\"')
         || '","holder_name":"' || REPLACE(REPLACE(REGEXP_REPLACE(COALESCE(holder_name, ''), '[\x00-\x1f]', ' '), '\', '\\'), '"', '\"')
         || '","held_name":"' || REPLACE(REPLACE(REGEXP_REPLACE(COALESCE(held_name, ''), '[\x00-\x1f]', ' '), '\', '\\'), '"', '\"')
         || '","stake_pct":' || CAST(stake_pct AS VARCHAR(12))
         || ',"control_flag":' || CASE WHEN control_flag THEN 'true' ELSE 'false' END
         || ',"control_type":"MAJORITY","effective_from":"' || TO_CHAR(effective_from, 'YYYY-MM-DD')
         || '","filed_on":"' || TO_CHAR(filed_on, 'YYYY-MM-DD') || '","registry_load_id":"' || REPLACE(REPLACE(REGEXP_REPLACE(COALESCE(load_id, ''), '[\x00-\x1f]', ' '), '\', '\\'), '"', '\"')
         || '","holder_group_code":"' || REPLACE(REPLACE(REGEXP_REPLACE(COALESCE(holder_code, ''), '[\x00-\x1f]', ' '), '\', '\\'), '"', '\"') || '","held_group_code":"' || REPLACE(REPLACE(REGEXP_REPLACE(COALESCE(held_code, ''), '[\x00-\x1f]', ' '), '\', '\\'), '"', '\"')
         || '","corroborated":' || CASE WHEN corroborated = 1 THEN 'true' ELSE 'false' END || '}}' AS evidence_json
  FROM own
),
p AS (
  SELECT ev.*, HASH_SHA256(evidence_json) AS evidence_hash,
         'P-' || SUBSTR(HASH_SHA256('OWNERSHIP' || subject_key || HASH_SHA256(evidence_json)), 1, 12) AS proposal_id
  FROM ev
),
newp AS (
  SELECT p.*
  FROM p
  WHERE NOT EXISTS (SELECT 1 FROM GOV.PROPOSAL x WHERE x.proposal_id = p.proposal_id)
    AND NOT EXISTS (SELECT 1 FROM GRAPH.V_OWNERSHIP_CURRENT c
                    WHERE c.edge_key = p.subject_key
                      AND ((c."ACTION" = 'ASSERT' AND c.status = 'CONFIRMED')
                           OR (c.status = 'REJECTED' AND c.evidence_hash = p.evidence_hash)))
),
batch AS (
  SELECT 'B-OWN-' || SUBSTR(HASH_SHA256(GROUP_CONCAT(proposal_id ORDER BY proposal_id SEPARATOR ',')), 1, 10) AS batch_id
  FROM newp
  WHERE corroborated = 1
),
grp AS (
  SELECT entity_key, group_key FROM GOV.RUN_MEMBERSHIP
  WHERE run_id = {baseline_run} AND membership_kind = 'MEMBER'
),
gexp AS (
  SELECT group_key, SUM(exposure_amount) AS amt FROM GOV.RUN_OUTPUT
  WHERE run_id = {baseline_run} GROUP BY group_key
)
SELECT n.proposal_id, 'OWNERSHIP', n.subject_key, CAST(NULL AS VARCHAR(16)), CAST(NULL AS VARCHAR(40)),
       CAST(NULL AS VARCHAR(48)), 'E:' || n.holder_cin, 'E:' || n.held_cin,
       CASE WHEN n.corroborated = 1 THEN 'T0' ELSE 'T1' END,
       CASE WHEN n.corroborated = 1 THEN 'CORROBORATED_OWNERSHIP' ELSE 'REGISTRY_ONLY_OWNERSHIP' END,
       CASE WHEN n.corroborated = 1 THEN CAST(NULL AS VARCHAR(200))
            ELSE 'Registry edge not reflected in the LOS group map' END,
       n.evidence_json, n.evidence_hash,
       CASE WHEN gh.group_key IS NULL OR gd.group_key IS NULL OR gh.group_key = gd.group_key THEN 0
            ELSE COALESCE(gx.amt, 0) END,
       CASE WHEN n.corroborated = 1 THEN b.batch_id END,
       {filed_at}, {baseline_run}, 'talos-sql-1'
FROM newp n
CROSS JOIN batch b
LEFT JOIN grp gh ON gh.entity_key = 'E:' || n.holder_cin
LEFT JOIN grp gd ON gd.entity_key = 'E:' || n.held_cin
LEFT JOIN gexp gx ON gx.group_key = gd.group_key;

-- CONTROL_RULING: ambiguous control is marked in one proposal before any edge is admitted.
INSERT INTO GOV.PROPOSAL (proposal_id, kind, subject_key, pair_key, rec_key, entity_key,
                          holder_entity_key, held_entity_key, tier, tier_reason, warning,
                          evidence_json, evidence_hash, rupee_impact, batch_id, filed_at,
                          filed_by_run, pipeline_version)
WITH reg_load AS (
  SELECT load_id
  FROM (SELECT DISTINCT load_id, loaded_at FROM RAW_REGISTRY.OWNERSHIP_EDGE WHERE loaded_at <= {known_at})
  QUALIFY ROW_NUMBER() OVER (ORDER BY loaded_at DESC, load_id DESC) = 1
),
fil AS (
  SELECT cin, entity_name
  FROM RAW_REGISTRY.ENTITY_FILING
  WHERE loaded_at <= {known_at}
  QUALIFY ROW_NUMBER() OVER (PARTITION BY cin ORDER BY loaded_at DESC, load_id DESC) = 1
),
q AS (
  SELECT e.*
  FROM RAW_REGISTRY.OWNERSHIP_EDGE e JOIN reg_load l ON l.load_id = e.load_id
  WHERE e.holder_cin <> e.held_cin
    AND (e.stake_pct > CAST({MAJORITY_MIN_PCT} AS DECIMAL(7,4)) OR e.control_flag = TRUE)
),
amb AS (
  SELECT held_cin,
         COUNT(*) AS n_holders,
         MAX(stake_pct) AS max_stake,
         MAX(effective_from) AS effective_from,
         '["' || GROUP_CONCAT('E:' || REPLACE(REPLACE(REGEXP_REPLACE(COALESCE(holder_cin, ''), '[\x00-\x1f]', ' '), '\', '\\'), '"', '\"') ORDER BY holder_cin SEPARATOR '","') || '"]' AS holders_json,
         '{{' || GROUP_CONCAT('"E:' || REPLACE(REPLACE(REGEXP_REPLACE(COALESCE(holder_cin, ''), '[\x00-\x1f]', ' '), '\', '\\'), '"', '\"') || '":' || CAST(stake_pct AS VARCHAR(12))
                              ORDER BY holder_cin SEPARATOR ',') || '}}' AS stakes_json
  FROM q
  GROUP BY held_cin
  HAVING COUNT(*) >= 2 OR MAX(stake_pct) <= CAST({MAJORITY_MIN_PCT} AS DECIMAL(7,4))
),
ev AS (
  SELECT amb.*, 'JV:E:' || amb.held_cin AS subject_key,
         '{{"kind":"CONTROL_RULING","held_entity_key":"E:' || REPLACE(REPLACE(REGEXP_REPLACE(COALESCE(amb.held_cin, ''), '[\x00-\x1f]', ' '), '\', '\\'), '"', '\"')
         || '","held_name":"' || REPLACE(REPLACE(REGEXP_REPLACE(COALESCE(f.entity_name, ''), '[\x00-\x1f]', ' '), '\', '\\'), '"', '\"')
         || '","holders":' || amb.holders_json || ',"stakes":' || amb.stakes_json
         || ',"effective_from":"' || TO_CHAR(amb.effective_from, 'YYYY-MM-DD') || '"}}' AS evidence_json
  FROM amb
  LEFT JOIN fil f ON f.cin = amb.held_cin
),
p AS (
  SELECT ev.*, HASH_SHA256(evidence_json) AS evidence_hash,
         'P-' || SUBSTR(HASH_SHA256('CONTROL_RULING' || subject_key || HASH_SHA256(evidence_json)), 1, 12) AS proposal_id
  FROM ev
),
grp AS (
  SELECT entity_key, group_key FROM GOV.RUN_MEMBERSHIP
  WHERE run_id = {baseline_run} AND membership_kind = 'MEMBER'
),
gexp AS (
  SELECT group_key, SUM(exposure_amount) AS amt FROM GOV.RUN_OUTPUT
  WHERE run_id = {baseline_run} GROUP BY group_key
)
SELECT p.proposal_id, 'CONTROL_RULING', p.subject_key, CAST(NULL AS VARCHAR(16)), CAST(NULL AS VARCHAR(40)),
       CAST(NULL AS VARCHAR(48)), CAST(NULL AS VARCHAR(48)), 'E:' || p.held_cin,
       'T3', 'AMBIGUOUS_CONTROL',
       'Ambiguous control: ' || CAST(p.n_holders AS VARCHAR(4)) || ' holders claim control; rule before any edge is admitted',
       p.evidence_json, p.evidence_hash, COALESCE(gx.amt, 0), CAST(NULL AS VARCHAR(16)),
       {filed_at}, {baseline_run}, 'talos-sql-1'
FROM p
LEFT JOIN grp g ON g.entity_key = 'E:' || p.held_cin
LEFT JOIN gexp gx ON gx.group_key = g.group_key
WHERE NOT EXISTS (SELECT 1 FROM GOV.PROPOSAL x WHERE x.proposal_id = p.proposal_id)
  AND NOT EXISTS (SELECT 1 FROM GOV.DECISION_LOG d
                  JOIN GOV.PROPOSAL y ON y.proposal_id = d.proposal_id
                  WHERE y.subject_key = p.subject_key AND d.decision = 'RULING');

-- INTERDEP: credit-memo dependencies at or above INTERDEP_SHARE_MIN, between the entities
-- the two LOS customers resolve to: the approved link if any, else the best T0/T1 pair.
-- Human only: never batched, never sent to the judge. An unresolved side is filed as a
-- U: pseudo-entity with warning ENDPOINT_UNRESOLVED and cannot be approved until linked.
INSERT INTO GOV.PROPOSAL (proposal_id, kind, subject_key, pair_key, rec_key, entity_key,
                          holder_entity_key, held_entity_key, tier, tier_reason, warning,
                          evidence_json, evidence_hash, rupee_impact, batch_id, filed_at,
                          filed_by_run, pipeline_version)
WITH los_load AS (
  SELECT load_id
  FROM (SELECT DISTINCT load_id, loaded_at FROM RAW_LOS.DEPENDENCY
        WHERE business_date = {business_date} AND loaded_at <= {known_at})
  QUALIFY ROW_NUMBER() OVER (ORDER BY loaded_at DESC, load_id DESC) = 1
),
dep AS (
  SELECT d.*
  FROM RAW_LOS.DEPENDENCY d JOIN los_load l ON l.load_id = d.load_id
  WHERE d.share_pct >= CAST({INTERDEP_SHARE_MIN} AS DECIMAL(5,2))
),
linked AS (
  SELECT rec_key, entity_key FROM GRAPH.V_LINK_CURRENT WHERE "ACTION" = 'ASSERT'
),
proposed AS (
  SELECT rec_a AS rec_key, 'E:' || SUBSTR(rec_b, 5) AS entity_key
  FROM RESOLVE.V_PAIR_TIER_FINAL
  WHERE tier IN ('T0', 'T1')
  QUALIFY ROW_NUMBER() OVER (PARTITION BY rec_a
                             ORDER BY CASE tier WHEN 'T0' THEN 0 ELSE 1 END, composite DESC, rec_b) = 1
),
ends AS (
  SELECT d.cust_id, d.depends_on_cust_id, d.share_pct, d.noted_on,
         COALESCE(lh.entity_key, ph.entity_key, 'U:LOS:' || d.depends_on_cust_id) AS holder_key,
         COALESCE(ld.entity_key, pd.entity_key, 'U:LOS:' || d.cust_id) AS held_key,
         CASE WHEN lh.entity_key IS NOT NULL THEN 'LINKED' WHEN ph.entity_key IS NOT NULL THEN 'PROPOSED' ELSE 'UNRESOLVED' END AS holder_basis,
         CASE WHEN ld.entity_key IS NOT NULL THEN 'LINKED' WHEN pd.entity_key IS NOT NULL THEN 'PROPOSED' ELSE 'UNRESOLVED' END AS held_basis
  FROM dep d
  LEFT JOIN linked lh ON lh.rec_key = 'LOS:' || d.depends_on_cust_id
  LEFT JOIN proposed ph ON ph.rec_key = 'LOS:' || d.depends_on_cust_id
  LEFT JOIN linked ld ON ld.rec_key = 'LOS:' || d.cust_id
  LEFT JOIN proposed pd ON pd.rec_key = 'LOS:' || d.cust_id
),
one AS (
  SELECT ends.*, 'INTERDEP:' || holder_key || '>' || held_key AS subject_key
  FROM ends
  WHERE holder_key <> held_key
  QUALIFY ROW_NUMBER() OVER (PARTITION BY holder_key, held_key ORDER BY share_pct DESC, cust_id, depends_on_cust_id) = 1
),
ev AS (
  SELECT one.*,
         '{{"kind":"INTERDEP","holder_entity_key":"' || REPLACE(REPLACE(REGEXP_REPLACE(COALESCE(holder_key, ''), '[\x00-\x1f]', ' '), '\', '\\'), '"', '\"') || '","held_entity_key":"' || REPLACE(REPLACE(REGEXP_REPLACE(COALESCE(held_key, ''), '[\x00-\x1f]', ' '), '\', '\\'), '"', '\"')
         || '","cust_id":"' || REPLACE(REPLACE(REGEXP_REPLACE(COALESCE(cust_id, ''), '[\x00-\x1f]', ' '), '\', '\\'), '"', '\"') || '","depends_on_cust_id":"' || REPLACE(REPLACE(REGEXP_REPLACE(COALESCE(depends_on_cust_id, ''), '[\x00-\x1f]', ' '), '\', '\\'), '"', '\"')
         || '","share_pct":' || CAST(share_pct AS VARCHAR(8)) || ',"stake_pct":' || CAST(share_pct AS VARCHAR(8))
         || ',"effective_from":"' || TO_CHAR(noted_on, 'YYYY-MM-DD') || '","noted_on":"' || TO_CHAR(noted_on, 'YYYY-MM-DD')
         || '","holder_basis":"' || REPLACE(REPLACE(REGEXP_REPLACE(COALESCE(holder_basis, ''), '[\x00-\x1f]', ' '), '\', '\\'), '"', '\"') || '","held_basis":"' || REPLACE(REPLACE(REGEXP_REPLACE(COALESCE(held_basis, ''), '[\x00-\x1f]', ' '), '\', '\\'), '"', '\"') || '"}}' AS evidence_json
  FROM one
),
p AS (
  SELECT ev.*, HASH_SHA256(evidence_json) AS evidence_hash,
         'P-' || SUBSTR(HASH_SHA256('INTERDEP' || subject_key || HASH_SHA256(evidence_json)), 1, 12) AS proposal_id
  FROM ev
),
grp AS (
  SELECT entity_key, group_key FROM GOV.RUN_MEMBERSHIP
  WHERE run_id = {baseline_run} AND membership_kind = 'MEMBER'
),
gexp AS (
  SELECT group_key, SUM(exposure_amount) AS amt FROM GOV.RUN_OUTPUT
  WHERE run_id = {baseline_run} GROUP BY group_key
)
SELECT p.proposal_id, 'INTERDEP', p.subject_key, CAST(NULL AS VARCHAR(16)), CAST(NULL AS VARCHAR(40)),
       CAST(NULL AS VARCHAR(48)), p.holder_key, p.held_key, CAST(NULL AS VARCHAR(20)), 'CREDIT_INTERDEPENDENCE',
       CASE WHEN p.holder_basis = 'UNRESOLVED' OR p.held_basis = 'UNRESOLVED'
              THEN 'ENDPOINT_UNRESOLVED: link both customers before approving'
            WHEN p.holder_basis = 'PROPOSED' OR p.held_basis = 'PROPOSED'
              THEN 'ENDPOINT_PROPOSED: a customer-to-entity link is still awaiting review' END,
       p.evidence_json, p.evidence_hash,
       CASE WHEN gh.group_key IS NULL OR gd.group_key IS NULL OR gh.group_key = gd.group_key THEN 0
            ELSE COALESCE(gx.amt, 0) END,
       CAST(NULL AS VARCHAR(16)), {filed_at}, {baseline_run}, 'talos-sql-1'
FROM p
LEFT JOIN grp gh ON gh.entity_key = p.holder_key
LEFT JOIN grp gd ON gd.entity_key = p.held_key
LEFT JOIN gexp gx ON gx.group_key = gd.group_key
WHERE NOT EXISTS (SELECT 1 FROM GOV.PROPOSAL x WHERE x.proposal_id = p.proposal_id)
  AND NOT EXISTS (SELECT 1 FROM GRAPH.V_OWNERSHIP_CURRENT c
                  WHERE c.edge_key = p.subject_key
                    AND ((c."ACTION" = 'ASSERT' AND c.status = 'CONFIRMED')
                         OR (c.status = 'REJECTED' AND c.evidence_hash = p.evidence_hash)));
