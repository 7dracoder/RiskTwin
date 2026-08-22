#!/usr/bin/env python3
"""Approved-source freshness checker, runnable outside the agent sandbox.

The Data Watcher is the only component allowed to reach an approved external
source, and it runs separately from the agents (spec section 8.5). Live fetching
stays disabled unless an organizer confirms a specific non-LLM source; this
script refuses to enable it from the command line and only reports what the
registry declares.

Two modes:

  --once    evaluate every source against its SLA and exit (used in checks)
  --watch   keep evaluating on a tick, the way the API's background loop does

The API already runs this loop internally. Use this script to inspect freshness
without the API, or to demonstrate the stale-source escalation on its own.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib

from _common import banner, configure_logging, field  # noqa: I001 - fixes sys.path

from agents import data_watcher
from agents.base import AgentContext
from agents.orchestrator import Orchestrator
from packages.config import get_settings
from packages.contracts import SourceStatus, utcnow
from packages.inference import build_inference_suite
from packages.runtime import AgentRuntime, PolicyEngine
from packages.storage import build_store


def _age(source) -> str:
    if source.lastEventAt is None:
        return "never"
    return f"{(utcnow() - source.lastEventAt).total_seconds():.0f}s ago"


async def report(context: AgentContext) -> int:
    """Print the freshness table. Returns the number of failing critical sources."""
    failing = 0
    for source in sorted(await data_watcher.load_sources(context), key=lambda s: s.sourceId):
        bad = source.status is not SourceStatus.FRESH
        if bad and source.critical and source.requiresContinuousFeed:
            failing += 1
        marks = []
        if source.critical:
            marks.append("critical")
        if source.requiresContinuousFeed:
            marks.append("continuous")
        field(
            source.sourceId,
            f"{source.status.value:<12} last event {_age(source):<10} "
            f"sla {source.freshnessSlaSeconds}s  [{', '.join(marks) or 'optional'}]",
        )
    return failing


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--once", action="store_true", help="evaluate once and exit")
    group.add_argument("--watch", action="store_true", help="evaluate on a tick until stopped")
    parser.add_argument("--interval", type=float, default=5.0, help="tick seconds for --watch")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)

    settings = get_settings()
    store = build_store(settings)
    await store.connect()
    context = AgentContext(
        store=store,
        settings=settings,
        models=build_inference_suite(settings),
        runtime=AgentRuntime(store, label=settings.agent_runtime),
        policy=PolicyEngine.from_settings(settings),
    )
    orchestrator = Orchestrator(context)

    banner("Data Watcher")
    field("case", settings.case_id)
    field("live external fetch", "ENABLED" if settings.data_watcher_live_fetch else "disabled")
    field("registry", settings.path(settings.sources_path))
    await data_watcher.register_sources(context)

    exit_code = 0
    try:
        if args.watch:
            print(f"\n  watching every {args.interval:.0f}s; Ctrl-C to stop\n")
            while True:
                written = await data_watcher.evaluate_freshness(context, settings.case_id)
                if written:
                    banner(f"freshness change at {utcnow():%H:%M:%S}")
                    await report(context)
                    verdict = await orchestrator.redecide(settings.case_id)
                    field("decision", verdict.decision.value)
                    for reason in verdict.reasons:
                        print(f"    - {reason}")
                await asyncio.sleep(args.interval)
        else:
            written = await data_watcher.evaluate_freshness(context, settings.case_id)
            banner("Source freshness")
            failing = await report(context)
            banner("Result")
            field("evidence written", len(written))
            field("failing critical sources", failing)
            if failing:
                print(
                    "\n  A stale or unavailable critical source is an adverse condition.\n"
                    "  The case can only ESCALATE while this is true."
                )
            exit_code = 1 if failing else 0
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n  stopped")
    finally:
        with contextlib.suppress(Exception):
            await context.models.close()
        await store.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
