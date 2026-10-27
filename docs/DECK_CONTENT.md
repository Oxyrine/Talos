# Pitch deck content

Thirteen slides plus a backup appendix, written to be pasted into any slide tool. Each slide has the **headline** (the one thing the audience should take away), the **on-slide content** (short, since the slide is read in seconds), a **visual**, and **speaker notes**.

All figures are from the dev run (`eval/results/dev.json`) and the live walkthrough in `docs/VOICEOVER.md`. Items marked **[fill]** are values that did not exist when this was written. **Do not present a number that is not in the repo.**

Suggested look: dark background, one accent colour for "breach", a second for "large exposure", large numerals, no clip art. Keep the Sunrise figures the same colour on every slide they appear.

Length: 3-minute video uses slides 1–2, 4, 8, 9 as stills if wanted. The finals talk uses all of them in about 8 minutes, leaving time for questions.

---

## 1. Title

**Headline:** Talos: connected exposure, matched, grouped and proven inside Exasol.

**On slide**
- ExaThon India 2026 · Track 01
- Team: **[fill names and roles]**
- github.com/Oxyrine/Talos · MIT licence

**Visual:** the Talos mark, and the board's capital-footprint chart for Sunrise with its 10% and 25% markers.

**Notes:** One sentence: "We find the borrower groups a bank's own systems can't see, and show what they owe against the RBI limit."

---

## 2. The problem, in one number

**Headline:** The loan system says ₹40 crore. The group owes ₹112 crore.

**On slide**
- *A lender's loan, treasury, guarantee and collateral books record the same corporate borrowers under different names and IDs, and none of them shows who owns whom. Group exposure is therefore understated, and a missed ownership link is an unreported limit breach.*
- Two big numbers side by side: **₹40.0 cr · 9.5% of capital** (what is reported) → **₹112.0 cr · 26.7%** (the true group)
- A line under them: capital ₹420 cr · 10% line ₹42 cr · 25% limit ₹105 cr

**Visual:** a horizontal bar of capital with the 10% and 25% marks; a small bar at 9.5% in grey, a long bar at 26.7% in the breach colour past the 25% mark.

**Notes:** Sunrise is a synthetic company in our benchmark world, and the numbers are exact: the generator asserts them to the paisa. The point is that nobody lied. Every system's number is correct for the records it can see.

---

## 3. The rule and why the group figure is wrong

**Headline:** The limit is on the group. The data is on the entity.

**On slide, left (the rule)**
- 25% of eligible capital for a group of connected counterparties
- 10% or more is a large exposure and is reported
- Capital base is Tier 1 capital
- Source: RBI Large Exposures Framework, circular RBI/2018-19/196, 3 Jun 2019 (paras 5.2, 4.1, 5.3)
- Connected = one controls the other (over 50% of voting rights) or they depend on each other economically

**On slide, right (why the books miss it)**
1. Records share no keys: many treasury, guarantee and collateral rows carry no PAN or CIN
2. The loan system's group map is updated once a year
3. Nothing in any lending book says who owns whom

**Visual:** four book icons (LOS, TSY, GTE, COL) feeding a question mark.

**Notes:** Re-check the paragraph numbers against the circular PDF before presenting. The 20% single-counterparty limit and the interdependence tests are in the same circular if a judge asks.

---

## 4. What Talos does

**Headline:** Five layers in the database, one human gate.

**On slide:** the diagram from the README, redrawn:

1. **Standardise and block**: clean names, hash IDs, generate candidate pairs
2. **Score and tier**: T0 exact ID · T1 strong name + pincode · T2 grey band · T3 conflict
3. **THE HUMAN GATE**: a person records an immutable decision
4. **Form groups**: label propagation over confirmed edges, in SQL
5. **Exposure and replay**: group exposure cube, output hash, replay

Under it: *Nothing is published until a person has decided. Tiers decide how a match is shown, never whether a person is needed.*

**Visual:** a vertical flow with the gate drawn as a bar across the flow.

**Notes:** The gate is the product. The matching is fast; trust is the hard part.

---

## 5. Matching is a SQL problem

**Headline:** 100 million possible pairs down to 731,543 in about five seconds.

**On slide** (a funnel)
- 25,000 book records × 4,000 registry companies = **100,000,000** possible pairs
- Exact-ID pass (hashed PAN, CIN, LEI) + three blocking passes (phonetic name + state, phonetic name + pincode, name prefix)
- **731,543 candidates · 99.27% removed**
- **99.88%** of the true pairs survive blocking
- **95.6%** of scored pairs settle at T0 or T1 without any model

