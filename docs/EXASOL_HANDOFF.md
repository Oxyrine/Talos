# Hand-off: what needs a live Exasol

Everything that does not need a database is done and on `main`: the code, the docs, the mock-mode console, and the unit and fake-connection tests. CI runs `talos init` and the Exasol tests on every push, and they pass.

**What has never run:** the web console against real data (`talos demo`), the five-step Sunrise walkthrough on live numbers, the test-set evaluation, the scale run, and anything involving the recording. The console's real-database code (`ui/queries.py`) is covered by a fake-connection test only, so expect to find a few mistakes. Fixing them is part of this hand-off.

Deadlines: code freeze **Thu 23 Oct, 23:59 IST**. Submission video and deck 24 to 25 Oct. Work in this order; each step unblocks the next.

---

## 0. Setup (about 30 minutes)

1. Get a database. Either Docker Desktop with at least 6 GB RAM and the Nano command in [RUN_GUIDE.md §2.1](RUN_GUIDE.md), or a GitHub Codespace on a 4-core machine (the same `docker run` works inside it). Nano is `amd64` only.
2. `git pull`, then `uv sync --extra dev`, `cp .env.example .env`, set `EXASOL_DSN` and `EXASOL_PASSWORD` (or `EXASOL_SYS_PASSWORD_FILE`).
3. `uv run talos init`, then `uv run pytest -m exasol`. Both should pass, as they do in CI.
4. `uv run talos add-reviewer "<your name>" --role APPROVER`.

## 1. Run the demo and fix what breaks

`uv run talos demo` resets everything, generates the dev data (about 2 minutes to load), matches, and serves <http://127.0.0.1:8000>. Sign in with the reviewer you added. Then go through each screen. The right-hand column is what is most likely to be wrong, because that code has only been tested against a fake connection.

| Screen | Check | Likely trouble |
|---|---|---|
| `/board` | Sunrise appears with reported ₹40.0 cr. Tiles show hidden exposure, breaches, large exposures. | Groups whose flags contain `UNRESOLVED` are shown as "Pending" with no figure (my choice, to match the mock). Confirm that reads well on dev data. |
| `/queue` | Two batch banners (exact-ID record links, corroborated ownership) plus individual cards, ranked by impact. | `V_PROPOSAL_QUEUE` with about 20,000 proposals: check the page loads in a few seconds. Cards depend on `ui/formatting.py::_normalise_pipeline_evidence`, which maps the flat evidence from `sql/70`/`71` to the card layout. Check names, IDs and stakes show. |
| `/queue/batch/<id>` | Seed on screen, sample pairs with Approve/Reject radios, submit. | **Sample size.** On dev, about 20,000 records resolve by exact ID, so the 5% sample is about 1,000 pairs (`DECISIONS.md` DEV-36). Too long to review on camera. Decide: lower `T0_SAMPLE_PCT` in policy, or show the first screen only. Also check the ownership batch (2%, about 70). |
| Decision / batch / ruling buttons | The board moves. Each decision calls `publish_run`. | Time per decision (the request waits for the publish). If it is slow, say how slow. |
| `/rulings/<id>` | Holders, stakes and groups for a real JV card. Try JOINT, SINGLE, NONE and CONNECTED. | `get_ruling_data` reads holder names from `REPORT.V_ENTITY_NAME`. CONNECTED needs a rationale of at least 20 characters. |
| `/lineage/group/<key>` | Ownership tree and member list. | `V_OWNERSHIP_PATH` (`CONNECT BY`) cost at scale, and that the head node and cycle marker show. |
| `/lineage/entity/<key>`, `/lineage/rows` | Component breakdown; rows with proposal, decision, reviewer. | Rows are capped at 1,000. |
| `/pipeline` | Stage timings, candidate paths, tier counts, summary. | `V_TIER_COUNTS` has a column called `count`, which I query as `"COUNT"`. Confirm it works. |
| `/audit` | Run list; "Verify replay" shows a match. | Replay runs as the pipeline user and takes as long as a publish. |

Fix problems in `ui/queries.py`, `ui/formatting.py` or the templates. If a view is wrong, change `sql/81_report_views.sql` and tell Track B; the contract lives in `CONTRACT.md`. Add a test for each fix: `tests/test_ui_queries_real.py` shows the fake-connection pattern.

## 2. Walk the Sunrise story on live numbers

The demo script and the video depend on these figures at business date 2026-09-30 (capital ₹420 cr, 10% line ₹42 cr, limit ₹105 cr). Approve in this order and write down what the board shows after each step.

| Step | Approve | Expect Sunrise group |
|---|---|---|
| 0 | nothing | reported ₹40.0 cr (9.5%) |
| 1 | the exact-ID record batch | ₹31.2 cr (7.4%) |
| 2 | the corroborated ownership batch | ₹58.2 cr (13.9%); the holding-company group is ₹36.4 cr |
| 3 | the hero's fuzzy-match cards; reject the wrong-PAN guarantee card | ₹75.6 cr (18.0%) |
| 4 | the single Sunrise Industries → Sunrise Finvest ownership card | ₹112.0 cr (26.7%), breach |

`tests/test_generator.py` asserts these in the generator, so a mismatch is either a pipeline problem or a UI problem, not bad data. If a step doesn't match, find out which layer is wrong before changing anything, and tell the team.

Then fill every `<…>` placeholder in [DEMO_SCRIPT.md](DEMO_SCRIPT.md) with what the screen shows (sample size, card amounts, similarity).

## 3. Measure

1. `uv run talos eval --profile dev`. It should reproduce `eval/results/dev.json` (0 of 6 missed breaches, 12 of 12 conflicts, 0 of 30 decoys). If it doesn't, stop and find out why.
2. **Freeze the thresholds.** Commit `policy/thresholds.json` with the message `freeze: matching thresholds`. Don't change it again.
3. Get the freeze commit with `git rev-parse HEAD`, then run `uv run talos eval --profile test --seed-from-commit <that sha>`. The test set's seed is derived from the SHA, so don't use another seed. (`--seed-from-commit` on `eval` was added on 19 Oct; before that this command could not run.) Commit `eval/results/test.json` and `misses_test.md`.
4. Fill the **Test** column in the README metrics block from the result, whatever it is. If it is worse than dev, say so in the README. Do not tune on it.
5. `uv run talos replay --all` must exit 0.

## 4. Scale and speed

1. `uv run talos generate --profile scale --out data/out/scale`, then load and match it. Record each stage's seconds in the README (the `/pipeline` screen shows them). If blocking or scoring is too slow, the first thing to try is `BLOCK_MAX`.
2. Python UDFs fail the Nano probe, so label propagation stays plain SQL (`udf/README.md`). Don't spend time on UDFs.

## 5. Recording material

Needs the live demo running: a **fallback screen recording** of the whole Sunrise walkthrough (steps 0 to 4, then the audit replay), and screenshots of the board, queue card, lineage tree and audit screen for the deck and README. The 3-minute video follows [DEMO_SCRIPT.md](DEMO_SCRIPT.md).

## 6. Optional, if time allows

- CI already runs `tests/test_e2e_tiny.py` in the Exasol job (it is marked `exasol`). Check it passes locally too; it is the quickest end-to-end smoke test (generate, load, match, oracle, replay).
- Write the exact-ID batch's sample size into the on-screen banner so the reviewer sees the burden up front.

## 7. Report back

Send the team: the five board figures from §2, the `talos eval` results for dev and test, the stage timings for dev and scale, anything that didn't match, and your decision on the batch sample size.
