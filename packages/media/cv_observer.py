"""Deterministic local visual event extraction.

This is the spec's last-resort vision path (section 9.4) and it runs on every
host, including one with no VLM served. It reports *candidate* findings with
honest confidence and never claims a text model saw the video.

Two signals, both plain OpenCV:
  * inter-frame change against the median of the sampled frames, which surfaces
    objects that appear or move across the walkthrough;
  * the built-in HOG pedestrian detector, used to separate people from material.

Zone attribution comes from the operator's frame-to-zone sidecar. Without it a
finding carries `zoneId: null` and cannot be used to claim a specific zone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from packages.media.frames import FrameRef

DETECTOR_VERSION = "opencv-median-diff+hog-people/1"

_ANALYSIS_WIDTH = 640
_MIN_AREA_FRACTION = 0.012
_MAX_PER_FRAME = 3


@dataclass(slots=True)
class CvObservation:
    frameIndex: int
    frameRef: str
    kind: str
    box: tuple[int, int, int, int]
    boxFraction: tuple[float, float, float, float]
    areaFraction: float
    zoneId: str | None
    confidence: float
    note: str

    def to_detail(self) -> dict[str, Any]:
        return {
            "frameIndex": self.frameIndex,
            "frameRef": self.frameRef,
            "kind": self.kind,
            "boxFraction": [round(v, 4) for v in self.boxFraction],
            "areaFraction": round(self.areaFraction, 4),
            "zoneId": self.zoneId,
            "confidence": self.confidence,
            "note": self.note,
            "detector": DETECTOR_VERSION,
        }


def _load_analysis_frames(frames: list[FrameRef]) -> list[tuple[FrameRef, np.ndarray]]:
    loaded: list[tuple[FrameRef, np.ndarray]] = []
    for frame in frames:
        image = cv2.imread(str(frame.path))
        if image is None:
            continue
        height, width = image.shape[:2]
        if width > _ANALYSIS_WIDTH:
            scale = _ANALYSIS_WIDTH / width
            image = cv2.resize(image, (_ANALYSIS_WIDTH, int(height * scale)))
        loaded.append((frame, image))
    return loaded


def _person_boxes(image: np.ndarray) -> list[tuple[int, int, int, int]]:
    hog = cv2.HOGDescriptor()
    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    height, width = image.shape[:2]
    if height < 128 or width < 64:
        return []
    rects, _ = hog.detectMultiScale(image, winStride=(8, 8), padding=(8, 8), scale=1.05)
    return [(int(x), int(y), int(w), int(h)) for x, y, w, h in rects]


def _overlaps(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    left, top = max(ax, bx), max(ay, by)
    right, bottom = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if right <= left or bottom <= top:
        return 0.0
    intersection = (right - left) * (bottom - top)
    return intersection / float(aw * ah)


def _zone_for_box(
    box_fraction: tuple[float, float, float, float], meta: dict[str, Any]
) -> str | None:
    cx = (box_fraction[0] + box_fraction[2]) / 2
    cy = (box_fraction[1] + box_fraction[3]) / 2
    for region in meta.get("regions") or []:
        bounds = region.get("box")
        if not bounds or len(bounds) != 4:
            continue
        if bounds[0] <= cx <= bounds[2] and bounds[1] <= cy <= bounds[3]:
            return region.get("zoneId")
    return meta.get("defaultZoneId")


def _change_boxes(gray: np.ndarray, reference: np.ndarray | None) -> list[tuple[int, int, int, int]]:
    if reference is not None:
        delta = cv2.absdiff(gray, reference)
        delta = cv2.GaussianBlur(delta, (7, 7), 0)
        _, mask = cv2.threshold(delta, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    else:
        edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 60, 160)
        mask = cv2.dilate(edges, np.ones((7, 7), np.uint8), iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return [cv2.boundingRect(contour) for contour in contours]


def analyse_frames(frames: list[FrameRef], meta: dict[str, Any] | None = None) -> list[CvObservation]:
    """Return candidate visual observations for the sampled frames."""
    meta = meta or {}
    loaded = _load_analysis_frames(frames)
    if not loaded:
        return []

    grays = [cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) for _, image in loaded]
    reference = np.median(np.stack(grays), axis=0).astype(np.uint8) if len(grays) > 1 else None

    observations: list[CvObservation] = []
    for (frame, image), gray in zip(loaded, grays, strict=True):
        height, width = gray.shape[:2]
        frame_area = float(height * width)
        people = _person_boxes(image)
        candidates: list[tuple[float, CvObservation]] = []

        for box in _change_boxes(gray, reference):
            x, y, w, h = box
            area_fraction = (w * h) / frame_area
            if area_fraction < _MIN_AREA_FRACTION or area_fraction > 0.85:
                continue
            box_fraction = (x / width, y / height, (x + w) / width, (y + h) / height)
            is_person = any(_overlaps(box, person) > 0.3 for person in people)
            zone_id = _zone_for_box(box_fraction, meta)
            if is_person:
                kind = "person_activity"
                confidence = round(min(0.8, 0.5 + area_fraction), 2)
                note = "pedestrian-shaped region; treated as a person, not material"
            else:
                kind = "candidate_obstruction"
                confidence = round(min(0.62, 0.3 + area_fraction * 2), 2)
                note = (
                    "candidate foreign object or material; requires human confirmation "
                    "before it may be treated as a confirmed obstruction"
                )
            if zone_id is None:
                confidence = round(confidence * 0.6, 2)
                note += "; no frame-to-zone mapping supplied, zone unconfirmed"
            candidates.append(
                (
                    area_fraction,
                    CvObservation(
                        frameIndex=frame.index,
                        frameRef=frame.ref,
                        kind=kind,
                        box=(x, y, w, h),
                        boxFraction=box_fraction,
                        areaFraction=area_fraction,
                        zoneId=zone_id,
                        confidence=confidence,
                        note=note,
                    ),
                )
            )

        candidates.sort(key=lambda pair: pair[0], reverse=True)
        observations.extend(observation for _, observation in candidates[:_MAX_PER_FRAME])

    return observations
