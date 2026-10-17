-- 61_membership.sql: groups of the run. A group is a connected component of admitted edges.
--   Controlled member: target of a CONFIRMED MAJORITY control edge whose holder is in the
--     same component (self-owning edges never count).
--   Head: uncontrolled first, then largest exposure, then key. The head is a member of its
--     own group; group_key = head entity key.
--   Flags (comma-joined, alphabetical):
--     CYCLE_HEADED  no member is uncontrolled (a rootless cycle)
--     UNASSIGNED    a member has a CONTROL_RULING proposal filed by known_at and no RULING
--                   decided by known_at
--     UNRESOLVED    the head is a U: pseudo-entity (an unlinked book record)

INSERT INTO GOV.RUN_MEMBERSHIP (run_id, group_key, entity_key, membership_kind, is_head, group_flags)
WITH comp AS (
  SELECT c.entity_id, c.label, COALESCE(x.exposure, 0) AS exposure
  FROM RESOLVE.W_COMPONENT_RUN c
  LEFT JOIN RESOLVE.W_ENTITY_EXPOSURE_RUN x ON x.entity_key = c.entity_id
),
ctrl AS (
  SELECT DISTINCT e.held_key
  FROM RESOLVE.W_EDGE_RUN e
  JOIN comp h ON h.entity_id = e.holder_key
  JOIN comp d ON d.entity_id = e.held_key
  WHERE e.status = 'CONFIRMED' AND e.edge_kind = 'CONTROL' AND e.control_type = 'MAJORITY'
    AND e.holder_key <> e.held_key AND h.label = d.label
),
m AS (
  SELECT comp.entity_id, comp.label, comp.exposure,
         CASE WHEN ctrl.held_key IS NULL THEN 1 ELSE 0 END AS uncontrolled
  FROM comp
  LEFT JOIN ctrl ON ctrl.held_key = comp.entity_id
),
heads AS (
  SELECT label, entity_id AS head_key
  FROM m
  QUALIFY ROW_NUMBER() OVER (PARTITION BY label ORDER BY uncontrolled DESC, exposure DESC, entity_id) = 1
),
pending AS (
  SELECT DISTINCT p.held_entity_key
  FROM GOV.PROPOSAL p
  WHERE p.kind = 'CONTROL_RULING' AND p.filed_at <= {known_at}
    AND NOT EXISTS (SELECT 1 FROM GOV.DECISION_LOG d
                    WHERE d.proposal_id = p.proposal_id AND d.decision = 'RULING'
                      AND d.decided_at <= {known_at})
),
lf AS (
  SELECT m.label,
         MAX(m.uncontrolled) AS any_uncontrolled,
         MAX(CASE WHEN pending.held_entity_key IS NULL THEN 0 ELSE 1 END) AS any_pending
  FROM m
  LEFT JOIN pending ON pending.held_entity_key = m.entity_id
  GROUP BY m.label
),
gf AS (
  SELECT h.label, h.head_key,
         TRIM(BOTH ',' FROM REGEXP_REPLACE(
           CASE WHEN lf.any_uncontrolled = 0 THEN CAST('CYCLE_HEADED' AS VARCHAR(20)) END || ',' ||
           CASE WHEN lf.any_pending = 1 THEN CAST('UNASSIGNED' AS VARCHAR(20)) END || ',' ||
           CASE WHEN h.head_key LIKE 'U:%' THEN CAST('UNRESOLVED' AS VARCHAR(20)) END, ',+', ',')) AS flags
  FROM heads h
  JOIN lf ON lf.label = h.label
)
SELECT {run_id}, gf.head_key, m.entity_id, 'MEMBER',
       CASE WHEN m.entity_id = gf.head_key THEN TRUE ELSE FALSE END,
       gf.flags
FROM m
JOIN gf ON gf.label = m.label;

-- Joint-venture attribution (policy JV_COUNT_IN_CONTROLLERS = 1): for an entity J with two
-- or more CONFIRMED JOINT control edges, every member of J's group is also attributed to
-- each controller's group. Book totals count J once (MEMBER rows only); limit checks
-- count it in each controller's group too.
INSERT INTO GOV.RUN_MEMBERSHIP (run_id, group_key, entity_key, membership_kind, is_head, group_flags)
SELECT DISTINCT {run_id}, gc.group_key, mj.entity_key, 'JV_ATTRIBUTION', FALSE, CAST(NULL AS VARCHAR(80))
FROM RESOLVE.W_EDGE_RUN j
JOIN (
  SELECT held_key
  FROM RESOLVE.W_EDGE_RUN
  WHERE status = 'CONFIRMED' AND edge_kind = 'CONTROL' AND control_type = 'JOINT'
  GROUP BY held_key
  HAVING COUNT(DISTINCT holder_key) >= 2
) jj ON jj.held_key = j.held_key
JOIN GOV.RUN_MEMBERSHIP gj
  ON gj.run_id = {run_id} AND gj.membership_kind = 'MEMBER' AND gj.entity_key = j.held_key
JOIN GOV.RUN_MEMBERSHIP mj
  ON mj.run_id = {run_id} AND mj.membership_kind = 'MEMBER' AND mj.group_key = gj.group_key
JOIN GOV.RUN_MEMBERSHIP gc
  ON gc.run_id = {run_id} AND gc.membership_kind = 'MEMBER' AND gc.entity_key = j.holder_key
WHERE j.status = 'CONFIRMED' AND j.edge_kind = 'CONTROL' AND j.control_type = 'JOINT'
  AND gc.group_key <> gj.group_key
  AND CAST({JV_COUNT_IN_CONTROLLERS} AS DECIMAL(1)) = 1;
