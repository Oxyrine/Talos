-- 62_run_output.sql: every fact row of the run, once per membership of its entity.
-- MEMBER rows give book exposure (each entity once, so a diamond is counted once);
-- JV_ATTRIBUTION rows add the JV into its controllers' limit exposure.
-- Each row carries the decision and proposal that linked its record (NULL if unlinked).

INSERT INTO GOV.RUN_OUTPUT (run_id, group_key, entity_key, membership_kind, source_system, source_row_id,
                            exposure_component, rec_key, product, gross_amount, ccf, exposure_amount,
                            link_decision_id, link_proposal_id)
SELECT {run_id}, m.group_key, m.entity_key, m.membership_kind, f.source_system, f.source_row_id,
       f.exposure_component, f.rec_key, f.product, f.gross_amount, f.ccf, f.exposure_amount,
       l.decision_id, l.proposal_id
FROM RESOLVE.W_FACT_RUN f
LEFT JOIN RESOLVE.W_RECORD_ENTITY_RUN l ON l.rec_key = f.rec_key
JOIN GOV.RUN_MEMBERSHIP m
  ON m.run_id = {run_id} AND m.entity_key = COALESCE(l.entity_key, 'U:' || f.rec_key);
