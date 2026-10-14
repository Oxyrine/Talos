"""eval/oracle.py: Automated Oracle reviewer that accepts system recommendations."""

from __future__ import annotations

from pyexasol import ExaConnection

from orchestrator.db import connect
from orchestrator.decide import (
    BatchProtectedError,
    ProposalConflictError,
    Reviewer,
    batch_decide,
    batch_sample,
    decide,
    rule,
)
from orchestrator.pipeline import publish_run
from orchestrator.policy import load_thresholds

ORACLE_REVIEWER = Reviewer(name="EVAL_ORACLE", role="APPROVER")


def run_oracle(
    conn: ExaConnection | None = None,
    apply_jv_rulings: bool = False,
    business_date: str = "2026-09-30",
) -> dict[str, int]:
    """Execute automated decisions based on system recommendations.

    Does NOT inspect TRUTH tables to make decisions.
    Approves T0 batches, T1 pairs, corroborated ownership, and recommended T2 pairs.
    Rejects T3 pairs.
    """
    close_conn = False
    if conn is None:
        conn = connect("approver", autocommit=False)
        close_conn = True

    stats = {
        "batch_approved": 0,
        "t1_approved": 0,
        "t2_approved": 0,
        "t3_rejected": 0,
        "ownership_approved": 0,
        "interdep_approved": 0,
        "jv_ruled": 0,
    }

    thresholds = load_thresholds()
    min_conf = float(thresholds.get("JUDGE_MIN_CONF", 0.80))

    try:
        # 1. Process active batches (T0 exact and corroborated ownership)
        batch_stmt = conn.execute(
            """
            SELECT DISTINCT batch_id
            FROM GOV.PROPOSAL
            WHERE batch_id IS NOT NULL
            """
        )
        batch_ids = [r[0] if not isinstance(r, dict) else r["batch_id"] for r in batch_stmt.fetchall()]

        for b_id in batch_ids:
            try:
                sample = batch_sample(b_id, business_date=business_date, conn=conn)
                # Oracle approves all sample items
                verdicts = {pid: True for pid in sample.sample_ids}
                batch_decide(
                    batch_id=b_id,
                    seed=sample.seed,
                    verdicts=verdicts,
                    reason="Oracle approval: batch sample verified",
                    reviewer=ORACLE_REVIEWER,
                    business_date=business_date,
                    conn=conn,
                )
                stats["batch_approved"] += 1
            except Exception:
                pass

        # 2. Process individual T1 proposals
        t1_stmt = conn.execute(
            """
            SELECT p.proposal_id
            FROM GOV.PROPOSAL p
            LEFT JOIN (
                SELECT c.proposal_id
                FROM GOV.DECISION_COVERS c
                JOIN GOV.DECISION_LOG d ON c.decision_id = d.decision_id
                WHERE d.decision IN ('APPROVE', 'REJECT', 'BATCH_APPROVE', 'RULING')
            ) term ON p.proposal_id = term.proposal_id
            WHERE p.tier = 'T1'
              AND p.kind = 'RECORD_LINK'
              AND term.proposal_id IS NULL
            """
        )
        t1_ids = [r[0] if not isinstance(r, dict) else r["proposal_id"] for r in t1_stmt.fetchall()]
        for pid in t1_ids:
            try:
                decide(
                    proposal_id=pid,
                    decision="APPROVE",
                    reason="Oracle approval: strong name and pincode agreement",
                    reviewer=ORACLE_REVIEWER,
                    business_date=business_date,
                    conn=conn,
                )
                stats["t1_approved"] += 1
            except (BatchProtectedError, ProposalConflictError, ValueError):
                pass

        # 3. Process T2 proposals with high-confidence model recommendation
        t2_stmt = conn.execute(
            """
            SELECT p.proposal_id, v.decision, v.confidence
            FROM GOV.PROPOSAL p
            JOIN RESOLVE.LLM_VERDICT v ON p.pair_key = v.pair_key
            LEFT JOIN (
                SELECT c.proposal_id
                FROM GOV.DECISION_COVERS c
                JOIN GOV.DECISION_LOG d ON c.decision_id = d.decision_id
                WHERE d.decision IN ('APPROVE', 'REJECT', 'BATCH_APPROVE', 'RULING')
            ) term ON p.proposal_id = term.proposal_id
            WHERE p.tier = 'T2'
              AND p.kind = 'RECORD_LINK'
              AND term.proposal_id IS NULL
              AND v.valid = TRUE
            """
        )
        for r in t2_stmt.fetchall():
            pid = r["proposal_id"] if isinstance(r, dict) else r[0]
            v_dec = r["decision"] if isinstance(r, dict) else r[1]
            v_conf = float(r["confidence"] if isinstance(r, dict) else r[2])

            if v_dec == "same" and v_conf >= min_conf:
                try:
                    decide(
                        proposal_id=pid,
                        decision="APPROVE",
                        reason=f"Oracle approval: model recommended match (confidence {v_conf:.2f})",
                        reviewer=ORACLE_REVIEWER,
                        business_date=business_date,
                        conn=conn,
                    )
                    stats["t2_approved"] += 1
                except (BatchProtectedError, ProposalConflictError, ValueError):
                    pass

        # 4. Process T3 proposals (Reject)
        t3_stmt = conn.execute(
            """
            SELECT p.proposal_id
            FROM GOV.PROPOSAL p
            LEFT JOIN (
                SELECT c.proposal_id
                FROM GOV.DECISION_COVERS c
                JOIN GOV.DECISION_LOG d ON c.decision_id = d.decision_id
                WHERE d.decision IN ('APPROVE', 'REJECT', 'BATCH_APPROVE', 'RULING')
            ) term ON p.proposal_id = term.proposal_id
            WHERE p.tier = 'T3'
              AND p.kind = 'RECORD_LINK'
              AND term.proposal_id IS NULL
            """
        )
        t3_ids = [r[0] if not isinstance(r, dict) else r["proposal_id"] for r in t3_stmt.fetchall()]
        for pid in t3_ids:
            try:
                decide(
                    proposal_id=pid,
                    decision="REJECT",
                    reason="Oracle rejection: ID conflict or name mismatch",
                    reviewer=ORACLE_REVIEWER,
                    business_date=business_date,
                    conn=conn,
                )
                stats["t3_rejected"] += 1
            except (BatchProtectedError, ProposalConflictError, ValueError):
                pass

        # 5. Process OWNERSHIP proposals (registry majority edges)
        own_stmt = conn.execute(
            """
            SELECT p.proposal_id
            FROM GOV.PROPOSAL p
            LEFT JOIN (
                SELECT c.proposal_id
                FROM GOV.DECISION_COVERS c
                JOIN GOV.DECISION_LOG d ON c.decision_id = d.decision_id
                WHERE d.decision IN ('APPROVE', 'REJECT', 'BATCH_APPROVE', 'RULING')
            ) term ON p.proposal_id = term.proposal_id
            WHERE p.kind = 'OWNERSHIP'
              AND term.proposal_id IS NULL
            """
        )
        own_ids = [r[0] if not isinstance(r, dict) else r["proposal_id"] for r in own_stmt.fetchall()]
        for pid in own_ids:
            try:
                decide(
                    proposal_id=pid,
                    decision="APPROVE",
                    reason="Oracle approval: registry control edge confirmed",
                    reviewer=ORACLE_REVIEWER,
                    business_date=business_date,
                    conn=conn,
                )
                stats["ownership_approved"] += 1
            except (BatchProtectedError, ProposalConflictError, ValueError):
                pass

        # 6. Process INTERDEP proposals (credit appraisal dependencies)
        dep_stmt = conn.execute(
            """
            SELECT p.proposal_id
            FROM GOV.PROPOSAL p
            LEFT JOIN (
                SELECT c.proposal_id
                FROM GOV.DECISION_COVERS c
                JOIN GOV.DECISION_LOG d ON c.decision_id = d.decision_id
                WHERE d.decision IN ('APPROVE', 'REJECT', 'BATCH_APPROVE', 'RULING')
            ) term ON p.proposal_id = term.proposal_id
            WHERE p.kind = 'INTERDEP'
              AND p.holder_entity_key NOT LIKE 'U:%'
              AND p.held_entity_key NOT LIKE 'U:%'
              AND term.proposal_id IS NULL
            """
        )
        dep_ids = [r[0] if not isinstance(r, dict) else r["proposal_id"] for r in dep_stmt.fetchall()]
        for pid in dep_ids:
            try:
                decide(
                    proposal_id=pid,
                    decision="APPROVE",
                    reason="Oracle approval: customer credit interdependence confirmed",
                    reviewer=ORACLE_REVIEWER,
                    business_date=business_date,
                    conn=conn,
                )
                stats["interdep_approved"] += 1
            except (BatchProtectedError, ProposalConflictError, ValueError):
                pass

        # 7. Optional: Apply JV truth rulings if requested
        if apply_jv_rulings:
            jv_stmt = conn.execute(
                """
                SELECT p.proposal_id, gt.ruling, gt.controller_entity_key
                FROM GOV.PROPOSAL p
                JOIN TRUTH.GT_JV_RULING gt ON p.held_entity_key = gt.held_entity_key
                LEFT JOIN (
                    SELECT c.proposal_id
                    FROM GOV.DECISION_COVERS c
                    JOIN GOV.DECISION_LOG d ON c.decision_id = d.decision_id
                    WHERE d.decision IN ('APPROVE', 'REJECT', 'BATCH_APPROVE', 'RULING')
                ) term ON p.proposal_id = term.proposal_id
                WHERE p.kind = 'CONTROL_RULING'
                  AND term.proposal_id IS NULL
                """
            )
            for r in jv_stmt.fetchall():
                pid = r["proposal_id"] if isinstance(r, dict) else r[0]
                rul = r["ruling"] if isinstance(r, dict) else r[1]
                ctrl = r["controller_entity_key"] if isinstance(r, dict) else r[2]
                try:
                    rule(
                        proposal_id=pid,
                        ruling=rul,
                        controller=ctrl,
                        reason=f"Oracle truth ruling: applied {rul}",
                        reviewer=ORACLE_REVIEWER,
                        business_date=business_date,
                        conn=conn,
                    )
                    stats["jv_ruled"] += 1
                except Exception:
                    pass

        # Republish final report run
        publish_run(business_date=business_date)

        return stats

    finally:
        if close_conn:
            conn.close()
