"""Replay control for the recorded site telemetry trace."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api/replay", tags=["replay"])


async def _snapshot(state: Any, case_id: str) -> dict[str, Any]:
    replay_state = await state.replay.state(case_id)
    recording = (
        await state.replay.recording(replay_state.recordingId) if replay_state else None
    )
    return {
        "banner": "RECORDED / SIMULATED SITE TELEMETRY — REPLAY MODE",
        "state": replay_state.to_doc() if replay_state else None,
        "recording": {
            "recordingId": recording.recordingId,
            "provenance": recording.provenance,
            "license": recording.license,
            "isSimulated": recording.isSimulated,
            "checksum": recording.checksum,
            "durationSeconds": recording.durationSeconds,
            "eventCount": len(recording.events),
            "upcoming": [
                {
                    "offsetSeconds": event.offsetSeconds,
                    "label": event.label,
                    "eventType": event.eventType,
                    "sourceId": event.sourceId,
                }
                for event in recording.events[(replay_state.cursor if replay_state else 0) :][:6]
            ],
        }
        if recording
        else None,
    }


@router.get("")
async def replay_status(request: Request) -> dict[str, Any]:
    state = request.app.state.risktwin
    return await _snapshot(state, state.settings.case_id)


@router.post("/start")
async def start(
    request: Request, speed: float | None = Query(default=None, ge=0.1, le=10.0)
) -> dict[str, Any]:
    """Start or resume playback from the durable cursor."""
    state = request.app.state.risktwin
    case_id = state.settings.case_id
    replay_state = await state.replay.state(case_id)
    if replay_state is None:
        raise HTTPException(status_code=409, detail="no recording has been imported")
    await state.replay.start(
        case_id, replay_state.recordingId, speed or replay_state.speed or state.settings.replay_speed
    )
    return await _snapshot(state, case_id)


@router.post("/pause")
async def pause(request: Request) -> dict[str, Any]:
    state = request.app.state.risktwin
    await state.replay.pause(state.settings.case_id)
    return await _snapshot(state, state.settings.case_id)


@router.post("/reset")
async def reset(request: Request) -> dict[str, Any]:
    """Rewind playback. Evidence already gathered is preserved; use the reset
    script if you want a clean case."""
    state = request.app.state.risktwin
    await state.replay.reset(state.settings.case_id)
    return await _snapshot(state, state.settings.case_id)
