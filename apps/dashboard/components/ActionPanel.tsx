"use client";

import { useState } from "react";
import { postJson, CASE_ID } from "@/lib/api";
import { shortTime } from "@/lib/decision";
import type { ActionRecord, NotificationRecord } from "@/lib/types";

// Only action types declared in config/openshell-policy.yaml. Anything else is
// denied by policy default, which is the behaviour, not an error to hide.
const ACTIONS = [
  { type: "issue_lift_clearance", label: "Issue lift clearance" },
  { type: "draft_alert", label: "Draft risk narrative" },
  { type: "equipment_command", label: "Command the crane" },
  { type: "export_raw_video", label: "Export raw video" },
];

const STATUS_STYLE: Record<string, string> = {
  BLOCKED: "text-escalate",
  REJECTED: "text-escalate",
  AWAITING_APPROVAL: "text-hold",
  APPROVED: "text-approve",
  EXECUTED: "text-approve",
  PROPOSED: "text-slate-300",
};

/**
 * Action panel: propose, see the policy verdict, then the named human approval
 * step. A safety-critical action never executes on the agent's own authority
 * (spec sections 6.1 and 10).
 */
export function ActionPanel({
  actions,
  notifications,
  onChange,
}: {
  actions: ActionRecord[];
  notifications: NotificationRecord[];
  onChange: () => void;
}) {
  const [approver, setApprover] = useState("site-manager-01");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function propose(type: string) {
    setBusy(type);
    setError(null);
    try {
      await postJson(`/api/cases/${CASE_ID}/actions`, {
        type,
        requestedBy: "site-controller",
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
      onChange();
    }
  }

  async function decide(actionId: string, approve: boolean) {
    setBusy(actionId);
    setError(null);
    try {
      await postJson(`/api/actions/${actionId}/approval`, {
        approvedBy: approver,
        approve,
        note: approve ? "approved on the controller dashboard" : "rejected on review",
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
      onChange();
    }
  }

  const outstanding = notifications.filter(
    (item) => item.requiresAck && item.status === "SENT",
  );

  return (
    <section className="panel flex h-full flex-col">
      <div className="panel-title">Action panel · policy gate</div>

      <div className="flex flex-wrap gap-2 border-b border-edge p-2">
        {ACTIONS.map((action) => (
          <button
            key={action.type}
            className="btn"
            disabled={busy !== null}
            onClick={() => propose(action.type)}
          >
            {action.label}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-2 border-b border-edge px-2 py-1.5 text-xs">
        <label className="text-slate-500" htmlFor="approver">
          human approver
        </label>
        <input
          id="approver"
          value={approver}
          onChange={(event) => setApprover(event.target.value)}
          className="flex-1 rounded border border-edge bg-black/40 px-2 py-1 font-mono text-xs"
        />
      </div>

      {error ? <p className="px-2 py-1 text-xs text-escalate">{error}</p> : null}

      <div className="flex-1 space-y-2 overflow-auto p-2">
        {actions.length === 0 ? (
          <p className="text-xs text-slate-500">No action has been proposed yet.</p>
        ) : null}
        {actions.map((action) => (
          <article key={action._id} className="rounded border border-edge bg-black/30 p-2 text-xs">
            <div className="flex items-center justify-between">
              <span className="font-semibold text-slate-200">{action.type}</span>
              <span className={`chip ${STATUS_STYLE[action.status] ?? ""}`}>{action.status}</span>
            </div>
            <p className="mt-1 text-slate-400">{action.reason}</p>
            <p className="mt-1 text-[10px] text-slate-500">
              requested by {action.requestedBy} at {shortTime(action.createdAt)}
              {action.approvedBy ? ` · approved by ${action.approvedBy}` : ""}
              {action.policyEvidence.length
                ? ` · policy evidence ${action.policyEvidence.join(", ")}`
                : ""}
            </p>
            {action.status === "AWAITING_APPROVAL" ? (
              <div className="mt-2 flex gap-2">
                <button
                  className="btn border-approve/50 text-approve"
                  disabled={busy !== null || !approver.trim()}
                  onClick={() => decide(action._id, true)}
                >
                  approve as {approver}
                </button>
                <button
                  className="btn border-escalate/50 text-escalate"
                  disabled={busy !== null}
                  onClick={() => decide(action._id, false)}
                >
                  reject
                </button>
              </div>
            ) : null}
          </article>
        ))}
      </div>

      <div className="border-t border-edge p-2 text-xs">
        <p className="mb-1 text-[11px] uppercase tracking-widest text-slate-500">
          worker alerts ({notifications.length}) · {outstanding.length} awaiting acknowledgement
        </p>
        <ul className="max-h-32 space-y-1 overflow-auto">
          {notifications.slice(0, 8).map((item) => (
            <li key={item._id} className="flex items-start justify-between gap-2">
              <span className="text-slate-300">
                <span className="font-mono text-[10px] text-slate-500">
                  {shortTime(item.sentAt)}{" "}
                </span>
                {item.workerAlias} · {item.tier} · {item.message}
              </span>
              <span
                className={`chip shrink-0 ${
                  item.status === "ACKNOWLEDGED" ? "text-approve" : "text-hold"
                }`}
              >
                {item.status === "ACKNOWLEDGED" ? `ack ${shortTime(item.acknowledgedAt)}` : "sent"}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
