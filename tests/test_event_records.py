"""Spec section 14: every input writes a clearly labelled record into the store.

One check per modality — video, audio, document, telemetry, worker — asserting the
record is present, attributed to its source, and labelled simulated or live. A
finding that cannot be traced to a stored record is not evidence.
"""

from __future__ import annotations

from pathlib import Path

from httpx import AsyncClient

from tests.conftest import make_walkthrough_video, write_crew_clip
from tests.helpers import CASE_ID, WIND, evidence as read_evidence, settle, telemetry, worker


async def _timeline(client: AsyncClient) -> list[dict]:
    return (await client.get(f"/api/cases/{CASE_ID}/timeline")).json()


async def test_telemetry_event_is_recorded_with_provenance(client: AsyncClient) -> None:
    await telemetry(client, WIND, 31, "km/h", "site-weather-042")

    event = next(item for item in await _timeline(client) if item["type"] == "telemetry")
    assert event["sourceId"] == "site-weather-042"
    assert event["isSimulated"] is True
    assert event["payload"]["kind"] == WIND
    assert event["payload"]["value"] == 31

    reading = next(
        item
        for item in await read_evidence(client)
        if item["evidenceType"] == "telemetry_observation"
    )
    assert reading["sourceRefs"], "a telemetry finding must cite its reading"
    assert reading["modelGenerated"] is False


async def test_worker_event_is_recorded_under_an_alias(client: AsyncClient) -> None:
    await worker(client, "worker-12", "A")

    event = next(item for item in await _timeline(client) if item["type"] == "worker_zone")
    assert event["sourceId"] == "worker-pwa"
    # A live device reported this, so it must not be labelled simulated.
    assert event["isSimulated"] is False
    assert event["payload"]["workerAlias"] == "worker-12"
    assert "name" not in event["payload"] and "deviceId" not in event["payload"]

    positions = (await client.get("/api/workers")).json()
    assert [item["workerAlias"] for item in positions] == ["worker-12"]
    assert positions[0]["siteModelVersion"] == 1


async def test_document_import_records_chunks_and_citations(
    client: AsyncClient, documents: Path
) -> None:
    report = (await client.post(f"/api/cases/{CASE_ID}/documents/import")).json()
    await settle(client)

    assert report["import"]["documents"] == 2
    files = {item["documentId"]: item for item in report["import"]["files"]}
    assert files["lift-plan-042"]["checksum"], "an imported document must record a checksum"
    assert files["lift-plan-042"]["license"], "an imported document must record its licence"
    assert "max_wind_gust_kmh" in files["lift-plan-042"]["ruleKeys"]

    policy = [
        item for item in await read_evidence(client) if item["evidenceType"] == "policy_evidence"
    ]
    assert policy, "retrieval must write citable policy evidence"
    assert all(item["sourceRefs"] for item in policy)


async def test_video_evidence_is_recorded_from_sampled_frames(
    client: AsyncClient, workspace: Path
) -> None:
    make_walkthrough_video(workspace / "data" / "raw" / "video" / "walkthrough.mp4")
    (workspace / "data" / "raw" / "video" / "walkthrough.mp4.meta.json").write_text(
        '{"regions": [{"zoneId": "C", "box": [0.55, 0.4, 1.0, 1.0]}]}', encoding="utf-8"
    )

    await client.post(f"/api/cases/{CASE_ID}/review")
    await settle(client)

    video = next(
        item for item in await read_evidence(client) if item["evidenceType"] == "video_observation"
    )
    assert video["detail"]["available"] is True
    assert video["sourceRefs"], "a visual finding must cite the frames it came from"
    # No VLM is served in the test profile, so the finding must say so rather than
    # imply a model watched the clip.
    assert video["modelGenerated"] is False

    frames = (await client.get("/api/media/frames")).json()
    assert frames, "the frames the agent analysed must be retrievable"

    manifests = (await client.get(f"/api/cases/{CASE_ID}/redaction")).json()
    assert manifests, "processing a clip must produce a redaction manifest"
    assert manifests[0]["redactionMethod"]


async def test_audio_evidence_records_its_transcript_source(
    client: AsyncClient, workspace: Path
) -> None:
    write_crew_clip(
        workspace / "data" / "raw" / "audio" / "crew.wav",
        "Banksman to crane four, zone C is clear, you are good for the lift.",
    )

    await client.post(f"/api/cases/{CASE_ID}/review")
    await settle(client)

    audio = next(
        item for item in await read_evidence(client) if item["evidenceType"] == "audio_observation"
    )
    assert audio["detail"]["transcriptSource"] == "operator-provided"
    assert audio["detail"]["claimsZoneClear"] == "C"
    assert audio["modelGenerated"] is False
