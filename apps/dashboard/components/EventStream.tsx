"use client";

import { useState } from "react";
import { SEVERITY_STYLE, shortTime } from "@/lib/decision";
import type { EvidenceItem, PolicyLogRow, SiteEventItem } from "@/lib/types";

type Tab = "events" | "evidence" | "policy";

/**
 * Bottom strip: the immutable event stream from the store and the forensic
 * evidence timeline built from it (spec section 11). Every row shows where the
 * record came from so a judge can trace a decision back to its inputs.
 */
export function EventStream({
  events,
  evidence,
  policyLog,
  storeBackend,
}: {
  events: SiteEventItem[];
  evidence: EvidenceItem[];
  policyLog: PolicyLogRow[];
  storeBackend: string;
}) {
  const [tab, setTab] = useState<Tab>("events");

  return (
    <section className="panel flex h-full flex-col">
      <div className="panel-title flex items-center justify-between">
        <div className="flex gap-3">
          {(
            [
              ["events", `event stream (${events.length})`],
              ["evidence", `forensic timeline (${evidence.length})`],
              ["policy", `policy log (${policyLog.length})`],
            ] as [Tab, string][]
          ).map(([id, label]) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={tab === id ? "text-slate-100" : "text-slate-500"}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="normal-case tracking-normal text-slate-500">{storeBackend}</span>
      </div>

      <div className="flex-1 overflow-auto font-mono text-[11px] leading-relaxed">
        {tab === "events" ? (
          <table className="w-full">
            <tbody>
              {events.map((event) => (
                <tr key={event._id} className="border-b border-edge/50">
                  <td className="w-20 px-2 py-1 text-slate-500">{shortTime(event.timestamp)}</td>
                  <td className="w-40 px-2 py-1 text-slate-300">{event.type}</td>
                  <td className="w-44 px-2 py-1 text-slate-500">
                    {event.sourceId ?? event.source}
                  </td>
                  <td className="px-2 py-1 text-slate-400">
                    {Object.entries(event.payload)
                      .filter(([, value]) => value !== null && value !== undefined)
                      .map(([key, value]) => `${key}=${String(value)}`)
                      .join("  ")}
                  </td>
                  <td className="w-24 px-2 py-1 text-right text-slate-600">
                    {event.isSimulated ? "simulated" : "live"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}

        {tab === "evidence" ? (
          <table className="w-full">
            <tbody>
              {evidence.map((item) => (
                <tr key={item._id} className="border-b border-edge/50">
                  <td className="w-20 px-2 py-1 text-slate-500">{shortTime(item.timestamp)}</td>
                  <td className="w-40 px-2 py-1 text-slate-300">{item.agent}</td>
                  <td className="w-44 px-2 py-1 text-slate-500">{item.evidenceType}</td>
                  <td className={`px-2 py-1 ${SEVERITY_STYLE[item.severity]}`}>{item.finding}</td>
                  <td className="w-40 px-2 py-1 text-right text-slate-600">
                    {item.sourceRefs.join(", ")}
                  </td>
                  <td className="w-24 px-2 py-1 text-right text-slate-600">
                    {item.modelGenerated ? "model" : "deterministic"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}

        {tab === "policy" ? (
          <table className="w-full">
            <tbody>
              {policyLog.map((row) => (
                <tr key={row._id} className="border-b border-edge/50">
                  <td className="w-20 px-2 py-1 text-slate-500">{shortTime(row.timestamp)}</td>
                  <td className="w-40 px-2 py-1 text-slate-300">{row.actionType}</td>
                  <td className="w-28 px-2 py-1 text-slate-500">{row.subject}</td>
                  <td
                    className={`w-32 px-2 py-1 ${
                      row.effect === "allow"
                        ? "text-approve"
                        : row.effect === "require_approval"
                          ? "text-hold"
                          : "text-escalate"
                    }`}
                  >
                    {row.effect}
                  </td>
                  <td className="px-2 py-1 text-slate-400">{row.reason}</td>
                  <td className="w-52 px-2 py-1 text-right text-slate-600">{row.policyId}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </div>
    </section>
  );
}
