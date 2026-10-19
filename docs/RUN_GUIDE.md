# Talos Operator & Run Guide

Comprehensive execution instructions for local interactive demonstrations, Docker container deployments, automated CLI pipelines, and regulatory cryptographic replays.

---

## 1. Quickstart: 2-Minute Interactive UI Demonstration (Mock Mode)

To explore the full Talos web console without spinning up an Exasol database, use the in-memory deterministic simulation engine:

```bash
# 1. Clone repository and navigate to workspace
cd talos

# 2. Set mock environment variable
export TALOS_MOCK=1          # macOS / Linux
$env:TALOS_MOCK="1"          # Windows PowerShell

# 3. Launch the web server using Uvicorn
uvicorn ui.app:app --host 127.0.0.1 --port 8000 --reload
```

Open your browser to:
**`http://127.0.0.1:8000`**

### Default Approver Credentials (Mock Mode Only):
* **Reviewer Email**: `reviewer@talos.internal`
* **Password**: `talos`
* **Role**: `APPROVER`

> [!NOTE]
> Mock mode operates **strictly when `TALOS_MOCK=1`** is present. A prominent warning banner indicates simulated execution. If `TALOS_MOCK` is unset and Exasol is unreachable, the application fails loudly with an **HTTP 503 Service Unavailable** screen. There is zero silent fallback.

---

## 2. Full Live Production Architecture (Exasol Docker Container)

### Step 2.1: Spin up Exasol Docker Container
```bash
docker run --name exasol-talos \
  -p 8563:8563 \
  --detach \
  --privileged \
  exasol/docker-db:latest
```
Wait approximately 30–45 seconds until Exasol finishes its internal initialization:
```bash
docker logs -f exasol-talos
# Watch for: "Exasol is ready to accept connections"
```

### Step 2.2: Configure Environment Variables
Copy the template configuration:
```bash
cp .env.example .env
```
Ensure your `.env` contains:
```ini
EXASOL_HOST=localhost
EXASOL_PORT=8563
EXASOL_USER=sys
EXASOL_PASSWORD=exasol
TALOS_MOCK=0
TALOS_SESSION_SECRET=replace_with_secure_production_secret_key_32_bytes
```

---

## 3. Data Generation, Database Loading & Pipeline Execution

### Step 3.1: Generate Deterministic Synthetic World
Generate the benchmark universe (400 groups, 4,000 legal entities, 25,000 identity records across 4 lending books):
```bash
# Generates Parquet files, canonical row manifests, and ground truth files in data/out/
python -m data.generator.generate --profile dev --seed 42
```
Profiles supported:
* `tiny`: Ultra-fast test set (0.2x scale, 800 records).
* `dev`: Standard demo profile (25,000 records).
* `scale`: Institutional stress profile (10x scale, 250,000 records).

### Step 3.2: Initialize Schema and Ingest Books into Exasol
```bash
# Deploys DDL tables (sql/00 through sql/20) and ingests Parquet files via pyarrow/pyexasol
python -m orchestrator.cli load
```

### Step 3.3: Execute In-Database Matching Engine
```bash
# Runs candidate blocking, Jaccard scoring, graph traversal, and bitemporal exposure rollup
python -m orchestrator.cli match --business-date 2026-09-30
```

---

## 4. Human-in-the-Loop CLI & Governance Workflow

The Talos orchestrator CLI exposes governance actions directly from the command line:

### List Open Review Proposals
```bash
python -m orchestrator.cli queue --tier T1
```

### Execute Individual Review Decision
```bash
# Approve an individual high-confidence link
python -m orchestrator.cli decide P-REC-GTE-SUNRISE-TRUE \
  --decision APPROVE \
  --reason "Bank guarantee facility verified via address match" \
  --reviewer "Aakash A"

# Reject an ID-Name conflict decoy
python -m orchestrator.cli decide P-REC-GTE-SUNRISE-CONFLICT \
  --decision REJECT \
  --reason "ID-Name mismatch detected: Decoy Kaveri Chemicals entity rejected" \
  --reviewer "Aakash A"
```

### Execute Joint Venture Ruling
```bash
python -m orchestrator.cli rule P-RULING-JV-01 \
  --ruling EQUAL_SPLIT \
  --reason "50-50 joint control confirmed under RBI LEF §5.3" \
  --reviewer "Aakash A"
```

### Inspect Audit Trail & Verify Replay
```bash
# List historical published runs
python -m orchestrator.cli audit

# Cryptographically replay an immutable historical run
python -m orchestrator.cli replay RUN-20260930-01
```
Output:
```
============================================================
TALOS CRYPTOGRAPHIC REPLAY VERIFICATION
============================================================
Run ID:          RUN-20260930-01
Published Hash:  a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6
Replay Hash:     a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6
Status:          ✓ REPLAY MATCH (100% Deterministic Bitwise Identity)
Code Version:    23016198 (Matches original execution commit)
============================================================
```

---

## 5. Running the Test Suite

```bash
# Run all unit, security, formatting, and routing tests (excluding live Exasol)
python -m pytest -m "not exasol"

# Run tests with Exasol integration (requires live container running on port 8563)
python -m pytest
```
