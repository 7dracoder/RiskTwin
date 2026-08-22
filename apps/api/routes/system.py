"""Health, stack disclosure and the local-only inference proof."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from packages.config import is_local_endpoint

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    state = request.app.state.risktwin
    storage = await state.store.health()
    return {
        "ok": bool(storage.get("ok")),
        "caseId": state.settings.case_id,
        "storage": storage,
        "degradedMode": state.models.degraded,
    }


@router.get("/system")
async def system(request: Request) -> dict[str, Any]:
    """Everything the dashboard header and the judge-facing panels need."""
    state = request.app.state.risktwin
    return await state.system_snapshot()


@router.get("/system/inference-check")
async def inference_check(request: Request) -> dict[str, Any]:
    """Confirm no configured model endpoint resolves off this host or LAN."""
    state = request.app.state.risktwin
    settings = state.settings
    results = []
    for label, url in settings.inference_endpoints().items():
        ok, detail = is_local_endpoint(url)
        results.append({"modality": label, "endpoint": url, "local": ok, "detail": detail})
    if not results:
        results.append(
            {
                "modality": "all",
                "endpoint": None,
                "local": True,
                "detail": "no network inference endpoints configured; deterministic local adapters only",
            }
        )
    return {
        "allLocal": all(item["local"] for item in results),
        "allowRemoteInference": settings.allow_remote_inference,
        "endpoints": results,
        "models": state.models.model_refs(),
    }
