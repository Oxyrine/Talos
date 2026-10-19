# The Hidden Concentration Problem: Group Exposure Under RBI LEF

## 1. Regulatory Context: RBI Large Exposures Framework (LEF)

Under the Reserve Bank of India's **Large Exposures Framework (RBI/2018-19/83 DBR.No.BP.BC.43/21.01.003/2018-19)**:
1. **Group Exposure Limit (§5.1)**:
   A bank's exposure to a single Group of Connected Counterparties (GCC) must not exceed **25.0%** of the bank's eligible Tier 1 + Tier 2 capital base (with an exceptional 5% board-approved infrastructure carve-out under strict conditions).
2. **Large Exposure Threshold (§6.1)**:
   Any exposure to a counterparty or connected group that equals or exceeds **10.0%** of the eligible capital base constitutes a *Large Exposure*, triggering mandatory statutory concentration reporting, special asset monitoring, and capital allocation buffers.
3. **Control Criteria (§5.2)**:
   Entities belong to the same group if one counterparty exercises decisive influence over another through direct or indirect equity shareholding (majority stake $\ge 50\%$), voting rights, or power to appoint/remove the majority of board directors.
4. **Economic Interdependence & Joint Ventures (§5.3)**:
   Even without majority ownership, counterparties form a single risk group if financial problems in one entity inevitably create fatal funding, operational, or credit contagion in another (e.g., bilateral cross-guarantees, common source of funding, or dependency exceeding 50% of annual revenues/costs). Joint ventures must be rigorously governed under designated consolidation rules (lead investor consolidation, proportional equity apportionment, or equal split).

---

## 2. The Practical Crisis: Why Group Risk Remains Blind

In tier-1 institutional banks, credit facilities are disbursed across isolated, siloed operational books:
* **Core Loan Origination System (LOS)**: Primary working capital and term loans.
* **Treasury Management System (TSY)**: Commercial papers, corporate bonds, certificates of deposit.
* **Trade Finance & Guarantee Desk (GTE)**: Performance guarantees, financial bank guarantees, standby letters of credit (SBLCs).
* **Collateral & Security Desk (COL)**: Asset pledges, promoter shares, third-party corporate hypothecations.

### The Fragmented Identity Deficit
Between 15% and 30% of non-LOS records (Treasury, Guarantees, Collateral) lack statutory national identifiers such as **PAN (Permanent Account Number)** or **CIN (Corporate Identification Number)**. Instead, borrower records carry:
* Truncated branch names (`"Sunrise Inds Ltd (Mumbai Br)"` vs. `"Sunrise Industries Limited"`).
* Historical trade aliases and abbreviations (`"M/s S.I.L. Commercial Dept"`).
* Legacy alphanumeric codes, operational branch typos, and outdated registered addresses.

Consequently, while the loan origination desk believes its exposure to *Sunrise Industries* is a comfortable **₹40.00 cr (9.52% of capital base)** safely under the 10% Large Exposure line, the bank's other desks hold unlinked treasury bonds, performance guarantees, and credit facilities across subsidiaries that secretly aggregate to **₹112.00 cr (26.67% of capital base)**.

**The bank crosses the statutory 25% insolvency threshold without knowing it.**

---

## 3. Why Legacy Architectures Fail

Traditional bank reconciliation approaches suffer from three systemic flaws:

### Failure 1: The Batch Heuristic Delusion
Nightly batch jobs using naive Levenshtein distance or heuristic thresholds generate tens of thousands of unranked candidate pairs. Reviewers face fatigue and rubber-stamp proposed merges without auditable legal evidence. When an incorrect merge occurs (e.g., merging two unrelated entities with similar names), groups are corrupted, exposures are misattributed, and compliance reports become legally indefensible.

### Failure 2: Cloud ML & External Graph Silos
Modern vendor architectures attempt to extract sensitive credit records and transmit them to external cloud SaaS or specialized graph databases (e.g., Neo4j, AWS Neptune). This violates:
* **Banking Secrecy & Data Residency Laws**: Sending non-public borrower contracts, unmasked PANs, and promoter details outside the bank's regulated perimeter.
* **Latency & Bitemporality**: Graph databases lack native ACID bitemporality (`known_at` vs. `business_date`), making it impossible to reconstruct what the bank knew at 4:00 PM on the quarter-end closing date.
* **Deterministic Replayability**: External ML models drift, hallucinate, and cannot cryptographically prove that re-running an evaluation produces the exact same byte-for-byte regulatory conclusion.

---

## 4. The Talos Architectural Remedy

Talos eliminates the entire external processing tier by executing **deterministic entity resolution, recursive graph traversal, and RBI exposure aggregation entirely inside Exasol**:

1. **Zero External API Calls**: All string normalisation, blocking candidate generation, token Jaccard scoring, and equity graph traversals execute natively inside Exasol SQL.
2. **Deterministic Governance Tiers**:
   * **Tier 0 (Exact Match)**: Deterministic PAN/CIN concordances approved in bulk through seed-verified sampling.
   * **Tier 1 (High-Confidence Fuzzy)**: Algorithmic name + address corroboration presented to human risk officers with exact rupee and regulatory impact ranking.
   * **Tier 2 (Low Score Discard)**: Filtered out by policy thresholds.
   * **Tier 3 (ID-Name Conflict Barrier)**: Same-PAN / different-name decoys flagged with mandatory rejection to prevent catastrophic false merges.
3. **Bitemporal Cryptographic Replay**: Every run produces an immutable SHA-256 state hash. An independent auditor or regulator can replay any historical execution down to the exact paisa.
