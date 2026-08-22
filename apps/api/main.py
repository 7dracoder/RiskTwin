"""RiskTwin local API.

Binds on the private LAN so the controller dashboard and the worker PWA can reach
it. Model endpoints and the database are never exposed here (spec section 8.4).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routes import ROUTERS
from apps.api.state import AppState
from packages.config import Settings, get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)-38s %(message)s",
)
logger = logging.getLogger("risktwin.api")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state = AppState(settings)
        app.state.risktwin = state
        case = await state.startup()
        logger.info(
            "case %s ready: decision=%s recovered=%s",
            case.caseId,
            case.decision.value,
            case.recoveredFromStore,
        )
        try:
            yield
        finally:
            await state.shutdown()

    app = FastAPI(
        title="RiskTwin",
        version="0.1.0",
        summary="Local multimodal safety sentinel for critical construction lifts",
        description=(
            "Decision support requiring a qualified human's approval. RiskTwin never "
            "commands equipment, never sends site data to an external service and never "
            "identifies individuals by face."
        ),
        lifespan=lifespan,
    )

    # The dashboard and worker page are served by Next.js on the same private LAN.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1|10\.[0-9.]+|192\.168\.[0-9.]+|172\.(1[6-9]|2[0-9]|3[01])\.[0-9.]+)(:\d+)?",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in ROUTERS:
        app.include_router(router)

    @app.get("/", tags=["system"])
    async def root() -> dict[str, str]:
        return {
            "service": "risktwin-api",
            "caseId": settings.case_id,
            "docs": "/docs",
            "dashboard": "served separately by apps/dashboard on port 3000",
        }

    return app


app = create_app()
