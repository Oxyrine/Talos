# Voice-over: 3-minute submission video

Narration for the screen recording described in [DEMO_SCRIPT.md](DEMO_SCRIPT.md), Part 1. It tells the Sunrise story and makes the case that Exasol does the work: every claim about the database below is something Talos actually runs in SQL or measured, and the sources are listed at the end. Sunrise figures were checked on live Exasol on 19 Oct (business date 2026-09-30, capital ₹420 cr, 10% line ₹42 cr, 25% limit ₹105 cr).

About 390 words, which is about 2:35 at a steady 150 words a minute, leaving room to pause on the key figures and the title card. Record the screen first, then read this over it. If you run long, cut the sentence marked *(optional)*.

**Editing notes**

- Each approval waits for a fresh report run: about 9 s for the exact-ID batch, 7 s for the ownership batch and 5 s for each card. Cut those waits in the edit.
- The exact-ID sample is 1,015 pairs on dev data. Show the first screen of it, scroll briefly, then cut to the result.
- On the board, point at the **Sunrise row**, not the "Hidden exposure unmasked" tile. The tile adds up every group in the book.
- Until it is linked, Sunrise's reported row reads "Sunrise Indu5tries Limited". That is the loan book's own spelling with the generator's typo noise, so leave it.

---

## 0:00 – 0:30 · The group nobody can see

**Screen:** `/board`. Scroll to the Sunrise row: reported **₹40.0 cr**, Pending. Point at the 10% and 25% markers.

> Indian banks can lend a group of connected companies at most twenty-five percent of their capital, and anything over ten percent must be reported. This bank has four hundred and twenty crore. Its loan system says Sunrise owes forty crore. Compliant.
>
> But Sunrise also sits in treasury and trade-finance books, under names that don't match, and behind a holding company nobody linked. Talos finds those links, and it does every step of it inside Exasol.

## 0:30 – 1:05 · A hundred million comparisons, answered in SQL

**Screen:** `/queue`. Open the **Exact-ID record links** banner: first screen of the 1,015-pair sample, seed by the submit button. Submit. Then the **Corroborated ownership** banner, 71 pairs. Submit. Back to `/board`: Sunrise **₹58.2 cr, 13.9%**, Large exposure.

> Twenty-five thousand book records against four thousand registry companies is a hundred million possible pairs. Exasol cuts that to seven hundred thousand candidates in about five seconds, and keeps ninety-nine point nine percent of the true matches. Identifiers are hashed in SQL, so a raw PAN never leaves the database.
>
> Routine links go into batches. The reviewer checks a seeded sample, and one rejection fails the whole batch. Then Exasol rebuilds every group with a single MERGE statement, repeated until nothing changes. Sunrise is now fifty-eight crore, past the ten percent line.

## 1:05 – 1:40 · The hard cases get a human

**Screen:** Queue, the *Sunrise Industries Ltd* guarantee card: names side by side, same pincode, no PAN. Approve. Then the T3 card where the *Sunrise Textiles* guarantee carries the PAN of *Bhopal Agro Foods*: red conflict chip. Reject. Board: **₹75.6 cr, 18.0%**.

> Records with no ID are scored with Exasol's built-in name functions, Soundex, Cologne phonetic and edit distance, right next to the data. This guarantee matches on name and pincode. Approve.
>
> This one is the trap: Sunrise Textiles, carrying another company's PAN. An ID that disagrees with the name is never trusted, and the rejection becomes a permanent do-not-link. Sunrise is now seventy-five crore.

## 1:40 – 2:15 · The holding company

**Screen:** The **Sunrise Industries → Sunrise Holdings** card: 18.0% → 26.7%, crosses the limit. Approve. `/board`: **₹112.0 cr, 26.7%**, Limit breach. Open the lineage page: the ownership tree, then the source rows.

> One registry filing says Sunrise owns seventy-four percent of Sunrise Holdings, which owns Sunrise Finvest. One approval merges them, and Sunrise goes from forty crore reported to one hundred and twelve crore. Over the limit.
>
> This tree is a single Exasol CONNECT BY query, and every rupee traces to a source row, a reviewer and a timestamp.

## 2:15 – 2:35 · It scales

**Screen:** `/pipeline`: stage timings, candidate paths, 99.27% reduction.

> Every stage you see is SQL. At ten times the size, two hundred and fifty thousand records and eleven and a half million candidate pairs, the whole SQL pipeline runs in under two and a half minutes, on Exasol Nano, on a laptop. *(optional)* Blocking and scoring grow roughly in line with the work, and no Python UDF is needed.

## 2:35 – 3:00 · Prove it

**Screen:** `/audit`. Click **Verify replay** on the latest run: green *Replay match* with its hash. Close on the title card.

> Nothing is ever updated or deleted. Every decision is an append-only event, so Exasol can rebuild any report exactly as it stood at any moment, and the auditor gets the same hash. Talos: connected exposure, matched, grouped and proven inside Exasol.

---

## Where each Exasol claim comes from

| Claim in the narration | Source |
|---|---|
| 100 million possible pairs cut to about 731,000 candidates in about 5 s, 99.9% recall | `eval/results/dev.json`: 731,543 candidates, reduction 99.27%, blocking recall 99.88%; blocking stage 3.9–5.5 s across runs |
| Identifiers hashed in SQL, raw PAN never leaves | `sql/20_id_tokens_exact.sql`: keyed `HASH_SHA256`; evidence carries no identifiers |
| Groups rebuilt with one MERGE, repeated until nothing changes | `sql/52_components_pass.sql`, looped by `publish_run` |
| Soundex, Cologne phonetic, edit distance | `sql/10_standardise.sql`, `sql/31_candidates_blocked.sql`; probe 1 in `docs/PROBE.md` |
| Ownership tree is one CONNECT BY query | `REPORT.V_OWNERSHIP_PATH` in `sql/81_report_views.sql`; probe 7 |
| 250,000 records, 11.5 million pairs, under 2.5 minutes of SQL | Stage timings in the README on branch `measure/test-and-scale` (19 Oct): the SQL stages at scale sum to about 144 s. The offline stub judge is not Exasol work and is left out. |
| No Python UDF needed | Probe 12: Python UDFs are not available on Nano, so label propagation is plain SQL (`udf/README.md`) |
| Append-only, rebuild as of any moment, same hash | Roles grant no UPDATE or DELETE on `RAW_*`, `GRAPH`, `GOV`; `sql/50_asof_links_edges.sql` (as of `known_at`); `talos replay --all` matched every run |
