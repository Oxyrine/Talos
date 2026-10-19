# Talos: 3-Minute Video Submission & 15-Minute Finals Script

---

# Part 1: Official 3-Minute Video Submission Script

**Target Duration**: 02:55 – 03:00  
**Presenter**: Lead Architect & Presenter (Aakash A)  
**Resolution**: 1920x1080 @ 60 FPS (Dark Theme, High Contrast)

---

### [00:00 – 00:35] Beat 1: The Invisible Concentration Crisis
**Visual**:
* Start full-screen on the **Exposure Board** (`http://localhost:8000/board`).
* Cursor points to the Top KPI Ribbon: `Hidden Exposure: ₹0.0 cr`, `Limit Breaches: 0`.
* Scroll down to row 17: **Sunrise Industries Group**.
* Cursor highlights the reported figure: **₹40.00 cr (9.52%)** with compliant green badge.

**Voiceover (Spoken)**:
> *"Every major banking failure begins with an invisible group concentration.  
> Under the RBI's Large Exposures Framework, a bank's exposure to a connected group must never breach 25% of its capital base, with mandatory statutory disclosures at 10%.  
> Look at our core loan book: Sunrise Industries shows an exposure of just ₹40.00 crore—under 10% of our ₹420 crore capital base. To our loan origination system, Sunrise is a safe, compliant borrower.  
> But in reality, the bank holds commercial papers in Treasury, performance bonds in Trade Finance, and facilities across hidden subsidiaries.  
> This is Talos: an in-database credit risk and entity resolution engine that runs entirely inside Exasol with zero external API calls."*

---

### [00:35 – 01:15] Beat 2: Deterministic Sampling & The 10% Large Exposure Line
**Visual**:
* Click on **Review Queue** (`/queue`).
* Banner at top: `Exact-ID Record Links Batch (1,912 matches waiting)`. Click **[Review Sample Batch]**.
* Cursor scrolls through the 96 seed-verified sample pairs showing explicit radio buttons `[✓ Approve] [✗ Reject]`.
* Click **[Submit Batch Decision & Sign Audit Trail]**.
* Banner 2: `Corroborated Ownership Edges Batch (3,540 edges)`. Click **[Review Sample Batch]** and submit approval.
* Return to **Exposure Board** (`/board`).
* Highlight the dynamic jump: Sunrise Group jumps from **₹40.00 cr** to **₹58.20 cr (13.86%)**.
* Cursor points to the SVG gauge: the amber needle crosses the **10% Large Exposure Threshold**.
* KPI Ribbon updates: `Hidden Exposure Unmasked: +₹18.20 cr`.

**Voiceover (Spoken)**:
> *"Instead of reviewing 5,000 routine links one by one, Talos groups exact PAN and corroborated MCA registry edges into cryptographically bounded batches.  
> Our risk officer inspects a seed-verified sample of pairs using explicit approve/reject radio buttons. One invalid pair fails the entire batch.  
> When we approve the batches, Exasol recursively builds the connected group in SQL.  
> Instantly, Sunrise Group expands to ₹58.20 crore. The amber needle crosses the 10% statutory threshold. Our bank is now officially carrying a Large Exposure that was previously invisible."*

---

### [01:15 – 01:55] Beat 3: Human-in-the-Loop T1 Fuzzy Match & T3 Decoy Rejection
**Visual**:
* Navigate back to **Review Queue** (`/queue`).
* Show Proposal Card 1: `P-REC-GTE-SUNRISE-TRUE` (Trade Guarantee of ₹17.40 cr). Side-by-side card shows missing PAN in book, but 94% name similarity and identical Nariman Point pincode. Click **[✓ Approve Link]**.
* Notice HTMX updates the card inline with zero page refresh, swapping the header KPI ribbon out-of-band.
* Show Proposal Card 2: `P-REC-GTE-SUNRISE-CONFLICT`. A decoy record carrying Kaveri Chemicals PAN with Sunrise name.
* Highlight the red conflict chip. Click **[✗ Reject Link]**.

**Voiceover (Spoken)**:
> *"For facilities without statutory PANs, Talos calculates Jaccard token similarity and address distance in-database.  
> In trade guarantees, we find a ₹17.40 crore facility with missing PAN, but matching registered address. Our approver confirms the link.  
> Right below it is our planted decoy: a borrower carrying a Kaveri Chemicals PAN entered by mistake in branch operations. A naive fuzzy match would merge Kaveri Chemicals into Sunrise, creating a catastrophic false merge.  
> Talos flags this as Tier 3 ID-Name conflict. Our reviewer rejects the link, writing an immutable DO-NOT-LINK barrier into the audit log."*

---

