# RiskTwin / LiftLock — Hackathon Build Specification

> **Status:** Planning-only document. Do not implement the application, agent prompts, pipeline code, or dashboard before the on-site build window opens. This specification is the team’s day-of execution guide.

## 1. One-line pitch

**RiskTwin is an always-on, local multimodal safety sentinel for construction sites.** It converts existing site video, periodic walkthroughs, crew radio checks, live site conditions, worker-zone presence, and lift-plan rules into targeted worker risk alerts plus evidence-backed `APPROVE`, `HOLD`, or `ESCALATE` recommendations—without letting AI autonomously control equipment or leak site data.

## 2. Why this is a real corporate workflow

Critical lifts (steel, HVAC units, façade panels, etc.) require a site supervisor to reconcile several disconnected sources before work begins:

- what the site physically looks like now;
- whether the exclusion zone is clear;
- the wind and equipment state;
- crew confirmation over radio;
- the approved lift plan and safety procedure.

Today this is a manual, time-pressured approval process. RiskTwin produces a **digital lift-clearance package** with traceable evidence and a human sign-off, while its always-on mode sends narrowly targeted risk alerts to the workers already near an active hazard. It does not replace a qualified safety manager; it reduces the need for a person to stare at separate camera, telemetry, and radio feeds all day.

### The demo decision

> “Can we safely start/restart Lift 042?”

The expected demo answer is `HOLD`: the site video identifies an obstruction in the exclusion zone, a worker enters or approaches that zone, and/or wind crosses the retrieved lift-plan threshold.

---

## 3. Hackathon constraints and non-negotiable decisions

| Constraint | Build decision |
| --- | --- |
| Eight-hour sprint | Build one polished near-miss scenario, not a general construction platform. |
| All inference local on GB10 | Every model endpoint is local to the Dell machine. No hosted model, remote embedding API, or remote transcription API is permitted in the runtime path. |
| Required stack: at least two of NemoClaw, OpenClaw, OpenShell | Use all three: OpenClaw agent roles, NemoClaw lifecycle/onboarding, and OpenShell policy enforcement. |
| Best Use of MongoDB | MongoDB is the durable evidence/event store, retrieval source, and recovery layer—not a JSON-file substitute. |
| Content/IP | Use only team-recorded or explicitly licensed video/audio/document assets. Record each asset’s origin and license in the submission README. |
| Safety | The system may send a local risk alert to an opted-in, on-site worker device; a human approves a lift permit. It never commands a crane, sends data to external services, or identifies individuals by face. |

### Scope cut: “spatial risk twin,” not perfect 3D reconstruction

The product vision is a 3D model generated from a walkthrough. Building accurate structure-from-motion, calibrated world coordinates, and centimeter-level worker tracking from arbitrary video is too risky in eight hours.

The hackathon prototype therefore creates a **2.5D spatial risk twin**:

1. Start with an annotated site plan and a simple Three.js-style 3D-looking scene.
2. Sample four to six video frames from the provided walkthrough.
3. Map detected/confirmed hazards to named zones (`A`, `B`, `C`) on the site plan.
4. Stream worker location as a zone event from a mobile browser.
5. Draw and update risk polygons/zone states on the map.

Be precise in the pitch: **“We build a risk-aware spatial map from a walkthrough.”** Do not claim full survey-grade reconstruction.

### Persistent spatial-model decision

The walkthrough-derived model is saved as a **versioned local site model**, not recreated for every alert. It is the system’s coordinate reference for workers, equipment, risk zones, and evidence.

```text
Worker location event (floor, x, y, z / zone)
                    ↓
Versioned local site model
                    ↓
Point-in-zone / point-in-risk-volume check
                    ↓
Worker status: safe, approaching, inside risk zone, or coverage unknown
```

The model helps **interpret** a worker’s location; it does not determine that location on its own. The prototype obtains location from the SiteMesh Simulator. A production deployment would receive it from approved site positioning hardware (for example UWB/BLE/GNSS) through a local gateway.

---

## 4. Required inputs and cleared data

### 4.1 Assets for the single demo case

| Input | Format | Demo role | Source/rights rule |
| --- | --- | --- | --- |
| Site walkthrough | 15–25 second `.mp4` recorded by the team | Vision evidence: blocked exclusion zone, active lift area, route obstruction | Team-owned footage or an explicitly licensed asset only |
| Crew call | 8–15 second `.wav`/`.mp3` | Local speech-to-text evidence: “hold lift” or a conflicting “zone clear” statement | Team-recorded voice only |
| Lift plan | 1–3 page PDF | Retrieved threshold, zones, restart procedure | Team-authored or cleared public document |
| Safety SOP | 1–3 page PDF | Retrieved policy and required human approval | Team-authored or cleared public document |
| Operational readings | Local MongoDB event stream | Conditions that change over the demo: weather, equipment state, site access, and zone presence | Import the team's recorded or clearly labelled simulated telemetry trace during the event, then replay it locally; add live phone-zone events |
| Worker phone event | Mobile browser POST to the local app | A real changing input that enters a risk zone | A teammate uses the browser; use a role/alias, not personal identity |

### 4.2 Continuous Site Intelligence Ingestor

RiskTwin should not be a one-time wind checker. It has a **Data Watcher** that continuously keeps its local MongoDB knowledge current from an explicit, allowlisted source registry. The Data Watcher is a narrow ingestion component; the OpenClaw agents never browse or scrape arbitrary websites themselves.

```text
Approved source connector → validation/normalisation → MongoDB → Change Stream
                                                           ↓
                                              agents retrieve local facts only
```

Use three source classes, in priority order:

| Source class | Examples | Why the decision needs it | Prototype behavior |
| --- | --- | --- | --- |
| **Site-owned operational data** | Crane load/position, lift schedule, worker-zone/presence events, site access status | The highest-value inputs for a lift-clearance decision | Mobile browser emits real zone events; an equipment event generator/replay emits local crane state. |
| **External environmental data** | Wind gust, lightning, rainfall, heat warnings | Conditions can invalidate a lift after planning is complete | Import cleared official observations during the event and replay them locally. |
| **Business/regulatory knowledge** | Lift plan, equipment manual, safety bulletin, permit restriction, worker-certification status | The agent must know whether a condition violates a specific rule | Import cleared documents/records into MongoDB and retrieve the exact applicable rule. |

Each connector writes a source manifest with: `sourceId`, owner, license/terms, retrieval time, freshness SLA, schema version, and checksum. Raw facts are preserved; normalized facts are written to `site_events`, `telemetry`, or `documents`.

