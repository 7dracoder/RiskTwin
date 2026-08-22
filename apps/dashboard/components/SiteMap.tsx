"use client";

import { useMemo } from "react";
import type { EvidenceItem, SiteModelView, WorkerPositionView } from "@/lib/types";

const ZONE_FILL: Record<string, string> = {
  "lift-exclusion": "#e5484d",
  staging: "#8b7cf6",
  "safe-route": "#30a46c",
  access: "#3b82f6",
  "work-area": "#f0a500",
};

/**
 * 2.5D site plan: one panel per floor, zones drawn from the versioned site model
 * and hazards attached to the named zone the evidence cites (spec section 4.1).
 * The z axis is floor elevation, not a reconstructed mesh — the panel says so.
 */
export function SiteMap({
  model,
  workers,
  evidence,
  liftActive,
}: {
  model: SiteModelView | null;
  workers: WorkerPositionView[];
  evidence: EvidenceItem[];
  liftActive: boolean;
}) {
  const hazardZones = useMemo(() => {
    const zones = new Map<string, { severity: string; finding: string }>();
    const rank = ["info", "low", "medium", "high", "critical"];
    for (const item of evidence) {
      const zoneId =
        (item.detail?.zoneId as string | undefined) ??
        (item.detail?.zone as string | undefined) ??
        null;
      if (!zoneId) continue;
      const current = zones.get(zoneId);
      if (!current || rank.indexOf(item.severity) > rank.indexOf(current.severity)) {
        zones.set(zoneId, { severity: item.severity, finding: item.finding });
      }
    }
    return zones;
  }, [evidence]);

  if (!model) {
    return (
      <section className="panel flex h-full items-center justify-center text-sm text-slate-500">
        no site model has been seeded
      </section>
    );
  }

  const bounds = model.zones
    .flatMap((zone) => zone.polygon)
    .reduce(
      (acc, [x, y]) => ({
        maxX: Math.max(acc.maxX, x),
        maxY: Math.max(acc.maxY, y),
      }),
      { maxX: 1, maxY: 1 },
    );

  return (
    <section className="panel flex h-full flex-col">
      <div className="panel-title flex items-center justify-between">
        <span>2.5D spatial risk twin</span>
        <span className="normal-case tracking-normal text-slate-500">
          {model.siteModelId} v{model.version} · {model.coordinateFrame.units} ·{" "}
          {model.coordinateFrame.origin}
        </span>
      </div>

      <div className="flex-1 overflow-auto p-3">
        {model.floors.map((floor) => {
          const zones = model.zones.filter((zone) => zone.floorId === floor.floorId);
          if (!zones.length) return null;
          const floorWorkers = workers.filter(
            (worker) => (worker.floorId ?? "F12") === floor.floorId,
          );
          return (
            <div key={floor.floorId} className="mb-4 last:mb-0">
              <div className="mb-1 flex items-center gap-2 text-[11px] uppercase tracking-widest text-slate-400">
                <span>floor {floor.floorId}</span>
                <span className="text-slate-600">elevation {floor.elevationMeters} m</span>
              </div>
              <svg
                viewBox={`-1 -1 ${bounds.maxX + 2} ${bounds.maxY + 2}`}
                className="w-full rounded border border-edge bg-black/40"
                style={{ aspectRatio: `${bounds.maxX + 2} / ${bounds.maxY + 2}` }}
              >
                {zones.map((zone) => {
                  const hazard = hazardZones.get(zone.zoneId);
                  const base = ZONE_FILL[zone.kind] ?? "#64748b";
                  const alert =
                    hazard?.severity === "critical" || hazard?.severity === "high";
                  return (
                    <g key={zone.zoneId}>
                      <polygon
                        points={zone.polygon.map(([x, y]) => `${x},${y}`).join(" ")}
                        fill={alert ? "#e5484d" : base}
                        fillOpacity={alert ? 0.42 : 0.14}
                        stroke={alert ? "#e5484d" : base}
                        strokeWidth={alert ? 0.22 : 0.1}
                      />
                      <text
                        x={zone.centroid[0]}
                        y={zone.centroid[1]}
                        fontSize="1.1"
                        textAnchor="middle"
                        fill="#e2e8f0"
                        fontWeight="600"
                      >
                        {zone.zoneId}
                      </text>
                      <text
                        x={zone.centroid[0]}
                        y={zone.centroid[1] + 1.2}
                        fontSize="0.52"
                        textAnchor="middle"
                        fill="#94a3b8"
                      >
                        {zone.kind}
                        {zone.kind === "lift-exclusion" && liftActive ? " · ACTIVE" : ""}
                      </text>
                    </g>
                  );
                })}

                {floorWorkers.map((worker) => {
                  const zone = zones.find((item) => item.zoneId === worker.zoneId);
                  const [x, y] =
                    worker.x !== null && worker.y !== null
                      ? [worker.x, worker.y]
                      : (zone?.centroid ?? [bounds.maxX / 2, bounds.maxY / 2]);
                  const inside = worker.relation === "inside_risk_zone";
                  return (
                    <g key={worker._id}>
                      <circle
                        cx={x}
                        cy={y}
                        r={0.55}
                        fill={inside ? "#e5484d" : "#facc15"}
                        stroke="#0a0d12"
                        strokeWidth={0.14}
                      />
                      <text x={x + 0.85} y={y + 0.25} fontSize="0.6" fill="#cbd5e1">
                        {worker.workerAlias}
                      </text>
                    </g>
                  );
                })}
              </svg>
            </div>
          );
        })}
      </div>

      <div className="border-t border-edge px-3 py-2 text-[10px] leading-relaxed text-slate-500">
        Hazards are attached to named zones on an annotated plan with floor elevation. This is not a
        reconstructed 3D mesh and not production-grade localisation.
        {hazardZones.size ? (
          <span className="ml-1 text-slate-400">
            Flagged: {[...hazardZones.keys()].join(", ")}.
          </span>
        ) : null}
      </div>
    </section>
  );
}
