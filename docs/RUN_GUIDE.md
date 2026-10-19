# Run Guide

Everything here uses [uv](https://docs.astral.sh/uv/) and Python 3.12 (`requires-python = ">=3.12,<3.13"`). Commands are the real `talos` CLI (`uv run talos --help`).

```bash
git clone https://github.com/Oxyrine/Talos.git
cd Talos
uv sync --extra dev
```

## 1. See the console without a database (mock mode)

Mock mode serves the web console from an in-memory simulation of the Sunrise story. It needs no Exasol and no Docker.

```powershell
$env:TALOS_MOCK = "1"        # bash: export TALOS_MOCK=1
uv run talos serve
```

Open <http://127.0.0.1:8000> and sign in with `reviewer@talos.internal` / `talos` (APPROVER). These credentials work only while `TALOS_MOCK=1`; a banner marks every page as simulated. With `TALOS_MOCK` unset and no database, the app shows a 503 page rather than falling back silently.

Mock mode is for UI work and demos. It does not exercise the SQL, the governance code or the replay.

## 2. Run against Exasol

### 2.1 Start Exasol Nano

Nano is the single-node image used by CI. It needs about 6 GB of RAM for Docker and is `amd64` only.

```bash
mkdir -p ~/.talos-secrets && printf '%s' 'ChooseAStrongSysPassword1!' > ~/.talos-secrets/sys_password

docker run -d --name exasol-nano --shm-size=512mb --pids-limit=-1 \
  -p 127.0.0.1:8563:8563 \
  -v ~/.talos-secrets/sys_password:/run/secrets/sys_password:ro \
  docker.io/exasol/nano:2026.2.0-nano.3-amd64 \
  init sys_password_file=/run/secrets/sys_password

# ready when this prints "Database is now up and running!"
docker logs -f exasol-nano
```

The Exasol Personal starter kit installs the same runtime on Windows, macOS and Linux if you prefer it.

### 2.2 Configure

```bash
cp .env.example .env
```

Set `EXASOL_DSN` (default `127.0.0.1:8563`) and either `EXASOL_PASSWORD` or `EXASOL_SYS_PASSWORD_FILE`. `talos init` generates the five role passwords and `TALOS_SESSION_SECRET` into `.env`. The web console refuses to start signing sessions without a real `TALOS_SESSION_SECRET`.

### 2.3 Initialise, add a reviewer, run the demo

```bash
uv run talos init                              # users, schemas, grants, views
uv run talos add-reviewer "Your Name" --role APPROVER
uv run talos demo                              # reset, generate dev data, load, match, serve
```

Then open <http://127.0.0.1:8000> and sign in with the reviewer you added. `talos demo` drops and recreates every Talos schema, so run it only against a database you are happy to wipe.

### 2.4 Step by step

```bash
uv run talos generate --profile dev --out data/out/dev   # profiles: dev | test | scale | tiny
uv run talos load data/out/dev
uv run talos match                                       # baseline run plus proposals
uv run talos serve
```

Decisions are made in the web console (queue, batch review and ruling screens). Each approval publishes a new run.

## 3. Measure and replay

```bash
uv run talos eval --profile dev    # reset, generate, load, match, oracle decisions, metrics
uv run talos eval --profile test --seed-from-commit <freeze-commit-sha>   # held-out set, seeded by the freeze commit
uv run talos replay --all          # re-run every published run and compare output hashes
uv run talos replay R-20261015-ab12   # one run
```

`talos eval` writes `eval/results/<profile>.json` and `misses_<profile>.md`. The oracle reviewer accepts the system's recommendation and never reads the ground truth. `talos replay` exits non-zero on a hash mismatch.

## 4. Tests

```bash
uv run ruff check .
uv run pytest -m "not exasol"      # no database needed
uv run pytest -m exasol            # needs Nano running and `talos init` done
```

## 5. Troubleshooting

| Symptom | Fix |
|---|---|
| 503 page on every route | Exasol isn't reachable and `TALOS_MOCK` isn't `1`. Check `docker ps` and `EXASOL_DSN`. |
| Sign-in fails with a 500 | `TALOS_SESSION_SECRET` is unset or still the `change_me` placeholder. Run `talos init` or set a real value. |
| `talos load` hangs | pyexasol's HTTP tunnel hangs on Nano under Docker Desktop for Windows. The loader uses chunked `INSERT` for that reason, so don't switch it to `import_from_iterable`. |
| TLS or version-string errors on connect | `orchestrator/db.py` patches pyexasol for Nano's `-nano.N` version string and uses the self-signed certificate. Don't pass `schema=` at connect. |
| Port 8563 already in use | Stop the other Exasol container, or change the `-p` mapping and `EXASOL_DSN`. |
| `talos reset` refuses to run | The DSN isn't localhost. Pass `--force` only if you mean it. |
