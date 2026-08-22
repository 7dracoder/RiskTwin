#!/usr/bin/env python3
"""Event-time import of cleared local data, with an attribution record.

Imports, in order: the versioned site model, the approved source registry, the
recorded telemetry trace, and every cleared document in `data/raw/documents`.
Each import records provenance, licence and a SHA-256 checksum so the submission
can state exactly which assets were used (spec sections 4.2 and 8.5).

Nothing here contacts the network. Documents are read from disk, chunked locally
and indexed into the store for the Rules Retrieval agent.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from _common import banner, configure_logging, field  # noqa: I001 - fixes sys.path

from agents import data_watcher
from agents.base import AgentContext
from packages import ingest
from packages.config import get_settings
from packages.inference import build_inference_suite
from packages.replay import load_recording_file
from packages.runtime import AgentRuntime, PolicyEngine
from packages.site_model import seed_site_model
from packages.storage import build_store
from packages.storage.base import DOCUMENTS, REPLAY_STATE, TELEMETRY_RECORDINGS


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="write the attribution report as JSON to this path",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)

    settings = get_settings()
    store = build_store(settings)
    await store.connect()
    await store.ensure_indexes()

    context = AgentContext(
        store=store,
        settings=settings,
        models=build_inference_suite(settings),
        runtime=AgentRuntime(store, label=settings.agent_runtime),
        policy=PolicyEngine.from_settings(settings),
    )

    banner("Site model")
    model = await seed_site_model(store, settings.path(settings.site_model_path))
    field("siteModelId", model.siteModelId)
    field("version", model.version)
    field("floors", ", ".join(floor.floorId for floor in model.floors))
    field("zones", ", ".join(f"{zone.zoneId}({zone.kind})" for zone in model.zones))

    banner("Approved source registry")
    live_fetch = {
        entry["sourceId"]
        for entry in data_watcher.load_source_registry(context)
        if entry.get("liveFetch")
    }
    manifests = await data_watcher.register_sources(context)
    for manifest in manifests:
        flags = []
        if manifest.critical:
            flags.append("critical")
        if manifest.requiresContinuousFeed:
            flags.append("continuous")
        if manifest.sourceId in live_fetch:
            flags.append("LIVE-FETCH")
        field(manifest.sourceId, f"{manifest.ingestMode} [{', '.join(flags) or 'optional'}]")
    field("live external fetch", ", ".join(sorted(live_fetch)) or "no source is allowed to fetch")

    banner("Recorded telemetry trace")
    recording_path = settings.path(settings.recording_path)
    recording_report: dict[str, object] = {}
    if recording_path.exists():
        recording = load_recording_file(recording_path)
        await store.upsert(
            TELEMETRY_RECORDINGS, {"_id": recording.id}, recording.to_doc()
        )
        await store.delete_many(REPLAY_STATE, {"caseId": settings.case_id})
        field("recordingId", recording.recordingId)
        field("provenance", recording.provenance)
        field("licence", recording.license)
        field("isSimulated", recording.isSimulated)
        field("events", len(recording.events))
        field("duration (s)", recording.durationSeconds)
        field("checksum", recording.checksum)
        recording_report = {
            "recordingId": recording.recordingId,
            "provenance": recording.provenance,
            "license": recording.license,
            "isSimulated": recording.isSimulated,
            "checksum": recording.checksum,
            "events": len(recording.events),
        }
    else:
        field("recording", f"MISSING at {recording_path}")

    banner("Cleared documents")
    report = await ingest.import_documents(store, settings)
    for item in report.files:
        field(item["documentId"], f"{item['chunks']} chunks, {item['ruleBearingChunks']} rule-bearing")
        field("  provenance", item["provenance"])
        field("  licence", item["license"])
        field("  checksum", item["checksum"])
        field("  rule keys", ", ".join(item["ruleKeys"]) or "none")

    indexed = await store.count(DOCUMENTS)
    banner("Result")
    field("documents indexed", report.documents)
    field("chunks in store", indexed)
    field("rule-bearing chunks", report.ruleBearingChunks)
    field("storage backend", store.backend)

    if report.ruleBearingChunks == 0:
        print(
            "\n  WARNING: no rule-bearing chunk was indexed. The Commander cannot\n"
            "  authorise anything without a retrieved limit, so every decision will\n"
            "  stay at ESCALATE. Check data/raw/documents."
        )

    if args.report:
        payload = {
            "siteModel": {"siteModelId": model.siteModelId, "version": model.version},
            "sources": [manifest.to_doc() for manifest in manifests],
            "recording": recording_report,
            "documents": report.as_dict(),
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        field("report written", args.report)

    await context.models.close()
    await store.close()
    return 0 if report.ruleBearingChunks else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
