-- 52_components_pass.sql: one label-propagation pass (the product spec's MERGE).
-- The orchestrator repeats it until it updates 0 rows, at most LP_MAX_PASSES times, else
-- the run is recorded as LP_ABORTED. Labels only ever decrease (string MIN), so the result
-- does not depend on row order. Edges are admitted CONFIRMED majority-control and
-- interdependence edges, direction ignored.

MERGE INTO RESOLVE.W_COMPONENT_RUN c
USING (
  SELECT e.a AS entity_id, MIN(n.label) AS new_label
  FROM RESOLVE.V_ADMITTED_EDGE_UNDIRECTED e
  JOIN RESOLVE.W_COMPONENT_RUN n ON n.entity_id = e.b
  GROUP BY e.a
) u ON c.entity_id = u.entity_id
WHEN MATCHED THEN UPDATE SET c.label = u.new_label
  WHERE u.new_label < c.label;
