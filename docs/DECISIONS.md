# DECISIONS.md — Architectural Decision Records (Talos)

This document records the architectural and design decisions for **Talos** (ExaThon India 2026, Track 01), specifically logging all deviations marked **[DEV]** from the original 31-page product specification.

---

## 1. Product Identity & Core Stack
- **[DEV-01] Product Name:** Named **Talos** everywhere (codebase, package, CLI, UI, documentation). The working title "Atlas" from the prompt PDF is discarded to avoid confusion with existing tools.
- **[DEV-02] UI Technology:** **FastAPI + Jinja2 + HTMX 2.0.4** with pure hand-crafted CSS design tokens. No Node.js runtime, npm/npx build steps, Tailwind compiler, or JS bundlers. Runs as a single unified process (`talos serve`).
- **[DEV-03] LLM Judge Design:** Provider-swappable interface with a deterministic `stub` provider in the MVP returning `unsure` with 0% external model share until the Should tier selects an SDK.

---

## 2. Data Modeling & Exasol Architecture
- **[DEV-04] Bipartite Record-to-Registry Resolution:** Candidate pairs are strictly structured as `(book record, registry filing)` where `rec_a` is the BOOK side and `rec_b` is the REG side (MCA legal entity master). We do not perform quadratic all-pairs `rec_id < rec_id` matching across books. Entity membership is direct, eliminating unstable transitive record clustering.
- **[DEV-05] String Entity & Record Keys:** String keys (`'LOS:cust_id'`, `'E:cin'`, `'U:rec_key'`) replace surrogate decimal IDs, guaranteeing permanent stability across pipeline rebuilds without sequence generators.
- **[DEV-06] Collateral Treatment:** Collateral pledges contribute identity linkages only (bridging records via PAN/CIN). By credit policy, collateral CCF is set to 0.00 because Talos computes regulatory group exposure, not credit risk mitigation or pricing.
- **[DEV-07] Governance Schemas for Run Outputs:** `GOV.RUN_MEMBERSHIP`, `GOV.RUN_OUTPUT`, `GOV.RUN_REPORTED`, and `GOV.PIPELINE_TIMING` are located in the `GOV` schema, reflecting that published runs are legally binding, immutable audit artifacts.
- **[DEV-08] Scale Profile Entity Ratio:** In the `scale` profile (`--scale 10`), entities and groups are scaled 10× alongside records, preserving a realistic ~6:1 record-to-entity ratio.
- **[DEV-09] Parameterized As-Of Edge View:** `RESOLVE.V_ADMITTED_EDGE_UNDIRECTED` is defined over the per-run working table `RESOLVE.W_EDGE_RUN` rather than directly in `GRAPH`, because Exasol views cannot take dynamic `business_date` or `known_at` parameters.
- **[DEV-10] Simplified Version Views:** `GRAPH.V_LINK_CURRENT` and `GRAPH.V_OWNERSHIP_CURRENT` evaluate replay rules at `CURRENT_DATE` / `SYSTIMESTAMP`. `V_LINK_VERSION` is omitted as redundant.

---

## 3. Matching & Governance Innovations
- **[DEV-11] Tier Column Widening for Funnel Observability:** `RESOLVE.PAIR_SCORE.tier` is widened from `VARCHAR(2)` to `VARCHAR(20)` to retain discarded candidate pairs marked as `DISCARD_ID_CONFLICT` (below T2 threshold) and `DISCARD_LOW_SCORE` (composite similarity below policy `T2_LOW`). This allows `REPORT.V_TIER_COUNTS` to report the entire candidate reduction funnel.
- **[DEV-12] Corroborated Ownership Batching:** Routine registry ownership edges corroborated by a second source (the borrower's reported LOS group code) are grouped into a dedicated sampled review batch (`B-OWN-...`). Only uncorroborated edges (~110 cards including 60 registry-only parents, 10 JVs, and 40 interdependencies) enter individual queue review.
- **[DEV-13] Dedicated Ownership Sampling Policy:** To prevent reviewer fatigue on ~3,500 routine edges, ownership sampling uses `OWN_SAMPLE_PCT = 2` (2%, min 20 pairs $\approx$ 70 reviewed pairs) governed independently from `T0_SAMPLE_PCT = 5` (5%, min 20 pairs $\approx$ 96 pairs). Integer ceiling math (`-(-pct * total // 100)`) is enforced.
- **[DEV-14] Domain Exception for Batch Protection:** `orchestrator.decide.decide()` raises domain exception `BatchProtectedError` if an individual proposal belongs to an active batch. The web route translates this to HTTP 409 Conflict.
- **[DEV-15] Redefined Diamond Benchmark Case:** To respect the mathematical invariant that incoming equity stakes sum to $\le 100\%$, the diamond benchmark case is modeled as Entity X held 60% by Entity B (majority control) plus an approved credit interdependence edge from Entity C ($\ge 50\%$ dependency share). Both B and C belong to the same parent group, and X is aggregated once.
- **[DEV-16] Content-Level Determinism & Python 3.12 Pin:** Parquet manifests record SHA-256 hashes of canonical sorted row values rather than raw file bytes (which vary due to PyArrow system metadata). The project strictly pins `requires-python = ">=3.12,<3.13"` to guarantee identical pseudo-random sequences in `random.sample`. Sets and dicts are strictly sorted before iteration.
- **[DEV-17] Synthetic Data Cleanliness Note:** The generator restricts uncorroborated edges strictly to benchmark cases to keep the live review queue small enough for an interactive demo. Production bank registries exhibit higher background ambiguity requiring ongoing triage.
- **[DEV-18] Public Web Checklist Exclusions:** Standards like OpenGraph images, robots.txt, sitemaps, cookie banners, and public terms are intentionally skipped because Talos is an internal institutional risk console bound strictly to `127.0.0.1`.
- **[DEV-19] Matching Thresholds as Policy Events:** `policy/thresholds.json` is the committed source, but `talos load` writes each threshold to `GOV.POLICY_EVENT`, so a replay reads the value that was in force rather than whatever the file says today. Thresholds are 0-to-1 scores and are exempt from the whole-number percentage rule.
- **[DEV-20] Low-Confidence Verdicts Are Valid but Unsure:** A schema-valid model verdict below `JUDGE_MIN_CONF` is stored with `valid = TRUE` and treated as `unsure`. Only malformed output is stored as `valid = FALSE`, so audit statistics separate model quality from output quality.
- **[DEV-21] No Quoted Results Before Measurement:** The README metrics block shows targets only until `talos eval` generates it. Accuracy is measured against planted ground truth, never asserted.
- **[DEV-22] Disjoint City Pincode Ranges:** City pincode ranges are disjoint within the generator geography, so "a decoy in a different city" always means a different pincode and cannot collide on the pincode blocking key by construction.
