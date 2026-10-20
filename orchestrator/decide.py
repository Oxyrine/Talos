"""orchestrator/decide.py: Governance decision processing, batch sampling, and JV rulings."""

from __future__ import annotations

import hashlib
import json
import random
import secrets
import warnings
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

from pyexasol import ExaConnection

from orchestrator.db import REPO_ROOT, connect
from orchestrator.loader import insert_rows
from orchestrator.policy import policy_in_force


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


_ACTIVE_BATCH_SEEDS: dict[str, int] = {}


def _record_batch_seed(batch_id: str, seed: int) -> None:
    """Record active seed for batch in memory and .talos/batch_seeds.json."""
    _ACTIVE_BATCH_SEEDS[batch_id] = seed
    try:
        seeds_dir = REPO_ROOT / ".talos"
        seeds_dir.mkdir(parents=True, exist_ok=True)
        seeds_file = seeds_dir / "batch_seeds.json"
        data = {}
        if seeds_file.is_file():
            try:
                data = json.loads(seeds_file.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        data[batch_id] = seed
        seeds_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        warnings.warn(f"Failed to persist batch seed to .talos/batch_seeds.json: {e}", stacklevel=2)


def _get_active_batch_seed(batch_id: str) -> int | None:
    """Retrieve the seed issued by batch_sample for a batch."""
    if batch_id in _ACTIVE_BATCH_SEEDS:
        return _ACTIVE_BATCH_SEEDS[batch_id]
    seeds_file = REPO_ROOT / ".talos" / "batch_seeds.json"
    if seeds_file.is_file():
        try:
            data = json.loads(seeds_file.read_text(encoding="utf-8"))
            if batch_id in data:
                seed = int(data[batch_id])
                _ACTIVE_BATCH_SEEDS[batch_id] = seed
                return seed
        except Exception:
            pass
    return None


def _clear_batch_seed(batch_id: str) -> None:
    """Remove active seed for batch once decided."""
    _ACTIVE_BATCH_SEEDS.pop(batch_id, None)
    seeds_file = REPO_ROOT / ".talos" / "batch_seeds.json"
    if seeds_file.is_file():
        try:
            data = json.loads(seeds_file.read_text(encoding="utf-8"))
            if batch_id in data:
                del data[batch_id]
                seeds_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass


def _extract_holder_stake(ev_data: dict[str, Any], h_key: str, proposal_id: str) -> float:
    """Extract declared stake_pct for a holder from evidence, raising if absent."""
    stakes = ev_data.get("stakes")
    if isinstance(stakes, dict) and h_key in stakes:
        return float(stakes[h_key])

    holders_raw = ev_data.get("holders")
    if isinstance(holders_raw, list):
        for item in holders_raw:
            if isinstance(item, dict):
                key = item.get("holder_entity_key") or item.get("holder") or item.get("entity_key")
                if key == h_key and "stake_pct" in item:
                    return float(item["stake_pct"])

    if "stake_pct" in ev_data:
        return float(ev_data["stake_pct"])

    raise ValueError(f"Proposal {proposal_id} evidence missing required 'stake_pct' for holder {h_key}.")


def calculate_sample_size(batch_total: int, batch_kind: str, policy: dict[str, Any]) -> int:
    """Compute sample size using integer ceiling: -(-pct * batch_total // 100).

    Strictly reads percentages and minimums from policy without fallback defaults (DEV-13).
    """
    if batch_kind == "OWNERSHIP":
        pct = policy["OWN_SAMPLE_PCT"]
        min_k = policy["OWN_SAMPLE_MIN"]
    else:
        pct = policy["T0_SAMPLE_PCT"]
        min_k = policy["T0_SAMPLE_MIN"]

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
        row = name_stmt.fetchone()
        if row and row.get("entity_name"):
            display_name = row["entity_name"]
    except Exception as e:
        warnings.warn(f"Failed to lookup entity name for {cin}: {e}", stacklevel=2)

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


# A proposal is superseded once a later proposal of the same kind is filed for its subject
# (the pipeline re-files when the evidence changes). Superseded proposals cannot be decided.
NOT_SUPERSEDED_SQL = (
    "NOT EXISTS (SELECT 1 FROM GOV.PROPOSAL n WHERE n.kind = p.kind "
    "AND n.subject_key = p.subject_key AND n.filed_at > p.filed_at)"
)


def _raise_if_superseded(conn: ExaConnection, proposal_id: str) -> None:
    """Raise ProposalConflictError if a newer proposal replaced this one."""
    newer = conn.execute(
        """
        SELECT n.proposal_id
        FROM GOV.PROPOSAL p
        JOIN GOV.PROPOSAL n
          ON n.kind = p.kind AND n.subject_key = p.subject_key AND n.filed_at > p.filed_at
        WHERE p.proposal_id = {superseded_pid}
        ORDER BY n.filed_at DESC, n.proposal_id DESC
        LIMIT 1
        """,
        query_params={"superseded_pid": proposal_id},
    ).fetchone()
    if newer is not None:
        raise ProposalConflictError(
            f"Proposal {proposal_id} was superseded by {newer['proposal_id']} (newer evidence)."
        )


def decide(
    proposal_id: str,
    decision: Literal["APPROVE", "REJECT", "DEFER"],
    reason: str,
    reviewer: Reviewer,
    business_date: str | date,
    conn: ExaConnection | None = None,
    publish: bool = True,
) -> DecisionResult:
    """Execute decision in TALOS_APPROVER transaction.

    Raises BatchProtectedError if proposal has active batch_id.
    """
    if reviewer.role != "APPROVER":
        raise UnauthorizedReviewerError("Only reviewers with role APPROVER may decide proposals.")

    if not (1 <= len(reason) <= 2000):
        raise ValueError("Decision reason must be between 1 and 2000 characters.")

    bd_str = business_date.isoformat() if isinstance(business_date, date) else str(business_date)

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
                   evidence_json, evidence_hash, rupee_impact
            FROM GOV.PROPOSAL
            WHERE proposal_id = {proposal_id}
            """,
            query_params={"proposal_id": proposal_id},
        )
        prop = p_stmt.fetchone()
        if not prop:
            raise ValueError(f"Proposal {proposal_id} not found.")

        p_kind = prop["kind"]
        if p_kind == "CONTROL_RULING":
            raise ValueError(
                f"Proposal {proposal_id} is a CONTROL_RULING; decide it with rule() "
                "(ruling NONE records that no control applies)."
            )
        _raise_if_superseded(conn, proposal_id)
        p_subj = prop["subject_key"]
        p_rec = prop["rec_key"]
        p_ent = prop["entity_key"]
        p_holder = prop["holder_entity_key"]
        p_held = prop["held_entity_key"]
        p_batch = prop["batch_id"]
        p_ev_json = prop["evidence_json"]
        p_ev_hash = prop["evidence_hash"]

        # Parse evidence details
        if p_ev_json:
            try:
                ev_data = json.loads(p_ev_json)
            except Exception as e:
                raise ValueError(f"Proposal {proposal_id} evidence_json is invalid JSON: {e}") from e
        else:
            ev_data = {}

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

        # 3. Guard: All proposals belonging to an active batch cannot be decided individually unless batch failed
        if p_batch:
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

        # 4. Kind-specific guards & endpoint validation
        if p_kind in ("OWNERSHIP", "INTERDEP", "CONTROLLER_LINK"):
            if not p_holder or not p_held or p_holder.strip() == "" or p_held.strip() == "":
                raise ValueError(f"Proposal {proposal_id} is missing required endpoints: holder={p_holder}, held={p_held}")

        if p_kind == "RECORD_LINK" and decision == "APPROVE" and p_rec and p_ent:
            # Check if record has active ASSERT to a different entity
            act_stmt = conn.execute(
                """
                SELECT entity_key FROM (
                    SELECT entity_key, "ACTION",
                           ROW_NUMBER() OVER (PARTITION BY link_key ORDER BY recorded_at DESC, event_id DESC) as rn
                    FROM GRAPH.LINK_EVENT
                    WHERE rec_key = {rec_key}
                ) WHERE rn = 1 AND "ACTION" = 'ASSERT'
                """,
                query_params={"rec_key": p_rec},
            )
            active_row = act_stmt.fetchone()
            if active_row:
                curr_ent = active_row["entity_key"]
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
                        event_id, link_key, rec_key, entity_key, "ACTION",
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
                # Read true stake_pct and effective_from from proposal evidence
                valid_from = ev_data.get("effective_from")
                if not valid_from or str(valid_from).strip() == "":
                    raise ValueError(f"Proposal {proposal_id} evidence missing required 'effective_from'.")

                if p_kind == "OWNERSHIP":
                    stake_raw = ev_data.get("stake_pct") if "stake_pct" in ev_data else ev_data.get("share_pct")
                    if stake_raw is None:
                        raise ValueError(f"Proposal {proposal_id} evidence missing required 'stake_pct'.")
                    stake_pct = Decimal(str(stake_raw))
                else:
                    stake_pct = Decimal(str(ev_data.get("stake_pct", 0.0)))

                conn.execute(
                    """
                    INSERT INTO GRAPH.OWNERSHIP_EVENT (
                        event_id, edge_key, holder_entity_key, held_entity_key,
                        edge_kind, control_type, status, stake_pct, "ACTION",
                        evidence_hash, valid_from, valid_to, recorded_at, decision_id, proposal_id
                    ) VALUES (
                        {event_id}, {edge_key}, {holder_entity_key}, {held_entity_key},
                        {edge_kind}, {control_type}, 'CONFIRMED', {stake_pct}, 'ASSERT',
                        {evidence_hash}, {valid_from}, '9999-12-31', {recorded_at}, {decision_id}, {proposal_id}
                    )
                    """,
                    query_params={
                        "event_id": ev_id,
                        "edge_key": p_subj,
                        "holder_entity_key": p_holder,
                        "held_entity_key": p_held,
                        "edge_kind": e_kind,
                        "control_type": c_type,
                        "stake_pct": float(stake_pct),
                        "evidence_hash": p_ev_hash,
                        "valid_from": valid_from,
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
                        event_id, link_key, rec_key, entity_key, "ACTION",
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
                valid_from = "0001-01-01"  # a rejection spans all time, whatever the edge's effective date
                conn.execute(
                    """
                    INSERT INTO GRAPH.OWNERSHIP_EVENT (
                        event_id, edge_key, holder_entity_key, held_entity_key,
                        edge_kind, control_type, status, stake_pct, "ACTION",
                        evidence_hash, valid_from, valid_to, recorded_at, decision_id, proposal_id
                    ) VALUES (
                        {event_id}, {edge_key}, {holder_entity_key}, {held_entity_key},
                        {edge_kind}, NULL, 'REJECTED', 0.0, 'RETRACT',
                        {evidence_hash}, {valid_from}, '9999-12-31', {recorded_at}, {decision_id}, {proposal_id}
                    )
                    """,
                    query_params={
                        "event_id": ev_id,
                        "edge_key": p_subj,
                        "holder_entity_key": p_holder,
                        "held_entity_key": p_held,
                        "edge_kind": e_kind,
                        "evidence_hash": p_ev_hash,
                        "valid_from": valid_from,
                        "recorded_at": decided_at_str,
                        "decision_id": dec_id,
                        "proposal_id": proposal_id,
                    },
                )

        conn.commit()

        # 7. Post-commit trigger publish_run
        published_run_id = None
        if publish:  # the eval oracle publishes once after all its decisions
            try:
                from orchestrator.pipeline import publish_run
                pub_res = publish_run(business_date=bd_str)
                published_run_id = pub_res.run_id
            except Exception as e:
                warnings.warn(f"publish_run after decision failed: {e}", stacklevel=2)

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


def batch_sample(
    batch_id: str,
    business_date: str | date,
    conn: ExaConnection | None = None,
) -> BatchSample:
    """Generate deterministic sample for a batch using secrets.randbits(31).

    Must connect as approver (not reader), as reader cannot SELECT on GOV schema.
    """
    close_conn = False
    if conn is None:
        conn = connect("approver", autocommit=True)
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
              AND {not_superseded}
            ORDER BY p.proposal_id
            """.replace("{not_superseded}", NOT_SUPERSEDED_SQL),
            query_params={"batch_id": batch_id},
        )
        rows = stmt.fetchall()
        if not rows:
            raise ValueError(f"No active proposals found for batch {batch_id}.")

        proposal_ids = [r["proposal_id"] for r in rows]
        first_kind = rows[0]["kind"]
        batch_kind: Literal["RECORD_LINK", "OWNERSHIP"] = (
            "OWNERSHIP" if first_kind == "OWNERSHIP" or batch_id.startswith("B-OWN-") else "RECORD_LINK"
        )

        n = len(proposal_ids)
        bd_str = business_date.isoformat() if isinstance(business_date, date) else str(business_date)
        policy_vals, _ = policy_in_force(conn, bd_str, datetime.now(UTC))
        k = calculate_sample_size(n, batch_kind, policy_vals)
        seed = secrets.randbits(31)
        _record_batch_seed(batch_id, seed)
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
    business_date: str | date,
    conn: ExaConnection | None = None,
    publish: bool = True,
) -> DecisionResult:
    """Process batch review with strict sample verification.

    Recomputes the sample from seed and requires verdicts for exactly those IDs.
    All True -> BATCH_APPROVE covering all proposals.
    Any False -> Failed items get REJECT (DNL), batch marked BATCH_FAILED.
    """
    if reviewer.role != "APPROVER":
        raise UnauthorizedReviewerError("Only reviewers with role APPROVER may decide batches.")

    if not (1 <= len(reason) <= 2000):
        raise ValueError("Decision reason must be between 1 and 2000 characters.")

    active_seed = _get_active_batch_seed(batch_id)
    if active_seed is not None and seed != active_seed:
        raise ValueError(
            f"Provided seed {seed} does not match active sample seed {active_seed} issued for batch {batch_id}."
        )

    bd_str = business_date.isoformat() if isinstance(business_date, date) else str(business_date)

    close_conn = False
    if conn is None:
        conn = connect("approver", autocommit=False)
        close_conn = True

    try:
        # Fetch all open proposals for batch
        stmt = conn.execute(
            """
            SELECT p.proposal_id, p.kind, p.subject_key, p.rec_key, p.entity_key,
                   p.holder_entity_key, p.held_entity_key, p.evidence_json, p.evidence_hash
            FROM GOV.PROPOSAL p
            LEFT JOIN (
                SELECT c.proposal_id
                FROM GOV.DECISION_COVERS c
                JOIN GOV.DECISION_LOG d ON c.decision_id = d.decision_id
                WHERE d.decision IN ('APPROVE', 'REJECT', 'BATCH_APPROVE', 'RULING')
            ) term ON p.proposal_id = term.proposal_id
            WHERE p.batch_id = {batch_id}
              AND term.proposal_id IS NULL
              AND {not_superseded}
            ORDER BY p.proposal_id
            """.replace("{not_superseded}", NOT_SUPERSEDED_SQL),
            query_params={"batch_id": batch_id},
        )
        rows = stmt.fetchall()
        if not rows:
            raise ValueError(f"No active proposals found for batch {batch_id}.")

        covered_props = {r["proposal_id"]: r for r in rows}
        first_kind = rows[0]["kind"]
        batch_kind = "OWNERSHIP" if first_kind == "OWNERSHIP" or batch_id.startswith("B-OWN-") else "RECORD_LINK"

        # Recompute expected sample from seed
        now_dt = datetime.now(UTC)
        policy_vals, _ = policy_in_force(conn, bd_str, now_dt)
        sample_k = calculate_sample_size(len(covered_props), batch_kind, policy_vals)

        rng = random.Random(seed)
        expected_sample_ids = set(rng.sample(sorted(covered_props.keys()), sample_k))

        # Strict check: verdicts must contain verdicts for EXACTLY the sampled IDs
        if set(verdicts.keys()) != expected_sample_ids:
            raise ValueError(
                f"Verdicts keys {set(verdicts.keys())} do not match expected sample IDs {expected_sample_ids} for seed {seed}."
            )

        all_passed = all(verdicts[pid] is True for pid in expected_sample_ids)
        decided_at_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        time_tag = now_dt.strftime("%Y%m%d%H%M%S%f")
        dec_id = f"D-{time_tag}-{secrets.token_hex(2)}"
        sample_json_str = json.dumps({pid: verdicts[pid] for pid in sorted(expected_sample_ids)})

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
                    "sample_json": sample_json_str,
                    "covered_count": len(covered_props),
                },
            )

            # Single atomic insert into GOV.DECISION_COVERS with computed in_sample (no UPDATE)
            sample_ids_sql = ", ".join(f"'{pid}'" for pid in sorted(expected_sample_ids))
            covered_ids_sql = ", ".join(f"'{pid}'" for pid in sorted(covered_props))
            conn.execute(
                f"""
                INSERT INTO GOV.DECISION_COVERS (decision_id, proposal_id, in_sample)
                SELECT {{decision_id}}, p.proposal_id,
                       CASE WHEN p.proposal_id IN ({sample_ids_sql}) THEN TRUE ELSE FALSE END
                FROM GOV.PROPOSAL p
                WHERE p.batch_id = {{batch_id}} AND p.proposal_id IN ({covered_ids_sql})
                """,
                query_params={"decision_id": dec_id, "batch_id": batch_id},
            )

            # Set-based insert into GRAPH events
            if batch_kind == "RECORD_LINK":
                conn.execute(
                    """
                    INSERT INTO GRAPH.LINK_EVENT (
                        event_id, link_key, rec_key, entity_key, "ACTION",
                        evidence_hash, valid_from, valid_to, recorded_at, decision_id, proposal_id
                    )
                    SELECT
                        'EV-' || {time_tag} || '-' || LPAD(ROW_NUMBER() OVER (ORDER BY p.proposal_id), 4, '0'),
                        p.rec_key || '>' || p.entity_key,
                        p.rec_key,
                        p.entity_key,
                        'ASSERT',
                        p.evidence_hash,
                        '0001-01-01',
                        '9999-12-31',
                        {recorded_at},
                        {decision_id},
                        p.proposal_id
                    FROM GOV.PROPOSAL p
                    WHERE p.batch_id = {batch_id} AND p.kind = 'RECORD_LINK'
                      AND p.proposal_id IN ({covered_ids_sql!r})
                    """,
                    query_params={
                        "covered_ids_sql": covered_ids_sql,
                        "time_tag": time_tag,
                        "batch_id": batch_id,
                        "recorded_at": decided_at_str,
                        "decision_id": dec_id,
                    },
                )
                # Set-based entity publishing
                conn.execute(
                    """
                    INSERT INTO GRAPH.ENTITY (entity_key, cin, display_name, first_published_at, decision_id)
                    SELECT DISTINCT
                        p.entity_key,
                        CASE WHEN p.entity_key LIKE 'E:%' THEN SUBSTR(p.entity_key, 3) ELSE p.entity_key END,
                        CASE WHEN p.entity_key LIKE 'E:%' THEN SUBSTR(p.entity_key, 3) ELSE p.entity_key END,
                        {recorded_at},
                        {decision_id}
                    FROM GOV.PROPOSAL p
                    WHERE p.batch_id = {batch_id} AND p.kind = 'RECORD_LINK'
                      AND p.proposal_id IN ({covered_ids_sql!r})
                      AND p.entity_key NOT IN (SELECT entity_key FROM GRAPH.ENTITY)
                    """,
                    query_params={
                        "covered_ids_sql": covered_ids_sql,
                        "batch_id": batch_id,
                        "recorded_at": decided_at_str,
                        "decision_id": dec_id,
                    },
                )
            else:  # OWNERSHIP batch
                # Insert OWNERSHIP_EVENTs reading real attributes. Every proposal is validated
                # first, then all events go in as chunked multi-row INSERTs (one statement per
                # proposal made a 3,500-edge batch take over a minute).
                events: list[tuple] = []
                for idx, (pid, pdata) in enumerate(covered_props.items(), start=1):
                    p_subj = pdata["subject_key"]
                    p_holder = pdata["holder_entity_key"]
                    p_held = pdata["held_entity_key"]
                    p_ev_hash = pdata["evidence_hash"]
                    p_ev_json = pdata["evidence_json"]

                    if not p_ev_json:
                        raise ValueError(f"Proposal {pid} evidence_json is missing.")
                    try:
                        ev_dict = json.loads(p_ev_json)
                    except Exception as e:
                        raise ValueError(f"Proposal {pid} evidence_json is invalid JSON: {e}") from e

                    if not p_holder or not p_held or p_holder.strip() == "" or p_held.strip() == "":
                        raise ValueError(f"Proposal {pid} missing required endpoints: holder={p_holder}, held={p_held}.")

                    v_from = ev_dict.get("effective_from")
                    if not v_from or str(v_from).strip() == "":
                        raise ValueError(f"Proposal {pid} evidence missing required 'effective_from'.")

                    stake_raw = ev_dict.get("stake_pct") if "stake_pct" in ev_dict else ev_dict.get("share_pct")
                    if stake_raw is None:
                        raise ValueError(f"Proposal {pid} evidence missing required 'stake_pct'.")
                    stake = Decimal(str(stake_raw))

                    events.append((
                        f"EV-{time_tag}-{idx:04d}", p_subj, p_holder, p_held,
                        "CONTROL", "MAJORITY", "CONFIRMED", stake, "ASSERT",
                        p_ev_hash, str(v_from), "9999-12-31", decided_at_str, dec_id, pid,
                    ))

                insert_rows(
                    conn,
                    "GRAPH.OWNERSHIP_EVENT",
                    ["event_id", "edge_key", "holder_entity_key", "held_entity_key", "edge_kind", "control_type",
                     "status", "stake_pct", '"ACTION"', "evidence_hash", "valid_from", "valid_to", "recorded_at",
                     "decision_id", "proposal_id"],
                    events,
                )

            decision_type = "BATCH_APPROVE"
            covered_ids = tuple(covered_props.keys())

        else:
            # BATCH_FAILED: Reject the failed sample items, unlock the remaining proposals
            failed_pids = [pid for pid in expected_sample_ids if not verdicts[pid]]
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
                    "sample_json": sample_json_str,
                    "covered_count": len(failed_pids),
                },
            )

            for idx, pid in enumerate(failed_pids, start=1):
                ev_id = f"EV-{time_tag}-{idx:04d}"
                conn.execute(
                    """
                    INSERT INTO GOV.DECISION_COVERS (decision_id, proposal_id, in_sample)
                    VALUES ({decision_id}, {proposal_id}, TRUE)
                    """,
                    query_params={"decision_id": dec_id, "proposal_id": pid},
                )
                pdata = covered_props[pid]
                p_kind = pdata["kind"]
                p_rec = pdata["rec_key"]
                p_ent = pdata["entity_key"]
                p_ev_hash = pdata["evidence_hash"]

                if p_kind == "RECORD_LINK" and p_rec and p_ent:
                    conn.execute(
                        """
                        INSERT INTO GRAPH.LINK_EVENT (
                            event_id, link_key, rec_key, entity_key, "ACTION",
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
        _clear_batch_seed(batch_id)

        published_run_id = None
        if publish:  # the eval oracle publishes once after all its decisions
            try:
                from orchestrator.pipeline import publish_run
                pub_res = publish_run(business_date=bd_str)
                published_run_id = pub_res.run_id
            except Exception as e:
                warnings.warn(f"publish_run after batch decision failed: {e}", stacklevel=2)

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
    business_date: str | date,
    connected_edge_kind: Literal["CONTROL", "INTERDEP"] = "CONTROL",
    conn: ExaConnection | None = None,
    publish: bool = True,
) -> DecisionResult:
    """Resolve Joint Venture control ambiguity with strict validation and atomic event generation."""
    if reviewer.role != "APPROVER":
        raise UnauthorizedReviewerError("Only reviewers with role APPROVER may issue rulings.")

    if not (1 <= len(reason) <= 2000):
        raise ValueError("Ruling reason must be between 1 and 2000 characters.")

    if ruling == "SINGLE" and not controller:
        raise ValueError("A controller entity key is required when ruling is SINGLE.")

    if ruling == "CONNECTED" and len(reason) < 20:
        raise ValueError("CONNECTED ruling requires at least 20 characters of evidence text.")

    bd_str = business_date.isoformat() if isinstance(business_date, date) else str(business_date)

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

        # Check proposal kind
        if prop["kind"] != "CONTROL_RULING":
            raise ValueError(f"Proposal {proposal_id} is of kind '{prop['kind']}', not 'CONTROL_RULING'.")

        _raise_if_superseded(conn, proposal_id)

        # Check existing terminal ruling
        term_stmt = conn.execute(
            """
            SELECT d.decision
            FROM GOV.DECISION_COVERS c
            JOIN GOV.DECISION_LOG d ON c.decision_id = d.decision_id
            WHERE c.proposal_id = {proposal_id}
              AND d.decision IN ('RULING', 'REJECT', 'APPROVE')
            """,
            query_params={"proposal_id": proposal_id},
        )
        if term_stmt.fetchone() is not None:
            raise ProposalConflictError(f"Proposal {proposal_id} already has a terminal decision.")

        held_key = prop["held_entity_key"]
        ev_hash = prop["evidence_hash"]
        ev_json_str = prop["evidence_json"]

        if not ev_json_str:
            raise ValueError(f"Proposal {proposal_id} evidence_json is missing.")
        try:
            ev_data = json.loads(ev_json_str)
        except Exception as e:
            raise ValueError(f"Proposal {proposal_id} evidence_json is invalid JSON: {e}") from e

        holders = ev_data.get("holders", [])
        if not holders:
            raise ValueError(f"Proposal {proposal_id} has no holders declared in evidence.")

        valid_from = ev_data.get("effective_from")
        if not valid_from or str(valid_from).strip() == "":
            raise ValueError(f"Proposal {proposal_id} evidence missing required 'effective_from'.")

        if ruling == "SINGLE" and controller not in holders:
            raise ValueError(f"Controller {controller} is not one of the declared holders {holders}.")

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
                {controller}, {valid_from}, '9999-12-31', {recorded_at}, {decision_id}, {proposal_id}
            )
            """,
            query_params={
                "event_id": ruling_ev_id,
                "ruling_key": f"JV:{held_key}",
                "held_entity_key": held_key,
                "ruling": ruling,
                "controller": controller,
                "valid_from": valid_from,
                "recorded_at": decided_at_str,
                "decision_id": dec_id,
                "proposal_id": proposal_id,
            },
        )

        # 3. Write OWNERSHIP_EVENTs based on ruling
        for idx, h_key in enumerate(holders, start=1):
            edge_ev_id = f"EV-{time_tag}-{idx:02d}"
            edge_key = f"CONTROL:{h_key}>{held_key}"
            stake = _extract_holder_stake(ev_data, h_key, proposal_id)

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
                    edge_kind, control_type, status, stake_pct, "ACTION",
                    evidence_hash, valid_from, valid_to, recorded_at, decision_id, proposal_id
                ) VALUES (
                    {event_id}, {edge_key}, {holder_entity_key}, {held_entity_key},
                    'CONTROL', {control_type}, {status}, {stake_pct}, 'ASSERT',
                    {evidence_hash}, {valid_from}, '9999-12-31', {recorded_at}, {decision_id}, {proposal_id}
                )
                """,
                query_params={
                    "event_id": edge_ev_id,
                    "edge_key": edge_key,
                    "holder_entity_key": h_key,
                    "held_entity_key": held_key,
                    "control_type": c_type,
                    "status": status,
                    "stake_pct": stake,
                    "evidence_hash": ev_hash,
                    "valid_from": valid_from,
                    "recorded_at": decided_at_str,
                    "decision_id": dec_id,
                    "proposal_id": proposal_id,
                },
            )

        # 4. If CONNECTED, file CONTROLLER_LINK proposal via pipeline connection
        # (APPROVER does not hold INSERT on GOV.PROPOSAL)
        if ruling == "CONNECTED" and len(holders) >= 2:
            hA, hB = holders[0], holders[1]
            ctrl_kind = connected_edge_kind  # Respect reviewer's choice (CONTROL or INTERDEP)
            ctrl_subj = f"{ctrl_kind}:{hA}>{hB}"
            ctrl_ev_hash = hashlib.sha256(reason.encode("utf-8")).hexdigest()
            ctrl_prop_id = f"P-{hashlib.sha256((ctrl_subj + ctrl_ev_hash).encode()).hexdigest()[:12]}"

            # Pipeline connection to insert proposal
            pipeline_conn = connect("pipeline", autocommit=True)
            try:
                pipeline_conn.execute(
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
                        "evidence_json": json.dumps({"reason": reason, "controllers": [hA, hB], "edge_kind": ctrl_kind}),
                        "evidence_hash": ctrl_ev_hash,
                        "filed_at": decided_at_str,
                    },
                )
            finally:
                pipeline_conn.close()

        conn.commit()

        published_run_id = None
        if publish:  # the eval oracle publishes once after all its decisions
            try:
                from orchestrator.pipeline import publish_run
                pub_res = publish_run(business_date=bd_str)
                published_run_id = pub_res.run_id
            except Exception as e:
                warnings.warn(f"publish_run after ruling failed: {e}", stacklevel=2)

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
