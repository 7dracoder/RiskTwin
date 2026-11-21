"""Latest site sensors and explicit local simulation presets."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from packages.storage.base import TELEMETRY

router = APIRouter(prefix="/api/sensors", tags=["sensors"])


class ScenarioRequest(BaseModel):
    scenario: str = "baseline"


SCENARIOS: dict[str, list[tuple[str, float, str]]] = {
    "baseline": [
        ("carbon_monoxide_ppm", 3, "ppm"),
        ("oxygen_percent", 20.9, "%"),
        ("noise_dba", 72, "dBA"),
        ("dust_pm25_ug_m3", 18, "µg/m³"),
        ("ambient_temperature_c", 27, "°C"),
        ("structural_tilt_deg", 0.2, "°"),
        ("vibration_mm_s", 1.1, "mm/s"),
        ("worker_plant_distance_m", 5.5, "m"),
    ],
    "multi-risk": [
        ("carbon_monoxide_ppm", 48, "ppm"),
        ("oxygen_percent", 18.7, "%"),
        ("noise_dba", 94, "dBA"),
        ("dust_pm25_ug_m3", 61, "µg/m³"),
        ("ambient_temperature_c", 41, "°C"),
        ("structural_tilt_deg", 2.7, "°"),
        ("vibration_mm_s", 7.2, "mm/s"),
        ("worker_plant_distance_m", 1.1, "m"),
    ],
}


@router.get("/latest")
async def latest(request: Request) -> list[dict[str, Any]]:
    state = request.app.state.risktwin
    docs = await state.store.find(
        TELEMETRY, {"caseId": state.settings.case_id}, sort=[("timestamp", 1)]
    )
    by_kind: dict[str, dict[str, Any]] = {}
    for doc in docs:
        by_kind[doc["kind"]] = doc
    return sorted(by_kind.values(), key=lambda doc: doc["kind"])


@router.post("/simulate", status_code=202)
async def simulate(payload: ScenarioRequest, request: Request) -> dict[str, Any]:
    if payload.scenario not in SCENARIOS:
        raise HTTPException(status_code=400, detail="scenario must be baseline or multi-risk")
    state = request.app.state.risktwin
    ids: list[str] = []
    for kind, value, unit in SCENARIOS[payload.scenario]:
        _, reading = await state.orchestrator.ingest_telemetry(
            case_id=state.settings.case_id,
            kind=kind,
            value=value,
            unit=unit,
            source="site-sensor-simulator",
            source_id="site-sensor-simulator",
            is_simulated=True,
        )
        ids.append(reading.id)
    return {"accepted": True, "scenario": payload.scenario, "readings": ids, "isSimulated": True}
