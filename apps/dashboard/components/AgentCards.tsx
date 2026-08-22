"use client";

import { SEVERITY_STYLE, shortTime } from "@/lib/decision";
import type { AgentRun, EvidenceItem } from "@/lib/types";

const AGENTS = [
  { id: "vision-risk", label: "Vision Risk", role: "sampled frames -> zone findings" },
  { id: "crew-comms", label: "Crew Comms", role: "radio clip -> transcript + intent" },
  { id: "telemetry-proximity", label: "Telemetry & Proximity", role: "thresholds + zone geometry" },
  { id: "rules-retrieval", label: "Rules Retrieval", role: "lift plan / SOP limits" },
  { id: "data-watcher", label: "Data Watcher", role: "source provenance + freshness" },
  { id: "safety-commander", label: "Safety Commander", role: "decides from stored evidence" },
  { id: "policy-gate", label: "Policy Gate", role: "OpenShell enforcement + alerts" },
];

/**
 * Right column: one card per specialist. Each resolves independently as its run
 * finishes, which is the multi-agent proof point in spec section 15 step 3.
 */
export function AgentCards({
  runs,
  evidence,
}: {
  runs: AgentRun[];
  evidence: EvidenceItem[];
}) {
  return (
    <section className="panel flex h-full flex-col">
      <div className="panel-title">Specialist agents</div>
      <div className="flex-1 space-y-2 overflow-auto p-2">
        {AGENTS.map((agent) => {
          const agentRuns = runs.filter((run) => run.agent === agent.id);
          const latest = agentRuns[0];
          const findings = evidence.filter((item) => item.agent === agent.id).slice(0, 2);
          const state = !latest
            ? "idle"
            : latest.status === "STARTED"
              ? "running"
              : latest.status === "FAILED"
                ? "failed"
                : "done";
          return (
            <article
              key={agent.id}
              className={`rounded border bg-black/30 p-2 text-xs ${
                state === "failed"
                  ? "border-escalate/50"
                  : state === "running"
                    ? "border-hold/50"
                    : "border-edge"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-200">{agent.label}</span>
                <span
                  className={`chip ${
                    state === "done"
                      ? "text-approve"
                      : state === "running"
                        ? "text-hold"
                        : state === "failed"
                          ? "text-escalate"
                          : ""
                  }`}
                >
                  {state}
                </span>
              </div>
              <p className="mt-0.5 text-[10px] text-slate-500">{agent.role}</p>
              {latest ? (
                <p className="mt-1 text-[10px] text-slate-500">
                  {agentRuns.length} run{agentRuns.length === 1 ? "" : "s"} · last{" "}
                  {shortTime(latest.startedAt)}
                  {latest.durationMs !== null ? ` · ${latest.durationMs} ms` : ""} ·{" "}
                  {latest.evidenceIds.length} evidence
                </p>
              ) : null}
              {latest?.detail ? (
                <p className="mt-1 text-[10px] text-escalate">{latest.detail}</p>
              ) : null}
              {findings.map((item) => (
                <p
                  key={item._id}
                  className={`mt-1 border-l-2 border-edge pl-2 leading-snug ${
                    SEVERITY_STYLE[item.severity]
                  }`}
                >
                  {item.finding}
                </p>
              ))}
            </article>
          );
        })}
      </div>
    </section>
  );
}
