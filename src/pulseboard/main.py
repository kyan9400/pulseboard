"""FastAPI application factory."""

import asyncio
import mimetypes
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import router
from .config import Settings, get_settings
from .database import Database
from .service import scheduler_loop

PACKAGE_DIR = Path(__file__).resolve().parent
mimetypes.add_type("text/javascript", ".js")


def create_app(
    settings: Settings | None = None,
    *,
    http_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database(app_settings.database_url)
        await database.initialize()
        client = httpx.AsyncClient(
            transport=http_transport,
            headers={"User-Agent": app_settings.user_agent},
            limits=httpx.Limits(max_connections=app_settings.check_concurrency * 2),
        )
        stop_event = asyncio.Event()
        scheduler_task: asyncio.Task[None] | None = None

        app.state.database = database
        app.state.http_client = client
        app.state.settings = app_settings
        if app_settings.enable_scheduler:
            scheduler_task = asyncio.create_task(
                scheduler_loop(database, client, app_settings, stop_event),
                name="pulseboard-scheduler",
            )
        try:
            yield
        finally:
            stop_event.set()
            if scheduler_task is not None:
                scheduler_task.cancel()
                with suppress(asyncio.CancelledError):
                    await scheduler_task
            await client.aclose()
            await database.dispose()

    docs_url = "/docs" if app_settings.show_docs else None
    openapi_url = "/openapi.json" if app_settings.show_docs else None
    app = FastAPI(
        title="Pulseboard",
        description="Self-hosted HTTP uptime monitoring and incident history.",
        version=__version__,
        docs_url=docs_url,
        redoc_url=None,
        openapi_url=openapi_url,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        )
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
    app.include_router(router)
    return app


app = create_app()
