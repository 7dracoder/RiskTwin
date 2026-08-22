"""The Orchestrator schedules only the specialists an event type needs.

Spec section 14: high-frequency telemetry must not wake the vision or speech
agents, and a heartbeat must not re-decide the case.
"""

from __future__ import annotations

from agents.orchestrator import RECORD_ONLY_EVENTS, plan_for
from httpx import AsyncClient

from tests.helpers import CASE_ID, WIND, baseline, settle, telemetry, worker


def test_plan_matches_event_type() -> None:
    assert plan_for("telemetry") == ["telemetry-proximity"]
    assert plan_for("worker_zone") == ["telemetry-proximity"]
    assert plan_for("vision_cue") == ["vision-risk"]
    assert plan_for("audio_cue") == ["crew-comms"]
    assert plan_for("source_freshness") == ["data-watcher"]
    assert plan_for("manual_review") == ["vision-risk", "crew-comms"]
    assert plan_for("gateway_heartbeat") == []
    assert "gateway_heartbeat" in RECORD_ONLY_EVENTS


async def _runs(client: AsyncClient) -> list[dict]:
    return (await client.get(f"/api/cases/{CASE_ID}/agents")).json()


async def test_telemetry_does_not_wake_vision_or_speech(client: AsyncClient) -> None:
    await telemetry(client, WIND, 24, "km/h", "site-weather-042")

    agents = {run["agent"] for run in await _runs(client)}
    assert "telemetry-proximity" in agents
    assert "safety-commander" in agents
    assert "vision-risk" not in agents
    assert "crew-comms" not in agents


async def test_worker_event_schedules_proximity_not_vision(client: AsyncClient) -> None:
    await worker(client, "worker-12", "A")

    agents = {run["agent"] for run in await _runs(client)}
    assert "telemetry-proximity" in agents
    assert "vision-risk" not in agents
    assert "crew-comms" not in agents


async def test_heartbeat_is_record_only(client: AsyncClient) -> None:
    """A gateway heartbeat refreshes freshness without re-running specialists."""
    await baseline(client)
    before_ids = {run["_id"] for run in await _runs(client)}

    event = await client.app_state.orchestrator._record_event(  # type: ignore[attr-defined]
        case_id=CASE_ID,
        event_type="gateway_heartbeat",
        source="recorded-replay",
        source_id="floor-gateway-f12",
        payload={"kind": "gateway_heartbeat", "value": "ok"},
        is_simulated=True,
    )
    assert event.id
    await settle(client)

    extra = [run for run in await _runs(client) if run["_id"] not in before_ids]
    assert extra == [], "a heartbeat must not schedule any agent"
