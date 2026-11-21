# RiskTwin

Local multimodal safety sentinel for a single critical lift: **LIFT-042**.

It turns a site walkthrough, a crew radio clip, recorded equipment/weather telemetry, a live worker-zone event, and the approved lift-plan rules into an evidence-backed `CONDITIONAL APPROVAL`, `HOLD`, or `ESCALATE` recommendation plus a targeted alert to the worker already near the hazard.

RiskTwin is **decision support**. A named human approves every lift clearance. It never commands a crane, never identifies people by face, never tracks a worker outside an active safety case, and never sends site data or model requests off the host.

## What this build is {and is not}

| Claim | Honest scope |
| --- | --- |
| Spatial twin | A **2.5D** versioned operational zone map plus a real, local **COLMAP sparse 3D reconstruction** made from the walkthrough video. It is not survey-grade geometry. |
| Always-on | A Data Watcher plus a change feed. On the Mac this is a local journal; on the Dell it is MongoDB Change Streams. |
| Multimodal | Sampled still frames + local ASR/transcript + telemetry + documents. The text model never “watches” video. |
| Multi-agent | Named specialist roles writing structured evidence. Specialisation is prompts, tools and stored state — not several giant models. |
| Required stack | OpenClaw, NemoClaw, OpenShell and MongoDB. On the Mac they run as documented **shims** with the same contracts; on the Dell they switch to native via `.env.dgx`. |

The demo question is: **can we safely start/restart Lift 042?** The expected answer after the staged anomalies is `HOLD` or `ESCALATE`.

## Two host profiles

Switching from this MacBook to the Dell GB10 is a profile copy, not a code change.

| Profile | File | Storage | Inference | Frameworks |
| --- | --- | --- | --- | --- |
| Build console (this Mac) | `.env.mac` | append-only file journal | deterministic local adapters | shims |
| Runtime host (Dell GB10) | `.env.dgx` | MongoDB replica set + Change Streams | local OpenAI-compatible servers | native OpenClaw / NemoClaw / OpenShell |

```bash
cp .env.mac .env    # MacBook
cp .env.dgx .env    # Dell, after transfer
```

See [docs/DGX_DEPLOY.md](docs/DGX_DEPLOY.md) for the Dell bring-up.

## MacBook runbook

Requires Python 3.11+, Node 20+, and the repo at the workspace root. No MongoDB and no model download.

```bash
# 1. Python env
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.mac .env

# 2. Prove the inference path is local (must pass before anything else)
python scripts/smoke_test_local_inference.py

# 3. Prepare the store, import the cleared corpus
python scripts/bootstrap_mongo.py
python scripts/ingest_cleared_data.py

# 4. Optional: drive the whole LIFT-042 sequence in-process
python scripts/replay_scenario.py --reset

# 5. API
python -m uvicorn apps.api.main:app --host 0.0.0.0 --port 8000

# 6. Dashboard + worker page (second terminal)
cd apps/dashboard
npm install
npm run dev
```

