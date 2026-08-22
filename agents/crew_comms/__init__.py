"""Crew Comms Agent — local ASR transcript to safety-intent evidence.

Extracts the instruction, the equipment referenced, the zone referenced and the
urgency. The extraction is deterministic keyword analysis by default; a served
text model may refine the wording, but a claim such as "zone C is clear" is only
recorded when it actually appears in a local transcript.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from agents.base import AgentContext, write_evidence
from packages.contracts import EvidenceType, Severity
from packages.media import discover_audio

logger = logging.getLogger(__name__)

AGENT_NAME = "crew-comms"

_STOP_PHRASES = (
    "hold the lift",
    "hold lift",
    "stop the lift",
    "stop work",
    "all stop",
    "abort",
    "down slow",
)
_CLEAR_PATTERN = re.compile(
    r"zone\s+([a-d])\b[^.!?]{0,30}?\b(is\s+)?(clear|all\s+clear|clear\s+for\s+the\s+lift)",
    re.IGNORECASE,
)
_ZONE_PATTERN = re.compile(r"\bzone\s+([a-d])\b", re.IGNORECASE)
_EQUIPMENT_PATTERN = re.compile(
    r"\b(crane\s*\d*|hoist|jib|spandrel|load|sling|tagline|banksman|signaller)\b", re.IGNORECASE
)
_URGENT_WORDS = ("now", "immediately", "urgent", "emergency", "stop", "hold")


def extract_intent(transcript: str) -> dict[str, Any]:
    """Deterministic safety-language extraction from a local transcript."""
    lowered = transcript.lower()
    stop_phrase = next((phrase for phrase in _STOP_PHRASES if phrase in lowered), None)
    clear_match = _CLEAR_PATTERN.search(transcript)
    zones = sorted({match.group(1).upper() for match in _ZONE_PATTERN.finditer(transcript)})
    equipment = sorted({match.group(1).strip().lower() for match in _EQUIPMENT_PATTERN.finditer(transcript)})
    urgency = "high" if stop_phrase or any(word in lowered for word in _URGENT_WORDS) else "normal"

    if stop_phrase:
        instruction = "stop_work"
    elif clear_match:
        instruction = "zone_clear_declaration"
    elif zones:
        instruction = "zone_status_report"
    else:
        instruction = "informational"

    return {
        "instruction": instruction,
        "stopPhrase": stop_phrase,
        "claimsZoneClear": clear_match.group(1).upper() if clear_match else None,
        "zonesReferenced": zones,
        "equipmentReferenced": equipment,
        "urgency": urgency,
    }


async def run(context: AgentContext, *, case_id: str, cue: dict[str, Any] | None = None) -> list[str]:
    settings = context.settings
    clips = discover_audio(settings.path(settings.raw_audio_dir))

    if not clips:
        record = await write_evidence(
            context,
            case_id=case_id,
            agent=AGENT_NAME,
            evidence_type=EvidenceType.AUDIO_OBSERVATION,
            finding=(
                "No crew radio clip is present in data/raw/audio, so no verbal confirmation "
                "or stop-work call can be evidenced for this case."
            ),
            confidence=1.0,
            severity=Severity.LOW,
            source_refs=["asset:missing"],
            detail={"available": False, "subject": "crew"},
            model_ref=context.models.speech.info.label,
        )
        return [record.id]

    asset = clips[0]
    transcript = await context.models.speech.transcribe(asset.path)

    if not transcript.available:
        record = await write_evidence(
            context,
            case_id=case_id,
            agent=AGENT_NAME,
            evidence_type=EvidenceType.AUDIO_OBSERVATION,
            finding=(
                f"{asset.name} is present but could not be transcribed locally: {transcript.note}. "
                "The crew statement is therefore unknown and is not assumed."
            ),
            confidence=1.0,
            severity=Severity.MEDIUM,
            source_refs=[f"asset:{asset.name}"],
            detail={"available": False, "subject": "crew", "reason": transcript.note},
            model_ref=context.models.speech.info.label,
        )
        return [record.id]

    intent = extract_intent(transcript.text)
    transcript_path = settings.path(settings.transcript_dir) / f"{asset.path.stem}.txt"
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text(transcript.text, encoding="utf-8")

    severity = Severity.HIGH if intent["instruction"] == "stop_work" else Severity.MEDIUM
    if intent["instruction"] == "informational":
        severity = Severity.LOW

    quoted = transcript.text.strip().replace("\n", " ")
    if len(quoted) > 220:
        quoted = quoted[:217] + "..."

    record = await write_evidence(
        context,
        case_id=case_id,
        agent=AGENT_NAME,
        evidence_type=EvidenceType.AUDIO_OBSERVATION,
        finding=(
            f"Crew radio ({transcript.transcriptSource}) — {intent['instruction'].replace('_', ' ')}, "
            f"urgency {intent['urgency']}: \u201c{quoted}\u201d"
        ),
        confidence=0.9 if transcript.transcriptSource == "local-asr" else 0.75,
        severity=severity,
        source_refs=[f"asset:{asset.name}", f"transcript:{transcript_path.name}"],
        detail={
            "available": True,
            "subject": "crew",
            "transcript": transcript.text,
            "transcriptSource": transcript.transcriptSource,
            "segments": transcript.segments[:12],
            **intent,
        },
        model_generated=transcript.transcriptSource == "local-asr",
        model_ref=context.models.speech.info.label,
    )
    return [record.id]
