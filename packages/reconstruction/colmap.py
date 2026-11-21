"""Fast, local video-to-point-cloud reconstruction with COLMAP.

The first useful output is deliberately a sparse SfM cloud. Dense stereo can be
minutes slower and is not required to show that the camera path and scene were
actually reconstructed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from packages.config import Settings

logger = logging.getLogger(__name__)

_LOCAL_COLMAP = Path("/home/dell/.local/opt/colmap-3.9.1/usr/bin/colmap")
_ACTIVE_PHASES = {"extracting", "features", "matching", "mapping", "exporting"}


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


class ColmapReconstruction:
    """Own one background reconstruction job and expose a small JSON cloud."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.output_root = settings.path(settings.reconstruction_dir)
        self._task: asyncio.Task[None] | None = None
        self._status: dict[str, Any] = self._initial_status()
        self._load_status()

    def _find_binary(self) -> Path | None:
        configured = Path(self.settings.colmap_binary).expanduser()
        if configured.is_file() and os.access(configured, os.X_OK):
            return configured
        discovered = shutil.which("colmap")
        if discovered:
            return Path(discovered)
        if _LOCAL_COLMAP.is_file() and os.access(_LOCAL_COLMAP, os.X_OK):
            return _LOCAL_COLMAP
        return None

    def _initial_status(self) -> dict[str, Any]:
        binary = self._find_binary()
        return {
            "phase": "idle",
            "progress": 0,
            "message": "Ready to reconstruct the latest local MP4"
            if binary
            else "COLMAP is not installed",
            "available": binary is not None,
            "engine": "COLMAP 3D Structure-from-Motion",
            "binary": str(binary) if binary else None,
            "videoName": None,
            "framesExtracted": 0,
            "registeredImages": 0,
            "pointCount": 0,
            "durationMs": None,
            "startedAt": None,
            "completedAt": None,
            "outputReady": False,
            "runId": None,
        }

    @property
    def status_path(self) -> Path:
        return self.output_root / "status.json"

    def _load_status(self) -> None:
        try:
            saved = json.loads(self.status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if saved.get("phase") in _ACTIVE_PHASES:
            saved.update(
                phase="interrupted", message="Previous reconstruction stopped before completion"
            )
        binary = self._find_binary()
        saved.update(available=binary is not None, binary=str(binary) if binary else None)
        self._status.update(saved)

    def _save_status(self) -> None:
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.status_path.write_text(json.dumps(self._status, indent=2), encoding="utf-8")

    def _update(self, **changes: Any) -> None:
        self._status.update(changes)
        self._save_status()

    def status(self) -> dict[str, Any]:
        result = dict(self._status)
        result["running"] = bool(self._task and not self._task.done())
        return result

    async def start(self, video_name: str | None = None) -> dict[str, Any]:
        if self._task and not self._task.done():
            return self.status()
        binary = self._find_binary()
        if not binary:
            self._update(
                phase="unavailable",
                available=False,
                message="Install COLMAP or set RISKTWIN_COLMAP_BINARY",
            )
            return self.status()
        raw_dir = self.settings.path(self.settings.raw_video_dir)
        videos = sorted(raw_dir.glob("*.mp4"), key=lambda path: path.stat().st_mtime, reverse=True)
        if video_name:
            if "/" in video_name or ".." in video_name:
                raise ValueError("invalid video name")
            videos = [raw_dir / video_name]
        if not videos or not videos[0].is_file():
            raise FileNotFoundError("no local MP4 is available for reconstruction")
        self._task = asyncio.create_task(self._run(binary, videos[0]))
        await asyncio.sleep(0)
        return self.status()

    async def shutdown(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def _command_env(self, binary: Path) -> dict[str, str]:
        env = os.environ.copy()
        if ".local/opt/colmap-" in str(binary):
            root = binary.parents[2]
            library_dirs = [
                root / "usr/lib/aarch64-linux-gnu",
                root / "usr/lib/aarch64-linux-gnu/lapack",
                root / "usr/lib/aarch64-linux-gnu/blas",
            ]
            current = env.get("LD_LIBRARY_PATH", "")
            env["LD_LIBRARY_PATH"] = ":".join(
                [*(str(path) for path in library_dirs), current]
            ).rstrip(":")
        return env

    async def _exec(self, binary: Path, *args: str) -> str:
        process = await asyncio.create_subprocess_exec(
            str(binary),
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=self._command_env(binary),
        )
        output_bytes, _ = await process.communicate()
        output = output_bytes.decode("utf-8", errors="replace")
        if process.returncode:
            tail = "\n".join(output.strip().splitlines()[-12:])
            raise RuntimeError(tail or f"COLMAP exited with code {process.returncode}")
        return output

    async def _run(self, binary: Path, video: Path) -> None:
        started = time.monotonic()
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        workspace = self.output_root / f"{video.stem}-{run_id}"
        images = workspace / "images"
        sparse = workspace / "sparse"
        text_model = workspace / "model-txt"
        database = workspace / "database.db"
        for path in (images, sparse, text_model):
            path.mkdir(parents=True, exist_ok=True)
        self._update(
            phase="extracting",
            progress=5,
            message="Sampling sharp frames from video",
            available=True,
            videoName=video.name,
            framesExtracted=0,
            registeredImages=0,
            pointCount=0,
            durationMs=None,
            startedAt=_utcnow(),
            completedAt=None,
            outputReady=False,
            runId=run_id,
            workspace=str(workspace),
        )
        try:
            frame_count = await asyncio.to_thread(
                self._extract_frames,
                video,
                images,
                self.settings.reconstruction_frame_count,
                self.settings.reconstruction_max_dimension,
            )
            self._update(
                phase="features",
                progress=25,
                framesExtracted=frame_count,
                message=f"COLMAP SIFT: {frame_count} frames",
            )
            await self._exec(
                binary,
                "feature_extractor",
                "--database_path",
                str(database),
                "--image_path",
                str(images),
                "--ImageReader.single_camera",
                "1",
                "--ImageReader.camera_model",
                "SIMPLE_RADIAL",
                "--SiftExtraction.use_gpu",
                "0",
                "--SiftExtraction.max_image_size",
                str(self.settings.reconstruction_max_dimension),
                "--SiftExtraction.max_num_features",
                "4096",
            )
            self._update(phase="matching", progress=50, message="Matching neighboring video frames")
            await self._exec(
                binary,
                "sequential_matcher",
                "--database_path",
                str(database),
                "--SiftMatching.use_gpu",
                "0",
                "--SequentialMatching.overlap",
                "8",
                "--SequentialMatching.quadratic_overlap",
                "1",
            )
            self._update(phase="mapping", progress=70, message="Solving camera poses and 3D points")
            await self._exec(
                binary,
                "mapper",
                "--database_path",
                str(database),
                "--image_path",
                str(images),
                "--output_path",
                str(sparse),
                "--Mapper.min_num_matches",
                "12",
                "--Mapper.init_min_num_inliers",
                "60",
            )
            models = sorted(path for path in sparse.iterdir() if path.is_dir())
            if not models:
                raise RuntimeError(
                    "COLMAP could not register a camera pair; "
                    "capture with slower motion and more parallax"
                )
            model = models[0]
            self._update(
                phase="exporting", progress=90, message="Preparing the interactive point cloud"
            )
            await self._exec(
                binary,
                "model_converter",
                "--input_path",
                str(model),
                "--output_path",
                str(text_model),
                "--output_type",
                "TXT",
            )
            registered, points = self._model_counts(text_model)
            if points == 0:
                raise RuntimeError("COLMAP registered images but produced no stable 3D points")
            duration = int((time.monotonic() - started) * 1000)
            self._update(
                phase="complete",
                progress=100,
                message="Interactive COLMAP point cloud ready",
                registeredImages=registered,
                pointCount=points,
                durationMs=duration,
                completedAt=_utcnow(),
                outputReady=True,
                modelPath=str(text_model),
            )
        except asyncio.CancelledError:
            self._update(phase="interrupted", message="Reconstruction stopped")
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("COLMAP reconstruction failed")
            self._update(
                phase="failed",
                message=str(exc).splitlines()[-1][:240],
                progress=0,
                durationMs=int((time.monotonic() - started) * 1000),
                completedAt=_utcnow(),
                outputReady=False,
            )

    @staticmethod
    def _extract_frames(video: Path, output: Path, target_count: int, max_dimension: int) -> int:
        capture = cv2.VideoCapture(str(video))
        if not capture.isOpened():
            raise RuntimeError(f"cannot open {video.name}")
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if total < 2:
            capture.release()
            raise RuntimeError("video does not contain enough frames")
        indices = np.linspace(0, total - 1, min(target_count, total), dtype=int)
        written = 0
        for frame_number in sorted(set(int(index) for index in indices)):
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            ok, frame = capture.read()
            if not ok:
                continue
            height, width = frame.shape[:2]
            scale = min(1.0, max_dimension / max(width, height))
            if scale < 1:
                frame = cv2.resize(
                    frame, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA
                )
            if not cv2.imwrite(
                str(output / f"frame-{written:04d}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 90]
            ):
                raise RuntimeError("failed to write a sampled frame")
            written += 1
        capture.release()
        if written < 8:
            raise RuntimeError("fewer than 8 usable video frames were extracted")
        return written

    @staticmethod
    def _model_counts(model: Path) -> tuple[int, int]:
        def rows(path: Path) -> int:
            return sum(
                1
                for line in path.open(encoding="utf-8")
                if line.strip() and not line.startswith("#")
            )

        return rows(model / "images.txt") // 2, rows(model / "points3D.txt")

    def point_cloud(self, limit: int = 8000) -> dict[str, Any]:
        if not self._status.get("outputReady"):
            return {"points": [], "pointCount": 0, "runId": self._status.get("runId")}
        point_path = Path(str(self._status["modelPath"])) / "points3D.txt"
        parsed: list[tuple[float, float, float, int, int, int]] = []
        with point_path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip() or line.startswith("#"):
                    continue
                parts = line.split()
                parsed.append(
                    (
                        float(parts[1]),
                        float(parts[2]),
                        float(parts[3]),
                        int(parts[4]),
                        int(parts[5]),
                        int(parts[6]),
                    )
                )
        if len(parsed) > limit:
            stride = max(1, len(parsed) // limit)
            parsed = parsed[::stride][:limit]
        xyz = np.asarray([row[:3] for row in parsed], dtype=np.float64)
        center = np.median(xyz, axis=0)
        xyz -= center
        scale = float(np.percentile(np.linalg.norm(xyz, axis=1), 95)) or 1.0
        xyz /= scale
        points = [
            {
                "x": round(float(position[0]), 5),
                "y": round(float(position[1]), 5),
                "z": round(float(position[2]), 5),
                "r": row[3],
                "g": row[4],
                "b": row[5],
            }
            for position, row in zip(xyz, parsed, strict=True)
        ]
        return {
            "points": points,
            "pointCount": int(self._status["pointCount"]),
            "sampledCount": len(points),
            "runId": self._status.get("runId"),
        }
