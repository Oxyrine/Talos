# Talos: 3-minute video script and voice-over

A recording sheet for the ExaThon submission video. Every click, number and on-screen detail below was rehearsed on a live Exasol dev load (20 Oct 2026, business date 2026-09-30, capital ₹420 cr, 10% line ₹42 cr, 25% limit ₹105 cr). The narration makes the case that **Exasol does the work**, and every claim about the database is something Talos runs in SQL or measured; the sources are at the end.

Narration is 404 words, which is 2:42 at 150 words a minute. That leaves room to pause on the figures and the title card. Record the screen first, cut the waits, then read the narration over it.

---

## Before you record

1. **Start from step 0.** Open a terminal in the repo root (branch `main`) and run:

   ```bash
   UV_SYSTEM_CERTS=1 uv run talos demo
   ```

   It wipes the Talos schemas, regenerates the dev data, loads and matches it (about 2½ minutes), then serves the console at **http://127.0.0.1:8000**. Record from that local address, which is faster than the public tunnel. Redo this any time you want a clean take.
2. **Sign in** as `Demo Approver`. The password is in `.talos/demo-reviewer.txt`.
3. **Check you are at step 0** before pressing record:
   - `/board` says **"5378 group perimeters awaiting resolution"** and the "Unmasked across the book" tile reads ₹0.0 cr.
   - `/queue` shows two batch banners: *Corroborated Ownership Edges* (3,535 connections, 71 pairs in sample) and *Exact-ID Record Links* (20,288 connections, 1015 pairs in sample), and "Resolution proposals 4813".
4. **Browser:** full screen, 1080p, zoom 100%. Close other tabs. Sign-in and the console run on `127.0.0.1`, so nothing is visible outside your laptop.
5. **One take is a one-way trip.** Each approval is permanent (append-only). If you fumble, rerun step 1 and start again; do not try to undo.

**Cuts to expect.** Each approval waits for a fresh report run. Cut these in the edit: the exact-ID batch about 9 s, the ownership batch about 7 s, each card about 5 s, the final ownership card about 8 s, Verify replay about 3 s.

**Where Sunrise is.** The board lists thousands of groups and Sunrise is not near the top, so use the **FIND** box on the board and on the queue and type `sunrise`. On the board it shows only Sunrise rows; the tiles keep their book-wide totals, so **point at the Sunrise row, never at the "Hidden exposure unmasked" tile**. The loan book spells it `Sunrise Indu5tries Limited` until it is linked. That is the book's own typo, so leave it and say so.

---

## Scene 1 · 0:00 – 0:30 · The group nobody can see

**Do:** `/board`. Click the **FIND** box, type `sunrise`, press **Search**. Two rows appear:

| Row | Reported | Status |
|---|---|---|
| Sunrise Indu5tries Limited | ₹40.0 cr | Pending |
| Sunrise Holdings Ltd | ₹36.4 cr | Pending |

Hover the 10% and 25% markers on the gauge. Say the figures: ₹40.0 cr is 9.5% of ₹420 cr, ₹36.4 cr is 8.7%.

> Indian banks can lend a group of connected companies at most twenty-five percent of their capital, and anything over ten percent must be reported. This bank has four hundred and twenty crore. Its loan system shows Sunrise at forty crore, and a separate holding company at thirty-six. Both compliant, because nobody has linked them.
>
> Talos finds those links, and it does every step of it inside Exasol, the in-memory analytic database.

## Scene 2 · 0:30 – 1:10 · A hundred million comparisons, answered in SQL

**Do:**

1. **Queue** (`/queue`) → on the *Exact-ID Record Links* banner click **Review sample**. The page lists the 1,015 pairs: names side by side, `ID: matches registry`, and a seed number by the submit button. Scroll a few rows (10 seconds at most), then click **Approve all in this sample**. The counter beside it reads *1015 approved, 0 rejected, 0 undecided of 1015*. Click **Submit Batch Decision & Sign Audit Trail** (the justification is pre-filled). Wait about 9 s (cut it). You land back on the queue.
2. *(Optional beat, 5 s.)* `/board?q=sunrise`: Sunrise is now **₹31.2 cr (7.4%)**, Holdings ₹26.0 cr (6.2%). Talos can show less than the loan book as well as more.
3. **Ownership banner** → **Review sample**. The columns read *Holder (parent)* and *Held (subsidiary)* with the stake and CIN under each. 71 pairs. **Approve all in this sample** → **Submit**. About 7 s.
4. `/board?q=sunrise`: **Sunrise Industries Limited: reported ₹40.0 cr → resolved ₹58.2 cr, +₹18.2 cr, 13.9% of capital, Large exposure.** Sunrise Holdings is now **₹36.4 cr, 8.7%** with 2 members.

