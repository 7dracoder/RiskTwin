"""The rubric-critical behaviour: retrieval and new events change the decision.

Mirrors the state table in spec section 7.5 and the staged anomaly sequence in
section 4.2.
"""

from __future__ import annotations

from pathlib import Path

from httpx import AsyncClient

from tests.conftest import make_walkthrough_video, write_crew_clip
from tests.helpers import (
    CASE_ID,
    LOAD,
    WIND,
    activate_lift,
    baseline,
    case as read_case,
    settle,
    telemetry,
    worker,
)


async def test_no_rules_means_escalate(client: AsyncClient) -> None:
    """First decision: the lift plan is missing, so nothing can be authorised."""
    await telemetry(client, WIND, 24, "km/h", "site-weather-042")
    case = await read_case(client)
    assert case["decision"] == "ESCALATE"
    assert any("lift-plan" in reason or "limits" in reason for reason in case["reasons"])


async def test_retrieval_enables_conditional_approval(
    client: AsyncClient, documents: Path
) -> None:
    """Rule retrieved, gust below the limit, zone clear -> CONDITIONAL APPROVAL."""
    await baseline(client)

    imported = (await client.post(f"/api/cases/{CASE_ID}/documents/import")).json()
    assert imported["import"]["ruleBearingChunks"] >= 5
    await settle(client)

    case = await read_case(client)
    assert case["decision"] == "CONDITIONAL_APPROVAL"

    evidence = (await client.get(f"/api/cases/{CASE_ID}/evidence")).json()
    rules = [item for item in evidence if item["evidenceType"] == "policy_evidence"]
    assert any("42" in item["finding"] for item in rules), "the 42 km/h limit must be cited"
    assert any("85" in item["finding"] for item in rules), "the 85% limit must be cited"


async def test_worker_entering_exclusion_zone_holds_the_lift(
    client: AsyncClient, documents: Path
) -> None:
    """A worker inside an active exclusion zone is a stop-work event."""
    await baseline(client)
    await client.post(f"/api/cases/{CASE_ID}/documents/import")
    await activate_lift(client)
    assert (await read_case(client))["decision"] == "CONDITIONAL_APPROVAL"

    await worker(client, "worker-12", "C")

    case = await read_case(client)
    assert case["decision"] == "HOLD"
    assert any("worker-12" in reason for reason in case["reasons"])
    # The checklist must require zone C to be cleared. Once the lift plan's own
    # restart procedure has been retrieved, the approved document's wording is
    # what the operator reads, so match on intent rather than on our phrasing.
    assert any(
        "zone c" in step.lower() and "clear" in step.lower()
        for step in case["requiredBeforeApproval"]
    )

    alerts = (await client.get("/api/notifications", params={"workerAlias": "worker-12"})).json()
    assert alerts, "the worker in the zone must receive a targeted alert"
    assert alerts[0]["tier"] == "STOP_ACK_REQUIRED"
    assert alerts[0]["requiresAck"] is True


async def test_threshold_breach_is_deterministic_and_cited(
    client: AsyncClient, documents: Path
) -> None:
    """Wind above the retrieved limit produces exact arithmetic, not a model guess."""
    await baseline(client)
    await client.post(f"/api/cases/{CASE_ID}/documents/import")
    await activate_lift(client)

    await telemetry(client, WIND, 46, "km/h", "site-weather-042")

    case = await read_case(client)
    assert case["decision"] == "HOLD"

    evidence = (await client.get(f"/api/cases/{CASE_ID}/evidence")).json()
    breach = next(
        item
        for item in evidence
        if item["evidenceType"] == "telemetry_observation" and item["detail"].get("breached")
    )
    assert breach["detail"]["value"] == 46
    assert breach["detail"]["limit"] == 42
    assert breach["detail"]["deviation"] == 4
    assert breach["detail"]["citation"] == "lift-plan-042:p3"
    assert breach["severity"] == "critical"
    assert breach["modelGenerated"] is False


async def test_load_breach_is_a_second_independent_anomaly(
    client: AsyncClient, documents: Path
) -> None:
    await baseline(client)
    await telemetry(client, WIND, 29, "km/h", "site-weather-042")
    await client.post(f"/api/cases/{CASE_ID}/documents/import")
    await activate_lift(client)
    await telemetry(client, LOAD, 89, "%", "crane-gateway-042")

    case = await read_case(client)
    assert case["decision"] == "HOLD"
    assert any("Load utilisation" in reason and "89" in reason for reason in case["reasons"])


async def test_superseded_reading_stops_holding_the_case(
    client: AsyncClient, documents: Path
) -> None:
    """A later in-limit reading must clear an earlier breach; the engine uses
    current state, not the whole history."""
    await baseline(client)
    await client.post(f"/api/cases/{CASE_ID}/documents/import")
    await activate_lift(client)
    await telemetry(client, WIND, 46, "km/h", "site-weather-042")
    assert (await read_case(client))["decision"] == "HOLD"

    await telemetry(client, WIND, 30, "km/h", "site-weather-042")
    assert (await read_case(client))["decision"] == "CONDITIONAL_APPROVAL"


async def test_crew_claim_conflicting_with_vision_escalates(
    client: AsyncClient, documents: Path, workspace: Path
) -> None:
    """An unresolved conflict between a verbal all-clear and visual evidence is
    not a hold decision — it cannot be resolved from the evidence, so it escalates."""
    make_walkthrough_video(workspace / "data" / "raw" / "video" / "walkthrough.mp4")
    (workspace / "data" / "raw" / "video" / "walkthrough.mp4.meta.json").write_text(
        '{"regions": [{"zoneId": "C", "box": [0.55, 0.4, 1.0, 1.0]},'
        ' {"zoneId": "A", "box": [0.0, 0.3, 0.55, 1.0]}]}',
        encoding="utf-8",
    )
    write_crew_clip(
        workspace / "data" / "raw" / "audio" / "crew.wav",
        "Banksman to crane four, zone C is clear, you are good for the lift.",
    )

    await baseline(client)
    await client.post(f"/api/cases/{CASE_ID}/documents/import")
    await activate_lift(client)

    review = (await client.post(f"/api/cases/{CASE_ID}/review")).json()
    await settle(client)

    assert review["decision"] == "ESCALATE"
    case = await read_case(client)
    assert case["decision"] == "ESCALATE"
    assert any("conflicts" in reason for reason in case["reasons"])

    evidence = (await client.get(f"/api/cases/{CASE_ID}/evidence")).json()
    audio = next(item for item in evidence if item["evidenceType"] == "audio_observation")
    assert audio["detail"]["claimsZoneClear"] == "C"
    assert audio["detail"]["transcriptSource"] == "operator-provided"
    video = [item for item in evidence if item["evidenceType"] == "video_observation"]
    assert video, "the walkthrough must produce visual evidence"


async def test_missing_media_never_fabricates_a_finding(
    client: AsyncClient, documents: Path
) -> None:
    await baseline(client)
    await client.post(f"/api/cases/{CASE_ID}/documents/import")
    await client.post(f"/api/cases/{CASE_ID}/review")
    await settle(client)

    evidence = (await client.get(f"/api/cases/{CASE_ID}/evidence")).json()
    video = next(item for item in evidence if item["evidenceType"] == "video_observation")
    assert video["detail"]["available"] is False
    assert "No site walkthrough" in video["finding"]
    assert (await read_case(client))["decision"] == "ESCALATE"
