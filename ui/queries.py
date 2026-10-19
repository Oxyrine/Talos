"""ui/queries.py: Database query abstraction layer.

Connects as TALOS_READER to execute read-only queries against REPORT.* views,
or transparently delegates to ui/mock_data.py when TALOS_MOCK=1 is set.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from typing import Any

from ui.auth import is_mock_mode


class DatabaseUnavailableError(Exception):
    """Raised when Exasol database cannot be reached and TALOS_MOCK is not set."""


def _get_reader_connection():
    """Connect to Exasol as TALOS_READER or raise DatabaseUnavailableError."""
    from orchestrator.db import connect
    try:
        return connect("reader", autocommit=True)
    except Exception as e:
        raise DatabaseUnavailableError(
            f"Exasol database unavailable (TALOS_MOCK is not enabled): {e}"
        ) from e


# -------------------------------------------------------------------------
# Screen 1: Exposure Board
# -------------------------------------------------------------------------
def get_board_data(business_date: str = "2026-09-30", sort: str = "hidden", view: str = "talos") -> dict[str, Any]:
    if is_mock_mode():
        from ui.mock_data import get_mock_board_data
        return get_mock_board_data(business_date=business_date, sort=sort, view=view)

    conn = _get_reader_connection()
    try:
        # 1. Fetch latest run metadata
        latest_run = conn.execute(
            "SELECT run_id, business_date, known_at, status FROM REPORT.V_LATEST_RUN WHERE business_date = {bd}",
            query_params={"bd": business_date},
        ).fetchone()

        run_id = latest_run[0] if latest_run else None

        # 2. Fetch group exposures
        rows = conn.execute(
            """
            SELECT group_key, group_name, head_entity_key, member_count,
                   reported_exposure, limit_exposure, capital_base,
                   utilisation_pct, is_large, is_breach, group_flags,
                   hidden_exposure, headroom
            FROM REPORT.V_GROUP_EXPOSURE
            WHERE run_id = {run_id}
            """,
            query_params={"run_id": run_id},
        ).fetchall()

        groups = []
        hidden_total = Decimal("0.00")
        breaches_count = 0
        large_count = 0

        for r in rows:
            rep_exp = Decimal(str(r[4] or 0))
            lim_exp = Decimal(str(r[5])) if r[5] is not None else None
            cap_base = Decimal(str(r[6] or 4200000000))
            util = Decimal(str(r[7] or 0))
            is_l = bool(r[8])
            is_b = bool(r[9])
            flags = str(r[10] or "")
            hid_raw = Decimal(str(r[11] or 0))
            headroom = Decimal(str(r[12] or 0))

            # Strictly clamp hidden exposure KPI at 0
            hid_clamped = max(Decimal("0.00"), hid_raw)
            hidden_total += hid_clamped
            if is_b:
                breaches_count += 1
            if is_l:
                large_count += 1

            groups.append({
                "group_key": r[0],
                "group_name": r[1] or "Unresolved Group",
                "head_entity_key": r[2],
                "member_count": r[3],
                "reported_exposure": rep_exp,
                "limit_exposure": lim_exp,
                "hidden_exposure": hid_clamped,
                "capital_base": cap_base,
                "utilisation_pct": util,
                "is_large": is_l,
                "is_breach": is_b,
                "group_flags": flags,
                "headroom": headroom,
            })

        # Sorting
        if sort == "util":
            groups.sort(key=lambda g: g["utilisation_pct"], reverse=True)
        elif sort == "hidden":
            groups.sort(key=lambda g: g["hidden_exposure"], reverse=True)
        else:
            groups.sort(key=lambda g: g["limit_exposure"] or Decimal("0"), reverse=True)

        return {
            "run_id": run_id,
            "business_date": business_date,
            "known_at": str(latest_run[2]) if latest_run else "",
            "kpi": {
                "hidden_exposure": hidden_total,
                "breaches_count": breaches_count,
                "large_count": large_count,
                "unassigned_exposure": Decimal("0.00"),
            },
            "groups": groups,
        }
    finally:
        conn.close()


# -------------------------------------------------------------------------
# Screen 2: Review Queue
# -------------------------------------------------------------------------
def get_queue_data(page: int = 1, per_page: int = 25, tier: str = "", kind: str = "") -> dict[str, Any]:
    if is_mock_mode():
        from ui.mock_data import get_mock_queue_data
        return get_mock_queue_data(page=page, per_page=per_page, tier=tier, kind=kind)

    conn = _get_reader_connection()
    try:
        # Check active batches
        batches_raw = conn.execute(
            """
            SELECT batch_id, batch_kind, COUNT(*) total_count
            FROM GOV.PROPOSAL
            WHERE batch_id IS NOT NULL
              AND proposal_id NOT IN (SELECT proposal_id FROM GOV.DECISION_COVERS)
            GROUP BY batch_id, batch_kind
            """
        ).fetchall()

        batches = []
        for b in batches_raw:
            b_id, b_kind, b_tot = b[0], b[1], int(b[2])
            is_rec = b_kind == "RECORD_LINK"
            pct = 5 if is_rec else 2
            min_k = 20
            sample_cnt = min(b_tot, max(min_k, -(-pct * b_tot // 100)))
            batches.append({
                "batch_id": b_id,
                "batch_kind": b_kind,
                "title": "Exact-ID Record Links Batch" if is_rec else "Corroborated Ownership Edges Batch",
                "desc": f"{b_tot:,} matches waiting. Review a representative sample of {sample_cnt} to approve.",
                "total_count": b_tot,
                "sample_count": sample_cnt,
            })

        # Fetch open individual proposals
        clauses = ["proposal_id NOT IN (SELECT proposal_id FROM GOV.DECISION_LOG WHERE proposal_id IS NOT NULL)"]
        params: dict[str, Any] = {}
        if tier:
            clauses.append("tier = {tier}")
            params["tier"] = tier
        if kind:
            clauses.append("kind = {kind}")
            params["kind"] = kind

        where_sql = " AND ".join(clauses)
        proposals_raw = conn.execute(
            f"""
            SELECT proposal_id, kind, subject_key, tier, tier_reason,
                   rupee_impact, crosses_limit, crosses_le, group_before_pct,
                   group_after_pct, group_name, evidence_json
            FROM REPORT.V_PROPOSAL_QUEUE
            WHERE {where_sql}
            ORDER BY crosses_limit DESC, crosses_le DESC, rupee_impact DESC
            """,
            query_params=params,
        ).fetchall()

        proposals = []
        for p in proposals_raw:
            proposals.append({
                "proposal_id": p[0],
                "kind": p[1],
                "subject_key": p[2],
                "tier": p[3],
                "tier_reason": p[4],
                "rupee_impact": Decimal(str(p[5] or 0)),
                "crosses_limit": int(p[6] or 0),
                "crosses_le": int(p[7] or 0),
                "group_before_pct": Decimal(str(p[8] or 0)),
                "group_after_pct": Decimal(str(p[9] or 0)),
                "group_name": p[10] or "",
                "evidence_json": p[11],
            })

        # Server-side pagination
        total_items = len(proposals)
        total_pages = max(1, (total_items + per_page - 1) // per_page)
        page = min(max(1, page), total_pages)
        start_idx = (page - 1) * per_page
        paginated = proposals[start_idx : start_idx + per_page]

        return {
            "batches": batches,
            "proposals": paginated,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total_items": total_items,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1,
            },
        }
    finally:
        conn.close()


def get_batch_data(batch_id: str, user_name: str) -> dict[str, Any]:
    if is_mock_mode():
        from ui.mock_data import get_mock_batch_data
        return get_mock_batch_data(batch_id=batch_id, user_name=user_name)

    from orchestrator.decide import batch_sample
    sample = batch_sample(batch_id)
    # Generate token
    from ui.mock_data import generate_batch_token
    token = generate_batch_token(user_name, batch_id, sample.seed, list(sample.sample_ids))

    conn = _get_reader_connection()
    try:
        # Load sample details
        items = []
        for pid in sample.sample_ids:
            row = conn.execute(
                "SELECT proposal_id, subject_key, evidence_json FROM GOV.PROPOSAL WHERE proposal_id = {pid}",
                query_params={"pid": pid},
            ).fetchone()
            if row:
                ev = json.loads(row[2])
                items.append({
                    "proposal_id": row[0],
                    "source_a": ev.get("book", {}).get("source", ""),
                    "name_a": ev.get("book", {}).get("raw_name", ""),
                    "pan_a": ev.get("book", {}).get("pan", "—"),
                    "source_b": "REG",
                    "name_b": ev.get("registry", {}).get("entity_name", ""),
                    "pan_b": ev.get("registry", {}).get("pan", "—"),
                    "status": "Sample Pair",
                })
        return {
            "batch_id": batch_id,
            "batch_kind": sample.batch_kind,
            "title": "Exact-ID Record Links" if sample.batch_kind == "RECORD_LINK" else "Corroborated Ownership Edges",
            "total_count": sample.total_count,
            "sample_count": sample.sample_count,
            "seed": sample.seed,
            "token": token,
            "items": items,
        }
    finally:
        conn.close()


# -------------------------------------------------------------------------
# Decision Handlers
# -------------------------------------------------------------------------
def execute_decision(proposal_id: str, decision: str, reason: str, reviewer_name: str, reviewer_role: str) -> dict[str, Any]:
    if is_mock_mode():
        from ui.mock_data import execute_mock_decision
        return execute_mock_decision(proposal_id, decision, reason, reviewer_name)

    from orchestrator.decide import Reviewer, decide
    reviewer = Reviewer(name=reviewer_name, role=reviewer_role)  # type: ignore[arg-type]
    res = decide(proposal_id, decision=decision, reason=reason, reviewer=reviewer)  # type: ignore[arg-type]

    # Return refreshed KPI
    board = get_board_data()
    return {
        "proposal_id": proposal_id,
        "decision": decision,
        "decision_id": res.decision_id,
        "kpi": board["kpi"],
    }


def execute_batch(batch_id: str, seed: int, token: str, verdicts: dict[str, bool], reason: str, reviewer_name: str, reviewer_role: str) -> dict[str, Any]:
    if is_mock_mode():
        from ui.mock_data import execute_mock_batch
        return execute_mock_batch(batch_id, seed, token, verdicts, reason, reviewer_name)

    from orchestrator.decide import Reviewer, batch_decide
    reviewer = Reviewer(name=reviewer_name, role=reviewer_role)  # type: ignore[arg-type]
    res = batch_decide(batch_id=batch_id, seed=seed, verdicts=verdicts, reason=reason, reviewer=reviewer)
    board = get_board_data()
    return {
        "batch_id": batch_id,
        "status": res.decision,
        "kpi": board["kpi"],
    }


def execute_ruling(proposal_id: str, ruling: str, controller: str | None, reason: str, reviewer_name: str, reviewer_role: str) -> dict[str, Any]:
    if is_mock_mode():
        from ui.mock_data import execute_mock_ruling
        return execute_mock_ruling(proposal_id, ruling, controller, reason, reviewer_name)

    from orchestrator.decide import Reviewer, rule
    reviewer = Reviewer(name=reviewer_name, role=reviewer_role)  # type: ignore[arg-type]
    res = rule(proposal_id=proposal_id, ruling=ruling, controller=controller, reason=reason, reviewer=reviewer)  # type: ignore[arg-type]
    board = get_board_data()
    return {
        "proposal_id": proposal_id,
        "ruling": ruling,
        "decision_id": res.decision_id,
        "kpi": board["kpi"],
    }


# -------------------------------------------------------------------------
# Lineage, Pipeline, and Audit
# -------------------------------------------------------------------------
def get_lineage_group_data(group_key: str, run_id: str | None = None) -> dict[str, Any]:
    if is_mock_mode():
        from ui.mock_data import get_mock_lineage_group_data
        return get_mock_lineage_group_data(group_key=group_key, run_id=run_id)

    conn = _get_reader_connection()
    try:
        latest = conn.execute("SELECT run_id FROM REPORT.V_LATEST_RUN").fetchval()
        is_latest = (run_id is None or run_id == latest)
        effective_run_id = run_id or latest

        tree_nodes = []
        if is_latest:
            tree_raw = conn.execute(
                """
                SELECT held_name, depth, closes_cycle, control_type, stake_pct, entity_key = root_key is_head
                FROM REPORT.V_OWNERSHIP_PATH
                WHERE root_key = {gk}
                ORDER BY depth, held_name
                """,
                query_params={"gk": group_key},
            ).fetchall()
            for t in tree_raw:
                tree_nodes.append({
                    "entity_name": t[0],
                    "depth": t[1],
                    "closes_cycle": bool(t[2]),
                    "stake_pct": f"{t[4]:.1f}%" if t[4] else t[3],
                    "is_head": bool(t[5]),
                })

        members_raw = conn.execute(
            """
            SELECT entity_key, entity_name, book_exposure
            FROM REPORT.V_ENTITY_EXPOSURE
            WHERE run_id = {run_id} AND group_key = {gk}
            ORDER BY book_exposure DESC
            """,
            query_params={"run_id": effective_run_id, "gk": group_key},
        ).fetchall()

        members = []
        for m in members_raw:
            members.append({
                "entity_key": m[0],
                "entity_name": m[1] or m[0],
                "exposure": Decimal(str(m[2] or 0)),
                "books": "LOS, TSY, GTE",
            })

        return {
            "group_key": group_key,
            "group_name": tree_nodes[0]["entity_name"] if tree_nodes else "Group Lineage",
            "run_id": effective_run_id,
            "is_latest": is_latest,
            "tree_nodes": tree_nodes,
            "members": members,
        }
    finally:
        conn.close()


def get_lineage_rows_data(group_key: str, source: str = "", product: str = "", run_id: str | None = None) -> list[dict[str, Any]]:
    if is_mock_mode():
        from ui.mock_data import get_mock_lineage_rows_data
        return get_mock_lineage_rows_data(group_key=group_key, source=source, product=product, run_id=run_id)

    conn = _get_reader_connection()
    try:
        latest = conn.execute("SELECT run_id FROM REPORT.V_LATEST_RUN").fetchval()
        effective_run_id = run_id or latest

        clauses = ["run_id = {run_id}", "group_key = {gk}"]
        params: dict[str, Any] = {"run_id": effective_run_id, "gk": group_key}
        if source:
            clauses.append("source_system = {src}")
            params["src"] = source
        if product:
            clauses.append("product = {prod}")
            params["prod"] = product

        where_sql = " AND ".join(clauses)
        rows_raw = conn.execute(
            f"""
            SELECT entity_name, source_system, source_row_id, product, exposure_component,
                   gross_amount, ccf, exposure_amount, link_proposal_id, link_decision_id,
                   reviewer, decided_at, tier
            FROM REPORT.V_LINEAGE
            WHERE {where_sql}
            ORDER BY exposure_amount DESC
            """,
            query_params=params,
        ).fetchall()

        rows = []
        for r in rows_raw:
            rows.append({
                "entity_name": r[0],
                "source_system": r[1],
                "source_row_id": r[2],
                "product": r[3],
                "component": r[4],
                "gross_amount": Decimal(str(r[5] or 0)),
                "ccf": Decimal(str(r[6] or 0)),
                "exposure_amount": Decimal(str(r[7] or 0)),
                "proposal_id": r[8],
                "decision_id": r[9],
                "reviewer": r[10] or "System",
                "decided_at": str(r[11]) if r[11] else "—",
                "tier": r[12] or "T0",
            })
        return rows
    finally:
        conn.close()


def get_pipeline_data() -> dict[str, Any]:
    if is_mock_mode():
        from ui.mock_data import get_mock_pipeline_data
        return get_mock_pipeline_data()

    conn = _get_reader_connection()
    try:
        timings_raw = conn.execute(
            "SELECT stage, rows_affected, seconds FROM REPORT.V_PIPELINE_TIMING ORDER BY started_at"
        ).fetchall()
        timings = [{"stage": r[0], "rows": int(r[1] or 0), "seconds": float(r[2] or 0)} for r in timings_raw]

        paths_raw = conn.execute(
            "SELECT via_path, candidate_count FROM REPORT.V_CANDIDATE_PATHS ORDER BY candidate_count DESC"
        ).fetchall()
        paths = [{"via_path": r[0], "count": int(r[1] or 0)} for r in paths_raw]

        tiers_raw = conn.execute("SELECT tier, count FROM REPORT.V_TIER_COUNTS ORDER BY tier").fetchall()
        tiers = [{"tier": r[0], "count": int(r[1] or 0)} for r in tiers_raw]

        summary_row = conn.execute(
            """
            SELECT total_book_records, total_reg_entities, total_candidates,
                   settled_in_sql_pct, sent_to_model_pct, reduction_ratio
            FROM REPORT.V_PIPELINE_SUMMARY
            """
        ).fetchone()

        summary = {
            "total_book_records": int(summary_row[0] or 0) if summary_row else 0,
            "total_reg_entities": int(summary_row[1] or 0) if summary_row else 0,
            "total_candidates": int(summary_row[2] or 0) if summary_row else 0,
            "settled_in_sql_pct": Decimal(str(summary_row[3] or 100)),
            "sent_to_model_pct": Decimal(str(summary_row[4] or 0)),
            "reduction_ratio": Decimal(str(summary_row[5] or 99.9)),
        }

        return {
            "job_id": "LATEST_MATCH",
            "timings": timings,
            "paths": paths,
            "tiers": tiers,
            "summary": summary,
        }
    finally:
        conn.close()


def get_audit_data() -> list[dict[str, Any]]:
    if is_mock_mode():
        from ui.mock_data import get_mock_audit_data
        return get_mock_audit_data()

    conn = _get_reader_connection()
    try:
        runs_raw = conn.execute(
            """
            SELECT run_id, business_date, known_at, code_version, output_hash, status, replay_of
            FROM REPORT.V_RUNS
            ORDER BY started_at DESC
            """
        ).fetchall()
        return [
            {
                "run_id": r[0],
                "business_date": str(r[1]),
                "known_at": str(r[2]),
                "code_version": r[3],
                "output_hash": r[4],
                "status": r[5],
                "replay_of": r[6],
            }
            for r in runs_raw
        ]
    finally:
        conn.close()


def execute_replay(run_id: str) -> dict[str, Any]:
    if is_mock_mode():
        return {
            "run_id": run_id,
            "matches": True,
            "replay_hash": "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
        }

    from orchestrator.replay import replay
    res = replay(run_id)
    return {
        "run_id": run_id,
        "matches": res.matches,
        "original_hash": res.original_hash,
        "replay_hash": res.replay_hash,
        "code_version_differs": res.code_version_differs,
    }
