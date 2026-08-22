"""Local media processing: frame sampling, deterministic CV, redaction, documents."""

from packages.media.assets import (
    Asset,
    discover_audio,
    discover_documents,
    discover_videos,
    load_sidecar,
    sha256_file,
)
from packages.media.cv_observer import CvObservation, analyse_frames
from packages.media.documents import (
    RULE_EXCLUSION_ZONE_CLEAR,
    RULE_HUMAN_APPROVAL,
    RULE_MAX_LOAD_UTILISATION,
    RULE_MAX_WIND_GUST,
    RULE_RESTART_PROCEDURE,
    RULE_STALE_DATA_ACTION,
    build_document_chunks,
    detect_rules,
)
from packages.media.frames import FrameRef, sample_frames, video_properties
from packages.media.redaction import RedactionResult, redact_video

__all__ = [
    "RULE_EXCLUSION_ZONE_CLEAR",
    "RULE_HUMAN_APPROVAL",
    "RULE_MAX_LOAD_UTILISATION",
    "RULE_MAX_WIND_GUST",
    "RULE_RESTART_PROCEDURE",
    "RULE_STALE_DATA_ACTION",
    "Asset",
    "CvObservation",
    "FrameRef",
    "RedactionResult",
    "analyse_frames",
    "build_document_chunks",
    "detect_rules",
    "discover_audio",
    "discover_documents",
    "discover_videos",
    "load_sidecar",
    "redact_video",
    "sample_frames",
    "sha256_file",
    "video_properties",
]
