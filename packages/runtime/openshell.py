"""Policy enforcement for the agent sandbox.

OpenShell is a product feature here, not a logo (spec section 8.2). Every proposed
action, every export and every outbound connection is evaluated against
`config/openshell-policy.yaml`, and the verdict is written to `policy_log` so the
dashboard action panel and the judge-facing policy view read the same record.

Backends
--------
`shim`   — this module. A local, auditable implementation of the documented policy.
`native` — delegate to an installed NVIDIA OpenShell runtime, used on the DGX.
           Falls back to the shim with a logged warning if it is not importable,
           so a missing runtime degrades visibly instead of silently allowing.
"""

from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from packages.config import Settings, get_settings
from packages.contracts import PolicyEffect

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PolicyDecision:
    effect: PolicyEffect
    reason: str
    policyId: str
    backend: str
    actionType: str
    constraints: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.effect is PolicyEffect.ALLOW

    @property
    def blocked(self) -> bool:
        return self.effect is PolicyEffect.DENY

    def as_dict(self) -> dict[str, Any]:
        return {
            "effect": self.effect.value,
            "reason": self.reason,
            "policyId": self.policyId,
            "backend": self.backend,
            "actionType": self.actionType,
            "constraints": self.constraints,
        }


class PolicyEngine:
    def __init__(self, policy: dict[str, Any], *, backend: str = "shim") -> None:
        self._policy = policy
        self._backend = backend
        self._actions = {
            entry["type"]: entry for entry in policy.get("actions", []) if "type" in entry
        }

    # ------------------------------------------------------------------ #
    # construction
    # ------------------------------------------------------------------ #

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> PolicyEngine:
        settings = settings or get_settings()
        policy = yaml.safe_load(settings.path(settings.policy_path).read_text(encoding="utf-8"))
        backend = settings.openshell_backend
        if backend == "native" and not _native_available():
            logger.warning(
                "RISKTWIN_OPENSHELL_BACKEND=native but the openshell runtime is not "
                "importable; falling back to the local shim. Install openshell on the "
                "runtime host before the demo."
            )
            backend = "shim-fallback"
        return cls(policy, backend=backend)

    @property
    def policy_id(self) -> str:
        return str(self._policy.get("policyId", "unknown"))

    @property
    def backend(self) -> str:
        return self._backend

    # ------------------------------------------------------------------ #
    # actions
    # ------------------------------------------------------------------ #

    def evaluate_action(self, action_type: str, context: dict[str, Any] | None = None) -> PolicyDecision:
        context = context or {}
        entry = self._actions.get(action_type)
        if entry is None:
            return self._decide(
                PolicyEffect.DENY,
                action_type,
                f"action {action_type!r} is not declared in {self.policy_id}; policy default is deny",
            )

        declared = PolicyEffect(entry.get("effect", "deny"))
        constraints = entry.get("constraints") or {}
        reason = entry.get("reason", "").strip() or f"policy default for {action_type}"

        blocked_decisions = constraints.get("blocked_when_decision_in") or []
        case_decision = context.get("caseDecision")
        if case_decision and case_decision in blocked_decisions:
            return self._decide(
                PolicyEffect.DENY,
                action_type,
                f"Safety-critical action requires a human approval and active case is {case_decision}.",
                constraints,
            )

        required_types = constraints.get("require_evidence_types") or []
        present_types = set(context.get("evidenceTypes") or [])
        missing = [item for item in required_types if item not in present_types]
        if missing:
            return self._decide(
                PolicyEffect.DENY,
                action_type,
                f"required evidence is missing: {', '.join(missing)}",
                constraints,
            )

        allowed_tiers = constraints.get("allowed_tiers")
        tier = context.get("tier")
        if allowed_tiers and tier and tier not in allowed_tiers:
            return self._decide(
                PolicyEffect.DENY,
                action_type,
                f"alert tier {tier!r} is not permitted by {self.policy_id}",
                constraints,
            )

        allowed_paths = constraints.get("allowed_paths")
        target = context.get("path")
        if allowed_paths and target and not _within_any(target, allowed_paths):
            return self._decide(
                PolicyEffect.DENY,
                action_type,
                f"{target!r} is outside the exportable paths {allowed_paths}",
                constraints,
            )
        if target and _within_any(target, self._policy.get("filesystem", {}).get("no_export", [])):
            return self._decide(
                PolicyEffect.DENY,
                action_type,
                f"{target!r} is inside a no-export path; only the redacted render may leave the workspace",
                constraints,
            )

        if declared is PolicyEffect.REQUIRE_APPROVAL:
            approver = context.get("approvedBy")
            if constraints.get("require_named_approver") and not approver:
                return self._decide(PolicyEffect.REQUIRE_APPROVAL, action_type, reason, constraints)
            if approver:
                return self._decide(
                    PolicyEffect.ALLOW,
                    action_type,
                    f"approved by named human approver {approver!r}",
                    constraints,
                )
            return self._decide(PolicyEffect.REQUIRE_APPROVAL, action_type, reason, constraints)

        return self._decide(declared, action_type, reason, constraints)

    # ------------------------------------------------------------------ #
    # network / export
    # ------------------------------------------------------------------ #

    def evaluate_network(self, target: str, *, component: str = "agent-sandbox") -> PolicyDecision:
        network = self._policy.get("network", {})
        host = urlparse(target).hostname or target
        allowed_hostnames = list(network.get("allow_hostnames") or [])
        if component == "data-watcher":
            allowed_hostnames += list(network.get("data_watcher_allow_hostnames") or [])

        if host in allowed_hostnames:
            return self._decide(
                PolicyEffect.ALLOW, "outbound_public_request", f"{host} is an allowlisted hostname"
            )

        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return self._decide(
                PolicyEffect.DENY,
                "outbound_public_request",
                f"{host!r} is not an allowlisted hostname for {component}",
            )

        for cidr in network.get("allow_cidrs") or []:
            if address in ipaddress.ip_network(cidr):
                return self._decide(
                    PolicyEffect.ALLOW,
                    "outbound_public_request",
                    f"{host} is inside permitted local range {cidr}",
                )
        return self._decide(
            PolicyEffect.DENY,
            "outbound_public_request",
            f"{host} is outside every permitted local range",
        )

    def evaluate_export(self, path: str) -> PolicyDecision:
        filesystem = self._policy.get("filesystem", {})
        if _within_any(path, filesystem.get("no_export", [])):
            return self.evaluate_action("export_raw_video", {"path": path})
        return self.evaluate_action("export_redacted_evidence", {"path": path})

    # ------------------------------------------------------------------ #
    # introspection for the dashboard policy view
    # ------------------------------------------------------------------ #

    def describe(self) -> dict[str, Any]:
        return {
            "policyId": self.policy_id,
            "backend": self._backend,
            "description": self._policy.get("description", "").strip(),
            "network": self._policy.get("network", {}),
            "filesystem": self._policy.get("filesystem", {}),
            "actions": [
                {
                    "type": entry.get("type"),
                    "effect": entry.get("effect"),
                    "reason": (entry.get("reason") or "").strip(),
                    "constraints": entry.get("constraints") or {},
                }
                for entry in self._policy.get("actions", [])
            ],
        }

    def _decide(
        self,
        effect: PolicyEffect,
        action_type: str,
        reason: str,
        constraints: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        return PolicyDecision(
            effect=effect,
            reason=reason,
            policyId=self.policy_id,
            backend=self._backend,
            actionType=action_type,
            constraints=constraints or {},
        )


def _within_any(target: str, prefixes: list[str]) -> bool:
    candidate = Path(target)
    for prefix in prefixes:
        prefix_path = Path(prefix)
        try:
            candidate.relative_to(prefix_path)
            return True
        except ValueError:
            if str(prefix_path) in str(candidate):
                return True
    return False


def _native_available() -> bool:
    try:
        import openshell  # noqa: F401, PLC0415

        return True
    except Exception:  # noqa: BLE001 - absence is the only thing that matters
        return False