### [01:55 – 02:35] Beat 4: The Holding Company Unmasking & 25% Regulatory Breach
**Visual**:
* In Review Queue, show Proposal Card 3: `P-OWN-SUNRISE-HOLDCO`.
* Heading alert: `⚠ REGULATORY BREACH WARNING: Approving merges Sunrise Finvest Group into Sunrise Industries, pushing group exposure to 26.7% (Limit: 25.0%)`.
* Click **[✓ Approve Link]**.
* Immediately redirect to **Exposure Board** (`/board`).
* Row 1: Sunrise Group is now **₹112.00 cr (26.67%)**.
* The regulatory meter fill pulses bright red beyond the 25% limit line.
* Status badge glows: **LIMIT BREACH**.
* Click **[Lineage →]** (`/lineage/group/GRP-017`).
* Show the recursive ownership tree rendered with Exasol's `CONNECT BY`, showing `Sunrise Finvest Private Limited` consolidated.

**Voiceover (Spoken)**:
> *"Here is the critical discovery: Sunrise Industries secretly owns 100% of an unlisted holding vehicle, Sunrise Finvest.  
> That holding vehicle was already on our balance sheet for ₹36.40 crore, but reported under a completely separate group code.  
> When we approve the parent-child registry link, Exasol dissolves the boundary and merges both groups.  
> Sunrise Group explodes to ₹112.00 crore—over 26.6% of our capital base. The regulatory limit is officially breached.  
> In our Lineage screen, the Chief Risk Officer can inspect the full recursive ownership hierarchy and trace every single rupee back to individual loan contracts."*

---

### [02:35 – 03:00] Beat 5: Deterministic Audit Trail & Exasol In-DB Supremacy
**Visual**:
* Click on **Audit Trail** (`/audit`).
* Show table of immutable execution runs with SHA-256 output hashes.
* Click **[⚡ Verify Replay]** on the latest run.
* Inline badge switches to: `✓ REPLAY MATCH • a1b2c3d4e5f6... (100% Deterministic)`.
* Transition to final closing title card:  
  **TALOS: Deterministic Group Risk Engine for Exasol (Track 01)**  
  *Zero External APIs • 100% In-Database SQL • Paisa-Exact Regulatory Governance*

**Voiceover (Spoken)**:
> *"Every single calculation, candidate blocking path, and human decision is cryptographically signed.  
> With one click, an auditor can trigger an in-process replay that re-runs the entire pipeline and verifies the output hash bit-for-bit.  
> Zero sensitive credit data leaves the database. Zero black-box LLM hallucinations.  
> Talos turns Exasol into an impenetrable fortress for regulatory compliance. Thank you."*

---

# Part 2: 15-Minute Live Finals Q&A Defense Guide

### Question 1 (Regulatory Focus):
**Judge**: *"HoldCo's ₹36.4 cr was already on your loan book under its own name, so in what sense is that exposure 'hidden'?"*

**Architect Response (Verbatim)**:
> *"The exposure was not hidden from the general ledger—it was hidden from the **Group Perimeter Boundary**.  
> Under RBI LEF Master Circular §5.1, concentration limits apply to connected borrower groups, not individual legal entities. The bank knew about the ₹36.40 crore loan, but classified it under an unrelated standalone group code with 8.67% utilisation.  
> By missing the MCA holding company link, the bank's reported credit concentration for Sunrise was understated by ₹72.00 crore, concealing a catastrophic statutory limit breach. In regulatory compliance, an aggregation perimeter error is an illegal breach."*

---

### Question 2 (Exasol Performance & Scalability):
**Judge**: *"Why do entity resolution and graph traversal inside Exasol instead of exporting to Neo4j or running Spark GraphX?"*

**Architect Response (Verbatim)**:
> *"Three reasons: Security, Bitemporality, and Transactional Atomicity.  
> First, exporting 250,000 banking records with unmasked PANs and credit facilities to external graph databases breaks banking secrecy and RBI data residency mandates.  
> Second, external graph engines lack native bitemporal transaction support (`business_date` vs `known_at`). Exasol's columnar engine allows us to query exactly what the credit committee knew as of 5:00 PM on the quarter-end closing date.  
> Third, Exasol's massively parallel columnar execution solves our blocking indices via parallel hash joins in milliseconds—giving us 99.96% candidate reduction purely in SQL."*

---

### Question 3 (Human Reviewer Feasibility):
**Judge**: *"Banks process hundreds of thousands of borrowers. Won't human-in-the-loop review overwhelm your credit officers?"*

**Architect Response (Verbatim)**:
> *"No, because of our two-tier triage architecture:  
> Over 95% of edges fall into Tier 0 (exact PAN/CIN matches) or corroborated registry batches. Using our integer-based sampling protocol with strict 2% and 5% sample rates, a reviewer only inspects 70 to 90 pairs to approve an entire batch of 3,500 edges.  
> For the remaining individual cards, our live regulatory impact ranking orders proposals by `crosses_limit DESC, crosses_le DESC, rupee_impact DESC`. The Chief Risk Officer only inspects the top 20 cards that actually threaten capital limits, keeping daily review time under 15 minutes."*
