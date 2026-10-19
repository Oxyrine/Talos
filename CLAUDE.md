# Talos

ExaThon India 2026, Track 01 entry. Resolves records to legal entities and links them into groups inside Exasol, computes group exposure against RBI limits, and publishes nothing until a person has recorded a decision. Read `README.md` first, `CONTRACT.md` for interfaces, `docs/DECISIONS.md` for deviations.

## Commands

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest -m "not exasol"          # no database; this is what the unit CI job runs
uv run pytest -m exasol                # needs Nano on 127.0.0.1:8563 and `talos init`
TALOS_MOCK=1 uv run talos serve        # console on simulated data, sign in reviewer@talos.internal / talos
uv run talos demo                      # live: reset, generate, load, match, serve (wipes the Talos schemas)
```

## Layout

- `sql/` numbered pipeline files, run in order. `sql/81_report_views.sql` is everything the UI reads.
- `orchestrator/` CLI, `db.py` (connection roles), `decide.py` (the only writer of decisions), `replay.py`, `policy.py`.
- `ui/` FastAPI + Jinja2 + HTMX. `queries.py` is the only module that talks to the database; `mock_data.py` backs mock mode.
- `data/generator/` deterministic synthetic world with planted cases; `eval/` scores against the truth tables.

## Conventions that bite

- SQL files are pyexasol format strings: `{name}` is a parameter, literal braces are doubled (`{{5}}`).
- `connect()` returns dict rows with lower-case keys. Index by name, not position.
- No role can UPDATE or DELETE evidence tables (`RAW_*`, `GRAPH`, `GOV`). The reader sees `REPORT` only, so the UI must not query `GOV` directly.
- `business_date` is a required argument to `decide`, `batch_decide`, `rule`, `batch_sample` and `publish_run`.
- Secrets: `TALOS_SESSION_SECRET` has no default outside mock mode. Don't add one.
- The web UI uses a strict CSP: no inline styles or scripts.
- Python is pinned to 3.12 so seeded sampling is reproducible.
- Commits are authored as `Aakash A <230161983+Oxyrine@users.noreply.github.com>` with no co-author trailer.