#### Hackathon default: recorded telemetry replay

For the sprint, do **not** scrape data and do not claim a physical sensor was present. Use a time-stamped **recorded telemetry dataset** and replay it locally as a controlled event stream. Do not describe it as “hard-coded sensor values” in the pitch; call it a **recorded/simulated site telemetry trace** and state its provenance honestly.

```text
Recorded telemetry trace
        ↓
Local Replay Engine on DGX
        ↓
MongoDB `site_events` + `telemetry`
        ↓
Change Stream wakes RiskTwin
```

The trace contains heat/temperature, wind gust, crane load/tilt, site-access, worker-zone, and gateway-status events. Import the original trace into MongoDB at startup, then replay it at 1×/2× speed; do not scatter values through agent code. Every replayed event carries `source: "recorded-replay"` and `isSimulated: true` unless the team can substantiate that the source was an actual cleared sensor recording.

```text
telemetry_recordings (immutable imported trace)
                    ↓
replay_state (case, playback position, speed, status)
                    ↓
site_events + telemetry (events arriving “now”)
                    ↓
agent evidence, decisions, alerts, acknowledgements
```

The replay engine persists `replay_state` in MongoDB. After an agent/sandbox restart, the system resumes the same case at the current replay position and preserves all previously generated evidence and actions.

The dashboard must display **“RECORDED / SIMULATED SITE TELEMETRY — REPLAY MODE”**. This is more credible than pretending the values are live sensor readings, while still proving that the real product responds continuously to changing operational facts.

#### Demo trace: `LIFT-042` staged anomaly sequence

Use one deterministic replay trace so every run tells the same clear story. The lift-plan document in the demo defines these project-specific limits:

- maximum wind gust: `42 km/h`;
- maximum planned load utilisation: `85%`;
- exclusion zone `C` must be clear whenever the lift is active;
- missing/stale critical telemetry means `ESCALATE`, not approval.

| Replay time | Recorded event | What the system should show |
| --- | --- | --- |
| `00:00` | Wind `24 km/h`, load `62%`, hydraulic temperature `46°C`, Zone C clear | Normal baseline; `CONDITIONAL APPROVAL` pending final checks. |
| `00:10` | Lift becomes active; wind `29 km/h`, load `71%` | Agents update the timeline; still within retrieved limits. |
| `00:18` | Drone/video evidence identifies material obstructing the Zone C boundary | Vision Agent writes medium-severity evidence; Commander requires zone confirmation. |
| `00:25` | Crew audio: “Zone C is clear” | Crew Comms Agent records the statement; it conflicts with visual evidence. |
| `00:32` | `worker-12` enters Zone C | Proximity Agent emits `STOP / ACK REQUIRED`; decision changes to `HOLD`. |
| `00:40` | Wind gust jumps from `29` to `46 km/h` | Threshold anomaly: exceeds the retrieved `42 km/h` limit; `HOLD` is reinforced. |
| `00:48` | Load utilisation rises to `89%` | Second independent threshold anomaly: exceeds `85%`; controller sees high-severity evidence. |
| `00:55` | Floor gateway has no update for longer than SLA | Source-freshness failure; decision changes to `ESCALATE` until coverage is verified. |

For the eight-hour minimum demo, implement the visual obstruction, worker-zone entry, and wind-threshold breach first. Add load utilisation and gateway-freshness events only after that core path is reliable.

The app should show each anomaly before showing the final narrative:

```text
ANOMALY DETECTED
Wind gust: 46 km/h
Lift-plan maximum: 42 km/h
Deviation: +4 km/h
Evidence: telemetry event #wind-046 + Lift Plan page 2
```

Then show the multi-agent conclusion:

```text
LIFT 042 — HOLD / ESCALATE

1. Worker-12 entered active exclusion Zone C.
2. Wind exceeded the retrieved lift-plan limit.
3. Load utilisation exceeded the planned limit.
4. Crew “zone clear” statement conflicts with visual evidence.
5. Floor-gateway freshness cannot be verified.
```

Build threshold checks as deterministic local code. The LLM explains the correlated evidence and drafts the action plan; it must not invent the anomaly calculation.

#### Runtime-network eligibility gate

The rule says **“No remote LLM/API calls in the agent’s runtime path.”** Read that conservatively. The safe, competition-ready mode is:

1. Acquire/import every external dataset during the on-site build window.
2. Run the whole final demo from local MongoDB, local models, and local services only.
3. Replay incoming data locally so the decision still changes live.

Only enable a live external data connector if an organizer explicitly confirms that polling a non-LLM public-data source is permitted. If approved, place it in a separate, OpenShell-restricted Data Watcher with a fixed allowlist and no model access. The agents still retrieve only from local MongoDB. Never depend on that connector for the final demo.

Do **not** scrape arbitrary websites. It is unreliable, may violate site terms, creates supply-chain risk, and undermines the local-first story. Prefer documented, official, licensed feeds or file exports, with attribution recorded in `data/ATTRIBUTION.md`.

Wi-Fi gives the Data Watcher a transport path; it does not make external inference acceptable. A production Data Watcher may use an explicitly approved network connection to collect source data, normalize it, and update MongoDB. The Vision, ASR, embedding, and Nemotron agents must continue to run only on the local Dell machine and must read the collected facts from MongoDB, not from the web. The hackathon build uses the local recorded-telemetry Replay Engine instead.

#### Freshness is a safety feature

The Data Watcher must mark every source as `fresh`, `stale`, or `unavailable` against its configured SLA. A stale critical source changes the agent’s behavior:

```text
Wind data stale for 7 minutes; allowed freshness is 2 minutes.
Decision: ESCALATE
Reason: Current environmental condition cannot be verified.
```

This makes continuous data ingestion meaningful, rather than adding feeds merely for show.

### 4.3 Location limitation

Ordinary phone GPS is not dependable enough for a tight crane exclusion zone, particularly around tall structures. The prototype sends named-zone events, for example `worker-12 → Zone C`.

Production deployment would use consented company devices with UWB/BLE anchors or another site-approved positioning method. RiskTwin must remain purpose-limited to active safety operations, not general workforce surveillance.

### 4.4 Always-on monitoring and direct worker alerts

The DGX can operate as an always-on **site sentinel**. It does not need a person continually watching a wall of screens, and it does not need a drone in the air all day.

