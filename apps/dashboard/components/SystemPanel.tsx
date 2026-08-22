"use client";

import { useState } from "react";
import { postJson, CASE_ID } from "@/lib/api";
import type { ReplayStatus, SystemSnapshot } from "@/lib/types";

/**
 * Stack disclosure and replay control. Every framework reports whether it is
 * running natively or as a local stand-in, because claiming an integration that
 * is not present would be worse than the gap (spec section 16).
 */
export function SystemPanel({
  system,
  replay,
  onChange,
}: {
  system: SystemSnapshot | null;
  replay: ReplayStatus | null;
  onChange: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function call(path: string, label: string) {
    setBusy(true);
    setNote(null);
    try {
      await postJson(path);
      setNote(label);
    } catch (cause) {
      setNote(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
      onChange();
    }
  }

  const state = replay?.state;
  const recording = replay?.recording;

  return (
    <section className="panel flex h-full flex-col">
      <div className="panel-title">Stack, models and replay</div>

      <div className="flex flex-wrap gap-2 border-b border-edge p-2">
        <button className="btn" disabled={busy} onClick={() => call("/api/replay/start", "replay started")}>
          start replay
        </button>
        <button className="btn" disabled={busy} onClick={() => call("/api/replay/pause", "replay paused")}>
          pause
        </button>
        <button className="btn" disabled={busy} onClick={() => call("/api/replay/reset", "replay rewound")}>
          rewind
        </button>
        <button
          className="btn"
          disabled={busy}
          onClick={() => call(`/api/cases/${CASE_ID}/documents/import`, "documents indexed and case re-decided")}
        >
          import documents
        </button>
        <button
          className="btn"
          disabled={busy}
          onClick={() => call(`/api/cases/${CASE_ID}/reset`, "case reset for another run")}
        >
          reset case
        </button>
      </div>
      {note ? <p className="px-2 py-1 text-[11px] text-slate-400">{note}</p> : null}

      <div className="flex-1 space-y-3 overflow-auto p-2 text-[11px]">
        {state && recording ? (
          <div className="rounded border border-edge bg-black/30 p-2">
            <div className="flex items-center justify-between">
              <span className="text-slate-300">
                replay {state.status.toLowerCase()} · event {state.cursor}/{recording.eventCount} ·
                t+{Math.round(state.positionSeconds)}s of {recording.durationSeconds}s
              </span>
              <span className="chip">x{state.speed}</span>
            </div>
            <p className="mt-1 text-[10px] text-slate-500">{recording.provenance}</p>
            <p className="mt-1 text-[10px] text-slate-600">
              licence {recording.license} · checksum {recording.checksum.slice(0, 16)}…
            </p>
            {recording.upcoming.length ? (
              <ul className="mt-1 space-y-0.5 text-[10px] text-slate-500">
                {recording.upcoming.map((item) => (
                  <li key={`${item.offsetSeconds}-${item.label}`}>
                    t+{item.offsetSeconds}s · {item.label}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}

        <div>
          <p className="mb-1 text-[11px] uppercase tracking-widest text-slate-500">models</p>
          {system
            ? Object.entries(system.models).map(([modality, ref]) => (
                <div key={modality} className="mb-1">
                  <span className={ref.degraded ? "text-hold" : "text-approve"}>
                    {modality}: {ref.backend}
                  </span>{" "}
                  <span className="text-slate-400">{ref.model}</span>
                  <p className="text-[10px] text-slate-600">{ref.note}</p>
                </div>
              ))
            : null}
          <p className="text-[10px] text-slate-500">
            local-only endpoints:{" "}
            {system && Object.keys(system.localOnlyEndpoints).length
              ? Object.entries(system.localOnlyEndpoints)
                  .map(([key, value]) => `${key}=${value}`)
                  .join(", ")
              : "no network model endpoint configured"}
          </p>
        </div>

        <div>
          <p className="mb-1 text-[11px] uppercase tracking-widest text-slate-500">
            required stack
          </p>
          {system?.frameworks.map((framework) => (
            <div key={framework.name} className="mb-1.5">
              <span className="text-slate-200">{framework.name}</span>{" "}
              <span className={framework.mode === "native" ? "text-approve" : "text-hold"}>
                [{framework.mode}]
              </span>
              <p className="text-[10px] leading-snug text-slate-500">{framework.role}</p>
              <p className="text-[10px] leading-snug text-slate-600">{framework.note}</p>
            </div>
          ))}
        </div>

        <div>
          <p className="mb-1 text-[11px] uppercase tracking-widest text-slate-500">policy</p>
          <p className="text-slate-400">
            {String(system?.policy?.policyId ?? "—")} · backend{" "}
            {String(system?.policy?.backend ?? "—")}
          </p>
          <p className="text-[10px] leading-snug text-slate-600">
            {String(system?.policy?.description ?? "")}
          </p>
        </div>
      </div>
    </section>
  );
}
