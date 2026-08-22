"""Discovery of operator-supplied media in `data/raw`.

RiskTwin never invents an asset. If the walkthrough video, crew audio or lift-plan
document is absent, the pipeline reports it as unavailable, which drives the case
to ESCALATE (spec section 14, failure handling).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".avi", ".mkv"}
AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aiff", ".aif", ".flac"}
DOCUMENT_SUFFIXES = {".pdf", ".md", ".txt"}


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(slots=True)
class Asset:
    path: Path
    kind: str
    checksum: str
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def provenance(self) -> str:
        return self.meta.get("provenance", "unrecorded — add data/ATTRIBUTION.md entry")

    @property
    def license(self) -> str:
        return self.meta.get("license", "unrecorded")


def load_sidecar(path: Path) -> dict[str, Any]:
    """Operator-supplied metadata: provenance, license and frame-to-zone mapping.

    Frame-to-zone mapping matters because a walkthrough clip carries no camera
    pose. Without it, a visual finding cannot claim a zone and stays unconfirmed.
    """
    sidecar = path.with_suffix(path.suffix + ".meta.json")
    if not sidecar.exists():
        sidecar = path.with_suffix(".meta.json")
    if not sidecar.exists():
        return {}
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _discover(directory: Path, suffixes: set[str], kind: str) -> list[Asset]:
    if not directory.exists():
        return []
    assets: list[Asset] = []
    for candidate in sorted(directory.iterdir()):
        if not candidate.is_file() or candidate.suffix.lower() not in suffixes:
            continue
        if candidate.name.endswith(".meta.json"):
            continue
        assets.append(
            Asset(
                path=candidate,
                kind=kind,
                checksum=sha256_file(candidate),
                meta=load_sidecar(candidate),
            )
        )
    return assets


def discover_videos(directory: Path) -> list[Asset]:
    return _discover(directory, VIDEO_SUFFIXES, "video")


def discover_audio(directory: Path) -> list[Asset]:
    return _discover(directory, AUDIO_SUFFIXES, "audio")


def discover_documents(directory: Path) -> list[Asset]:
    return _discover(directory, DOCUMENT_SUFFIXES, "document")
