import type { Decision } from "./types";

export const DECISION_LABEL: Record<Decision, string> = {
  APPROVE: "APPROVED",
  CONDITIONAL_APPROVAL: "CONDITIONAL APPROVAL",
  HOLD: "HOLD",
  ESCALATE: "ESCALATE",
};

export const DECISION_STYLE: Record<Decision, string> = {
  APPROVE: "bg-approve/15 text-approve border-approve/40",
  CONDITIONAL_APPROVAL: "bg-approve/10 text-approve border-approve/30",
  HOLD: "bg-hold/15 text-hold border-hold/40",
  ESCALATE: "bg-escalate/15 text-escalate border-escalate/40",
};

export const SEVERITY_STYLE: Record<string, string> = {
  critical: "text-escalate",
  high: "text-hold",
  medium: "text-amber-300",
  low: "text-slate-300",
  info: "text-slate-400",
};

export function shortTime(iso: string | null | undefined): string {
  if (!iso) return "--:--:--";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "--:--:--" : date.toLocaleTimeString();
}

export function relativeSeconds(iso: string | null | undefined): string {
  if (!iso) return "never";
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms)) return "never";
  const seconds = Math.max(0, Math.round(ms / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  return `${Math.round(seconds / 60)}m ago`;
}
