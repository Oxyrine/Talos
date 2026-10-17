-- 30_block_keys.sql: blocking keys in their own table, distributed on the key.
--   P1 = phonetic first token + state     (skipped when the state is missing)
--   P2 = phonetic first token + pincode   (skipped when the pincode is missing)
--   P3 = first six characters of the name with spaces removed (names of 6+ characters)
-- Keys with more than BLOCK_MAX members on either side are dropped and reported.

TRUNCATE TABLE STAGE.RECORD_BLOCK_KEY;

INSERT INTO STAGE.RECORD_BLOCK_KEY (rec_key, side, pass_name, block_key)
SELECT rec_key, side, 'P1', soundex_first || '|' || state_code
FROM STAGE.RECORD_STD
WHERE soundex_first IS NOT NULL AND state_code IS NOT NULL
UNION ALL
SELECT rec_key, side, 'P2', soundex_first || '|' || pincode
FROM STAGE.RECORD_STD
WHERE soundex_first IS NOT NULL AND pincode IS NOT NULL
UNION ALL
SELECT rec_key, side, 'P3', SUBSTR(name_nospace, 1, 6)
FROM STAGE.RECORD_STD
WHERE LENGTH(name_nospace) >= 6;

TRUNCATE TABLE STAGE.BLOCK_DROPPED;

INSERT INTO STAGE.BLOCK_DROPPED (pass_name, block_key, book_n, reg_n)
SELECT pass_name, block_key,
       SUM(CASE WHEN side = 'BOOK' THEN 1 ELSE 0 END),
       SUM(CASE WHEN side = 'REG' THEN 1 ELSE 0 END)
FROM STAGE.RECORD_BLOCK_KEY
GROUP BY pass_name, block_key
HAVING SUM(CASE WHEN side = 'BOOK' THEN 1 ELSE 0 END) > CAST({BLOCK_MAX} AS DECIMAL(9))
    OR SUM(CASE WHEN side = 'REG' THEN 1 ELSE 0 END) > CAST({BLOCK_MAX} AS DECIMAL(9));
