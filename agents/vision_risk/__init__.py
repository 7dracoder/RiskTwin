"""Vision Risk Agent — sampled frames to zone-attributed evidence.

Runs on a new walkthrough, a risk-state change or a manager request, never
continuously on every camera frame (spec section 9.4). When no video is available
it writes an explicit "evidence missing" record, which escalates the case rather
than inventing a scene finding.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.base import AgentContext, write_evidence
from packages.contracts import EvidenceType, RedactionManifest, Severity, SiteModel
from packages.media import discover_videos, redact_video, sample_frames
from packages.storage.base import REDACTION_MANIFEST

logger = logging.getLogger(__name__)

AGENT_NAME = "vision-risk"

_RISK_SEVERITY = {
    "person_in_exclusion_zone": Severity.CRITICAL,
    "zone_obstruction": Severity.HIGH,
    "load_path_conflict": Severity.HIGH,
    "route_obstruction": Severity.MEDIUM,
    "housekeeping": Severity.LOW,
    "none": Severity.INFO,
}


def _zone_regions(site_model: SiteModel | None, meta: dict[str, Any]) -> list[dict[str, Any]]:
    """Combine the operator's frame-to-zone mapping with zone kinds from the site model."""
    kinds = {zone.zoneId: zone.kind for zone in (site_model.zones if site_model else [])}
    regions: list[dict[str, Any]] = []
    for region in meta.get("regions") or []:
        zone_id = region.get("zoneId")
        regions.append(
            {
                "zoneId": zone_id,
                "box": region.get("box"),
                "zoneKind": kinds.get(zone_id),
                "risk": kinds.get(zone_id) == "lift-exclusion",
            }
        )
    return regions


async def run(
    context: AgentContext,
    *,
    case_id: str,
    site_model: SiteModel | None,
    cue: dict[str, Any] | None = None,
    redact: bool = True,
) -> list[str]:
    settings = context.settings
    videos = discover_videos(settings.path(settings.raw_video_dir))

    if not videos:
        record = await write_evidence(
            context,
            case_id=case_id,
            agent=AGENT_NAME,
            evidence_type=EvidenceType.VIDEO_OBSERVATION,
            finding=(
                "No site walkthrough or camera footage is present in data/raw/video, so no "
                "visual evidence can be produced for the lift area."
            ),
            confidence=1.0,
            severity=Severity.HIGH,
            source_refs=["asset:missing"],
            detail={"available": False, "zoneId": (cue or {}).get("zoneId")},
            model_ref=context.models.vision.info.label,
        )
        return [record.id]

    asset = videos[0]
    meta = dict(asset.meta)
    if cue and cue.get("zoneId") and not meta.get("regions") and not meta.get("defaultZoneId"):
        # A cue names the zone under review; without a frame mapping the finding
        # still cannot claim a region, so record the cue and let confidence drop.
        meta["defaultZoneId"] = cue["zoneId"]

    frames = sample_frames(
        asset.path, settings.frame_sample_count, settings.path(settings.frame_dir)
    )
    if not frames:
        record = await write_evidence(
            context,
            case_id=case_id,
            agent=AGENT_NAME,
            evidence_type=EvidenceType.VIDEO_OBSERVATION,
            finding=f"{asset.name} could not be decoded into frames; visual evidence is unavailable.",
            confidence=1.0,
            severity=Severity.HIGH,
            source_refs=[f"asset:{asset.name}"],
            detail={"available": False},
            model_ref=context.models.vision.info.label,
        )
        return [record.id]

    regions = _zone_regions(site_model, meta)
    observations = await context.models.vision.observe(frames, {**meta, "regions": regions})

    written: list[str] = []
    if not observations:
        record = await write_evidence(
            context,
            case_id=case_id,
            agent=AGENT_NAME,
            evidence_type=EvidenceType.VIDEO_OBSERVATION,
            finding=(
                f"{len(frames)} frames sampled from {asset.name}; no obstruction, person or "
                "load-path conflict was detected in the mapped zones."
            ),
            confidence=0.6,
            severity=Severity.INFO,
            source_refs=[f"asset:{asset.name}"] + [frame.ref for frame in frames],
            detail={"available": True, "riskType": "none", "zoneId": None},
            model_generated=context.models.vision.info.backend != "deterministic",
            model_ref=context.models.vision.info.label,
        )
        written.append(record.id)

    for observation in observations:
        severity = _RISK_SEVERITY.get(observation.riskType, Severity.LOW)
        zone_text = f"zone {observation.zoneId}" if observation.zoneId else "an unmapped area"
        record = await write_evidence(
            context,
            case_id=case_id,
            agent=AGENT_NAME,
            evidence_type=EvidenceType.VIDEO_OBSERVATION,
            finding=(
                f"{observation.riskType.replace('_', ' ').capitalize()} affecting {zone_text}: "
                + "; ".join(observation.observations[:3])
            ),
            confidence=observation.confidence,
            severity=severity,
            source_refs=[f"asset:{asset.name}"] + observation.frameRefs,
            detail={
                "available": True,
                "zoneId": observation.zoneId,
                "riskType": observation.riskType,
                # Only a served VLM or a human may confirm a finding; the deterministic
                # detector reports candidates.
                "confirmed": observation.modelGenerated,
                "detector": observation.detector,
                "frameRefs": observation.frameRefs,
                **observation.detail,
            },
            model_generated=observation.modelGenerated,
            model_ref=context.models.vision.info.label,
        )
        written.append(record.id)

    if redact:
        try:
            await _write_redacted_evidence(context, case_id=case_id, asset=asset, regions=regions)
        except Exception:  # noqa: BLE001 - redaction failure must not block the decision
            logger.exception("redaction failed for %s", asset.name)

    return written


async def _write_redacted_evidence(
    context: AgentContext, *, case_id: str, asset: Any, regions: list[dict[str, Any]]
) -> RedactionManifest:
    settings = context.settings
    existing = await context.store.find_one(
        REDACTION_MANIFEST, {"caseId": case_id, "inputSha256": asset.checksum}
    )
    if existing:
        return RedactionManifest.model_validate(existing)

    output = settings.path(settings.redacted_dir) / f"{asset.path.stem}-redacted.mp4"
    result = redact_video(asset.path, output, regions=regions, banner=case_id)
    manifest = RedactionManifest(caseId=case_id, **result.to_manifest_fields())
    await context.store.insert_one(REDACTION_MANIFEST, manifest.to_doc())
    return manifest
