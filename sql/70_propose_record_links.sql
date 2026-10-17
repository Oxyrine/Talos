-- 70_propose_record_links.sql: file RECORD_LINK proposals after the baseline run.
--   Candidates: the best non-T3 pair per book record (T0 before T1 before T2, then
--   composite), plus every T3 pair, so a record with a wrong-PAN T3 and a true T1 shows both.
--   entity_key = 'E:' || cin of the registry side; subject_key = link_key = rec_key > entity.
--   Evidence holds names, places and ID status only: identifiers appear as hashed tokens.
--   rupee_impact = the record's exposure in the baseline run.
--   T0 proposals of this job share one sampled batch, B-REC-<hash of their sorted ids>.
--   Not filed again: links already asserted, rejections (DNL) with the same evidence, and
--   proposal ids already on file (ids are deterministic).

INSERT INTO GOV.PROPOSAL (proposal_id, kind, subject_key, pair_key, rec_key, entity_key,
                          holder_entity_key, held_entity_key, tier, tier_reason, warning,
                          evidence_json, evidence_hash, rupee_impact, batch_id, filed_at,
                          filed_by_run, pipeline_version)
WITH tok AS (
  SELECT rec_key,
         MAX(CASE WHEN id_type = 'PAN' THEN token END) AS pan_t,
         MAX(CASE WHEN id_type = 'CIN' THEN token END) AS cin_t,
         MAX(CASE WHEN id_type = 'LEI' THEN token END) AS lei_t
  FROM STAGE.RECORD_ID_TOKEN
  GROUP BY rec_key
),
best AS (
  SELECT pair_key, rec_a, rec_b, via, name_dist, name_sim, composite, tier, tier_reason, recommendation
  FROM (
    SELECT *
    FROM RESOLVE.V_PAIR_TIER_FINAL
    WHERE tier IN ('T0', 'T1', 'T2')
    QUALIFY ROW_NUMBER() OVER (PARTITION BY rec_a
                               ORDER BY CASE tier WHEN 'T0' THEN 0 WHEN 'T1' THEN 1 ELSE 2 END,
                                        composite DESC, rec_b) = 1
  )
  UNION ALL
  SELECT pair_key, rec_a, rec_b, via, name_dist, name_sim, composite, tier, tier_reason, recommendation
  FROM RESOLVE.V_PAIR_TIER_FINAL
  WHERE tier = 'T3'
),
ev AS (
  SELECT b.pair_key, b.rec_a, b.tier, b.tier_reason, b.recommendation,
         'E:' || SUBSTR(b.rec_b, 5) AS entity_key,
         b.rec_a || '>E:' || SUBSTR(b.rec_b, 5) AS subject_key,
         '{{"kind":"RECORD_LINK","rec_key":"' || b.rec_a || '","entity_key":"E:' || SUBSTR(b.rec_b, 5)
         || '","source_a":"' || a.source_system || '","source_b":"REG"'
         || ',"name_a_raw":"' || REPLACE(REPLACE(COALESCE(a.name_raw, ''), '\', '\\'), '"', '\"')
         || '","name_b_raw":"' || REPLACE(REPLACE(COALESCE(r.name_raw, ''), '\', '\\'), '"', '\"')
         || '","name_a_std":"' || COALESCE(a.name_std, '') || '","name_b_std":"' || COALESCE(r.name_std, '')
         || '","city_a":"' || COALESCE(a.city, '') || '","city_b":"' || COALESCE(r.city, '')
         || '","pincode_a":"' || COALESCE(a.pincode, '') || '","pincode_b":"' || COALESCE(r.pincode, '')
         || '","state_a":"' || COALESCE(a.state_code, '') || '","state_b":"' || COALESCE(r.state_code, '')
         || '","id_status":{{"PAN":"'
         || CASE WHEN ta.pan_t IS NULL OR tb.pan_t IS NULL THEN 'missing' WHEN ta.pan_t = tb.pan_t THEN 'agree' ELSE 'conflict' END
         || '","CIN":"'
         || CASE WHEN ta.cin_t IS NULL OR tb.cin_t IS NULL THEN 'missing' WHEN ta.cin_t = tb.cin_t THEN 'agree' ELSE 'conflict' END
         || '","LEI":"'
         || CASE WHEN ta.lei_t IS NULL OR tb.lei_t IS NULL THEN 'missing' WHEN ta.lei_t = tb.lei_t THEN 'agree' ELSE 'conflict' END
         || '"}},"id_tokens_a":{{"PAN":"' || COALESCE(SUBSTR(ta.pan_t, 1, 16), '') || '","CIN":"' || COALESCE(SUBSTR(ta.cin_t, 1, 16), '')
         || '"}},"id_tokens_b":{{"PAN":"' || COALESCE(SUBSTR(tb.pan_t, 1, 16), '') || '","CIN":"' || COALESCE(SUBSTR(tb.cin_t, 1, 16), '')
         || '"}},"via":"' || b.via || '","name_dist":' || CAST(b.name_dist AS VARCHAR(8))
         || ',"name_sim":' || CAST(CAST(b.name_sim AS DECIMAL(6,4)) AS VARCHAR(10))
         || ',"composite":' || CAST(CAST(b.composite AS DECIMAL(6,4)) AS VARCHAR(10))
         || ',"tier":"' || b.tier || '","tier_reason":"' || b.tier_reason || '"}}' AS evidence_json
  FROM best b
  JOIN STAGE.RECORD_STD a ON a.rec_key = b.rec_a
  JOIN STAGE.RECORD_STD r ON r.rec_key = b.rec_b
  LEFT JOIN tok ta ON ta.rec_key = b.rec_a
  LEFT JOIN tok tb ON tb.rec_key = b.rec_b
),
h AS (
  SELECT ev.*, HASH_SHA256(evidence_json) AS evidence_hash
  FROM ev
),
p AS (
  SELECT h.*, 'P-' || SUBSTR(HASH_SHA256('RECORD_LINK' || subject_key || evidence_hash), 1, 12) AS proposal_id
  FROM h
),
newp AS (
  SELECT p.*
  FROM p
  WHERE NOT EXISTS (SELECT 1 FROM GOV.PROPOSAL x WHERE x.proposal_id = p.proposal_id)
    AND NOT EXISTS (SELECT 1 FROM GRAPH.V_LINK_CURRENT c
                    WHERE c.link_key = p.subject_key
                      AND (c."ACTION" = 'ASSERT' OR (c."ACTION" = 'DNL' AND c.evidence_hash = p.evidence_hash)))
),
batch AS (
  SELECT 'B-REC-' || SUBSTR(HASH_SHA256(GROUP_CONCAT(proposal_id ORDER BY proposal_id SEPARATOR ',')), 1, 10) AS batch_id
  FROM newp
  WHERE tier = 'T0'
),
imp AS (
  SELECT rec_key, SUM(exposure_amount) AS amt
  FROM GOV.RUN_OUTPUT
  WHERE run_id = {baseline_run} AND membership_kind = 'MEMBER'
  GROUP BY rec_key
)
SELECT n.proposal_id, 'RECORD_LINK', n.subject_key, n.pair_key, n.rec_a, n.entity_key,
       CAST(NULL AS VARCHAR(48)), CAST(NULL AS VARCHAR(48)), n.tier, n.tier_reason,
       CASE n.tier_reason
         WHEN 'ID_NAME_CONFLICT' THEN 'Shared ID but the names differ: likely a wrong ID on the book record'
         WHEN 'CONFLICTING_ID' THEN 'Identifiers disagree although the names look alike'
         WHEN 'LLM_UNSURE' THEN 'Model was unsure or returned an invalid verdict'
         WHEN 'LLM_SAME_OVERRULED' THEN 'Model said same, but an identifier conflicts'
         ELSE CASE WHEN n.tier = 'T2' THEN 'Grey band: ' || n.recommendation END
       END,
       n.evidence_json, n.evidence_hash, COALESCE(i.amt, 0),
       CASE WHEN n.tier = 'T0' THEN b.batch_id END,
       {filed_at}, {baseline_run}, 'talos-sql-1'
FROM newp n
CROSS JOIN batch b
LEFT JOIN imp i ON i.rec_key = n.rec_a;
