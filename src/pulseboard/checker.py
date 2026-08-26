"""HTTP check execution."""

from dataclasses import dataclass
from time import perf_counter

import httpx

from .models import Monitor
from .security import validate_target_url


@dataclass(frozen=True, slots=True)
class CheckOutcome:
    status: str
    status_code: int | None
    duration_ms: float | None
    error: str | None


async def check_monitor(
    client: httpx.AsyncClient,
    monitor: Monitor,
    *,
    allow_private_targets: bool,
) -> CheckOutcome:
    """Run one bounded request without following redirects."""

    started = perf_counter()
    try:
        await validate_target_url(monitor.url, allow_private_targets=allow_private_targets)
        async with client.stream(
            monitor.method,
            monitor.url,
            follow_redirects=False,
            timeout=httpx.Timeout(monitor.timeout_seconds),
        ) as response:
            duration_ms = round((perf_counter() - started) * 1_000, 1)
            is_up = (
                monitor.expected_status_min <= response.status_code <= monitor.expected_status_max
            )
            return CheckOutcome(
                status="up" if is_up else "down",
                status_code=response.status_code,
                duration_ms=duration_ms,
                error=None if is_up else f"Unexpected HTTP {response.status_code}",
            )
    except (httpx.HTTPError, ValueError) as error:
        duration_ms = round((perf_counter() - started) * 1_000, 1)
        return CheckOutcome(
            status="down",
            status_code=None,
            duration_ms=duration_ms,
            error=str(error)[:500],
        )
