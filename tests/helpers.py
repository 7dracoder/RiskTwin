"""Shared drivers for the API-level tests.

Every helper posts through the HTTP surface and then waits for the change feed to
go quiet, so a test observes the same closed loop a judge would: an event is
written, the feed wakes the orchestrator, agents write evidence, the Commander
re-decides.
"""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

CASE_ID = "LIFT-042"
WIND = "wind_gust_kmh"
LOAD = "crane_load_pct"

# Sources declared with requiresContinuousFeed in config/sources.yaml. Silence
# from these is itself an adverse condition, so a test that wants a clean
# starting state has to make them report first.
CONTINUOUS_SOURCES = ("crane-gateway-042", "floor-gateway-f12", "site-weather-042")


def state(client: AsyncClient) -> Any:
    return client.app_state  # type: ignore[attr-defined]


async def settle(client: AsyncClient) -> None:
    assert await state(client).wait_idle(), "the change feed never went quiet"


async def case(client: AsyncClient) -> dict[str, Any]:
    return (await client.get(f"/api/cases/{CASE_ID}")).json()


async def evidence(client: AsyncClient) -> list[dict[str, Any]]:
    return (await client.get(f"/api/cases/{CASE_ID}/evidence")).json()


async def telemetry(
    client: AsyncClient, kind: str, value: float, unit: str, source_id: str
) -> None:
    response = await client.post(
        "/api/events/telemetry",
        json={
            "caseId": CASE_ID,
            "kind": kind,
            "value": value,
            "unit": unit,
            "source": "recorded-replay",
            "sourceId": source_id,
            "isSimulated": True,
        },
    )
    assert response.status_code == 200
    await settle(client)


async def worker(client: AsyncClient, alias: str, zone: str) -> None:
    response = await client.post(
        "/api/events/worker-position",
        json={"caseId": CASE_ID, "workerAlias": alias, "zoneId": zone, "floorId": "F12"},
    )
    assert response.status_code == 200
    await settle(client)


async def heartbeat(client: AsyncClient, source_id: str) -> None:
    await state(client).orchestrator._record_event(
        case_id=CASE_ID,
        event_type="gateway_heartbeat",
        source="recorded-replay",
        source_id=source_id,
        payload={"kind": "gateway_heartbeat", "value": "ok"},
        is_simulated=True,
    )
    await settle(client)


async def baseline(client: AsyncClient) -> None:
    """The trace's 00:00 baseline: every continuously monitored source reporting."""
    await heartbeat(client, "floor-gateway-f12")
    await telemetry(client, WIND, 22, "km/h", "site-weather-042")
    await telemetry(client, LOAD, 61, "%", "crane-gateway-042")


async def activate_lift(client: AsyncClient) -> None:
    """Drive the lift-active state the way the replay trace does."""
    event = await state(client).orchestrator._record_event(
        case_id=CASE_ID,
        event_type="site_state",
        source="recorded-replay",
        source_id="crane-gateway-042",
        payload={"kind": "lift_state", "value": "active"},
        is_simulated=True,
    )
    assert event.id
    await settle(client)


async def import_documents(client: AsyncClient) -> dict[str, Any]:
    report = (await client.post(f"/api/cases/{CASE_ID}/documents/import")).json()
    await settle(client)
    return report
