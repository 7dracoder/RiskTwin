"""Local document extraction and rule indexing.

For a corpus this small, deterministic rule/tag retrieval beats adding a vector
search dependency (spec section 7.3). Each chunk is scanned for machine-checkable
limits, so the Rules Retrieval Agent can return the *exact* applicable rule with a
numeric threshold instead of a generic safety summary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from packages.contracts import DocumentChunk

# Rule keys the deterministic risk engine can evaluate directly.
RULE_MAX_WIND_GUST = "max_wind_gust_kmh"
RULE_MAX_LOAD_UTILISATION = "max_load_utilisation_pct"
RULE_EXCLUSION_ZONE_CLEAR = "exclusion_zone_clear"
RULE_STALE_DATA_ACTION = "stale_critical_data_action"
RULE_HUMAN_APPROVAL = "human_approval_required"
RULE_RESTART_PROCEDURE = "restart_procedure"

_MAX_CHUNK_CHARS = 700

_WIND_PATTERN = re.compile(
    r"(?:maximum|max\.?|not\s+exceed|limit)[^.\n]{0,60}?"
    r"(?:wind|gust)[^.\n]{0,40}?(\d{1,3}(?:\.\d+)?)\s*(km/?h|kph|mph|m/s)",
    re.IGNORECASE,
)
_WIND_PATTERN_REVERSED = re.compile(
    r"(?:wind|gust)[^.\n]{0,60}?(?:maximum|max\.?|not\s+exceed|limit|above|over)[^.\n]{0,30}?"
    r"(\d{1,3}(?:\.\d+)?)\s*(km/?h|kph|mph|m/s)",
    re.IGNORECASE,
)
_LOAD_PATTERN = re.compile(
    r"(?:load|utilisation|utilization|capacity)[^.\n]{0,60}?(\d{1,3}(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)
_ZONE_PATTERN = re.compile(
    r"(?:exclusion\s+zone|zone)\s+([A-D])\b[^.\n]{0,80}?(clear|kept\s+clear|no\s+entry|closed)",
    re.IGNORECASE,
)
_STALE_PATTERN = re.compile(
    r"(?:stale|missing|unverified|no\s+update|out\s+of\s+date)[^.\n]{0,90}?"
    r"(escalate|escalation|stop|suspend)",
    re.IGNORECASE,
)
_APPROVAL_PATTERN = re.compile(
    r"(named|qualified|authorised|authorized|competent)[^.\n]{0,80}?"
    r"(approv\w*|sign[-\s]?off|permit)",
    re.IGNORECASE,
)
_RESTART_PATTERN = re.compile(r"(restart|resume|re-?commence)[^.\n]{0,80}?(lift|work|operation)", re.IGNORECASE)

_TAG_KEYWORDS = {
    "wind": ("wind", "gust", "weather"),
    "load": ("load", "utilisation", "utilization", "capacity", "swl"),
    "zone": ("zone", "exclusion", "barricade"),
    "approval": ("approval", "sign-off", "permit", "authorised", "authorized"),
    "freshness": ("stale", "telemetry", "sensor", "update"),
    "restart": ("restart", "resume", "recommence"),
    "personnel": ("worker", "personnel", "crew", "banksman", "signaller"),
}


@dataclass(slots=True)
class DetectedRule:
    ruleKey: str
    value: float | None
    unit: str | None


def extract_pages(path: Path) -> list[tuple[int, str]]:
    """Return (pageNumber, text) pairs. Markdown/plain text is split on headings so
    a citation can still point at a stable location."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(str(path))
        return [
            (index + 1, (page.extract_text() or "").strip())
            for index, page in enumerate(reader.pages)
        ]

    text = path.read_text(encoding="utf-8", errors="replace")
    if suffix in {".md", ".markdown"}:
        sections: list[tuple[int, str]] = []
        current: list[str] = []
        for line in text.splitlines():
            if line.startswith("## ") and current:
                sections.append((len(sections) + 1, "\n".join(current).strip()))
                current = [line]
            else:
                current.append(line)
        if current:
            sections.append((len(sections) + 1, "\n".join(current).strip()))
        return [section for section in sections if section[1]]
    return [(1, text.strip())]


