"""Monitor persistence, summaries, incident state, and scheduling."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import case, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .checker import CheckOutcome, check_monitor
from .config import Settings
from .database import Database
from .models import Check, Incident, Monitor, utc_now
from .schemas import CheckView, IncidentView, MonitorCreate, MonitorUpdate, MonitorView, SloView

logger = logging.getLogger(__name__)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def create_monitor(session: AsyncSession, payload: MonitorCreate) -> Monitor:
    monitor = Monitor(**payload.model_dump(mode="json"))
    try:
        session.add(monitor)
        await session.commit()
        await session.refresh(monitor)
        return monitor
    except IntegrityError as error:
        await session.rollback()
        raise ValueError("a monitor with this URL already exists") from error


async def update_monitor(
    session: AsyncSession, monitor: Monitor, payload: MonitorUpdate
) -> Monitor:
    changes = payload.model_dump(exclude_unset=True, mode="json")
    minimum = changes.get("expected_status_min", monitor.expected_status_min)
    maximum = changes.get("expected_status_max", monitor.expected_status_max)
    if minimum > maximum:
        raise ValueError("expected_status_min must not exceed expected_status_max")
    for name, value in changes.items():
        setattr(monitor, name, value)
    try:
        await session.commit()
        await session.refresh(monitor)
        return monitor
    except IntegrityError as error:
        await session.rollback()
        raise ValueError("a monitor with this URL already exists") from error


async def get_monitor(session: AsyncSession, monitor_id: str) -> Monitor | None:
    return await session.get(Monitor, monitor_id)


async def delete_monitor(session: AsyncSession, monitor: Monitor) -> None:
    await session.delete(monitor)
    await session.commit()


async def record_outcome(
    session: AsyncSession,
    monitor_id: str,
    outcome: CheckOutcome,
    *,
    max_history: int,
) -> Check:
    checked_at = utc_now()
    check = Check(
        monitor_id=monitor_id,
        checked_at=checked_at,
        status=outcome.status,
        status_code=outcome.status_code,
        duration_ms=outcome.duration_ms,
        error=outcome.error,
    )
    session.add(check)
    await session.flush()

    open_incident = await session.scalar(
        select(Incident).where(
            Incident.monitor_id == monitor_id,
            Incident.resolved_at.is_(None),
        )
    )
    if outcome.status == "down" and open_incident is None:
        session.add(
            Incident(
                monitor_id=monitor_id,
                started_at=checked_at,
                cause=outcome.error or "Availability check failed",
            )
        )
    elif outcome.status == "up" and open_incident is not None:
        open_incident.resolved_at = checked_at

    retained_ids = (
        select(Check.id)
        .where(Check.monitor_id == monitor_id)
        .order_by(Check.checked_at.desc(), Check.id.desc())
        .limit(max_history)
    )
    await session.execute(
        delete(Check).where(Check.monitor_id == monitor_id, Check.id.not_in(retained_ids))
    )
    await session.commit()
    await session.refresh(check)
    return check


async def list_checks(session: AsyncSession, monitor_id: str, *, limit: int = 50) -> list[Check]:
    checks = await session.scalars(
        select(Check)
        .where(Check.monitor_id == monitor_id)
        .order_by(Check.checked_at.desc(), Check.id.desc())
        .limit(limit)
    )
    return list(checks)


async def list_incidents(session: AsyncSession, *, limit: int = 50) -> list[IncidentView]:
    rows = await session.execute(
        select(Incident, Monitor.name)
        .join(Monitor, Monitor.id == Incident.monitor_id)
        .order_by(Incident.started_at.desc(), Incident.id.desc())
        .limit(limit)
    )
    return [
        IncidentView(
            id=incident.id,
            monitor_id=incident.monitor_id,
            monitor_name=monitor_name,
            started_at=incident.started_at,
            resolved_at=incident.resolved_at,
            cause=incident.cause,
        )
        for incident, monitor_name in rows
    ]


async def list_monitor_views(session: AsyncSession) -> list[MonitorView]:
    latest_check_id = (
        select(Check.id)
        .where(Check.monitor_id == Monitor.id)
        .order_by(Check.checked_at.desc(), Check.id.desc())
        .limit(1)
        .correlate(Monitor)
        .scalar_subquery()
    )
    rows = (
        await session.execute(
            select(Monitor, Check)
            .outerjoin(Check, Check.id == latest_check_id)
            .order_by(Monitor.name.asc())
        )
    ).all()

    cutoff = utc_now() - timedelta(hours=24)
    availability_rows = await session.execute(
        select(
            Check.monitor_id,
            func.count(Check.id),
            func.sum(case((Check.status == "up", 1), else_=0)),
        )
        .where(Check.checked_at >= cutoff)
        .group_by(Check.monitor_id)
    )
    availability = {
        monitor_id: (int(up_count or 0) / int(total_count)) * 100
        for monitor_id, total_count, up_count in availability_rows
        if total_count
    }
    open_incident_ids = set(
        await session.scalars(select(Incident.monitor_id).where(Incident.resolved_at.is_(None)))
    )

    views: list[MonitorView] = []
    for monitor, latest_check in rows:
        if not monitor.active:
            current_status = "paused"
        elif latest_check is None:
            current_status = "pending"
        else:
            current_status = latest_check.status
        views.append(
            MonitorView(
                id=monitor.id,
                name=monitor.name,
                url=monitor.url,
                method=monitor.method,
                interval_seconds=monitor.interval_seconds,
                timeout_seconds=monitor.timeout_seconds,
                expected_status_min=monitor.expected_status_min,
                expected_status_max=monitor.expected_status_max,
                active=monitor.active,
                created_at=monitor.created_at,
                updated_at=monitor.updated_at,
                current_status=current_status,
                uptime_24h=round(availability[monitor.id], 2)
                if monitor.id in availability
                else None,
                last_check=CheckView.model_validate(latest_check) if latest_check else None,
                has_open_incident=monitor.id in open_incident_ids,
            )
        )
    return views


async def list_slo_views(
    session: AsyncSession, *, window_hours: int, target_percent: float
) -> list[SloView]:
    cutoff = utc_now() - timedelta(hours=window_hours)
    monitors = list(await session.scalars(select(Monitor).order_by(Monitor.name.asc())))
    rows = await session.execute(
        select(
            Check.monitor_id,
            func.count(Check.id),
            func.sum(case((Check.status == "down", 1), else_=0)),
        )
        .where(Check.checked_at >= cutoff)
        .group_by(Check.monitor_id)
    )
    counts = {monitor_id: (int(total or 0), int(failed or 0)) for monitor_id, total, failed in rows}
    window_seconds = window_hours * 3600
    allowed_downtime = window_seconds * (1 - target_percent / 100)
    views: list[SloView] = []
    for monitor in monitors:
        samples, failed = counts.get(monitor.id, (0, 0))
        estimated_downtime = min(float(window_seconds), float(failed * monitor.interval_seconds))
        remaining = max(0.0, allowed_downtime - estimated_downtime)
        if samples == 0:
            observed_uptime = None
            consumed = None
            slo_status = "no_data"
        else:
            observed_uptime = ((samples - failed) / samples) * 100
            consumed = (estimated_downtime / allowed_downtime) * 100
            if remaining == 0 and estimated_downtime > 0:
                slo_status = "exhausted"
            elif consumed >= 75:
                slo_status = "risk"
            else:
                slo_status = "healthy"
        views.append(
            SloView(
                monitor_id=monitor.id,
                monitor_name=monitor.name,
                target_percent=target_percent,
                window_hours=window_hours,
                samples=samples,
                failed_checks=failed,
                observed_uptime_percent=round(observed_uptime, 3)
                if observed_uptime is not None
                else None,
                allowed_downtime_seconds=round(allowed_downtime, 1),
                estimated_downtime_seconds=round(estimated_downtime, 1),
                remaining_budget_seconds=round(remaining, 1),
                budget_consumed_percent=round(consumed, 1) if consumed is not None else None,
                status=slo_status,
            )
        )
    return views


async def due_monitor_ids(session: AsyncSession) -> list[str]:
    latest = (
        select(Check.monitor_id, func.max(Check.checked_at).label("last_checked_at"))
        .group_by(Check.monitor_id)
        .subquery()
    )
    rows = await session.execute(
        select(Monitor.id, Monitor.interval_seconds, latest.c.last_checked_at)
        .outerjoin(latest, latest.c.monitor_id == Monitor.id)
        .where(Monitor.active.is_(True))
    )
    now = utc_now()
    return [
        monitor_id
        for monitor_id, interval_seconds, last_checked_at in rows
        if last_checked_at is None
        or _as_utc(last_checked_at) <= now - timedelta(seconds=interval_seconds)
    ]


async def perform_check(
    database: Database,
    client: httpx.AsyncClient,
    settings: Settings,
    monitor_id: str,
) -> Check | None:
    async with database.session_factory() as session:
        monitor = await session.get(Monitor, monitor_id)
        if monitor is None:
            return None

    outcome = await check_monitor(
        client,
        monitor,
        allow_private_targets=settings.allow_private_targets,
    )
    async with database.session_factory() as session:
        return await record_outcome(
            session,
            monitor_id,
            outcome,
            max_history=settings.max_checks_per_monitor,
        )


async def scheduler_loop(
    database: Database,
    client: httpx.AsyncClient,
    settings: Settings,
    stop_event: asyncio.Event,
) -> None:
    semaphore = asyncio.Semaphore(settings.check_concurrency)

    async def run_bounded(monitor_id: str) -> None:
        async with semaphore:
            try:
                await perform_check(database, client, settings, monitor_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Scheduled check failed for monitor %s", monitor_id)

    while not stop_event.is_set():
        async with database.session_factory() as session:
            monitor_ids = await due_monitor_ids(session)
        if monitor_ids:
            await asyncio.gather(*(run_bounded(monitor_id) for monitor_id in monitor_ids))
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.scheduler_tick_seconds)
        except TimeoutError:
            continue
