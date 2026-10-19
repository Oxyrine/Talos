# Q&A Cheat Sheet

Short, checkable answers. Regulatory references are to the RBI Large Exposures Framework circular RBI/2018-19/196 of 3 June 2019, with paragraph numbers read from the RBI notification page on 19 Oct 2026. **Re-check them against the original PDF before the finals.** If you are asked something the circular doesn't clearly answer, say so rather than guess.

## 1. Regulation

| Question | Answer | Where in Talos |
|---|---|---|
| What is the group limit? | 25% of the eligible capital base for a group of connected counterparties (para 5.2). The single-counterparty limit is 20%, with up to 5% more in exceptional cases (para 5.1). | `V_GROUP_EXPOSURE.is_breach` is `limit_exposure > capital_base × GROUP_LIMIT_PCT`. The percentage is a policy value. |
| What is the capital base? | Tier 1 capital (para 5.3). The demo uses ₹420 cr, with a mid-period change from ₹400 cr on 1 Sep 2026 to show policy replay. | `GOV.POLICY_EVENT`, key `CAPITAL_BASE_INR`. |
| What is a large exposure? | 10% or more of the eligible capital base (para 4.1), reported under para 4.2. | `is_large`, with `LE_LINE_PCT = 10`. |
| When are counterparties connected? | When one controls the other, which includes more than 50% of voting rights (paras 6.2(a), 6.3), or when they are economically interdependent (para 6.2(b)), for example 50% or more of gross receipts or expenditure (para 6.7). Interdependence applies from 1 April 2020. | OWNERSHIP proposals need a stake above `MAJORITY_MIN_PCT` (50). INTERDEP proposals come from `RAW_LOS.DEPENDENCY` at `INTERDEP_SHARE_MIN` (50) and are always decided by a person. |
| Joint ventures? | Not looked up for this version: check what the circular says about jointly controlled entities before the finals. Talos does not guess, it asks a person to rule. | A `CONTROL_RULING` proposal: SINGLE controller, JOINT control, NONE, or CONNECTED. |

**Don't claim:** that the demo breach breaks a specific statute, that this is RBI-approved, or that it covers NBFCs. We compute against the limit in the framework; whether a breach is reportable is the bank's compliance call.

## 2. Honesty notes (say these before they are asked)

1. **The data is synthetic and cleaner than a real registry.** The generator keeps uncorroborated ownership edges to the planted cases so the individual queue stays small (DEV-17). A real feed has far more, which is why the queue is ranked by live impact on the group figure.
2. **Why the holding company is "hidden".** The ₹36.4 cr was on the books, in a separate group at 8.7%. What was missing was the ownership link that makes it part of Sunrise.
3. **The evaluator's reviewer is an "accept the recommendation" oracle**, not a person, and it never reads the ground truth. Real reviewers can do better or worse.
4. **No model is used in the demo.** The judge is provider-swappable and defaults to a stub (DEV-03, DEV-31).
5. **Dev numbers are in-sample.** Thresholds were tuned on dev. The unseen test set is generated after the freeze and reported as it comes out.

## 3. Numbers on the dev data (`eval/results/dev.json`)

| Metric | Result |
|---|---|
| Candidate pairs / reduction | 731,543 pairs, 99.27% of the 25,000 × 4,000 space removed |
| Blocking recall | 99.88% |
| ER precision / recall | 1.00 / 0.998 |
| Wrong-ID records routed to T3 | 12 of 12 |
| Decoys wrongly merged | 0 of 30 |
| Hidden breaches found / false breaches | 6 of 6 / 0 |
| Understated exposure, before → after | ₹246.7 cr → ₹0 |
| Replay hash matches | 100% |
| Resolved without a model | 95.6% |

## 4. Technical

**Why Exasol and not an external graph or ML service?** Borrower data stays in the database. Matching and grouping are set operations the engine parallelises. Reproducibility comes from append-only event tables plus a recorded manifest, so there is no separate system to keep in step.

**What in Exasol is load-bearing?** `EDIT_DISTANCE`, `SOUNDEX`, `COLOGNE_PHONETIC`, `HASH_SHA256`, regular expressions, `QUALIFY`, `MERGE` in a loop for label propagation, `CONNECT BY NOCYCLE` for the ownership tree, `GROUPING SETS` for the cube, and schema-level grants for the governance rules. The README maps each to its file.

**How is a run made reproducible?** A run stores its business date, `known_at`, the load IDs and policy event IDs it used, and the code version. The output hash is SHA-256 over sorted canonical lines (`M|…` for membership and `O|…` for output rows, amounts to two decimals, no run IDs or timestamps). `talos replay` rebuilds the run from that manifest and compares hashes.

**Why integer sample sizes?** Sample size is `min(batch, max(min, ceil(pct × batch / 100)))` in integer arithmetic, and the sample is `random.Random(seed).sample(sorted ids, k)` with the seed shown on screen. The server re-derives the sample from the seed, so a reviewer can't choose which pairs to check.

**How is a wrong merge prevented?** An ID that conflicts with the name is T3 and can't be batch-approved. A rejection writes a do-not-link event over all time. A later run re-proposes only if the evidence changes.

**What are the limits?** Collateral carries no exposure by policy. One registry feed. Label propagation is plain SQL because Python UDFs failed the Nano probe. A cycle of owners with no outside parent becomes one group flagged `CYCLE_HEADED`, headed by its largest exposure.
