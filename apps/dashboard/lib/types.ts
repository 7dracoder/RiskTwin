export type Decision = "APPROVE" | "CONDITIONAL_APPROVAL" | "HOLD" | "ESCALATE";

export interface CaseView {
  caseId: string;
  decision: Decision;
  reasons: string[];
  evidence: string[];
  requiredBeforeApproval: string[];
  confidence: number;
  narrative: string | null;
  liftActive: boolean;
  degradedMode: boolean;
  recoveredFromStore: boolean;
  siteModelId: string | null;
  siteModelVersion: number | null;
  evidenceCount: number;
  updatedAt: string;
}

export interface EvidenceItem {
  _id: string;
  caseId: string;
  agent: string;
  evidenceType: string;
  finding: string;
  confidence: number;
  severity: "info" | "low" | "medium" | "high" | "critical";
  timestamp: string;
  sourceRefs: string[];
  detail: Record<string, unknown>;
  modelGenerated: boolean;
  modelRef: string | null;
}

export interface SiteEventItem {
  _id: string;
  caseId: string;
  type: string;
  source: string;
  sourceId: string | null;
  timestamp: string;
  isSimulated: boolean;
  payload: Record<string, unknown>;
}

export interface AgentRun {
  _id: string;
  agent: string;
  caseId: string;
  status: "STARTED" | "COMPLETED" | "FAILED";
  startedAt: string;
  completedAt: string | null;
  durationMs: number | null;
  evidenceIds: string[];
  detail: string | null;
  inputEventId: string | null;
}

export interface Zone {
  zoneId: string;
  floorId: string;
  kind: string;
  label: string | null;
  polygon: number[][];
  centroid: number[];
  approachBufferMeters: number;
}

export interface SiteModelView {
  siteModelId: string;
  version: number;
  coordinateFrame: { name: string; units: string; origin: string };
  floors: { floorId: string; elevationMeters: number }[];
  zones: Zone[];
  hazards: Record<string, unknown>[];
  availableVersions: { siteModelId: string; version: number; active: boolean }[];
}

export interface WorkerPositionView {
  _id: string;
  workerAlias: string;
  zoneId: string | null;
  floorId: string | null;
  x: number | null;
  y: number | null;
  z: number | null;
  latitude: number | null;
  longitude: number | null;
  accuracyMeters: number | null;
  headingDegrees: number | null;
  speedMps: number | null;
  locationSource: string;
  isSimulated: boolean;
  relation: string | null;
  timestamp: string;
}

export interface SourceRow {
  sourceId: string;
  label: string;
  sourceClass: string;
  status: "fresh" | "stale" | "unavailable";
  critical: boolean;
  requiresContinuousFeed: boolean;
  freshnessSlaSeconds: number;
  lastEventAt: string | null;
  failureRule: string;
  license: string;
  origin: string;
}

export type ActionStatus =
  | "PROPOSED"
  | "BLOCKED"
  | "AWAITING_APPROVAL"
  | "APPROVED"
  | "REJECTED"
  | "EXECUTED";

export type PolicyEffect = "allow" | "deny" | "require_approval";

export interface ActionRecord {
  _id: string;
  caseId: string;
  type: string;
  requestedBy: string;
  status: ActionStatus;
  reason: string | null;
  requiresApproval: boolean;
  approvedBy: string | null;
  policyEffect: PolicyEffect | null;
  policyEvidence: string[];
  payload: Record<string, unknown>;
  audit: Record<string, unknown>[];
  createdAt: string;
  updatedAt: string;
}

export type AlertTier = "INFO" | "CAUTION" | "STOP_ACK_REQUIRED" | "ESCALATE";

export interface NotificationRecord {
  _id: string;
  caseId: string;
  workerAlias: string;
  tier: AlertTier;
  message: string;
  zoneId: string | null;
  status: "SENT" | "ACKNOWLEDGED" | "EXPIRED";
  requiresAck: boolean;
  ackDeadlineSeconds: number | null;
  acknowledgedAt: string | null;
  sentAt: string;
  reasonEvidenceIds: string[];
}

export interface PolicyLogRow {
  _id: string;
  caseId: string | null;
  subject: string;
  actionType: string;
  effect: PolicyEffect;
  reason: string;
  policyId: string;
  backend: string;
  context: Record<string, unknown>;
  timestamp: string;
}

export interface FrameRow {
  name: string;
  sizeBytes: number;
  assetName: string;
}

export interface SensorReading {
  _id: string;
  caseId: string;
  kind: string;
  value: number | string | boolean;
  unit: string | null;
  timestamp: string;
  source: string;
  sourceId: string | null;
  isSimulated: boolean;
}

export interface RedactionRow {
  name: string;
  caseId: string;
  framesProcessed: number;
  redactedRegions: number;
  detectorVersion: string;
  redactionMethod: string;
  warnings: string[];
  outputSha256: string | null;
}

export interface FrameworkRow {
  name: string;
  role: string;
  configured: string;
  installed: boolean;
  version: string | null;
  mode: "native" | "shim";
  note: string;
}

export interface SystemSnapshot {
  caseId: string;
  hostProfile: string;
  banner: string;
  degradedMode: boolean;
  models: Record<
    string,
    { modality: string; backend: string; model: string; degraded: boolean; note: string; label: string }
  >;
  localOnlyEndpoints: Record<string, string>;
  allowRemoteInference: boolean;
  dataWatcherLiveFetch: boolean;
  storage: Record<string, unknown>;
  policy: Record<string, unknown>;
  frameworks: FrameworkRow[];
  runtime: Record<string, unknown>;
  replay: Record<string, unknown>;
  websocketClients: number;
}

export interface ReplayStatus {
  banner: string;
  state: {
    caseId: string;
    recordingId: string;
    cursor: number;
    positionSeconds: number;
    speed: number;
    status: string;
  } | null;
  recording: {
    recordingId: string;
    provenance: string;
    license: string;
    isSimulated: boolean;
    checksum: string;
    durationSeconds: number;
    eventCount: number;
    upcoming: { offsetSeconds: number; label: string; eventType: string; sourceId: string | null }[];
  } | null;
}

export interface ReconstructionStatus {
  phase: "idle" | "extracting" | "features" | "matching" | "mapping" | "exporting" | "complete" | "failed" | "interrupted" | "unavailable";
  progress: number;
  message: string;
  available: boolean;
  engine: string;
  videoName: string | null;
  framesExtracted: number;
  registeredImages: number;
  pointCount: number;
  durationMs: number | null;
  outputReady: boolean;
  running: boolean;
  runId: string | null;
}

export interface PointCloud {
  points: { x: number; y: number; z: number; r: number; g: number; b: number }[];
  pointCount: number;
  sampledCount: number;
  runId: string | null;
}

export interface WorkerStatus {
  caseId: string;
  workerAlias: string;
  decision: Decision | null;
  liftActive: boolean;
  position: WorkerPositionView | null;
  notifications: NotificationRecord[];
  topEvidence: string[];
}
