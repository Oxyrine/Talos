# Talos

[![CI](https://github.com/Oxyrine/Talos/actions/workflows/ci.yml/badge.svg)](https://github.com/Oxyrine/Talos/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/downloads/release/python-3120/)

A lender's loan, treasury, guarantee and collateral books record the same corporate borrowers under different names and IDs, and none of them shows who owns whom. Group exposure (RBI: 25% of eligible capital for a group of connected counterparties, with 10% as the large-exposure line) is therefore understated. A missed ownership link is an unreported limit breach.

Talos resolves records to legal entities and links entities into groups, entirely inside Exasol. It computes on- and off-balance-sheet group exposure and publishes nothing until a human has recorded an immutable decision. Every figure traces to a source row and a decision, and every report can be replayed and verified against its cryptographic output hash.

---

## The Problem & The Regulation

In corporate banking, credit exposure is fragmented across disparate books:
- **Loan Origination System (LOS)**: Term loans, working capital lines, cash credit facilities.
- **Treasury Management**: Commercial paper (CP), non-convertible debentures (NCD), corporate bonds.
- **Trade & Guarantees**: Financial guarantees, performance guarantees, letters of credit.
- **Collateral Management**: Share pledges, asset mortgages.

Under the Reserve Bank of India (RBI) Large Exposures Framework (LEF):
- A lender's exposure to a **Group of Connected Counterparties** must not exceed **25% of the eligible capital base**.
- Any exposure **at or above 10% of eligible capital** is a large exposure and is reported as such.

When companies borrow under different trade styles, minor typographical aliases, or via opaque intermediate holding companies, fragmented internal data hides the true consolidated exposure. A lender with a ₹420 crore capital base and a ₹105 crore regulatory limit (25%) may see a borrower reported at only ₹40 crore (9.5%), while their true group exposure sits at ₹112 crore (26.7%)—an undetected regulatory breach.

---

## Why Exasol is Load-Bearing

Talos executes entity resolution, graph label propagation, exposure cube aggregation, and historical point-in-time time-travel entirely within Exasol:

| # | Exasol Capability | Usage in Talos | Planned SQL file |
|---|---|---|---|
| 1 | `EDIT_DISTANCE`, `SOUNDEX`, `COLOGNE_PHONETIC` | In-database phonetic and string distance scoring across every candidate pair | `sql/10_standardise.sql`, `sql/40_score_tier.sql` |
| 2 | `HASH_SHA256` | Token hashing (PAN, CIN, LEI, DINs) preserving PII privacy across matching pipelines | `sql/20_id_tokens_exact.sql` |
| 3 | `REGEXP_LIKE` & `REGEXP_REPLACE` | High-throughput name standardisation, legal suffix stripping, and PAN/CIN format validation | `sql/10_standardise.sql` |
| 4 | `QUALIFY` with Window Functions | De-duplicating latest snapshot loads and selecting candidate pairs per partitioning window | `sql/10_standardise.sql`, `sql/70_propose_record_links.sql` |
| 5 | `MERGE` inside iterative loops | Synchronous in-database Label Propagation for deterministic connected component group discovery | `sql/52_components_pass.sql` |
| 6 | `CONNECT BY NOCYCLE`, `SYS_CONNECT_BY_PATH` | Cycle-safe hierarchical tree traversal for ownership lineage reporting | `sql/81_report_views.sql` |
| 7 | `GROUPING SETS`, `ROLLUP` | Multidimensional OLAP exposure cube calculation across groups, entities, and books | `sql/81_report_views.sql` |
| 8 | Row-level `DISTRIBUTE BY` | Colocating candidate pairs and component working tables across cluster nodes | `sql/03_stage_resolve.sql` |
| 9 | Role-Based Access Control & Views | Enforcing immutable evidence: no role holds `UPDATE` or `DELETE` on raw data, graph events, or governance tables | `sql/06_roles_grants.sql` |

---

## Architecture: 5 Layers, 1 Human Gate

```
  [Raw Books: LOS, Treasury, Guarantee, Collateral, MCA Registry]
                                │
                                ▼
  [Layer 1: Standardise & Blocking (Exact ID Tokens + Phonetic Passes)]
                                │
                                ▼
  [Layer 2: Scoring & Tiering (T0 Exact, T1 Strong, T2 Grey, T3 Conflict)]
                                │
                                ▼
  ================== THE HUMAN GOVERNANCE GATE ==================
  [Layer 3: Decision Engine (Sampled Batches & Live Impact Queue)]
  • Reviewer verifies T0 Record Links batch
  • Reviewer verifies Corroborated Ownership batch
  • Reviewer decides individual T1 cards & uncorroborated edges
  • Immutable decision log written (APPROVE / REJECT / DNL)
  ================================================================
                                │
                                ▼
  [Layer 4: Graph Propagation & Group Formation (Exasol MERGE)]
                                │
                                ▼
  [Layer 5: Regulatory Exposure Cube & Cryptographic Replay]
```

---

## Project Status

Scaffold stage (11 Oct 2026). Done: repository layout, frozen `CONTRACT.md`, generator vocabulary, CI. Not built yet: the generator world and planted cases, the SQL pipeline, the orchestrator, the web console and the evaluator. The CLI subcommands only print a message until they are implemented.

---

## Quick Start

```powershell
# 1. Clone repository
git clone https://github.com/Oxyrine/Talos.git
cd Talos

# 2. Run the end-to-end demo (generates dev world, loads Exasol, runs pipeline, and starts UI)
uv run talos demo   # NOT IMPLEMENTED YET: currently a stub, see Project Status
```

Once the demo is implemented, navigate to `http://127.0.0.1:8000` to access the interactive review console.

---

## Benchmark Metrics

<!-- METRICS:START -->
Not yet measured. This block is generated by `talos eval` against planted ground truth once the pipeline exists; until then only the targets are stated.

| Metric | Dev | Test (unseen) | Target |
|---|---|---|---|
| Understated group exposure, after Talos vs before | not measured | not measured | at most 5% of the before figure |
| Overstated group exposure | not measured | not measured | near zero, every rupee explained |
| Missed breaches / false breaches | not measured | not measured | 0 of 6 / 0 |
| Blocking recall | not measured | not measured | 0.99 |
| Entity-resolution precision / recall | not measured | not measured | 0.99 / 0.97 |
| ID-name conflicts routed to T3 | not measured | not measured | all 12 |
| Decoy false merges | not measured | not measured | 0 of 30 |
| Replay fidelity (output hash match) | not measured | not measured | 100% |
| Resolved without the model | not measured | not measured | 95% |
<!-- METRICS:END -->

---

## Synthetic Dataset & Known Limitations

All data used in Talos is synthetic, generated deterministically using pure Python (`data/generator/`) with no third-party fake data packages:
- **Scope**: 400 groups, 4,000 corporate entities, and 25,000 identity records across 4 lending books.
- **Noise Families**: Systematic abbreviation expansion, optical character recognition (OCR) errors, typographical errors, and dropped tax identifiers.
- **Known Limitations**:
  - *Controlled Uncorroborated Edges*: The generator keeps uncorroborated edges to the planted cases so the individual queue stays small enough to demo. Real-world corporate registry feeds have many more uncorroborated edges that require ongoing workflow triage.
  - *Perimeter Aggregation*: The hero group unmasks ₹36.4 crore from an intermediate holding company that was already present on the balance sheet under a separate group code. The error caught is an aggregation boundary failure under RBI rules, not an omitted loan transaction.

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