Footnote: *Identifiers are hashed in SQL; a raw PAN never leaves the database.*

**Visual:** funnel with three stages and those three numbers large.

**Notes:** Blocking timing is about 5 to 6 seconds on Nano on a laptop (dev data; see the pipeline screen). Scoring uses EDIT_DISTANCE, SOUNDEX and COLOGNE_PHONETIC inside Exasol.

---

## 6. The human gate

**Headline:** Reviewers check samples and decide the hard cases, with the impact in front of them.

**On slide** (four columns)
- **Sampled batches (T0):** exact-ID links and corroborated ownership edges, reviewed by a seeded random sample. The server re-derives the sample from the seed. One rejection fails the batch.
- **Impact-ranked cards (T1):** each card says what approving does: "Sunrise group 18.0% → 26.7%, crosses the 25% limit"
- **Conflicts (T3):** an ID that disagrees with the name is never trusted. Reject, and a do-not-link is recorded for good
- **Joint ventures:** single controller, joint, none, or connected holders: a person rules

Under it: *Every decision is an append-only event with a reviewer, a reason and a timestamp.*

**Visual:** one real queue card (the 18.0% → 26.7% card), cropped.

**Notes:** The batch screen has an "Approve all in this sample" button that pre-ticks every pair, and the reviewer can flip any to Reject. The form still posts one verdict per sampled pair. Say this yourself before a judge asks.

---

## 7. Groups, formed in the database

**Headline:** Label propagation, an ownership tree and an exposure cube: all SQL.

**On slide**
- **Groups:** a `MERGE` statement repeated until nothing changes; over confirmed ownership and interdependence edges only. Cycles, diamonds and joint ventures handled and tested
- **Ownership tree:** one `CONNECT BY NOCYCLE` query, cycle-safe, shown on the lineage screen
- **Exposure:** `GROUPING SETS` cube by group, entity, book and product
- **As-of:** every figure can be rebuilt as of any business date and known-at time

**Visual:** the Sunrise ownership tree from the lineage screen (Industries → 74% Holdings → 100% Finvest, plus subsidiaries).

**Notes:** Collateral carries zero exposure by policy and is used only for its identifiers. Python UDFs failed the probe on Nano, so all of this is plain SQL.

---

## 8. The Sunrise story, five approvals

**Headline:** Five approvals take Sunrise from ₹40 crore to a limit breach.

**On slide:** a step chart with the 10% (₹42 cr) and 25% (₹105 cr) lines.

| Step | Approved | Sunrise group |
|---|---|---|
| 0 | nothing | reported ₹40.0 cr (9.5%) |
| 1 | exact-ID record batch | ₹31.2 cr (7.4%): the head company alone |
| 2 | ownership batch | ₹58.2 cr (13.9%): **over the 10% line** |
| 3 | fuzzy-match cards; wrong-PAN card rejected | ₹75.6 cr (18.0%) |
| 4 | one card: Sunrise Industries → Sunrise Holdings | **₹112.0 cr (26.7%): over the 25% limit** |

Callout: *+₹72.0 cr the loan book could not see.*

**Visual:** the step chart. Screenshots of the board at steps 0 and 4 beside it.

**Notes:** Step 1 is lower than reported because only the head company's own exposure is linked yet; Talos can show less than the loan book as well as more. The holding company group (₹36.4 cr, 8.7%) looked compliant on its own until step 4.

---

## 9. Proof

**Headline:** Every figure traces to a row, a reviewer and a replayable run.

**On slide**
- Click any number: group → entity → source rows, each with the proposal, the decision, who decided and when
- Each run stores its data versions, policy values and code version, and a SHA-256 of its output
- **`talos replay --all`: every run reproduces its hash**
- No role can update or delete evidence: grants forbid it, and a CI test checks it

**Visual:** the audit screen with the green "Replay match" badge and the first digits of a hash.

**Notes:** An auditor can ask "what did you know on the quarter-end date" and get the same answer, because the "as of" rule is part of the SQL.

---

## 10. Results (dev data)

**Headline:** Every planted breach found, no false merges.

**On slide** (table, dev profile)

| | Result |
|---|---|
| Hidden breaches found / false breaches | **6 of 6 / 0** |
| Understated exposure, before → after | **₹246.7 cr → ₹0** |
| Record-to-entity precision / recall | **1.00 / 0.998** |
| Wrong-ID records routed to T3 | **12 of 12** |
| Look-alike decoys wrongly merged | **0 of 30** |
| Replay hash matches | **100%** |
| Unseen test set | **[fill from `eval/results/test.json`, whatever it shows]** |

