"""Start and inspect the local COLMAP video reconstruction."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api/reconstruction", tags=["reconstruction"])


@router.get("/status")
async def status(request: Request) -> dict[str, Any]:
    return request.app.state.risktwin.reconstruction.status()


@router.post("/start", status_code=202)
async def start(request: Request, video: str | None = None) -> dict[str, Any]:
    try:
        return await request.app.state.risktwin.reconstruction.start(video)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/points")
async def points(
    request: Request, limit: int = Query(default=8000, ge=100, le=20000)
) -> dict[str, Any]:
    return request.app.state.risktwin.reconstruction.point_cloud(limit)
