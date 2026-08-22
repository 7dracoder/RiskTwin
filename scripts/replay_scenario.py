#!/usr/bin/env python3
"""Local event-sequence driver for the LIFT-042 scenario.

Runs the whole loop in one process — store, change feed, agents, policy gate —
without the HTTP layer, and prints the decision after every recorded event. This
is the fastest way to verify the staged anomaly sequence in spec section 4.2 and
the state transitions in section 7.5.

Every emitted event carries `source: "recorded-replay"` and `isSimulated: true`.
The banner is printed for the same reason the dashboard shows it: nothing here is
a live sensor reading.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib

from _common import banner, configure_logging, field  # noqa: I001 - fixes sys.path

from apps.api.state import AppState
from packages import ingest
from packages.config import get_settings
from packages.replay import load_recording_file
from packages.storage.base import CASES, EVIDENCE

BANNER = "RECORDED / SIMULATED SITE TELEMETRY — REPLAY MODE"


async def _decision(state: AppState) -> tuple[str, list[str]]:
    doc = await state.store.find_one(CASES, {"caseId": state.settings.case_id})
    if doc is None:
        return "MISSING", []
    return doc.get("decision", "UNKNOWN"), doc.get("reasons", [])


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--speed", type=float, default=0.0,
        help="playback speed; 0 replays every event immediately (default)",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="clear prior case activity before replaying",
    )
    parser.add_argument(
        "--skip-documents", action="store_true",
        help="do not import the lift plan, to show the no-rules ESCALATE state",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)

    settings = get_settings()
    state = AppState(settings)
    await state.startup()

    try:
        banner("RiskTwin scenario replay")
        print(f"  {BANNER}")
        field("case", settings.case_id)
        field("storage", state.store.backend)
        field("degraded model mode", state.models.degraded)
        for name, ref in state.models.model_refs().items():
            field(f"  {name} model", f"{ref['backend']} / {ref['model']}")

        if args.reset:
            await state.replay.reset(settings.case_id)
            await ingest.reset_case(state.store, settings.case_id)
            state.orchestrator.invalidate_rules()
            field("reset", "case activity cleared")

        decision, _ = await _decision(state)
        banner("Before any evidence")
        field("decision", decision)

        if not args.skip_documents:
            report = await ingest.import_documents(state.store, settings)
            verdict = await state.orchestrator.redecide(settings.case_id)
            banner("After importing the cleared documents")
            field("documents", report.documents)
            field("rule-bearing chunks", report.ruleBearingChunks)
            field("decision", verdict.decision.value)
            for reason in verdict.reasons:
                print(f"    - {reason}")

        recording = load_recording_file(settings.path(settings.recording_path))
        banner(f"Replaying {recording.recordingId} ({len(recording.events)} events)")
        field("provenance", recording.provenance[:96] + "…")
        field("checksum", recording.checksum)

        previous = (await _decision(state))[0]
        position = 0.0
        for event in recording.events:
            if args.speed > 0:
                await asyncio.sleep(max(0.0, (event.offsetSeconds - position) / args.speed))
            position = event.offsetSeconds
            await state.orchestrator.ingest_replay_event(event, recording)
            await state.wait_idle()
            decision, reasons = await _decision(state)
            marker = "->" if decision != previous else "  "
            print(f"  {marker} t+{event.offsetSeconds:>3.0f}s  {decision:<22} {event.label}")
            if decision != previous:
                for reason in reasons:
                    print(f"        because: {reason}")
                previous = decision

        banner("Final state")
        decision, reasons = await _decision(state)
        field("decision", decision)
        for reason in reasons:
            print(f"    - {reason}")
        field("evidence records", await state.store.count(EVIDENCE, {"caseId": settings.case_id}))
        snapshot = await state.system_snapshot()
        field("policy", f"{snapshot['policy']['policyId']} / {snapshot['policy']['backend']}")
        field("local-only endpoints", snapshot["localOnlyEndpoints"] or "no served endpoint")
        return 0
    finally:
        with contextlib.suppress(Exception):
            await state.shutdown()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
