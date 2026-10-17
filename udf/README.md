# Union-find UDF: the scale path (not built)

The MVP computes groups with label propagation in plain SQL (`sql/51_components_init.sql`,
`sql/52_components_pass.sql`): each pass is one `MERGE` and costs one hop of the longest path
in a component. Registry trees are at most six levels deep, so dev converges in a handful of
passes and the 50-pass guard (`LP_MAX_PASSES`) never trips.

A union-find set UDF would compute every component in one pass over the admitted edges,
which matters only when components have very long paths (long chains of interdependence
edges, for example). The plan was a `PYTHON3 SET SCRIPT` that reads `(a, b)` edges grouped by
a hash bucket and emits `(entity_id, root)`.

It is not built because Exasol Nano ships without a script language container: probe 12 in
`docs/PROBE.md` fails with "No usable script language container is installed". On an Exasol
deployment with the standard Python 3 container the UDF can replace stage 52 without changing
any table or view: it would write `RESOLVE.W_COMPONENT_RUN` directly, and stages 60 to 63 stay
as they are.
