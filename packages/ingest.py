"""Event-time import of cleared local data.

Documents, the site model and the telemetry trace are imported during the build
window and then everything runs from the local store (spec section 4.2). Each
import records provenance and a checksum so the submission can state exactly what
was used.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from packages.config import Settings
from packages.contracts import DocumentChunk, utcnow
from packages.media import build_document_chunks, discover_documents
from packages.storage.base import (
    ACTIONS,
    AGENT_RUNS,
    CASES,
    DOCUMENTS,
    EVIDENCE,
    NOTIFICATIONS,
    POLICY_LOG,
    REDACTION_MANIFEST,
    SITE_EVENTS,
    SOURCE_MANIFEST,
    TELEMETRY,
    WORKER_POSITIONS,
    Store,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ImportReport:
    documents: int = 0
    chunks: int = 0
    ruleBearingChunks: int = 0
    files: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "documents": self.documents,
            "chunks": self.chunks,
            "ruleBearingChunks": self.ruleBearingChunks,
            "files": self.files,
        }


async def import_documents(store: Store, settings: Settings) -> ImportReport:
    """Index every cleared document in `data/raw/documents` for rule retrieval."""
    report = ImportReport()
    directory = settings.path(settings.raw_document_dir)
    for asset in discover_documents(directory):
        document_id = asset.meta.get("documentId") or asset.path.stem
        source_id = asset.meta.get("sourceId") or document_id
        title = asset.meta.get("title") or asset.path.stem

        chunks: list[DocumentChunk] = build_document_chunks(
            path=asset.path,
            document_id=document_id,
            source_id=source_id,
            title=title,
            checksum=asset.checksum,
        )
        await store.delete_many(DOCUMENTS, {"documentId": document_id})
        for chunk in chunks:
            await store.insert_one(DOCUMENTS, chunk.to_doc())

        rule_bearing = sum(1 for chunk in chunks if chunk.ruleKey)
        report.documents += 1
        report.chunks += len(chunks)
        report.ruleBearingChunks += rule_bearing
        report.files.append(
            {
                "documentId": document_id,
                "sourceId": source_id,
                "title": title,
                "path": str(asset.path.relative_to(settings.path("."))) if _is_relative(asset.path, settings) else str(asset.path),
                "checksum": asset.checksum,
                "provenance": asset.provenance,
                "license": asset.license,
                "chunks": len(chunks),
                "ruleBearingChunks": rule_bearing,
                "ruleKeys": sorted({chunk.ruleKey for chunk in chunks if chunk.ruleKey}),
            }
        )
        await store.update_one(
            SOURCE_MANIFEST,
            {"sourceId": source_id},
            {
                "checksum": asset.checksum,
                "retrievedAt": utcnow().isoformat().replace("+00:00", "Z"),
                "lastEventAt": utcnow().isoformat().replace("+00:00", "Z"),
                "status": "fresh",
                "origin": asset.provenance,
                "license": asset.license,
            },
        )
        logger.info(
            "indexed %s: %d chunks, %d rule-bearing", document_id, len(chunks), rule_bearing
        )
    return report


def _is_relative(path: Path, settings: Settings) -> bool:
    try:
        path.relative_to(settings.path("."))
        return True
    except ValueError:
        return False


# Collections cleared by a demo reset. `documents`, `site_model`,
# `telemetry_recordings` and `source_manifest` survive, because they are imported
# reference data rather than case activity.
RESETTABLE = [
    EVIDENCE,
    SITE_EVENTS,
    TELEMETRY,
    WORKER_POSITIONS,
    NOTIFICATIONS,
    ACTIONS,
    AGENT_RUNS,
    POLICY_LOG,
    REDACTION_MANIFEST,
]


async def reset_case(store: Store, case_id: str) -> dict[str, int]:
    """Clear case activity for a fresh demo run, keeping imported reference data."""
    removed: dict[str, int] = {}
    for collection in RESETTABLE:
        removed[collection] = await store.delete_many(collection, {"caseId": case_id})
    removed[POLICY_LOG] = removed.get(POLICY_LOG, 0) + await store.delete_many(
        POLICY_LOG, {"caseId": None}
    )
    await store.update_one(
        CASES,
        {"caseId": case_id},
        {
            "decision": "ESCALATE",
            "reasons": ["Case reset; no evidence or applicable rule has been retrieved yet."],
            "requiredBeforeApproval": [],
            "latestEvidenceIds": [],
            "confidence": 0.0,
            "narrative": None,
            "liftActive": False,
            "recoveredFromStore": False,
            "updatedAt": utcnow().isoformat().replace("+00:00", "Z"),
        },
    )
    for doc in await store.find(SOURCE_MANIFEST):
        await store.update_one(
            SOURCE_MANIFEST,
            {"_id": doc["_id"]},
            {"status": "unavailable", "lastEventAt": None},
        )
    return removed
