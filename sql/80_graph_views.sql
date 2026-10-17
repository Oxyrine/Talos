-- 80_graph_views.sql: the current state of the graph, by the replay rule evaluated at
-- CURRENT_DATE / SYSTIMESTAMP. Per key, among events whose [valid_from, valid_to) covers
-- today and that are already recorded, the latest recorded one wins. These views carry
-- every action (ASSERT, RETRACT, DNL); callers filter on action and status.

CREATE OR REPLACE VIEW GRAPH.V_LINK_CURRENT AS
SELECT event_id, link_key, rec_key, entity_key, "ACTION", evidence_hash,
       valid_from, valid_to, recorded_at, decision_id, proposal_id
FROM GRAPH.LINK_EVENT
WHERE recorded_at <= SYSTIMESTAMP
  AND valid_from <= CURRENT_DATE AND CURRENT_DATE < valid_to
QUALIFY ROW_NUMBER() OVER (PARTITION BY link_key ORDER BY recorded_at DESC, event_id DESC) = 1;

CREATE OR REPLACE VIEW GRAPH.V_OWNERSHIP_CURRENT AS
SELECT event_id, edge_key, holder_entity_key, held_entity_key, edge_kind, control_type,
       status, stake_pct, "ACTION", evidence_hash, valid_from, valid_to, recorded_at,
       decision_id, proposal_id
FROM GRAPH.OWNERSHIP_EVENT
WHERE recorded_at <= SYSTIMESTAMP
  AND valid_from <= CURRENT_DATE AND CURRENT_DATE < valid_to
QUALIFY ROW_NUMBER() OVER (PARTITION BY edge_key ORDER BY recorded_at DESC, event_id DESC) = 1;

-- Confirmed control edges in force today, with names for the ownership path display.
CREATE OR REPLACE VIEW GRAPH.V_CONTROL_EDGE AS
SELECT o.holder_entity_key AS holder_key,
       o.held_entity_key AS held_key,
       o.control_type,
       o.stake_pct,
       COALESCE(e.display_name, f.entity_name, o.held_entity_key) AS held_name
FROM GRAPH.V_OWNERSHIP_CURRENT o
LEFT JOIN GRAPH.ENTITY e ON e.entity_key = o.held_entity_key
LEFT JOIN (
  SELECT 'E:' || cin AS entity_key, entity_name
  FROM RAW_REGISTRY.ENTITY_FILING
  QUALIFY ROW_NUMBER() OVER (PARTITION BY cin ORDER BY loaded_at DESC, load_id DESC) = 1
) f ON f.entity_key = o.held_entity_key
WHERE o."ACTION" = 'ASSERT'
  AND o.status = 'CONFIRMED'
  AND o.edge_kind = 'CONTROL'
  AND o.control_type IN ('MAJORITY', 'JOINT');
