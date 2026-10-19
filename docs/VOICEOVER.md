# Voice-over: 3-minute submission video

Narration for the screen recording described in [DEMO_SCRIPT.md](DEMO_SCRIPT.md), Part 1. Every figure below was checked on live Exasol on 19 Oct (`uv run talos demo`, business date 2026-09-30, capital ₹420 cr, 10% line ₹42 cr, 25% limit ₹105 cr).

About 410 words, which is 2:45 at a steady 150 words a minute, leaving a few seconds for the title card. Record the screen first, then read this over it.

**Editing notes**

- Each approval waits for a fresh report run: about 10 s for the exact-ID batch and about 5 s for each card. Cut those waits in the edit.
- The exact-ID sample is 1,015 pairs on dev data. Show the first screen of it, scroll briefly, then cut to the submitted result. The narration says so plainly.
- On the board, point at the **Sunrise row**, not the "Hidden exposure unmasked" tile. The tile adds up every group in the book, so after step 1 it is already far larger than Sunrise's own figure.
- On screen, Sunrise's reported row reads "Sunrise Indu5tries Limited" until it is linked. That is the loan book's own spelling, with the generator's typo noise, so leave it.

---

## 0:00 – 0:35 · The group nobody can see

**Screen:** `/board`. Scroll to the Sunrise row: reported **₹40.0 cr**, Pending. Then point at the 10% and 25% markers.

> Indian banks can lend a group of connected companies no more than twenty-five percent of their capital, and anything at ten percent or more must be reported. This bank has four hundred and twenty crore of capital. Its loan system says the Sunrise group owes forty crore, under ten percent. Compliant.
>
> But Sunrise also sits in the treasury book and in trade-finance guarantees, under names that don't quite match. And part of it hides in a holding company nobody has linked. Talos finds those links inside Exasol, and shows what the group really owes.

## 0:35 – 1:15 · Review a sample, not twenty thousand rows

**Screen:** `/queue`. Open the **Exact-ID record links** banner: the first screen of the 1,015-pair sample, seed by the submit button. Submit. Then the **Corroborated ownership** banner, 71 pairs. Submit. Back to `/board`: Sunrise **₹58.2 cr, 13.9%**, Large exposure, hidden **+₹18.2 cr**.

> Most links are routine. The PAN matches exactly, or the registry and the loan book agree on who owns whom. Talos puts those in batches and draws a random sample from a seed shown on screen. Here that is one thousand and fifteen pairs out of twenty thousand. The reviewer decides every pair in the sample, and a single rejection fails the whole batch.
>
> Once approved, Exasol rebuilds the groups in SQL. Sunrise is now fifty-eight crore, thirteen point nine percent, past the ten percent line.

## 1:15 – 1:55 · The hard cases get a human

**Screen:** Queue, Sunrise's individual cards. Open the guarantee card for *Sunrise Industries Ltd*: book name and registry name side by side, same pincode, no PAN on the book record. Approve. Then the T3 card where the *Sunrise Textiles* guarantee carries the PAN of *Bhopal Agro Foods*: red conflict chip. Reject.

> Records with no identifier get scored in the database on name, sound-alike spelling and pincode, and a person sees the evidence side by side. This guarantee matches on name and pincode, so the reviewer approves it.
>
> This one is the trap. The record says Sunrise Textiles, but it carries the PAN of a different company. Talos never trusts an ID that disagrees with the name, and a rejection is written to the audit log as a permanent do-not-link.

**Screen:** board after the remaining Sunrise cards: **₹75.6 cr, 18.0%**.

> With the treasury and guarantee records linked, Sunrise is seventy-five crore, eighteen percent.

## 1:55 – 2:35 · The holding company

**Screen:** Queue, the **Sunrise Industries → Sunrise Holdings** ownership card. The headline reads 18.0% → 26.7%, crossing the limit. Approve. `/board`: **₹112.0 cr, 26.7%**, Limit breach. Open the lineage page: the ownership tree, then the source rows.

> One registry filing says Sunrise Industries owns seventy-four percent of Sunrise Holdings, which owns Sunrise Finvest. That holding group already carries thirty-six crore of loans under its own name. On its own it looks fine, and so does Sunrise.
>
> One approval merges them. Sunrise goes from forty crore reported to one hundred and twelve crore, twenty-six point seven percent of capital, over the limit. And every rupee traces back to a source row, the person who approved the link, and when.

## 2:35 – 3:00 · Prove it

**Screen:** `/audit`. Click **Verify replay** on the latest run: green *Replay match* with the hash. Close on the title card.

> Every published run records the data versions, policy and code it used, plus a hash of its output. An auditor can replay any run and get the same hash. The matching and grouping run inside Exasol, and in this demo no AI model makes a decision. Talos: group exposure under RBI limits, computed in the database.
