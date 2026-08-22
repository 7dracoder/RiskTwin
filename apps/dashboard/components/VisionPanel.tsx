"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { apiBase, postForm, postJson } from "@/lib/api";
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
  onUploaded,
}: {
  frames: FrameRow[];
  redactions: RedactionRow[];
  evidence: EvidenceItem[];
  onReview: () => Promise<void>;
  onUploaded: () => void;
}) {
  const [selected, setSelected] = useState(0);
  const [rawResult, setRawResult] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [uploadResult, setUploadResult] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => setSelected(0), [frames]);

  const visual = useMemo(() => {
    const unique = new Map<string, EvidenceItem>();
    for (const item of evidence) {
      const activeAsset = frames[0]?.assetName;
      if (item.evidenceType === "video_observation" && (!activeAsset || item.sourceRefs.includes(`asset:${activeAsset}`))) {
        unique.set(`${item.modelRef}:${item.finding}`, item);
      }
    }
    return [...unique.values()];
  }, [evidence, frames]);
  const frame = frames[Math.min(selected, Math.max(frames.length - 1, 0))];
  const regions = visual.flatMap((item) => {
    const rows = Array.isArray(item.detail?.regions) ? item.detail.regions : [];
    return (rows as Array<{ frameIndex?: number; boxFraction?: number[]; kind?: string; confidence?: number }>).filter(
      (region) => region.frameIndex === selected && region.boxFraction?.length === 4,
    );
  });

  async function runReview() {
    setBusy(true);
    try {
      await onReview();
    } finally {
      setBusy(false);
    }
  }

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

  async function uploadVideo(file: File) {
    setBusy(true);
    setUploadResult(null);
    try {
      const body = new FormData();
      body.append("video", file);
      const result = await postForm<{ videoName: string }>("/api/media/upload", body);
      setUploadResult(`${result.videoName} accepted · analysis and 3D reconstruction started`);
      setTimeout(onUploaded, 1200);
    } catch (cause) {
      const detail = (cause as { payload?: { detail?: string } }).payload?.detail;
      setUploadResult(detail ?? (cause instanceof Error ? cause.message : String(cause)));
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  return (
    <section className="panel flex h-full flex-col">
      <div className="panel-title flex items-center justify-between">
        <span>Vision model output</span>
        <div className="flex gap-1">
          <input ref={fileInput} className="hidden" type="file" accept="video/mp4,.mp4" onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadVideo(file); }} />
          <button className="btn border-cyan-700 py-0.5 text-cyan-200" onClick={() => fileInput.current?.click()} disabled={busy}>{busy ? "working…" : "upload new video"}</button>
          <button className="btn py-0.5" onClick={runReview} disabled={busy}>{busy ? "analysing…" : "review again"}</button>
        </div>
      </div>

      {uploadResult ? <p className="mx-3 mt-2 rounded border border-edge bg-black/30 px-2 py-1 text-[11px] text-cyan-200">{uploadResult}</p> : null}

      <div className="mx-3 mt-2 rounded border border-edge bg-black/30 px-2 py-1 text-[10px] leading-relaxed text-slate-400">
        Coverage: people/exclusion · vehicles · PPE · edges/openings · fire/smoke · leaks/spills · electrical · unstable materials · blocked egress · visibility. Served VLM findings can confirm a class; local CV findings remain labelled candidates.
      </div>

      <div className="pipeline m-3 mb-0" aria-label="Vision analysis stages">
        <span className="pipeline-done">MP4 input</span><b>→</b>
        <span className="pipeline-done">{frames.length} sampled frames</span><b>→</b>
        <span className="pipeline-live"><i className="status-dot" /> local CV active</span><b>→</b>
        <span className="pipeline-done">{visual.length} finding{visual.length === 1 ? "" : "s"}</span>
      </div>

      <div className="p-3">
        {frame ? (
          <>
            <div className="relative overflow-hidden rounded border border-edge bg-black">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={`${apiBase()}/api/media/frames/${frame.name}`} alt={`sampled frame ${frame.name}`} className="block h-auto w-full object-contain" />
              {regions.map((region, index) => {
                const [x1, y1, x2, y2] = region.boxFraction as number[];
                return (
                  <div
                    key={`${selected}-${index}`}
                    className="vision-box"
                    style={{ left: `${x1 * 100}%`, top: `${y1 * 100}%`, width: `${(x2 - x1) * 100}%`, height: `${(y2 - y1) * 100}%` }}
                  >
                    <span>{String(region.kind ?? "candidate").replace(/_/g, " ")} · {Math.round((region.confidence ?? 0) * 100)}%</span>
                  </div>
                );
              })}
              <div className="absolute left-2 top-2 rounded bg-slate-950/80 px-2 py-1 text-[10px] uppercase tracking-wider text-cyan-200">
                analysed frame {selected + 1}/{frames.length}
              </div>
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              {frames.map((item, index) => (
                <button
                  key={item.name}
                  onClick={() => setSelected(index)}
                  aria-pressed={index === selected}
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
        <p className="mb-1 text-[11px] uppercase tracking-widest text-slate-500">Evidence written by vision</p>
        {visual.length ? (
          <ul className="space-y-2 text-xs">
            {visual.map((item) => (
              <li key={item._id} className="rounded border border-edge bg-black/30 p-2">
                <div className="flex items-center justify-between">
                  <span className={`font-semibold ${SEVERITY_STYLE[item.severity]}`}>
                    {String(item.detail?.zoneId ?? "location unconfirmed")} ·{" "}
                    {String(item.detail?.riskType ?? "observation")}
                  </span>
                  <span className="chip">{Math.round(item.confidence * 100)}%</span>
                </div>
                <p className="mt-1 text-slate-300">{item.finding}</p>
                <p className="mt-1 text-[10px] text-slate-500">
                  {item.modelGenerated ? "served vision model" : "local deterministic CV active"} ·{" "}
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
