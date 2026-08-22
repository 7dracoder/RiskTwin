"use client";

import { useCallback, useEffect, useState } from "react";
import { CASE_ID, postJson } from "@/lib/api";
import { shortTime } from "@/lib/decision";
import { useLive } from "@/lib/useLive";
import { useMounted } from "@/lib/useMounted";
import type { SiteModelView, WorkerStatus } from "@/lib/types";

const TIER_STYLE: Record<string, string> = {
  STOP_ACK_REQUIRED: "border-escalate bg-escalate/20 text-escalate",
  ESCALATE: "border-escalate bg-escalate/20 text-escalate",
  CAUTION: "border-hold bg-hold/20 text-hold",
  INFO: "border-edge bg-black/40 text-slate-300",
};

/**
 * Minimal worker page for the demo phone.
 *
 * Role alias only: no personal account, no facial recognition, no background
 * tracking, no native app. The worker reports a zone and receives a local alert
 * that is acknowledged back into the store (spec sections 4.3 and 11).
 */
export default function WorkerPage() {
  const mounted = useMounted();
  const [alias, setAlias] = useState("worker-12");
  const [committedAlias, setCommittedAlias] = useState("worker-12");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const model = useLive<SiteModelView>("/api/site-model", 30000);
  const status = useLive<WorkerStatus>(`/api/workers/${committedAlias}/status`, 1500);

  useEffect(() => {
    const timer = setTimeout(() => setCommittedAlias(alias.trim() || "worker-12"), 600);
    return () => clearTimeout(timer);
  }, [alias]);

  const report = useCallback(
    async (zoneId: string, floorId: string) => {
      setBusy(true);
      setError(null);
      try {
        await postJson("/api/events/worker-position", {
          caseId: CASE_ID,
          workerAlias: committedAlias,
          zoneId,
          floorId,
        });
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        setBusy(false);
        void status.refresh();
      }
    },
    [committedAlias, status],
  );

  const acknowledge = useCallback(
    async (notificationId: string) => {
      setBusy(true);
      try {
        await postJson("/api/notifications/ack", {
          workerAlias: committedAlias,
          notificationId,
        });
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        setBusy(false);
        void status.refresh();
      }
    },
    [committedAlias, status],
  );

  const outstanding = (status.data?.notifications ?? []).filter(
    (item) => item.status === "SENT",
  );
  const current = status.data?.position;

  if (!mounted) {
    return (
      <main className="flex min-h-screen items-center justify-center text-sm text-slate-500">
        connecting…
      </main>
    );
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col gap-3 p-4">
      <header className="panel px-3 py-2">
        <p className="text-[10px] uppercase tracking-widest text-slate-500">
          RiskTwin worker · {status.data?.caseId ?? CASE_ID}
        </p>
        <div className="mt-1 flex items-center gap-2">
          <label className="text-xs text-slate-500" htmlFor="alias">
            alias
          </label>
          <input
            id="alias"
            value={alias}
            onChange={(event) => setAlias(event.target.value)}
            className="flex-1 rounded border border-edge bg-black/40 px-2 py-1 font-mono text-sm"
          />
        </div>
        <p className="mt-1 text-[10px] leading-snug text-slate-600">
          Role alias only. No personal account, no camera on this device, no tracking outside an
          active safety case.
        </p>
      </header>

      {outstanding.length ? (
        outstanding.map((item) => (
          <section
            key={item._id}
            className={`rounded-lg border-2 p-4 ${TIER_STYLE[item.tier] ?? TIER_STYLE.INFO}`}
          >
            <p className="text-xs font-semibold uppercase tracking-widest">
              {item.tier.replace(/_/g, " ")}
            </p>
            <p className="mt-1 text-xl font-bold leading-tight">{item.message}</p>
            <p className="mt-2 text-[10px] opacity-80">
              sent {shortTime(item.sentAt)}
              {item.ackDeadlineSeconds
                ? ` · acknowledge within ${item.ackDeadlineSeconds}s`
                : ""}
            </p>
            {item.requiresAck ? (
              <button
                className="mt-3 w-full rounded border-2 border-current px-3 py-3 text-sm font-bold uppercase tracking-wide"
                disabled={busy}
                onClick={() => acknowledge(item._id)}
              >
                acknowledge
              </button>
            ) : null}
          </section>
        ))
      ) : (
        <section className="panel px-3 py-4 text-center text-sm text-slate-400">
          No active alert for {committedAlias}.
          <p className="mt-1 text-[10px] text-slate-600">
            Case decision: {status.data?.decision ?? "—"}
            {status.data?.liftActive ? " · lift active" : ""}
          </p>
        </section>
      )}

      <section className="panel p-3">
        <p className="mb-2 text-[11px] uppercase tracking-widest text-slate-500">
          report my zone
        </p>
        <div className="grid grid-cols-2 gap-2">
          {(model.data?.zones ?? []).map((zone) => {
            const active = current?.zoneId === zone.zoneId;
            return (
              <button
                key={`${zone.floorId}-${zone.zoneId}`}
                className={`rounded border px-3 py-3 text-left text-sm ${
                  active ? "border-slate-300 bg-white/10" : "border-edge bg-black/40"
                }`}
                disabled={busy}
                onClick={() => report(zone.zoneId, zone.floorId)}
              >
                <span className="text-base font-bold">Zone {zone.zoneId}</span>
                <span className="block text-[10px] text-slate-500">
                  {zone.floorId} · {zone.kind}
                </span>
              </button>
            );
          })}
        </div>
        {current ? (
          <p className="mt-2 text-[10px] text-slate-500">
            last reported zone {current.zoneId ?? "unknown"} at {shortTime(current.timestamp)}
            {current.relation ? ` · ${current.relation.replace(/_/g, " ")}` : ""}
          </p>
        ) : null}
        {error ? <p className="mt-2 text-[11px] text-escalate">{error}</p> : null}
      </section>

      {status.data?.topEvidence?.length ? (
        <section className="panel p-3">
          <p className="mb-1 text-[11px] uppercase tracking-widest text-slate-500">
            why you were alerted
          </p>
          <ul className="space-y-1 text-xs text-slate-300">
            {status.data.topEvidence.map((finding) => (
              <li key={finding}>• {finding}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <p className="px-1 text-[10px] leading-snug text-slate-600">
        Radios remain the operational channel for urgent instructions. This page is decision
        support; a qualified human approves every lift.
      </p>
    </main>
  );
}
