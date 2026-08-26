import asyncio
from pathlib import Path
from typing import Any

import httpx
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from pulseboard.config import Settings
from pulseboard.main import create_app


async def create_monitor(client: AsyncClient, payload: dict[str, Any]) -> dict[str, Any]:
    response = await client.post("/api/monitors", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def test_dashboard_health_and_security_headers(client: AsyncClient) -> None:
    dashboard = await client.get("/")
    assert dashboard.status_code == 200
    assert "Operations at a glance" in dashboard.text
    assert dashboard.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in dashboard.headers["content-security-policy"]
    javascript = await client.get("/static/app.js")
    assert javascript.status_code == 200
    assert javascript.headers["content-type"].startswith("text/javascript")

    assert (await client.get("/health/live")).json() == {"status": "ok"}
    assert (await client.get("/health/ready")).json() == {"status": "ready"}


async def test_monitor_lifecycle_and_manual_check(
    client: AsyncClient,
    monitor_payload: dict[str, Any],
    target_state: dict[str, Any],
) -> None:
    monitor = await create_monitor(client, monitor_payload)
    assert monitor["current_status"] == "pending"
    assert monitor["active"] is True

    checked = await client.post(f"/api/monitors/{monitor['id']}/checks")
    assert checked.status_code == 201
    assert checked.json()["status"] == "up"
    assert checked.json()["status_code"] == 204
    assert len(target_state["requests"]) == 1

    listed = (await client.get("/api/monitors")).json()
    assert listed[0]["current_status"] == "up"
    assert listed[0]["uptime_24h"] == 100.0

    paused = await client.patch(f"/api/monitors/{monitor['id']}", json={"active": False})
    assert paused.status_code == 200
    assert paused.json()["current_status"] == "paused"

    removed = await client.delete(f"/api/monitors/{monitor['id']}")
    assert removed.status_code == 204
    assert (await client.get("/api/monitors")).json() == []


async def test_incident_opens_once_and_resolves_on_recovery(
    client: AsyncClient,
    monitor_payload: dict[str, Any],
    target_state: dict[str, Any],
) -> None:
    monitor = await create_monitor(client, monitor_payload)
    target_state["status_code"] = 503

    first = await client.post(f"/api/monitors/{monitor['id']}/checks")
    second = await client.post(f"/api/monitors/{monitor['id']}/checks")
    assert first.json()["status"] == "down"
    assert second.json()["error"] == "Unexpected HTTP 503"

    incidents = (await client.get("/api/incidents")).json()
    assert len(incidents) == 1
    assert incidents[0]["resolved_at"] is None
    assert incidents[0]["monitor_name"] == monitor_payload["name"]

    target_state["status_code"] = 204
    recovered = await client.post(f"/api/monitors/{monitor['id']}/checks")
    assert recovered.json()["status"] == "up"
    incidents = (await client.get("/api/incidents")).json()
    assert incidents[0]["resolved_at"] is not None


async def test_status_and_prometheus_metrics(
    client: AsyncClient,
    monitor_payload: dict[str, Any],
) -> None:
    monitor = await create_monitor(client, monitor_payload)
    await client.post(f"/api/monitors/{monitor['id']}/checks")

    status_response = await client.get("/api/status")
    summary = status_response.json()
    assert summary["overall_status"] == "operational"
    assert summary["monitors_up"] == 1

    status_page = await client.get("/status")
    assert status_page.status_code == 200
    assert "All systems operational." in status_page.text
    assert monitor_payload["name"] in status_page.text
    assert monitor_payload["url"] not in status_page.text
    assert status_page.headers["cache-control"] == "public, max-age=10"

    metrics = await client.get("/metrics")
    assert metrics.status_code == 200
    assert 'pulseboard_monitors{state="up"} 1' in metrics.text
    assert "pulseboard_open_incidents 0" in metrics.text


async def test_duplicate_url_and_invalid_range_are_rejected(
    client: AsyncClient,
    monitor_payload: dict[str, Any],
) -> None:
    await create_monitor(client, monitor_payload)
    duplicate = await client.post("/api/monitors", json=monitor_payload)
    assert duplicate.status_code == 422
    assert "already exists" in duplicate.json()["detail"]

    invalid = {
        **monitor_payload,
        "url": "https://other.example.test",
        "expected_status_min": 400,
        "expected_status_max": 299,
    }
    response = await client.post("/api/monitors", json=invalid)
    assert response.status_code == 422


async def test_missing_monitor_routes_return_404(client: AsyncClient) -> None:
    monitor_id = "00000000-0000-0000-0000-000000000000"
    assert (
        await client.patch(f"/api/monitors/{monitor_id}", json={"active": False})
    ).status_code == 404
    assert (await client.delete(f"/api/monitors/{monitor_id}")).status_code == 404
    assert (await client.post(f"/api/monitors/{monitor_id}/checks")).status_code == 404
    assert (await client.get(f"/api/monitors/{monitor_id}/checks")).status_code == 404


async def test_write_routes_support_optional_api_key(
    tmp_path: Path,
    monitor_payload: dict[str, Any],
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'protected.db').as_posix()}",
        api_key="correct-horse-battery-staple",
        allow_private_targets=True,
        enable_scheduler=False,
    )
    app = create_app(
        settings,
        http_transport=httpx.MockTransport(lambda request: httpx.Response(204, request=request)),
    )
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as protected,
    ):
        denied = await protected.post("/api/monitors", json=monitor_payload)
        assert denied.status_code == 401
        created = await protected.post(
            "/api/monitors",
            json=monitor_payload,
            headers={"X-API-Key": "correct-horse-battery-staple"},
        )
        assert created.status_code == 201
        assert (await protected.get("/api/monitors")).status_code == 200


async def test_private_targets_are_blocked_by_default(
    tmp_path: Path,
    monitor_payload: dict[str, Any],
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'ssrf.db').as_posix()}",
        allow_private_targets=False,
        enable_scheduler=False,
    )
    app = create_app(settings)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as protected,
    ):
        payload = {**monitor_payload, "url": "http://127.0.0.1:9000/health"}
        response = await protected.post("/api/monitors", json=payload)
        assert response.status_code == 422
        assert "private" in response.json()["detail"]


async def test_background_scheduler_runs_due_monitors(
    tmp_path: Path,
    monitor_payload: dict[str, Any],
) -> None:
    requests: list[httpx.Request] = []

    def target(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204, request=request)

    settings = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'scheduler.db').as_posix()}",
        allow_private_targets=True,
        enable_scheduler=True,
        scheduler_tick_seconds=0.01,
    )
    app = create_app(settings, http_transport=httpx.MockTransport(target))
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as scheduled,
    ):
        created = await scheduled.post("/api/monitors", json=monitor_payload)
        assert created.status_code == 201
        for _ in range(20):
            await asyncio.sleep(0.01)
            monitors = (await scheduled.get("/api/monitors")).json()
            if monitors[0]["current_status"] == "up":
                break
        assert monitors[0]["current_status"] == "up"
        assert requests


async def test_production_mode_hides_interactive_docs(tmp_path: Path) -> None:
    settings = Settings(
        environment="production",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'production.db').as_posix()}",
        enable_scheduler=False,
    )
    app = create_app(settings)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as production,
    ):
        dashboard = await production.get("/")
        assert dashboard.status_code == 200
        assert 'href="/status">Status</a>' in dashboard.text
        assert (await production.get("/docs")).status_code == 404
        assert (await production.get("/openapi.json")).status_code == 404
