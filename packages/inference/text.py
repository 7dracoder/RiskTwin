"""Shared local text model.

One text model serves every agent role; specialisation comes from prompts, tools
and stored state, not from loading several large models (spec section 9.3).

The contract is deliberately narrow: a text model may only *return structured
JSON or nothing*. Callers always compute their deterministic result first and use
the model to improve wording or draft an action plan. A model outage therefore
degrades the prose, never the safety maths.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

import httpx

from packages.config import Settings
from packages.inference.base import ModelRef, local_client, parse_json_response

logger = logging.getLogger(__name__)


class TextModel(Protocol):
    info: ModelRef

    async def complete_json(
        self, *, system: str, user: str, example: dict[str, Any] | None = None
    ) -> dict[str, Any] | None: ...

    async def health(self) -> dict[str, Any]: ...

    async def close(self) -> None: ...


class NullTextModel:
    """No text model is served on this host.

    Returns nothing so callers fall back to their deterministic composition. This
    is the honest "degraded model mode" from spec section 9.2, not a silent stub
    that fabricates reasoning.
    """

    def __init__(self) -> None:
        self.info = ModelRef(
            modality="text",
            backend="deterministic",
            model="rule-engine+template-composer",
            degraded=True,
            note=(
                "No text model is served on this host. Decisions come from the "
                "deterministic risk engine and narratives from local templates."
            ),
        )

    async def complete_json(
        self, *, system: str, user: str, example: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        return None

    async def health(self) -> dict[str, Any]:
        return {"ok": True, "served": False, **self.info.as_dict()}

    async def close(self) -> None:
        return None


class OpenAICompatTextModel:
    """vLLM / NIM / llama.cpp server exposing an OpenAI-compatible route."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = local_client(
            settings.llm_base_url, settings.llm_timeout_seconds, settings, label="text"
        )
        self.info = ModelRef(
            modality="text",
            backend="openai_compat",
            model=settings.llm_model,
            degraded=False,
            note=f"served locally at {settings.llm_base_url}",
        )

    async def complete_json(
        self, *, system: str, user: str, example: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        payload: dict[str, Any] = {
            "model": self._settings.llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
            "max_tokens": 700,
            "response_format": {"type": "json_object"},
        }
        try:
            response = await self._client.post("/chat/completions", json=payload)
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            logger.warning("local text model unavailable (%s); using deterministic output", exc)
            return None
        return parse_json_response(content)

    async def health(self) -> dict[str, Any]:
        try:
            response = await self._client.get("/models")
            response.raise_for_status()
            return {"ok": True, "served": True, **self.info.as_dict()}
        except httpx.HTTPError as exc:
            return {"ok": False, "served": False, "error": str(exc), **self.info.as_dict()}

    async def close(self) -> None:
        await self._client.aclose()


class OllamaTextModel:
    """Local Ollama daemon; a convenience path for a non-DGX host."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = local_client(
            settings.llm_base_url, settings.llm_timeout_seconds, settings, label="text"
        )
        self.info = ModelRef(
            modality="text",
            backend="ollama",
            model=settings.llm_model,
            degraded=False,
            note=f"served locally at {settings.llm_base_url}",
        )

    async def complete_json(
        self, *, system: str, user: str, example: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        payload = {
            "model": self._settings.llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.1},
        }
        try:
            response = await self._client.post("/api/chat", json=payload)
            response.raise_for_status()
            content = response.json()["message"]["content"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            logger.warning("local Ollama text model unavailable (%s)", exc)
            return None
        return parse_json_response(content)

    async def health(self) -> dict[str, Any]:
        try:
            response = await self._client.get("/api/tags")
            response.raise_for_status()
            return {"ok": True, "served": True, **self.info.as_dict()}
        except httpx.HTTPError as exc:
            return {"ok": False, "served": False, "error": str(exc), **self.info.as_dict()}

    async def close(self) -> None:
        await self._client.aclose()


def build_text_model(settings: Settings) -> TextModel:
    if settings.llm_backend == "openai_compat":
        return OpenAICompatTextModel(settings)
    if settings.llm_backend == "ollama":
        return OllamaTextModel(settings)
    return NullTextModel()
