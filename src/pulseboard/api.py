"""HTTP API and dashboard routes."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_session
from .schemas import (
    CheckView,
    IncidentView,
    MonitorCreate,
    MonitorUpdate,
    MonitorView,
    StatusSummary,
)
from .security import require_write_access, validate_target_url
from .service import (
    create_monitor,
    delete_monitor,
    get_monitor,
    list_checks,
    list_incidents,
    list_monitor_views,
    perform_check,
    update_monitor,
)

PACKAGE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")
router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]
HistoryLimit = Annotated[int, Query(ge=1, le=500)]


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found.")


def _status_summary(monitor_views: list[MonitorView]) -> StatusSummary:
    counts = {
        state: sum(view.current_status == state for view in monitor_views)
        for state in ("up", "down", "pending", "paused")
    }
    if counts["down"]:
        overall = "degraded"
    elif counts["up"]:
        overall = "operational"
    else:
        overall = "unknown"
    return StatusSummary(
        generated_at=datetime.now(UTC),
        overall_status=overall,
        monitors_up=counts["up"],
        monitors_down=counts["down"],
        monitors_pending=counts["pending"],
        monitors_paused=counts["paused"],
        monitors=monitor_views,
    )


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"show_docs": request.app.state.settings.show_docs},
    )


@router.get("/status", response_class=HTMLResponse, include_in_schema=False)
async def status_page(request: Request, session: Session) -> HTMLResponse:
    summary = _status_summary(await list_monitor_views(session))
    recent_incidents = await list_incidents(session, limit=20)
    return templates.TemplateResponse(
        request=request,
        name="status.html",
        context={"summary": summary, "incidents": recent_incidents},
        headers={"Cache-Control": "public, max-age=10"},
    )


@router.get("/api/monitors", response_model=list[MonitorView], tags=["monitors"])
async def monitors(session: Session) -> list[MonitorView]:
    return await list_monitor_views(session)


@router.post(
    "/api/monitors",
    response_model=MonitorView,
    status_code=status.HTTP_201_CREATED,
    tags=["monitors"],
    dependencies=[Depends(require_write_access)],
)
async def add_monitor(
    request: Request,
    payload: MonitorCreate,
    session: Session,
) -> MonitorView:
    try:
        await validate_target_url(
            str(payload.url),
            allow_private_targets=request.app.state.settings.allow_private_targets,
        )
        monitor = await create_monitor(session, payload)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    views = await list_monitor_views(session)
    return next(view for view in views if view.id == monitor.id)


@router.patch(
    "/api/monitors/{monitor_id}",
    response_model=MonitorView,
    tags=["monitors"],
    dependencies=[Depends(require_write_access)],
)
async def edit_monitor(
    request: Request,
    monitor_id: str,
    payload: MonitorUpdate,
    session: Session,
) -> MonitorView:
    monitor = await get_monitor(session, monitor_id)
    if monitor is None:
        raise _not_found()
    if payload.url is not None:
        try:
            await validate_target_url(
                str(payload.url),
                allow_private_targets=request.app.state.settings.allow_private_targets,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
            ) from error
    try:
        await update_monitor(session, monitor, payload)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    views = await list_monitor_views(session)
    return next(view for view in views if view.id == monitor.id)


@router.delete(
    "/api/monitors/{monitor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["monitors"],
    dependencies=[Depends(require_write_access)],
)
async def remove_monitor(
    monitor_id: str,
    session: Session,
) -> Response:
    monitor = await get_monitor(session, monitor_id)
    if monitor is None:
        raise _not_found()
    await delete_monitor(session, monitor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/api/monitors/{monitor_id}/checks",
    response_model=CheckView,
    status_code=status.HTTP_201_CREATED,
    tags=["checks"],
    dependencies=[Depends(require_write_access)],
)
async def run_check(request: Request, monitor_id: str) -> CheckView:
    check = await perform_check(
        request.app.state.database,
        request.app.state.http_client,
        request.app.state.settings,
        monitor_id,
    )
    if check is None:
        raise _not_found()
    return CheckView.model_validate(check)


@router.get(
    "/api/monitors/{monitor_id}/checks",
    response_model=list[CheckView],
    tags=["checks"],
)
async def check_history(
    monitor_id: str,
    session: Session,
    limit: HistoryLimit = 50,
) -> list[CheckView]:
    if await get_monitor(session, monitor_id) is None:
        raise _not_found()
    return [
        CheckView.model_validate(check)
        for check in await list_checks(session, monitor_id, limit=limit)
    ]


@router.get("/api/incidents", response_model=list[IncidentView], tags=["incidents"])
async def incidents(
    session: Session,
    limit: HistoryLimit = 50,
) -> list[IncidentView]:
    return await list_incidents(session, limit=limit)


@router.get("/api/status", response_model=StatusSummary, tags=["status"])
async def public_status(session: Session) -> StatusSummary:
    return _status_summary(await list_monitor_views(session))


@router.get("/health/live", include_in_schema=False)
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", include_in_schema=False)
async def readiness(session: Session) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"status": "ready"}


@router.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
async def metrics(session: Session) -> PlainTextResponse:
    views = await list_monitor_views(session)
    states = ("up", "down", "pending", "paused")
    lines = [
        "# HELP pulseboard_monitors Number of configured monitors by current state.",
        "# TYPE pulseboard_monitors gauge",
        *(
            f'pulseboard_monitors{{state="{state}"}} '
            f"{sum(view.current_status == state for view in views)}"
            for state in states
        ),
        "# HELP pulseboard_open_incidents Number of unresolved incidents.",
        "# TYPE pulseboard_open_incidents gauge",
        f"pulseboard_open_incidents {sum(view.has_open_incident for view in views)}",
        "",
    ]
    return PlainTextResponse("\n".join(lines), media_type="text/plain; version=0.0.4")
