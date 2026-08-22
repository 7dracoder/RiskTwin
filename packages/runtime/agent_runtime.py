"""Agent execution runtime.

Specialist agents are roles over one shared local model, run concurrently with a
small concurrency limit so a 30B text model is not asked to serve five parallel
generations (spec section 9.3). Every run is journaled to `agent_runs`, which is
what makes the restart-recovery story auditable.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from packages.contracts import AgentRun, AgentRunStatus, utcnow
from packages.storage.base import AGENT_RUNS, Store

logger = logging.getLogger(__name__)

# Two concurrent generations at most; agent cards then update as results arrive.
DEFAULT_CONCURRENCY = 2


class AgentRuntime:
    """In-process role runtime.

    Named `AgentRuntime` rather than `OpenClawRuntime` because on this host it is a
    local stand-in. When `RISKTWIN_AGENT_RUNTIME=openclaw` the runtime label changes
    and `describe()` reports the delegation target, so the dashboard never implies a
    framework that is not actually running.
    """

    def __init__(self, store: Store, *, label: str = "inprocess", concurrency: int = DEFAULT_CONCURRENCY) -> None:
        self._store = store
        self._label = label
        self._semaphore = asyncio.Semaphore(concurrency)
        self._concurrency = concurrency
        self._active: dict[str, str] = {}

    @property
    def label(self) -> str:
        return self._label

    @property
    def active(self) -> dict[str, str]:
        return dict(self._active)

    async def run(
        self,
        *,
        agent: str,
        case_id: str,
        task: Callable[[], Awaitable[list[str]]],
        input_event_id: str | None = None,
    ) -> AgentRun:
        """Execute one agent task, journaling start, completion and duration.

        `task` returns the evidence ids it wrote, which is what the case timeline
        and the Commander's citation list are built from.
        """
        record = AgentRun(
            caseId=case_id,
            agent=agent,
            inputEventId=input_event_id,
            status=AgentRunStatus.STARTED,
        )
        await self._store.insert_one(AGENT_RUNS, record.to_doc())
        started = time.perf_counter()
        self._active[record.id] = agent

        async with self._semaphore:
            try:
                evidence_ids = await task()
                record.status = AgentRunStatus.COMPLETED
                record.evidenceIds = evidence_ids or []
            except Exception as exc:  # noqa: BLE001 - one agent failing must not stop the loop
                logger.exception("agent %s failed for case %s", agent, case_id)
                record.status = AgentRunStatus.FAILED
                record.detail = f"{type(exc).__name__}: {exc}"
            finally:
                self._active.pop(record.id, None)

        record.completedAt = utcnow()
        record.durationMs = int((time.perf_counter() - started) * 1000)
        await self._store.update_one(
            AGENT_RUNS,
            {"_id": record.id},
            {
                "status": record.status.value,
                "evidenceIds": record.evidenceIds,
                "detail": record.detail,
                "completedAt": record.completedAt.isoformat().replace("+00:00", "Z"),
                "durationMs": record.durationMs,
            },
        )
        return record

    async def run_all(self, tasks: list[dict[str, Any]]) -> list[AgentRun]:
        """Run several specialists concurrently under the shared concurrency limit."""
        return list(
            await asyncio.gather(
                *(
                    self.run(
                        agent=item["agent"],
                        case_id=item["caseId"],
                        task=item["task"],
                        input_event_id=item.get("inputEventId"),
                    )
                    for item in tasks
                )
            )
        )

    def describe(self) -> dict[str, Any]:
        return {
            "label": self._label,
            "concurrencyLimit": self._concurrency,
            "activeRuns": self.active,
        }