Footnote: *Synthetic data with planted ground truth. Thresholds tuned on dev only, then frozen before the test set was generated.*

**Visual:** the table, with the test column visibly present.

**Notes:** Say that dev numbers are in-sample. If the test numbers are worse, show them anyway; judges trust a team that reports its own misses (`misses_test.md`). Live timings (dev): board 1.8 s, a decision 4 to 6 s (it waits for a fresh run), the ownership batch of 3,535 edges about 7 s.

---

## 11. Why Exasol is load-bearing

**Headline:** Remove Exasol and the product stops existing.

**On slide** (compact table)

| Exasol capability | What it does in Talos |
|---|---|
| `EDIT_DISTANCE`, `SOUNDEX`, `COLOGNE_PHONETIC` | scores every candidate pair next to the data |
| `HASH_SHA256`, regexes | hashed identifiers, name standardisation, format checks |
| `QUALIFY` + window functions | latest snapshot per record, best match per record |
| `MERGE` in a loop | label propagation: group formation |
| `CONNECT BY NOCYCLE` | cycle-safe ownership tree |
| `GROUPING SETS` | exposure cube |
| Schema grants | append-only evidence; reader sees reports only |

Footer: *Nothing leaves the database.*

**Visual:** the table, with each row linking to its `sql/` file in the repo.

**Notes:** If asked "why not a graph database": non-public borrower data stays inside; the bitemporal as-of rule is plain SQL over append-only events; and the heavy steps are set operations the engine already parallelises.

---

## 12. Honest limits and what is next

**Headline:** What Talos does not do yet.

**On slide, limits**
- Data is synthetic and cleaner than a real registry. We kept uncorroborated edges to the planted cases so the queue is demoable
- The evaluator's reviewer is an "accept the recommendation" oracle, not a person
- No model is used in the demo: the grey band (T2) stays with a human. A model judge is wired in behind a swappable interface and can only demote a pair to a human, never approve it
- Collateral gives identifiers only (zero exposure); one registry feed; commercial banks' framework only, not NBFCs
- The exact-ID sample is large (about 1,000 pairs); it is a policy percentage you can tune

**On slide, next**
1. A model judge for the grey band, behind the existing guardrails
2. Relationship reader over sanction notes (proposals only, with quoted evidence)
3. Question-answering over the report views for a risk officer, via Exasol's MCP server
4. The NBFC framework and RBI reporting formats

**Visual:** two plain columns, no icons.

**Notes:** Read the limits aloud. This slide is where the Q&A gets easier.

---

## 13. Close

**Headline:** A group limit is only as good as the links behind it.

**On slide**
- Talos finds the links, shows the impact, records the decision and proves the result.
- Repo: github.com/Oxyrine/Talos · `uv run talos demo`
- Team and contact: **[fill]**

**Visual:** the Sunrise board row at ₹112.0 cr, Limit breach.

**Notes:** End on the breach. Then stop talking.

---

# Appendix (backup slides)

**A1. Scoring criteria map**

| Criterion (weight) | Where the evidence is |
|---|---|
| Exasol use (25%) | slide 11; `sql/` (24 files); `docs/PROBE.md` |
| Innovation (25%) | the human gate with live impact; sampled batches; append-only replay |
| Technical quality (20%) | tests and CI (unit + Exasol job); `CONTRACT.md`; role grants |
| UX (15%) | board, queue card, lineage; one-click path from number to source row |
| Docs and reproducibility (10%) | README, RUN_GUIDE, deterministic generator, `talos replay` |
| Open source (5%) | MIT, public repo |

**A2. Architecture:** the schemas (`RAW_*`, `STAGE`, `RESOLVE`, `GRAPH`, `GOV`, `REPORT`, `TRUTH`) and the five database roles, with who can write where.

**A3. Capability probe:** `docs/PROBE.md` (14 of 15 pass; Python UDF fails on Nano, so the product uses none).

**A4. Pipeline timings:** the `/pipeline` screen for dev; **[fill]** the scale-profile run (250,000 records) if it has been done. `docs/VOICEOVER.md` quotes about 11.5 million candidate pairs and under 2.5 minutes for blocking, scoring and grouping at that size. **Confirm that against a real scale run before saying it.**

**A5. Likely questions:** see `docs/DEMO_SCRIPT.md` part 2 and `docs/QA.md`.
