"use client";

import { useState } from "react";
import { postJson } from "@/lib/api";
import type { SensorReading } from "@/lib/types";

const LABELS: Record<string, string> = {
  carbon_monoxide_ppm: "CO", oxygen_percent: "oxygen", noise_dba: "noise",
  dust_pm25_ug_m3: "PM2.5", ambient_temperature_c: "temperature",
  structural_tilt_deg: "structural tilt", vibration_mm_s: "vibration",
  worker_plant_distance_m: "worker ↔ plant",
};

const BREACH = (row: SensorReading) => ({
  carbon_monoxide_ppm: Number(row.value) > 35,
  oxygen_percent: Number(row.value) < 19.5,
  noise_dba: Number(row.value) > 85,
  dust_pm25_ug_m3: Number(row.value) > 35,
  ambient_temperature_c: Number(row.value) > 38,
  structural_tilt_deg: Number(row.value) > 2,
  vibration_mm_s: Number(row.value) > 5,
  worker_plant_distance_m: Number(row.value) < 2,
}[row.kind] ?? false);

export function SensorPanel({ readings, onChange }: { readings: SensorReading[]; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  const simulate = async (scenario: "baseline" | "multi-risk") => {
    setBusy(true);
    try {
      await postJson("/api/sensors/simulate", { scenario });
      setTimeout(onChange, 800);
    } finally { setBusy(false); }
  };
  const site = readings.filter((row) => row.kind in LABELS);
  return (
    <section className="panel px-3 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-[11px] uppercase tracking-widest text-slate-400">whole-site risk sensors</p>
          <p className="text-[10px] text-slate-600">Environmental · occupational · structural · plant proximity. Demo bands must be replaced by the project safety plan.</p>
        </div>
        <div className="flex gap-1"><button className="btn py-1" disabled={busy} onClick={() => simulate("baseline")}>simulate normal</button><button className="btn border-escalate py-1 text-escalate" disabled={busy} onClick={() => simulate("multi-risk")}>simulate multi-risk</button></div>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-1 sm:grid-cols-4 xl:grid-cols-8">
        {site.length ? site.map((row) => {
          const breached = BREACH(row);
          return <div key={row.kind} className={`rounded border px-2 py-1 ${breached ? "border-escalate bg-escalate/10" : "border-edge bg-black/30"}`}><p className="text-[9px] uppercase text-slate-500">{LABELS[row.kind]}</p><p className={`font-mono text-sm ${breached ? "text-escalate" : "text-approve"}`}>{String(row.value)} <span className="text-[9px]">{row.unit}</span></p><p className="text-[9px] text-slate-600">{breached ? "outside demo band" : "inside demo band"} · simulated</p></div>;
        }) : <p className="col-span-full py-2 text-xs text-slate-500">No site sensor set yet. Use either simulation preset to populate the dashboard.</p>}
      </div>
    </section>
  );
}
