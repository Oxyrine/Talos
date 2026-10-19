# The Hidden Group Exposure Problem

A lender's loan, treasury, guarantee and collateral books record the same corporate borrowers under different names and IDs, and none of them shows who owns whom. Group exposure is therefore understated, and a missed ownership link is an unreported limit breach.

## 1. The rule

RBI's Large Exposures Framework (circular RBI/2018-19/196, 3 June 2019) caps a bank's exposure to a **group of connected counterparties** at **25% of its eligible capital base** (para 5.2), and treats any exposure at or above **10%** as a large exposure (para 4.1) that must be reported (para 4.2). The eligible capital base is Tier 1 capital (para 5.3).

Counterparties are connected when one controls the other, which includes owning more than 50% of its voting rights (paras 6.2(a) and 6.3), or when they are economically interdependent (para 6.2(b)), for example when 50% or more of one party's gross receipts or expenditure comes from the other (para 6.7). The interdependence criteria apply from 1 April 2020.

The limit applies to the group, not to a single legal entity. A bank can be inside the limit on every borrower it knows about and over it on the group.

> Paragraph numbers were read from the RBI notification page on 19 Oct 2026. Re-check them against the original PDF before quoting them to the judges. The framework for NBFCs differs and is out of scope.

## 2. Why the group figure is wrong in practice

Exposure sits in four books that were built independently:

| Book | Holds |
|---|---|
| LOS (loan origination) | term loans, working capital, cash credit |
| TSY (treasury) | NCDs, commercial paper, bonds |
| GTE (guarantees) | financial and performance guarantees |
| COL (collateral) | pledges. Talos reads these for identifiers only and gives them no exposure. |

Three things go wrong:

1. **Records don't share keys.** Many treasury, guarantee and collateral rows carry no PAN or CIN, only a name and an address, and the name is abbreviated, mistyped or reordered.
2. **The group map is stale.** The loan system's group code is updated once a year, so a subsidiary acquired or registered since then sits outside the group.
3. **Nothing records who owns whom.** Ownership lives in registry filings, not in any lending book.

In the demo data, Sunrise Industries shows **₹40.0 cr (9.5% of a ₹420 cr capital base)** in the loan book. After its other books are linked and its hidden holding company is merged in, the group is **₹112.0 cr (26.7%)**, which is over the ₹105 cr limit.

## 3. Why the usual fixes fall short

- **Nightly fuzzy-match jobs** hand reviewers a long unranked list. A wrong merge corrupts a group's figure and nothing shows why.
- **Exporting records to an external graph or ML service** moves non-public borrower data out of the bank's perimeter and gives no way to reproduce the answer later.

## 4. What Talos does

Talos resolves records to legal entities and links entities into groups **inside Exasol**, then publishes group exposure only after a person has recorded a decision.

1. **Matching runs in SQL.** Name standardisation, blocking, edit-distance and phonetic scoring, and group formation (label propagation with `MERGE`) all run in the database.
2. **Every match is tiered, and tiers decide presentation, not whether a person is involved.**
   - **T0:** exact PAN, CIN or LEI agreement with a consistent name. Reviewed as a batch by checking a seeded random sample.
   - **T1:** a very close name plus the same pincode. Reviewed one by one.
   - **T2:** the grey band. In this version there is no model verdict, so these stay in the queue marked "no model verdict".
   - **T3:** an ID that agrees while the name does not, or the reverse. These need an explicit rejection or a justified approval.
3. **Decisions are append-only.** A rejection writes a do-not-link record. No role can update or delete evidence.
4. **Every run can be replayed.** A run records the load versions, the policy values and the code version it used, plus a SHA-256 of its output. `talos replay` re-runs it and compares the hash, so a figure can be reproduced as the bank knew it at a given time.
