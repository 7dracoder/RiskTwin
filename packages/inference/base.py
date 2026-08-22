"""Shared inference types and the local-only HTTP client.

Every model call in the agent runtime path goes through here, so there is exactly
one place where a hosted endpoint could sneak in — and it is guarded.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from packages.config import Settings, assert_local_endpoint


@dataclass(slots=True, frozen=True)
class ModelRef:
    """What actually produced a result, so the UI can label degraded mode honestly."""

    modality: str
    backend: str
    model: str
    degraded: bool
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "modality": self.modality,
            "backend": self.backend,
            "model": self.model,
            "degraded": self.degraded,
            "note": self.note,
        }

    @property
    def label(self) -> str:
        return f"{self.backend}:{self.model}"


def local_client(base_url: str, timeout: float, settings: Settings, *, label: str) -> httpx.AsyncClient:
    if not settings.allow_remote_inference:
        assert_local_endpoint(base_url, label=label)
    return httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        timeout=timeout,
        # No proxy, no redirect off-host: a local endpoint must stay local.
        trust_env=False,
        follow_redirects=False,
    )


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def parse_json_response(text: str) -> dict[str, Any] | None:
    """Models wrap JSON in prose or fences more often than they should."""
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK.search(text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None