| Continuous source | Normal site counterpart | RiskTwin behavior |
| --- | --- | --- |
| Fixed camera at a high-risk zone | Existing gate, lift, loading, or crane-area camera | Local CV produces a lightweight scene/risk update every few seconds. A drone/phone walkthrough is used only after a layout change or to inspect a blind spot. |
| Equipment/site telemetry | Crane, wind, access, or local IoT system | Data Watcher updates the risk state as facts arrive. |
| Worker device | Company-managed phone/PWA on local site Wi-Fi | Sends purpose-limited zone presence and receives a local alert over WebSocket/local network. |
| Policies/documents | Lift plan, safety SOP, permit conditions | Retrieved whenever a risk requires an explanation or a decision. |

The always-on loop must be resource-aware. Do not ask a 30B model to reason about every video frame. Use deterministic proximity/threshold checks for high-frequency events, and invoke the text model only when the risk state changes, sources conflict, a worker enters a risk zone, or a manager asks for an explanation.

```text
Local camera/telemetry/location update
                ↓
Fast deterministic zone + threshold evaluation
                ↓
No material change → record event only
Material risk change → update MongoDB risk state
                ↓
Worker inside/approaching risk zone?
       ├─ no  → notify controller only if severity is critical
       └─ yes → send local worker alert + require acknowledgement
                ↓
        no acknowledgement / critical condition → escalate to site controller
                ↓
        local agents assemble evidence and recommended action
```

#### Alert tiers

| Tier | Trigger | Direct worker experience | Controller experience |
| --- | --- | --- | --- |
| `INFO` | Route/zone awareness | No interruptive alert | Timeline only |
| `CAUTION` | Worker is approaching a dynamic risk zone | “Caution: Crane 4 active ahead. Use East corridor.” | Alert card |
| `STOP / ACK REQUIRED` | Worker is inside an active exclusion zone, or a rule threshold is breached | “Stop. Do not enter Zone C. Active suspended-load risk.” plus acknowledge button | High-priority alert and acknowledgement timer |
| `ESCALATE` | Critical source stale, conflicting evidence, or no acknowledgement | “Move to a safe area and contact supervisor.” | Site manager receives evidence bundle; human decides next step |

For the prototype, a local browser notification/banner and acknowledgement button is enough. A production deployment would integrate a site-approved device-management/notification channel after a safety review.

---

## 5. What makes it genuinely multimodal

RiskTwin does not describe one text prompt as “multimodal.” Each input becomes a locally generated, timestamped evidence item:

| Modality | Local processing | Output written to MongoDB |
| --- | --- | --- |
| Video | Sample frames; local detector/VLM identifies relevant scene facts and maps them to a site zone | `video_observation` with frame timestamp, zone, finding, confidence |
| Audio | Local ASR transcribes the crew call; text model extracts instruction, equipment, and urgency | `audio_observation` with transcript, speaker role if known, and safety intent |
| Documents | Local PDF text extraction/OCR; document chunks are indexed for retrieval | `policy_evidence` with document/page/chunk reference |
| Operational data | Local event ingestion validates wind/load values and compares them with thresholds | `telemetry_observation` with source, time, reading, threshold state |
| Worker position | Local mobile app posts zone/location event | `proximity_observation` with worker alias, current zone, and risk-zone relation |

The Commander must cite at least two independent evidence types before it can move a case to `APPROVE` or `HOLD`. If evidence conflicts or is missing, the only valid answer is `ESCALATE`.

### 5.1 Privacy-preserving video output

The uploaded drone video may contain workers, faces, vehicles, licence plates, or sensitive site layout. RiskTwin therefore has two separate local artifacts:

| Artifact | Access | Purpose |
| --- | --- | --- |
| **Raw source video** | Restricted to the local processing workspace; never downloadable from the dashboard | Frame extraction and locally scoped analysis only |
| **Redacted evidence video** | Dashboard preview/download | Gaussian-blurred/pixelated identities plus risk-zone, hazard, and timestamp overlays |

The local redaction pipeline is:

```text
Raw local drone video
        ↓
Local face/person/plate detection
        ↓
Face blur; if face detection is uncertain, pixelate the entire person box
        ↓
Add non-identifying labels (worker-1, worker-2), zone/risk overlays, and timestamps
        ↓
Write redacted MP4 + redaction manifest locally
```

Use a local CV detector plus OpenCV-style blur/pixelation. The VLM is the visual **reasoning** model; it is not the pixel-level redaction tool. The safest prototype approach is to use person boxes as a fallback when high-angle drone footage makes faces too small to detect reliably.

The app should never claim it has “fixed” or “corrected” the site. Its output is a **redacted safety-evidence video**: it shows what the system observed, which zone is at risk, and why it recommended `HOLD` or `ESCALATE`.

Store a `redaction_manifest` record in MongoDB with the input hash, detection/redaction model version, redacted frame ranges, output hash, and timestamp. OpenShell policy must deny raw-video export and permit only the redacted output to be previewed or downloaded.

### 5.2 Durable spatial model and worker-location resolution

Store the visual site artifact locally as a `.glb`/scene JSON or simple site-plan image, and store its authoritative metadata in MongoDB. For the hackathon, keep the geometry simple and reliable: floors plus named 2D polygons with an elevation/range, rather than a complex survey-grade mesh.

```json
{
  "siteModelId": "site-042",
  "version": 1,
  "coordinateFrame": { "name": "local-site-grid", "units": "meters", "origin": "south-west ground corner" },
  "asset": { "localPath": "data/site-models/site-042-v1.glb", "sha256": "<hash>" },
  "floors": [
    { "floorId": "F12", "elevationMeters": 36 },
    { "floorId": "F13", "elevationMeters": 39 }
  ],
  "zones": [
    { "zoneId": "A", "floorId": "F12", "polygon": [[0,0],[8,0],[8,5],[0,5]], "kind": "safe-route" },
    { "zoneId": "C", "floorId": "F12", "polygon": [[8,0],[14,0],[14,6],[8,6]], "kind": "lift-exclusion" }
  ]
}
```

When a location event arrives, the non-LLM risk engine resolves it against the current site-model version:

```text
worker-12 @ F12, x=10.1, y=2.8
             ↓
site-042, version 1
             ↓
inside Zone C / active lift-exclusion risk
             ↓
send STOP / ACK REQUIRED; store decision evidence
```

Do not overwrite a model after a new walkthrough. Create `site-042:version-2`, preserve the old model/evidence linkage, and make the controller explicitly choose the active version. That is how the audit trail can answer which layout the system used for a given alert.

### Multimodal event example

```text
Video frame @ 10:18:02  → Zone C obstructed
Audio @ 10:18:05        → “Hold the lift”
Wind event @ 10:18:08   → 46 km/h
Lift-plan retrieval     → Maximum permitted gust: 42 km/h
Phone event @ 10:18:11 → worker-12 entered Zone C

Commander result        → HOLD
```

