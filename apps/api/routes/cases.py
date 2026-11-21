"""Case, evidence, timeline and agent-run views for the controller dashboard."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from packages import ingest
from packages.contracts import Case, Evidence
from packages.site_model import get_active_site_model, zone_summary
from packages.storage.base import (
    AGENT_RUNS,
    CASES,
    EVIDENCE,
    NOTIFICATIONS,
    REDACTION_MANIFEST,
    SITE_EVENTS,
    SITE_MODEL,
    SOURCE_MANIFEST,
    WORKER_POSITIONS,
)

router = APIRouter(prefix="/api", tags=["cases"])


@router.get("/cases")
async def list_cases(request: Request) -> list[dict[str, Any]]:
    state = request.app.state.risktwin
    return await state.store.find(CASES, sort=[("updatedAt", -1)])


@router.get("/cases/{case_id}")
async def get_case(case_id: str, request: Request) -> dict[str, Any]:
    """The contract from spec section 10, plus the state the dashboard renders."""
    state = request.app.state.risktwin
    doc = await state.store.find_one(CASES, {"caseId": case_id})
    if doc is None:
        raise HTTPException(status_code=404, detail=f"case {case_id} not found")
    case = Case.model_validate(doc)
    evidence_docs = await state.store.find(
        EVIDENCE, {"caseId": case_id}, sort=[("timestamp", -1)]
    )
    return {
        "caseId": case.caseId,
        "decision": case.decision.value,
        "reasons": case.reasons,
        "evidence": case.latestEvidenceIds,
        "requiredBeforeApproval": case.requiredBeforeApproval,
        "confidence": case.confidence,
        "narrative": case.narrative,
        "liftActive": case.liftActive,
        "degradedMode": case.degradedMode,
        "recoveredFromStore": case.recoveredFromStore,
        "siteModelId": case.siteModelId,
        "siteModelVersion": case.siteModelVersion,
        "evidenceCount": len(evidence_docs),
        "updatedAt": case.updatedAt.isoformat().replace("+00:00", "Z"),
    }


@router.get("/cases/{case_id}/evidence")
async def list_evidence(
    case_id: str,
    request: Request,
    limit: int = Query(default=200, ge=1, le=1000),
    evidence_type: str | None = Query(default=None, alias="type"),
) -> list[dict[str, Any]]:
    state = request.app.state.risktwin
    query: dict[str, Any] = {"caseId": case_id}
    if evidence_type:
        query["evidenceType"] = evidence_type
    return await state.store.find(
        EVIDENCE, query, sort=[("timestamp", -1)], limit=limit
    )


@router.get("/cases/{case_id}/timeline")
async def timeline(
    case_id: str,
    request: Request,
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[dict[str, Any]]:
    """The forensic event stream, newest first."""
    state = request.app.state.risktwin
    return await state.store.find(
        SITE_EVENTS, {"caseId": case_id}, sort=[("timestamp", -1)], limit=limit
    )


@router.get("/cases/{case_id}/agents")
async def agent_runs(
    case_id: str,
    request: Request,
    limit: int = Query(default=60, ge=1, le=500),
) -> list[dict[str, Any]]:
    state = request.app.state.risktwin
    return await state.store.find(
        AGENT_RUNS, {"caseId": case_id}, sort=[("startedAt", -1)], limit=limit
    )


@router.get("/cases/{case_id}/redaction")
async def redaction_manifests(case_id: str, request: Request) -> list[dict[str, Any]]:
    state = request.app.state.risktwin
    return await state.store.find(
        REDACTION_MANIFEST, {"caseId": case_id}, sort=[("createdAt", -1)]
    )


@router.post("/cases/{case_id}/review")
async def manual_review(case_id: str, request: Request) -> dict[str, Any]:
    """Run the media specialists on demand, as a site manager request would."""
    state = request.app.state.risktwin
    verdict = await state.orchestrator.run_manual_review(case_id)
    if verdict is None:
        raise HTTPException(status_code=409, detail="review produced no decision")
    return verdict.to_doc()


@router.post("/cases/{case_id}/redecide")
async def redecide(case_id: str, request: Request) -> dict[str, Any]:
    """Re-retrieve rules and re-evaluate. Used after importing documents."""
    state = request.app.state.risktwin
    verdict = await state.orchestrator.redecide(case_id)
    return verdict.to_doc()


@router.post("/cases/{case_id}/documents/import")
async def import_documents(case_id: str, request: Request) -> dict[str, Any]:
    """Index the cleared documents, then re-decide.

    This is the "retrieval changes behaviour" proof: before the import there is no
    applicable rule and the case can only ESCALATE; afterwards the exact retrieved
    limits govern the decision (spec section 7.5).
    """
    state = request.app.state.risktwin
    report = await ingest.import_documents(state.store, state.settings)
    verdict = await state.orchestrator.redecide(case_id)
    return {"import": report.as_dict(), "decision": verdict.to_doc()}


@router.post("/cases/{case_id}/reset")
async def reset_case(case_id: str, request: Request) -> dict[str, Any]:
    """Clear case activity and rewind the replay for another demo run."""
    state = request.app.state.risktwin
    await state.replay.reset(case_id)
    removed = await ingest.reset_case(state.store, case_id)
    state.orchestrator.invalidate_rules()
    return {"caseId": case_id, "removed": removed}


@router.get("/site-model")
async def site_model(request: Request) -> dict[str, Any]:
    state = request.app.state.risktwin
    model = await get_active_site_model(state.store)
    if model is None:
        raise HTTPException(status_code=404, detail="no site model has been seeded")
    versions = await state.store.find(SITE_MODEL, sort=[("version", -1)])
    return {
        "siteModelId": model.siteModelId,
        "version": model.version,
        "coordinateFrame": model.coordinateFrame.model_dump(),
        "floors": [floor.model_dump() for floor in model.floors],
        "zones": zone_summary(model),
        "hazards": model.hazards,
        "availableVersions": [
            {"siteModelId": doc["siteModelId"], "version": doc["version"], "active": doc.get("active", False)}
            for doc in versions
        ],
    }


@router.get("/sources")
async def sources(request: Request) -> list[dict[str, Any]]:
    """Provenance and freshness per approved source (spec section 4.2)."""
    state = request.app.state.risktwin
    return await state.store.find(SOURCE_MANIFEST, sort=[("sourceId", 1)])


@router.get("/workers")
async def workers(request: Request) -> list[dict[str, Any]]:
    """Latest reported position per worker alias, for the site map."""
    state = request.app.state.risktwin
    docs = await state.store.find(
        WORKER_POSITIONS,
        {"caseId": state.settings.case_id},
        sort=[("timestamp", 1)],
    )
    latest: dict[str, dict[str, Any]] = {}
    for doc in docs:
        latest[doc["workerAlias"]] = doc
    return sorted(latest.values(), key=lambda doc: doc["workerAlias"])


@router.get("/workers/{worker_alias}/status")
async def worker_status(worker_alias: str, request: Request) -> dict[str, Any]:
    """What the worker page needs: my zone, my alerts, the current case decision."""
    state = request.app.state.risktwin
    case_id = state.settings.case_id
    case_doc = await state.store.find_one(CASES, {"caseId": case_id})
    positions = await state.store.find(
        WORKER_POSITIONS,
        {"caseId": case_id, "workerAlias": worker_alias},
        sort=[("timestamp", -1)],
        limit=1,
    )
    notifications = await state.store.find(
        NOTIFICATIONS,
        {"caseId": case_id, "workerAlias": worker_alias},
        sort=[("sentAt", -1)],
        limit=10,
    )
    evidence = await state.store.find(
        EVIDENCE,
        {"caseId": case_id, "severity": {"$in": ["critical", "high"]}},
        sort=[("timestamp", -1)],
        limit=3,
    )
    return {
        "caseId": case_id,
        "workerAlias": worker_alias,
        "decision": (case_doc or {}).get("decision"),
        "liftActive": (case_doc or {}).get("liftActive", False),
        "position": positions[0] if positions else None,
        "notifications": notifications,
        "topEvidence": [Evidence.model_validate(doc).finding for doc in evidence],
    }
