-- 00_probe.sql: capability probe, run by `talos probe` as SYS. Results go to docs/PROBE.md.
-- Each block starts with a marker line:  -- @probe <n> | <feature> | <fallback>
-- A probe passes when every statement in its block runs. The last statement's first row
-- is recorded as evidence. Blocks marked @setup / @teardown are not scored.

-- @setup
CREATE SCHEMA IF NOT EXISTS TALOS_PROBE;
CREATE OR REPLACE TABLE TALOS_PROBE.T (id VARCHAR(10), label VARCHAR(10));
CREATE OR REPLACE TABLE TALOS_PROBE.E (a VARCHAR(10), b VARCHAR(10));

-- @probe 1 | EDIT_DISTANCE, SOUNDEX, COLOGNE_PHONETIC | none (core)
SELECT EDIT_DISTANCE('SUNRISE', 'SUNRIZE') AS ed, SOUNDEX('SUNRISE') AS sx, COLOGNE_PHONETIC('SUNRISE') AS cp;

-- @probe 2 | HASH_SHA256 | HASH_MD5 (token width 32)
SELECT HASH_SHA256('PAN:ABCDE1234F') AS h, LENGTH(HASH_SHA256('PAN:ABCDE1234F')) AS len;

-- @probe 3 | REGEXP_LIKE infix, full-string semantics | add explicit anchors
SELECT CASE WHEN 'ABCDE1234F' REGEXP_LIKE '[A-Z]{{5}}[0-9]{{4}}[A-Z]' THEN 1 ELSE 0 END AS full_match,
       CASE WHEN 'XXABCDE1234F' REGEXP_LIKE '[A-Z]{{5}}[0-9]{{4}}[A-Z]' THEN 1 ELSE 0 END AS prefix_rejected;

-- @probe 4 | REGEXP_REPLACE with word boundaries | lookaround form
SELECT TRIM(REGEXP_REPLACE(' SUNRISE PVT LTD ', '\b(PVT|LTD)\b', ' ')) AS stripped;

-- @probe 5 | QUALIFY | nested subquery
SELECT x FROM (SELECT 1 AS x FROM DUAL UNION ALL SELECT 2 FROM DUAL)
QUALIFY ROW_NUMBER() OVER (ORDER BY x DESC) = 1;

-- @probe 6 | MERGE ... UPDATE ... WHERE reading the target inside USING | CREATE TABLE AS per pass
INSERT INTO TALOS_PROBE.T VALUES ('a', 'a'), ('b', 'b'), ('c', 'c');
INSERT INTO TALOS_PROBE.E VALUES ('a', 'b'), ('b', 'a'), ('b', 'c'), ('c', 'b');
MERGE INTO TALOS_PROBE.T c
USING (SELECT e.a AS id, MIN(n.label) AS new_label
       FROM TALOS_PROBE.E e JOIN TALOS_PROBE.T n ON n.id = e.b GROUP BY e.a) u
ON c.id = u.id
WHEN MATCHED THEN UPDATE SET c.label = u.new_label WHERE u.new_label < c.label;
SELECT GROUP_CONCAT(label ORDER BY id SEPARATOR '') AS labels_after_one_pass FROM TALOS_PROBE.T;

-- @probe 7 | CONNECT BY NOCYCLE, CONNECT_BY_ISCYCLE, CONNECT_BY_ROOT, SYS_CONNECT_BY_PATH, LEVEL | none (display only)
SELECT MAX(is_cycle) AS saw_cycle, MAX(lvl) AS max_level, MAX(walk) AS longest_path, MIN(root_key) AS root_key
FROM (
  SELECT CONNECT_BY_ISCYCLE AS is_cycle, LEVEL AS lvl, SYS_CONNECT_BY_PATH(b, '>') AS walk, CONNECT_BY_ROOT a AS root_key
  FROM (SELECT 'a' AS a, 'b' AS b FROM DUAL UNION ALL SELECT 'b', 'c' FROM DUAL UNION ALL SELECT 'c', 'a' FROM DUAL)
  CONNECT BY NOCYCLE PRIOR b = a
  START WITH a = 'a'
);

-- @probe 8 | GROUPING SETS, ROLLUP, GROUPING() | UNION ALL of group-bys
SELECT g, s, SUM(v) AS total, GROUPING(g, s) AS lvl
FROM (SELECT 'G1' AS g, 'LOS' AS s, 10 AS v FROM DUAL UNION ALL SELECT 'G1', 'TSY', 5 FROM DUAL)
GROUP BY GROUPING SETS ((g, s), (g), ())
ORDER BY lvl DESC
LIMIT 1;

-- @probe 9 | GROUP_CONCAT(DISTINCT ... ORDER BY ... SEPARATOR) | LISTAGG
SELECT GROUP_CONCAT(DISTINCT x ORDER BY x SEPARATOR ',') AS passes
FROM (SELECT 'P3' AS x FROM DUAL UNION ALL SELECT 'P1' FROM DUAL UNION ALL SELECT 'P1' FROM DUAL);

-- @probe 10 | Bulk load path | pyexasol import_from_iterable (the loader's path)
CREATE OR REPLACE TABLE TALOS_PROBE.L (id DECIMAL(9), d DATE, ts TIMESTAMP, b BOOLEAN, amt DECIMAL(18,2));
INSERT INTO TALOS_PROBE.L VALUES (1, '2026-09-30', '2026-10-02 06:00:00', 'True', 1234.50);
SELECT COUNT(*) AS loaded, MAX(b) AS bool_from_text FROM TALOS_PROBE.L;

-- @probe 11 | Schema and object grants to a role | none (governance core)
CREATE ROLE TALOS_PROBE_ROLE;
GRANT SELECT ON TALOS_PROBE TO TALOS_PROBE_ROLE;
GRANT INSERT ON TALOS_PROBE.T TO TALOS_PROBE_ROLE;
DROP ROLE TALOS_PROBE_ROLE;
SELECT 'granted and revoked' AS outcome;

-- @probe 12 | Python3 scalar UDF | MVP unaffected; union-find UDF dropped
--/
CREATE OR REPLACE PYTHON3 SCALAR SCRIPT TALOS_PROBE.ONE() RETURNS DECIMAL(1) AS
def run(ctx):
    return 1
/
SELECT TALOS_PROBE.ONE() AS one;

-- @probe 13 | DISTRIBUTE BY inside CREATE TABLE | none
CREATE OR REPLACE TABLE TALOS_PROBE.D (k VARCHAR(10), v DECIMAL(9), DISTRIBUTE BY k);
SELECT 'created' AS outcome;

-- @probe 14 | CREATE TABLE IF NOT EXISTS (used by talos init) | CREATE OR REPLACE guarded in Python
CREATE TABLE IF NOT EXISTS TALOS_PROBE.D (k VARCHAR(10), v DECIMAL(9));
SELECT 'idempotent' AS outcome;

-- @probe 15 | REGEXP_SUBSTR with occurrence (DIN splitting) | client-side split
SELECT REGEXP_SUBSTR('12345678;23456789;34567890', '[0-9]{{8}}', 1, 2) AS second_din;

-- @teardown
DROP SCHEMA IF EXISTS TALOS_PROBE CASCADE;
