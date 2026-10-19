# Demo Script

Two scripts: the 3-minute submission video and the 15-minute finals walkthrough with answers to the questions we expect.

**Figures.** The Sunrise numbers come from the generator's hero group and are asserted by `tests/test_generator.py`. Capital base is ₹420 cr, so the 10% line is ₹42 cr and the 25% limit is ₹105 cr.

| Step | What has been approved | Reported (loan book) | Talos group figure |
|---|---|---|---|
| 0 | Nothing | ₹40.0 cr (9.5%) | not linked yet |
| 1 | Exact-ID record links batch | ₹40.0 cr | ₹31.2 cr (7.4%), the head company alone |
| 2 | Corroborated ownership batch | ₹40.0 cr | ₹58.2 cr (13.9%), over the 10% line |
| 3 | The hero's fuzzy-match cards, and the wrong-PAN card rejected | ₹40.0 cr | ₹75.6 cr (18.0%) |
| 4 | The single Sunrise Industries → Sunrise Finvest ownership card | ₹40.0 cr | ₹112.0 cr (26.7%), over the 25% limit |

Sunrise Finvest and its two operating subsidiaries are a separate ₹36.4 cr group (8.7%) until step 4, so each side looks compliant on its own.

> **Before recording:** run the whole flow once on live Exasol (`uv run talos demo`) and replace every `<…>` below with what the screen shows. The sample sizes, amounts and similarity scores depend on the generated data and were not fixed when this was written. Note that the exact-ID record batch is large on the dev data (about 20,000 records resolve by exact ID, so a 5% sample is about 1,000 pairs, see DEV-36 in `DECISIONS.md`). If that is too long to review on camera, lower `T0_SAMPLE_PCT` in policy or show the first screen of the sample and say so.

---

## Part 1: 3-minute video

Target 2:55 to 3:00. Dark theme, 1080p.

### 0:00 – 0:35  The group nobody can see
**Screen:** Exposure board (`/board`). Point at the review-position panel (hidden exposure, limit breaches) and then the Sunrise row: reported **₹40.0 cr, 9.5%**, compliant.

> The RBI Large Exposures Framework caps a bank's exposure to a group of connected borrowers at 25% of its Tier 1 capital, and requires anything at 10% or more to be reported. Here the loan system says Sunrise is ₹40 crore, under 10% of a ₹420 crore capital base. But the bank also holds Sunrise paper in treasury and guarantees in trade finance, under names that don't match, and some of Sunrise sits in a holding company nobody has linked to it. Talos finds those links, inside Exasol, and shows what the group really owes.

### 0:35 – 1:15  Review a sample, not 5,000 rows
**Screen:** Review queue (`/queue`). Open the **exact-ID record links** batch banner, scroll the sample (`<sample size>` pairs, seed shown), choose Approve for each, submit. Do the same for the **corroborated ownership** batch. Return to the board: Sunrise now **₹58.2 cr (13.9%)**, past the 10% mark, hidden exposure **+₹18.2 cr**.

> Most links are routine: the PAN matches exactly, or two sources agree on ownership. Talos groups those into batches and draws a random sample from a seed shown on screen. The reviewer decides every pair in the sample, and one rejection fails the whole batch. Once approved, Exasol rebuilds the groups in SQL, and Sunrise crosses the 10% line.

### 1:15 – 1:55  The hard cases get a human
**Screen:** Queue, individual cards. Open the Sunrise guarantee card whose book record has no PAN: side-by-side names, `<similarity>`, same pincode. Approve. Then the card where the book record carries **another company's PAN**: red conflict chip, tier T3. Reject.

> For records with no ID, Talos scores name distance, phonetic match and pincode in the database and shows the evidence side by side. This card matches on name and pincode, and the reviewer approves it. This one is the trap: the record carries a PAN belonging to a different company. An ID that disagrees with the name is never trusted, and a rejection writes a permanent do-not-link entry to the audit log.

### 1:55 – 2:35  The holding company
**Screen:** Queue, the **Sunrise Industries → Sunrise Finvest** ownership card. The headline reads that approving moves the group from 18.0% to 26.7% and crosses the 25% limit. Approve. Board: **₹112.0 cr (26.7%)**, status **Limit breach**. Open the lineage page and show the ownership tree and the rows behind the figure.

> Sunrise Industries owns all of a holding company, Sunrise Finvest, which already carries ₹36.4 crore of loans under its own group. Only a registry filing says who owns it. One approval merges the two groups, and Sunrise goes from ₹40 crore to ₹112 crore, over the ₹105 crore limit. Every rupee traces to a source row, the person who approved the link, and when.

### 2:35 – 3:00  Prove it
**Screen:** Audit (`/audit`). Click **Verify replay** on the latest run: the match badge with its hash. Close on the title card: *Talos, group exposure under RBI limits, computed inside Exasol.*

> Each published run records the data versions, policy and code it used, plus a hash of its output. An auditor can replay any run and check the hash matches. The matching and grouping run in the database, and in this demo no model is involved in any decision.

---

## Part 2: 15-minute finals, likely questions

**1. "HoldCo's ₹36.4 cr was already on your books. In what sense is it hidden?"**
It was on the balance sheet, but under a different group, at 8.7% of capital. The limit applies to the group of connected counterparties (RBI/2018-19/196 para 5.2), so what was hidden was the link, not the loan. Reported 9.5% and 8.7% look fine separately and add up to 26.7% together. (Reported ₹40.0 cr to ₹112.0 cr is +₹72.0 cr for the group; ₹35.6 cr of that is the treasury and guarantee rows, and ₹36.4 cr is the holding company.)

**2. "Why do this in Exasol rather than export to a graph database?"**
Three reasons. The data is non-public borrower data, so it never leaves the database. Runs are reproducible as of a business date and a known-at time, which we implement with append-only event tables and the replay rule. And the heavy steps, blocking and label propagation, are set operations the engine parallelises. On the dev data blocking cuts 25,000 × 4,000 possible pairs to 731,543 candidates (a 99.27% reduction) while keeping 99.88% of the true pairs.

**3. "Won't human review overwhelm credit officers?"**
Review effort is spent where it matters. On the dev data 95.6% of tiered pairs are T0 or T1, and T0 is reviewed as a sample. The remaining cards are ordered by live impact, so ones that cross the 25% limit or the 10% line come first. We report reviewer load and are open that the sample on dev is large (DEV-36); the sample percentage is a policy value, not code.

**4. "How do you know the matching is accurate?"**
The generator plants known cases (decoys, wrong-PAN records, hidden parents) and writes the truth to tables the pipeline cannot read. `talos eval` scores against it. On dev: precision 1.00, recall 0.998, 12 of 12 wrong-ID records caught, 0 of 30 decoys merged, 6 of 6 hidden breaches found, 0 false breaches. Thresholds are tuned on dev only and frozen before the unseen test set is generated; the test result goes in the README whatever it is. Say plainly that the data is synthetic and cleaner than a real registry (DEV-17).

**5. "Where does an LLM fit?"**
It is optional and not used in this demo. The grey band (T2) can be sent to a model through a provider-swappable function, but the model never writes to the database, and a model verdict can only demote a pair to a human, never approve it. With the default stub provider, T2 pairs stay in the queue marked "no model verdict".

**6. "What can't it do?"**
It does not price credit risk or credit-risk mitigation (collateral carries zero exposure by policy). It reads one registry feed. JV rulings need a human. Python UDFs failed the Nano probe, so label propagation is plain SQL, which is correct but not the fastest option at very large scale.
