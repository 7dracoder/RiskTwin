"""Runtime configuration, shared by the API, the agents and the scripts.

One settings object drives which storage backend, inference adapters and
framework integrations are active. Switching from the build console to the DGX is
a profile copy (`cp .env.dgx .env`), never a code change.
"""

from __future__ import annotations

import ipaddress
import socket
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[1]

# Loopback plus the RFC1918 / link-local ranges that a private event LAN uses.
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


class LocalOnlyViolation(RuntimeError):
    """Raised when a configured endpoint is not local to this machine or LAN."""


def is_local_endpoint(url: str) -> tuple[bool, str]:
    """Return (ok, detail). Resolves the host so a public DNS name cannot slip in."""
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return False, f"no hostname in {url!r}"
    if host in {"localhost", "localhost.localdomain"}:
        return True, "localhost"
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        return False, f"cannot resolve {host!r}: {exc}"
    addresses = {info[4][0] for info in infos}
    for address in addresses:
        try:
            parsed_ip = ipaddress.ip_address(address.split("%")[0])
        except ValueError:
            return False, f"unparseable address {address!r} for {host!r}"
        if not any(parsed_ip in net for net in _PRIVATE_NETWORKS):
            return False, f"{host!r} resolves to public address {address}"
    return True, f"{host} -> {sorted(addresses)}"


def assert_local_endpoint(url: str, *, label: str) -> None:
    ok, detail = is_local_endpoint(url)
    if not ok:
        raise LocalOnlyViolation(
            f"{label} endpoint is not local: {detail}. "
            "RiskTwin forbids hosted inference in the agent runtime path (spec 8.3)."
        )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RISKTWIN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    case_id: str = "LIFT-042"
    host_profile: Literal["build-console", "runtime-host"] = "build-console"

    # --- storage ---
    storage_backend: Literal["file", "mongodb"] = "file"
    mongodb_uri: str = "mongodb://127.0.0.1:27017/?replicaSet=rs0&directConnection=true"
    mongodb_db: str = "risktwin"
    state_dir: str = "data/state"

    # --- inference ---
    llm_backend: Literal["deterministic", "openai_compat", "ollama"] = "deterministic"
    llm_base_url: str = "http://127.0.0.1:8001/v1"
    llm_model: str = "nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4"
    llm_timeout_seconds: float = 90.0

    vlm_backend: Literal["deterministic", "openai_compat", "ollama"] = "deterministic"
    vlm_base_url: str = "http://127.0.0.1:8002/v1"
    vlm_model: str = "nvidia/NVIDIA-Nemotron-Nano-12B-v2-VL-NVFP4-QAD"
    vlm_timeout_seconds: float = 120.0

    asr_backend: Literal["deterministic", "openai_compat", "parakeet_mlx"] = "deterministic"
    asr_base_url: str = "http://127.0.0.1:8003/v1"
    asr_model: str = "nvidia/parakeet-unified-en-0.6b"
    asr_timeout_seconds: float = 120.0

    # --- framework integration ---
    openshell_backend: Literal["shim", "native"] = "shim"
    agent_runtime: Literal["inprocess", "openclaw"] = "inprocess"
    lifecycle: Literal["local", "nemoclaw"] = "local"

    # --- safety rails ---
    allow_remote_inference: bool = False
    data_watcher_live_fetch: bool = False

    # --- replay ---
    replay_speed: float = 1.0
    recording_path: str = "data/recordings/lift-042-trace.json"

    # --- site model ---
    site_model_path: str = "data/site-models/site-042-v1.json"

    # --- media / documents ---
    raw_video_dir: str = "data/raw/video"
    raw_audio_dir: str = "data/raw/audio"
    raw_document_dir: str = "data/raw/documents"
    frame_dir: str = "data/processed/frames"
    transcript_dir: str = "data/processed/transcripts"
    redacted_dir: str = "data/processed/redacted"
    frame_sample_count: int = Field(default=6, ge=1, le=24)

    # --- local COLMAP reconstruction ---
    reconstruction_dir: str = "data/processed/reconstruction"
    colmap_binary: str = "colmap"
    reconstruction_frame_count: int = Field(default=40, ge=8, le=120)
    reconstruction_max_dimension: int = Field(default=960, ge=480, le=2400)

    # --- policy / sources ---
    policy_path: str = "config/openshell-policy.yaml"
    sources_path: str = "config/sources.yaml"

    # --- service binding ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    def path(self, value: str) -> Path:
        candidate = Path(value)
        return candidate if candidate.is_absolute() else REPO_ROOT / candidate

    @property
    def degraded_mode(self) -> bool:
        """True when any modality is running on deterministic local code instead of a
        served model. The dashboard must say so rather than imply model quality."""
        return "deterministic" in {self.llm_backend, self.vlm_backend, self.asr_backend}

    def inference_endpoints(self) -> dict[str, str]:
        endpoints: dict[str, str] = {}
        if self.llm_backend != "deterministic":
            endpoints["text"] = self.llm_base_url
        if self.vlm_backend != "deterministic":
            endpoints["vision"] = self.vlm_base_url
        if self.asr_backend == "openai_compat":
            endpoints["speech"] = self.asr_base_url
        return endpoints

    def enforce_local_only(self) -> dict[str, str]:
        """Fail fast if a configured model endpoint is not on this host or LAN."""
        checked: dict[str, str] = {}
        for label, url in self.inference_endpoints().items():
            if self.allow_remote_inference:
                checked[label] = f"{url} (LOCAL-ONLY GUARD DISABLED)"
                continue
            assert_local_endpoint(url, label=label)
            checked[label] = url
        if self.storage_backend == "mongodb" and not self.allow_remote_inference:
            assert_local_endpoint(
                self.mongodb_uri.replace("mongodb://", "http://"), label="mongodb"
            )
            checked["mongodb"] = self.mongodb_uri
        return checked


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
