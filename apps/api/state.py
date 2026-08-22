"""Application state: the store, the agents, the replay engine and the change feed.

The change feed is what drives the agent loop. The HTTP handlers only write
immutable events; the loop wakes on the feed and the dashboard learns the outcome
over the WebSocket. That is deliberate — it is the behaviour spec section 6.2
asks judges to see.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from agents import data_watcher
from agents.base import AgentContext
from agents.orchestrator import Orchestrator
from apps.api.bus import EventBus
from packages.config import Settings, get_settings
from packages.contracts import Case
from packages.inference import build_inference_suite
from packages.replay import ReplayEngine
from packages.runtime import AgentRuntime, PolicyEngine, framework_status
from packages.storage import build_store
from packages.storage.base import CASES, ChangeEvent

logger = logging.getLogger(__name__)

FRESHNESS_TICK_SECONDS = 5.0


class AppState:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.store = build_store(self.settings)
        self.models = build_inference_suite(self.settings)
        self.policy = PolicyEngine.from_settings(self.settings)
        self.runtime = AgentRuntime(self.store, label=self.settings.agent_runtime)
        self.context = AgentContext(
            store=self.store,
            settings=self.settings,
            models=self.models,
            runtime=self.runtime,
            policy=self.policy,
        )
        self.orchestrator = Orchestrator(self.context)
        self.replay = ReplayEngine(self.store, handler=self.orchestrator.ingest_replay_event)
        self.bus = EventBus()
        self.localOnlyCheck: dict[str, str] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self._inflight = 0
        self._last_change_at = 0.0

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #

    async def startup(self) -> Case:
        self.localOnlyCheck = self.settings.enforce_local_only()
        await self.store.connect()
        self.orchestrator.add_listener(self._broadcast_change)
        case = await self.orchestrator.bootstrap(self.settings.case_id)

        recording_path = self.settings.path(self.settings.recording_path)
        if recording_path.exists():
            recording = await self.replay.import_recording(recording_path)
            await self.replay.ensure_state(
                case.caseId, recording.recordingId, self.settings.replay_speed
            )
        else:
            logger.warning("no telemetry recording at %s; replay disabled", recording_path)

        self._tasks.append(asyncio.create_task(self._consume_changes()))
        self._tasks.append(asyncio.create_task(self._freshness_loop()))
        logger.info(
            "RiskTwin API ready: storage=%s policy=%s models=%s",
            self.store.backend,
            f"{self.policy.policy_id}/{self.policy.backend}",
            {key: value["backend"] for key, value in self.models.model_refs().items()},
        )
        return case

    async def shutdown(self) -> None:
        await self.replay.stop()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks.clear()
        await self.models.close()
        await self.store.close()

    # ------------------------------------------------------------------ #
    # change feed
    # ------------------------------------------------------------------ #

    async def _consume_changes(self) -> None:
        while True:
            try:
                async for change in self.store.watch():
                    self._inflight += 1
                    self._last_change_at = time.monotonic()
                    try:
                        await self.orchestrator.on_change(change)
                    except Exception:  # noqa: BLE001 - keep the feed alive
                        logger.exception("change handling failed for %s", change.collection)
                    finally:
                        self._inflight -= 1
                        self._last_change_at = time.monotonic()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("change feed dropped; retrying in 2s")
                await asyncio.sleep(2)

    async def _broadcast_change(self, change: ChangeEvent) -> None:
        await self.bus.broadcast(
            {
                "kind": "change",
                "collection": change.collection,
                "operation": change.operation,
                "document": change.document,
            }
        )
        if change.collection == CASES:
            await self.bus.broadcast({"kind": "case", "document": change.document})

    async def _freshness_loop(self) -> None:
        """Continuously verify source freshness and acknowledgement deadlines."""
        case_id = self.settings.case_id
        while True:
            try:
                await asyncio.sleep(FRESHNESS_TICK_SECONDS)
                written = await data_watcher.evaluate_freshness(self.context, case_id)
                escalated = await self.orchestrator.escalate_unacknowledged(case_id)
                if written or escalated:
                    await self.orchestrator.redecide(case_id)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("freshness loop iteration failed")

    async def wait_idle(self, *, quiet_seconds: float = 0.15, timeout: float = 15.0) -> bool:
        """Block until the change feed has been quiet, used by tests and scripts."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            marker = self._last_change_at
            await asyncio.sleep(quiet_seconds)
            if self._inflight == 0 and marker == self._last_change_at:
                return True
        return False

    # ------------------------------------------------------------------ #
    # introspection
    # ------------------------------------------------------------------ #

    async def system_snapshot(self) -> dict[str, Any]:
        return {
            "caseId": self.settings.case_id,
            "hostProfile": self.settings.host_profile,
            "banner": "RECORDED / SIMULATED SITE TELEMETRY — REPLAY MODE",
            "degradedMode": self.models.degraded,
            "models": self.models.model_refs(),
            "localOnlyEndpoints": self.localOnlyCheck,
            "allowRemoteInference": self.settings.allow_remote_inference,
            "dataWatcherLiveFetch": self.settings.data_watcher_live_fetch,
            "storage": await self.store.health(),
            "policy": self.policy.describe(),
            "frameworks": framework_status(self.settings),
            "runtime": self.runtime.describe(),
            "replay": self.replay.describe(),
            "websocketClients": self.bus.client_count,
        }
