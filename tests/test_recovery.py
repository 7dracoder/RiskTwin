"""Restart recovery: the case lives in the store, not in the process.

Spec section 14: restarting the agent process restores LIFT-042 and its decision
from durable state. On the Mac this is the file journal; on the DGX it is MongoDB
Change Streams. The application code is the same.
"""

from __future__ import annotations

from pathlib import Path

from httpx import ASGITransport, AsyncClient

from apps.api.main import create_app
from packages.config import Settings
from tests.helpers import CASE_ID, activate_lift, baseline, case as read_case, worker


async def _client_for(app) -> AsyncClient:
    transport = ASGITransport(app=app)
    http = AsyncClient(transport=transport, base_url="http://risktwin.test")
    http.app_state = app.state.risktwin  # type: ignore[attr-defined]
    return http


async def test_restart_restores_hold_decision(
    settings: Settings, documents: Path
) -> None:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with await _client_for(app) as client:
            await baseline(client)
            await client.post(f"/api/cases/{CASE_ID}/documents/import")
            await activate_lift(client)
            await worker(client, "worker-12", "C")
            held = await read_case(client)
            assert held["decision"] == "HOLD"
            evidence_count = held["evidenceCount"]
            assert evidence_count > 0

    restarted = create_app(settings)
    async with restarted.router.lifespan_context(restarted):
        async with await _client_for(restarted) as client:
            recovered = await read_case(client)
            assert recovered["decision"] == "HOLD"
            assert recovered["recoveredFromStore"] is True
            assert recovered["evidenceCount"] == evidence_count
            assert any("worker-12" in reason for reason in recovered["reasons"])
