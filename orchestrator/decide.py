"""orchestrator/decide.py: Governance decision processing, batch sampling, and JV rulings."""

from __future__ import annotations

import hashlib
import json
import random
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pyexasol import ExaConnection

from orchestrator.db import connect


class BatchProtectedError(Exception):
    """Raised when an individual decision is attempted on a proposal belonging to an active batch."""


class ProposalConflictError(Exception):
    """Raised when a proposal already has a terminal decision (HTTP 409)."""


class UnauthorizedReviewerError(Exception):
    """Raised when an action requires APPROVER role but reviewer is ANALYST (HTTP 403)."""


@dataclass(frozen=True)
class Reviewer:
    name: str
    role: Literal["APPROVER", "ANALYST"]


@dataclass(frozen=True)
class DecisionResult:
    decision_id: str
    decision: str
    proposal_ids: tuple[str, ...]
    decided_at: datetime
    published_run_id: str | None


@dataclass(frozen=True)
class BatchSample:
    batch_id: str
    batch_kind: Literal["RECORD_LINK", "OWNERSHIP"]
    seed: int
    sample_ids: tuple[str, ...]
    covered_ids: tuple[str, ...]
    total_count: int
    sample_count: int


def calculate_sample_size(batch_total: int, batch_kind: str, policy: dict[str, Any] | None = None) -> int:
    """Compute sample size using integer ceiling: -(-pct * batch_total // 100)."""
    if policy is None:
        policy = {}

    if batch_kind == "OWNERSHIP":
        pct = policy.get("OWN_SAMPLE_PCT", 2)
        min_k = policy.get("OWN_SAMPLE_MIN", 20)
    else:
        pct = policy.get("T0_SAMPLE_PCT", 5)
        min_k = policy.get("T0_SAMPLE_MIN", 20)

    calculated = -(-int(pct) * batch_total // 100)
    return min(batch_total, max(int(min_k), calculated))


def _ensure_entity_exists(
    conn: ExaConnection,
    entity_key: str,
    decided_at_str: str,
    decision_id: str,
) -> None:
    """Insert into GRAPH.ENTITY if entity_key has not been published yet."""
    check_stmt = conn.execute(
        "SELECT 1 FROM GRAPH.ENTITY WHERE entity_key = {entity_key}",
        query_params={"entity_key": entity_key},
    )
    if check_stmt.fetchone() is not None:
        return

    cin = entity_key.removeprefix("E:")
    display_name = cin

    # Try resolving display_name from RAW_REGISTRY.ENTITY_FILING
    try:
        name_stmt = conn.execute(
            """
            SELECT entity_name FROM RAW_REGISTRY.ENTITY_FILING
            WHERE cin = {cin}
            ORDER BY loaded_at DESC, filed_on DESC
            LIMIT 1
            """,
            query_params={"cin": cin},
        )
        found_name = name_stmt.fetchval()
        if found_name:
            display_name = str(found_name)
    except Exception:
        pass

    conn.execute(
        """
        INSERT INTO GRAPH.ENTITY (
            entity_key, cin, display_name, first_published_at, decision_id
        ) VALUES (
            {entity_key}, {cin}, {display_name}, {first_published_at}, {decision_id}
        )
        """,
        query_params={
            "entity_key": entity_key,
            "cin": cin,
            "display_name": display_name,
            "first_published_at": decided_at_str,
            "decision_id": decision_id,
        },
    )


def decide(
    proposal_id: str,
    decision: Literal["APPROVE", "REJECT", "DEFER"],
    reason: str,
    reviewer: Reviewer,
    conn: ExaConnection | None = None,
) -> DecisionResult:
    """Execute decision in TALOS_APPROVER transaction.

    Raises BatchProtectedError if proposal has active batch_id.
    """
    if reviewer.role != "APPROVER":
        raise UnauthorizedReviewerError("Only reviewers with role APPROVER may decide proposals.")

    if not (1 <= len(reason) <= 2000):
        raise ValueError("Decision reason must be between 1 and 2000 characters.")

    close_conn = False
    if conn is None:
        conn = connect("approver", autocommit=False)
        close_conn = True

    try:
        # 1. Fetch proposal
        p_stmt = conn.execute(
            """
            SELECT proposal_id, kind, subject_key, rec_key, entity_key,
                   holder_entity_key, held_entity_key, tier, batch_id,
                   evidence_hash, rupee_impact
            FROM GOV.PROPOSAL
            WHERE proposal_id = {proposal_id}
            """,
            query_params={"proposal_id": proposal_id},
        )
        prop_row = p_stmt.fetchone()
        if not prop_row:
            raise ValueError(f"Proposal {proposal_id} not found.")

        if isinstance(prop_row, dict):
            p_kind = prop_row["kind"]
            p_subj = prop_row["subject_key"]
            p_rec = prop_row["rec_key"]
            p_ent = prop_row["entity_key"]
            p_holder = prop_row["holder_entity_key"]
            p_held = prop_row["held_entity_key"]
            p_tier = prop_row["tier"]
            p_batch = prop_row["batch_id"]
            p_ev_hash = prop_row["evidence_hash"]
        else:
            _, p_kind, p_subj, p_rec, p_ent, p_holder, p_held, p_tier, p_batch, p_ev_hash, _ = prop_row

        # 2. Check for existing terminal decision
        term_stmt = conn.execute(
            """
            SELECT d.decision
            FROM GOV.DECISION_COVERS c
            JOIN GOV.DECISION_LOG d ON c.decision_id = d.decision_id
            WHERE c.proposal_id = {proposal_id}
              AND d.decision IN ('APPROVE', 'REJECT', 'BATCH_APPROVE', 'RULING')
            """,
            query_params={"proposal_id": proposal_id},
        )
        if term_stmt.fetchone() is not None:
            raise ProposalConflictError(f"Proposal {proposal_id} already has a terminal decision.")

        # 3. Guard: T0 proposals belonging to an active batch cannot be decided individually unless batch failed
        if p_tier == "T0" and p_batch:
            bf_stmt = conn.execute(
                """
                SELECT 1 FROM GOV.DECISION_LOG
                WHERE batch_id = {batch_id} AND decision = 'BATCH_FAILED'
                """,
                query_params={"batch_id": p_batch},
            )
            if bf_stmt.fetchone() is None:
                raise BatchProtectedError(
                    f"Proposal {proposal_id} belongs to active batch {p_batch}. It must be reviewed via batch."
                )

        # 4. Kind-specific guards
        if p_kind == "RECORD_LINK" and decision == "APPROVE" and p_rec and p_ent:
            # Check if record has active ASSERT to different entity
            act_stmt = conn.execute(
                """
                SELECT entity_key FROM (
                    SELECT entity_key, action,
                           ROW_NUMBER() OVER (PARTITION BY link_key ORDER BY recorded_at DESC, event_id DESC) as rn
                    FROM GRAPH.LINK_EVENT
                    WHERE rec_key = {rec_key}
                ) WHERE rn = 1 AND action = 'ASSERT'
                """,
                query_params={"rec_key": p_rec},
            )
            active_row = act_stmt.fetchone()
            if active_row:
                curr_ent = active_row["entity_key"] if isinstance(active_row, dict) else active_row[0]
                if curr_ent != p_ent:
                    raise ProposalConflictError(
                        f"Record {p_rec} is already asserted to {curr_ent}. Retract it before linking to {p_ent}."
                    )

        if p_kind == "INTERDEP" and decision == "APPROVE":
            if (p_holder and p_holder.startswith("U:")) or (p_held and p_held.startswith("U:")):
                raise ProposalConflictError("Cannot approve INTERDEP proposal with unresolved endpoints.")

        # 5. Insert DECISION_LOG and DECISION_COVERS
        now_dt = datetime.now(UTC)
        decided_at_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        time_tag = now_dt.strftime("%Y%m%d%H%M%S%f")
        dec_id = f"D-{time_tag}-{secrets.token_hex(2)}"
        ev_id = f"EV-{time_tag}-01"

        conn.execute(
            """
            INSERT INTO GOV.DECISION_LOG (
                decision_id, decision, proposal_id, batch_id, ruling,
                reason, reviewer, reviewer_role, decided_at, covered_count
            ) VALUES (
                {decision_id}, {decision}, {proposal_id}, NULL, NULL,
                {reason}, {reviewer}, {reviewer_role}, {decided_at}, 1
            )
            """,
            query_params={
                "decision_id": dec_id,
                "decision": decision,
                "proposal_id": proposal_id,
                "reason": reason,
                "reviewer": reviewer.name,
                "reviewer_role": reviewer.role,
                "decided_at": decided_at_str,
            },
        )

        conn.execute(
            """
            INSERT INTO GOV.DECISION_COVERS (
                decision_id, proposal_id, in_sample
            ) VALUES (
                {decision_id}, {proposal_id}, TRUE
            )
            """,
            query_params={"decision_id": dec_id, "proposal_id": proposal_id},
        )

        # 6. Insert graph events
        if decision == "APPROVE":
            if p_kind == "RECORD_LINK" and p_rec and p_ent:
                conn.execute(
                    """
                    INSERT INTO GRAPH.LINK_EVENT (
                        event_id, link_key, rec_key, entity_key, action,
                        evidence_hash, valid_from, valid_to, recorded_at, decision_id, proposal_id
                    ) VALUES (
                        {event_id}, {link_key}, {rec_key}, {entity_key}, 'ASSERT',
                        {evidence_hash}, '0001-01-01', '9999-12-31', {recorded_at}, {decision_id}, {proposal_id}
                    )
                    """,
                    query_params={
                        "event_id": ev_id,
                        "link_key": f"{p_rec}>{p_ent}",
                        "rec_key": p_rec,
                        "entity_key": p_ent,
                        "evidence_hash": p_ev_hash,
                        "recorded_at": decided_at_str,
                        "decision_id": dec_id,
                        "proposal_id": proposal_id,
                    },
                )
                _ensure_entity_exists(conn, p_ent, decided_at_str, dec_id)

            elif p_kind in ("OWNERSHIP", "INTERDEP", "CONTROLLER_LINK"):
                e_kind = "INTERDEP" if p_kind == "INTERDEP" else "CONTROL"
                c_type = "MAJORITY" if e_kind == "CONTROL" else None
                conn.execute(
                    """
                    INSERT INTO GRAPH.OWNERSHIP_EVENT (
                        event_id, edge_key, holder_entity_key, held_entity_key,
                        edge_kind, control_type, status, stake_pct, action,
                        evidence_hash, valid_from, valid_to, recorded_at, decision_id, proposal_id
                    ) VALUES (
                        {event_id}, {edge_key}, {holder_entity_key}, {held_entity_key},
                        {edge_kind}, {control_type}, 'CONFIRMED', 100.0, 'ASSERT',
                        {evidence_hash}, '0001-01-01', '9999-12-31', {recorded_at}, {decision_id}, {proposal_id}
                    )
                    """,
                    query_params={
                        "event_id": ev_id,
                        "edge_key": p_subj,
                        "holder_entity_key": p_holder or "",
                        "held_entity_key": p_held or "",
                        "edge_kind": e_kind,
                        "control_type": c_type,
                        "evidence_hash": p_ev_hash,
                        "recorded_at": decided_at_str,
                        "decision_id": dec_id,
                        "proposal_id": proposal_id,
                    },
                )

        elif decision == "REJECT":
            if p_kind == "RECORD_LINK" and p_rec and p_ent:
                conn.execute(
                    """
                    INSERT INTO GRAPH.LINK_EVENT (
                        event_id, link_key, rec_key, entity_key, action,
                        evidence_hash, valid_from, valid_to, recorded_at, decision_id, proposal_id
                    ) VALUES (
                        {event_id}, {link_key}, {rec_key}, {entity_key}, 'DNL',
                        {evidence_hash}, '0001-01-01', '9999-12-31', {recorded_at}, {decision_id}, {proposal_id}
                    )
                    """,
                    query_params={
                        "event_id": ev_id,
                        "link_key": f"{p_rec}>{p_ent}",
                        "rec_key": p_rec,
                        "entity_key": p_ent,
                        "evidence_hash": p_ev_hash,
                        "recorded_at": decided_at_str,
                        "decision_id": dec_id,
                        "proposal_id": proposal_id,
                    },
                )
            elif p_kind in ("OWNERSHIP", "INTERDEP"):
                e_kind = "INTERDEP" if p_kind == "INTERDEP" else "CONTROL"
                conn.execute(
                    """
                    INSERT INTO GRAPH.OWNERSHIP_EVENT (
                        event_id, edge_key, holder_entity_key, held_entity_key,
                        edge_kind, control_type, status, stake_pct, action,
                        evidence_hash, valid_from, valid_to, recorded_at, decision_id, proposal_id
                    ) VALUES (
                        {event_id}, {edge_key}, {holder_entity_key}, {held_entity_key},
                        {edge_kind}, NULL, 'REJECTED', 0.0, 'RETRACT',
                        {evidence_hash}, '0001-01-01', '9999-12-31', {recorded_at}, {decision_id}, {proposal_id}
                    )
                    """,
                    query_params={
                        "event_id": ev_id,
                        "edge_key": p_subj,
                        "holder_entity_key": p_holder or "",
                        "held_entity_key": p_held or "",
                        "edge_kind": e_kind,
                        "evidence_hash": p_ev_hash,
                        "recorded_at": decided_at_str,
                        "decision_id": dec_id,
                        "proposal_id": proposal_id,
                    },
                )

        conn.commit()

        # 7. Post-commit trigger publish_run
        published_run_id = None
        try:
            from orchestrator.pipeline import publish_run
            pub_res = publish_run("2026-09-30")
            published_run_id = pub_res.run_id
        except Exception:
            pass

        return DecisionResult(
            decision_id=dec_id,
            decision=decision,
            proposal_ids=(proposal_id,),
            decided_at=now_dt,
            published_run_id=published_run_id,
        )

    except Exception:
        conn.rollback()
        raise
    finally:
        if close_conn:
            conn.close()


def batch_sample(batch_id: str, conn: ExaConnection | None = None) -> BatchSample:
    """Generate deterministic sample for a batch using secrets.randbits(31)."""
    close_conn = False
    if conn is None:
        conn = connect("reader", autocommit=True)
        close_conn = True

    try:
        stmt = conn.execute(
            """
            SELECT p.proposal_id, p.kind
            FROM GOV.PROPOSAL p
            LEFT JOIN (
                SELECT c.proposal_id
                FROM GOV.DECISION_COVERS c
                JOIN GOV.DECISION_LOG d ON c.decision_id = d.decision_id
                WHERE d.decision IN ('APPROVE', 'REJECT', 'BATCH_APPROVE', 'RULING')
            ) term ON p.proposal_id = term.proposal_id
            WHERE p.batch_id = {batch_id}
              AND term.proposal_id IS NULL
            ORDER BY p.proposal_id
            """,
            query_params={"batch_id": batch_id},
        )
        rows = stmt.fetchall()
        if not rows:
            raise ValueError(f"No active proposals found for batch {batch_id}.")

        proposal_ids = [r["proposal_id"] if isinstance(r, dict) else r[0] for r in rows]
        first_kind = rows[0]["kind"] if isinstance(rows[0], dict) else rows[0][1]
        batch_kind: Literal["RECORD_LINK", "OWNERSHIP"] = (
            "OWNERSHIP" if first_kind == "OWNERSHIP" or batch_id.startswith("B-OWN-") else "RECORD_LINK"
        )

        n = len(proposal_ids)
        k = calculate_sample_size(n, batch_kind)
        seed = secrets.randbits(31)
        rng = random.Random(seed)
        sample_ids = tuple(rng.sample(sorted(proposal_ids), k))

        return BatchSample(
            batch_id=batch_id,
            batch_kind=batch_kind,
            seed=seed,
            sample_ids=sample_ids,
            covered_ids=tuple(sorted(proposal_ids)),
            total_count=n,
            sample_count=k,
        )
    finally:
        if close_conn:
            conn.close()


def batch_decide(
    batch_id: str,
    seed: int,
    verdicts: dict[str, bool],
    reason: str,
    reviewer: Reviewer,
    conn: ExaConnection | None = None,
) -> DecisionResult:
    """Process batch review.

    All True -> BATCH_APPROVE covering all proposals.
    Any False -> Failed items get REJECT (DNL), batch marked BATCH_FAILED.
    """
    if reviewer.role != "APPROVER":
        raise UnauthorizedReviewerError("Only reviewers with role APPROVER may decide batches.")

    if not (1 <= len(reason) <= 2000):
        raise ValueError("Decision reason must be between 1 and 2000 characters.")

    close_conn = False
    if conn is None:
        conn = connect("approver", autocommit=False)
        close_conn = True

    try:
        # Fetch all open proposals for batch
        stmt = conn.execute(
            """
            SELECT p.proposal_id, p.kind, p.subject_key, p.rec_key, p.entity_key,
                   p.holder_entity_key, p.held_entity_key, p.evidence_hash
            FROM GOV.PROPOSAL p
            LEFT JOIN (
                SELECT c.proposal_id
                FROM GOV.DECISION_COVERS c
                JOIN GOV.DECISION_LOG d ON c.decision_id = d.decision_id
                WHERE d.decision IN ('APPROVE', 'REJECT', 'BATCH_APPROVE', 'RULING')
            ) term ON p.proposal_id = term.proposal_id
            WHERE p.batch_id = {batch_id}
              AND term.proposal_id IS NULL
            ORDER BY p.proposal_id
            """,
            query_params={"batch_id": batch_id},
        )
        rows = stmt.fetchall()
        if not rows:
            raise ValueError(f"No active proposals found for batch {batch_id}.")

        covered_props = {}
        for r in rows:
            pid = r["proposal_id"] if isinstance(r, dict) else r[0]
            covered_props[pid] = r

        all_passed = all(verdicts.get(pid, False) for pid in verdicts)
        now_dt = datetime.now(UTC)
        decided_at_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        time_tag = now_dt.strftime("%Y%m%d%H%M%S%f")
        dec_id = f"D-{time_tag}-{secrets.token_hex(2)}"

        if all_passed:
            # BATCH_APPROVE
            conn.execute(
                """
                INSERT INTO GOV.DECISION_LOG (
                    decision_id, decision, proposal_id, batch_id, ruling,
                    reason, reviewer, reviewer_role, decided_at, batch_seed, sample_json, covered_count
                ) VALUES (
                    {decision_id}, 'BATCH_APPROVE', NULL, {batch_id}, NULL,
                    {reason}, {reviewer}, {reviewer_role}, {decided_at}, {batch_seed}, {sample_json}, {covered_count}
                )
                """,
                query_params={
                    "decision_id": dec_id,
                    "batch_id": batch_id,
                    "reason": reason,
                    "reviewer": reviewer.name,
                    "reviewer_role": reviewer.role,
                    "decided_at": decided_at_str,
                    "batch_seed": seed,
                    "sample_json": json.dumps(verdicts),
                    "covered_count": len(covered_props),
                },
            )

            idx = 0
            for pid, pdata in covered_props.items():
                idx += 1
                ev_id = f"EV-{time_tag}-{idx:04d}"
                in_sample = (pid in verdicts)

                conn.execute(
                    """
                    INSERT INTO GOV.DECISION_COVERS (decision_id, proposal_id, in_sample)
                    VALUES ({decision_id}, {proposal_id}, {in_sample})
                    """,
                    query_params={"decision_id": dec_id, "proposal_id": pid, "in_sample": in_sample},
                )

                p_kind = pdata["kind"] if isinstance(pdata, dict) else pdata[1]
                p_subj = pdata["subject_key"] if isinstance(pdata, dict) else pdata[2]
                p_rec = pdata["rec_key"] if isinstance(pdata, dict) else pdata[3]
                p_ent = pdata["entity_key"] if isinstance(pdata, dict) else pdata[4]
                p_ev_hash = pdata["evidence_hash"] if isinstance(pdata, dict) else pdata[7]

                if p_kind == "RECORD_LINK" and p_rec and p_ent:
                    conn.execute(
                        """
                        INSERT INTO GRAPH.LINK_EVENT (
                            event_id, link_key, rec_key, entity_key, action,
                            evidence_hash, valid_from, valid_to, recorded_at, decision_id, proposal_id
                        ) VALUES (
                            {event_id}, {link_key}, {rec_key}, {entity_key}, 'ASSERT',
                            {evidence_hash}, '0001-01-01', '9999-12-31', {recorded_at}, {decision_id}, {proposal_id}
                        )
                        """,
                        query_params={
                            "event_id": ev_id,
                            "link_key": f"{p_rec}>{p_ent}",
                            "rec_key": p_rec,
                            "entity_key": p_ent,
                            "evidence_hash": p_ev_hash,
                            "recorded_at": decided_at_str,
                            "decision_id": dec_id,
                            "proposal_id": pid,
                        },
                    )
                    _ensure_entity_exists(conn, p_ent, decided_at_str, dec_id)
                elif p_kind == "OWNERSHIP":
                    p_holder = pdata["holder_entity_key"] if isinstance(pdata, dict) else pdata[5]
                    p_held = pdata["held_entity_key"] if isinstance(pdata, dict) else pdata[6]
                    conn.execute(
                        """
                        INSERT INTO GRAPH.OWNERSHIP_EVENT (
                            event_id, edge_key, holder_entity_key, held_entity_key,
                            edge_kind, control_type, status, stake_pct, action,
                            evidence_hash, valid_from, valid_to, recorded_at, decision_id, proposal_id
                        ) VALUES (
                            {event_id}, {edge_key}, {holder_entity_key}, {held_entity_key},
                            'CONTROL', 'MAJORITY', 'CONFIRMED', 100.0, 'ASSERT',
                            {evidence_hash}, '0001-01-01', '9999-12-31', {recorded_at}, {decision_id}, {proposal_id}
                        )
                        """,
                        query_params={
                            "event_id": ev_id,
                            "edge_key": p_subj,
                            "holder_entity_key": p_holder or "",
                            "held_entity_key": p_held or "",
                            "evidence_hash": p_ev_hash,
                            "recorded_at": decided_at_str,
                            "decision_id": dec_id,
                            "proposal_id": pid,
                        },
                    )

            decision_type = "BATCH_APPROVE"
            covered_ids = tuple(covered_props.keys())

        else:
            # BATCH_FAILED: reject the failed sample items, leave others unlocked
            failed_pids = [pid for pid, passed in verdicts.items() if not passed]
            conn.execute(
                """
                INSERT INTO GOV.DECISION_LOG (
                    decision_id, decision, proposal_id, batch_id, ruling,
                    reason, reviewer, reviewer_role, decided_at, batch_seed, sample_json, covered_count
                ) VALUES (
                    {decision_id}, 'BATCH_FAILED', NULL, {batch_id}, NULL,
                    {reason}, {reviewer}, {reviewer_role}, {decided_at}, {batch_seed}, {sample_json}, {covered_count}
                )
                """,
                query_params={
                    "decision_id": dec_id,
                    "batch_id": batch_id,
                    "reason": reason,
                    "reviewer": reviewer.name,
                    "reviewer_role": reviewer.role,
                    "decided_at": decided_at_str,
                    "batch_seed": seed,
                    "sample_json": json.dumps(verdicts),
                    "covered_count": len(failed_pids),
                },
            )

            idx = 0
            for pid in failed_pids:
                idx += 1
                ev_id = f"EV-{time_tag}-{idx:04d}"
                conn.execute(
                    """
                    INSERT INTO GOV.DECISION_COVERS (decision_id, proposal_id, in_sample)
                    VALUES ({decision_id}, {proposal_id}, TRUE)
                    """,
                    query_params={"decision_id": dec_id, "proposal_id": pid},
                )
                pdata = covered_props[pid]
                p_kind = pdata["kind"] if isinstance(pdata, dict) else pdata[1]
                p_rec = pdata["rec_key"] if isinstance(pdata, dict) else pdata[3]
                p_ent = pdata["entity_key"] if isinstance(pdata, dict) else pdata[4]
                p_ev_hash = pdata["evidence_hash"] if isinstance(pdata, dict) else pdata[7]

                if p_kind == "RECORD_LINK" and p_rec and p_ent:
                    conn.execute(
                        """
                        INSERT INTO GRAPH.LINK_EVENT (
                            event_id, link_key, rec_key, entity_key, action,
                            evidence_hash, valid_from, valid_to, recorded_at, decision_id, proposal_id
                        ) VALUES (
                            {event_id}, {link_key}, {rec_key}, {entity_key}, 'DNL',
                            {evidence_hash}, '0001-01-01', '9999-12-31', {recorded_at}, {decision_id}, {proposal_id}
                        )
                        """,
                        query_params={
                            "event_id": ev_id,
                            "link_key": f"{p_rec}>{p_ent}",
                            "rec_key": p_rec,
                            "entity_key": p_ent,
                            "evidence_hash": p_ev_hash,
                            "recorded_at": decided_at_str,
                            "decision_id": dec_id,
                            "proposal_id": pid,
                        },
                    )

            decision_type = "BATCH_FAILED"
            covered_ids = tuple(failed_pids)

        conn.commit()

        published_run_id = None
        try:
            from orchestrator.pipeline import publish_run
            pub_res = publish_run("2026-09-30")
            published_run_id = pub_res.run_id
        except Exception:
            pass

        return DecisionResult(
            decision_id=dec_id,
            decision=decision_type,
            proposal_ids=covered_ids,
            decided_at=now_dt,
            published_run_id=published_run_id,
        )

    except Exception:
        conn.rollback()
        raise
    finally:
        if close_conn:
            conn.close()


def rule(
    proposal_id: str,
    ruling: Literal["SINGLE", "JOINT", "NONE", "CONNECTED"],
    controller: str | None,
    reason: str,
    reviewer: Reviewer,
    conn: ExaConnection | None = None,
) -> DecisionResult:
    """Resolve Joint Venture control ambiguity with atomic event generation."""
    if reviewer.role != "APPROVER":
        raise UnauthorizedReviewerError("Only reviewers with role APPROVER may issue rulings.")

    if not (1 <= len(reason) <= 2000):
        raise ValueError("Ruling reason must be between 1 and 2000 characters.")

    if ruling == "SINGLE" and not controller:
        raise ValueError("A controller entity key is required when ruling is SINGLE.")

    if ruling == "CONNECTED" and len(reason) < 20:
        raise ValueError("CONNECTED ruling requires at least 20 characters of evidence text.")

    close_conn = False
    if conn is None:
        conn = connect("approver", autocommit=False)
        close_conn = True

    try:
        p_stmt = conn.execute(
            """
            SELECT proposal_id, kind, held_entity_key, evidence_json, evidence_hash
            FROM GOV.PROPOSAL
            WHERE proposal_id = {proposal_id}
            """,
            query_params={"proposal_id": proposal_id},
        )
        prop = p_stmt.fetchone()
        if not prop:
            raise ValueError(f"Proposal {proposal_id} not found.")

        held_key = prop["held_entity_key"] if isinstance(prop, dict) else prop[2]
        ev_hash = prop["evidence_hash"] if isinstance(prop, dict) else prop[4]
        ev_json_str = prop["evidence_json"] if isinstance(prop, dict) else prop[3]

        holders: list[str] = []
        try:
            ev_data = json.loads(ev_json_str)
            holders = ev_data.get("holders", [])
        except Exception:
            pass

        now_dt = datetime.now(UTC)
        decided_at_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        time_tag = now_dt.strftime("%Y%m%d%H%M%S%f")
        dec_id = f"D-{time_tag}-{secrets.token_hex(2)}"

        # 1. Write DECISION_LOG & DECISION_COVERS
        conn.execute(
            """
            INSERT INTO GOV.DECISION_LOG (
                decision_id, decision, proposal_id, batch_id, ruling,
                reason, reviewer, reviewer_role, decided_at, covered_count
            ) VALUES (
                {decision_id}, 'RULING', {proposal_id}, NULL, {ruling},
                {reason}, {reviewer}, {reviewer_role}, {decided_at}, 1
            )
            """,
            query_params={
                "decision_id": dec_id,
                "proposal_id": proposal_id,
                "ruling": ruling,
                "reason": reason,
                "reviewer": reviewer.name,
                "reviewer_role": reviewer.role,
                "decided_at": decided_at_str,
            },
        )

        conn.execute(
            """
            INSERT INTO GOV.DECISION_COVERS (decision_id, proposal_id, in_sample)
            VALUES ({decision_id}, {proposal_id}, TRUE)
            """,
            query_params={"decision_id": dec_id, "proposal_id": proposal_id},
        )

        # 2. Write GRAPH.RULING_EVENT
        ruling_ev_id = f"EV-{time_tag}-00"
        conn.execute(
            """
            INSERT INTO GRAPH.RULING_EVENT (
                event_id, ruling_key, held_entity_key, ruling,
                controller_entity_key, valid_from, valid_to, recorded_at, decision_id, proposal_id
            ) VALUES (
                {event_id}, {ruling_key}, {held_entity_key}, {ruling},
                {controller}, '0001-01-01', '9999-12-31', {recorded_at}, {decision_id}, {proposal_id}
            )
            """,
            query_params={
                "event_id": ruling_ev_id,
                "ruling_key": f"JV:{held_key}",
                "held_entity_key": held_key,
                "ruling": ruling,
                "controller": controller,
                "recorded_at": decided_at_str,
                "decision_id": dec_id,
                "proposal_id": proposal_id,
            },
        )

        # 3. Write OWNERSHIP_EVENTs based on ruling
        for idx, h_key in enumerate(holders, start=1):
            edge_ev_id = f"EV-{time_tag}-{idx:02d}"
            edge_key = f"CONTROL:{h_key}>{held_key}"

            if ruling == "SINGLE":
                if h_key == controller:
                    c_type, status = "MAJORITY", "CONFIRMED"
                else:
                    c_type, status = "MINORITY", "CONFIRMED"
            elif ruling in ("JOINT", "CONNECTED"):
                c_type, status = "JOINT", "CONFIRMED"
            else:  # NONE
                c_type, status = "UNKNOWN", "REJECTED"

            conn.execute(
                """
                INSERT INTO GRAPH.OWNERSHIP_EVENT (
                    event_id, edge_key, holder_entity_key, held_entity_key,
                    edge_kind, control_type, status, stake_pct, action,
                    evidence_hash, valid_from, valid_to, recorded_at, decision_id, proposal_id
                ) VALUES (
                    {event_id}, {edge_key}, {holder_entity_key}, {held_entity_key},
                    'CONTROL', {control_type}, {status}, 50.0, 'ASSERT',
                    {evidence_hash}, '0001-01-01', '9999-12-31', {recorded_at}, {decision_id}, {proposal_id}
                )
                """,
                query_params={
                    "event_id": edge_ev_id,
                    "edge_key": edge_key,
                    "holder_entity_key": h_key,
                    "held_entity_key": held_key,
                    "control_type": c_type,
                    "status": status,
                    "evidence_hash": ev_hash,
                    "recorded_at": decided_at_str,
                    "decision_id": dec_id,
                    "proposal_id": proposal_id,
                },
            )

        # 4. If CONNECTED, file CONTROLLER_LINK proposal between controllers
        if ruling == "CONNECTED" and len(holders) >= 2:
            hA, hB = holders[0], holders[1]
            ctrl_subj = f"INTERDEP:{hA}>{hB}"
            ctrl_ev_hash = hashlib.sha256(reason.encode("utf-8")).hexdigest()
            ctrl_prop_id = f"P-{hashlib.sha256((ctrl_subj + ctrl_ev_hash).encode()).hexdigest()[:12]}"

            conn.execute(
                """
                INSERT INTO GOV.PROPOSAL (
                    proposal_id, kind, subject_key, holder_entity_key, held_entity_key,
                    tier, tier_reason, evidence_json, evidence_hash, rupee_impact,
                    filed_at, pipeline_version
                ) VALUES (
                    {proposal_id}, 'CONTROLLER_LINK', {subject_key}, {hA}, {hB},
                    'T1', 'CONNECTED_CONTROLLERS', {evidence_json}, {evidence_hash}, 0.0,
                    {filed_at}, 'v1'
                )
                """,
                query_params={
                    "proposal_id": ctrl_prop_id,
                    "subject_key": ctrl_subj,
                    "hA": hA,
                    "hB": hB,
                    "evidence_json": json.dumps({"reason": reason, "controllers": [hA, hB]}),
                    "evidence_hash": ctrl_ev_hash,
                    "filed_at": decided_at_str,
                },
            )

        conn.commit()

        published_run_id = None
        try:
            from orchestrator.pipeline import publish_run
            pub_res = publish_run("2026-09-30")
            published_run_id = pub_res.run_id
        except Exception:
            pass

        return DecisionResult(
            decision_id=dec_id,
            decision="RULING",
            proposal_ids=(proposal_id,),
            decided_at=now_dt,
            published_run_id=published_run_id,
        )

    except Exception:
        conn.rollback()
        raise
    finally:
        if close_conn:
            conn.close()
