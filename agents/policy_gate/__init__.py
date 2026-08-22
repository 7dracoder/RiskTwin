"""Policy Gate — every action passes through OpenShell policy before it exists.

Drafting is permitted deterministically; anything safety-critical or external is
blocked or held for a named human approver (spec section 6.1). Refusals are
recorded with their reason and policy evidence so the dashboard can show
`BLOCKED / APPROVAL REQUIRED` with a traceable justification.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.base import AgentContext
from packages.contracts import (
    ActionRecord,
    ActionStatus,
    AlertTier,
    Evidence,
    Notification,
    NotificationStatus,
    PolicyEffect,
    PolicyLogEntry,
    utcnow,
)
from packages.storage.base import ACTIONS, CASES, EVIDENCE, NOTIFICATIONS, POLICY_LOG

logger = logging.getLogger(__name__)

AGENT_NAME = "policy-gate"

_ACK_DEADLINE_SECONDS = 45

_TIER_MESSAGES = {
    AlertTier.CAUTION: "Caution: {zone} has an active lift hazard ahead. Use the zone A east corridor.",
    AlertTier.STOP_ACK_REQUIRED: "Stop. Do not enter {zone}. Active suspended-load risk.",
    AlertTier.ESCALATE: "Move to a safe area and contact your supervisor.",
    AlertTier.INFO: "Route advisory for {zone}.",
}


async def log_policy_decision(
    context: AgentContext,
    *,
    case_id: str | None,
    subject: str,
    decision: Any,
) -> None:
    await context.store.insert_one(
        POLICY_LOG,
        PolicyLogEntry(
            caseId=case_id,
            subject=subject,
            actionType=decision.actionType,
            effect=PolicyEffect(decision.effect),
            reason=decision.reason,
            policyId=decision.policyId,
            backend=decision.backend,
            context={"constraints": decision.constraints},
        ).to_doc(),
    )


async def _case_context(context: AgentContext, case_id: str) -> dict[str, Any]:
    case = await context.store.find_one(CASES, {"caseId": case_id})
    evidence_docs = await context.store.find(EVIDENCE, {"caseId": case_id})
    return {
        "caseDecision": (case or {}).get("decision"),
        "evidenceTypes": sorted({doc.get("evidenceType") for doc in evidence_docs if doc.get("evidenceType")}),
        "policyEvidenceIds": [
            doc["_id"] for doc in evidence_docs if doc.get("evidenceType") == "policy_evidence"
        ][:3],
    }


# --------------------------------------------------------------------------- #
# Actions
# --------------------------------------------------------------------------- #


async def propose_action(
    context: AgentContext,
    *,
    case_id: str,
    action_type: str,
    requested_by: str,
    payload: dict[str, Any] | None = None,
) -> ActionRecord:
    """Create an auditable action record carrying the policy verdict."""
    payload = payload or {}
    case_state = await _case_context(context, case_id)
    decision = context.policy.evaluate_action(
        action_type,
        {
            "caseDecision": case_state["caseDecision"],
            "evidenceTypes": case_state["evidenceTypes"],
            "requestedBy": requested_by,
            **payload,
        },
    )
    await log_policy_decision(context, case_id=case_id, subject=requested_by, decision=decision)

    status = {
        PolicyEffect.ALLOW: ActionStatus.APPROVED,
        PolicyEffect.DENY: ActionStatus.BLOCKED,
        PolicyEffect.REQUIRE_APPROVAL: ActionStatus.AWAITING_APPROVAL,
    }[decision.effect]

    record = ActionRecord(
        caseId=case_id,
        type=action_type,
        status=status,
        requestedBy=requested_by,
        requiresApproval=decision.effect is PolicyEffect.REQUIRE_APPROVAL,
        reason=decision.reason,
        policyEffect=decision.effect,
        policyEvidence=case_state["policyEvidenceIds"],
        payload=payload,
        audit=[
            {
                "at": utcnow().isoformat().replace("+00:00", "Z"),
                "by": requested_by,
                "event": "proposed",
                "policyEffect": decision.effect.value,
                "reason": decision.reason,
            }
        ],
    )
    await context.store.insert_one(ACTIONS, record.to_doc())
    return record


async def decide_approval(
    context: AgentContext,
    *,
    action_id: str,
    approved_by: str,
    approve: bool,
    note: str | None = None,
) -> ActionRecord | None:
    """Apply a named human's approval decision, re-checking policy at approval time."""
    doc = await context.store.find_one(ACTIONS, {"_id": action_id})
    if doc is None:
        return None
    record = ActionRecord.model_validate(doc)

    if not approve:
        status = ActionStatus.REJECTED
        reason = note or f"rejected by {approved_by}"
        effect = PolicyEffect.DENY
    else:
        case_state = await _case_context(context, record.caseId)
        decision = context.policy.evaluate_action(
            record.type,
            {
                "caseDecision": case_state["caseDecision"],
                "evidenceTypes": case_state["evidenceTypes"],
                "approvedBy": approved_by,
                **record.payload,
            },
        )
        await log_policy_decision(context, case_id=record.caseId, subject=approved_by, decision=decision)
        effect = decision.effect
        reason = decision.reason
        status = ActionStatus.EXECUTED if decision.allowed else ActionStatus.BLOCKED

    audit = list(record.audit)
    audit.append(
        {
            "at": utcnow().isoformat().replace("+00:00", "Z"),
            "by": approved_by,
            "event": "approved" if approve else "rejected",
            "policyEffect": effect.value,
            "reason": reason,
            **({"note": note} if note else {}),
        }
    )
    updated = await context.store.update_one(
        ACTIONS,
        {"_id": action_id},
        {
            "status": status.value,
            "approvedBy": approved_by if approve else None,
            "reason": reason,
            "policyEffect": effect.value,
            "audit": audit,
            "updatedAt": utcnow().isoformat().replace("+00:00", "Z"),
        },
    )
    return ActionRecord.model_validate(updated) if updated else None


