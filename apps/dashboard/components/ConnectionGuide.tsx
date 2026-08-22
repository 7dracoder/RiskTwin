"use client";

import { useEffect, useMemo, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { DEFAULT_API_PORT } from "@/lib/api";
import type { EvidenceItem, SiteModelView, SystemSnapshot } from "@/lib/types";

function isLoopback(hostname: string) {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
}

export function ConnectionGuide({
  system,
  model,
  evidence,
}: {
  system: SystemSnapshot | null;
  model: SiteModelView | null;
  evidence: EvidenceItem[];
}) {
  const [browserAddress, setBrowserAddress] = useState({
    hostname: "<DGX-LAN-IP>",
    protocol: "http:",
    port: "3000",
  });

  useEffect(() => {
    setBrowserAddress({
      hostname: window.location.hostname,
      protocol: window.location.protocol,
      port: window.location.port || "3000",
    });
  }, []);

  const workerUrl = isLoopback(browserAddress.hostname)
    ? `http://<DGX-LAN-IP>:${browserAddress.port}/worker`
    : `${browserAddress.protocol}//${browserAddress.hostname}:${browserAddress.port}/worker`;
  const vision = system?.models.vision;
  const visualFindings = useMemo(() => {
    const unique = new Map<string, EvidenceItem>();
    for (const item of evidence) {
      if (item.evidenceType === "video_observation") {
        unique.set(`${item.modelRef}:${item.finding}`, item);
      }
    }
    return [...unique.values()];
  }, [evidence]);
  const mapped = visualFindings.filter((item) => Boolean(item.detail?.zoneId)).length;

  return (
    <section className="grid gap-2 lg:grid-cols-3" aria-label="System at a glance">
      <article className="status-card status-card-live">
        <div className="status-kicker">
          <span className="status-dot" /> inference path live
        </div>
        <p className="mt-2 text-base font-semibold text-white">
          {vision?.backend === "deterministic" ? "Local CV is running" : "Vision model is running"}
        </p>
        <p className="mt-1 text-xs leading-relaxed text-slate-400">
          {vision?.model ?? "connecting…"} · {visualFindings.length} unique visual finding
          {visualFindings.length === 1 ? "" : "s"}
        </p>
        <div className="pipeline mt-3" aria-label="Inference pipeline">
          <span>MP4</span><b>→</b><span>frames</span><b>→</b><span>CV</span><b>→</b><span>evidence</span>
        </div>
      </article>

      <article className="status-card">
        <div className="status-kicker text-cyan-300">2.5D twin active</div>
        <p className="mt-2 text-base font-semibold text-white">
          {model ? `${model.siteModelId} · version ${model.version}` : "Loading site model…"}
        </p>
        <p className="mt-1 text-xs leading-relaxed text-slate-400">
          {model?.zones.length ?? 0} named zones · {model?.floors.length ?? 0} elevation layers · {mapped} mapped / {Math.max(visualFindings.length - mapped, 0)} awaiting location
        </p>
        <p className="mt-3 text-[10px] uppercase tracking-wider text-slate-500">
          Switch between isometric and plan view on the map
        </p>
      </article>

      <article className="status-card">
        <div className="status-kicker text-violet-300">connect a worker phone</div>
        <div className="mt-2 flex items-center gap-3">
          {!isLoopback(browserAddress.hostname) ? <div className="rounded bg-white p-1.5"><QRCodeSVG value={workerUrl} size={82} level="M" title="Scan to open the RiskTwin worker page" /></div> : null}
          <div className="min-w-0"><p className="break-all font-mono text-xs font-semibold text-white">{workerUrl}</p><p className="mt-1 text-[10px] uppercase tracking-wider text-violet-300">scan with phone camera to join</p></div>
        </div>
        <ol className="mt-2 space-y-1 text-[11px] text-slate-400">
          <li><b className="text-slate-200">1.</b> Put the phone and DGX on the same private Wi-Fi/LAN.</li>
          <li><b className="text-slate-200">2.</b> Open the DGX LAN address above—not 127.0.0.1.</li>
          <li><b className="text-slate-200">3.</b> Allow inbound TCP {browserAddress.port} and {DEFAULT_API_PORT} on the DGX firewall.</li>
        </ol>
        <a className="mt-3 inline-block text-xs font-semibold text-violet-300 underline" href="/worker">
          preview worker screen →
        </a>
      </article>
    </section>
  );
}
