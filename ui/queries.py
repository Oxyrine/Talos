"""ui/queries.py: Database query abstraction layer.

Connects as TALOS_READER to execute read-only queries against REPORT.* views (the reader holds
SELECT on REPORT only, so nothing here may touch GOV, GRAPH or RESOLVE directly), or
transparently delegates to ui/mock_data.py when TALOS_MOCK=1 is set. Decisions go through
orchestrator.decide, which connects as TALOS_APPROVER.

orchestrator.db.connect() returns dict rows with lower-case keys (fetch_dict, lower_ident).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from ui.auth import is_mock_mode
from ui.batch_token import generate_batch_token, verify_batch_token
from ui.formatting import parse_evidence

DEFAULT_BUSINESS_DATE = "2026-09-30"


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


def _rows(conn, sql: str, **params: Any) -> list[dict[str, Any]]:
    return conn.execute(sql, query_params=params).fetchall()


def _dec(v: Any, default: str = "0") -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal(default)


def _current_run(conn) -> tuple[str | None, str]:
    """(run_id, business_date) of the newest successful run; business date falls back to the default."""
    rows = _rows(conn, "SELECT run_id, business_date FROM REPORT.V_CURRENT_RUN")
    if not rows:
        return None, DEFAULT_BUSINESS_DATE
    return rows[0]["run_id"], str(rows[0]["business_date"])[:10]


def _current_business_date() -> str:
    conn = _get_reader_connection()
    try:
        return _current_run(conn)[1]
    finally:
        conn.close()


# -------------------------------------------------------------------------
# Screen 1: Exposure Board
# -------------------------------------------------------------------------
def get_board_data(business_date: str = DEFAULT_BUSINESS_DATE, sort: str = "hidden", view: str = "talos") -> dict[str, Any]:
    if is_mock_mode():
        from ui.mock_data import get_mock_board_data

        return get_mock_board_data(business_date=business_date, sort=sort, view=view)

    conn = _get_reader_connection()
    try:
        latest = _rows(
            conn,
            "SELECT run_id, known_at FROM REPORT.V_LATEST_RUN WHERE business_date = {bd}",
            bd=business_date,
        )
        run_id = latest[0]["run_id"] if latest else None

        rows = _rows(
            conn,
            """
            SELECT group_key, group_name, head_entity_key, member_count,
                   reported_exposure, limit_exposure, capital_base,
                   utilisation_pct, is_large, is_breach, group_flags,
                   hidden_exposure, headroom
            FROM REPORT.V_GROUP_EXPOSURE
            WHERE run_id = {run_id} AND limit_exposure > 0
            """,
            run_id=run_id,
        )

        groups = []
        hidden_total = Decimal("0.00")
        unassigned = Decimal("0.00")
        breaches_count = 0
        large_count = 0

        for r in rows:
            flags = str(r["group_flags"] or "")
            unresolved = "UNRESOLVED" in flags  # a lone unlinked record: shown as pending, not as a figure
            lim_exp = None if unresolved else _dec(r["limit_exposure"])
            # Hidden exposure is clamped at zero: Talos can only unmask, never shrink, a reported figure.
            hid_clamped = Decimal("0.00") if unresolved else max(Decimal("0.00"), _dec(r["hidden_exposure"]))
            hidden_total += hid_clamped
            if unresolved or "UNASSIGNED" in flags:
                unassigned += _dec(r["limit_exposure"])
            if r["is_breach"] and not unresolved:
                breaches_count += 1
            if r["is_large"] and not unresolved:
                large_count += 1

            groups.append({
                "group_key": r["group_key"],
                "group_name": r["group_name"] or "Unresolved Group",
                "head_entity_key": r["head_entity_key"],
                "member_count": r["member_count"],
                "reported_exposure": _dec(r["reported_exposure"]),
                "limit_exposure": lim_exp,
                "hidden_exposure": hid_clamped,
                "capital_base": _dec(r["capital_base"]),
                "utilisation_pct": _dec(r["utilisation_pct"]),
                "is_large": bool(r["is_large"]),
                "is_breach": bool(r["is_breach"]),
                "group_flags": flags,
                "headroom": _dec(r["headroom"]),
            })

        if sort == "util":
            groups.sort(key=lambda g: g["utilisation_pct"], reverse=True)
        elif sort == "hidden":
            groups.sort(key=lambda g: g["hidden_exposure"], reverse=True)
        else:
            groups.sort(key=lambda g: g["limit_exposure"] or Decimal("0"), reverse=True)

        return {
            "run_id": run_id,
            "business_date": business_date,
            "known_at": str(latest[0]["known_at"]) if latest else "",
            "kpi": {
                "hidden_exposure": hidden_total,
                "breaches_count": breaches_count,
                "large_count": large_count,
                "unassigned_exposure": unassigned,
                "capital_base": groups[0]["capital_base"] if groups else None,
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
        # Batch banners: V_PROPOSAL_QUEUE computes the totals and the policy-driven sample sizes.
        batches = []
        for b in _rows(
            conn,
            """
            SELECT batch_id, batch_kind, MAX(batch_total_count) AS total_count, MAX(batch_sample_count) AS sample_count
            FROM REPORT.V_PROPOSAL_QUEUE
            WHERE batch_id IS NOT NULL AND batch_failed = FALSE
            GROUP BY batch_id, batch_kind
            ORDER BY batch_id
            """,
        ):
            is_rec = b["batch_kind"] == "RECORD_LINK"
            total, sample = int(b["total_count"]), int(b["sample_count"])
            batches.append({
                "batch_id": b["batch_id"],
                "batch_kind": b["batch_kind"],
                "title": "Exact-ID Record Links Batch" if is_rec else "Corroborated Ownership Edges Batch",
                "desc": f"{total:,} matches waiting. Review a representative sample of {sample} to approve.",
                "total_count": total,
                "sample_count": sample,
            })

        # Individual cards: batch members are decided through their batch, unless the batch failed.
        clauses = ["(batch_id IS NULL OR batch_failed = TRUE)"]
        params: dict[str, Any] = {}
        if tier:
            clauses.append("tier = {tier}")
            params["tier"] = tier
        if kind:
            clauses.append("kind = {kind}")
            params["kind"] = kind
        where_sql = " AND ".join(clauses)

        total_items = int(conn.execute(
            f"SELECT COUNT(*) FROM REPORT.V_PROPOSAL_QUEUE WHERE {where_sql}", query_params=params
        ).fetchval())
        total_pages = max(1, (total_items + per_page - 1) // per_page)
        page = min(max(1, page), total_pages)

        # per_page and offset are ints validated by the route, so formatting them in is safe.
        proposals_raw = conn.execute(
            f"""
            SELECT proposal_id, kind, subject_key, tier, tier_reason, warning, rupee_impact,
                   crosses_limit, crosses_le, group_before_pct, group_after_pct, group_name, evidence_json
            FROM REPORT.V_PROPOSAL_QUEUE
            WHERE {where_sql}
            ORDER BY crosses_limit DESC, crosses_le DESC, delta_amt DESC, proposal_id
            LIMIT {int(per_page)} OFFSET {int((page - 1) * per_page)}
            """,
            query_params=params,
        ).fetchall()

        proposals = [{
            "proposal_id": p["proposal_id"],
            "kind": p["kind"],
            "subject_key": p["subject_key"],
            "tier": p["tier"],
            "tier_reason": p["tier_reason"],
            "warning": p["warning"],
            "rupee_impact": _dec(p["rupee_impact"]),
            "crosses_limit": int(bool(p["crosses_limit"])),
            "crosses_le": int(bool(p["crosses_le"])),
            "group_before_pct": _dec(p["group_before_pct"]),
            "group_after_pct": _dec(p["group_after_pct"]),
            "group_name": p["group_name"] or "",
            "evidence_json": p["evidence_json"],
        } for p in proposals_raw]

        return {
            "batches": batches,
            "proposals": proposals,
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

    # batch_sample connects as TALOS_APPROVER (the reader cannot see GOV) and issues a fresh seed.
    sample = batch_sample(batch_id, business_date=_current_business_date())
    token = generate_batch_token(user_name, batch_id, sample.seed, list(sample.sample_ids))

    conn = _get_reader_connection()
    try:
        ids = list(sample.sample_ids)
        marks = ", ".join(f"{{p{i}}}" for i in range(len(ids)))
        by_id = {
            r["proposal_id"]: r
            for r in _rows(
                conn,
                f"SELECT proposal_id, kind, evidence_json FROM REPORT.V_PROPOSAL_QUEUE WHERE proposal_id IN ({marks})",
                **{f"p{i}": pid for i, pid in enumerate(ids)},
            )
        } if ids else {}

        items = []
        for pid in ids:  # keep the sample's order
            row = by_id.get(pid)
            ev = parse_evidence(row["evidence_json"]) if row else {"book": {}, "registry": {}}
            if row and row["kind"] == "OWNERSHIP":
                items.append({
                    "proposal_id": pid,
                    "source_a": "REG",
                    "name_a": ev["book"].get("holder_name", ""),
                    "pan_a": ev["book"].get("stake_pct") or "—",
                    "source_b": "REG",
                    "name_b": ev["book"].get("held_name", ""),
                    "pan_b": ev["book"].get("held_cin") or "—",
                    "status": "Corroborated ownership edge",
                })
            else:
                items.append({
                    "proposal_id": pid,
                    "source_a": ev["book"].get("source", ""),
                    "name_a": ev["book"].get("raw_name", ""),
                    "pan_a": ev["book"].get("pan") or "—",
                    "source_b": "REG",
                    "name_b": ev["registry"].get("entity_name", ""),
                    "pan_b": ev["registry"].get("pan") or "—",
                    "status": ev.get("tier_reason") or "Sample pair",
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

    bd = _current_business_date()
    reviewer = Reviewer(name=reviewer_name, role=reviewer_role)  # type: ignore[arg-type]
    res = decide(proposal_id, decision=decision, reason=reason, reviewer=reviewer, business_date=bd)  # type: ignore[arg-type]
    return {
        "proposal_id": proposal_id,
        "decision": decision,
        "decision_id": res.decision_id,
        "kpi": get_board_data(business_date=bd)["kpi"],
    }


def execute_batch(
    batch_id: str,
    seed: int,
    token: str,
    verdicts: dict[str, bool],
    reason: str,
    reviewer_name: str,
    reviewer_role: str,
) -> dict[str, Any]:
    # The token binds (reviewer, batch, seed, sample) as issued on GET; the seed comes from the token,
    # never from the form, and batch_decide re-derives the sample from it before accepting verdicts.
    seed = verify_batch_token(token, reviewer_name, batch_id, list(verdicts))

    if is_mock_mode():
        from ui.mock_data import execute_mock_batch

        return execute_mock_batch(batch_id, seed, token, verdicts, reason, reviewer_name)

    from orchestrator.decide import Reviewer, batch_decide

    bd = _current_business_date()
    reviewer = Reviewer(name=reviewer_name, role=reviewer_role)  # type: ignore[arg-type]
    res = batch_decide(batch_id=batch_id, seed=seed, verdicts=verdicts, reason=reason, reviewer=reviewer, business_date=bd)
    return {
        "batch_id": batch_id,
        "status": res.decision,
        "kpi": get_board_data(business_date=bd)["kpi"],
    }


def get_ruling_data(proposal_id: str) -> dict[str, Any] | None:
    """The JV a CONTROL_RULING proposal is about: its holders, their stakes and groups, and its exposure."""
    if is_mock_mode():
        from ui.mock_data import get_mock_ruling_data

        return get_mock_ruling_data(proposal_id)

    conn = _get_reader_connection()
    try:
        rows = _rows(
            conn,
            "SELECT kind, evidence_json, rupee_impact FROM REPORT.V_PROPOSAL_QUEUE WHERE proposal_id = {pid}",
            pid=proposal_id,
        )
        if not rows or rows[0]["kind"] != "CONTROL_RULING":
            return None
        ev = parse_evidence(rows[0]["evidence_json"])
        holders = list(ev.get("holders") or [])
        stakes = ev.get("stakes") or {}
        run_id, _ = _current_run(conn)

        partners = []
        for key in holders:
            name = _rows(conn, "SELECT entity_name FROM REPORT.V_ENTITY_NAME WHERE entity_key = {k}", k=key)
            grp = _rows(
                conn,
                """
                SELECT g.group_name FROM REPORT.V_ENTITY_EXPOSURE e
                JOIN REPORT.V_GROUP_EXPOSURE g ON g.run_id = e.run_id AND g.group_key = e.group_key
                WHERE e.run_id = {run_id} AND e.entity_key = {k}
                """,
                run_id=run_id,
                k=key,
            )
            partners.append({
                "entity_key": key,
                "name": name[0]["entity_name"] if name else key,
                "pct": stakes.get(key),
                "group_name": grp[0]["group_name"] if grp else "No exposure in the book",
            })
        return {
            "proposal_id": proposal_id,
            "entity_name": ev.get("held_name") or ev.get("held_entity_key") or proposal_id,
            "gross_exposure": _dec(rows[0]["rupee_impact"]),
            "partners": partners,
        }
    finally:
        conn.close()


def execute_ruling(
    proposal_id: str,
    ruling: str,
    controller: str | None,
    reason: str,
    reviewer_name: str,
    reviewer_role: str,
    connected_edge_kind: str = "CONTROL",
) -> dict[str, Any]:
    if is_mock_mode():
        from ui.mock_data import execute_mock_ruling

        return execute_mock_ruling(proposal_id, ruling, controller, reason, reviewer_name)

    from orchestrator.decide import Reviewer, rule

    bd = _current_business_date()
    reviewer = Reviewer(name=reviewer_name, role=reviewer_role)  # type: ignore[arg-type]
    res = rule(
        proposal_id=proposal_id,
        ruling=ruling,  # type: ignore[arg-type]
        controller=controller,
        reason=reason,
        reviewer=reviewer,
        business_date=bd,
        connected_edge_kind=connected_edge_kind,  # type: ignore[arg-type]
    )
    return {
        "proposal_id": proposal_id,
        "ruling": ruling,
        "decision_id": res.decision_id,
        "kpi": get_board_data(business_date=bd)["kpi"],
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
        current, _ = _current_run(conn)
        is_latest = run_id is None or run_id == current
        effective_run_id = run_id or current

        group_rows = _rows(
            conn,
            "SELECT group_name FROM REPORT.V_GROUP_EXPOSURE WHERE run_id = {run_id} AND group_key = {gk}",
            run_id=effective_run_id,
            gk=group_key,
        )
        group_name = group_rows[0]["group_name"] if group_rows else "Group Lineage"

        # The ownership tree is built from today's confirmed edges, so it is only shown for the latest run.
        tree_nodes: list[dict[str, Any]] = []
        if is_latest:
            tree_nodes.append({"entity_name": group_name, "depth": 0, "closes_cycle": False, "stake_pct": "head", "is_head": True})
            for t in _rows(
                conn,
                """
                SELECT held_name, depth, closes_cycle, control_type, stake_pct
                FROM REPORT.V_OWNERSHIP_PATH
                WHERE root_key = {gk}
                ORDER BY depth, held_name
                """,
                gk=group_key,
            ):
                tree_nodes.append({
                    "entity_name": t["held_name"],
                    "depth": int(t["depth"]),
                    "closes_cycle": bool(t["closes_cycle"]),
                    "stake_pct": f"{_dec(t['stake_pct']):.1f}%" if t["stake_pct"] is not None else (t["control_type"] or ""),
                    "is_head": False,
                })

        books = {
            r["entity_key"]: r["books"]
            for r in _rows(
                conn,
                """
                SELECT entity_key, GROUP_CONCAT(DISTINCT source_system ORDER BY source_system SEPARATOR ', ') AS books
                FROM REPORT.V_LINEAGE
                WHERE run_id = {run_id} AND group_key = {gk} AND membership_kind = 'MEMBER'
                GROUP BY entity_key
                """,
                run_id=effective_run_id,
                gk=group_key,
            )
        }
        members = [{
            "entity_key": m["entity_key"],
            "entity_name": m["entity_name"] or m["entity_key"],
            "exposure": _dec(m["book_exposure"]),
            "books": books.get(m["entity_key"], "—"),
        } for m in _rows(
            conn,
            """
            SELECT entity_key, entity_name, book_exposure
            FROM REPORT.V_ENTITY_EXPOSURE
            WHERE run_id = {run_id} AND group_key = {gk}
            ORDER BY book_exposure DESC
            """,
            run_id=effective_run_id,
            gk=group_key,
        )]

        return {
            "group_key": group_key,
            "group_name": group_name,
            "run_id": effective_run_id,
            "is_latest": is_latest,
            "tree_nodes": tree_nodes,
            "members": members,
        }
    finally:
        conn.close()


def get_lineage_entity_data(entity_key: str) -> dict[str, Any] | None:
    if is_mock_mode():
        from ui.mock_data import get_mock_lineage_entity_data

        return get_mock_lineage_entity_data(entity_key)

    conn = _get_reader_connection()
    try:
        run_id, _ = _current_run(conn)
        rows = _rows(
            conn,
            """
            SELECT e.entity_key, e.entity_name, e.group_key, g.group_name, e.book_exposure,
                   e.funded_amt, e.undrawn_amt, e.holding_amt, e.gte_fin_amt, e.gte_perf_amt, e.published_at
            FROM REPORT.V_ENTITY_EXPOSURE e
            LEFT JOIN REPORT.V_GROUP_EXPOSURE g ON g.run_id = e.run_id AND g.group_key = e.group_key
            WHERE e.run_id = {run_id} AND e.entity_key = {k}
            """,
            run_id=run_id,
            k=entity_key,
        )
        if not rows:
            return None
        r = rows[0]
        return {
            "entity_key": entity_key,
            "entity_name": r["entity_name"] or entity_key,
            "cin": entity_key.removeprefix("E:") if entity_key.startswith("E:") else None,
            "group_key": r["group_key"],
            "group_name": r["group_name"] or r["group_key"],
            "exposure": _dec(r["book_exposure"]),
            "published_at": str(r["published_at"]) if r["published_at"] else None,
            "components": [
                ("Funded", _dec(r["funded_amt"])),
                ("Undrawn (CCF)", _dec(r["undrawn_amt"])),
                ("Treasury holdings", _dec(r["holding_amt"])),
                ("Financial guarantees", _dec(r["gte_fin_amt"])),
                ("Performance guarantees", _dec(r["gte_perf_amt"])),
            ],
        }
    finally:
        conn.close()


def get_lineage_rows_data(group_key: str, source: str = "", product: str = "", run_id: str | None = None) -> list[dict[str, Any]]:
    if is_mock_mode():
        from ui.mock_data import get_mock_lineage_rows_data

        return get_mock_lineage_rows_data(group_key=group_key or "GRP-017", source=source, product=product, run_id=run_id)

    conn = _get_reader_connection()
    try:
        effective_run_id = run_id or _current_run(conn)[0]

        clauses = ["run_id = {run_id}"]
        params: dict[str, Any] = {"run_id": effective_run_id}
        if group_key:  # empty = every group in the run (capped below)
            clauses.append("group_key = {gk}")
            params["gk"] = group_key
        if source:
            clauses.append("source_system = {src}")
            params["src"] = source
        if product:
            clauses.append("product = {prod}")
            params["prod"] = product

        rows_raw = conn.execute(
            f"""
            SELECT entity_name, source_system, source_row_id, product, exposure_component,
                   gross_amount, ccf, exposure_amount, link_proposal_id, link_decision_id,
                   reviewer, decided_at, tier
            FROM REPORT.V_LINEAGE
            WHERE {" AND ".join(clauses)}
            ORDER BY exposure_amount DESC
            LIMIT 1000
            """,
            query_params=params,
        ).fetchall()

        return [{
            "entity_name": r["entity_name"],
            "source_system": r["source_system"],
            "source_row_id": r["source_row_id"],
            "product": r["product"],
            "component": r["exposure_component"],
            "gross_amount": _dec(r["gross_amount"]),
            "ccf": _dec(r["ccf"]),
            "exposure_amount": _dec(r["exposure_amount"]),
            "proposal_id": r["link_proposal_id"],
            "decision_id": r["link_decision_id"],
            "reviewer": r["reviewer"] or "System",
            "decided_at": str(r["decided_at"]) if r["decided_at"] else "—",
            "tier": r["tier"] or "—",
        } for r in rows_raw]
    finally:
        conn.close()


def get_pipeline_data() -> dict[str, Any]:
    if is_mock_mode():
        from ui.mock_data import get_mock_pipeline_data

        return get_mock_pipeline_data()

    conn = _get_reader_connection()
    try:
        timings = [
            {"stage": r["stage"], "rows": int(r["rows_affected"] or 0), "seconds": float(r["seconds"] or 0)}
            for r in _rows(conn, "SELECT stage, rows_affected, seconds FROM REPORT.V_PIPELINE_TIMING ORDER BY started_at")
        ]
        paths = [
            {"via_path": r["via_path"], "count": int(r["candidate_count"] or 0)}
            for r in _rows(conn, "SELECT via_path, candidate_count FROM REPORT.V_CANDIDATE_PATHS ORDER BY candidate_count DESC")
        ]
        tiers = [
            {"tier": r["tier"], "count": int(r["n"] or 0)}
            for r in _rows(conn, 'SELECT tier, "COUNT" AS n FROM REPORT.V_TIER_COUNTS ORDER BY tier')
        ]
        s = (_rows(
            conn,
            """
            SELECT total_book_records, total_reg_entities, total_candidates,
                   settled_in_sql_pct, sent_to_model_pct, reduction_ratio
            FROM REPORT.V_PIPELINE_SUMMARY
            """,
        ) or [None])[0]

        return {
            "job_id": "LATEST_MATCH",
            "timings": timings,
            "paths": paths,
            "tiers": tiers,
            "summary": {
                "total_book_records": int(s["total_book_records"] or 0) if s else 0,
                "total_reg_entities": int(s["total_reg_entities"] or 0) if s else 0,
                "total_candidates": int(s["total_candidates"] or 0) if s else 0,
                "settled_in_sql_pct": _dec(s["settled_in_sql_pct"] if s else None),
                "sent_to_model_pct": _dec(s["sent_to_model_pct"] if s else None),
                "reduction_ratio": _dec(s["reduction_ratio"] if s else None),
            },
        }
    finally:
        conn.close()


def get_audit_data() -> list[dict[str, Any]]:
    if is_mock_mode():
        from ui.mock_data import get_mock_audit_data

        return get_mock_audit_data()

    conn = _get_reader_connection()
    try:
        return [
            {
                "run_id": r["run_id"],
                "business_date": str(r["business_date"]),
                "known_at": str(r["known_at"]),
                "code_version": r["code_version"],
                "output_hash": r["output_hash"],
                "status": r["status"],
                "replay_of": r["replay_of"],
            }
            for r in _rows(
                conn,
                """
                SELECT run_id, business_date, known_at, code_version, output_hash, status, replay_of
                FROM REPORT.V_RUNS
                ORDER BY started_at DESC
                """,
            )
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
