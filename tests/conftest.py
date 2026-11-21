"""Test fixtures.

Every test runs against an isolated state directory with the deterministic
inference adapters, so the suite never depends on a served model, a network
endpoint or a MongoDB install.
"""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import cv2
import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient

from packages.config import REPO_ROOT, Settings, reset_settings_cache

CASE_ID = "LIFT-042"


@pytest.fixture
def workspace(tmp_path: Path) -> Iterator[Path]:
    """An isolated copy of the data workspace."""
    for name in (
        "raw/video",
        "raw/audio",
        "raw/documents",
        "processed/frames",
        "processed/transcripts",
        "processed/redacted",
        "processed/reconstruction",
        "state",
    ):
        (tmp_path / "data" / name).mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        REPO_ROOT / "data" / "site-models", tmp_path / "data" / "site-models", dirs_exist_ok=True
    )
    shutil.copytree(
        REPO_ROOT / "data" / "recordings", tmp_path / "data" / "recordings", dirs_exist_ok=True
    )
    yield tmp_path
    reset_settings_cache()


@pytest.fixture
def documents(workspace: Path) -> Path:
    """Copy the authored lift plan and SOP into the isolated workspace."""
    source = REPO_ROOT / "data" / "raw" / "documents"
    target = workspace / "data" / "raw" / "documents"
    shutil.copytree(source, target, dirs_exist_ok=True)
    return target


@pytest.fixture
def settings(workspace: Path) -> Settings:
    return Settings(
        case_id=CASE_ID,
        host_profile="build-console",
        storage_backend="file",
        state_dir=str(workspace / "data" / "state"),
        llm_backend="deterministic",
        vlm_backend="deterministic",
        asr_backend="deterministic",
        openshell_backend="shim",
        agent_runtime="inprocess",
        lifecycle="local",
        allow_remote_inference=False,
        replay_speed=1.0,
        recording_path=str(workspace / "data" / "recordings" / "lift-042-trace.json"),
        site_model_path=str(workspace / "data" / "site-models" / "site-042-v1.json"),
        raw_video_dir=str(workspace / "data" / "raw" / "video"),
        raw_audio_dir=str(workspace / "data" / "raw" / "audio"),
        raw_document_dir=str(workspace / "data" / "raw" / "documents"),
        frame_dir=str(workspace / "data" / "processed" / "frames"),
        transcript_dir=str(workspace / "data" / "processed" / "transcripts"),
        redacted_dir=str(workspace / "data" / "processed" / "redacted"),
        reconstruction_dir=str(workspace / "data" / "processed" / "reconstruction"),
        frame_sample_count=4,
        policy_path=str(REPO_ROOT / "config" / "openshell-policy.yaml"),
        sources_path=str(REPO_ROOT / "config" / "sources.yaml"),
    )


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    from apps.api.main import create_app

    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://risktwin.test") as http:
            http.app_state = app.state.risktwin  # type: ignore[attr-defined]
            yield http


def make_walkthrough_video(path: Path, *, frames: int = 60, obstruction_from: int = 30) -> Path:
    """A synthetic walkthrough clip: a moving figure plus material that appears
    on the right-hand side of the frame partway through."""
    width, height, fps = 640, 480, 25
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    rng = np.random.default_rng(7)
    background = rng.integers(70, 110, (height, width, 3)).astype(np.uint8)
    for index in range(frames):
        frame = background.copy()
        cv2.rectangle(frame, (0, 340), (width, height), (120, 120, 125), -1)
        x = 40 + index * 5
        cv2.rectangle(frame, (x, 200), (x + 40, 330), (60, 70, 190), -1)
        cv2.circle(frame, (x + 20, 190), 16, (180, 170, 160), -1)
        if index >= obstruction_from:
            cv2.rectangle(frame, (430, 270), (570, 340), (40, 140, 190), -1)
        writer.write(frame)
    writer.release()
    return path


def write_crew_clip(path: Path, transcript: str) -> Path:
    """A silent WAV plus an operator transcript sidecar.

    The deterministic ASR adapter refuses to invent speech, so a transcript is
    supplied the same way an operator would supply one on a host with no ASR model.
    """
    import struct
    import wave

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(struct.pack("<h", 0) * 16000)
    path.with_suffix(path.suffix + ".transcript.txt").write_text(transcript, encoding="utf-8")
    return path
