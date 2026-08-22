"""Local redaction pipeline producing the only exportable video artifact.

Raw source video stays in the processing workspace. The dashboard may only ever
preview or download the redacted render (spec section 5.1), which OpenShell
policy enforces separately.

Faces are Gaussian-blurred. When no face is confidently located inside a detected
person box — common with high-angle walkthrough footage — the whole person box is
pixelated instead, which is the safe default rather than leaving an identity
exposed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from packages.media.assets import sha256_file

DETECTOR_VERSION = "opencv-haar-frontalface+hog-people/1"
REDACTION_METHOD = "gaussian-face-blur; person-box pixelation fallback"

_MAX_WIDTH = 960
_DETECT_INTERVAL = 5


@dataclass(slots=True)
class RedactionResult:
    inputPath: str
    inputSha256: str
    outputPath: str
    outputSha256: str
    detectorVersion: str
    redactionMethod: str
    framesProcessed: int
    redactedRegions: int
    redactedFrameRanges: list[list[int]] = field(default_factory=list)
    identitiesLabelled: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_manifest_fields(self) -> dict[str, Any]:
        return {
            "inputPath": self.inputPath,
            "inputSha256": self.inputSha256,
            "outputPath": self.outputPath,
            "outputSha256": self.outputSha256,
            "detectorVersion": self.detectorVersion,
            "redactionMethod": self.redactionMethod,
            "framesProcessed": self.framesProcessed,
            "redactedRegions": self.redactedRegions,
            "redactedFrameRanges": self.redactedFrameRanges,
            "warnings": self.warnings,
        }


def _face_cascade() -> cv2.CascadeClassifier:
    return cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")


def _hog() -> cv2.HOGDescriptor:
    hog = cv2.HOGDescriptor()
    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    return hog


def _blur_region(image: np.ndarray, box: tuple[int, int, int, int]) -> None:
    x, y, w, h = box
    region = image[y : y + h, x : x + w]
    if region.size == 0:
        return
    kernel = max(15, (min(w, h) // 2) * 2 + 1)
    image[y : y + h, x : x + w] = cv2.GaussianBlur(region, (kernel, kernel), 0)


def _pixelate_region(image: np.ndarray, box: tuple[int, int, int, int], blocks: int = 12) -> None:
    x, y, w, h = box
    region = image[y : y + h, x : x + w]
    if region.size == 0:
        return
    small = cv2.resize(
        region, (max(1, blocks), max(1, blocks)), interpolation=cv2.INTER_LINEAR
    )
    image[y : y + h, x : x + w] = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)


def _clamp_box(
    box: tuple[int, int, int, int], width: int, height: int
) -> tuple[int, int, int, int]:
    x, y, w, h = box
    x = max(0, min(int(x), width - 1))
    y = max(0, min(int(y), height - 1))
    w = max(1, min(int(w), width - x))
    h = max(1, min(int(h), height - y))
    return x, y, w, h


def _draw_overlays(
    image: np.ndarray,
    *,
    people: list[tuple[int, int, int, int]],
    regions: list[dict[str, Any]],
    time_seconds: float,
    banner: str,
) -> int:
    height, width = image.shape[:2]

    for region in regions:
        bounds = region.get("box")
        if not bounds or len(bounds) != 4:
            continue
        x1, y1 = int(bounds[0] * width), int(bounds[1] * height)
        x2, y2 = int(bounds[2] * width), int(bounds[3] * height)
        colour = (0, 0, 220) if region.get("risk") else (0, 190, 220)
        cv2.rectangle(image, (x1, y1), (x2, y2), colour, 2)
        label = f"ZONE {region.get('zoneId', '?')}"
        if region.get("risk"):
            label += " — RISK"
        cv2.putText(
            image, label, (x1 + 6, max(18, y1 + 22)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, colour, 2
        )

    for index, box in enumerate(sorted(people, key=lambda b: b[0]), start=1):
        x, y, w, h = box
        cv2.rectangle(image, (x, y), (x + w, y + h), (240, 240, 240), 1)
        cv2.putText(
            image,
            f"worker-{index}",
            (x, max(14, y - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (240, 240, 240),
            1,
        )

    cv2.rectangle(image, (0, 0), (width, 30), (18, 18, 22), -1)
    cv2.putText(
        image,
        f"{banner}  t={time_seconds:0.2f}s  REDACTED SAFETY EVIDENCE",
        (8, 21),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (240, 240, 240),
        1,
    )
    return len(people)


def redact_video(
    input_path: Path,
    output_path: Path,
    *,
    regions: list[dict[str, Any]] | None = None,
    banner: str = "LIFT-042",
) -> RedactionResult:
    """Write a redacted MP4 next to a manifest-ready summary of what was redacted."""
    capture = cv2.VideoCapture(str(input_path))
    if not capture.isOpened():
        raise ValueError(f"cannot open video {input_path}")

    face_cascade = _face_cascade()
    hog = _hog()
    regions = regions or []

    try:
        source_fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
        source_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        source_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        scale = min(1.0, _MAX_WIDTH / source_width) if source_width else 1.0
        width = int(source_width * scale) or _MAX_WIDTH
        height = int(source_height * scale) or int(_MAX_WIDTH * 9 / 16)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        writer = cv2.VideoWriter(
            str(output_path), cv2.VideoWriter_fourcc(*"mp4v"), source_fps, (width, height)
        )
        if not writer.isOpened():
            raise ValueError(f"cannot open writer for {output_path}")

        frame_index = 0
        redacted_regions = 0
        identities = 0
        redacted_frames: list[int] = []
        people: list[tuple[int, int, int, int]] = []

        try:
            while True:
                ok, frame = capture.read()
                if not ok or frame is None:
                    break
                if scale != 1.0:
                    frame = cv2.resize(frame, (width, height))
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

                if frame_index % _DETECT_INTERVAL == 0:
                    detections, _ = hog.detectMultiScale(
                        frame, winStride=(8, 8), padding=(8, 8), scale=1.06
                    )
                    people = [
                        _clamp_box((int(x), int(y), int(w), int(h)), width, height)
                        for x, y, w, h in detections
                    ]

                faces = [
                    _clamp_box((int(x), int(y), int(w), int(h)), width, height)
                    for x, y, w, h in face_cascade.detectMultiScale(gray, 1.1, 5, minSize=(24, 24))
                ]

                frame_redactions = 0
                for face in faces:
                    _blur_region(frame, face)
                    frame_redactions += 1

                for person in people:
                    px, py, pw, ph = person
                    has_face = any(
                        px <= fx <= px + pw and py <= fy <= py + ph for fx, fy, _, _ in faces
                    )
                    if not has_face:
                        _pixelate_region(frame, person)
                        frame_redactions += 1

                identities = max(
                    identities,
                    _draw_overlays(
                        frame,
                        people=people,
                        regions=regions,
                        time_seconds=frame_index / source_fps if source_fps else 0.0,
                        banner=banner,
                    ),
                )

                if frame_redactions:
                    redacted_regions += frame_redactions
                    redacted_frames.append(frame_index)

                writer.write(frame)
                frame_index += 1
        finally:
            writer.release()
    finally:
        capture.release()

    warnings: list[str] = []
    if frame_index and not redacted_regions:
        # Silence here is not proof the clip is identity-free, so say so rather
        # than letting the dashboard imply a verified redaction.
        warnings.append(
            "no face or person regions were detected; redaction could not be verified "
            "automatically and the clip must be reviewed manually before it is shared"
        )

    return RedactionResult(
        inputPath=str(input_path),
        inputSha256=sha256_file(input_path),
        outputPath=str(output_path),
        outputSha256=sha256_file(output_path) if output_path.exists() else "",
        detectorVersion=DETECTOR_VERSION,
        redactionMethod=REDACTION_METHOD,
        framesProcessed=frame_index,
        redactedRegions=redacted_regions,
        redactedFrameRanges=_to_ranges(redacted_frames),
        identitiesLabelled=identities,
        warnings=warnings,
    )


def _to_ranges(frames: list[int]) -> list[list[int]]:
    if not frames:
        return []
    ranges: list[list[int]] = []
    start = previous = frames[0]
    for value in frames[1:]:
        if value == previous + 1:
            previous = value
            continue
        ranges.append([start, previous])
        start = previous = value
    ranges.append([start, previous])
    return ranges
