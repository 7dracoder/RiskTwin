"""Local speech-to-text for the crew radio clip.

Parakeet served locally is the intended path (spec section 9.4). Where no ASR
model is served, RiskTwin will use an operator-supplied transcript sidecar if one
exists and will otherwise report the evidence as unavailable — it never invents a
radio call, because a fabricated "zone clear" would be a safety defect.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

from packages.config import Settings
from packages.inference.base import ModelRef, local_client

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Transcript:
    available: bool
    text: str = ""
    segments: list[dict[str, Any]] = field(default_factory=list)
    transcriptSource: str = "unavailable"
    note: str = ""
    durationSeconds: float | None = None


class SpeechModel(Protocol):
    info: ModelRef

    async def transcribe(self, audio_path: Path) -> Transcript: ...

    async def close(self) -> None: ...


def _read_operator_transcript(audio_path: Path) -> Transcript | None:
    """An operator may drop `<clip>.transcript.txt` or `.transcript.json` beside the
    audio. It is clearly labelled as operator-provided, never as local ASR output."""
    for suffix in (".transcript.json", ".transcript.txt"):
        candidate = audio_path.with_suffix(audio_path.suffix + suffix)
        if not candidate.exists():
            candidate = audio_path.with_suffix(suffix)
        if not candidate.exists():
            continue
        if candidate.suffix == ".json":
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            return Transcript(
                available=True,
                text=payload.get("text", ""),
                segments=payload.get("segments") or [],
                transcriptSource="operator-provided",
                note=f"transcript supplied by the operator in {candidate.name}",
            )
        text = candidate.read_text(encoding="utf-8").strip()
        if text:
            return Transcript(
                available=True,
                text=text,
                transcriptSource="operator-provided",
                note=f"transcript supplied by the operator in {candidate.name}",
            )
    return None


class DeterministicSpeechModel:
    def __init__(self) -> None:
        self.info = ModelRef(
            modality="speech",
            backend="deterministic",
            model="operator-transcript-sidecar",
            degraded=True,
            note=(
                "No ASR model is served on this host. A crew statement is only used "
                "when the operator supplies a transcript sidecar; otherwise the audio "
                "evidence is reported as unavailable."
            ),
        )

    async def transcribe(self, audio_path: Path) -> Transcript:
        operator = _read_operator_transcript(audio_path)
        if operator is not None:
            return operator
        return Transcript(
            available=False,
            transcriptSource="unavailable",
            note=(
                "no local ASR model is served and no operator transcript sidecar was "
                "found; audio evidence is missing rather than assumed"
            ),
        )


    async def close(self) -> None:
        return None


class OpenAICompatSpeechModel:
    """Locally served ASR exposing an OpenAI-compatible transcription route."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = local_client(
            settings.asr_base_url, settings.asr_timeout_seconds, settings, label="speech"
        )
        self._fallback = DeterministicSpeechModel()
        self.info = ModelRef(
            modality="speech",
            backend="openai_compat",
            model=settings.asr_model,
            degraded=False,
            note=f"served locally at {settings.asr_base_url}",
        )

    async def transcribe(self, audio_path: Path) -> Transcript:
        try:
            files = {"file": (audio_path.name, audio_path.read_bytes(), "application/octet-stream")}
            data = {
                "model": self._settings.asr_model,
                "response_format": "verbose_json",
                "timestamp_granularities[]": "segment",
            }
            response = await self._client.post("/audio/transcriptions", files=files, data=data)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("local ASR unavailable (%s); falling back", exc)
            return await self._fallback.transcribe(audio_path)

        text = (body.get("text") or "").strip()
        if not text:
            return await self._fallback.transcribe(audio_path)
        return Transcript(
            available=True,
            text=text,
            segments=body.get("segments") or [],
            transcriptSource="local-asr",
            note=f"transcribed locally by {self._settings.asr_model}",
            durationSeconds=body.get("duration"),
        )

    async def close(self) -> None:
        await self._client.aclose()


class ParakeetMlxSpeechModel:
    """Parakeet on Apple Silicon via MLX, for a build console that has it installed.

    Optional: if `parakeet_mlx` is not importable the deterministic path is used.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._fallback = DeterministicSpeechModel()
        self._model = None
        self.info = ModelRef(
            modality="speech",
            backend="parakeet_mlx",
            model=settings.asr_model,
            degraded=False,
            note="Parakeet running locally through MLX",
        )

    def _load(self):
        if self._model is None:
            from parakeet_mlx import from_pretrained  # noqa: PLC0415

            self._model = from_pretrained(self._settings.asr_model)
        return self._model

    async def transcribe(self, audio_path: Path) -> Transcript:
        try:
            model = self._load()
            result = model.transcribe(str(audio_path))
        except Exception as exc:  # noqa: BLE001 - optional dependency, any failure falls back
            logger.warning("parakeet-mlx unavailable (%s); falling back", exc)
            return await self._fallback.transcribe(audio_path)
        segments = [
            {"start": getattr(s, "start", None), "end": getattr(s, "end", None), "text": getattr(s, "text", "")}
            for s in getattr(result, "sentences", []) or []
        ]
        return Transcript(
            available=True,
            text=getattr(result, "text", "").strip(),
            segments=segments,
            transcriptSource="local-asr",
            note=f"transcribed locally by {self._settings.asr_model} via MLX",
        )

    async def close(self) -> None:
        return None


def build_speech_model(settings: Settings) -> SpeechModel:
    if settings.asr_backend == "openai_compat":
        return OpenAICompatSpeechModel(settings)
    if settings.asr_backend == "parakeet_mlx":
        return ParakeetMlxSpeechModel(settings)
    return DeterministicSpeechModel()