- Controller dashboard: [http://127.0.0.1:3000](http://127.0.0.1:3000)
- Worker page: [http://127.0.0.1:3000/worker](http://127.0.0.1:3000/worker)
- API: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

On a private demo LAN, phones scan the dashboard QR (or load `http://<host-lan-ip>:3000/worker`). Only the Worker API/dashboard is reachable; model ports and MongoDB stay bound to loopback on the Dell.

### Drop-in media (you supply)

| Path | What to put there |
| --- | --- |
| `data/raw/video/` | 15–25 s team-recorded `.mp4`, optional `<clip>.mp4.meta.json` zone regions |
| `data/raw/audio/` | 8–15 s 16 kHz mono `.wav`. If no ASR is served, also `<clip>.wav.transcript.txt` |

Without those files the system still runs: missing visual/audio evidence **escalates** and is never fabricated. Then click **run media review** on the dashboard. With COLMAP installed, choose **COLMAP 3D → build 3D from video** to sample the latest MP4, match its sequential views, solve camera poses, and render the resulting point cloud. Set `RISKTWIN_COLMAP_BINARY` when the executable is outside `PATH`.

### Demo controls on the dashboard

1. **Import documents** — retrieval changes the case from `ESCALATE` (no applicable rule) to `CONDITIONAL APPROVAL` when telemetry is in limit.
2. **Start replay** — the recorded LIFT-042 trace (wind, load, worker, gateway stale).
3. Have a teammate scan the worker QR, join `/worker`, and pick **Zone C**.
4. Open **COLMAP 3D** to inspect or rebuild the walkthrough reconstruction.
5. **Issue lift clearance** / **Command the crane** / **request raw clip** — OpenShell blocks or holds for a named human.
6. Restart the API process. The case and its decision come back from the store (`recovered from store` on the banner).

The 90-second pitch is in [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).

## How retrieval changes the decision

This is the rubric-critical behaviour (spec section 7.5).

1. With no lift plan indexed, the Commander **cannot** authorise anything. Decision = `ESCALATE` (“no applicable rule”).
2. Importing `data/raw/documents/lift-plan-042.md` writes rule-bearing chunks. The Rules Retrieval agent cites **max gust 42 km/h** and **max load 85%**.
3. With those limits in the store and in-limit telemetry, the decision becomes `CONDITIONAL APPROVAL`.
4. A later event changes it again without re-prompting a model to “decide”:
   - worker in Zone C during an active lift → `HOLD`
   - gust 46 km/h → `HOLD`, arithmetic `46 − 42 = 4`, citation `lift-plan-042:p3`
   - floor gateway stale past its SLA → `ESCALATE`

The LLM, when served, only composes the narrative. Thresholds, zones and freshness are deterministic.

## Required stack (one sentence each)

| Framework | Role | This Mac | Dell |
| --- | --- | --- | --- |
| **OpenClaw** | Hosts the named specialist agent roles that write structured evidence back to the case store. | in-process runtime with the same contracts, concurrency limit and run journal | `RISKTWIN_AGENT_RUNTIME=openclaw` |
| **NemoClaw** | Manages sandbox lifecycle and local inference routing on the DGX host. | local process lifecycle; durable state is in the store | `RISKTWIN_LIFECYCLE=nemoclaw` |
| **OpenShell** | Confines the agent sandbox: denies public egress, raw-media export and equipment actuation; requires a named human before a lift clearance. | auditable shim against `config/openshell-policy.yaml` | `RISKTWIN_OPENSHELL_BACKEND=native` |
| **MongoDB** | Durable evidence/event store, retrieval source and recovery layer; its change feed drives the agent loop. | file journal with the same change-feed semantics | Community Server replica set + Change Streams |

The dashboard **Stack, models and replay** panel reports `native` vs `shim` for each. Do not claim a framework that is not actually running.

## Models

Configured names live in `.env.dgx`. Nothing is downloaded by this repository.

| Modality | Intended DGX model | MacBook adapter |
| --- | --- | --- |
| Text (shared agent model) | NVIDIA Nemotron 3.5 Lightning 30B A3B NVFP4 at `127.0.0.1:8001` | deterministic risk engine + template narrative (`degraded model mode`) |
| Vision | NVIDIA Nemotron Nano 12B v2 VL NVFP4-QAD on **sampled frames** at `127.0.0.1:8002` | OpenCV median-diff + HOG people detector; findings labelled as candidates |
| Speech | NVIDIA Parakeet Unified English 0.6B at `127.0.0.1:8003` | operator transcript sidecar only; missing audio is reported unavailable |

Fallback ladder (Dell, in order): Lightning 30B → Super 120B (only if already loaded) → Llama 3.1 Nemotron 70B GGUF → Nano 4B (label degraded). Vision fallbacks: Nano VL 8B → Qwen2.5-VL-7B → deterministic CV. Speech fallback: Parakeet TDT 0.6B v3.

`scripts/smoke_test_local_inference.py` fails if any configured endpoint is not local, or if source files mention a hosted LLM/ASR/vision/weather hostname.

## Tests

```bash
source .venv/bin/activate
python -m pytest tests -q
```

Coverage maps to spec section 14: every modality writes a labelled record; the Orchestrator schedules only relevant agents; retrieval and new events change the decision; a stale critical source escalates; a worker in the exclusion zone is alerted and the ack is durable; a process restart restores the case; safety-critical actions stay blocked; endpoints are local-only; missing media is never fabricated.

## Layout

```text
apps/api/                 FastAPI ingest, case API, change-feed worker
apps/dashboard/           Controller dashboard + /worker
agents/                   Orchestrator + six specialists + policy gate
packages/                 Contracts, store, site model, inference, risk engine, replay
scripts/                  bootstrap, ingest, data-watcher, replay, smoke-test
config/                   OpenShell policy + approved source registry
data/raw/                 Cleared inputs (media gitignored; documents committed)
data/ATTRIBUTION.md       Every non-authored or team-authored asset
docs/RISK_TWIN_BUILD_SPEC.md
docs/DEMO_SCRIPT.md
docs/DGX_DEPLOY.md
```

## Closing statement

RiskTwin is a local AI safety co-pilot for critical construction lifts. It sees a site walkthrough, hears the crew, retrieves the approved lift rules, reacts to live site events, and produces an auditable hold-or-clear decision. Its intelligence is multimodal and multi-agent; its memory and recovery live in MongoDB (or the local journal on a build console); and OpenShell ensures it cannot turn a recommendation into an unsafe autonomous action.
