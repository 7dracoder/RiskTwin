"""OpenShell policy, targeted alerts and acknowledgement (spec sections 6.1, 10, 14)."""

from __future__ import annotations

from pathlib import Path

from httpx import AsyncClient

from tests.helpers import CASE_ID, activate_lift, baseline, case as read_case, settle, worker


async def test_lift_clearance_is_blocked_while_the_case_is_escalate(
    client: AsyncClient,
) -> None:
    response = await client.post(
        f"/api/cases/{CASE_ID}/actions",
        json={"type": "issue_lift_clearance", "requestedBy": "site-controller"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "BLOCKED"
    assert "HOLD" in body["reason"] or "ESCALATE" in body["reason"]
    assert body["policyEvidence"] is not None


async def test_equipment_command_is_always_denied(client: AsyncClient) -> None:
    response = await client.post(
        f"/api/cases/{CASE_ID}/actions",
        json={"type": "equipment_command", "requestedBy": "site-controller"},
    )
    body = response.json()
    assert body["status"] == "BLOCKED"
    assert "never commands" in body["reason"].lower() or "crane" in body["reason"].lower()


async def test_raw_media_export_is_refused_and_logged(client: AsyncClient) -> None:
    response = await client.get("/api/media/raw/walkthrough.mp4")
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["status"] == "BLOCKED"

    log = (await client.get("/api/policy/log")).json()
    assert any(row["actionType"] == "export_raw_video" and row["effect"] == "deny" for row in log)


async def test_clearance_awaits_named_human_when_conditions_are_safe(
    client: AsyncClient, documents: Path
) -> None:
    await baseline(client)
    await client.post(f"/api/cases/{CASE_ID}/documents/import")
    await settle(client)
    assert (await read_case(client))["decision"] == "CONDITIONAL_APPROVAL"

    proposed = (
        await client.post(
            f"/api/cases/{CASE_ID}/actions",
            json={"type": "issue_lift_clearance", "requestedBy": "site-controller"},
        )
    ).json()
    assert proposed["status"] == "AWAITING_APPROVAL"
    assert proposed["requiresApproval"] is True

    action_id = proposed["actionId"]
    approved = (
        await client.post(
            f"/api/actions/{action_id}/approval",
            json={"approvedBy": "site-manager-01", "approve": True},
        )
    ).json()
    assert approved["status"] == "EXECUTED"
    assert approved["approvedBy"] == "site-manager-01"


async def test_worker_alert_acknowledgement_is_durable(
    client: AsyncClient, documents: Path
) -> None:
    await baseline(client)
    await client.post(f"/api/cases/{CASE_ID}/documents/import")
    await activate_lift(client)
    await worker(client, "worker-12", "C")

    alerts = (await client.get("/api/notifications", params={"workerAlias": "worker-12"})).json()
    assert alerts
    outstanding = next(item for item in alerts if item["status"] == "SENT")
    assert outstanding["requiresAck"] is True

    acked = (
        await client.post(
            "/api/notifications/ack",
            json={"workerAlias": "worker-12", "notificationId": outstanding["_id"]},
        )
    ).json()
    assert acked["status"] == "ACKNOWLEDGED"
    assert acked["acknowledgedAt"]

    stored = (await client.get("/api/notifications", params={"workerAlias": "worker-12"})).json()
    assert stored[0]["status"] == "ACKNOWLEDGED"


async def test_stale_critical_source_escalates(
    client: AsyncClient, documents: Path
) -> None:
    await baseline(client)
    await client.post(f"/api/cases/{CASE_ID}/documents/import")
    await settle(client)
    assert (await read_case(client))["decision"] == "CONDITIONAL_APPROVAL"

    await client.app_state.orchestrator._record_event(  # type: ignore[attr-defined]
        case_id=CASE_ID,
        event_type="source_freshness",
        source="recorded-replay",
        source_id="floor-gateway-f12",
        payload={"slaSeconds": 45, "reportedBy": "test"},
        is_simulated=True,
    )
    await settle(client)

    case = await read_case(client)
    assert case["decision"] == "ESCALATE"
    assert any("floor-gateway-f12" in reason or "Floor 12" in reason for reason in case["reasons"])
