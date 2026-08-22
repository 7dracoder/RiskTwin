"""Versioned local site model: the coordinate reference for workers and zones.

The model *interprets* a location; it never determines one. Locations arrive from
the worker PWA (named zones) or, in production, from approved site positioning
hardware via a local gateway (spec section 3).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packages.contracts import SiteModel, WorkerZoneRelation, utcnow
from packages.site_model.geometry import (
    distance_to_polygon,
    point_in_polygon,
    polygon_centroid,
)
from packages.storage.base import SITE_MODEL, Store

RISK_ZONE_KINDS = {"lift-exclusion"}


@dataclass(slots=True)
class ZoneResolution:
    zoneId: str | None
    zoneKind: str | None
    relation: WorkerZoneRelation
    distanceMeters: float | None
    siteModelId: str
    siteModelVersion: int
    detail: str


def load_site_model_file(path: Path) -> SiteModel:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.setdefault("_id", f"{payload['siteModelId']}:v{payload['version']}")
    asset = payload.get("asset") or {}
    local_path = asset.get("localPath")
    if local_path:
        candidate = Path(local_path)
        if candidate.exists():
            asset["sha256"] = hashlib.sha256(candidate.read_bytes()).hexdigest()
            payload["asset"] = asset
    return SiteModel.model_validate(payload)


async def seed_site_model(store: Store, path: Path) -> SiteModel:
    """Import the site model file and make it the active version if none is active."""
    model = load_site_model_file(path)
    existing_active = await store.find_one(SITE_MODEL, {"active": True})
    model.active = existing_active is None or existing_active.get("_id") == model.id
    model.updatedAt = utcnow()
    await store.upsert(SITE_MODEL, {"_id": model.id}, model.to_doc())
    return model


async def get_active_site_model(store: Store) -> SiteModel | None:
    doc = await store.find_one(SITE_MODEL, {"active": True})
    if doc is None:
        docs = await store.find(SITE_MODEL, sort=[("version", -1)], limit=1)
        doc = docs[0] if docs else None
    return SiteModel.model_validate(doc) if doc else None


async def activate_version(store: Store, site_model_id: str, version: int) -> SiteModel | None:
    """A new walkthrough never overwrites a model; the controller chooses the
    active version so the audit trail records which layout produced an alert."""
    target = await store.find_one(SITE_MODEL, {"siteModelId": site_model_id, "version": version})
    if target is None:
        return None
    for doc in await store.find(SITE_MODEL, {"siteModelId": site_model_id}):
        await store.update_one(
            SITE_MODEL, {"_id": doc["_id"]}, {"active": doc["_id"] == target["_id"]}
        )
    refreshed = await store.find_one(SITE_MODEL, {"_id": target["_id"]})
    return SiteModel.model_validate(refreshed) if refreshed else None


def resolve_zone(
    model: SiteModel,
    *,
    zone_id: str | None = None,
    floor_id: str | None = None,
    x: float | None = None,
    y: float | None = None,
) -> ZoneResolution:
    """Resolve a reported position to a named zone and a geometric relation.

    Two input styles are supported, matching spec section 4.3: a named zone from
    the worker PWA, or floor-plus-coordinates from a positioning gateway.
    """
    if zone_id:
        zone = next((z for z in model.zones if z.zoneId == zone_id), None)
        if zone is None:
            return ZoneResolution(
                zoneId=zone_id,
                zoneKind=None,
                relation=WorkerZoneRelation.COVERAGE_UNKNOWN,
                distanceMeters=None,
                siteModelId=model.siteModelId,
                siteModelVersion=model.version,
                detail=f"zone {zone_id!r} is not present in {model.siteModelId} v{model.version}",
            )
        inside_risk = zone.kind in RISK_ZONE_KINDS
        return ZoneResolution(
            zoneId=zone.zoneId,
            zoneKind=zone.kind,
            relation=(
                WorkerZoneRelation.INSIDE_RISK_ZONE if inside_risk else WorkerZoneRelation.SAFE
            ),
            distanceMeters=0.0,
            siteModelId=model.siteModelId,
            siteModelVersion=model.version,
            detail=f"reported zone {zone.zoneId} ({zone.kind})",
        )

    if x is None or y is None:
        return ZoneResolution(
            zoneId=None,
            zoneKind=None,
            relation=WorkerZoneRelation.COVERAGE_UNKNOWN,
            distanceMeters=None,
            siteModelId=model.siteModelId,
            siteModelVersion=model.version,
            detail="no zone and no coordinates supplied",
        )

    candidates = [z for z in model.zones if floor_id is None or z.floorId == floor_id]
    if not candidates:
        return ZoneResolution(
            zoneId=None,
            zoneKind=None,
            relation=WorkerZoneRelation.COVERAGE_UNKNOWN,
            distanceMeters=None,
            siteModelId=model.siteModelId,
            siteModelVersion=model.version,
            detail=f"no mapped zones on floor {floor_id!r}",
        )

    point = (x, y)
    containing = next((z for z in candidates if point_in_polygon(point, z.polygon)), None)
    risk_zones = [z for z in candidates if z.kind in RISK_ZONE_KINDS]
    nearest_risk = min(
        ((z, distance_to_polygon(point, z.polygon)) for z in risk_zones),
        key=lambda pair: pair[1],
        default=(None, None),
    )

    if containing is not None and containing.kind in RISK_ZONE_KINDS:
        return ZoneResolution(
            zoneId=containing.zoneId,
            zoneKind=containing.kind,
            relation=WorkerZoneRelation.INSIDE_RISK_ZONE,
            distanceMeters=0.0,
            siteModelId=model.siteModelId,
            siteModelVersion=model.version,
            detail=f"({x:.1f}, {y:.1f}) is inside zone {containing.zoneId}",
        )

    zone, distance = nearest_risk
    if zone is not None and distance is not None and distance <= zone.approachBufferMeters:
        return ZoneResolution(
            zoneId=containing.zoneId if containing else zone.zoneId,
            zoneKind=containing.kind if containing else zone.kind,
            relation=WorkerZoneRelation.APPROACHING,
            distanceMeters=round(distance, 2),
            siteModelId=model.siteModelId,
            siteModelVersion=model.version,
            detail=f"{distance:.1f} m from exclusion zone {zone.zoneId} boundary",
        )

    return ZoneResolution(
        zoneId=containing.zoneId if containing else None,
        zoneKind=containing.kind if containing else None,
        relation=WorkerZoneRelation.SAFE if containing else WorkerZoneRelation.COVERAGE_UNKNOWN,
        distanceMeters=round(distance, 2) if distance is not None else None,
        siteModelId=model.siteModelId,
        siteModelVersion=model.version,
        detail=(
            f"({x:.1f}, {y:.1f}) is inside zone {containing.zoneId}"
            if containing
            else f"({x:.1f}, {y:.1f}) is outside every mapped zone"
        ),
    )


def zone_summary(model: SiteModel) -> list[dict[str, Any]]:
    """Map payload for the dashboard: zones plus their centroids."""
    return [
        {
            "zoneId": zone.zoneId,
            "floorId": zone.floorId,
            "kind": zone.kind,
            "label": zone.label,
            "polygon": zone.polygon,
            "centroid": polygon_centroid(zone.polygon),
            "approachBufferMeters": zone.approachBufferMeters,
        }
        for zone in model.zones
    ]


__all__ = [
    "RISK_ZONE_KINDS",
    "ZoneResolution",
    "activate_version",
    "get_active_site_model",
    "load_site_model_file",
    "resolve_zone",
    "seed_site_model",
    "zone_summary",
]
