"""Local-first checks: no hosted inference endpoint can enter the runtime path."""

from __future__ import annotations

from packages.config import LocalOnlyViolation, Settings, is_local_endpoint
from httpx import AsyncClient


def test_loopback_endpoint_is_local() -> None:
    ok, detail = is_local_endpoint("http://127.0.0.1:8001/v1")
    assert ok is True
    assert "127.0.0.1" in detail or "localhost" in detail


def test_localhost_endpoint_is_local() -> None:
    ok, _ = is_local_endpoint("http://localhost:8002/v1")
    assert ok is True


def test_public_hostname_is_rejected() -> None:
    ok, detail = is_local_endpoint("https://api.openai.com/v1")
    assert ok is False
    assert "openai" in detail.lower() or "public" in detail.lower() or "cannot resolve" in detail.lower()


def test_settings_refuse_a_public_text_endpoint() -> None:
    settings = Settings(
        llm_backend="openai_compat",
        llm_base_url="https://api.openai.com/v1",
        allow_remote_inference=False,
    )
    try:
        settings.enforce_local_only()
    except LocalOnlyViolation as exc:
        assert "text" in str(exc)
        return
    raise AssertionError("a public text endpoint must fail the local-only guard")


async def test_inference_check_reports_all_local(client: AsyncClient) -> None:
    check = (await client.get("/api/system/inference-check")).json()
    assert check["allLocal"] is True
    assert check["allowRemoteInference"] is False
    system = (await client.get("/api/system")).json()
    assert system["degradedMode"] is True
    assert system["dataWatcherLiveFetch"] is False
