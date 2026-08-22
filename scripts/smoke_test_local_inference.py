#!/usr/bin/env python3
"""Prove the inference path is local, then exercise one request per modality.

Three independent checks (spec sections 8.3 and 14):

1. Configuration — every configured model endpoint must resolve to this host or a
   private LAN address. A public DNS name or address fails the run.
2. Source scan — no source file may reference a hosted LLM, ASR, vision,
   embedding or weather API hostname.
3. Live request — one real text, vision and speech call through the same
   adapters the agents use, reporting backend, model and latency.

Run this before building anything else on a new host, and again before the final
demo with public egress denied.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import time
from pathlib import Path

from _common import banner, configure_logging, field  # noqa: I001 - fixes sys.path

from packages.config import get_settings, is_local_endpoint
from packages.inference import build_inference_suite
from packages.media.frames import sample_frames
from packages.runtime import framework_status

# Hostnames that would mean inference left the machine. Matched against source
# text, so a URL in a comment fails the check too — that is intentional.
FORBIDDEN_HOSTS = [
    "api.openai.com",
    "api.anthropic.com",
    "generativelanguage.googleapis.com",
    "api.cohere.ai",
    "api.mistral.ai",
    "api.groq.com",
    "api.together.xyz",
    "api.replicate.com",
    "api-inference.huggingface.co",
    "api.deepgram.com",
    "api.assemblyai.com",
    "api.elevenlabs.io",
    "api.openweathermap.org",
    "api.weatherapi.com",
    "api.open-meteo.com",
    "integrate.api.nvidia.com",
    "api.nvcf.nvidia.com",
    "bedrock-runtime",
    "openai.azure.com",
]

SCANNED_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".yaml", ".yml", ".sh"}
SKIPPED_DIRS = {
    ".git", ".venv", "node_modules", "__pycache__", ".next", ".pytest_cache",
    "data", ".ruff_cache", ".mypy_cache", "tests",
}


def scan_sources(root: Path) -> list[tuple[Path, str, int]]:
    """Return (file, host, line) for every forbidden hostname reference."""
    pattern = re.compile("|".join(re.escape(host) for host in FORBIDDEN_HOSTS))
    hits: list[tuple[Path, str, int]] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
            continue
        if any(part in SKIPPED_DIRS for part in path.parts):
            continue
        if path.name == Path(__file__).name:
            continue  # this file lists the hostnames on purpose
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            match = pattern.search(line)
            if match:
                hits.append((path.relative_to(root), match.group(0), number))
    return hits


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-requests", action="store_true", help="only run the static checks"
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)

    settings = get_settings()
    failures: list[str] = []

    banner("1. Configured endpoints")
    field("host profile", settings.host_profile)
    field("allow remote inference", settings.allow_remote_inference)
    field("data watcher live fetch", settings.data_watcher_live_fetch)
    endpoints = settings.inference_endpoints()
    if not endpoints:
        field("endpoints", "none — deterministic local adapters only")
    for label, url in endpoints.items():
        ok, detail = is_local_endpoint(url)
        field(label, f"{url}  {'LOCAL' if ok else 'NOT LOCAL'}  ({detail})")
        if not ok:
            failures.append(f"{label} endpoint {url} is not local: {detail}")
    if settings.allow_remote_inference:
        failures.append(
            "RISKTWIN_ALLOW_REMOTE_INFERENCE is true; the local-only guard is disabled"
        )

    banner("2. Source scan for hosted API hostnames")
    hits = scan_sources(settings.path("."))
    if hits:
        for path, host, number in hits:
            field(str(path), f"line {number}: {host}")
            failures.append(f"{path}:{number} references hosted endpoint {host}")
    else:
        field("result", f"clean — none of {len(FORBIDDEN_HOSTS)} hosted hostnames appear")

    banner("3. Framework and storage disclosure")
    for item in framework_status(settings):
        field(item["name"], f"{item['mode']:<7} configured={item['configured']}")

    if args.skip_requests:
        return _finish(failures)

    models = build_inference_suite(settings)
    banner("4. One live request per modality")
    for name, ref in models.model_refs().items():
        field(f"{name} adapter", f"{ref['backend']} / {ref['model']}")

    started = time.perf_counter()
    text_result = await models.text.complete_json(
        system="You are a construction safety assistant. Reply with JSON only.",
        user='Reply exactly: {"ok": true, "check": "local"}',
    )
    field(
        "text call",
        f"{(time.perf_counter() - started) * 1000:.0f} ms -> "
        + (
            f"served, keys={sorted(text_result)}"
            if text_result
            else "no served text model; deterministic composition in use"
        ),
    )

    video = _first_media(settings.path(settings.raw_video_dir), (".mp4", ".mov", ".m4v", ".avi"))
    if video is None:
        field("vision call", f"no clip in {settings.raw_video_dir}; skipped")
    else:
        started = time.perf_counter()
        frames = sample_frames(
            video,
            count=min(3, settings.frame_sample_count),
            output_dir=settings.path(settings.frame_dir),
        )
        observations = await models.vision.observe(frames, {})
        field(
            "vision call",
            f"{(time.perf_counter() - started) * 1000:.0f} ms -> {len(frames)} frames sampled, "
            f"{len(observations)} observation(s)",
        )
        for observation in observations[:3]:
            field("  observation", f"{observation.riskType} conf={observation.confidence:.2f}")

    audio = _first_media(settings.path(settings.raw_audio_dir), (".wav", ".flac", ".m4a", ".mp3"))
    if audio is None:
        field("speech call", f"no clip in {settings.raw_audio_dir}; skipped")
    else:
        started = time.perf_counter()
        transcript = await models.speech.transcribe(audio)
        field(
            "speech call",
            f"{(time.perf_counter() - started) * 1000:.0f} ms -> "
            f"available={transcript.available} source={transcript.transcriptSource}",
        )
        if transcript.text:
            field("  transcript", transcript.text[:88])

    await models.close()
    return _finish(failures)


def _first_media(directory: Path, suffixes: tuple[str, ...]) -> Path | None:
    if not directory.exists():
        return None
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() in suffixes:
            return path
    return None


def _finish(failures: list[str]) -> int:
    banner("Result")
    if failures:
        field("verdict", "FAILED — the inference path is not provably local")
        for failure in failures:
            print(f"    - {failure}")
        return 1
    field("verdict", "PASS — no remote inference endpoint is configured or referenced")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