> Twenty-five thousand book records against four thousand registry companies is a hundred million possible pairs. Exasol cuts that to seven hundred thousand candidates in about five seconds, and keeps ninety-nine point nine percent of the true matches. Identifiers are hashed in SQL, so a raw PAN never leaves the database.
>
> Routine links go into batches. The reviewer checks a seeded sample, every verdict is stored pair by pair, and one rejection fails the whole batch. Then Exasol rebuilds every group with a single MERGE statement, repeated until nothing changes. Sunrise is now fifty-eight crore, past the ten percent line.

## Scene 3 · 1:10 – 1:50 · The hard cases get a human

**Do:** `/queue`, **FIND** `sunrise`, Search. Eight cards. **Leave the first one alone** (the ownership card at ₹36.4 cr; you will use it in Scene 4). Then:

| Card | Book record | Tier | Impact | On the card |
|---|---|---|---|---|
| `P-bb8e279d02b9` | GTE guarantee, *Sunrise Industries Ltd* | T1 | ₹2.7 cr | book name `Ltd`, registry name `Limited`, same pincode (STRONG_NAME_PIN) |
| `P-90563ac9dab8` | GTE guarantee, *Sunrise Textiles Private Limited* | **T3**, ID_NAME_CONFLICT | ₹2.7 cr | titled **Bhopal Industries Limited**: the PAN belongs to a different company |
| `P-e31d9cf52535`, `P-400a8dfe6ad2`, `P-777802b21aea`, `P-22753a165b27`, `P-d547782f4df7` | TSY and GTE records of Sunrise companies | T1 | ₹6.3 / 2.8 / 2.7 / 1.5 / 1.4 cr | same name and pincode |

1. **Approve `P-bb8e…`**: type `Same name and pincode.` in the *Decision rationale* box (a reason is required on every card), click **Approve link**. Show the evidence for a few seconds first.
2. **Reject `P-9056…`**: point at the **T3** tier and the **ID_NAME_CONFLICT** label, then at the two names: the book says Sunrise Textiles, the PAN matches Bhopal's registry entry. Reason: `The PAN on this record belongs to a different company.` Click **Reject link**.
3. **Approve the other five** with the same reason. Jump-cut: this is about 40 s of typing and waiting.
4. `/board?q=sunrise`: **Sunrise Industries Limited ₹75.6 cr, 18.0%, +₹35.6 cr**, Large exposure.

> Records with no ID are scored with Exasol's built-in name functions, Soundex, Cologne phonetic and edit distance, right next to the data. This guarantee matches on name and pincode. Approve.
>
> And this is the trap: a Sunrise Textiles guarantee carrying another company's PAN. An ID that disagrees with the name is never trusted, and the rejection becomes a permanent do-not-link. Sunrise is now seventy-five crore, eighteen percent.

## Scene 4 · 1:50 – 2:20 · The holding company

**Do:** `/queue`, **FIND** `sunrise`: the ownership card `P-4ddd8057db89` is now the only Sunrise card left. Its banner reads **"Crosses the group limit."** and **18.0% → 26.7% of capital**, impact **₹36.4 cr**. The evidence: holder *Sunrise Industries Limited* (CIN L58060RJ1984PLC352987), equity holding **74%**, held *Sunrise Holdings Limited* (CIN L87707RJ1994PLC825391), filing date 2015-08-14.

Type `Registry filing shows 74% ownership of Sunrise Holdings.` and click **Approve link**. About 8 s (cut).

Then `/board?q=sunrise`: **one** row, *Sunrise Industries Limited*, 9 members, **₹40.0 cr → ₹112.0 cr, +₹72.0 cr, 26.7%, Limit breach.** The *Limit breaches* tile reads 1. Click the arrow on the row for the **lineage page**: *Recursive Graph Ownership Traversal (Exasol CONNECT BY)*: Sunrise Industries Limited (ultimate parent) → 74% Sunrise Holdings Limited → 100% Sunrise Finvest Private Limited, plus six operating subsidiaries. Click **View Row-Level Lineage** for a moment: each row shows its proposal, decision, reviewer and timestamp.

> One registry filing says Sunrise owns seventy-four percent of Sunrise Holdings, which owns Sunrise Finvest. One approval merges the two groups, and Sunrise goes from forty crore reported to one hundred and twelve crore. Twenty-six point seven percent. Over the limit.
>
> This ownership tree is a single Exasol CONNECT BY query. And every rupee traces back to a source row, a reviewer and a timestamp.

