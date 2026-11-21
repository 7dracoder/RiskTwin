"use client";

import { useMemo, useState } from "react";
import dynamic from "next/dynamic";
import type { EvidenceItem, PointCloud, ReconstructionStatus, SiteModelView, WorkerPositionView, Zone } from "@/lib/types";

const PointCloudViewer = dynamic(() => import("@/components/PointCloudViewer").then((module) => module.PointCloudViewer), { ssr: false });

const ZONE_FILL: Record<string, string> = {
  "lift-exclusion": "#ef4444",
  staging: "#a78bfa",
  "safe-route": "#34d399",
  access: "#38bdf8",
  "work-area": "#fbbf24",
};
const SEVERITY_RANK = ["info", "low", "medium", "high", "critical"];

type ViewMode = "isometric" | "plan" | "colmap";

function uniqueVisualEvidence(evidence: EvidenceItem[]) {
  const unique = new Map<string, EvidenceItem>();
  for (const item of evidence) {
    if (item.evidenceType === "video_observation") {
      unique.set(`${item.modelRef}:${item.finding}`, item);
    }
  }
  return [...unique.values()];
}

function isoPoint([x, y]: number[], elevation = 0): [number, number] {
  return [24 + (x - y) * 2.5, 7 + (x + y) * 1.25 - elevation * 0.08];
}

function polygonPoints(zone: Zone, view: ViewMode, elevation: number) {
  if (view === "plan") return zone.polygon.map(([x, y]) => `${x},${y}`).join(" ");
  return zone.polygon.map((point) => isoPoint(point, elevation).join(",")).join(" ");
}

function labelPoint(zone: Zone, view: ViewMode, elevation: number): [number, number] {
  if (view === "plan") return [zone.centroid[0], zone.centroid[1]];
  return isoPoint(zone.centroid, elevation);
}