---

## 6. Multi-agent loop

### 6.1 Agent roster

Multi-agent means specialized roles with separate structured outputs and shared durable state. It does **not** mean loading five 70B models at the same time. Agent roles share one locally served text model and call their local tools concurrently with a small concurrency limit.

| Agent | Trigger | Reads | Writes | Responsibility |
| --- | --- | --- | --- | --- |
| **Data Watcher** | Timer/new source record | Allowlisted source registry and freshness status | `site_events`, `telemetry`, `documents`, `source_manifest` | Validates/normalizes approved data and marks sources fresh, stale, or unavailable. |
| **Case Orchestrator** | Any new case event | Case status and event type | Task records | Chooses the specialists to run and tracks completion. |
| **Vision Risk Agent** | Video/frame event | Frame/metadata and site zones | `evidence` | Finds/records a potential obstruction, load path, or hazard zone. |
| **Crew Comms Agent** | Audio event | Local transcript | `evidence` | Extracts safety language, equipment references, and contradictions. |
| **Telemetry & Proximity Agent** | Wind/load/worker event | Time-series and current risk zones | `evidence` | Detects threshold breach or worker-zone conflict. |
| **Rules Retrieval Agent** | A decision is requested | Lift-plan/SOP chunks from MongoDB | `evidence` | Retrieves the specific rule, not a generic safety summary. |
| **Safety Commander** | Required evidence set complete | All case evidence + retrieved rules | `decision`, `actions` | Produces `APPROVE`, `HOLD`, or `ESCALATE` with citations and required next steps. |
| **Policy Gate** | Action proposed | Decision and action type | `actions` | Deterministically permits drafting, but requires a human for safety-critical/external actions. |

### 6.2 Closed-loop behavior

```text
1. An input arrives in MongoDB as an immutable event.
2. A MongoDB Change Stream wakes the Case Orchestrator.
3. The Orchestrator schedules the relevant specialist agents.
4. Each specialist writes structured evidence back to MongoDB.
5. The Rules Retrieval Agent fetches the applicable lift-plan/SOP rule.
6. The Safety Commander evaluates only stored evidence and rules.
7. The Policy Gate creates an auditable proposed action.
8. A new event repeats the loop and can change the decision.
```

This is the key behavior judges should see: a new gust, stale source, equipment event, or worker-zone event changes `CONDITIONAL APPROVAL` to `HOLD`/`ESCALATE`; the agent is not simply rephrasing its first answer.

### 6.3 Structured contracts

All agents return JSON validated by the backend before a database write.

```json
{
  "caseId": "LIFT-042",
  "agent": "telemetry-proximity",
  "evidenceType": "telemetry_observation",
  "sourceRefs": ["telemetry:wind-178", "site-model:zone-c"],
  "finding": "Wind gust 46 km/h exceeds the retrieved 42 km/h threshold.",
  "confidence": 0.98,
  "severity": "critical",
  "timestamp": "2026-08-22T10:18:08Z"
}
```

The Commander response is also structured:

```json
{
  "caseId": "LIFT-042",
  "decision": "HOLD",
  "reasons": ["Zone C obstruction", "Wind threshold exceeded"],
  "evidenceIds": ["ev-vision-31", "ev-wind-52", "ev-rule-7"],
  "requiredBeforeApproval": ["Clear Zone C", "Recheck wind", "Supervisor sign-off"],
  "confidence": 0.93
}
```

---

## 7. MongoDB design and prize alignment

### 7.1 Why MongoDB is essential

MongoDB is the source of truth for the case. It holds raw event metadata, structured agent evidence, document retrieval records, decisions, and approvals. The OpenClaw sandbox is intentionally disposable; the investigation persists outside it.

