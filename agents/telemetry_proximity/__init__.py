"""Telemetry & Proximity Agent — threshold breaches and worker-zone conflicts.

Every number here comes from deterministic arithmetic against a retrieved limit.
This agent is the high-frequency path, so it never calls a text model
(spec section 4.4).
"""

from __future__ import annotations

import logging
from typing import Any

from agents.base import AgentContext, write_evidence
from packages.contracts import (
    EvidenceType,
    Severity,
    SiteModel,
    TelemetryReading,
    WorkerPosition,
    WorkerZoneRelation,
)
from packages.risk_engine import READABLE_KIND, RuleSet, evaluate_threshold
from packages.site_model import resolve_zone

logger = logging.getLogger(__name__)

AGENT_NAME = "telemetry-proximity"


async def evaluate_reading(
    context: AgentContext, *, reading: TelemetryReading, rules: RuleSet
) -> list[str]:
    """Compare one reading with its retrieved limit and write the verdict."""
    verdict = evaluate_threshold(reading.kind, reading.value, rules, unit=reading.unit)
    name = READABLE_KIND.get(reading.kind, reading.kind)
    unit = f" {verdict.unit}" if verdict.unit else ""

    if verdict.limit is None:
        finding = (
            f"{name} is {verdict.value:g}{unit}. No retrieved limit applies to this reading, "
            "so it cannot be cleared against a rule."
        )
        severity = Severity.MEDIUM if reading.kind in {"wind_gust_kmh", "crane_load_pct"} else Severity.INFO
        confidence = 0.8
    elif verdict.breached:
        finding = (
            f"{name} {verdict.value:g}{unit} exceeds the retrieved limit of "
            f"{verdict.limit:g}{unit} by {verdict.deviation:g}{unit}."
        )
        severity = Severity.CRITICAL if reading.kind == "wind_gust_kmh" else Severity.HIGH
        confidence = 0.98
    else:
        finding = (
            f"{name} {verdict.value:g}{unit} is within the retrieved limit of {verdict.limit:g}{unit}."
        )
        severity = Severity.INFO
        confidence = 0.95

    record = await write_evidence(
        context,
        case_id=reading.caseId,
        agent=AGENT_NAME,
        evidence_type=EvidenceType.TELEMETRY_OBSERVATION,
        finding=finding,
        confidence=confidence,
        severity=severity,
        source_refs=[f"telemetry:{reading.id}", f"source:{reading.sourceId or reading.source}"],
        detail={
            **verdict.as_detail(),
            "sourceRef": f"telemetry:{reading.id}",
            "isSimulated": reading.isSimulated,
        },
    )
    return [record.id]


async def evaluate_position(
    context: AgentContext,
    *,
    position: WorkerPosition,
    site_model: SiteModel | None,
    lift_active: bool,
) -> tuple[list[str], WorkerZoneRelation]:
    """Resolve a reported position against the active site model version."""
    if site_model is None:
        record = await write_evidence(
            context,
            case_id=position.caseId,
            agent=AGENT_NAME,
            evidence_type=EvidenceType.PROXIMITY_OBSERVATION,
            finding=(
                f"{position.workerAlias} reported a position but no active site model version "
                "is available, so the position cannot be interpreted."
            ),
            confidence=1.0,
            severity=Severity.HIGH,
            source_refs=[f"worker-position:{position.id}"],
            detail={
                "workerAlias": position.workerAlias,
                "zoneId": position.zoneId,
                "relation": WorkerZoneRelation.COVERAGE_UNKNOWN.value,
            },
        )
        return [record.id], WorkerZoneRelation.COVERAGE_UNKNOWN

    resolution = resolve_zone(
        site_model,
        zone_id=position.zoneId,
        floor_id=position.floorId,
        x=position.x,
        y=position.y,
    )

    severity = {
        WorkerZoneRelation.INSIDE_RISK_ZONE: Severity.CRITICAL if lift_active else Severity.MEDIUM,
        WorkerZoneRelation.APPROACHING: Severity.MEDIUM,
        WorkerZoneRelation.COVERAGE_UNKNOWN: Severity.HIGH,
        WorkerZoneRelation.SAFE: Severity.INFO,
    }[resolution.relation]

    if resolution.relation is WorkerZoneRelation.INSIDE_RISK_ZONE:
        finding = (
            f"{position.workerAlias} is inside {resolution.zoneKind} zone {resolution.zoneId} "
            + ("during an active lift" if lift_active else "while the lift is not active")
            + f" ({resolution.detail})."
        )
    elif resolution.relation is WorkerZoneRelation.APPROACHING:
        finding = (
            f"{position.workerAlias} is approaching exclusion zone {resolution.zoneId}: "
            f"{resolution.detail}."
        )
    elif resolution.relation is WorkerZoneRelation.COVERAGE_UNKNOWN:
        finding = (
            f"{position.workerAlias} position cannot be resolved against "
            f"{resolution.siteModelId} v{resolution.siteModelVersion}: {resolution.detail}."
        )
    else:
        finding = (
            f"{position.workerAlias} is in a non-restricted area: {resolution.detail}."
        )

    record = await write_evidence(
        context,
        case_id=position.caseId,
        agent=AGENT_NAME,
        evidence_type=EvidenceType.PROXIMITY_OBSERVATION,
        finding=finding,
        confidence=0.95,
        severity=severity,
        source_refs=[
            f"worker-position:{position.id}",
            f"site-model:{resolution.siteModelId}:v{resolution.siteModelVersion}",
        ],
        detail={
            "workerAlias": position.workerAlias,
            "zoneId": resolution.zoneId,
            "zoneKind": resolution.zoneKind,
            "relation": resolution.relation.value,
            "distanceMeters": resolution.distanceMeters,
            "siteModelId": resolution.siteModelId,
            "siteModelVersion": resolution.siteModelVersion,
            "liftActive": lift_active,
        },
    )
    return [record.id], resolution.relation


async def evaluate_site_state(
    context: AgentContext, *, case_id: str, kind: str, value: Any, source_id: str | None
) -> list[str]:
    """Record a discrete operational state change (lift active, zone reported clear)."""
    if kind == "lift_state":
        finding = f"Lift state is now {value!r}."
        severity = Severity.INFO
    elif kind == "zone_state":
        finding = f"Zone state reported as {value!r} by {source_id or 'an operational source'}."
        severity = Severity.INFO
    else:
        finding = f"{kind} reported as {value!r}."
        severity = Severity.INFO

    record = await write_evidence(
        context,
        case_id=case_id,
        agent=AGENT_NAME,
        evidence_type=EvidenceType.TELEMETRY_OBSERVATION,
        finding=finding,
        confidence=0.95,
        severity=severity,
        source_refs=[f"source:{source_id}"] if source_id else [],
        detail={"kind": kind, "value": value, "breached": False, "limit": None, "unit": None},
    )
    return [record.id]
