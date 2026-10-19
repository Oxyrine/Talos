"""ui/app.py: FastAPI production application for Talos.

Provides server-rendered UI with Jinja2, HTMX 2.0.4, strict CSP,
session authentication, and Exasol / mock query integration.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from orchestrator.decide import BatchProtectedError, ProposalConflictError, UnauthorizedReviewerError
from ui.auth import (
    COOKIE_NAME,
    SESSION_MAX_AGE,
    SessionUser,
    clear_failed_attempts,
    create_session_token,
    get_client_ip,
    get_current_user_optional,
    is_mock_mode,
    require_approver,
    require_auth,
    verify_origin,
    verify_reviewer,
)
from ui.formatting import (
    gauge_bar_class,
    gauge_bar_width,
    inr_cr,
    inr_full,
    parse_evidence,
    percentage,
)
from ui.queries import (
    DatabaseUnavailableError,
    execute_batch,
    execute_decision,
    execute_replay,
    execute_ruling,
    get_audit_data,
    get_batch_data,
    get_board_data,
    get_lineage_group_data,
    get_lineage_rows_data,
    get_pipeline_data,
    get_queue_data,
)

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="Talos",
    description="Deterministic Credit Risk & Group Exposure Engine for Exasol",
    docs_url=None,
    redoc_url=None,
)

# Static files
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Jinja2 templates & custom filters
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.filters["inr_cr"] = inr_cr
templates.env.filters["inr_full"] = inr_full
templates.env.filters["percentage"] = percentage
templates.env.filters["parse_evidence"] = parse_evidence
templates.env.filters["gauge_bar_width"] = gauge_bar_width
templates.env.filters["gauge_bar_class"] = gauge_bar_class


# -----------------------------------------------------------------------------
# Security Headers Middleware
# -----------------------------------------------------------------------------
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response: Response = await call_next(request)

    # Strict Content Security Policy - zero unsafe-inline allowed
    csp_directives = [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "frame-ancestors 'none'",
        "form-action 'self'",
    ]
    response.headers["Content-Security-Policy"] = "; ".join(csp_directives)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    return response


# -----------------------------------------------------------------------------
# Exception Handlers
# -----------------------------------------------------------------------------
@app.exception_handler(DatabaseUnavailableError)
async def database_unavailable_handler(request: Request, exc: DatabaseUnavailableError):
    if request.headers.get("hx-request") == "true":
        return HTMLResponse(
            content=f'<div class="banner banner-danger">Database Unavailable: {exc}</div>',
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return templates.TemplateResponse(
        request=request,
        name="503.html",
        context={"error_detail": str(exc), "is_mock": is_mock_mode()},
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@app.exception_handler(BatchProtectedError)
async def batch_protected_handler(request: Request, exc: BatchProtectedError):
    if request.headers.get("hx-request") == "true":
        return HTMLResponse(
            content=f'<div class="alert alert-danger">HTTP 409 Conflict: {exc} (Must be decided as part of the batch).</div>',
            status_code=status.HTTP_409_CONFLICT,
        )
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@app.exception_handler(ProposalConflictError)
async def proposal_conflict_handler(request: Request, exc: ProposalConflictError):
    if request.headers.get("hx-request") == "true":
        return HTMLResponse(
            content=f'<div class="alert alert-danger">HTTP 409 Conflict: {exc}</div>',
            status_code=status.HTTP_409_CONFLICT,
        )
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@app.exception_handler(UnauthorizedReviewerError)
async def unauthorized_reviewer_handler(request: Request, exc: UnauthorizedReviewerError):
    if request.headers.get("hx-request") == "true":
        return HTMLResponse(
            content=f'<div class="alert alert-danger">HTTP 403 Forbidden: {exc}</div>',
            status_code=status.HTTP_403_FORBIDDEN,
        )
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


# -----------------------------------------------------------------------------
# Healthcheck & Base Redirect
# -----------------------------------------------------------------------------
@app.get("/healthz")
async def healthz():
    return {"status": "ok", "mock": is_mock_mode()}


@app.get("/")
async def root(request: Request):
    user = get_current_user_optional(request)
    if not user:
        return RedirectResponse(url="/signin", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/board", status_code=status.HTTP_303_SEE_OTHER)


# -----------------------------------------------------------------------------
# Auth Routes
# -----------------------------------------------------------------------------
@app.get("/signin")
async def signin_page(request: Request, error: str | None = None):
    user = get_current_user_optional(request)
    if user:
        return RedirectResponse(url="/board", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request=request,
        name="signin.html",
        context={"error": error, "is_mock": is_mock_mode()},
    )


@app.post("/signin")
async def signin_action(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    verify_origin(request)
    client_ip = get_client_ip(request)

    try:
        user = verify_reviewer(username.strip(), password, client_ip)
    except HTTPException as e:
        return templates.TemplateResponse(
            request=request,
            name="signin.html",
            context={"error": e.detail, "is_mock": is_mock_mode()},
            status_code=e.status_code,
        )

    if not user:
        return templates.TemplateResponse(
            request=request,
            name="signin.html",
            context={"error": "Invalid reviewer credentials.", "is_mock": is_mock_mode()},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    token = create_session_token(user)
    response = RedirectResponse(url="/board", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="strict",
        secure=False,  # Allow local HTTP development
    )
    return response


@app.post("/signout")
async def signout_action(request: Request):
    verify_origin(request)
    response = RedirectResponse(url="/signin", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(COOKIE_NAME)
    return response


# -----------------------------------------------------------------------------
# Screen 1: Exposure Board (/board)
# -----------------------------------------------------------------------------
@app.get("/board")
async def exposure_board(
    request: Request,
    user: SessionUser = Depends(require_auth),
    sort: str = Query("hidden", pattern="^(hidden|util|exposure)$"),
    view: str = Query("talos", pattern="^(talos|reported)$"),
    bd: str = Query("2026-09-30"),
):
    board = get_board_data(business_date=bd, sort=sort, view=view)
    ctx = {
        "user": user,
        "is_mock": is_mock_mode(),
        "active_nav": "board",
        "board": board,
        "sort": sort,
        "view": view,
        "bd": bd,
    }
    return templates.TemplateResponse(request=request, name="board.html", context=ctx)


# -----------------------------------------------------------------------------
# Screen 2: Review Queue (/queue)
# -----------------------------------------------------------------------------
@app.get("/queue")
async def review_queue(
    request: Request,
    user: SessionUser = Depends(require_auth),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=5, le=100),
    tier: str = Query(""),
    kind: str = Query(""),
):
    queue = get_queue_data(page=page, per_page=per_page, tier=tier, kind=kind)
    ctx = {
        "user": user,
        "is_mock": is_mock_mode(),
        "active_nav": "queue",
        "queue": queue,
        "tier": tier,
        "kind": kind,
    }
    return templates.TemplateResponse(request=request, name="queue.html", context=ctx)


@app.get("/queue/batch/{batch_id}")
async def batch_review_page(
    batch_id: str,
    request: Request,
    user: SessionUser = Depends(require_auth),
):
    batch = get_batch_data(batch_id=batch_id, user_name=user.username)
    ctx = {
        "user": user,
        "is_mock": is_mock_mode(),
        "active_nav": "queue",
        "batch": batch,
    }
    return templates.TemplateResponse(request=request, name="batch.html", context=ctx)


@app.post("/queue/batch/{batch_id}")
async def submit_batch_decision(
    batch_id: str,
    request: Request,
    user: SessionUser = Depends(require_approver),
):
    verify_origin(request)
    form_data = await request.form()

    seed = int(form_data.get("seed", 0))
    token = str(form_data.get("token", ""))
    reason = str(form_data.get("reason", "Batch sample approved")).strip()

    # Extract pair verdicts from form: pair_{pid} = "APPROVE" | "REJECT"
    verdicts: dict[str, bool] = {}
    for key, value in form_data.items():
        if key.startswith("pair_"):
            pid = key[5:]
            verdicts[pid] = (value == "APPROVE")

    res = execute_batch(
        batch_id=batch_id,
        seed=seed,
        token=token,
        verdicts=verdicts,
        reason=reason,
        reviewer_name=user.username,
        reviewer_role=user.role,
    )

    if request.headers.get("hx-request") == "true":
        response = Response(status_code=status.HTTP_200_OK)
        response.headers["HX-Redirect"] = "/queue"
        return response

    return RedirectResponse(url="/queue", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/proposals/{proposal_id}/decision")
async def decide_proposal(
    proposal_id: str,
    request: Request,
    user: SessionUser = Depends(require_approver),
    decision: str = Form(..., pattern="^(APPROVE|REJECT)$"),
    reason: str = Form(...),
):
    verify_origin(request)
    res = execute_decision(
        proposal_id=proposal_id,
        decision=decision,
        reason=reason.strip(),
        reviewer_name=user.username,
        reviewer_role=user.role,
    )

    # Return decided card replacement + OOB KPI ribbon update
    kpi = res["kpi"]
    oob_ribbon = f"""
    <div id="header-kpi-ribbon" hx-swap-oob="outerHTML" class="kpi-ribbon">
      <div class="kpi-tile {'danger-state' if kpi['hidden_exposure'] > 0 else ''}">
        <div class="kpi-label">Hidden Exposure Unmasked</div>
        <div class="kpi-value tabular-nums">
          {'+' if kpi['hidden_exposure'] > 0 else ''}{inr_cr(kpi['hidden_exposure'])}
        </div>
        <div class="kpi-sub">Across unconsolidated connected perimeters</div>
      </div>
      <div class="kpi-tile {'danger-state' if kpi['breaches_count'] > 0 else ''}">
        <div class="kpi-label">Group Limit Breaches (>25%)</div>
        <div class="kpi-value tabular-nums">{kpi['breaches_count']}</div>
        <div class="kpi-sub">RBI Large Exposures Framework (LEF) §5.1</div>
      </div>
      <div class="kpi-tile">
        <div class="kpi-label">Large Exposures (≥10%)</div>
        <div class="kpi-value tabular-nums">{kpi['large_count']}</div>
        <div class="kpi-sub">Subject to statutory credit concentration reporting</div>
      </div>
      <div class="kpi-tile">
        <div class="kpi-label">Eligible Capital Base</div>
        <div class="kpi-value tabular-nums">₹420.0 cr</div>
        <div class="kpi-sub">Tier 1 + Tier 2 capital denominator</div>
      </div>
    </div>
    """

    card_content = f"""
    <div id="card-{proposal_id}" class="proposal-card">
      <div class="proposal-header">
        <div>
          <span class="badge badge-{'success' if decision == 'APPROVE' else 'danger'}">
            {'✓ LINK APPROVED' if decision == 'APPROVE' else '✗ LINK REJECTED'}
          </span>
          <span class="text-muted font-mono ml-2">{proposal_id}</span>
          <p class="text-muted text-xs mt-2">
            Decided by <strong>{user.username}</strong> ({user.role}) • Rationale: <em>"{reason.strip()}"</em>
          </p>
        </div>
      </div>
    </div>
    """

    return HTMLResponse(content=card_content + oob_ribbon)


# -----------------------------------------------------------------------------
# JV Ruling (/rulings/{proposal_id})
# -----------------------------------------------------------------------------
@app.get("/rulings/{proposal_id}")
async def ruling_page(
    proposal_id: str,
    request: Request,
    user: SessionUser = Depends(require_auth),
):
    ctx = {
        "user": user,
        "is_mock": is_mock_mode(),
        "active_nav": "queue",
        "proposal_id": proposal_id,
        "entity_name": "Sunrise-Apex Infrastructure JV Pvt Ltd",
        "gross_exposure": 280000000,
        "partner_a": "Sunrise Industries Ltd",
        "partner_a_pct": 50,
        "partner_b": "Apex Capital Ltd",
        "partner_b_pct": 50,
    }
    return templates.TemplateResponse(request=request, name="ruling.html", context=ctx)


@app.post("/rulings/{proposal_id}")
async def submit_ruling(
    proposal_id: str,
    request: Request,
    user: SessionUser = Depends(require_approver),
    ruling: str = Form(..., pattern="^(LEAD_CONSOLIDATES|EQUAL_SPLIT|PROPORTIONAL|STANDALONE)$"),
    controller: str = Form(None),
    reason: str = Form(...),
):
    verify_origin(request)
    execute_ruling(
        proposal_id=proposal_id,
        ruling=ruling,
        controller=controller,
        reason=reason.strip(),
        reviewer_name=user.username,
        reviewer_role=user.role,
    )
    return RedirectResponse(url="/queue", status_code=status.HTTP_303_SEE_OTHER)


# -----------------------------------------------------------------------------
# Lineage Views (/lineage/...)
# -----------------------------------------------------------------------------
@app.get("/lineage/group/{group_key}")
async def lineage_group_view(
    group_key: str,
    request: Request,
    user: SessionUser = Depends(require_auth),
    run_id: str | None = Query(None),
):
    data = get_lineage_group_data(group_key=group_key, run_id=run_id)
    ctx = {
        "user": user,
        "is_mock": is_mock_mode(),
        "active_nav": "lineage",
        "data": data,
        "group_key": group_key,
    }
    return templates.TemplateResponse(request=request, name="lineage_group.html", context=ctx)


@app.get("/lineage/entity/{entity_key}")
async def lineage_entity_view(
    entity_key: str,
    request: Request,
    user: SessionUser = Depends(require_auth),
):
    ctx = {
        "user": user,
        "is_mock": is_mock_mode(),
        "active_nav": "lineage",
        "entity_key": entity_key,
        "entity_name": "Sunrise Industries Ltd" if "017" in entity_key else entity_key,
        "cin": "U12345MH2010PLC123456",
        "pan": "AABCS1234D",
        "group_name": "Sunrise Group (GRP-017)",
    }
    return templates.TemplateResponse(request=request, name="lineage_entity.html", context=ctx)


@app.get("/lineage/rows")
async def lineage_rows_view(
    request: Request,
    user: SessionUser = Depends(require_auth),
    group_key: str = Query("GRP-017"),
    source: str = Query(""),
    product: str = Query(""),
    run_id: str | None = Query(None),
):
    rows = get_lineage_rows_data(group_key=group_key, source=source, product=product, run_id=run_id)
    ctx = {
        "user": user,
        "is_mock": is_mock_mode(),
        "active_nav": "lineage",
        "rows": rows,
        "group_key": group_key,
        "source": source,
        "product": product,
    }
    return templates.TemplateResponse(request=request, name="lineage_rows.html", context=ctx)


# -----------------------------------------------------------------------------
# Diagnostic & Audit Screens (/pipeline, /audit)
# -----------------------------------------------------------------------------
@app.get("/pipeline")
async def pipeline_diagnostics(
    request: Request,
    user: SessionUser = Depends(require_auth),
):
    data = get_pipeline_data()
    ctx = {
        "user": user,
        "is_mock": is_mock_mode(),
        "active_nav": "pipeline",
        "data": data,
    }
    return templates.TemplateResponse(request=request, name="pipeline.html", context=ctx)


@app.get("/audit")
async def audit_runs(
    request: Request,
    user: SessionUser = Depends(require_auth),
):
    runs = get_audit_data()
    ctx = {
        "user": user,
        "is_mock": is_mock_mode(),
        "active_nav": "audit",
        "runs": runs,
    }
    return templates.TemplateResponse(request=request, name="audit.html", context=ctx)


@app.post("/audit/replay/{run_id}")
async def replay_run_action(
    run_id: str,
    request: Request,
    user: SessionUser = Depends(require_approver),
):
    verify_origin(request)
    res = execute_replay(run_id)
    if res["matches"]:
        return HTMLResponse(
            content=f"""
            <span class="badge badge-success">
              ✓ REPLAY MATCH • {res['replay_hash'][:12]}... (Deterministic)
            </span>
            """
        )
    return HTMLResponse(
        content=f"""
        <span class="badge badge-danger">
          ✗ REPLAY MISMATCH • Expected {res.get('original_hash', '')[:12]}... got {res.get('replay_hash', '')[:12]}...
        </span>
        """
    )