# --------------------------------------------------------------------------- #
# Targeted worker alerts
# --------------------------------------------------------------------------- #


async def send_worker_alert(
    context: AgentContext,
    *,
    case_id: str,
    worker_alias: str,
    tier: AlertTier,
    zone_id: str | None,
    evidence_ids: list[str],
    message: str | None = None,
) -> Notification | None:
    """Deliver a narrowly targeted local alert to one worker, policy permitting."""
    decision = context.policy.evaluate_action(
        "send_worker_alert", {"tier": tier.value, "caseDecision": None}
    )
    await log_policy_decision(context, case_id=case_id, subject=worker_alias, decision=decision)
    if not decision.allowed:
        logger.warning("worker alert to %s blocked: %s", worker_alias, decision.reason)
        return None

    zone_text = f"zone {zone_id}" if zone_id else "the lift area"
    text = message or _TIER_MESSAGES[tier].format(zone=zone_text)

    # Do not re-alert the same worker at the same tier while an alert is outstanding.
    outstanding = await context.store.find_one(
        NOTIFICATIONS,
        {
            "caseId": case_id,
            "workerAlias": worker_alias,
            "tier": tier.value,
            "status": NotificationStatus.SENT.value,
        },
    )
    if outstanding is not None:
        return Notification.model_validate(outstanding)

    notification = Notification(
        caseId=case_id,
        workerAlias=worker_alias,
        tier=tier,
        message=text,
        zoneId=zone_id,
        reasonEvidenceIds=evidence_ids,
        requiresAck=tier in {AlertTier.STOP_ACK_REQUIRED, AlertTier.ESCALATE},
        ackDeadlineSeconds=_ACK_DEADLINE_SECONDS
        if tier in {AlertTier.STOP_ACK_REQUIRED, AlertTier.ESCALATE}
        else None,
    )
    await context.store.insert_one(NOTIFICATIONS, notification.to_doc())
    return notification


async def acknowledge(
    context: AgentContext, *, worker_alias: str, notification_id: str | None = None
) -> Notification | None:
    query: dict[str, Any] = {"workerAlias": worker_alias, "status": NotificationStatus.SENT.value}
    if notification_id:
        query = {"_id": notification_id}
    doc = await context.store.update_one(
        NOTIFICATIONS,
        query,
        {
            "status": NotificationStatus.ACKNOWLEDGED.value,
            "acknowledgedAt": utcnow().isoformat().replace("+00:00", "Z"),
        },
    )
    return Notification.model_validate(doc) if doc else None


async def unacknowledged_alerts(context: AgentContext, case_id: str) -> list[Notification]:
    docs = await context.store.find(
        NOTIFICATIONS,
        {"caseId": case_id, "status": NotificationStatus.SENT.value, "requiresAck": True},
        sort=[("sentAt", 1)],
    )
    return [Notification.model_validate(doc) for doc in docs]


def tier_for(relation: str, *, lift_active: bool, decision: str) -> AlertTier | None:
    """Map a resolved worker-zone relation to an alert tier (spec section 4.4)."""
    if decision == "ESCALATE" and relation in {"inside_risk_zone", "approaching", "coverage_unknown"}:
        return AlertTier.ESCALATE
    if relation == "inside_risk_zone":
        return AlertTier.STOP_ACK_REQUIRED if lift_active else AlertTier.CAUTION
    if relation == "approaching" and lift_active:
        return AlertTier.CAUTION
    return None


async def evidence_for_alert(context: AgentContext, case_id: str, limit: int = 3) -> list[str]:
    docs = await context.store.find(
        EVIDENCE,
        {"caseId": case_id, "severity": {"$in": ["critical", "high"]}},
        sort=[("timestamp", -1)],
        limit=limit,
    )
    return [Evidence.model_validate(doc).id for doc in docs]
