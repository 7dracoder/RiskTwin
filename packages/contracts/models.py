"""Validated contracts shared by the API, the agents and the dashboard.

Every agent return value is validated against one of these models before it may
be written to the database (spec section 6.3). Timestamps are carried as
timezone-aware datetimes in Python and serialised to ISO-8601 `Z` strings on the
wire and at rest, so the file-backed store and MongoDB behave identically.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def short_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #


class Decision(StrEnum):
    """Case outcomes. CONDITIONAL_APPROVAL is the pre-clearance state from
    spec section 7.5; only a human may convert it into an issued permit."""

    APPROVE = "APPROVE"
    CONDITIONAL_APPROVAL = "CONDITIONAL_APPROVAL"
    HOLD = "HOLD"
    ESCALATE = "ESCALATE"


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


SEVERITY_RANK: dict[str, int] = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


class AlertTier(StrEnum):
    INFO = "INFO"
    CAUTION = "CAUTION"
    STOP_ACK_REQUIRED = "STOP_ACK_REQUIRED"
    ESCALATE = "ESCALATE"


class EvidenceType(StrEnum):
    VIDEO_OBSERVATION = "video_observation"
    AUDIO_OBSERVATION = "audio_observation"
    POLICY_EVIDENCE = "policy_evidence"
    TELEMETRY_OBSERVATION = "telemetry_observation"
    PROXIMITY_OBSERVATION = "proximity_observation"
    SOURCE_FRESHNESS = "source_freshness"


class SourceStatus(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


class PolicyEffect(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class ActionStatus(StrEnum):
    PROPOSED = "PROPOSED"
    BLOCKED = "BLOCKED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"


class NotificationStatus(StrEnum):
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    EXPIRED = "EXPIRED"


class AgentRunStatus(StrEnum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class WorkerZoneRelation(StrEnum):
    SAFE = "safe"
    APPROACHING = "approaching"
    INSIDE_RISK_ZONE = "inside_risk_zone"
    COVERAGE_UNKNOWN = "coverage_unknown"


# --------------------------------------------------------------------------- #
# Base
# --------------------------------------------------------------------------- #


class RiskTwinModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_serializer("*", when_used="json")
    def _serialize_datetimes(self, value: Any) -> Any:
        if isinstance(value, datetime):
            return iso(value)
        return value

    def to_doc(self) -> dict[str, Any]:
        """Storage/wire representation: plain JSON types only."""
        return self.model_dump(mode="json", by_alias=True)


# --------------------------------------------------------------------------- #
# Events (`site_events`, `telemetry`, `worker_positions`)
# --------------------------------------------------------------------------- #


class SiteEvent(RiskTwinModel):
    """Immutable incoming event log entry."""

    id: str = Field(default_factory=lambda: short_id("evt"), alias="_id")
    caseId: str
    type: str
    source: str
    sourceId: str | None = None
    timestamp: datetime = Field(default_factory=utcnow)
    isSimulated: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)


class TelemetryReading(RiskTwinModel):
    id: str = Field(default_factory=lambda: short_id("tel"), alias="_id")
    caseId: str
    kind: str
    value: float | str | bool
    unit: str | None = None
    timestamp: datetime = Field(default_factory=utcnow)
    source: str
    sourceId: str | None = None
    isSimulated: bool = True


class WorkerPosition(RiskTwinModel):
    id: str = Field(default_factory=lambda: short_id("pos"), alias="_id")
    caseId: str
    workerAlias: str
    zoneId: str | None = None
    floorId: str | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    accuracyMeters: float | None = None
    headingDegrees: float | None = None
    speedMps: float | None = None
    locationSource: str = "manual-zone"
    isSimulated: bool = False
    siteModelVersion: int | None = None
    relation: WorkerZoneRelation = WorkerZoneRelation.COVERAGE_UNKNOWN
    timestamp: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------- #
# Evidence (spec section 6.3)
# --------------------------------------------------------------------------- #


class Evidence(RiskTwinModel):
    id: str = Field(default_factory=lambda: short_id("ev"), alias="_id")
    caseId: str
    agent: str
    evidenceType: EvidenceType
    sourceRefs: list[str] = Field(default_factory=list)
    finding: str
    confidence: float = Field(ge=0.0, le=1.0)
    severity: Severity
    timestamp: datetime = Field(default_factory=utcnow)
    # Structured detail the deterministic engine produced, e.g. threshold maths.
    detail: dict[str, Any] = Field(default_factory=dict)
    # True when a model (not deterministic code) authored the finding text.
    modelGenerated: bool = False
    modelRef: str | None = None


class AgentEvidenceEnvelope(RiskTwinModel):
    """Exactly the JSON an agent must return, per spec section 6.3."""

    caseId: str
    agent: str
    evidenceType: EvidenceType
    sourceRefs: list[str]
    finding: str
    confidence: float = Field(ge=0.0, le=1.0)
    severity: Severity
    timestamp: datetime = Field(default_factory=utcnow)
    detail: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Documents (`documents`)
# --------------------------------------------------------------------------- #


class DocumentChunk(RiskTwinModel):
    id: str = Field(default_factory=lambda: short_id("doc"), alias="_id")
    documentId: str
    sourceId: str
    title: str
    page: int
    chunkIndex: int
    text: str
    tags: list[str] = Field(default_factory=list)
    ruleKey: str | None = None
    # Machine-checkable limit carried by the rule, when the chunk states one.
    ruleValue: float | None = None
    ruleUnit: str | None = None
    localPath: str | None = None
    checksum: str | None = None
    ingestedAt: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------- #
# Site model (`site_model`)
# --------------------------------------------------------------------------- #


class Floor(RiskTwinModel):
    floorId: str
    elevationMeters: float


class Zone(RiskTwinModel):
    zoneId: str
    floorId: str
    polygon: list[list[float]]
    kind: Literal["safe-route", "lift-exclusion", "work-area", "access", "staging"]
    label: str | None = None
    # Metres of buffer outside the polygon that counts as "approaching".
    approachBufferMeters: float = 2.0


class CoordinateFrame(RiskTwinModel):
    name: str = "local-site-grid"
    units: str = "meters"
    origin: str = "south-west ground corner"


class SiteModelAsset(RiskTwinModel):
    localPath: str | None = None
    sha256: str | None = None


class SiteModel(RiskTwinModel):
    id: str = Field(default_factory=lambda: short_id("sm"), alias="_id")
    siteModelId: str
    version: int
    active: bool = False
    coordinateFrame: CoordinateFrame = Field(default_factory=CoordinateFrame)
    asset: SiteModelAsset = Field(default_factory=SiteModelAsset)
    floors: list[Floor] = Field(default_factory=list)
    zones: list[Zone] = Field(default_factory=list)
    hazards: list[dict[str, Any]] = Field(default_factory=list)
    derivedFrom: str | None = None
    updatedAt: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------- #
# Case, decision, actions
# --------------------------------------------------------------------------- #


class CommanderVerdict(RiskTwinModel):
    """Exactly the Safety Commander response shape from spec section 6.3."""

    caseId: str
    decision: Decision
    reasons: list[str]
    evidenceIds: list[str]
    requiredBeforeApproval: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    narrative: str | None = None
    degradedMode: bool = False
    modelRef: str | None = None
    decidedAt: datetime = Field(default_factory=utcnow)


class Case(RiskTwinModel):
    id: str = Field(alias="_id")
    caseId: str
    title: str
    status: Literal["OPEN", "CLOSED"] = "OPEN"
    decision: Decision = Decision.ESCALATE
    reasons: list[str] = Field(default_factory=list)
    requiredBeforeApproval: list[str] = Field(default_factory=list)
    latestEvidenceIds: list[str] = Field(default_factory=list)
    siteModelId: str | None = None
    siteModelVersion: int | None = None
    liftActive: bool = False
    confidence: float = 0.0
    degradedMode: bool = False
    narrative: str | None = None
    recoveredFromStore: bool = False
    createdAt: datetime = Field(default_factory=utcnow)
    updatedAt: datetime = Field(default_factory=utcnow)


class ActionRecord(RiskTwinModel):
    id: str = Field(default_factory=lambda: short_id("act"), alias="_id")
    caseId: str
    type: str
    status: ActionStatus
    requestedBy: str
    requiresApproval: bool
    reason: str | None = None
    policyEffect: PolicyEffect | None = None
    policyEvidence: list[str] = Field(default_factory=list)
    approvedBy: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    audit: list[dict[str, Any]] = Field(default_factory=list)
    createdAt: datetime = Field(default_factory=utcnow)
    updatedAt: datetime = Field(default_factory=utcnow)


class PolicyLogEntry(RiskTwinModel):
    id: str = Field(default_factory=lambda: short_id("pol"), alias="_id")
    caseId: str | None = None
    subject: str
    actionType: str
    effect: PolicyEffect
    reason: str
    policyId: str
    backend: str
    context: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------- #
# Notifications
# --------------------------------------------------------------------------- #


class Notification(RiskTwinModel):
    id: str = Field(default_factory=lambda: short_id("ntf"), alias="_id")
    caseId: str
    workerAlias: str
    tier: AlertTier
    message: str
    zoneId: str | None = None
    reasonEvidenceIds: list[str] = Field(default_factory=list)
    status: NotificationStatus = NotificationStatus.SENT
    requiresAck: bool = False
    ackDeadlineSeconds: int | None = None
    sentAt: datetime = Field(default_factory=utcnow)
    acknowledgedAt: datetime | None = None


# --------------------------------------------------------------------------- #
# Sources, replay, runs
# --------------------------------------------------------------------------- #


class SourceManifest(RiskTwinModel):
    id: str = Field(default_factory=lambda: short_id("src"), alias="_id")
    sourceId: str
    sourceClass: str
    label: str
    origin: str
    license: str
    critical: bool = False
    # True when the decision needs a continuously live feed from this source, so
    # silence is itself an adverse condition. Event-driven sources (a worker
    # device, an on-demand camera analysis) are critical to their own evidence but
    # are not expected to stream, and their silence must not block a clearance.
    requiresContinuousFeed: bool = False
    schemaVersion: int = 1
    ingestMode: str = "recorded-replay"
    freshnessSlaSeconds: int = 120
    status: SourceStatus = SourceStatus.UNAVAILABLE
    failureRule: str = "ESCALATE"
    lastEventAt: datetime | None = None
    retrievedAt: datetime = Field(default_factory=utcnow)
    checksum: str | None = None
    isSimulated: bool = True


class TelemetryRecordingEvent(RiskTwinModel):
    offsetSeconds: float
    kind: str
    value: float | str | bool
    unit: str | None = None
    sourceId: str
    label: str
    eventType: str = "telemetry"
    payload: dict[str, Any] = Field(default_factory=dict)


class TelemetryRecording(RiskTwinModel):
    id: str = Field(alias="_id")
    recordingId: str
    caseId: str
    source: str
    provenance: str
    license: str
    isSimulated: bool = True
    checksum: str | None = None
    durationSeconds: float = 0.0
    events: list[TelemetryRecordingEvent] = Field(default_factory=list)
    importedAt: datetime = Field(default_factory=utcnow)


class ReplayState(RiskTwinModel):
    id: str = Field(alias="_id")
    caseId: str
    recordingId: str
    cursor: int = 0
    positionSeconds: float = 0.0
    speed: float = 1.0
    status: Literal["IDLE", "RUNNING", "PAUSED", "COMPLETED"] = "IDLE"
    startedAt: datetime | None = None
    updatedAt: datetime = Field(default_factory=utcnow)


class AgentRun(RiskTwinModel):
    id: str = Field(default_factory=lambda: short_id("run"), alias="_id")
    caseId: str
    agent: str
    inputEventId: str | None = None
    status: AgentRunStatus = AgentRunStatus.STARTED
    detail: str | None = None
    evidenceIds: list[str] = Field(default_factory=list)
    startedAt: datetime = Field(default_factory=utcnow)
    completedAt: datetime | None = None
    durationMs: int | None = None


class RedactionManifest(RiskTwinModel):
    id: str = Field(default_factory=lambda: short_id("red"), alias="_id")
    caseId: str
    inputPath: str
    inputSha256: str
    outputPath: str
    outputSha256: str | None = None
    detectorVersion: str
    redactionMethod: str
    framesProcessed: int = 0
    redactedRegions: int = 0
    redactedFrameRanges: list[list[int]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    createdAt: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------- #
# API request bodies (spec section 10)
# --------------------------------------------------------------------------- #


class WorkerPositionRequest(RiskTwinModel):
    caseId: str
    workerAlias: str
    zoneId: str | None = None
    floorId: str | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    accuracyMeters: float | None = None
    headingDegrees: float | None = None
    speedMps: float | None = None
    locationSource: str = "manual-zone"
    isSimulated: bool = False
    timestamp: datetime | None = None


class TelemetryRequest(RiskTwinModel):
    caseId: str
    kind: str
    value: float | str | bool
    unit: str | None = None
    source: str = "local-replay"
    sourceId: str | None = None
    isSimulated: bool = True
    timestamp: datetime | None = None


class ActionRequest(RiskTwinModel):
    type: str
    requestedBy: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ApprovalRequest(RiskTwinModel):
    approvedBy: str
    approve: bool = True
    note: str | None = None


class AcknowledgeRequest(RiskTwinModel):
    workerAlias: str
    notificationId: str | None = None
