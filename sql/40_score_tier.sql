-- 40_score_tier.sql: score every candidate pair and assign a tier. Thresholds and weights
-- are policy events (frozen in policy/thresholds.json), passed in by the orchestrator.
-- Tiers decide how a proposal is presented, never whether it skips a human.
--
--   T0  exact ID, no other ID conflicts, name_sim >= ID_NAME_MIN_SIM          EXACT_ID
--   T3  exact ID otherwise                          ID_NAME_CONFLICT | CONFLICTING_ID
--   --  conflicting ID, blocked path, and the record already has a T0 pair
--                                  DISCARD_ID_CONFLICT / ID_RESOLVED_ELSEWHERE [DEV-23]
--   T3  conflicting ID and composite >= T2_LOW                          CONFLICTING_ID
--   --  conflicting ID otherwise                 DISCARD_ID_CONFLICT (kept for the funnel)
--   T1  (name_dist <= T1_MAX_DIST and same pincode) or composite >= T2_HIGH
--                                                  STRONG_NAME_PIN | STRONG_COMPOSITE
--   T2  T2_LOW <= composite < T2_HIGH                                         GREY_BAND
--   --  below T2_LOW                                 DISCARD_LOW_SCORE (kept for the funnel)

TRUNCATE TABLE RESOLVE.PAIR_SCORE;

INSERT INTO RESOLVE.PAIR_SCORE (
  pair_key, rec_a, rec_b, via, name_dist, name_sim, phon_eq, pin_eq, state_eq,
  id_agree, id_conflict, conflict_types, composite, tier, tier_reason)
WITH idc AS (
  SELECT c.pair_key,
         MAX(CASE WHEN ta.token = tb.token THEN 1 ELSE 0 END) AS id_agree,
         MAX(CASE WHEN ta.token <> tb.token THEN 1 ELSE 0 END) AS id_conflict,
         GROUP_CONCAT(DISTINCT CASE WHEN ta.token <> tb.token THEN ta.id_type END
                      ORDER BY CASE WHEN ta.token <> tb.token THEN ta.id_type END SEPARATOR ',') AS conflict_types
  FROM RESOLVE.CANDIDATE_PAIR c
  JOIN STAGE.RECORD_ID_TOKEN ta ON ta.rec_key = c.rec_a
  JOIN STAGE.RECORD_ID_TOKEN tb ON tb.rec_key = c.rec_b AND tb.id_type = ta.id_type
  GROUP BY c.pair_key
),
f AS (
  SELECT c.pair_key, c.rec_a, c.rec_b, c.via, c.name_dist,
         1 - CAST(c.name_dist AS DOUBLE)
             / GREATEST(LENGTH(COALESCE(a.name_std, '')), LENGTH(COALESCE(b.name_std, '')), 1) AS name_sim,
         CASE WHEN a.soundex_first = b.soundex_first OR a.cologne_first = b.cologne_first THEN 1 ELSE 0 END AS phon_eq,
         CASE WHEN a.pincode = b.pincode THEN 1 ELSE 0 END AS pin_eq,
         CASE WHEN a.state_code = b.state_code THEN 1 ELSE 0 END AS state_eq,
         COALESCE(i.id_agree, 0) AS id_agree,
         COALESCE(i.id_conflict, 0) AS id_conflict,
         i.conflict_types
  FROM RESOLVE.CANDIDATE_PAIR c
  JOIN STAGE.RECORD_STD a ON a.rec_key = c.rec_a
  JOIN STAGE.RECORD_STD b ON b.rec_key = c.rec_b
  LEFT JOIN idc i ON i.pair_key = c.pair_key
),
g AS (
  SELECT f.*,
         CAST({W_NAME} AS DOUBLE) * name_sim
         + CAST({W_PHON} AS DOUBLE) * phon_eq
         + CAST({W_PIN} AS DOUBLE) * pin_eq
         + CAST({W_STATE} AS DOUBLE) * state_eq AS composite,
         MAX(CASE WHEN via LIKE 'EXACT_%' AND id_conflict = 0
                   AND name_sim >= CAST({ID_NAME_MIN_SIM} AS DOUBLE) THEN 1 ELSE 0 END)
           OVER (PARTITION BY rec_a) AS rec_has_t0
  FROM f
),
t AS (
  SELECT g.*,
    CASE
      WHEN via LIKE 'EXACT_%' AND id_conflict = 0 AND name_sim >= CAST({ID_NAME_MIN_SIM} AS DOUBLE) THEN 'T0'
      WHEN via LIKE 'EXACT_%' THEN 'T3'
      WHEN id_conflict = 1 AND rec_has_t0 = 1 THEN 'DISCARD_ID_CONFLICT'
      WHEN id_conflict = 1 AND composite >= CAST({T2_LOW} AS DOUBLE) THEN 'T3'
      WHEN id_conflict = 1 THEN 'DISCARD_ID_CONFLICT'
      WHEN (name_dist <= CAST({T1_MAX_DIST} AS DECIMAL(5)) AND pin_eq = 1)
           OR composite >= CAST({T2_HIGH} AS DOUBLE) THEN 'T1'
      WHEN composite >= CAST({T2_LOW} AS DOUBLE) THEN 'T2'
      ELSE 'DISCARD_LOW_SCORE'
    END AS tier,
    CASE
      WHEN via LIKE 'EXACT_%' AND id_conflict = 0 AND name_sim >= CAST({ID_NAME_MIN_SIM} AS DOUBLE) THEN 'EXACT_ID'
      WHEN via LIKE 'EXACT_%' AND name_sim < CAST({ID_NAME_MIN_SIM} AS DOUBLE) THEN 'ID_NAME_CONFLICT'
      WHEN via LIKE 'EXACT_%' THEN 'CONFLICTING_ID'
      WHEN id_conflict = 1 AND rec_has_t0 = 1 THEN 'ID_RESOLVED_ELSEWHERE'
      WHEN id_conflict = 1 AND composite >= CAST({T2_LOW} AS DOUBLE) THEN 'CONFLICTING_ID'
      WHEN id_conflict = 1 THEN 'ID_CONFLICT_LOW_SCORE'
      WHEN name_dist <= CAST({T1_MAX_DIST} AS DECIMAL(5)) AND pin_eq = 1 THEN 'STRONG_NAME_PIN'
      WHEN composite >= CAST({T2_HIGH} AS DOUBLE) THEN 'STRONG_COMPOSITE'
      WHEN composite >= CAST({T2_LOW} AS DOUBLE) THEN 'GREY_BAND'
      ELSE 'BELOW_T2_LOW'
    END AS tier_reason
  FROM g
)
SELECT pair_key, rec_a, rec_b, via, name_dist, name_sim, phon_eq, pin_eq, state_eq,
       id_agree, id_conflict, conflict_types, composite, tier, tier_reason
FROM t;
