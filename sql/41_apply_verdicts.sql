-- 41_apply_verdicts.sql: the judge's verdicts are applied by the view
-- RESOLVE.V_PAIR_TIER_FINAL (03_stage_resolve.sql), which reads the append-only
-- RESOLVE.LLM_VERDICT log, so nothing is rewritten here. This stage reports how many
-- pairs the verdicts moved, which the pipeline records in GOV.PIPELINE_TIMING.

SELECT COUNT(*) AS pairs_moved
FROM RESOLVE.V_PAIR_TIER_FINAL
WHERE tier <> base_tier OR tier_reason LIKE 'LLM_%';
