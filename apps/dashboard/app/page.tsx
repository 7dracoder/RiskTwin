"use client";

import { useCallback } from "react";
import { ActionPanel } from "@/components/ActionPanel";
import { AgentCards } from "@/components/AgentCards";
import { DecisionBanner } from "@/components/DecisionBanner";
import { EventStream } from "@/components/EventStream";
import { SiteMap } from "@/components/SiteMap";
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
  RedactionRow,
  ReplayStatus,
  SiteEventItem,
  SiteModelView,
  SourceRow,
  SystemSnapshot,
  WorkerPositionView,
} from "@/lib/types";

export default function ControllerDashboard() {
  const mounted = useMounted();
  const { connected } = useFeedStatus();

  const caseQuery = useLive<CaseView>(`/api/cases/${CASE_ID}`);
  const evidenceQuery = useLive<EvidenceItem[]>(`/api/cases/${CASE_ID}/evidence`);
  const timelineQuery = useLive<SiteEventItem[]>(`/api/cases/${CASE_ID}/timeline`);
  const runsQuery = useLive<AgentRun[]>(`/api/cases/${CASE_ID}/agents`);
  const actionsQuery = useLive<ActionRecord[]>(`/api/cases/${CASE_ID}/actions`);
  const redactionQuery = useLive<RedactionRow[]>(`/api/media/redacted`);
  const framesQuery = useLive<FrameRow[]>(`/api/media/frames`);
  const modelQuery = useLive<SiteModelView>(`/api/site-model`, 20000);
  const workersQuery = useLive<WorkerPositionView[]>(`/api/workers`);
  const sourcesQuery = useLive<SourceRow[]>(`/api/sources`, 2000);
  const notificationsQuery = useLive<NotificationRecord[]>(`/api/notifications`);
  const policyQuery = useLive<PolicyLogRow[]>(`/api/policy/log`);
  const systemQuery = useLive<SystemSnapshot>(`/api/system`, 6000);
  const replayQuery = useLive<ReplayStatus>(`/api/replay`, 2000);

  const refreshAll = useCallback(() => {
    void caseQuery.refresh();
    void evidenceQuery.refresh();
    void actionsQuery.refresh();
    void notificationsQuery.refresh();
    void policyQuery.refresh();
    void runsQuery.refresh();
    void replayQuery.refresh();
    void framesQuery.refresh();
    void redactionQuery.refresh();
  }, [
    caseQuery,
    evidenceQuery,
    actionsQuery,
    notificationsQuery,
    policyQuery,
    runsQuery,
    replayQuery,
    framesQuery,
    redactionQuery,
  ]);

  const runReview = useCallback(async () => {
    try {
      await postJson(`/api/cases/${CASE_ID}/review`);
    } finally {
      refreshAll();
    }
  }, [refreshAll]);

  const evidence = evidenceQuery.data ?? [];

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

      <div className="grid flex-1 grid-cols-1 gap-2 xl:grid-cols-12">
        <div className="flex flex-col gap-2 xl:col-span-3">
          <div className="min-h-[26rem] flex-1">
            <VisionPanel
              frames={framesQuery.data ?? []}
              redactions={redactionQuery.data ?? []}
              evidence={evidence}
              onReview={runReview}
            />
          </div>
          <div className="min-h-[14rem]">
            <SourcePanel sources={sourcesQuery.data ?? []} />
          </div>
        </div>

        <div className="flex flex-col gap-2 xl:col-span-5">
          <div className="min-h-[24rem] flex-1">
            <SiteMap
              model={modelQuery.data}
              workers={workersQuery.data ?? []}
              evidence={evidence}
              liftActive={Boolean(caseQuery.data?.liftActive)}
            />
          </div>
          <div className="min-h-[18rem]">
            <ActionPanel
              actions={actionsQuery.data ?? []}
              notifications={notificationsQuery.data ?? []}
              onChange={refreshAll}
            />
          </div>
        </div>

        <div className="flex flex-col gap-2 xl:col-span-4">
          <div className="min-h-[22rem] flex-1">
            <AgentCards runs={runsQuery.data ?? []} evidence={evidence} />
          </div>
          <div className="min-h-[20rem]">
            <SystemPanel
              system={systemQuery.data}
              replay={replayQuery.data}
              onChange={refreshAll}
            />
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
