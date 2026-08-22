"use client";

import { relativeSeconds } from "@/lib/decision";
import type { SourceRow } from "@/lib/types";

const STATUS_STYLE: Record<string, string> = {
  fresh: "text-approve",
  stale: "text-hold",
  unavailable: "text-escalate",
};

/**
 * Data Watcher view: every approved source with its provenance, licence and
 * freshness verdict. An unverifiable condition is an adverse condition, so this
 * panel is part of the safety case, not decoration (spec section 4.2).
 */
export function SourcePanel({ sources }: { sources: SourceRow[] }) {
  return (
    <section className="panel flex h-full flex-col">
      <div className="panel-title">Approved sources · Data Watcher</div>
      <div className="flex-1 overflow-auto p-2">
        <table className="w-full text-[11px]">
          <thead className="text-slate-500">
            <tr className="text-left">
              <th className="px-1 py-1 font-medium">source</th>
              <th className="px-1 py-1 font-medium">status</th>
              <th className="px-1 py-1 font-medium">last event</th>
              <th className="px-1 py-1 font-medium">sla</th>
              <th className="px-1 py-1 font-medium">on failure</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((source) => (
              <tr key={source.sourceId} className="border-t border-edge/60 align-top">
                <td className="px-1 py-1">
                  <div className="text-slate-200">{source.sourceId}</div>
                  <div className="text-[10px] text-slate-500">{source.label}</div>
                  <div className="text-[10px] text-slate-600">
                    {source.sourceClass}
                    {source.critical ? " · critical" : ""}
                    {source.requiresContinuousFeed ? " · continuous" : " · event-driven"}
                  </div>
                </td>
                <td className={`px-1 py-1 ${STATUS_STYLE[source.status] ?? ""}`}>
                  {source.status}
                </td>
                <td className="px-1 py-1 text-slate-400">
                  {relativeSeconds(source.lastEventAt)}
                </td>
                <td className="px-1 py-1 text-slate-500">{source.freshnessSlaSeconds}s</td>
                <td className="px-1 py-1 text-slate-500">{source.failureRule}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="border-t border-edge px-2 py-1.5 text-[10px] leading-relaxed text-slate-500">
        Live external fetching is disabled. Cleared datasets were imported locally and are replayed;
        the agents only read records the Data Watcher has already validated.
      </p>
    </section>
  );
}
