-- 20_id_tokens_exact.sql: exact identifiers, no blocking. One token per valid identifier,
-- hashed with the secret {id_token_key} (TALOS_ID_TOKEN_KEY) so the raw PAN / CIN / LEI never
-- leaves this stage and a token cannot be reversed by enumerating identifiers. A shared token pairs a book
-- record with a registry filing whatever their names or states, so planted ID-name
-- conflicts always reach scoring.

TRUNCATE TABLE STAGE.RECORD_ID_TOKEN;

INSERT INTO STAGE.RECORD_ID_TOKEN (rec_key, side, id_type, token)
SELECT rec_key, side, 'PAN', HASH_SHA256({id_token_key} || '|PAN:' || v)
FROM (SELECT rec_key, side, UPPER(TRIM(pan_raw)) AS v FROM STAGE.RECORD_STD)
WHERE v REGEXP_LIKE '[A-Z]{{3}}[ABCFGHLJPT][A-Z][0-9]{{4}}[A-Z]'
UNION ALL
SELECT rec_key, side, 'CIN', HASH_SHA256({id_token_key} || '|CIN:' || v)
FROM (SELECT rec_key, side, UPPER(TRIM(cin_raw)) AS v FROM STAGE.RECORD_STD)
WHERE v REGEXP_LIKE '[LU][0-9]{{5}}[A-Z]{{2}}[0-9]{{4}}[A-Z]{{3}}[0-9]{{6}}'
UNION ALL
SELECT rec_key, side, 'LEI', HASH_SHA256({id_token_key} || '|LEI:' || v)
FROM (SELECT rec_key, side, UPPER(TRIM(lei_raw)) AS v FROM STAGE.RECORD_STD)
WHERE v REGEXP_LIKE '[A-Z0-9]{{18}}[0-9]{{2}}';

TRUNCATE TABLE RESOLVE.CANDIDATE_PAIR;

INSERT INTO RESOLVE.CANDIDATE_PAIR (pair_key, rec_a, rec_b, via, name_dist)
SELECT SUBSTR(HASH_SHA256(a.rec_key || '|' || b.rec_key), 1, 16),
       a.rec_key,
       b.rec_key,
       'EXACT_' || GROUP_CONCAT(DISTINCT a.id_type ORDER BY a.id_type SEPARATOR '+'),
       EDIT_DISTANCE(ra.name_std, rb.name_std)
FROM STAGE.RECORD_ID_TOKEN a
JOIN STAGE.RECORD_ID_TOKEN b
  ON a.id_type = b.id_type AND a.token = b.token AND a.side = 'BOOK' AND b.side = 'REG'
JOIN STAGE.RECORD_STD ra ON ra.rec_key = a.rec_key
JOIN STAGE.RECORD_STD rb ON rb.rec_key = b.rec_key
GROUP BY a.rec_key, b.rec_key, ra.name_std, rb.name_std;
