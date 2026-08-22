"""Local API routes."""

from apps.api.routes import actions, cases, events, media, replay, system, ws

ROUTERS = [
    system.router,
    events.router,
    cases.router,
    actions.router,
    replay.router,
    media.router,
    ws.router,
]

__all__ = ["ROUTERS"]
