"""Case Orchestrator — event intake, agent scheduling and the closed loop.

An input arrives as an immutable event, the change feed wakes this component, it
schedules only the specialists that event type needs, each specialist writes
structured evidence, the rules are retrieved, and the Commander decides from
stored evidence alone. A later event repeats the loop and can change the decision
(spec section 6.2).

The loop is resource-aware: high-frequency events take the deterministic path
only, and the Commander runs when the risk state can actually change.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from agents import crew_comms, data_watcher, policy_gate, rules_retrieval, safety_commander
from agents import telemetry_proximity as telemetry_agent
from agents import vision_risk
from agents.base import AgentContext
from packages.contracts import (
    AlertTier,
    Case,
    CommanderVerdict,
    Decision,
    SiteEvent,
    SiteModel,
    TelemetryReading,
    TelemetryRecording,
    TelemetryRecordingEvent,
    WorkerPosition,
    WorkerPositionRequest,
    WorkerZoneRelation,
    utcnow,
)
from packages.risk_engine import RuleSet
from packages.site_model import get_active_site_model, seed_site_model
from packages.storage.base import (
    CASES,
    DOCUMENTS,
    EVIDENCE,
    SITE_EVENTS,
    TELEMETRY,
    WORKER_POSITIONS,
    ChangeEvent,
)

logger = logging.getLogger(__name__)

AGENT_NAME = "case-orchestrator"

# Which specialists an event type actually needs. Everything else is noise.
EVENT_PLAN: dict[str, list[str]] = {
    "telemetry": ["telemetry-proximity"],
    "site_state": ["telemetry-proximity"],
    "worker_zone": ["telemetry-proximity"],
    "vision_cue": ["vision-risk"],
    "audio_cue": ["crew-comms"],
    "source_freshness": ["data-watcher"],
    "gateway_heartbeat": [],
    "manual_review": ["vision-risk", "crew-comms"],
    "documents_indexed": [],
}

# Event types that cannot change the risk state, so the Commander stays asleep.
RECORD_ONLY_EVENTS = {"gateway_heartbeat"}


def plan_for(event_type: str) -> list[str]:
    """Specialists scheduled for an event type, always followed by rules + commander."""
    return list(EVENT_PLAN.get(event_type, []))


class Orchestrator:
    def __init__(self, context: AgentContext) -> None:
        self._context = context
        self._locks: dict[str, asyncio.Lock] = {}
        self._site_model: SiteModel | None = None
        self._rules: RuleSet | None = None
        self._document_count = -1
        self._listeners: list[Any] = []

    @property
    def context(self) -> AgentContext:
        return self._context

    def add_listener(self, callback: Any) -> None:
        """Register a coroutine callback invoked with every change event, for the UI feed."""
        self._listeners.append(callback)

    def _lock(self, case_id: str) -> asyncio.Lock:
        return self._locks.setdefault(case_id, asyncio.Lock())

    # ------------------------------------------------------------------ #
    # bootstrap and recovery
    # ------------------------------------------------------------------ #

    async def bootstrap(self, case_id: str) -> Case:
        """Prepare the case, recovering prior state from the store when it exists."""
        settings = self._context.settings
        await self._context.store.ensure_indexes()
        self._site_model = await seed_site_model(
            self._context.store, settings.path(settings.site_model_path)
        )
        await data_watcher.register_sources(self._context)

        existing = await self._context.store.find_one(CASES, {"caseId": case_id})
        if existing is not None:
            evidence_count = await self._context.store.count(EVIDENCE, {"caseId": case_id})
            await self._context.store.update_one(
                CASES,
                {"caseId": case_id},
                {
                    "recoveredFromStore": evidence_count > 0,
                    "siteModelId": self._site_model.siteModelId,
                    "siteModelVersion": self._site_model.version,
                },
            )
            recovered = await self._context.store.find_one(CASES, {"caseId": case_id})
            case = Case.model_validate(recovered)
            if case.recoveredFromStore:
                logger.info(
                    "recovered case %s from %s — decision remains %s (%d evidence items)",
                    case_id,
                    self._context.store.backend,
                    case.decision.value,
                    evidence_count,
                )
            return case

        case = Case(
            _id=case_id,
            caseId=case_id,
            title=f"Critical lift {case_id}",
            decision=Decision.ESCALATE,
            reasons=["Case opened; no evidence or applicable rule has been retrieved yet."],
            siteModelId=self._site_model.siteModelId,
            siteModelVersion=self._site_model.version,
        )
        await self._context.store.insert_one(CASES, case.to_doc())
        return case

    async def site_model(self) -> SiteModel | None:
        if self._site_model is None:
            self._site_model = await get_active_site_model(self._context.store)
        return self._site_model

    async def refresh_site_model(self) -> SiteModel | None:
        self._site_model = await get_active_site_model(self._context.store)
        return self._site_model

    async def case(self, case_id: str) -> Case | None:
        doc = await self._context.store.find_one(CASES, {"caseId": case_id})
        return Case.model_validate(doc) if doc else None

    # ------------------------------------------------------------------ #
    # intake
    # ------------------------------------------------------------------ #

    async def _record_event(
        self,
        *,
        case_id: str,
        event_type: str,
        source: str,
        source_id: str | None,
        payload: dict[str, Any],
        is_simulated: bool,
    ) -> SiteEvent:
        event = SiteEvent(
            caseId=case_id,
            type=event_type,
            source=source,
            sourceId=source_id,
            isSimulated=is_simulated,
            payload=payload,
        )
        await self._context.store.insert_one(SITE_EVENTS, event.to_doc())
        if source_id:
            await data_watcher.record_source_activity(self._context, source_id)
        return event

    async def ingest_telemetry(
        self,
        *,
        case_id: str,
        kind: str,
        value: Any,
        unit: str | None,
        source: str,
        source_id: str | None,
        is_simulated: bool = True,
    ) -> tuple[SiteEvent, TelemetryReading]:
        reading = TelemetryReading(
            caseId=case_id,
            kind=kind,
            value=value,
            unit=unit,
            source=source,
            sourceId=source_id,
            isSimulated=is_simulated,
        )
        await self._context.store.insert_one(TELEMETRY, reading.to_doc())
        event = await self._record_event(
            case_id=case_id,
            event_type="telemetry",
            source=source,
            source_id=source_id,
            payload={"kind": kind, "value": value, "unit": unit, "telemetryId": reading.id},
            is_simulated=is_simulated,
        )
        return event, reading

    async def ingest_worker_position(
        self, request: WorkerPositionRequest, *, source: str = "worker-pwa"
    ) -> tuple[SiteEvent, WorkerPosition]:
        position = WorkerPosition(
            caseId=request.caseId,
            workerAlias=request.workerAlias,
            zoneId=request.zoneId,
            floorId=request.floorId,
            x=request.x,
            y=request.y,
            z=request.z,
            timestamp=request.timestamp or utcnow(),
        )
        model = await self.site_model()
        if model is not None:
            position.siteModelVersion = model.version
        await self._context.store.insert_one(WORKER_POSITIONS, position.to_doc())
        event = await self._record_event(
            case_id=request.caseId,
            event_type="worker_zone",
            source=source,
            source_id="worker-pwa",
            payload={
                "workerAlias": position.workerAlias,
                "zoneId": position.zoneId,
                "floorId": position.floorId,
                "x": position.x,
                "y": position.y,
                "positionId": position.id,
            },
            is_simulated=False,
        )
        return event, position

    async def ingest_replay_event(
        self, event: TelemetryRecordingEvent, recording: TelemetryRecording
    ) -> None:
        """Handler the replay engine calls for each recorded event."""
        case_id = recording.caseId
        if event.eventType == "telemetry":
            await self.ingest_telemetry(
                case_id=case_id,
                kind=event.kind,
                value=event.value,
                unit=event.unit,
                source="recorded-replay",
                source_id=event.sourceId,
                is_simulated=True,
            )
        elif event.eventType == "worker_zone":
            payload = event.payload or {}
            await self.ingest_worker_position(
                WorkerPositionRequest(
                    caseId=case_id,
                    workerAlias=payload.get("workerAlias", "worker-unknown"),
                    zoneId=payload.get("zoneId"),
                    floorId=payload.get("floorId"),
                ),
                source="recorded-replay",
            )
        else:
            await self._record_event(
                case_id=case_id,
                event_type=event.eventType,
                source="recorded-replay",
                source_id=event.sourceId,
                payload={
                    "kind": event.kind,
                    "value": event.value,
                    "label": event.label,
                    **(event.payload or {}),
                },
                is_simulated=True,
            )

    # ------------------------------------------------------------------ #
    # the loop
    # ------------------------------------------------------------------ #

    async def on_change(self, change: ChangeEvent) -> None:
        for listener in self._listeners:
            try:
                await listener(change)
            except Exception:  # noqa: BLE001 - a UI listener must not break the loop
                logger.exception("change listener failed")

        if change.collection != SITE_EVENTS or change.operation not in {"insert", "update"}:
            return
        document = change.document or {}
        event_type = document.get("type")
        if event_type in {"decision", None} or event_type == "action":
            return
        await self.handle_event(SiteEvent.model_validate(document))

    async def handle_event(self, event: SiteEvent) -> CommanderVerdict | None:
        """Schedule the specialists this event needs, then re-decide the case."""
        async with self._lock(event.caseId):
            if event.type == "site_state" and event.payload.get("kind") == "lift_state":
                await self._context.store.update_one(
                    CASES,
                    {"caseId": event.caseId},
                    {"liftActive": event.payload.get("value") == "active"},
                )

            case = await self.case(event.caseId)
            lift_active = bool(case.liftActive) if case else False
            scheduled = plan_for(event.type)
            tasks: list[dict[str, Any]] = []

            for agent_name in scheduled:
                task = self._build_task(
                    agent_name, event=event, lift_active=lift_active
                )
                if task is not None:
                    tasks.append(
                        {
                            "agent": agent_name,
                            "caseId": event.caseId,
                            "task": task,
                            "inputEventId": event.id,
                        }
                    )
            if tasks:
                await self._context.runtime.run_all(tasks)

            if event.type in RECORD_ONLY_EVENTS:
                return None

            rules = await self._ensure_rules(event.caseId, input_event_id=event.id)
            verdict = await self._decide(event.caseId, rules=rules, input_event_id=event.id)
            await self._dispatch_alerts(event.caseId, verdict=verdict, lift_active=lift_active)
            return verdict

    def _build_task(self, agent_name: str, *, event: SiteEvent, lift_active: bool):
        context = self._context
        case_id = event.caseId

        if agent_name == "telemetry-proximity":
            return self._telemetry_task(event, lift_active)
        if agent_name == "vision-risk":

            async def vision_task() -> list[str]:
                return await vision_risk.run(
                    context,
                    case_id=case_id,
                    site_model=await self.site_model(),
                    cue=event.payload,
                )

            return vision_task
        if agent_name == "crew-comms":

            async def audio_task() -> list[str]:
                return await crew_comms.run(context, case_id=case_id, cue=event.payload)

            return audio_task
        if agent_name == "data-watcher":

            async def freshness_task() -> list[str]:
                source_id = event.sourceId or event.payload.get("sourceId")
                if event.type == "source_freshness" and source_id:
                    return await data_watcher.force_stale(
                        context, case_id, source_id, event.payload
                    )
                return await data_watcher.evaluate_freshness(context, case_id)

            return freshness_task
        return None

    def _telemetry_task(self, event: SiteEvent, lift_active: bool):
        context = self._context
        case_id = event.caseId
        payload = event.payload

        if event.type == "telemetry":

            async def reading_task() -> list[str]:
                docs = await context.store.find(
                    TELEMETRY, {"_id": payload.get("telemetryId")}, limit=1
                )
                if not docs:
                    return []
                rules = await self._current_rules()
                return await telemetry_agent.evaluate_reading(
                    context, reading=TelemetryReading.model_validate(docs[0]), rules=rules
                )

            return reading_task

        if event.type == "worker_zone":

            async def position_task() -> list[str]:
                docs = await context.store.find(
                    WORKER_POSITIONS, {"_id": payload.get("positionId")}, limit=1
                )
                if not docs:
                    return []
                written, _ = await telemetry_agent.evaluate_position(
                    context,
                    position=WorkerPosition.model_validate(docs[0]),
                    site_model=await self.site_model(),
                    lift_active=lift_active,
                )
                return written

            return position_task

        async def state_task() -> list[str]:
            return await telemetry_agent.evaluate_site_state(
                context,
                case_id=case_id,
                kind=payload.get("kind", event.type),
                value=payload.get("value"),
                source_id=event.sourceId,
            )

        return state_task

    def invalidate_rules(self) -> None:
        """Drop the cached ruleset so the next decision re-runs retrieval."""
        self._rules = None
        self._document_count = -1

    async def _current_rules(self) -> RuleSet:
        if self._rules is None:
            self._rules = await rules_retrieval.load_ruleset(self._context)
        return self._rules

    async def _ensure_rules(self, case_id: str, *, input_event_id: str | None = None) -> RuleSet:
        """Retrieve rules when the corpus changes, so retrieval visibly alters behaviour."""
        count = await self._context.store.count(DOCUMENTS)
        if count == self._document_count and self._rules is not None:
            return self._rules

        holder: dict[str, RuleSet] = {}

        async def task() -> list[str]:
            written, rules = await rules_retrieval.run(self._context, case_id=case_id)
            holder["rules"] = rules
            return written

        await self._context.runtime.run(
            agent="rules-retrieval", case_id=case_id, task=task, input_event_id=input_event_id
        )
        self._rules = holder.get("rules") or await rules_retrieval.load_ruleset(self._context)
        self._document_count = count
        return self._rules

    async def _decide(
        self, case_id: str, *, rules: RuleSet, input_event_id: str | None = None
    ) -> CommanderVerdict:
        case = await self.case(case_id)
        lift_active = bool(case.liftActive) if case else False
        holder: dict[str, CommanderVerdict] = {}

        async def task() -> list[str]:
            verdict = await safety_commander.run(
                self._context, case_id=case_id, rules=rules, lift_active=lift_active
            )
            holder["verdict"] = verdict
            return verdict.evidenceIds

        await self._context.runtime.run(
            agent="safety-commander", case_id=case_id, task=task, input_event_id=input_event_id
        )
        return holder["verdict"]

    async def redecide(self, case_id: str) -> CommanderVerdict:
        """Force a fresh decision, used after a document import or a manual review."""
        async with self._lock(case_id):
            self._document_count = -1
            rules = await self._ensure_rules(case_id)
            verdict = await self._decide(case_id, rules=rules)
            case = await self.case(case_id)
            await self._dispatch_alerts(
                case_id, verdict=verdict, lift_active=bool(case.liftActive) if case else False
            )
            return verdict

    async def run_manual_review(self, case_id: str) -> CommanderVerdict | None:
        """Process the supplied media on demand, as a manager request would."""
        event = await self._record_event(
            case_id=case_id,
            event_type="manual_review",
            source="site-controller",
            source_id=None,
            payload={"reason": "manual media review requested"},
            is_simulated=False,
        )
        return await self.handle_event(event)

    # ------------------------------------------------------------------ #
    # targeted alerts
    # ------------------------------------------------------------------ #

    async def _dispatch_alerts(
        self, case_id: str, *, verdict: CommanderVerdict, lift_active: bool
    ) -> None:
        """Alert only the workers actually near the hazard (spec section 4.4)."""
        positions = await self._context.store.find(
            WORKER_POSITIONS, {"caseId": case_id}, sort=[("timestamp", 1)]
        )
        latest: dict[str, WorkerPosition] = {}
        for doc in positions:
            position = WorkerPosition.model_validate(doc)
            latest[position.workerAlias] = position

        if not latest:
            return

        model = await self.site_model()
        evidence_ids = await policy_gate.evidence_for_alert(self._context, case_id)

        for alias, position in latest.items():
            relation = position.relation
            zone_id = position.zoneId
            if model is not None:
                from packages.site_model import resolve_zone  # noqa: PLC0415

                resolution = resolve_zone(
                    model,
                    zone_id=position.zoneId,
                    floor_id=position.floorId,
                    x=position.x,
                    y=position.y,
                )
                relation = resolution.relation
                zone_id = resolution.zoneId
            if isinstance(relation, WorkerZoneRelation):
                relation_value = relation.value
            else:
                relation_value = str(relation)

            tier = policy_gate.tier_for(
                relation_value, lift_active=lift_active, decision=verdict.decision.value
            )
            if tier is None:
                continue
            await policy_gate.send_worker_alert(
                self._context,
                case_id=case_id,
                worker_alias=alias,
                tier=tier,
                zone_id=zone_id,
                evidence_ids=evidence_ids,
            )

    async def escalate_unacknowledged(self, case_id: str) -> list[str]:
        """No acknowledgement is itself an escalation trigger (spec section 4.4)."""
        outstanding = await policy_gate.unacknowledged_alerts(self._context, case_id)
        escalated: list[str] = []
        now = utcnow()
        for notification in outstanding:
            deadline = notification.ackDeadlineSeconds or 0
            if not deadline:
                continue
            if (now - notification.sentAt).total_seconds() < deadline:
                continue
            await policy_gate.send_worker_alert(
                self._context,
                case_id=case_id,
                worker_alias=notification.workerAlias,
                tier=AlertTier.ESCALATE,
                zone_id=notification.zoneId,
                evidence_ids=notification.reasonEvidenceIds,
            )
            escalated.append(notification.id)
        return escalated