def chunk_text(text: str) -> list[str]:
    paragraphs = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    chunks: list[str] = []
    buffer = ""
    for paragraph in paragraphs:
        if not buffer:
            buffer = paragraph
        elif len(buffer) + len(paragraph) + 2 <= _MAX_CHUNK_CHARS:
            buffer = f"{buffer}\n\n{paragraph}"
        else:
            chunks.append(buffer)
            buffer = paragraph
    if buffer:
        chunks.append(buffer)
    return chunks


def _to_kmh(value: float, unit: str) -> tuple[float, str]:
    normalised = unit.lower().replace("/", "")
    if normalised in {"kmh", "kph"}:
        return value, "km/h"
    if normalised == "mph":
        return round(value * 1.609344, 1), "km/h"
    if normalised == "ms":
        return round(value * 3.6, 1), "km/h"
    return value, unit


def detect_rules(text: str) -> list[DetectedRule]:
    """Find machine-checkable limits stated in a chunk."""
    rules: list[DetectedRule] = []

    wind_match = _WIND_PATTERN.search(text) or _WIND_PATTERN_REVERSED.search(text)
    if wind_match:
        value, unit = _to_kmh(float(wind_match.group(1)), wind_match.group(2))
        rules.append(DetectedRule(RULE_MAX_WIND_GUST, value, unit))

    load_match = _LOAD_PATTERN.search(text)
    if load_match:
        rules.append(DetectedRule(RULE_MAX_LOAD_UTILISATION, float(load_match.group(1)), "%"))

    zone_match = _ZONE_PATTERN.search(text)
    if zone_match:
        rules.append(DetectedRule(RULE_EXCLUSION_ZONE_CLEAR, None, zone_match.group(1).upper()))

    if _STALE_PATTERN.search(text):
        rules.append(DetectedRule(RULE_STALE_DATA_ACTION, None, "ESCALATE"))

    if _APPROVAL_PATTERN.search(text):
        rules.append(DetectedRule(RULE_HUMAN_APPROVAL, None, None))

    if _RESTART_PATTERN.search(text):
        rules.append(DetectedRule(RULE_RESTART_PROCEDURE, None, None))

    return rules


def derive_tags(text: str) -> list[str]:
    lowered = text.lower()
    return sorted(
        tag for tag, keywords in _TAG_KEYWORDS.items() if any(word in lowered for word in keywords)
    )


def build_document_chunks(
    *,
    path: Path,
    document_id: str,
    source_id: str,
    title: str,
    checksum: str | None = None,
) -> list[DocumentChunk]:
    """Turn one local document into retrievable, rule-tagged chunks.

    A chunk that states several limits is emitted once per limit so the retrieval
    agent can cite the precise rule it applied.
    """
    records: list[DocumentChunk] = []
    for page_number, page_text in extract_pages(path):
        for chunk_index, chunk in enumerate(chunk_text(page_text)):
            rules = detect_rules(chunk)
            tags = derive_tags(chunk)
            if not rules:
                records.append(
                    DocumentChunk(
                        documentId=document_id,
                        sourceId=source_id,
                        title=title,
                        page=page_number,
                        chunkIndex=chunk_index,
                        text=chunk,
                        tags=tags,
                        localPath=str(path),
                        checksum=checksum,
                    )
                )
                continue
            for rule in rules:
                records.append(
                    DocumentChunk(
                        documentId=document_id,
                        sourceId=source_id,
                        title=title,
                        page=page_number,
                        chunkIndex=chunk_index,
                        text=chunk,
                        tags=tags,
                        ruleKey=rule.ruleKey,
                        ruleValue=rule.value,
                        ruleUnit=rule.unit,
                        localPath=str(path),
                        checksum=checksum,
                    )
                )
    return records
