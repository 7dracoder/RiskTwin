"""Evidence media access, gated by OpenShell policy.

Only the redacted render is retrievable. A raw-video request is a live policy
proof point: it is refused and the refusal is logged (spec sections 5.1 and 8.2).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from agents.policy_gate import log_policy_decision
from packages.storage.base import REDACTION_MANIFEST

router = APIRouter(prefix="/api/media", tags=["media"])


@router.get("/redacted")
async def list_redacted(request: Request) -> list[dict[str, Any]]:
    state = request.app.state.risktwin
    manifests = await state.store.find(REDACTION_MANIFEST, sort=[("createdAt", -1)])
    return [
        {
            "name": manifest["outputPath"].rsplit("/", 1)[-1],
            "caseId": manifest["caseId"],
            "framesProcessed": manifest["framesProcessed"],
            "redactedRegions": manifest["redactedRegions"],
            "detectorVersion": manifest["detectorVersion"],
            "redactionMethod": manifest["redactionMethod"],
            "warnings": manifest.get("warnings", []),
            "outputSha256": manifest.get("outputSha256"),
        }
        for manifest in manifests
    ]


@router.get("/redacted/{name}")
async def get_redacted(name: str, request: Request) -> FileResponse:
    state = request.app.state.risktwin
    target = state.settings.path(state.settings.redacted_dir) / name
    decision = state.policy.evaluate_export(f"{state.settings.redacted_dir}/{name}")
    await log_policy_decision(
        state.context, case_id=state.settings.case_id, subject="dashboard", decision=decision
    )
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)
    if ".." in name or "/" in name or not target.exists():
        raise HTTPException(status_code=404, detail=f"redacted evidence {name} not found")
    return FileResponse(target, media_type="video/mp4", filename=name)


@router.get("/raw/{name}")
async def get_raw(name: str, request: Request) -> FileResponse:
    """Always refused. Kept as an endpoint so the refusal can be demonstrated."""
    state = request.app.state.risktwin
    decision = state.policy.evaluate_export(f"{state.settings.raw_video_dir}/{name}")
    await log_policy_decision(
        state.context, case_id=state.settings.case_id, subject="dashboard", decision=decision
    )
    raise HTTPException(
        status_code=403,
        detail={
            "status": "BLOCKED",
            "reason": decision.reason,
            "policyId": decision.policyId,
            "alternative": "Request the redacted evidence render instead.",
        },
    )


@router.get("/frames")
async def list_frames(request: Request) -> list[dict[str, Any]]:
    """Sampled frames the vision agent actually analysed."""
    state = request.app.state.risktwin
    frame_dir = state.settings.path(state.settings.frame_dir)
    if not frame_dir.exists():
        return []
    return [
        {"name": path.name, "sizeBytes": path.stat().st_size}
        for path in sorted(frame_dir.glob("*.jpg"))
    ]


@router.get("/frames/{name}")
async def get_frame(name: str, request: Request) -> FileResponse:
    state = request.app.state.risktwin
    if ".." in name or "/" in name:
        raise HTTPException(status_code=400, detail="invalid frame name")
    target = state.settings.path(state.settings.frame_dir) / name
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"frame {name} not found")
    return FileResponse(target, media_type="image/jpeg")
