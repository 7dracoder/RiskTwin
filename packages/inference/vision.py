"""Local vision: sampled frames in, structured zone observations out.

Never raw video, never a remote URL (spec section 9.4). The served VLM path asks
for strict JSON containing `zoneId`, `observations`, `riskType`, `confidence` and
`frameRefs`; if it cannot answer, the deterministic OpenCV path runs instead and
the result is labelled accordingly.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from packages.config import Settings
from packages.inference.base import ModelRef, local_client, parse_json_response
from packages.media.cv_observer import DETECTOR_VERSION, analyse_frames
from packages.media.frames import FrameRef

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a construction site safety vision analyst. You are shown one sampled "
    "still frame from a site walkthrough. Report only what is visible. Never guess a "
    "zone that was not supplied to you. Reply with JSON only."
)

_RISK_TYPES = (
    "zone_obstruction",
    "person_in_exclusion_zone",
    "route_obstruction",
    "load_path_conflict",
    "housekeeping",
    "ppe_noncompliance",
    "unsafe_edge_or_opening",
    "fire_or_smoke",
    "spill_or_leak",
    "vehicle_person_conflict",
    "electrical_hazard",
    "unstable_materials",
    "blocked_egress",
    "poor_visibility",
    "structural_damage",
    "none",
)


@dataclass(slots=True)
class VisionObservation:
    zoneId: str | None
    observations: list[str]
    riskType: str
    confidence: float
    frameRefs: list[str]
    modelGenerated: bool
    detector: str
    detail: dict[str, Any] = field(default_factory=dict)


class VisionModel(Protocol):
    info: ModelRef

    async def observe(
        self, frames: list[FrameRef], meta: dict[str, Any] | None = None
    ) -> list[VisionObservation]: ...

    async def close(self) -> None: ...


def _risk_type_for(kinds: set[str], zone_kind: str | None) -> str:
    if "person_activity" in kinds and zone_kind == "lift-exclusion":
        return "person_in_exclusion_zone"
    if "candidate_obstruction" in kinds:
        return "zone_obstruction" if zone_kind == "lift-exclusion" else "route_obstruction"
    if "candidate_fire_or_hot_work" in kinds or "candidate_smoke_or_dust" in kinds:
        return "fire_or_smoke"
    if "candidate_low_visibility" in kinds:
        return "poor_visibility"
    return "housekeeping"


class DeterministicVisionModel:
    """Local OpenCV event extraction. The claim stays narrow: local visual event
    extraction feeding agentic reasoning, not a model that watched the video."""

    def __init__(self) -> None:
        self.info = ModelRef(
            modality="vision",
            backend="deterministic",
            model=DETECTOR_VERSION,
            degraded=True,
            note=(
                "No VLM is served on this host. Findings come from local OpenCV "
                "change detection plus the built-in pedestrian detector, and are "
                "reported as candidates requiring human confirmation."
            ),
        )

    async def observe(
        self, frames: list[FrameRef], meta: dict[str, Any] | None = None
    ) -> list[VisionObservation]:
        meta = meta or {}
        raw = analyse_frames(frames, meta)
        if not raw:
            return []

        zone_kinds: dict[str, str] = {
            region.get("zoneId"): region.get("zoneKind")
            for region in (meta.get("regions") or [])
            if region.get("zoneId")
        }

        grouped: dict[tuple[str | None, str], list[Any]] = {}
        for observation in raw:
            category = (
                "fire-or-smoke"
                if observation.kind in {"candidate_fire_or_hot_work", "candidate_smoke_or_dust"}
                else "visibility"
                if observation.kind == "candidate_low_visibility"
                else "person-or-obstruction"
            )
            grouped.setdefault((observation.zoneId, category), []).append(observation)

        results: list[VisionObservation] = []
        for (zone_id, _category), items in grouped.items():
            kinds = {item.kind for item in items}
            best = max(item.confidence for item in items)
            results.append(
                VisionObservation(
                    zoneId=zone_id,
                    observations=sorted({f"{item.kind}: {item.note}" for item in items}),
                    riskType=_risk_type_for(kinds, zone_kinds.get(zone_id or "")),
                    confidence=best,
                    frameRefs=sorted({item.frameRef for item in items}),
                    modelGenerated=False,
                    detector=DETECTOR_VERSION,
                    detail={"regions": [item.to_detail() for item in items]},
                )
            )
        return results

    async def close(self) -> None:
        return None


class OpenAICompatVisionModel:
    """Locally served VLM (Nemotron Nano VL and friends) over an OpenAI-compatible route."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = local_client(
            settings.vlm_base_url, settings.vlm_timeout_seconds, settings, label="vision"
        )
        self._fallback = DeterministicVisionModel()
        self.info = ModelRef(
            modality="vision",
            backend="openai_compat",
            model=settings.vlm_model,
            degraded=False,
            note=f"served locally at {settings.vlm_base_url}, single-image inference on sampled frames",
        )

    async def observe(
        self, frames: list[FrameRef], meta: dict[str, Any] | None = None
    ) -> list[VisionObservation]:
        meta = meta or {}
        zone_ids = [
            region.get("zoneId") for region in (meta.get("regions") or []) if region.get("zoneId")
        ]
        results: list[VisionObservation] = []
        for frame in frames:
            parsed = await self._observe_frame(frame, zone_ids)
            if parsed is None:
                continue
            zone_id = parsed.get("zoneId")
            if zone_id not in zone_ids:
                zone_id = None
            observations = parsed.get("observations") or []
            if isinstance(observations, str):
                observations = [observations]
            risk_type = parsed.get("riskType")
            if risk_type not in _RISK_TYPES:
                risk_type = "housekeeping"
            try:
                confidence = float(parsed.get("confidence", 0.5))
            except (TypeError, ValueError):
                confidence = 0.5
            results.append(
                VisionObservation(
                    zoneId=zone_id,
                    observations=[str(item) for item in observations][:6],
                    riskType=risk_type,
                    confidence=max(0.0, min(1.0, confidence)),
                    frameRefs=[frame.ref],
                    modelGenerated=True,
                    detector=self.info.label,
                    detail={"raw": parsed},
                )
            )

        if not results:
            logger.warning("local VLM produced no usable output; using deterministic CV path")
            return await self._fallback.observe(frames, meta)
        return results

    async def _observe_frame(self, frame: FrameRef, zone_ids: list[str]) -> dict[str, Any] | None:
        encoded = base64.b64encode(frame.path.read_bytes()).decode("ascii")
        zone_hint = ", ".join(zone_ids) if zone_ids else "none supplied"
        user_prompt = (
            f"Frame reference: {frame.ref}. Zones visible in this camera view: {zone_hint}. "
            "Check people and vehicles, PPE, restricted areas, edges/openings, load paths, "
            "fire or smoke, spills or leaks, electrical hazards, unstable materials, blocked "
            "egress, poor visibility, housekeeping and visible structural damage. Report only "
            "what this frame supports. Respond with JSON: "
            '{"zoneId": string|null, "observations": string[], "riskType": one of '
            f"{list(_RISK_TYPES)}, "
            '"confidence": 0..1, "frameRefs": string[]}'
        )
        payload = {
            "model": self._settings.vlm_model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                        },
                    ],
                },
            ],
            "temperature": 0.1,
            "max_tokens": 400,
        }
        try:
            response = await self._client.post("/chat/completions", json=payload)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            logger.warning("local VLM call failed for %s (%s)", frame.ref, exc)
            return None
        return parse_json_response(content)

    async def close(self) -> None:
        await self._client.aclose()


def build_vision_model(settings: Settings) -> VisionModel:
    if settings.vlm_backend in {"openai_compat", "ollama"}:
        return OpenAICompatVisionModel(settings)
    return DeterministicVisionModel()
