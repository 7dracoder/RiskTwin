"""Data Watcher — validates approved sources and marks freshness.

The narrow ingestion component. Agents never browse the web; they read the local
facts this component has already validated (spec section 4.2). Live external
fetching stays disabled unless an organizer explicitly approves one documented
source, and even then only this component may use it — never the agent sandbox.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import yaml

from agents.base import AgentContext, write_evidence
from packages.contracts import (
    EvidenceType,
    Severity,
    SourceManifest,
    SourceStatus,
    utcnow,
)
from packages.storage.base import SOURCE_MANIFEST

logger = logging.getLogger(__name__)

AGENT_NAME = "data-watcher"


def load_source_registry(context: AgentContext) -> list[dict[str, Any]]:
    path = context.settings.path(context.settings.sources_path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return payload.get("sources", [])


async def register_sources(context: AgentContext) -> list[SourceManifest]:
    """Write a manifest row per declared source, preserving any observed activity."""
    manifests: list[SourceManifest] = []
    for entry in load_source_registry(context):
        existing = await context.store.find_one(
            SOURCE_MANIFEST, {"sourceId": entry["sourceId"]}
        )
        manifest = SourceManifest(
            sourceId=entry["sourceId"],
            sourceClass=entry.get("sourceClass", "unknown"),
            label=entry.get("label", entry["sourceId"]),
            origin=str(entry.get("owner", "unrecorded")),
            license=str(entry.get("license", "unrecorded")),
            critical=bool(entry.get("critical", False)),
            requiresContinuousFeed=bool(entry.get("requiresContinuousFeed", False)),
            schemaVersion=int(entry.get("schemaVersion", 1)),
            ingestMode=entry.get("ingestMode", "recorded-replay"),
            freshnessSlaSeconds=int(entry.get("freshnessSlaSeconds", 120)),
            failureRule=entry.get("failureRule", "ESCALATE"),
            status=SourceStatus.UNAVAILABLE,
            isSimulated=entry.get("ingestMode") == "recorded-replay",
        )
        if existing:
            manifest.id = existing["_id"]
            manifest.status = SourceStatus(existing.get("status", SourceStatus.UNAVAILABLE))
            manifest.lastEventAt = (
                datetime.fromisoformat(existing["lastEventAt"].replace("Z", "+00:00"))
                if existing.get("lastEventAt")
                else None
            )
        await context.store.upsert(
            SOURCE_MANIFEST, {"sourceId": manifest.sourceId}, manifest.to_doc()
        )
        manifests.append(manifest)
    return manifests


async def record_source_activity(
    context: AgentContext, source_id: str, *, checksum: str | None = None
) -> None:
    """Mark a source fresh because a validated event just arrived from it."""
    await context.store.update_one(
        SOURCE_MANIFEST,
        {"sourceId": source_id},
        {
            "status": SourceStatus.FRESH.value,
            "lastEventAt": utcnow().isoformat().replace("+00:00", "Z"),
            "retrievedAt": utcnow().isoformat().replace("+00:00", "Z"),
            **({"checksum": checksum} if checksum else {}),
        },
    )


async def mark_source_status(
    context: AgentContext, source_id: str, status: SourceStatus
) -> SourceManifest | None:
    doc = await context.store.update_one(
        SOURCE_MANIFEST,
        {"sourceId": source_id},
        {"status": status.value, "retrievedAt": utcnow().isoformat().replace("+00:00", "Z")},
    )
    return SourceManifest.model_validate(doc) if doc else None


async def load_sources(context: AgentContext) -> list[SourceManifest]:
    docs = await context.store.find(SOURCE_MANIFEST)
    return [SourceManifest.model_validate(doc) for doc in docs]


async def evaluate_freshness(context: AgentContext, case_id: str) -> list[str]:
    """Compare each source against its SLA and write freshness evidence on change.

    Freshness is a safety feature: an unverifiable condition is an adverse
    condition, so a stale critical source is evidence in its own right
    (spec section 4.2).
    """
    now = utcnow()
    written: list[str] = []
    for source in await load_sources(context):
        if not source.requiresContinuousFeed:
            # An event-driven source is not expected to stream, so silence is not a
            # freshness failure. Its absence shows up as missing evidence instead.
            continue
        previous = source.status
        if source.lastEventAt is None:
            current = SourceStatus.UNAVAILABLE
            age_seconds = None
        else:
            age_seconds = (now - source.lastEventAt).total_seconds()
            deadline = timedelta(seconds=source.freshnessSlaSeconds)
            current = (
                SourceStatus.FRESH if age_seconds <= deadline.total_seconds() else SourceStatus.STALE
            )

        if current is previous:
            continue

        await mark_source_status(context, source.sourceId, current)
        if current is SourceStatus.FRESH:
            continue

        severity = Severity.CRITICAL if source.critical else Severity.MEDIUM
        age_text = (
            f"last update {age_seconds:.0f}s ago"
            if age_seconds is not None
            else "no update has ever been received"
        )
        record = await write_evidence(
            context,
            case_id=case_id,
            agent=AGENT_NAME,
            evidence_type=EvidenceType.SOURCE_FRESHNESS,
            finding=(
                f"Source {source.label} ({source.sourceId}) is {current.value}: {age_text}, "
                f"allowed freshness is {source.freshnessSlaSeconds}s. "
                f"Configured failure rule: {source.failureRule}."
            ),
            confidence=1.0,
            severity=severity,
            source_refs=[f"source:{source.sourceId}"],
            detail={
                "sourceId": source.sourceId,
                "status": current.value,
                "critical": source.critical,
                "slaSeconds": source.freshnessSlaSeconds,
                "lastSeenSecondsAgo": round(age_seconds, 1) if age_seconds is not None else None,
                "failureRule": source.failureRule,
            },
        )
        written.append(record.id)
    return written


async def force_stale(
    context: AgentContext, case_id: str, source_id: str, payload: dict[str, Any]
) -> list[str]:
    """Apply an explicit source-freshness failure carried by the replay trace."""
    source = next((s for s in await load_sources(context) if s.sourceId == source_id), None)
    if source is None:
        return []
    await mark_source_status(context, source_id, SourceStatus.STALE)
    record = await write_evidence(
        context,
        case_id=case_id,
        agent=AGENT_NAME,
        evidence_type=EvidenceType.SOURCE_FRESHNESS,
        finding=(
            f"Source {source.label} ({source_id}) has no update for longer than its "
            f"{payload.get('slaSeconds', source.freshnessSlaSeconds)}s freshness SLA; "
            "the current condition cannot be verified."
        ),
        confidence=1.0,
        severity=Severity.CRITICAL if source.critical else Severity.MEDIUM,
        source_refs=[f"source:{source_id}"],
        detail={
            "sourceId": source_id,
            "status": SourceStatus.STALE.value,
            "critical": source.critical,
            "slaSeconds": payload.get("slaSeconds", source.freshnessSlaSeconds),
            "lastSeenSecondsAgo": None,
            "failureRule": source.failureRule,
            "reportedBy": payload.get("reportedBy", "replay-trace"),
        },
    )
    return [record.id]
