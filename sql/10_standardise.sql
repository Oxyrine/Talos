-- 10_standardise.sql: one standardised row per identity (book records and registry filings).
-- Latest row per identity across loads known at {known_at}. Names: uppercase, punctuation to
-- spaces, the inverse of the generator's ABBREV table, legal suffixes stripped. The honorific
-- stoplist (SHREE, SHRI, SRI, THE, NEW, M S) is fixed domain knowledge (DECISIONS.md).
-- Column aliases are reused only across CTE layers, never inside one SELECT list.

TRUNCATE TABLE STAGE.RECORD_STD;

INSERT INTO STAGE.RECORD_STD (
  rec_key, side, source_system, source_ref, name_raw, name_std, name_nospace, first_token,
  soundex_first, cologne_first, address_raw, city, district, state_code, pincode,
  pan_raw, cin_raw, lei_raw, director_tok)
WITH src AS (
  SELECT 'LOS:' || cust_id AS rec_key, 'BOOK' AS side, 'LOS' AS source_system, cust_id AS source_ref,
         cust_name AS name_raw, address AS address_raw, city, state_code, pan AS pan_raw, cin AS cin_raw,
         CAST(NULL AS VARCHAR(24)) AS lei_raw, director_dins AS dins
  FROM RAW_LOS.CUSTOMER
  WHERE loaded_at <= {known_at}
  QUALIFY ROW_NUMBER() OVER (PARTITION BY cust_id ORDER BY loaded_at DESC, load_id DESC) = 1
  UNION ALL
  SELECT 'TSY:' || issuer_ref, 'BOOK', 'TSY', issuer_ref, issuer_name, address, city, state_code, pan, cin,
         lei, CAST(NULL AS VARCHAR(200))
  FROM RAW_TREASURY.HOLDING
  WHERE loaded_at <= {known_at}
  QUALIFY ROW_NUMBER() OVER (PARTITION BY issuer_ref ORDER BY loaded_at DESC, load_id DESC, holding_id) = 1
  UNION ALL
  SELECT 'GTE:' || party_ref, 'BOOK', 'GTE', party_ref, party_name, address, city, state_code, pan, cin,
         CAST(NULL AS VARCHAR(24)), CAST(NULL AS VARCHAR(200))
  FROM RAW_GUARANTEE.GUARANTEE
  WHERE loaded_at <= {known_at}
  QUALIFY ROW_NUMBER() OVER (PARTITION BY party_ref ORDER BY loaded_at DESC, load_id DESC, guarantee_id) = 1
  UNION ALL
  SELECT 'COL:' || pledgor_ref, 'BOOK', 'COL', pledgor_ref, pledgor_name, address, city, state_code, pan, cin,
         CAST(NULL AS VARCHAR(24)), CAST(NULL AS VARCHAR(200))
  FROM RAW_COLLATERAL.PLEDGE
  WHERE loaded_at <= {known_at}
  QUALIFY ROW_NUMBER() OVER (PARTITION BY pledgor_ref ORDER BY loaded_at DESC, load_id DESC, pledge_id) = 1
  UNION ALL
  SELECT 'REG:' || cin, 'REG', 'REG', cin, entity_name, address, city, state_code, pan, cin, lei, director_dins
  FROM RAW_REGISTRY.ENTITY_FILING
  WHERE loaded_at <= {known_at}
  QUALIFY ROW_NUMBER() OVER (PARTITION BY cin ORDER BY loaded_at DESC, load_id DESC) = 1
),
l1 AS (
  SELECT s.*, ' ' || REGEXP_REPLACE(UPPER(name_raw), '[^A-Z0-9]+', ' ') || ' ' AS n1
  FROM src s
),
l2 AS (
  SELECT l1.*,
    REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(
    REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(n1,
      '\bPVT\b', 'PRIVATE'),
      '\bLTD\b', 'LIMITED'),
      '\bTEX\b', 'TEXTILES'),
      '\bINDS\b', 'INDUSTRIES'),
      '\bENGG\b', 'ENGINEERING'),
      '\bMFG\b', 'MANUFACTURING'),
      '\bPHARMA\b', 'PHARMACEUTICALS'),
      '\bCHEM\b', 'CHEMICALS'),
      '\bINTL\b', 'INTERNATIONAL'),
      '\bINFRA\b', 'INFRASTRUCTURE') AS n2
  FROM l1
),
l3 AS (
  SELECT l2.*,
    TRIM(REGEXP_REPLACE(
      REGEXP_REPLACE(n2, '\b(PRIVATE|PVT|LIMITED|LTD|P|PLC|LLP|CO|COMPANY|CORPORATION|CORPN|INC|M S)\b', ' '),
      ' +', ' ')) AS std,
    REGEXP_SUBSTR(address_raw, '\b[1-9][0-9]{{5}}\b') AS pin,
    REGEXP_SUBSTR(dins, '[0-9]{{8}}', 1, 1) AS d1,
    REGEXP_SUBSTR(dins, '[0-9]{{8}}', 1, 2) AS d2,
    REGEXP_SUBSTR(dins, '[0-9]{{8}}', 1, 3) AS d3,
    REGEXP_SUBSTR(dins, '[0-9]{{8}}', 1, 4) AS d4
  FROM l2
),
l4 AS (
  SELECT l3.*,
    REGEXP_SUBSTR(REGEXP_REPLACE(std, '^((SHREE|SHRI|SRI|THE|NEW|M S) )+', ''), '[A-Z0-9]+') AS ftok,
    -- HASH_SHA256('DIN:' || NULL) is a hash, not NULL, so absent DINs are filtered first.
    TRIM(BOTH ';' FROM
      CASE WHEN d1 IS NULL THEN CAST(NULL AS VARCHAR(64)) ELSE CAST(HASH_SHA256('DIN:' || d1) AS VARCHAR(64)) END || ';' ||
      CASE WHEN d2 IS NULL THEN CAST(NULL AS VARCHAR(64)) ELSE CAST(HASH_SHA256('DIN:' || d2) AS VARCHAR(64)) END || ';' ||
      CASE WHEN d3 IS NULL THEN CAST(NULL AS VARCHAR(64)) ELSE CAST(HASH_SHA256('DIN:' || d3) AS VARCHAR(64)) END || ';' ||
      CASE WHEN d4 IS NULL THEN CAST(NULL AS VARCHAR(64)) ELSE CAST(HASH_SHA256('DIN:' || d4) AS VARCHAR(64)) END) AS dtok
  FROM l3
)
SELECT l4.rec_key, l4.side, l4.source_system, l4.source_ref, l4.name_raw, l4.std,
       REPLACE(l4.std, ' ', ''), l4.ftok, SOUNDEX(l4.ftok), COLOGNE_PHONETIC(l4.ftok),
       l4.address_raw, l4.city, pd.district, l4.state_code, l4.pin,
       l4.pan_raw, l4.cin_raw, l4.lei_raw, l4.dtok
FROM l4
LEFT JOIN STAGE.PINCODE_DISTRICT pd ON pd.pincode = l4.pin;
