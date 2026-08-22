"""Local event ingest. Handlers write immutable events; the change feed decides."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from packages.contracts import TelemetryRequest, WorkerPositionRequest

router = APIRouter(prefix="/api/events", tags=["events"])


@router.post("/worker-position")
async def ingest_worker_position(payload: WorkerPositionRequest, request: Request) -> dict[str, Any]:
    """Zone presence from an opted-in worker device on the private LAN.

    Carries a role alias, never a personal identity, and is purpose-limited to
    active safety operations (spec section 4.3).
    """
    state = request.app.state.risktwin
    event, position = await state.orchestrator.ingest_worker_position(payload)
    return {
        "accepted": True,
        "eventId": event.id,
        "positionId": position.id,
        "caseId": position.caseId,
        "workerAlias": position.workerAlias,
        "zoneId": position.zoneId,
        "siteModelVersion": position.siteModelVersion,
        "note": "Evidence and any targeted alert follow on the change feed.",
    }


@router.post("/telemetry")
async def ingest_telemetry(payload: TelemetryRequest, request: Request) -> dict[str, Any]:
    state = request.app.state.risktwin
    event, reading = await state.orchestrator.ingest_telemetry(
        case_id=payload.caseId,
        kind=payload.kind,
        value=payload.value,
        unit=payload.unit,
        source=payload.source,
        source_id=payload.sourceId or payload.source,
        is_simulated=payload.isSimulated,
    )
    return {
        "accepted": True,
        "eventId": event.id,
        "telemetryId": reading.id,
        "caseId": reading.caseId,
        "kind": reading.kind,
        "value": reading.value,
        "isSimulated": reading.isSimulated,
    }
