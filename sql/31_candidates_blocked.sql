-- 31_candidates_blocked.sql: BOOK x REG pairs that share a block key, one row per pair with
-- the passes that found it ('P1,P3'). Pairs already present from the exact-ID path and
-- dropped (oversize) blocks are excluded.

INSERT INTO RESOLVE.CANDIDATE_PAIR (pair_key, rec_a, rec_b, via, name_dist)
SELECT SUBSTR(HASH_SHA256(k.rec_key || '|' || k2.rec_key), 1, 16),
       k.rec_key,
       k2.rec_key,
       GROUP_CONCAT(DISTINCT k.pass_name ORDER BY k.pass_name SEPARATOR ','),
       EDIT_DISTANCE(a.name_std, b.name_std)
FROM STAGE.RECORD_BLOCK_KEY k
JOIN STAGE.RECORD_BLOCK_KEY k2
  ON k.pass_name = k2.pass_name AND k.block_key = k2.block_key
 AND k.side = 'BOOK' AND k2.side = 'REG'
JOIN STAGE.RECORD_STD a ON a.rec_key = k.rec_key
JOIN STAGE.RECORD_STD b ON b.rec_key = k2.rec_key
WHERE NOT EXISTS (SELECT 1 FROM STAGE.BLOCK_DROPPED d
                  WHERE d.pass_name = k.pass_name AND d.block_key = k.block_key)
  AND NOT EXISTS (SELECT 1 FROM RESOLVE.CANDIDATE_PAIR p
                  WHERE p.rec_a = k.rec_key AND p.rec_b = k2.rec_key)
GROUP BY k.rec_key, k2.rec_key, a.name_std, b.name_std;
