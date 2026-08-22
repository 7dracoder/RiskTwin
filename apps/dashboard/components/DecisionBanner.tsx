"use client";

import { DECISION_LABEL, DECISION_STYLE, shortTime } from "@/lib/decision";
import type { CaseView, SystemSnapshot } from "@/lib/types";

export function DecisionBanner({
  caseView,
  system,
  connected,
}: {
  caseView: CaseView | null;
  system: SystemSnapshot | null;
  connected: boolean;
}) {
  const decision = caseView?.decision ?? "ESCALATE";
  return (
    <header className={`panel border ${DECISION_STYLE[decision]} px-4 py-3`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-baseline gap-4">
          <span className="text-2xl font-bold tracking-tight">
            {caseView?.caseId ?? "LIFT-042"} — {DECISION_LABEL[decision]}
          </span>
          {caseView?.liftActive ? (
            <span className="chip border-hold/50 text-hold">lift active</span>
          ) : (
            <span className="chip">lift not active</span>
          )}
          <span className="chip">
            confidence {caseView ? Math.round(caseView.confidence * 100) : 0}%
          </span>
          <span className="chip">{caseView?.evidenceCount ?? 0} evidence records</span>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[10px] uppercase tracking-wide">
          <span className={`chip ${connected ? "text-approve" : "text-escalate"}`}>
            change feed {connected ? "live" : "reconnecting"}
          </span>
          {system?.degradedMode ? (
            <span className="chip border-hold/50 text-hold">degraded model mode</span>
          ) : null}
          {caseView?.recoveredFromStore ? (
            <span className="chip border-approve/50 text-approve">recovered from store</span>
          ) : null}
          <span className="chip">
            site model {caseView?.siteModelId ?? "—"} v{caseView?.siteModelVersion ?? "—"}
          </span>
          <span className="chip">updated {shortTime(caseView?.updatedAt)}</span>
        </div>
      </div>

      <p className="mt-2 text-[11px] uppercase tracking-widest text-slate-500">
        {system?.banner ?? "RECORDED / SIMULATED SITE TELEMETRY — REPLAY MODE"} · decision support
        only; a qualified human approves every lift
      </p>

      {caseView?.reasons?.length ? (
        <ul className="mt-2 space-y-1 text-sm">
          {caseView.reasons.map((reason) => (
            <li key={reason} className="flex gap-2">
              <span className="text-slate-500">•</span>
              <span>{reason}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {caseView?.requiredBeforeApproval?.length ? (
        <div className="mt-2 flex flex-wrap gap-2">
          <span className="text-[11px] uppercase tracking-widest text-slate-500">
            required before approval
          </span>
          {caseView.requiredBeforeApproval.map((step) => (
            <span key={step} className="chip border-slate-600 text-slate-300 normal-case">
              {step}
            </span>
          ))}
        </div>
      ) : null}

      {caseView?.narrative ? (
        <p className="mt-2 border-t border-white/5 pt-2 text-xs leading-relaxed text-slate-400">
          {caseView.narrative}
        </p>
      ) : null}
    </header>
  );
}
