"""Agent runtime, policy enforcement and honest framework reporting."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import shutil
from typing import Any

from packages.config import Settings, get_settings
from packages.runtime.agent_runtime import DEFAULT_CONCURRENCY, AgentRuntime
from packages.runtime.openshell import PolicyDecision, PolicyEngine

__all__ = [
    "DEFAULT_CONCURRENCY",
    "AgentRuntime",
    "PolicyDecision",
    "PolicyEngine",
    "framework_status",
]


def _module_present(name: str) -> tuple[bool, str | None]:
    try:
        if importlib.util.find_spec(name) is None:
            return False, None
    except (ImportError, ValueError):
        return False, None
    try:
        return True, importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return True, None


def framework_status(settings: Settings | None = None) -> list[dict[str, Any]]:
    """Report what is actually running, per required-stack item.

    The submission must name each framework with a one-sentence role (spec section
    16). Reporting `mode: shim` where a framework is not installed is deliberate:
    claiming an integration that is not present would be worse than the gap.
    """
    settings = settings or get_settings()

    openshell_present, openshell_version = _module_present("openshell")
    nemoclaw_present, nemoclaw_version = _module_present("nemoclaw")
    openclaw_cli = shutil.which("openclaw")

    return [
        {
            "name": "OpenShell",
            "role": (
                "Confines the agent sandbox: denies public egress, raw-media export "
                "and equipment actuation, and requires a named human approver before a "
                "lift clearance can be issued."
            ),
            "configured": settings.openshell_backend,
            "installed": openshell_present,
            "version": openshell_version,
            "mode": "native" if (settings.openshell_backend == "native" and openshell_present) else "shim",
            "note": (
                "Policy decisions delegated to the installed OpenShell runtime."
                if openshell_present and settings.openshell_backend == "native"
                else "Policy enforced by the local auditable shim in packages/runtime/openshell.py "
                "against config/openshell-policy.yaml."
            ),
        },
        {
            "name": "OpenClaw",
            "role": (
                "Hosts the named specialist agent roles that write structured evidence "
                "back to the case store."
            ),
            "configured": settings.agent_runtime,
            "installed": bool(openclaw_cli),
            "version": None,
            "mode": "native" if (settings.agent_runtime == "openclaw" and openclaw_cli) else "shim",
            "note": (
                f"OpenClaw CLI found at {openclaw_cli}."
                if openclaw_cli
                else "Agent roles run in-process under packages/runtime/agent_runtime.py with the "
                "same contracts, concurrency limit and run journal."
            ),
        },
        {
            "name": "NemoClaw",
            "role": (
                "Manages sandbox lifecycle and local inference routing for the agent "
                "environment on the DGX host."
            ),
            "configured": settings.lifecycle,
            "installed": nemoclaw_present,
            "version": nemoclaw_version,
            "mode": "native" if (settings.lifecycle == "nemoclaw" and nemoclaw_present) else "shim",
            "note": (
                "NemoClaw lifecycle management active."
                if nemoclaw_present and settings.lifecycle == "nemoclaw"
                else "Not available on this host. Sandbox lifecycle is the local process "
                "lifecycle; durable state lives in the case store so a restart recovers the case."
            ),
        },
        {
            "name": "MongoDB",
            "role": (
                "Durable evidence and event store, retrieval source and recovery layer; "
                "its change feed drives the agent loop."
            ),
            "configured": settings.storage_backend,
            "installed": settings.storage_backend == "mongodb",
            "version": None,
            "mode": "native" if settings.storage_backend == "mongodb" else "shim",
            "note": (
                "MongoDB Community local single-node replica set with Change Streams."
                if settings.storage_backend == "mongodb"
                else "No MongoDB on this host: an append-only local journal with the same "
                "change-feed semantics is in use. Switch to the runtime-host profile for the "
                "graded path."
            ),
        },
    ]
