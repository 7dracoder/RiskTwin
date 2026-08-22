"use client";

import { useState } from "react";
import { apiBase, postJson, CASE_ID } from "@/lib/api";
import { SEVERITY_STYLE } from "@/lib/decision";
import type { EvidenceItem, FrameRow, RedactionRow } from "@/lib/types";

/**
 * Left column: the sampled frames the vision agent actually analysed, the risk
 * overlay derived from those frames, and the redaction manifest. Only the
 * redacted render is retrievable; the raw-request button demonstrates the policy
 * refusal (spec sections 5.1 and 11).
 */
export function VisionPanel({
  frames,
  redactions,
  evidence,
  onReview,
}: {
  frames: FrameRow[];
  redactions: RedactionRow[];
  evidence: EvidenceItem[];
  onReview: () => void;
}) {
  const [selected, setSelected] = useState(0);
  const [rawResult, setRawResult] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const visual = evidence.filter((item) => item.evidenceType === "video_observation");
  const frame = frames[Math.min(selected, Math.max(frames.length - 1, 0))];

  async function requestRaw() {
    setBusy(true);
    try {
      await postJson(`/api/media/raw/walkthrough.mp4`);
      setRawResult("Unexpected: the raw clip was served. Check the policy configuration.");
    } catch (cause) {
      const detail = (cause as { payload?: { detail?: { reason?: string } } }).payload?.detail;
      setRawResult(detail?.reason ?? "Blocked by policy.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel flex h-full flex-col">
      <div className="panel-title flex items-center justify-between">
        <span>Visual evidence</span>
        <button className="btn py-0.5" onClick={onReview}>
          run media review
        </button>
      </div>

      <div className="p-3">
        {frame ? (
          <>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={`${apiBase()}/api/media/frames/${frame.name}`}
              alt={`sampled frame ${frame.name}`}
              className="w-full rounded border border-edge bg-black object-contain"
            />
            <div className="mt-2 flex flex-wrap gap-1">
              {frames.map((item, index) => (
                <button
                  key={item.name}
                  onClick={() => setSelected(index)}
                  className={`chip normal-case ${
                    index === selected ? "border-slate-400 text-slate-100" : ""
                  }`}
                >
                  {item.name.replace(/\.jpg$/, "")}
                </button>
              ))}
            </div>
          </>
        ) : (
          <div className="rounded border border-dashed border-edge px-3 py-8 text-center text-xs text-slate-500">
            No walkthrough frames yet. Drop a cleared clip in <code>data/raw/video/</code> and run a
            media review. Missing visual evidence escalates the case; it is never invented.
          </div>
        )}
      </div>

      <div className="flex-1 overflow-auto border-t border-edge px-3 py-2">
        <p className="mb-1 text-[11px] uppercase tracking-widest text-slate-500">Risk overlay</p>
        {visual.length ? (
          <ul className="space-y-2 text-xs">
            {visual.map((item) => (
              <li key={item._id} className="rounded border border-edge bg-black/30 p-2">
                <div className="flex items-center justify-between">
                  <span className={`font-semibold ${SEVERITY_STYLE[item.severity]}`}>
                    {String(item.detail?.zoneId ?? "unmapped zone")} ·{" "}
                    {String(item.detail?.riskType ?? "observation")}
                  </span>
                  <span className="chip">{Math.round(item.confidence * 100)}%</span>
                </div>
                <p className="mt-1 text-slate-300">{item.finding}</p>
                <p className="mt-1 text-[10px] text-slate-500">
                  {item.modelGenerated ? "model-generated" : "local deterministic CV"} ·{" "}
                  {item.modelRef ?? "no model served"} · {item.sourceRefs.join(", ")}
                </p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-slate-500">No visual finding has been recorded.</p>
        )}
      </div>

      <div className="border-t border-edge px-3 py-2 text-[10px] text-slate-500">
        {redactions.length ? (
          redactions.map((item) => (
            <div key={item.name} className="mb-1">
              <a
                className="text-slate-300 underline"
                href={`${apiBase()}/api/media/redacted/${item.name}`}
              >
                {item.name}
              </a>{" "}
              — {item.redactedRegions} regions {item.redactionMethod} across {item.framesProcessed}{" "}
              frames · {item.detectorVersion}
              {item.warnings.length ? (
                <span className="text-hold"> · {item.warnings.join("; ")}</span>
              ) : null}
            </div>
          ))
        ) : (
          <span>No redacted render has been produced yet.</span>
        )}
        <div className="mt-1 flex items-center gap-2">
          <button className="btn py-0.5" onClick={requestRaw} disabled={busy}>
            request raw clip
          </button>
          {rawResult ? <span className="text-escalate">{rawResult}</span> : null}
        </div>
      </div>
    </section>
  );
}