export function SiteMap({
  model,
  workers,
  evidence,
  liftActive,
  reconstruction,
  cloud,
  onBuild3D,
}: {
  model: SiteModelView | null;
  workers: WorkerPositionView[];
  evidence: EvidenceItem[];
  liftActive: boolean;
  reconstruction: ReconstructionStatus | null;
  cloud: PointCloud | null;
  onBuild3D: () => Promise<void>;
}) {
  const [view, setView] = useState<ViewMode>("isometric");
  const visualEvidence = useMemo(() => uniqueVisualEvidence(evidence), [evidence]);
  const hazardZones = useMemo(() => {
    const zones = new Map<string, { severity: string; finding: string; modelRef: string | null }>();
    for (const item of evidence) {
      const zoneId = (item.detail?.zoneId as string | undefined) ?? (item.detail?.zone as string | undefined);
      if (!zoneId) continue;
      const current = zones.get(zoneId);
      if (!current || SEVERITY_RANK.indexOf(item.severity) > SEVERITY_RANK.indexOf(current.severity)) {
        zones.set(zoneId, { severity: item.severity, finding: item.finding, modelRef: item.modelRef });
      }
    }
    return zones;
  }, [evidence]);
  const unmapped = visualEvidence.filter((item) => !item.detail?.zoneId);

  if (!model) {
    return <section className="panel flex h-full items-center justify-center text-sm text-slate-500">loading the versioned site twin…</section>;
  }

  const bounds = model.zones.flatMap((zone) => zone.polygon).reduce(
    (acc, [x, y]) => ({ maxX: Math.max(acc.maxX, x), maxY: Math.max(acc.maxY, y) }),
    { maxX: 1, maxY: 1 },
  );

  return (
    <section className="panel flex h-full flex-col overflow-hidden">
      <div className="panel-title flex flex-wrap items-center justify-between gap-2">
        <div>
          <span className="text-slate-200">Spatial twin output</span>
          <span className="ml-2 normal-case tracking-normal text-slate-500">{model.siteModelId} v{model.version} · {model.coordinateFrame.units}</span>
        </div>
        <div className="flex rounded border border-edge bg-black/30 p-0.5" role="group" aria-label="Map view">
          {(["isometric", "plan", "colmap"] as ViewMode[]).map((mode) => (
            <button key={mode} className={`rounded px-3 py-1 text-[10px] uppercase tracking-wider ${view === mode ? "bg-cyan-400/15 text-cyan-200" : "text-slate-500"}`} aria-pressed={view === mode} onClick={() => setView(mode)}>
              {mode === "isometric" ? "2.5D isometric" : mode === "plan" ? "plan view" : "COLMAP 3D"}
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-2 border-b border-edge bg-black/20 p-2 sm:grid-cols-4">
        <div className="metric"><b>{model.zones.length}</b><span>versioned zones</span></div>
        <div className="metric"><b>{hazardZones.size}</b><span>mapped risk zones</span></div>
        <div className={`metric ${unmapped.length ? "metric-warn" : ""}`}><b>{unmapped.length}</b><span>model findings awaiting map</span></div>
        <div className="metric"><b>{reconstruction?.pointCount ?? 0}</b><span>COLMAP 3D points</span></div>
      </div>

      {unmapped.length ? (
        <div className="mx-3 mt-3 flex items-start gap-3 rounded border border-hold/40 bg-hold/5 p-3">
          <span className="model-ping mt-1" aria-hidden="true" />
          <div>
            <p className="text-xs font-semibold text-hold">MODEL OUTPUT DETECTED · LOCATION UNCONFIRMED</p>
            <p className="mt-1 text-[11px] leading-relaxed text-slate-400">
              {String(unmapped[0].detail?.riskType ?? "visual observation").replace(/_/g, " ")} · {Math.round(unmapped[0].confidence * 100)}% confidence. The finding is visible here, but is not painted onto a zone until a camera-to-zone sidecar is supplied.
            </p>
          </div>
        </div>
      ) : null}

      <div className="relative flex-1 overflow-auto p-3">
        {view === "colmap" ? <PointCloudViewer cloud={cloud} status={reconstruction} onBuild={onBuild3D} /> : null}
        {view !== "colmap" ? <>
        <div className="absolute right-5 top-5 z-10 rounded border border-cyan-400/30 bg-slate-950/80 px-2 py-1 text-[10px] uppercase tracking-wider text-cyan-200">z-axis = floor elevation</div>
        {model.floors.map((floor) => {
          const zones = model.zones.filter((zone) => zone.floorId === floor.floorId);
          if (!zones.length) return null;
          const floorWorkers = workers.filter((worker) => (worker.floorId ?? "F12") === floor.floorId);
          const viewBox = view === "plan" ? `-1 -1 ${bounds.maxX + 2} ${bounds.maxY + 2}` : "-10 -2 70 45";
          return (
            <div key={floor.floorId} className="h-full min-h-[27rem]">
              <div className="mb-2 flex items-center gap-3 text-[11px] uppercase tracking-widest text-slate-400">
                <span className="text-cyan-200">floor {floor.floorId}</span><span>elevation {floor.elevationMeters} m</span><span className="text-slate-600">annotated geometry</span>
              </div>
              <svg viewBox={viewBox} className="h-[calc(100%-2rem)] min-h-[25rem] w-full rounded-lg border border-edge bg-slate-950" role="img" aria-label={`${view} site twin for floor ${floor.floorId}`}>
                <defs>
                  <pattern id="grid" width="2" height="2" patternUnits="userSpaceOnUse"><path d="M 2 0 L 0 0 0 2" fill="none" stroke="#334155" strokeWidth="0.04" /></pattern>
                  <radialGradient id="map-bg"><stop offset="0" stopColor="#172033" /><stop offset="1" stopColor="#080b10" /></radialGradient>
                  <filter id="glow"><feGaussianBlur stdDeviation="0.35" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
                </defs>
                <rect x={view === "plan" ? -1 : -10} y={-2} width={view === "plan" ? bounds.maxX + 2 : 70} height={view === "plan" ? bounds.maxY + 3 : 47} fill="url(#map-bg)" />
                <rect x={view === "plan" ? -1 : -10} y={-2} width={view === "plan" ? bounds.maxX + 2 : 70} height={view === "plan" ? bounds.maxY + 3 : 47} fill="url(#grid)" />
                {zones.map((zone) => {
                  const hazard = hazardZones.get(zone.zoneId);
                  const base = ZONE_FILL[zone.kind] ?? "#64748b";
                  const alert = hazard?.severity === "critical" || hazard?.severity === "high";
                  const [lx, ly] = labelPoint(zone, view, floor.elevationMeters);
                  const modelFinding = Boolean(hazard?.modelRef);
                  return (
                    <g key={zone.zoneId}>
                      {view === "isometric" ? <polygon points={zone.polygon.map((point) => { const [x, y] = isoPoint(point, floor.elevationMeters); return `${x},${y + 1.1}`; }).join(" ")} fill="#05070a" stroke="#263344" strokeWidth="0.12" /> : null}
                      <polygon points={polygonPoints(zone, view, floor.elevationMeters)} fill={alert ? "#ef4444" : base} fillOpacity={alert ? 0.48 : 0.2} stroke={alert ? "#fb7185" : base} strokeWidth={alert ? 0.24 : 0.13} />
                      <text x={lx} y={ly - 0.2} fontSize={view === "plan" ? "1.2" : "1.35"} textAnchor="middle" fill="#f8fafc" fontWeight="700">ZONE {zone.zoneId}</text>
                      <text x={lx} y={ly + 1.1} fontSize={view === "plan" ? "0.5" : "0.62"} textAnchor="middle" fill="#cbd5e1">{zone.label ?? zone.kind}</text>
                      <text x={lx} y={ly + 2} fontSize={view === "plan" ? "0.45" : "0.5"} textAnchor="middle" fill={base}>{zone.kind}{zone.kind === "lift-exclusion" && liftActive ? " · LIFT ACTIVE" : ""}</text>
                      {modelFinding ? <g filter="url(#glow)"><circle cx={lx} cy={ly - 2} r="1.15" fill="none" stroke="#fbbf24" strokeWidth="0.22" /><circle cx={lx} cy={ly - 2} r="0.35" fill="#fbbf24" /><text x={lx + 1.7} y={ly - 1.8} fontSize="0.55" fill="#fde68a">MODEL FINDING</text></g> : null}
                    </g>
                  );
                })}
                {floorWorkers.map((worker) => {
                  const zone = zones.find((item) => item.zoneId === worker.zoneId);
                  const raw = worker.x !== null && worker.y !== null ? [worker.x, worker.y] : (zone?.centroid ?? [bounds.maxX / 2, bounds.maxY / 2]);
                  const [x, y] = view === "plan" ? [raw[0], raw[1]] : isoPoint(raw, floor.elevationMeters);
                  const inside = worker.relation === "inside_risk_zone";
                  return <g key={worker._id} filter="url(#glow)"><circle cx={x} cy={y} r="0.65" fill={inside ? "#ef4444" : "#facc15"} stroke="#fff" strokeWidth="0.12" /><text x={x + 0.9} y={y + 0.2} fontSize="0.65" fill="#fff">{worker.workerAlias}</text></g>;
                })}
              </svg>
            </div>
          );
        })}
        </> : null}
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-edge px-3 py-2 text-[10px] text-slate-500">
        {Object.entries(ZONE_FILL).slice(0, 4).map(([kind, color]) => <span key={kind} className="flex items-center gap-1"><i className="h-2 w-2 rounded-sm" style={{ backgroundColor: color }} />{kind}</span>)}
        <span className="ml-auto">2.5D operational zones · COLMAP 3D reconstructed directly from video</span>
      </div>
    </section>
  );
}
