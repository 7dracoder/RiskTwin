"use client";

import { useCallback } from "react";
import { ActionPanel } from "@/components/ActionPanel";
import { AgentCards } from "@/components/AgentCards";
import { ConnectionGuide } from "@/components/ConnectionGuide";
import { DecisionBanner } from "@/components/DecisionBanner";
import { EventStream } from "@/components/EventStream";
import { SiteMap } from "@/components/SiteMap";
import { SensorPanel } from "@/components/SensorPanel";
import { SourcePanel } from "@/components/SourcePanel";
import { SystemPanel } from "@/components/SystemPanel";
import { VisionPanel } from "@/components/VisionPanel";
import { CASE_ID, postJson } from "@/lib/api";
import { useFeedStatus, useLive } from "@/lib/useLive";
import { useMounted } from "@/lib/useMounted";
import type {
  ActionRecord,
  AgentRun,
  CaseView,
  EvidenceItem,
  FrameRow,
  NotificationRecord,
  PolicyLogRow,
  PointCloud,
  RedactionRow,
  ReconstructionStatus,
  ReplayStatus,
  SiteEventItem,
  SiteModelView,
  SourceRow,
  SystemSnapshot,
  WorkerPositionView,
  SensorReading,
} from "@/lib/types";

export default function ControllerDashboard() {
  const mounted = useMounted();
  const { connected } = useFeedStatus();

  const caseQuery = useLive<CaseView>(`/api/cases/${CASE_ID}`, 4000, ["cases"]);
  const evidenceQuery = useLive<EvidenceItem[]>(`/api/cases/${CASE_ID}/evidence`, 4000, ["evidence"]);
  const visualEvidenceQuery = useLive<EvidenceItem[]>(
    `/api/cases/${CASE_ID}/evidence?type=video_observation&limit=50`,
    4000, ["evidence"],
  );
  const timelineQuery = useLive<SiteEventItem[]>(`/api/cases/${CASE_ID}/timeline`, 4000, ["site_events"]);
  const runsQuery = useLive<AgentRun[]>(`/api/cases/${CASE_ID}/agents`, 4000, ["agent_runs"]);
  const actionsQuery = useLive<ActionRecord[]>(`/api/cases/${CASE_ID}/actions`, 4000, ["actions"]);
  const redactionQuery = useLive<RedactionRow[]>(`/api/media/redacted`, 10000, ["redaction_manifest"]);
  const framesQuery = useLive<FrameRow[]>(`/api/media/frames`, 15000, []);
  const modelQuery = useLive<SiteModelView>(`/api/site-model`, 20000, ["site_model"]);
  const workersQuery = useLive<WorkerPositionView[]>(`/api/workers`, 4000, ["worker_positions"]);
  const sourcesQuery = useLive<SourceRow[]>(`/api/sources`, 5000, ["source_manifest"]);
  const notificationsQuery = useLive<NotificationRecord[]>(`/api/notifications`, 4000, ["notifications"]);
  const policyQuery = useLive<PolicyLogRow[]>(`/api/policy/log`, 8000, ["policy_log"]);
  const systemQuery = useLive<SystemSnapshot>(`/api/system`, 6000, []);
  const replayQuery = useLive<ReplayStatus>(`/api/replay`, 2000, ["replay_state"]);
  const reconstructionQuery = useLive<ReconstructionStatus>(`/api/reconstruction/status`, 1200, []);
  const cloudQuery = useLive<PointCloud>(`/api/reconstruction/points`, 5000, []);
  const sensorsQuery = useLive<SensorReading[]>(`/api/sensors/latest`, 3000, ["telemetry"]);

  const build3D = useCallback(async () => {
    await postJson<ReconstructionStatus>("/api/reconstruction/start");
    await reconstructionQuery.refresh();
  }, [reconstructionQuery]);

  const refreshAll = useCallback(() => {
    void caseQuery.refresh();
    void evidenceQuery.refresh();
    void visualEvidenceQuery.refresh();
    void actionsQuery.refresh();
    void notificationsQuery.refresh();
    void policyQuery.refresh();
    void runsQuery.refresh();
    void replayQuery.refresh();
    void framesQuery.refresh();
    void redactionQuery.refresh();
    void sensorsQuery.refresh();
  }, [
    caseQuery,
    evidenceQuery,
    visualEvidenceQuery,
    actionsQuery,
    notificationsQuery,
    policyQuery,
    runsQuery,
    replayQuery,
    framesQuery,
    redactionQuery,
    sensorsQuery,
  ]);

  const runReview = useCallback(async () => {
    try {
      await postJson(`/api/cases/${CASE_ID}/review`);
    } finally {
      refreshAll();
    }
  }, [refreshAll]);

  const visualEvidence = visualEvidenceQuery.data ?? [];
  const visualIds = new Set(visualEvidence.map((item) => item._id));
  const evidence = [
    ...visualEvidence,
    ...(evidenceQuery.data ?? []).filter((item) => !visualIds.has(item._id)),
  ];

  if (!mounted) {
    return (
      <main className="flex min-h-screen items-center justify-center text-sm text-slate-500">
        connecting to the local RiskTwin API…
      </main>
    );
  }

  return (
    <main className="flex min-h-screen flex-col gap-2 p-2">
      <DecisionBanner
        caseView={caseQuery.data}
        system={systemQuery.data}
        connected={connected}
      />

      <ConnectionGuide
        system={systemQuery.data}
        model={modelQuery.data}
        evidence={evidence}
      />

      <SensorPanel readings={sensorsQuery.data ?? []} onChange={refreshAll} />

      <div className="grid grid-cols-1 gap-2 xl:grid-cols-12">
        <div className="min-h-[38rem] xl:col-span-5">
          <VisionPanel
            frames={framesQuery.data ?? []}
            redactions={redactionQuery.data ?? []}
            evidence={evidence}
            onReview={runReview}
            onUploaded={refreshAll}
          />
        </div>
        <div className="min-h-[38rem] xl:col-span-7">
          <SiteMap
            model={modelQuery.data}
            workers={workersQuery.data ?? []}
            evidence={evidence}
            liftActive={Boolean(caseQuery.data?.liftActive)}
            reconstruction={reconstructionQuery.data}
            cloud={cloudQuery.data}
            onBuild3D={build3D}
          />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-2 xl:grid-cols-12">
        <div className="min-h-[30rem] xl:col-span-4">
          <AgentCards runs={runsQuery.data ?? []} evidence={evidence} />
        </div>
        <div className="min-h-[30rem] xl:col-span-5">
          <SystemPanel system={systemQuery.data} replay={replayQuery.data} onChange={refreshAll} />
        </div>
        <div className="flex min-h-[30rem] flex-col gap-2 xl:col-span-3">
          <div className="min-h-[14rem] flex-1">
            <ActionPanel
              actions={actionsQuery.data ?? []}
              notifications={notificationsQuery.data ?? []}
              onChange={refreshAll}
            />
          </div>
          <div className="min-h-[14rem] flex-1">
            <SourcePanel sources={sourcesQuery.data ?? []} />
          </div>
        </div>
      </div>

      <div className="h-72">
        <EventStream
          events={timelineQuery.data ?? []}
          evidence={evidence}
          policyLog={policyQuery.data ?? []}
          storeBackend={String(systemQuery.data?.storage?.backend ?? "connecting…")}
        />
      </div>

      <footer className="flex flex-wrap items-center justify-between gap-2 px-1 pb-1 text-[10px] text-slate-600">
        <span>
          RiskTwin is decision support. It never commands equipment, never performs facial
          recognition and never tracks a worker outside an active safety case.
        </span>
        <a className="underline" href="/worker">
          worker page
        </a>
      </footer>
    </main>
  );
}
