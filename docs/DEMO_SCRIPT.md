# LIFT-042 — 90-second demo script

Banner on screen the whole time:

**RECORDED / SIMULATED SITE TELEMETRY — REPLAY MODE**

RiskTwin is decision support. A qualified human approves every lift.

---

1. **Problem (10 s).**  
   “Before a critical lift, a site manager has to reconcile a changing site, a crew call, equipment conditions, and PDF rules. That is slow and error-prone.”  
   Show the dashboard at `ESCALATE` with no lift plan retrieved.

2. **Spatial input (15 s).**  
   Import documents, then run media review (or start replay through the walkthrough cue).  
   Zone C on the 2.5D plan turns red from **local sampled-frame evidence**, not a reconstructed mesh.  
   Say: “We build a risk-aware spatial map from a walkthrough.”

3. **Multi-agent proof (15 s).**  
   Point at the specialist cards as they resolve independently: Vision Risk, Crew Comms, Telemetry & Proximity, Rules Retrieval. Each card shows a stored finding, not a chat transcript.

4. **Always-on proof (15 s).**  
   A teammate on the event LAN opens `/worker`, reports **Zone C**.  
   The Data Watcher shows source freshness. The change feed updates the case. That same phone gets **STOP / ACK REQUIRED**. They tap acknowledge; the controller timeline records it.

5. **Retrieval proof (10 s).**  
   Open forensic timeline → policy evidence. Cite **42 km/h** and **85%** from the lift plan.  
   Replay the gust to 46 km/h (or start replay if not already running). Decision flips to `HOLD` with `46 − 42 = 4` and citation `lift-plan-042:p3`. Optionally let the gateway go stale → `ESCALATE`.

6. **OpenShell proof (10 s).**  
   Click **Issue lift clearance** → `BLOCKED` / `AWAITING_APPROVAL`.  
   Click **Command the crane** → denied.  
   Click **request raw clip** → denied. Policy log shows the same verdict.

7. **Persistence proof (10 s).**  
   Stop and restart the API. The banner shows **recovered from store**. `LIFT-042` is still `HOLD` with the same evidence ids. On the Dell this is MongoDB; on the Mac it is the local journal with the same contract.

8. **Close (5 s).**  
   “The host runs the multimodal reasoning locally, MongoDB (or the durable store) gives it operational memory, and OpenShell keeps AI inside human safety policy.”

---

## Kill switches during the pitch

| If this is broken | Do this |
| --- | --- |
| No walkthrough clip | Skip the red overlay; keep retrieval + worker-zone + policy. |
| Dashboard lag | Narrate off `python scripts/replay_scenario.py --reset` in a terminal. |
| Phone not on the LAN | Drive the worker event from the dashboard host browser at `/worker`. |
| Model server down | Leave **degraded model mode** visible; do not pretend a VLM watched the video. |
