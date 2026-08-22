"""Deterministic risk evaluation.

Threshold arithmetic, zone containment, source freshness and the decision itself
are plain code (spec section 4.2). A text model may explain the correlated
evidence and draft the action plan; it may never invent the anomaly calculation or
the verdict.

Decision ladder, highest priority first:

1. no applicable rule retrieved                       -> ESCALATE
2. a critical source is stale or unavailable          -> ESCALATE
3. required modality evidence is missing              -> ESCALATE
4. sources conflict and nothing resolves the conflict -> ESCALATE
5. a stop-work condition is present                   -> HOLD
6. otherwise, limits verified and zone clear          -> CONDITIONAL_APPROVAL

APPROVE is never produced here. Converting CONDITIONAL_APPROVAL into an issued
permit requires the named human approver action (spec section 8.2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from packages.contracts import (
    SEVERITY_RANK,
    Decision,
    DocumentChunk,
    Evidence,
    EvidenceType,
    Severity,
    SourceManifest,
    SourceStatus,
)
from packages.media.documents import (
    RULE_EXCLUSION_ZONE_CLEAR,
    RULE_HUMAN_APPROVAL,
    RULE_MAX_LOAD_UTILISATION,
    RULE_MAX_WIND_GUST,
    RULE_RESTART_PROCEDURE,
    RULE_STALE_DATA_ACTION,
)

FindingClass = Literal["escalate", "hold", "info"]

# Telemetry kinds the engine can check against a retrieved limit.
THRESHOLD_RULES: dict[str, str] = {
    "wind_gust_kmh": RULE_MAX_WIND_GUST,
    "crane_load_pct": RULE_MAX_LOAD_UTILISATION,
}

READABLE_KIND = {
    "wind_gust_kmh": "Wind gust",
    "crane_load_pct": "Load utilisation",
    "hydraulic_temp_c": "Hydraulic temperature",
}


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class RuleCitation:
    ruleKey: str
    documentId: str
    title: str
    page: int
    value: float | None
    unit: str | None
    text: str

    @property
    def ref(self) -> str:
        return f"{self.documentId}:p{self.page}"


@dataclass(slots=True)
class RuleSet:
    maxWindGustKmh: float | None = None
    maxLoadUtilisationPct: float | None = None
    exclusionZoneId: str | None = None
    staleDataAction: str | None = None
    humanApprovalRequired: bool = False
    restartSteps: list[str] = field(default_factory=list)
    citations: dict[str, RuleCitation] = field(default_factory=dict)

    @property
    def has_any(self) -> bool:
        return bool(self.citations)

    @property
    def missing(self) -> list[str]:
        gaps = []
        if self.maxWindGustKmh is None:
            gaps.append(RULE_MAX_WIND_GUST)
        if self.maxLoadUtilisationPct is None:
            gaps.append(RULE_MAX_LOAD_UTILISATION)
        if self.exclusionZoneId is None:
            gaps.append(RULE_EXCLUSION_ZONE_CLEAR)
        return gaps

    @property
    def sufficient_for_clearance(self) -> bool:
        """A clearance needs the environmental limit, the load limit and the zone rule."""
        return not self.missing

    def citation_refs(self) -> list[str]:
        return sorted({citation.ref for citation in self.citations.values()})


def build_ruleset(chunks: list[DocumentChunk]) -> RuleSet:
    """Assemble the applicable limits from retrieved document chunks.

    The most restrictive stated limit wins, so a stricter project-specific lift
    plan is never relaxed by a more permissive generic document.
    """
    rules = RuleSet()
    for chunk in chunks:
        if not chunk.ruleKey:
            continue
        citation = RuleCitation(
            ruleKey=chunk.ruleKey,
            documentId=chunk.documentId,
            title=chunk.title,
            page=chunk.page,
            value=chunk.ruleValue,
            unit=chunk.ruleUnit,
            text=chunk.text,
        )

        if chunk.ruleKey == RULE_MAX_WIND_GUST and chunk.ruleValue is not None:
            if rules.maxWindGustKmh is None or chunk.ruleValue < rules.maxWindGustKmh:
                rules.maxWindGustKmh = chunk.ruleValue
                rules.citations[RULE_MAX_WIND_GUST] = citation
        elif chunk.ruleKey == RULE_MAX_LOAD_UTILISATION and chunk.ruleValue is not None:
            if (
                rules.maxLoadUtilisationPct is None
                or chunk.ruleValue < rules.maxLoadUtilisationPct
            ):
                rules.maxLoadUtilisationPct = chunk.ruleValue
                rules.citations[RULE_MAX_LOAD_UTILISATION] = citation
        elif chunk.ruleKey == RULE_EXCLUSION_ZONE_CLEAR:
            rules.exclusionZoneId = chunk.ruleUnit or rules.exclusionZoneId
            rules.citations.setdefault(RULE_EXCLUSION_ZONE_CLEAR, citation)
        elif chunk.ruleKey == RULE_STALE_DATA_ACTION:
            rules.staleDataAction = chunk.ruleUnit or "ESCALATE"
            rules.citations.setdefault(RULE_STALE_DATA_ACTION, citation)
        elif chunk.ruleKey == RULE_HUMAN_APPROVAL:
            rules.humanApprovalRequired = True
            rules.citations.setdefault(RULE_HUMAN_APPROVAL, citation)
        elif chunk.ruleKey == RULE_RESTART_PROCEDURE:
            rules.restartSteps = _extract_steps(chunk.text)
            rules.citations.setdefault(RULE_RESTART_PROCEDURE, citation)
    return rules


def _extract_steps(text: str) -> list[str]:
    """Read a numbered procedure, joining lines wrapped by the source document."""
    steps: list[str] = []
    in_step = False
    for line in text.splitlines():
        stripped = line.strip()
        starts_step = len(stripped) > 3 and stripped[0].isdigit() and stripped[1] in ".)"
        if starts_step:
            steps.append(stripped[2:].strip())
            in_step = True
        elif not stripped:
            # A blank line ends the numbered list; the prose after it is commentary.
            in_step = False
        elif in_step:
            steps[-1] = f"{steps[-1]} {stripped}"
    return steps


# --------------------------------------------------------------------------- #
# Thresholds
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class ThresholdVerdict:
    kind: str
    value: float
    unit: str | None
    limit: float | None
    ruleKey: str | None
    breached: bool
    deviation: float | None
    citation: str | None

    def as_detail(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "value": self.value,
            "unit": self.unit,
            "limit": self.limit,
            "ruleKey": self.ruleKey,
            "breached": self.breached,
            "deviation": self.deviation,
            "citation": self.citation,
        }

    def anomaly_block(self) -> str:
        """The 'ANOMALY DETECTED' panel text from spec section 4.2."""
        name = READABLE_KIND.get(self.kind, self.kind)
        unit = f" {self.unit}" if self.unit else ""
        lines = [
            "ANOMALY DETECTED",
            f"{name}: {self.value:g}{unit}",
            f"Lift-plan maximum: {self.limit:g}{unit}" if self.limit is not None else
            "Lift-plan maximum: not retrieved",
        ]
        if self.deviation is not None:
            lines.append(f"Deviation: +{self.deviation:g}{unit}")
        if self.citation:
            lines.append(f"Evidence: {self.citation}")
        return "\n".join(lines)


def evaluate_threshold(kind: str, value: Any, rules: RuleSet, unit: str | None = None) -> ThresholdVerdict:
    """Compare one reading with its retrieved limit. Never guesses a limit."""
    numeric = _as_float(value)
    rule_key = THRESHOLD_RULES.get(kind)
    limit: float | None = None
    if rule_key == RULE_MAX_WIND_GUST:
        limit = rules.maxWindGustKmh
    elif rule_key == RULE_MAX_LOAD_UTILISATION:
        limit = rules.maxLoadUtilisationPct

    citation = rules.citations.get(rule_key or "")
    breached = numeric is not None and limit is not None and numeric > limit
    return ThresholdVerdict(
        kind=kind,
        value=numeric if numeric is not None else 0.0,
        unit=unit or (citation.unit if citation else None),
        limit=limit,
        ruleKey=rule_key,
        breached=breached,
        deviation=round(numeric - limit, 2) if breached and numeric is not None and limit is not None else None,
        citation=citation.ref if citation else None,
    )


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Current facts
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class CurrentFacts:
    """The latest state per subject, so a superseded reading cannot linger."""

    telemetry: dict[str, Evidence] = field(default_factory=dict)
    proximity: dict[str, Evidence] = field(default_factory=dict)
    vision: dict[str, Evidence] = field(default_factory=dict)
    audio: dict[str, Evidence] = field(default_factory=dict)
    freshness: dict[str, Evidence] = field(default_factory=dict)
    policy: list[Evidence] = field(default_factory=list)

    @property
    def evidence_types(self) -> set[str]:
        present: set[str] = set()
        if self.telemetry:
            present.add(EvidenceType.TELEMETRY_OBSERVATION.value)
        if self.proximity:
            present.add(EvidenceType.PROXIMITY_OBSERVATION.value)
        if self.vision:
            present.add(EvidenceType.VIDEO_OBSERVATION.value)
        if self.audio:
            present.add(EvidenceType.AUDIO_OBSERVATION.value)
        if self.policy:
            present.add(EvidenceType.POLICY_EVIDENCE.value)
        if self.freshness:
            present.add(EvidenceType.SOURCE_FRESHNESS.value)
        return present


def reduce_current_facts(evidence: list[Evidence]) -> CurrentFacts:
    facts = CurrentFacts()
    for item in sorted(evidence, key=lambda e: e.timestamp):
        detail = item.detail or {}
        if item.evidenceType is EvidenceType.TELEMETRY_OBSERVATION:
            key = str(detail.get("kind") or item.id)
            facts.telemetry[key] = item
        elif item.evidenceType is EvidenceType.PROXIMITY_OBSERVATION:
            key = str(detail.get("workerAlias") or item.id)
            facts.proximity[key] = item
        elif item.evidenceType is EvidenceType.VIDEO_OBSERVATION:
            key = str(detail.get("zoneId") or "unmapped")
            facts.vision[key] = item
        elif item.evidenceType is EvidenceType.AUDIO_OBSERVATION:
            key = str(detail.get("subject") or "crew")
            facts.audio[key] = item
        elif item.evidenceType is EvidenceType.SOURCE_FRESHNESS:
            key = str(detail.get("sourceId") or item.id)
            facts.freshness[key] = item
        elif item.evidenceType is EvidenceType.POLICY_EVIDENCE:
            facts.policy.append(item)
    return facts


# --------------------------------------------------------------------------- #
# Decision
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class RiskFinding:
    code: str
    findingClass: FindingClass
    text: str
    severity: Severity
    evidenceIds: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "class": self.findingClass,
            "text": self.text,
            "severity": self.severity.value,
            "evidenceIds": self.evidenceIds,
            "citations": self.citations,
        }


@dataclass(slots=True)
class DecisionOutcome:
    decision: Decision
    reasons: list[str]
    evidenceIds: list[str]
    requiredBeforeApproval: list[str]
    confidence: float
    findings: list[RiskFinding]
    anomalies: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "reasons": self.reasons,
            "evidenceIds": self.evidenceIds,
            "requiredBeforeApproval": self.requiredBeforeApproval,
            "confidence": self.confidence,
            "findings": [finding.as_dict() for finding in self.findings],
            "anomalies": self.anomalies,
        }


def derive_decision(
    *,
    evidence: list[Evidence],
    rules: RuleSet,
    sources: list[SourceManifest],
    lift_active: bool,
) -> DecisionOutcome:
    facts = reduce_current_facts(evidence)
    findings: list[RiskFinding] = []
    anomalies: list[str] = []

    # 1. Applicable rule must have been retrieved.
    if not rules.sufficient_for_clearance:
        findings.append(
            RiskFinding(
                code="RULES_NOT_RETRIEVED",
                findingClass="escalate",
                text=(
                    "The applicable lift-plan limits have not been retrieved "
                    f"({', '.join(rules.missing)}); a clearance cannot be authorised without them."
                ),
                severity=Severity.HIGH,
                evidenceIds=[item.id for item in facts.policy],
            )
        )

    # 2. Freshness of the continuously monitored critical sources. Only a source
    #    the decision depends on streaming can block on silence; an event-driven
    #    source contributes missing evidence instead.
    for source in sources:
        if not (source.critical and source.requiresContinuousFeed):
            continue
        if source.status is SourceStatus.FRESH:
            continue
        evidence_item = facts.freshness.get(source.sourceId)
        never_reported = source.status is SourceStatus.UNAVAILABLE and source.lastEventAt is None
        findings.append(
            RiskFinding(
                code="CRITICAL_SOURCE_UNVERIFIED",
                findingClass="escalate",
                text=(
                    f"Critical source {source.label} ({source.sourceId}) is {source.status.value}"
                    + (
                        " and has never reported"
                        if never_reported
                        else f" against a {source.freshnessSlaSeconds}s freshness requirement"
                    )
                    + "; its condition cannot be verified."
                ),
                severity=Severity.CRITICAL,
                evidenceIds=[evidence_item.id] if evidence_item else [],
                citations=[rules.citations[RULE_STALE_DATA_ACTION].ref]
                if RULE_STALE_DATA_ACTION in rules.citations
                else [],
            )
        )

    # 3. Threshold breaches.
    for kind, item in facts.telemetry.items():
        detail = item.detail or {}
        if not detail.get("breached"):
            continue
        name = READABLE_KIND.get(kind, kind)
        unit = detail.get("unit") or ""
        findings.append(
            RiskFinding(
                code=f"THRESHOLD_BREACH:{kind}",
                findingClass="hold",
                text=(
                    f"{name} {detail.get('value')}{unit} exceeds the retrieved limit of "
                    f"{detail.get('limit')}{unit}."
                ),
                severity=Severity.CRITICAL if kind == "wind_gust_kmh" else Severity.HIGH,
                evidenceIds=[item.id],
                citations=[detail["citation"]] if detail.get("citation") else [],
            )
        )
        anomalies.append(_anomaly_text(name, detail))

    # 4. Worker inside or approaching an active exclusion zone.
    worker_in_zone: list[str] = []
    for alias, item in facts.proximity.items():
        detail = item.detail or {}
        relation = detail.get("relation")
        zone_id = detail.get("zoneId")
        if relation == "inside_risk_zone":
            worker_in_zone.append(alias)
            findings.append(
                RiskFinding(
                    code="WORKER_IN_EXCLUSION_ZONE",
                    findingClass="hold" if lift_active else "info",
                    text=(
                        f"{alias} is inside exclusion zone {zone_id}"
                        + (" during an active lift." if lift_active else " while the lift is not active.")
                    ),
                    severity=Severity.CRITICAL if lift_active else Severity.MEDIUM,
                    evidenceIds=[item.id],
                    citations=[rules.citations[RULE_EXCLUSION_ZONE_CLEAR].ref]
                    if RULE_EXCLUSION_ZONE_CLEAR in rules.citations
                    else [],
                )
            )
        elif relation == "approaching" and lift_active:
            findings.append(
                RiskFinding(
                    code="WORKER_APPROACHING_ZONE",
                    findingClass="info",
                    text=f"{alias} is approaching exclusion zone {zone_id} ({detail.get('distanceMeters')} m).",
                    severity=Severity.MEDIUM,
                    evidenceIds=[item.id],
                )
            )
        elif relation == "coverage_unknown":
            findings.append(
                RiskFinding(
                    code="POSITION_COVERAGE_UNKNOWN",
                    findingClass="escalate" if lift_active else "info",
                    text=f"Position coverage for {alias} cannot be resolved against the active site model.",
                    severity=Severity.HIGH,
                    evidenceIds=[item.id],
                )
            )

    # 5. Visual obstruction of the exclusion zone.
    visual_obstruction: list[str] = []
    for zone_id, item in facts.vision.items():
        detail = item.detail or {}
        if not detail.get("available", True):
            findings.append(
                RiskFinding(
                    code="VISION_EVIDENCE_MISSING",
                    findingClass="escalate",
                    text=(
                        "No visual evidence is available for the lift area; a scene finding "
                        "will not be fabricated."
                    ),
                    severity=Severity.HIGH,
                    evidenceIds=[item.id],
                )
            )
            continue
        risk_type = detail.get("riskType")
        if risk_type not in {"zone_obstruction", "person_in_exclusion_zone", "load_path_conflict"}:
            continue
        visual_obstruction.append(zone_id)
        confirmed = bool(detail.get("confirmed"))
        findings.append(
            RiskFinding(
                code="ZONE_OBSTRUCTION",
                findingClass="hold" if lift_active else "info",
                text=(
                    f"Visual evidence indicates {risk_type.replace('_', ' ')} affecting zone {zone_id}"
                    + ("." if confirmed else "; the finding is a candidate and needs human confirmation.")
                ),
                severity=Severity.HIGH if confirmed else Severity.MEDIUM,
                evidenceIds=[item.id],
                citations=[rules.citations[RULE_EXCLUSION_ZONE_CLEAR].ref]
                if RULE_EXCLUSION_ZONE_CLEAR in rules.citations
                else [],
            )
        )

    # 6. Crew statement conflicting with instrumented or visual evidence.
    for item in facts.audio.values():
        detail = item.detail or {}
        if not detail.get("available", True):
            findings.append(
                RiskFinding(
                    code="AUDIO_EVIDENCE_MISSING",
                    findingClass="info",
                    text="No crew transcript is available; the radio channel adds no evidence to this decision.",
                    severity=Severity.LOW,
                    evidenceIds=[item.id],
                )
            )
            continue
        claimed_clear = detail.get("claimsZoneClear")
        if not claimed_clear:
            continue
        contradicted_by_instrument = bool(worker_in_zone)
        contradicted_by_vision = claimed_clear in visual_obstruction
        if not (contradicted_by_instrument or contradicted_by_vision):
            continue
        resolved = contradicted_by_instrument
        findings.append(
            RiskFinding(
                code="CONFLICTING_SOURCES" if not resolved else "CONFLICT_RESOLVED_BY_INSTRUMENT",
                findingClass="hold" if resolved else "escalate",
                text=(
                    f"Crew radio states zone {claimed_clear} is clear, which conflicts with "
                    + (
                        f"the instrumented position of {', '.join(worker_in_zone)} inside the zone."
                        if resolved
                        else "unconfirmed visual evidence of an obstruction; the zone status cannot be confirmed."
                    )
                ),
                severity=Severity.HIGH,
                evidenceIds=[item.id],
            )
        )

    # 7. Independent-evidence requirement.
    evidence_types = facts.evidence_types - {EvidenceType.SOURCE_FRESHNESS.value}
    if len(evidence_types) < 2:
        findings.append(
            RiskFinding(
                code="INSUFFICIENT_INDEPENDENT_EVIDENCE",
                findingClass="escalate",
                text=(
                    "Fewer than two independent evidence types are present; a hold or a clearance "
                    "requires corroboration."
                ),
                severity=Severity.MEDIUM,
            )
        )

    decision = _resolve_decision(findings)
    contributing = [f for f in findings if f.findingClass in {"escalate", "hold"}] or findings
    reasons = [finding.text for finding in contributing]
    evidence_ids = _unique(
        [eid for finding in contributing for eid in finding.evidenceIds]
        + [item.id for item in facts.policy][:3]
    )
    return DecisionOutcome(
        decision=decision,
        reasons=reasons,
        evidenceIds=evidence_ids,
        requiredBeforeApproval=_required_steps(findings, rules, decision),
        confidence=_confidence(findings, facts, evidence),
        findings=findings,
        anomalies=anomalies,
    )


def _resolve_decision(findings: list[RiskFinding]) -> Decision:
    if any(finding.findingClass == "escalate" for finding in findings):
        return Decision.ESCALATE
    if any(finding.findingClass == "hold" for finding in findings):
        return Decision.HOLD
    return Decision.CONDITIONAL_APPROVAL


# Keywords that show the retrieved restart procedure already states a step, so the
# engine's own generic wording is dropped in favour of the citable document text.
_PLAN_COVERAGE = {
    "zone": ("zone", "clear"),
    "threshold": ("re-check", "recheck", "utilisation", "gust"),
    "freshness": ("fresh", "reporting"),
    "approval": ("approval", "approver", "supervisor"),
}


def _covered_by_plan(tag: str, restart_steps: list[str]) -> bool:
    keywords = _PLAN_COVERAGE.get(tag, ())
    if not keywords:
        return False
    return any(
        any(keyword in step.lower() for keyword in keywords) for step in restart_steps
    )


def _required_steps(findings: list[RiskFinding], rules: RuleSet, decision: Decision) -> list[str]:
    """The checklist a human must complete. The lift plan's own restart procedure
    wins wherever it covers the same ground, so the operator reads the approved
    document's wording rather than a paraphrase of it."""
    codes = {finding.code.split(":")[0] for finding in findings if finding.findingClass != "info"}
    generated: list[tuple[str, str]] = []
    if "WORKER_IN_EXCLUSION_ZONE" in codes or "ZONE_OBSTRUCTION" in codes:
        zone = rules.exclusionZoneId or "the exclusion zone"
        generated.append(("zone", f"Clear zone {zone} and confirm visually and over the radio"))
    if any(code.startswith("THRESHOLD_BREACH") for code in codes):
        generated.append(
            (
                "threshold",
                "Recheck the breached readings against the retrieved limits over a settled observation",
            )
        )
    if "CRITICAL_SOURCE_UNVERIFIED" in codes or "POSITION_COVERAGE_UNKNOWN" in codes:
        generated.append(("freshness", "Restore and verify coverage for every critical data source"))
    if "RULES_NOT_RETRIEVED" in codes:
        generated.append(("rules", "Retrieve and index the approved lift plan and safety SOP"))
    if "CONFLICTING_SOURCES" in codes:
        generated.append(
            (
                "conflict",
                "Resolve the conflict between the crew statement and the observed evidence on site",
            )
        )
    if "VISION_EVIDENCE_MISSING" in codes:
        generated.append(("vision", "Capture current visual evidence of the lift area"))

    steps = [text for tag, text in generated if not _covered_by_plan(tag, rules.restartSteps)]
    for step in rules.restartSteps:
        if step not in steps:
            steps.append(step)
    if rules.humanApprovalRequired or decision is not Decision.CONDITIONAL_APPROVAL:
        if not _covered_by_plan("approval", rules.restartSteps):
            steps.append("Named, qualified lift supervisor records the approval and the reason")
    return steps


