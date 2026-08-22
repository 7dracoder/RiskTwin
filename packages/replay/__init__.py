"""Local replay engine for the recorded site telemetry trace.

The trace is imported once into `telemetry_recordings` as an immutable record and
then replayed as events arriving "now" (spec section 4.2). Playback position lives
in `replay_state`, so restarting the process resumes the same case at the same
position instead of replaying from the beginning and losing the evidence trail.

Nothing here pretends to be a live sensor. Every emitted event carries
`source: "recorded-replay"` and `isSimulated: true`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from packages.contracts import (
    ReplayState,
    TelemetryRecording,
    TelemetryRecordingEvent,
    utcnow,
)
from packages.storage.base import REPLAY_STATE, TELEMETRY_RECORDINGS, Store

logger = logging.getLogger(__name__)

EventHandler = Callable[[TelemetryRecordingEvent, TelemetryRecording], Awaitable[None]]


def load_recording_file(path: Path) -> TelemetryRecording:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.setdefault("_id", payload["recordingId"])
    events = payload.get("events") or []
    payload["checksum"] = hashlib.sha256(
        json.dumps(events, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    payload["events"] = sorted(events, key=lambda item: item["offsetSeconds"])
    return TelemetryRecording.model_validate(payload)


class ReplayEngine:
    def __init__(self, store: Store, *, handler: EventHandler) -> None:
        self._store = store
        self._handler = handler
        self._task: asyncio.Task[None] | None = None
        self._recording: TelemetryRecording | None = None
        self._pause = asyncio.Event()
        self._pause.set()

    # ------------------------------------------------------------------ #
    # import
    # ------------------------------------------------------------------ #

    async def import_recording(self, path: Path) -> TelemetryRecording:
        recording = load_recording_file(path)
        await self._store.upsert(
            TELEMETRY_RECORDINGS, {"_id": recording.id}, recording.to_doc()
        )
        self._recording = recording
        return recording

    async def recording(self, recording_id: str) -> TelemetryRecording | None:
        if self._recording is not None and self._recording.recordingId == recording_id:
            return self._recording
        doc = await self._store.find_one(TELEMETRY_RECORDINGS, {"recordingId": recording_id})
        if doc is None:
            return None
        self._recording = TelemetryRecording.model_validate(doc)
        return self._recording

    # ------------------------------------------------------------------ #
    # state
    # ------------------------------------------------------------------ #

    async def state(self, case_id: str) -> ReplayState | None:
        doc = await self._store.find_one(REPLAY_STATE, {"caseId": case_id})
        return ReplayState.model_validate(doc) if doc else None

    async def _write_state(self, state: ReplayState) -> ReplayState:
        state.updatedAt = utcnow()
        await self._store.upsert(REPLAY_STATE, {"_id": state.id}, state.to_doc())
        return state

    async def ensure_state(
        self, case_id: str, recording_id: str, speed: float
    ) -> ReplayState:
        existing = await self.state(case_id)
        if existing is not None:
            existing.speed = speed
            return await self._write_state(existing)
        return await self._write_state(
            ReplayState(
                _id=f"{case_id}:{recording_id}",
                caseId=case_id,
                recordingId=recording_id,
                cursor=0,
                positionSeconds=0.0,
                speed=speed,
                status="IDLE",
            )
        )

    # ------------------------------------------------------------------ #
    # playback
    # ------------------------------------------------------------------ #

    async def start(self, case_id: str, recording_id: str, speed: float = 1.0) -> ReplayState:
        """Start or resume playback. Resuming keeps the durable cursor."""
        recording = await self.recording(recording_id)
        if recording is None:
            raise ValueError(f"recording {recording_id!r} has not been imported")

        state = await self.ensure_state(case_id, recording_id, speed)
        if state.status == "COMPLETED":
            return state
        state.status = "RUNNING"
        state.startedAt = state.startedAt or utcnow()
        state = await self._write_state(state)

        self._pause.set()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(case_id, recording))
        return state

    async def pause(self, case_id: str) -> ReplayState | None:
        state = await self.state(case_id)
        if state is None:
            return None
        self._pause.clear()
        state.status = "PAUSED"
        return await self._write_state(state)

    async def resume(self, case_id: str) -> ReplayState | None:
        state = await self.state(case_id)
        if state is None:
            return None
        return await self.start(state.caseId, state.recordingId, state.speed)

    async def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._task = None

    async def reset(self, case_id: str) -> ReplayState | None:
        await self.stop()
        state = await self.state(case_id)
        if state is None:
            return None
        state.cursor = 0
        state.positionSeconds = 0.0
        state.status = "IDLE"
        state.startedAt = None
        return await self._write_state(state)

    async def _run(self, case_id: str, recording: TelemetryRecording) -> None:
        """Emit each remaining event at its recorded offset, scaled by speed."""
        try:
            while True:
                await self._pause.wait()
                state = await self.state(case_id)
                if state is None or state.status not in {"RUNNING"}:
                    return
                if state.cursor >= len(recording.events):
                    state.status = "COMPLETED"
                    await self._write_state(state)
                    logger.info("replay of %s completed for %s", recording.recordingId, case_id)
                    return

                event = recording.events[state.cursor]
                speed = max(0.1, state.speed)
                delay = max(0.0, (event.offsetSeconds - state.positionSeconds) / speed)
                if delay:
                    await asyncio.sleep(delay)

                await self._pause.wait()
                refreshed = await self.state(case_id)
                if refreshed is None or refreshed.status != "RUNNING":
                    return

                started = time.perf_counter()
                try:
                    await self._handler(event, recording)
                except Exception:  # noqa: BLE001 - a bad event must not kill playback
                    logger.exception("replay handler failed for %s", event.label)

                refreshed.cursor += 1
                refreshed.positionSeconds = event.offsetSeconds
                await self._write_state(refreshed)
                elapsed = time.perf_counter() - started
                if elapsed > 2.0:
                    logger.warning("replay handler took %.1fs for %s", elapsed, event.label)
        except asyncio.CancelledError:
            raise

    def describe(self) -> dict[str, Any]:
        return {
            "running": self._task is not None and not self._task.done(),
            "recordingId": self._recording.recordingId if self._recording else None,
            "banner": "RECORDED / SIMULATED SITE TELEMETRY — REPLAY MODE",
        }


__all__ = ["EventHandler", "ReplayEngine", "load_recording_file"]
