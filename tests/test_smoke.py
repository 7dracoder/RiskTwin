"""Boot smoke test: the app starts, the case exists and the stack is disclosed."""

from __future__ import annotations

from httpx import AsyncClient


async def test_app_boots_and_opens_the_case(client: AsyncClient) -> None:
    health = (await client.get("/api/health")).json()
    assert health["ok"] is True

    case = (await client.get("/api/cases/LIFT-042")).json()
    # Nothing has been retrieved yet, so the only valid answer is ESCALATE.
    assert case["decision"] == "ESCALATE"

    system = (await client.get("/api/system")).json()
    assert system["degradedMode"] is True
    assert {entry["name"] for entry in system["frameworks"]} == {
        "OpenShell",
        "OpenClaw",
        "NemoClaw",
        "MongoDB",
    }

    check = (await client.get("/api/system/inference-check")).json()
    assert check["allLocal"] is True


async def test_site_model_is_seeded(client: AsyncClient) -> None:
    model = (await client.get("/api/site-model")).json()
    assert model["siteModelId"] == "site-042"
    assert {zone["zoneId"] for zone in model["zones"]} == {"A", "B", "C", "D"}
    exclusion = next(zone for zone in model["zones"] if zone["zoneId"] == "C")
    assert exclusion["kind"] == "lift-exclusion"


async def test_sources_are_registered(client: AsyncClient) -> None:
    sources = (await client.get("/api/sources")).json()
    ids = {source["sourceId"] for source in sources}
    assert {"crane-gateway-042", "floor-gateway-f12", "worker-pwa", "site-weather-042"} <= ids
    assert all(source["status"] in {"fresh", "stale", "unavailable"} for source in sources)
