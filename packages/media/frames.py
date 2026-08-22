"""Local frame sampling.

The vision model works on a handful of sampled still frames, never on raw video
(spec section 9.4). Sampling happens here so both the VLM path and the
deterministic CV path see exactly the same evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2


@dataclass(slots=True)
class FrameRef:
    index: int
    frameNumber: int
    timeSeconds: float
    path: Path

    @property
    def ref(self) -> str:
        return f"frame:{self.index}@{self.timeSeconds:.2f}s"


def sample_frames(video_path: Path, count: int, output_dir: Path) -> list[FrameRef]:
    """Extract `count` evenly spaced frames and write them as JPEGs."""
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError(f"cannot open video {video_path}")
    try:
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = capture.get(cv2.CAP_PROP_FPS) or 0.0
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = video_path.stem

        if total > 0:
            step = max(total // (count + 1), 1)
            targets = [min(step * (i + 1), total - 1) for i in range(count)]
        else:
            targets = list(range(count))

        frames: list[FrameRef] = []
        for position, frame_number in enumerate(dict.fromkeys(targets)):
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            ok, image = capture.read()
            if not ok or image is None:
                continue
            destination = output_dir / f"{stem}-f{position:02d}.jpg"
            cv2.imwrite(str(destination), image)
            frames.append(
                FrameRef(
                    index=position,
                    frameNumber=frame_number,
                    timeSeconds=(frame_number / fps) if fps > 0 else float(position),
                    path=destination,
                )
            )
        return frames
    finally:
        capture.release()


def video_properties(video_path: Path) -> dict[str, float]:
    capture = cv2.VideoCapture(str(video_path))
    try:
        return {
            "frameCount": float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0),
            "fps": float(capture.get(cv2.CAP_PROP_FPS) or 0),
            "width": float(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0),
            "height": float(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0),
        }
    finally:
        capture.release()