Run a **local single-node replica set** so [Change Streams](https://www.mongodb.com/docs/manual/changeStreams/) are available. Confirm this in the first hour—this is a critical path item.

### 7.2 Collections

| Collection | Purpose | Important fields |
| --- | --- | --- |
| `cases` | Current lift/incident state | `_id`, `status`, `decision`, `latestEvidenceIds`, `updatedAt` |
| `site_events` | Immutable incoming event log | `caseId`, `type`, `source`, `timestamp`, `payload` |
| `evidence` | Normalized agent findings | `caseId`, `agent`, `evidenceType`, `sourceRefs`, `finding`, `confidence`, `severity` |
| `site_model` | Named zones and risk polygons | `version`, `zones`, `hazards`, `updatedAt` |
| `documents` | Lift-plan/SOP chunk records | `documentId`, `page`, `text`, `tags`, `ruleKey` |
| `telemetry_recordings` | Immutable imported source trace for the demo | `recordingId`, `source`, `provenance`, `events`, `checksum`, `isSimulated` |
| `replay_state` | Durable replay position and speed | `caseId`, `recordingId`, `cursor`, `speed`, `status`, `updatedAt` |
| `telemetry` | Wind/load/heat/access readings | `caseId`, `kind`, `value`, `unit`, `timestamp`, `source`, `isSimulated` |
| `worker_positions` | Team-member location/zone events | `caseId`, `workerAlias`, `zoneId`, `timestamp` |
| `source_manifest` | Provenance and freshness for each data source | `sourceId`, `origin`, `license`, `retrievedAt`, `freshnessSlaSeconds`, `status`, `checksum` |
| `notifications` | Targeted local worker alerts and acknowledgement state | `caseId`, `workerAlias`, `tier`, `reasonEvidenceIds`, `status`, `sentAt`, `acknowledgedAt` |
| `actions` | Proposed and human-approved actions | `caseId`, `type`, `status`, `requestedBy`, `requiresApproval`, `audit` |
| `agent_runs` | Recovery/debug trace | `caseId`, `agent`, `inputEventId`, `status`, `startedAt`, `completedAt` |

### 7.3 Required indexes

- `site_events`: `{ caseId: 1, timestamp: 1 }`
- `evidence`: `{ caseId: 1, severity: -1, timestamp: 1 }`
- `telemetry_recordings`: `{ recordingId: 1, checksum: 1 }`
- `replay_state`: `{ caseId: 1, status: 1 }`
- `telemetry`: `{ caseId: 1, kind: 1, timestamp: -1 }`
- `worker_positions`: `{ caseId: 1, workerAlias: 1, timestamp: -1 }`
- `source_manifest`: `{ sourceId: 1, status: 1, retrievedAt: -1 }`
- `notifications`: `{ workerAlias: 1, status: 1, sentAt: -1 }`
- `documents`: `{ ruleKey: 1, tags: 1 }`

For the short hackathon corpus, deterministic rule/tag retrieval is safer than adding a vector-search dependency. If local vector search is already available and verified, add embeddings as a stretch goal—but do not make the demo depend on it.

### 7.4 “Agent survives its own sandbox” demo

1. Run Case `LIFT-042` until it reaches `HOLD`.
2. Restart/recreate the OpenClaw/NemoClaw sandbox or restart the orchestrator process.
3. Start it again.
4. It reads `cases`, `evidence`, `actions`, and latest event state from MongoDB.
5. The dashboard shows **“Recovered case LIFT-042 — decision remains HOLD.”**

This is a concrete proof that durable memory and state survive the agent process.

### 7.5 “Retrieval changes behavior” demo

Use three states:

| Moment | Retrieved/received fact | Expected behavior |
| --- | --- | --- |
| First decision | Lift plan missing | `ESCALATE`: cannot authorize without rule retrieval. |
| Rule retrieved | Gust threshold is 42 km/h; current gust is 38 km/h; zone clear | `CONDITIONAL APPROVAL`. |
| New event | Gust rises to 46 km/h or worker enters Zone C | `HOLD` with the exact retrieved rule cited. |
| Freshness failure | Required crane/environment data passes its SLA | `ESCALATE`: data is too stale to issue clearance. |

If the exact same response would be produced without MongoDB documents/events, this requirement has not been met.

---

## 8. Local-only architecture

### 8.0 Build console versus runtime host

The **Dell Pro Max with GB10 (DGX)** is the only runtime and integration-test host. Its pre-provisioned local models remain on that machine; they are not copied to, served from, or called through a developer laptop. The team may author source code on its PC, then transfer/deploy it to the Dell for every end-to-end test and the final demo.

| Device | Permitted role | Must not do |
| --- | --- | --- |
| Developer laptop/PC | Author/edit source code, transfer it to the Dell, optional browser display, and presentation screen | Run models, MongoDB, OpenClaw/NemoClaw/OpenShell, media analysis, or an end-to-end agent test. |
| Dell Pro Max with GB10 | Deployed project workspace, local web app/API, MongoDB Community, replay engine, OpenClaw/NemoClaw/OpenShell, all models, and all video/audio processing | Expose model or MongoDB ports to worker phones or the public internet. |
| Phone | Thin Worker PWA client over the event Wi-Fi | Access a model endpoint, database, or raw source media. |

During the official event build window, author the project on the PC and deploy/sync it to a workspace on the Dell. Run every model-backed, MongoDB-backed, and end-to-end test there. This preserves the rule that the system is built during the event on the supplied machine. Do not pre-build the application or agent system on the PC before doors open; keep pre-event work to planning, licensed assets, and familiarisation only.

```text
Developer laptop (source code) ──deploy/sync─────┐
Browser/display ─────────────────────────────────┼──────┐
Worker PWA ─────────event Wi-Fi, Worker API──────┘      │
                                                 ▼
                 ┌────────────────────────────────────────┐
                 │ Dell Pro Max with GB10                  │
                 │ Project workspace + local dashboard/API │
Video + audio ───┤ Frame sampler + local ASR/CV/VLM         │
PDFs ────────────┤ Local document extractor                 │
Telemetry replay ┤ Local Replay Engine                       │
                 │              │                           │
                 │              ▼                           │
                 │  MongoDB Community local replica set     │
                 │              │ Change Streams            │
                 │              ▼                           │
                 │ OpenClaw agents in NemoClaw/OpenShell    │
                 │              │ loopback model endpoints  │
                 │              ▼                           │
                 │ Pre-provisioned local NVIDIA models      │
                 └────────────────────────────────────────┘
```

### 8.1 Stack

| Layer | Recommended choice | Why |
| --- | --- | --- |
| UI | Next.js/React + simple 2.5D map | Fast dashboard and a phone-friendly worker page. |
| API/event coordinator | Python FastAPI or Node/TypeScript service | Accepts local events, validates agent JSON, subscribes to Change Streams, and owns simulator/source-freshness rules. Pick the team’s fastest language. |
| Database | MongoDB Community, local single-node replica set | Durable state, real event stream, document/evidence collections, sandbox recovery. |
| Agent runtime | OpenClaw running under NemoClaw | Named specialist agents and managed local runtime. |
| Isolation/policy | OpenShell | Blocks unauthorised network/data/action paths; exposes policy evidence for judges. |
| Text inference | One locally served Nemotron model | Shared by agents; do not run one large model per agent. |
| Vision | Local VLM or local object-detection + frame-analysis pipeline | Converts frames into structured site observations. |
| Speech | NVIDIA Parakeet Unified English 0.6B, served locally | Converts team-recorded radio audio into a timestamped transcript. |

### 8.2 OpenShell policy

OpenShell is a product feature, not a logo in the README. The policy must allow only:

- reads/writes to the case workspace;
- connection to the local MongoDB/API/model endpoints needed by the sandbox;
- local tool calls needed for document/video processing.

The local API may deliver a pre-approved `CAUTION` or `STOP / ACK REQUIRED` risk alert to an on-site worker PWA. It must record the alert and acknowledgement in MongoDB; it may not issue machinery commands or use an external messaging service.

If an organizer approves one live public-data feed, allow the Data Watcher only to reach that exact documented hostname. The agent sandbox must not receive general internet access.

It must deny or require approval for:

- outbound public-network requests;
- sending raw video, worker-location data, or documents externally;
- any direct crane/equipment control;
- issuing a final lift approval without a named human approver.

The dashboard’s action panel should show an attempted unsafe action as `BLOCKED / APPROVAL REQUIRED`, plus a reason. The actual OpenShell policy/log view is the proof point.

### 8.3 Local inference rule

Every agent must use a local base URL, such as a loopback/local-network inference endpoint. No agent prompt, embedding request, ASR request, or vision request may call a hosted provider. During the demo, deny public egress from the agent sandbox. The separate Data Watcher remains disabled unless organizers explicitly approve its exact allowlisted public-data connection.

NemoClaw is designed to manage OpenClaw environments inside OpenShell containers, including managed inference routing and sandbox lifecycle. See the [NemoClaw overview](https://docs.nvidia.com/nemoclaw/latest/user-guide/openclaw/about/overview) and its [CLI selection guide](https://docs.nvidia.com/nemoclaw/latest/user-guide/openclaw/reference/cli-selection-guide).

### 8.4 Network and worker-connection design

An IP address alone does not connect two devices on different Wi-Fi/cellular networks. A private address such as `192.168.x.x` works only on the same routed LAN. If a worker phone has mobile internet while the DGX sits behind a site router, the phone cannot safely reach the DGX just by knowing its private IP.

RiskTwin therefore has three distinct deployment modes.

#### Mode A — Hackathon demonstration: private local Wi-Fi

```text
Worker phone ─┐
Controller ───┼── private event Wi-Fi/LAN ── DGX Worker API (local IP)
              │                                  ↓
              └──────────────────────────── MongoDB + local models
```

- Put the DGX, controller device, and demo worker phones on the **same private LAN**.
- The worker scans a QR code containing the local API address, for example `http://<DGX-LAN-IP>:3000/worker`.
- The worker page uses WebSocket/local HTTP to send zone events and receive alerts.
- No model endpoint or MongoDB port is exposed to the phones; only the Worker API/dashboard is reachable.
- Wi-Fi is transport only. All inference remains local on the GB10.
- If venue guest Wi-Fi isolates clients, use an organizer-approved private router/LAN instead.

Do not try to demonstrate phones on unrelated Wi-Fi or cellular networks during the sprint. That requires production-grade routing/authentication and adds needless demo risk.

#### Mode B — Production: workers on different networks

```text
Worker phone on cellular / home / site Wi-Fi
                     ↓ TLS + authenticated VPN / zero-trust ingress
                Site ingress gateway
                     ↓ private routed connection
                 DGX Worker API
                     ↓
        MongoDB Community + local inference services
```

- The public-facing surface is a narrow, authenticated **Worker API**—never MongoDB, OpenClaw, or a model server.
- Workers connect by a company-managed app/PWA using TLS and short-lived device credentials through an enterprise VPN or zero-trust access path.
- The DGX maintains the private site-side connection; do not expose a raw database or model port to the public internet.
- Worker events contain only `workerAlias`, device trust state, floor/zone or coordinates, timestamp, and acknowledgement status. They do not upload raw video or expose personal location history broadly.
- All model inference still happens on the site DGX. Network traffic is only telemetry, position, alert, and authorised data-ingestion traffic.

#### Mode C — High-rise or no Wi-Fi: floor edge gateways

```text
UWB/BLE tag, camera, crane sensor, or wired sensor
                     ↓
       Floor edge gateway (one or more per floor/zone)
                     ↓ wired Ethernet/fibre, private LTE, or approved backhaul
                  Site DGX
```

- A single hotspot is not a high-rise coverage solution.
- Use multiple floor/zone gateways; each can receive UWB/BLE/LoRa or wired sensor events locally.
- Gateways buffer signed events if their backhaul drops, then forward them to MongoDB when restored.
- The Data Watcher marks a gateway `stale` after its freshness SLA. RiskTwin changes to `ESCALATE`; it never assumes workers remain safe during an outage.
- Existing two-way radios remain the operational fallback for urgent human communication. RiskTwin can generate the evidence-backed stop-work message, but safety procedures decide who transmits it.

### 8.5 Production-only approved data-ingestion boundary

The **Data Watcher** is the only component that may contact an approved external data source when policy/event rules allow it. It runs separately from the agent sandbox. This is a production extension, not part of the hackathon runtime.

```text
Allowlisted official/licensed source
             ↓  (Wi-Fi/cellular/backhaul only if permitted)
Local Data Watcher on DGX
             ↓  validate + provenance + freshness
MongoDB Community Server
             ↓
OpenClaw agents retrieve local records only
```

Example source domains—not a promise to use all of them—are weather/severe-condition bulletins, approved project schedule/permit exports, equipment-gateway records, and safety bulletins. Every connector needs an owner, purpose, source terms, allowed hostname, schema validation, rate limit, freshness SLA, and a failure rule.

For the hackathon, use the safe fallback: import/seed cleared datasets locally during the event and replay them. Enable a live Wi-Fi data connector only after explicit organizer confirmation that it complies with the “no remote LLM/API calls” requirement.

---

## 9. Model plan

### 9.1 Important limitation

The supplied Llama/Nemotron models are **text-generation models**. They are excellent for orchestration, retrieval reasoning, policy interpretation, and structured action decisions, but they do not by themselves ingest raw video/audio.

RiskTwin is still fully local and multimodal by pairing them with:

- a local vision component that turns sampled video frames into structured observations; and
- a local ASR component that turns the radio clip into a transcript.

The text model reasons over those local outputs and the original files never leave the Dell machine.

### 9.2 Provided models and recommended use

| Model | Recommended role | Day-of decision |
| --- | --- | --- |
| [NVIDIA Nemotron 3.5 Lightning 30B A3B NVFP4](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4) | **Default shared agent model** for Orchestrator, Rules Retrieval, and Safety Commander | First choice. NVIDIA’s model card identifies a single DGX Spark/GB10 deployment and positions it for long-running agent/sub-agent workflows. |
| [NVIDIA Nemotron 3 Super 120B A12B NVFP4](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4) | Optional final decision/reasoning model | Use only if it is already available and passes a smoke test quickly. Do not risk the full demo on a large-model download or cold start. |
| [Llama 3.1 Nemotron 70B Instruct GGUF](https://huggingface.co/bartowski/Llama-3.1-Nemotron-70B-Instruct-HF-GGUF) | Optional `llama.cpp` fallback for Commander/orchestration | User-supplied fallback path. Confirm the quant, context, and startup time on the actual Dell before committing. The linked Q4_K_M artifact is about 42.5 GB. |
| [NVIDIA Nemotron 3 Nano 4B GGUF](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF) | Emergency recovery/fallback: event classification, simple extraction, or a degraded Commander | Keep the user experience honest: show “degraded model mode” rather than claiming large-model quality. |

### 9.3 Model-serving rules

1. Start **one** primary text model server. Multi-agent specialization comes from prompts, tools, and MongoDB state—not from loading multiple giant models.
2. Limit concurrent text generations to one or two during the demo, then update agent cards as results arrive.
3. Use short structured outputs and a constrained context: relevant document chunks, top evidence items, and current case state only.
4. Use a 120B model only as a stretch after the 30B path is verified.
5. Test a single local inference request before building the dashboard.

The Lightning model’s official model card includes GB10 deployment guidance and local-serving options; its NVFP4 package is designed for efficient local agent use. The linked 70B and Nano model cards are explicitly tagged for text generation. [Lightning model card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4), [Nano model card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF), [70B GGUF listing](https://huggingface.co/bartowski/Llama-3.1-Nemotron-70B-Instruct-HF-GGUF).

### 9.4 Vision and speech decision gate

#### Vision: `nvidia/NVIDIA-Nemotron-Nano-12B-v2-VL-NVFP4-QAD`

Use [NVIDIA Nemotron Nano V2 VL 12B FP4 QAD](https://huggingface.co/nvidia/NVIDIA-Nemotron-Nano-12B-v2-VL-NVFP4-QAD) as the **Vision Risk Agent**, provided it is already available or passes a local start-and-inference smoke test in the first 15–20 minutes. It is NVIDIA’s image-text VLM and supports local Transformers/vLLM serving. Its model card describes single-image inference, so RiskTwin must use it on sampled frames—never claim raw-video or perfect 3D understanding.

- Input: four to six locally extracted drone-video frames at a fixed low frame rate (for example, one frame per second); do not send the video to any URL or hosted endpoint.
- Prompt/output: require strict JSON containing `zoneId`, `observations`, `riskType`, `confidence`, and `frameRefs`.
- Invocation: run on new walkthrough footage, a risk-state change, or a manager request—not continuously for every camera frame.
- Continuous camera optimization: a small local detector/motion gate may decide which frames merit VLM analysis. It is a trigger, not the system of record.
- First fallback: [NVIDIA Llama 3.1 Nemotron Nano VL 8B V1](https://huggingface.co/nvidia/Llama-3.1-Nemotron-Nano-VL-8B-V1), also used as an image-text model on sampled frames.
- Second fallback: [Qwen2.5-VL-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct), only if neither NVIDIA VLM can start locally in the time box.
- Last fallback: use local deterministic CV/detector output on the prepared clip and narrow the claim to **“local visual event extraction plus agentic safety reasoning.”** Never imply that a text-only model saw the video.

#### Voice: `nvidia/parakeet-unified-en-0.6b`

Use [NVIDIA Parakeet Unified English 0.6B](https://huggingface.co/nvidia/parakeet-unified-en-0.6b) as the **Crew Comms Agent** speech model. It is an NVIDIA local ASR model supporting both offline and streaming transcription, making it a better fit for prerecorded radio clips now and periodic/live radio snippets later.

- Input: team-recorded, local 16 kHz mono WAV audio.
- Output: timestamped transcript stored in MongoDB; the text model extracts equipment names, zone references, and safety intent from that transcript.
- Invocation: run when a radio clip arrives; do not call any hosted ASR service.
- Fallback: [NVIDIA Parakeet TDT 0.6B v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3), which has a local GGUF artifact for a lighter recovery path.

#### Day-of model order

1. Start and smoke-test Parakeet on the radio clip.
2. Start and smoke-test NVIDIA Nano V2 VL 12B on four local frames; switch immediately to Nano VL 8B or Qwen if it misses the 15–20 minute time box.
3. Write both outputs to MongoDB as evidence.
4. Start the Lightning 30B text model and confirm that it reasons over those evidence records.

This sequence proves genuine local multimodality before the larger multi-agent orchestration work begins. Record the exact model revisions, licenses, and local serving command in the final README.

---

## 10. API contracts

All endpoints are local-only. Exact routing may change; preserve these contracts.

### Ingest a worker-zone event

`POST /api/events/worker-position`

```json
{
  "caseId": "LIFT-042",
  "workerAlias": "worker-12",
  "zoneId": "C",
  "timestamp": "2026-08-22T10:18:11Z"
}
```

### Ingest an operational reading

`POST /api/events/telemetry`

```json
{
  "caseId": "LIFT-042",
  "kind": "wind_gust_kmh",
  "value": 46,
  "source": "local-replay",
  "timestamp": "2026-08-22T10:18:08Z"
}
```

### Request/observe a decision

`GET /api/cases/LIFT-042`

```json
{
  "caseId": "LIFT-042",
  "decision": "HOLD",
  "reasons": ["Wind exceeds lift-plan maximum", "Worker is in Zone C"],
  "evidence": ["ev-wind-52", "ev-worker-19", "ev-rule-7"],
  "requiredBeforeApproval": ["Clear Zone C", "Recheck wind", "Supervisor approval"]
}
```

### Propose a safety-critical action

`POST /api/cases/LIFT-042/actions`

```json
{
  "type": "issue_lift_clearance",
  "requestedBy": "site-controller"
}
```

Expected response when conditions are unsafe:

```json
{
  "status": "BLOCKED",
  "reason": "Safety-critical action requires a human approval and active case is HOLD.",
  "policyEvidence": ["ev-rule-7", "ev-wind-52"]
}
```

---

## 11. UI requirements

Build one controller dashboard and one minimal mobile worker page.

### Controller dashboard

- **Left:** video frame/clip and a risk-zone overlay.
- **Center:** site plan/2.5D map with worker dot and zones A–D.
- **Right:** specialist-agent cards that resolve independently.
- **Bottom:** MongoDB event stream and forensic timeline.
- **Top banner:** `LIFT 042 — HOLD` / `CONDITIONAL APPROVAL` / `ESCALATE`.
- **Action panel:** proposed action, policy gate status, human-approval step.

### Worker mobile page

- Send/choose current zone for the demo.
- Receive a local `CAUTION` or `STOP / ACK REQUIRED` alert: “Stop — Zone C has suspended-load risk.”
- Acknowledge the alert; the acknowledgement updates the controller dashboard through MongoDB.
- Do not include personal accounts, facial recognition, background tracking, or a full native mobile application.

---

## 12. Suggested file layout to create after kickoff

```text
risktwin/
├── README.md                         # Local runbook, model/data attribution, stack disclosure
├── docker-compose.yml                # MongoDB/local services only if permitted by environment
├── apps/
│   ├── dashboard/                    # Controller dashboard + mobile worker route
│   └── api/                          # Local ingest, case API, Change Stream worker
├── agents/
│   ├── orchestrator/                 # Event-to-task routing
│   ├── vision-risk/                  # Frame-to-evidence adapter
│   ├── crew-comms/                   # ASR transcript-to-evidence adapter
│   ├── telemetry-proximity/          # Threshold + zone logic
│   ├── rules-retrieval/              # Local document retrieval
│   └── safety-commander/             # Decision and action proposal
├── packages/
│   ├── contracts/                    # Shared validated schemas
│   └── site-model/                   # Zones, risk polygons, demo seed state
├── scripts/
│   ├── bootstrap-mongo.*             # Replica set/index setup
│   ├── ingest-cleared-data.*         # Event-time import with attribution record
│   ├── data-watcher.*                 # Allowlisted connector + freshness checker, only if approved
│   ├── replay-scenario.*             # Local event sequence driver
│   └── smoke-test-local-inference.*  # Confirms no remote endpoint is used
├── data/
│   ├── raw/                          # Cleared inputs; excluded from Git if needed
│   ├── processed/                    # Frames/transcripts created during event
│   └── ATTRIBUTION.md                # Every non-authored asset and its permission
└── docs/
    ├── RISK_TWIN_BUILD_SPEC.md       # This document
    └── DEMO_SCRIPT.md                # Final 90-second script created during event
```

---

## 13. Eight-hour execution plan for four builders

| Time | Builder A: platform/data | Builder B: agent system | Builder C: multimodal | Builder D: UI/demo |
| --- | --- | --- | --- | --- |
| 0:00–0:45 | Start local Mongo replica set; prove Change Streams | Verify OpenClaw/NemoClaw local model path | Verify frame extraction + local ASR/VLM availability | Create dashboard shell and site map mock |
| 0:45–1:30 | Create schemas/indexes and source manifest; import cleared data | Create agent contracts and one Commander smoke test | Process video/audio into local artifacts | Build case/timeline panels |
| 1:30–3:00 | Implement local event replay, source freshness, and worker events | Implement specialist agents + evidence writes | Implement frame/transcript evidence adapters | Connect dashboard to case/event API |
| 3:00–4:30 | Implement recovery state reads | Implement rule retrieval and behavior transition | Seed zone/risk observations | Animate agent cards and map zones |
| 4:30–5:30 | Add action/audit collection | Add OpenShell policy-gate integration | Test all-local path | Add mobile zone page and alert view |
| 5:30–6:30 | Sandbox-recovery demonstration | Validate `ESCALATE → CONDITIONAL → HOLD` | Improve evidence clarity | Polish decision view / timer / reset button |
| 6:30–8:00 | Capture diagnostics | Rehearse prompts and fallback model | Rehearse assets locally | Rehearse full pitch; prepare screenshots/write-up |

### Day-of milestones and kill switches

| Deadline | Must be true | If not true, cut to |
| --- | --- | --- |
| 00:45 | Local model answers one request; MongoDB Change Stream receives one event | Use Nano model; defer all visual polish |
| 02:00 | Event → evidence → case status loop works | Remove optional 3D styling and extra agents |
| 03:30 | Dashboard shows live Mongo state | Use a static site map; preserve live decision behavior |
| 05:00 | Retrieval changes a decision | Make this the single priority; it is rubric-critical |
| 06:00 | Agent restart recovers case from MongoDB | Remove any stretch model/feature to finish recovery |

---

## 14. Test plan

### Functional checks

- Video/audio/document/telemetry/worker events each write a clearly labeled record into MongoDB.
- The Orchestrator schedules only relevant agents per event type.
- The Commander cannot decide `APPROVE` or `HOLD` without required evidence and retrieved rule.
- The case decision changes after a new wind/worker event.
- A stale critical data source changes the decision to `ESCALATE`.
- A worker entering a high-risk zone receives a local alert; acknowledgement is durably recorded in MongoDB.
- Restarting the agent process restores the case from MongoDB.
- A safety-critical action remains blocked pending human approval.

### Local-first checks

- Model endpoint resolves to local host/service only.
- The model server, MongoDB, agent runtime, API, and deployed project workspace are on the Dell; source code may be authored on the laptop but is integration-tested only after deployment to the Dell.
- Disconnect/deny public egress before the final run.
- No browser/server code calls hosted LLM, ASR, vision, embeddings, or weather APIs.
- Database, models, processed assets, and dashboard run from the Dell machine.

### Failure handling

| Failure | Safe behavior |
| --- | --- |
| Missing video/ASR evidence | `ESCALATE`; never fabricate a scene finding. |
| Unknown wind threshold | `ESCALATE` and request policy retrieval. |
| Model server slow/unavailable | Switch to Nano fallback and visibly label degraded mode. |
| MongoDB unavailable | Show no clearance; the agent cannot prove or persist a decision. |
| Critical source is stale/unavailable | `ESCALATE`; display the missing source and last known timestamp. |
| Conflicting sources | `HOLD`/`ESCALATE` with both sources displayed. |

---

## 15. Final 90-second demo script

1. **Problem (10 sec):** “Before a critical lift, a site manager must reconcile a changing site, crew call, equipment conditions, and PDF rules. That is slow and error-prone.”
2. **Spatial input (15 sec):** Play the walkthrough and show Zone C turn red from local visual evidence.
3. **Multi-agent proof (15 sec):** Show Vision, Crew Comms, Telemetry/Proximity, and Rules agents independently writing evidence.
4. **Always-on proof (15 sec):** A teammate sends a live worker-zone event from a phone. The Data Watcher shows fresh equipment/environmental sources; MongoDB Change Streams update the risk state and send that same phone a `STOP / ACK REQUIRED` alert.
5. **Retrieval proof (10 sec):** The Rules Agent cites the lift-plan threshold; a new gust, equipment event, or source-freshness failure changes the recommendation to `HOLD`/`ESCALATE`.
6. **OpenShell proof (10 sec):** Attempt to issue a lift clearance or send raw evidence externally. It is blocked/held for human approval.
7. **Persistence proof (10 sec):** Restart the agent sandbox/process. RiskTwin restores `LIFT-042` and its `HOLD` decision from MongoDB.
8. **Close (5 sec):** “The DGX runs the multimodal reasoning locally, MongoDB gives it durable operational memory, and OpenShell keeps AI inside human safety policy.”

---

## 16. Submission checklist

- [ ] State clearly that all inference ran locally on the Dell Pro Max with GB10.
- [ ] Name and version every model actually used, including local vision/ASR components.
- [ ] List OpenClaw, NemoClaw, OpenShell, and MongoDB with a one-sentence role for each.
- [ ] Include a screenshot or short video of the MongoDB-backed recovery demo.
- [ ] Explain exactly how retrieval changed the decision.
- [ ] Include `data/ATTRIBUTION.md` and all model/data licenses.
- [ ] Avoid claims of autonomous crane control, continuous employee surveillance, perfect 3D reconstruction, or production-grade localization.
- [ ] Say that RiskTwin is decision support requiring a qualified human’s approval.

## 17. Judge-ready closing statement

> “RiskTwin is a local AI safety co-pilot for critical construction lifts. It sees a site walkthrough, hears the crew, retrieves the approved lift rules, reacts to live site events, and produces an auditable hold-or-clear decision. Its intelligence is multimodal and multi-agent; its memory and recovery live in MongoDB; and OpenShell ensures it cannot turn a recommendation into an unsafe autonomous action.”
