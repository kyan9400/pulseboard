from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from pulseboard.config import Settings
from pulseboard.main import create_app


@pytest.fixture
def target_state() -> dict[str, Any]:
    return {"status_code": 204, "requests": []}


@pytest.fixture
async def client(
    tmp_path: Path,
    target_state: dict[str, Any],
) -> AsyncGenerator[AsyncClient, None]:
    def target(request: httpx.Request) -> httpx.Response:
        target_state["requests"].append(request)
        return httpx.Response(target_state["status_code"], request=request)

    settings = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'pulseboard.db').as_posix()}",
        allow_private_targets=True,
        enable_scheduler=False,
        max_checks_per_monitor=20,
    )
    app = create_app(settings, http_transport=httpx.MockTransport(target))
    async with (
        LifespanManager(app),
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as test_client,
    ):
        yield test_client


@pytest.fixture
def monitor_payload() -> dict[str, Any]:
    return {
        "name": "Customer API",
        "url": "https://status.example.test/health",
        "method": "GET",
        "interval_seconds": 60,
        "timeout_seconds": 5,
        "expected_status_min": 200,
        "expected_status_max": 299,
    }