def _confidence(findings: list[RiskFinding], facts: CurrentFacts, evidence: list[Evidence]) -> float:
    """Confidence in the *verdict*, driven by evidence coverage and its own confidence."""
    if not evidence:
        return 0.0
    contributing = [f for f in findings if f.findingClass in {"escalate", "hold"}]
    ids = {eid for finding in contributing for eid in finding.evidenceIds}
    relevant = [item for item in evidence if item.id in ids] or evidence
    mean_confidence = sum(item.confidence for item in relevant) / len(relevant)
    coverage = min(1.0, len(facts.evidence_types) / 4)
    severity_weight = max(
        (SEVERITY_RANK[finding.severity.value] for finding in contributing), default=1
    ) / 4
    score = 0.5 * mean_confidence + 0.3 * coverage + 0.2 * severity_weight
    return round(min(0.99, max(0.05, score)), 2)


def _anomaly_text(name: str, detail: dict[str, Any]) -> str:
    unit = detail.get("unit") or ""
    lines = [
        "ANOMALY DETECTED",
        f"{name}: {detail.get('value')}{unit}",
        f"Lift-plan maximum: {detail.get('limit')}{unit}",
    ]
    if detail.get("deviation") is not None:
        lines.append(f"Deviation: +{detail['deviation']}{unit}")
    if detail.get("citation"):
        lines.append(f"Evidence: {detail.get('sourceRef', 'telemetry')} + {detail['citation']}")
    return "\n".join(lines)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
