from typing import Any

import httpx

from pulseboard.checker import check_monitor
from pulseboard.models import Monitor


def make_monitor(**changes: Any) -> Monitor:
    values = {
        "name": "Example",
        "url": "https://example.test/health",
        "method": "GET",
        "interval_seconds": 60,
        "timeout_seconds": 2,
        "expected_status_min": 200,
        "expected_status_max": 299,
        "active": True,
    }
    values.update(changes)
    return Monitor(**values)


async def test_unexpected_status_is_down() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(429, request=request))
    async with httpx.AsyncClient(transport=transport) as client:
        outcome = await check_monitor(client, make_monitor(), allow_private_targets=True)

    assert outcome.status == "down"
    assert outcome.status_code == 429
    assert outcome.error == "Unexpected HTTP 429"


async def test_network_error_is_recorded_without_raising() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        outcome = await check_monitor(client, make_monitor(), allow_private_targets=True)

    assert outcome.status == "down"
    assert outcome.status_code is None
    assert outcome.error == "connection refused"
