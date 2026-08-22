# Data and model attribution

Every non-code asset used by RiskTwin, and the models the runtime-host profile is configured to load. Nothing in this file is a hosted API.

RiskTwin will not run a demo that depends on uncleared footage, a scraped web source, or a model endpoint off the Dell.

## Team-authored documents (committed)

| Asset | Path | Origin | Licence |
| --- | --- | --- | --- |
| Critical Lift Plan — LIFT-042 (rev 3) | `data/raw/documents/lift-plan-042.md` | Team-authored. Project-specific limits transcribed from the build spec section 4.2 demo trace. **Not** a customer document. | Team-authored, unrestricted use by this team. |
| Safety SOP — Crane and Suspended Load Operations | `data/raw/documents/safety-sop-crane-operations.md` | Team-authored generic controls. **Not** a copy of any published standard. | Team-authored, unrestricted use by this team. |

Replace either file with a cleared customer PDF plus a matching `.meta.json` before a scored demo if the organizers supply one.

## Team-authored site model and telemetry (committed)

| Asset | Path | Origin | Licence |
| --- | --- | --- | --- |
| Site model v1 (floors F12/F13, zones A–D) | `data/site-models/site-042-v1.json` | Team-authored annotated plan. Not derived from photogrammetry. | Team-authored. |
| Recorded / simulated site telemetry trace | `data/recordings/lift-042-trace.json` | Authored from spec section 4.2 staged anomaly sequence. **No physical sensor was present.** Every replayed event carries `source: "recorded-replay"` and `isSimulated: true`. | Team-authored. |

Do not describe the trace as live sensor data in the pitch.

## Operator-supplied media (not committed)

Place files locally; they are gitignored because raw video/audio may contain identifiable people, plates or site layout.

| Asset | Path | Rule |
| --- | --- | --- |
| Site walkthrough | `data/raw/video/*.mp4` | Team-recorded or explicitly licensed only. Optional `<clip>.mp4.meta.json` names the zones visible in the frame. |
| Crew radio clip | `data/raw/audio/*.wav` | Team-recorded voice only. Optional operator transcript sidecar if no local ASR is served. |

Until those files exist, Vision Risk and Crew Comms write **unavailable** evidence and the case escalates. That is the correct failure, not a stub scene.

Processed artifacts (`data/processed/frames`, `transcripts`, `redacted`) are generated at run time and must not be treated as source media.

## Approved source registry

`config/sources.yaml` is the only allowlist the Data Watcher may ingest from. Live external fetch is **disabled** (`RISKTWIN_DATA_WATCHER_LIVE_FETCH=false`). Enabling it requires an organizer-confirmed non-LLM hostname written into the OpenShell policy `data_watcher_allow_hostnames` list.

## Models (runtime host)

None of these weights are in the repository. Record the **exact revision actually served** on the Dell in the submission README after smoke-test.

| Role | Configured id | Licence / card | Local serving |
| --- | --- | --- | --- |
| Shared text model | `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4` | NVIDIA model card, local use on GB10 | `http://127.0.0.1:8001/v1` |
| Optional larger text | `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4` | NVIDIA | only if already loaded |
| Optional GGUF fallback | `bartowski/Llama-3.1-Nemotron-70B-Instruct-HF-GGUF` | Llama 3.1 community GGUF | llama.cpp on loopback |
| Degraded text fallback | `nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF` | NVIDIA | label “degraded model mode” |
| Vision | `nvidia/NVIDIA-Nemotron-Nano-12B-v2-VL-NVFP4-QAD` | NVIDIA; **single-image** inference on sampled frames | `http://127.0.0.1:8002/v1` |
| Vision fallback | `nvidia/Llama-3.1-Nemotron-Nano-VL-8B-V1` | NVIDIA | same |
| Vision last fallback | `Qwen/Qwen2.5-VL-7B-Instruct` | Qwen / Tongyi | only if neither NVIDIA VLM starts |
| Speech | `nvidia/parakeet-unified-en-0.6b` | NVIDIA | `http://127.0.0.1:8003/v1` |
| Speech fallback | `nvidia/parakeet-tdt-0.6b-v3` | NVIDIA | local GGUF / runtime |

On the MacBook build-console profile no model is served. Adapters are:

- text: `rule-engine+template-composer`
- vision: `opencv-median-diff+hog-people/1` (OpenCV 4.x, BSD)
- speech: operator transcript sidecar

## Software licences used by the local adapters

| Package | Role | Licence (upstream) |
| --- | --- | --- |
| FastAPI / Pydantic / Uvicorn | API | MIT |
| pymongo | MongoDB driver | Apache-2.0 |
| OpenCV (headless 4.x) | frame sample, CV observations, redaction | Apache-2.0 |
| Next.js / React | dashboard | MIT |
| MongoDB Community Server | runtime-host store | SSPL (server only; not shipped in this repo) |

## What we do not use

- Hosted LLM, ASR, vision, embedding or weather APIs
- Public web scrape as a knowledge source
- Facial recognition or biometric identification
- Any dataset that identifies a real worker
