"""Action proposal, human approval and the targeted-alert acknowledgement path."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from agents import policy_gate
from packages.contracts import (
    AcknowledgeRequest,
    ActionRequest,
    ActionStatus,
    ApprovalRequest,
)
from packages.storage.base import ACTIONS, NOTIFICATIONS, POLICY_LOG

router = APIRouter(prefix="/api", tags=["actions"])


@router.post("/cases/{case_id}/actions")
async def propose_action(case_id: str, payload: ActionRequest, request: Request) -> dict[str, Any]:
    """Propose an action. Unsafe requests return the blocked contract from spec section 10."""
    state = request.app.state.risktwin
    record = await policy_gate.propose_action(
        state.context,
        case_id=case_id,
        action_type=payload.type,
        requested_by=payload.requestedBy,
        payload=payload.payload,
    )
    body: dict[str, Any] = {
        "actionId": record.id,
        "status": record.status.value,
        "reason": record.reason,
        "policyEvidence": record.policyEvidence,
        "requiresApproval": record.requiresApproval,
    }
    if record.status is ActionStatus.BLOCKED:
        body["status"] = "BLOCKED"
    return body


@router.get("/cases/{case_id}/actions")
async def list_actions(case_id: str, request: Request) -> list[dict[str, Any]]:
    state = request.app.state.risktwin
    return await state.store.find(ACTIONS, {"caseId": case_id}, sort=[("createdAt", -1)])


@router.post("/actions/{action_id}/approval")
async def approve_action(
    action_id: str, payload: ApprovalRequest, request: Request
) -> dict[str, Any]:
    """A named human approver decides. Policy is re-checked at approval time."""
    state = request.app.state.risktwin
    record = await policy_gate.decide_approval(
        state.context,
        action_id=action_id,
        approved_by=payload.approvedBy,
        approve=payload.approve,
        note=payload.note,
    )
    if record is None:
        raise HTTPException(status_code=404, detail=f"action {action_id} not found")
    return record.to_doc()


@router.get("/notifications")
async def list_notifications(
    request: Request,
    workerAlias: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, Any]]:
    state = request.app.state.risktwin
    query: dict[str, Any] = {}
    if workerAlias:
        query["workerAlias"] = workerAlias
    return await state.store.find(NOTIFICATIONS, query, sort=[("sentAt", -1)], limit=limit)


@router.post("/notifications/ack")
async def acknowledge(payload: AcknowledgeRequest, request: Request) -> dict[str, Any]:
    """Worker acknowledgement, durably recorded and visible on the controller dashboard."""
    state = request.app.state.risktwin
    record = await policy_gate.acknowledge(
        state.context,
        worker_alias=payload.workerAlias,
        notification_id=payload.notificationId,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="no outstanding alert to acknowledge")
    return record.to_doc()


@router.get("/policy/log")
async def policy_log(
    request: Request, limit: int = Query(default=100, ge=1, le=500)
) -> list[dict[str, Any]]:
    """The OpenShell decision trail — the judge-facing proof point."""
    state = request.app.state.risktwin
    return await state.store.find(POLICY_LOG, sort=[("timestamp", -1)], limit=limit)
