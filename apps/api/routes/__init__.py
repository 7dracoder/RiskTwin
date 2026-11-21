"""Local API routes."""

from apps.api.routes import (
    actions,
    cases,
    events,
    media,
    reconstruction,
    replay,
    sensors,
    system,
    ws,
)

ROUTERS = [
    system.router,
    events.router,
    cases.router,
    actions.router,
    replay.router,
    media.router,
    sensors.router,
    reconstruction.router,
    ws.router,
]

__all__ = ["ROUTERS"]
