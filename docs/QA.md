# Talos: Regulatory, Technical & Exasol Defense Cheat Sheet (Q&A)

---

## 1. Regulatory Defense & The Honesty Notes

### Honesty Note 1: Synthetic Universe Cleanliness
> [!NOTE]
> **Anticipated Judge Question**: *"In the real world, corporate registry filings (MCA21) are messy, incomplete, and full of stale director filings. Why does your synthetic queue have clean numbers and manageable triage lists?"*
>
> **Direct Answer**:  
> *"We explicitly documented this in `docs/DECISIONS.md` under ADR-014. In our synthetic benchmark, we deliberately isolated the uncorroborated edges to the 11 planted test cases so that a reviewer can complete a full live regulatory demo in under 3 minutes.  
> In a production banking deployment, MCA21 feeds contain thousands of uncorroborated holding links and director cross-appointments. However, Talos's core innovation is its **impact-ranked triage architecture**: even with 10,000 uncorroborated edges, sorting by `crosses_limit DESC, crosses_le DESC, rupee_impact DESC` guarantees that the 5 edges threatening the bank's regulatory capital appear on Page 1, while immaterial holding edges remain safely in background analyst queues."*

---

### Honesty Note 2: Perimeter Exposure vs. Balance Sheet Delta
> [!IMPORTANT]
> **Anticipated Judge Question**: *"HoldCo's ₹36.4 cr was already on your loan book under its own name. In what sense is that exposure 'hidden', and why do you report a +₹72.0 cr perimeter delta?"*
>
> **Direct Answer (Verbatim)**:  
> *"The exposure was on the balance sheet, but reported under a completely separate borrower group.  
> Under RBI LEF Master Circular §5.1, concentration limits apply to **Groups of Connected Counterparties (GCC)**. Prior to running Talos, the bank reported:
> * Group A (Sunrise Industries): ₹40.00 cr (9.52% of capital) → Compliant.
> * Group B (Sunrise Finvest HoldCo): ₹36.40 cr (8.67% of capital) → Compliant.
>
> Because both perimeters were reported independently, neither triggered the 10% Large Exposure disclosure threshold nor the 25% Group Limit.  
> When Talos unmasked the 100% MCA holding link, the two perimeters consolidated into a single group of **₹112.00 cr (26.67% of capital)**, exposing an illegal statutory breach of ₹7.00 crore beyond the ₹105.00 crore legal ceiling.  
> Therefore:
> * **The Group Perimeter Delta** is **+₹72.00 cr** (from ₹40.00 cr to ₹112.00 cr).
> * **The Bank-Wide Loan Book Delta** is **+₹35.60 cr** (the unlinked Treasury CP and Trade Guarantee rows unmasked across books).  
> Regulatory breaches are breaches of group perimeters, and failing to aggregate connected groups is a direct violation of Section 20 of the Banking Regulation Act."*

---

## 2. Regulatory Citations & Statutory Cheat Sheet

| RBI LEF Section | Statutory Mandate | Talos Implementation in Exasol |
|---|---|---|
| **§5.1 (Group Limit)** | Maximum exposure to a Group of Connected Counterparties must not exceed **25.0%** of eligible capital. | Exposure aggregation in `V_GROUP_EXPOSURE` automatically flags `is_breach = TRUE` when `limit_exposure > capital_base * 0.25`. |
| **§6.1 (Large Exposure)** | Exposures $\ge 10.0\%$ of capital must be reported to the Credit Committee and RBI CRILC. | `is_large = TRUE` flagged when `limit_exposure >= capital_base * 0.10`. Highlighted with amber needles on the SVG gauge. |
| **§5.2 (Control Criteria)** | Common control established through equity stakes $\ge 50\%$, majority board seats, or power of appointment. | Recursive graph traversal via Exasol `CONNECT BY held_entity = PRIOR holder_entity` traversing only `CONFIRMED` edges with cycle pruning. |
| **§5.3 (Interdependence)** | Connectedness through bilateral contagion (e.g. counterparty guarantees or funding dependence $>50\%$). | Dedicated `INTERDEP` edge types in `GOV.PROPOSAL` requiring mandatory human governance. |
| **§5.3.4 (Joint Ventures)** | Joint ventures must be consolidated under designated statutory rules. | Live `/rulings/{id}` screen supporting 4 mathematical apportionment formulas: `LEAD_CONSOLIDATES`, `EQUAL_SPLIT`, `PROPORTIONAL`, and `STANDALONE`. |

---

## 3. Exasol Architecture & Performance Defense

### Why In-Database SQL Beats External Graph / ML Silos
```
Traditional Banking Stack                 Talos In-Database Stack
┌─────────────────────────┐               ┌─────────────────────────┐
│ Core Banking (Exasol)   │               │ Core Banking (Exasol)   │
└────────────┬────────────┘               │                         │
             │ Sensitive PII Export       │ • String Normalisation  │
             ▼                            │ • Candidate Blocking    │
┌─────────────────────────┐               │ • Token Jaccard Scoring │
│ Cloud SaaS / Graph DB   │               │ • Recursive CONNECT BY  │
│ (Neo4j / Neptune / ML)  │               │ • Bitemporal Rollup     │
└────────────┬────────────┘               │ • Audit Hash Generation │
             │ Non-Deterministic Output   └────────────┬────────────┘
             ▼                                         │ Zero Data Egress
┌─────────────────────────┐                            ▼
│ Regulatory Misreporting │               ┌─────────────────────────┐
└─────────────────────────┘               │ Bitwise Replay Proof    │
                                          └─────────────────────────┘
```

### The Candidate Reduction Funnel (Pure Exasol)
* **Cartesian Product**: 25,000 book records $\times$ 4,000 registry entities = **100,000,000 potential pairs**.
* **Stage 1 (Exact PAN/CIN Index Blocking)**: Resolves ~18,000 records in sub-second hash joins.
* **Stage 2 (Fuzzy Token Blocking on First Stem + State)**: Produces ~35,000 candidate pairs.
* **Reduction Ratio**: **99.965%** search space eliminated without invoking slow external python loops or foreign embeddings.

---

## 4. Algorithmic Integrity & The Paisa Standard

### 1. Integer Sample Sizing (No Float Drift)
Floating-point arithmetic introduces non-deterministic sampling across OS architectures (e.g., `0.07 * 100 == 7.000000000000001`). Talos uses pure integer ceiling division:
$$\text{calculated} = -(-\text{pct} \times \text{batch\_total} // 100)$$
$$\text{sample\_size} = \min(\text{batch\_total}, \max(\text{min\_k}, \text{calculated}))$$

### 2. Zero-False-Merge Guarantee
* When a human reviewer rejects a proposed link (such as the Kaveri Chemicals decoy `P-REC-GTE-SUNRISE-CONFLICT`), Talos writes an immutable `DO_NOT_LINK` barrier record into `GOV.DECISION_LOG`.
* Downstream resolution queries execute an `ANTI JOIN` against active `DO_NOT_LINK` barriers.
* Even if subsequent pipeline runs change scoring thresholds, a previously rejected pair is permanently barred from consolidating.

### 3. Cryptographic Bitemporal Replay
* Runs record both `business_date` (the financial reporting as-of date) and `known_at` (the bitemporal transaction timestamp).
* The final published report hash is computed as:
  $$\text{SHA-256}(\text{sorted\_canonical\_json}(\text{V\_GROUP\_EXPOSURE}))$$
* Any regulatory auditor can execute `talos replay <run_id>` and independently verify that the historical state matches the signed manifest down to the exact byte.