## Scene 5 · 2:20 – 2:40 · It scales

**Do:** `/pipeline`. Hold on the tiles (*Settled purely in SQL* **95.6%**, *Candidate reduction* **99.27%**) and the **stage timings** table: standardise about 1.5 s, blocking about 6 s, scoring about 3 s.

> Every stage you see is SQL. At ten times the size, two hundred and fifty thousand records and eleven and a half million candidate pairs, the blocking, scoring and grouping stages run in under two and a half minutes, on Exasol Nano, on a laptop. *(optional)* Blocking and scoring grow roughly in line with the work, and no Python UDF is needed.

## Scene 6 · 2:40 – 3:00 · Prove it

**Do:** `/audit`. On the newest run click **⚡ Verify Replay**: the badge turns green, **✓ REPLAY MATCH** with the first digits of the output hash. Hold for two seconds, then cut to the title card: *Talos. Connected exposure, matched, grouped and proven inside Exasol.*

> Nothing is ever updated or deleted. Every decision is an append-only event, so Exasol can rebuild any report exactly as it stood at any moment, and the auditor gets the same hash. Talos: connected exposure, matched, grouped and proven inside Exasol.

---

## Timing

| Scene | Screen time | Narration | Words |
|---|---|---|---|
| 1 The group nobody can see | 0:00 – 0:30 | 0:28 | 71 |
| 2 A hundred million comparisons | 0:30 – 1:10 | 0:40 | 99 |
| 3 The hard cases | 1:10 – 1:50 | 0:27 | 67 |
| 4 The holding company | 1:50 – 2:20 | 0:26 | 65 |
| 5 It scales | 2:20 – 2:40 | 0:24 | 61 |
| 6 Prove it | 2:40 – 3:00 | 0:16 | 41 |

Scene 5 is the tightest: the narration is 24 s for a 20 s window, so say it a touch faster or cut the *(optional)* sentence. If the whole video runs long, also drop the optional board beat in Scene 2.

## If a judge asks

- **"A reviewer approves 1,015 pairs in one click?"** The button fills every verdict with Approve so the reviewer only flips the exceptions. The form still posts one verdict per sampled pair, the server checks it is exactly the sample drawn from the recorded seed, and one Reject fails the batch. The 5% sample size is a policy value (`T0_SAMPLE_PCT`), not code (DEV-36).
- **"Where is the model?"** There is none in this demo. The grey band can go to an optional judge, which can only send a pair to a human, never approve it.
- **"What is slow at scale?"** The judge stage, which is Python writing one verdict row per round trip: 96% of the 250,000-record match. The SQL stages are 144 s. Batching that insert is the next step.
- **"Is the data real?"** Synthetic and cleaner than a real registry (DEV-17). The planted cases are scored against truth tables the pipeline cannot read.

## Where each Exasol claim comes from

| Claim in the narration | Source |
|---|---|
| 100 million possible pairs cut to about 731,000 candidates in about 5 s, 99.9% recall | `eval/results/dev.json`: 731,543 candidates, reduction 99.27%, blocking recall 99.88%; blocking stage 3.9–6.3 s across runs |
| Identifiers hashed in SQL, raw PAN never leaves | `sql/20_id_tokens_exact.sql`: keyed `HASH_SHA256`; proposal evidence carries no identifiers |
| Groups rebuilt with one MERGE, repeated until nothing changes | `sql/52_components_pass.sql`, looped by `publish_run` |
| Soundex, Cologne phonetic, edit distance | `sql/10_standardise.sql`, `sql/31_candidates_blocked.sql`; probe 1 in `docs/PROBE.md` |
| Ownership tree is one CONNECT BY query | `REPORT.V_OWNERSHIP_PATH` in `sql/81_report_views.sql`; probe 7 |
| 250,000 records, 11.5 million pairs, SQL stages under 2.5 minutes | Stage timings in the README on branch `measure/test-and-scale` (19 Oct): the SQL stages at scale sum to about 144 s. The judge stage is Python and is left out. **Push that branch before submitting** so the claim can be checked. |
| No Python UDF needed | Probe 12: Python UDFs are not available on Nano, so label propagation is plain SQL (`udf/README.md`) |
| Append-only, rebuild as of any moment, same hash | Roles grant no UPDATE or DELETE on `RAW_*`, `GRAPH`, `GOV`; `sql/50_asof_links_edges.sql` (as of `known_at`); `talos replay --all` matched every run |
| Sunrise figures (₹40.0 → 31.2 → 58.2 → 75.6 → 112.0 cr) | Rehearsed on live Exasol through the console: the same five numbers as the generator's hero group in `tests/test_generator.py` |
