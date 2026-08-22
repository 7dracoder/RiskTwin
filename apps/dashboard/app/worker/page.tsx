"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiBase, CASE_ID, postJson } from "@/lib/api";
import { shortTime } from "@/lib/decision";
import { useLive } from "@/lib/useLive";
import { useMounted } from "@/lib/useMounted";
import type { SiteModelView, WorkerStatus } from "@/lib/types";

const TIER_STYLE: Record<string, string> = {
  STOP_ACK_REQUIRED: "border-escalate bg-escalate/20 text-escalate",
  ESCALATE: "border-escalate bg-escalate/20 text-escalate",
  CAUTION: "border-hold bg-hold/20 text-hold",
  INFO: "border-edge bg-black/40 text-slate-300",
};

/**
 * Minimal worker page for the demo phone.
 *
 * Role alias only: no personal account, no facial recognition, no background
 * tracking, no native app. The worker reports a zone and receives a local alert
 * that is acknowledged back into the store (spec sections 4.3 and 11).
 */
export default function WorkerPage() {
  const mounted = useMounted();
  const [alias, setAlias] = useState("worker-12");
  const [committedAlias, setCommittedAlias] = useState("worker-12");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [voiceEnabled, setVoiceEnabled] = useState(false);
  const [trackingMode, setTrackingMode] = useState<"off" | "phone" | "simulation">("off");
  const [selectedFloor, setSelectedFloor] = useState("F12");
  const spoken = useRef(new Set<string>());
  const watchId = useRef<number | null>(null);
  const simulationTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const gpsOrigin = useRef<{ latitude: number; longitude: number } | null>(null);

  const model = useLive<SiteModelView>("/api/site-model", 30000, ["site_model"]);
  const status = useLive<WorkerStatus>(`/api/workers/${committedAlias}/status`, 1500, [
    "worker_positions", "notifications", "cases",
  ]);

  useEffect(() => {
    const timer = setTimeout(() => setCommittedAlias(alias.trim() || "worker-12"), 600);
    return () => clearTimeout(timer);
  }, [alias]);

  const stopTracking = useCallback(() => {
    if (watchId.current !== null && navigator.geolocation) {
      navigator.geolocation.clearWatch(watchId.current);
      watchId.current = null;
    }
    if (simulationTimer.current) clearInterval(simulationTimer.current);
    simulationTimer.current = null;
    gpsOrigin.current = null;
    setTrackingMode("off");
  }, []);

  useEffect(() => stopTracking, [stopTracking]);

  useEffect(() => {
    if (!voiceEnabled || typeof window === "undefined" || !("speechSynthesis" in window)) return;
    for (const item of (status.data?.notifications ?? []).filter((row) => row.status === "SENT")) {
      if (spoken.current.has(item._id)) continue;
      spoken.current.add(item._id);
      const speech = new SpeechSynthesisUtterance(`RiskTwin alert. ${item.tier.replace(/_/g, " ")}. ${item.message}`);
      speech.rate = 0.95;
      window.speechSynthesis.speak(speech);
      navigator.vibrate?.([250, 120, 250]);
    }
  }, [status.data?.notifications, voiceEnabled]);

  const reportCoordinates = useCallback(async (payload: Record<string, unknown>) => {
    try {
      await postJson("/api/events/worker-position", {
        caseId: CASE_ID,
        workerAlias: committedAlias,
        floorId: selectedFloor,
        ...payload,
      });
      void status.refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }, [committedAlias, selectedFloor, status]);

  const enableVoice = useCallback(() => {
    setVoiceEnabled(true);
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
      const speech = new SpeechSynthesisUtterance("RiskTwin voice alerts enabled.");
      speech.rate = 1;
      window.speechSynthesis.speak(speech);
    }
  }, []);

  const startPhoneLocation = useCallback(() => {
    stopTracking();
    setError(null);
    if (!navigator.geolocation) {
      setError("This browser does not expose phone location.");
      return;
    }
    setTrackingMode("phone");
    watchId.current = navigator.geolocation.watchPosition(
      (position) => {
        const { latitude, longitude, accuracy, heading, speed } = position.coords;
        if (!gpsOrigin.current) gpsOrigin.current = { latitude, longitude };
        const origin = gpsOrigin.current;
        const metresPerLongitude = 111_320 * Math.cos((origin.latitude * Math.PI) / 180);
        void reportCoordinates({
          x: 1 + (longitude - origin.longitude) * metresPerLongitude,
          y: 1 + (latitude - origin.latitude) * 111_320,
          latitude,
          longitude,
          accuracyMeters: accuracy,
          headingDegrees: heading,
          speedMps: speed,
          locationSource: "phone-gps-session-relative",
          isSimulated: false,
        });
      },
      (failure) => {
        setError(`${failure.message}. Phone location usually needs HTTPS (localhost is the exception).`);
        setTrackingMode("off");
      },
      { enableHighAccuracy: true, maximumAge: 1000, timeout: 12000 },
    );
  }, [reportCoordinates, stopTracking]);

  const startSimulation = useCallback(() => {
    stopTracking();
    setError(null);
    setTrackingMode("simulation");
    const waypoints = [[1, 1], [7, 1], [12, 1], [13, 4], [13, 9], [10, 11], [4, 11], [1, 8], [1, 3]];
    let tick = 0;
    const emit = () => {
      const segment = Math.floor(tick / 6) % waypoints.length;
      const next = (segment + 1) % waypoints.length;
      const fraction = (tick % 6) / 6;
      const x = waypoints[segment][0] + (waypoints[next][0] - waypoints[segment][0]) * fraction;
      const y = waypoints[segment][1] + (waypoints[next][1] - waypoints[segment][1]) * fraction;
      void reportCoordinates({ x, y, z: selectedFloor === "F13" ? 3.6 : 0, accuracyMeters: 0.25, locationSource: "simulated-indoor-path", isSimulated: true });
      tick += 1;
    };
    emit();
    simulationTimer.current = setInterval(emit, 1500);
  }, [reportCoordinates, selectedFloor, stopTracking]);

  const report = useCallback(
    async (zoneId: string, floorId: string) => {
      setBusy(true);
      setError(null);
      try {
        await postJson("/api/events/worker-position", {
          caseId: CASE_ID,
          workerAlias: committedAlias,
          zoneId,
          floorId,
        });
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        setBusy(false);
        void status.refresh();
      }
    },
    [committedAlias, status],
  );

  const acknowledge = useCallback(
    async (notificationId: string) => {
      setBusy(true);
      try {
        await postJson("/api/notifications/ack", {
          workerAlias: committedAlias,
          notificationId,
        });
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        setBusy(false);
        void status.refresh();
      }
    },
    [committedAlias, status],
  );

  const outstanding = (status.data?.notifications ?? []).filter(
    (item) => item.status === "SENT",
  );
  const current = status.data?.position;

  if (!mounted) {
    return (
      <main className="flex min-h-screen items-center justify-center text-sm text-slate-500">
        connecting…
      </main>
    );
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col gap-3 p-4">
      <header className="panel px-3 py-2">
        <div className="flex items-center justify-between gap-2">
          <p className="text-[10px] uppercase tracking-widest text-slate-500">RiskTwin worker · {status.data?.caseId ?? CASE_ID}</p>
          <span className={`flex items-center gap-1 text-[10px] uppercase ${status.error ? "text-escalate" : "text-approve"}`}>
            <i className={status.error ? "h-2 w-2 rounded-full bg-escalate" : "status-dot"} />
            {status.error ? "DGX link offline" : "DGX link live"}
          </span>
        </div>
        <div className="mt-1 flex items-center gap-2">
          <label className="text-xs text-slate-500" htmlFor="alias">
            alias
          </label>
          <input
            id="alias"
            value={alias}
            onChange={(event) => setAlias(event.target.value)}
            className="flex-1 rounded border border-edge bg-black/40 px-2 py-1 font-mono text-sm"
          />
        </div>
        <p className="mt-1 text-[10px] leading-snug text-slate-600">
          Role alias only. No personal account, no camera on this device, no tracking outside an
          active safety case.
        </p>
        <p className="mt-2 rounded border border-edge bg-black/30 px-2 py-1 font-mono text-[10px] text-slate-500">
          API {apiBase()}
        </p>
      </header>

      {outstanding.length ? (
        outstanding.map((item) => (
          <section
            key={item._id}
            className={`rounded-lg border-2 p-4 ${TIER_STYLE[item.tier] ?? TIER_STYLE.INFO}`}
          >
            <p className="text-xs font-semibold uppercase tracking-widest">
              {item.tier.replace(/_/g, " ")}
            </p>
            <p className="mt-1 text-xl font-bold leading-tight">{item.message}</p>
            <p className="mt-2 text-[10px] opacity-80">
              sent {shortTime(item.sentAt)}
              {item.ackDeadlineSeconds
                ? ` · acknowledge within ${item.ackDeadlineSeconds}s`
                : ""}
            </p>
            {item.requiresAck ? (
              <button
                className="mt-3 w-full rounded border-2 border-current px-3 py-3 text-sm font-bold uppercase tracking-wide"
                disabled={busy}
                onClick={() => acknowledge(item._id)}
              >
                acknowledge
              </button>
            ) : null}
          </section>
        ))
      ) : (
        <section className="panel px-3 py-4 text-center text-sm text-slate-400">
          No active alert for {committedAlias}.
          <p className="mt-1 text-[10px] text-slate-600">
            Case decision: {status.data?.decision ?? "—"}
            {status.data?.liftActive ? " · lift active" : ""}
          </p>
        </section>
      )}

      <section className="panel p-3">
        <div className="mb-3 rounded border border-edge bg-black/30 p-2">
          <div className="flex items-center justify-between gap-2">
            <p className="text-[11px] uppercase tracking-widest text-slate-500">live position + spoken safety alert</p>
            <select value={selectedFloor} onChange={(event) => setSelectedFloor(event.target.value)} className="rounded border border-edge bg-slate-950 px-2 py-1 text-xs">
              {(model.data?.floors ?? []).map((floor) => <option key={floor.floorId}>{floor.floorId}</option>)}
            </select>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <button className="btn" onClick={enableVoice}>{voiceEnabled ? "voice alerts on" : "enable voice alerts"}</button>
            {trackingMode === "off" ? <button className="btn" onClick={startPhoneLocation}>use phone location</button> : <button className="btn border-escalate text-escalate" onClick={stopTracking}>stop {trackingMode}</button>}
            <button className="btn col-span-2" onClick={startSimulation} disabled={trackingMode === "simulation"}>simulate walking around building</button>
          </div>
          <p className="mt-2 text-[10px] leading-snug text-slate-500">
            Phone GPS is recorded with its accuracy and converted to a session-relative site grid; it is not survey-grade indoors. The path button is clearly marked simulated and moves continuously through the plan.
          </p>
          {current?.x != null && current?.y != null ? <p className="mt-1 font-mono text-[11px] text-cyan-200">{current.floorId} · x {current.x.toFixed(2)} m · y {current.y.toFixed(2)} m · ±{current.accuracyMeters?.toFixed(1) ?? "?"} m · {current.locationSource}</p> : null}
        </div>
        <p className="mb-2 text-[11px] uppercase tracking-widest text-slate-500">
          manual zone fallback
        </p>
        <div className="grid grid-cols-2 gap-2">
          {(model.data?.zones ?? []).map((zone) => {
            const active = current?.zoneId === zone.zoneId;
            return (
              <button
                key={`${zone.floorId}-${zone.zoneId}`}
                className={`rounded border px-3 py-3 text-left text-sm ${
                  active ? "border-slate-300 bg-white/10" : "border-edge bg-black/40"
                }`}
                disabled={busy}
                onClick={() => report(zone.zoneId, zone.floorId)}
              >
                <span className="text-base font-bold">Zone {zone.zoneId}</span>
                <span className="block text-[10px] text-slate-500">
                  {zone.floorId} · {zone.kind}
                </span>
              </button>
            );
          })}
        </div>
        {current ? (
          <p className="mt-2 text-[10px] text-slate-500">
            last reported zone {current.zoneId ?? "unknown"} at {shortTime(current.timestamp)}
            {current.relation ? ` · ${current.relation.replace(/_/g, " ")}` : ""}
          </p>
        ) : null}
        {error ? <p className="mt-2 text-[11px] text-escalate">{error}</p> : null}
      </section>

      {status.data?.topEvidence?.length ? (
        <section className="panel p-3">
          <p className="mb-1 text-[11px] uppercase tracking-widest text-slate-500">
            why you were alerted
          </p>
          <ul className="space-y-1 text-xs text-slate-300">
            {status.data.topEvidence.map((finding) => (
              <li key={finding}>• {finding}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <p className="px-1 text-[10px] leading-snug text-slate-600">
        Radios remain the operational channel for urgent instructions. This page is decision
        support; a qualified human approves every lift.
      </p>
    </main>
  );
}
