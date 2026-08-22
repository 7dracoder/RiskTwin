"""Safety Commander — the verdict, its citations and the required next steps.

The verdict itself is produced by the deterministic risk engine over stored
evidence and retrieved rules. A served text model, when present, may only rewrite
the explanation and propose *additional* checks; it cannot change the decision,
the cited evidence or the mandatory steps that came from the retrieved rules.

The best autonomous outcome is CONDITIONAL_APPROVAL. Turning that into an issued
permit is a human action through the Policy Gate.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.base import AgentContext, load_evidence
from packages.contracts import (
    Case,
    CommanderVerdict,
    Decision,
    Evidence,
    SiteEvent,
    SourceManifest,
    utcnow,
)
from packages.risk_engine import DecisionOutcome, RuleSet, derive_decision
from packages.storage.base import CASES, SITE_EVENTS, SOURCE_MANIFEST

logger = logging.getLogger(__name__)

AGENT_NAME = "safety-commander"

_SYSTEM_PROMPT = (
    "You are the safety commander for a construction lift clearance. You are given a "
    "decision that has already been computed by deterministic rule checks, together with "
    "the evidence it cites. Explain the correlated evidence clearly for a site controller "
    "and propose any additional practical checks. You must not change the decision, "
    "invent readings, or contradict the listed findings. Reply with JSON only: "
    '{"narrative": string, "additionalChecks": string[]}'
)


def compose_narrative(case_id: str, outcome: DecisionOutcome) -> str:
    """The judge-facing conclusion block from spec section 4.2."""
    heading = f"{case_id} — {outcome.decision.value.replace('_', ' ')}"
    lines = [heading, ""]
    for index, reason in enumerate(outcome.reasons, start=1):
        lines.append(f"{index}. {reason}")
    if not outcome.reasons:
        lines.append("1. All retrieved limits are satisfied and no conflicting evidence is present.")
    return "\n".join(lines)


async def _load_sources(context: AgentContext) -> list[SourceManifest]:
    docs = await context.store.find(SOURCE_MANIFEST)
    return [SourceManifest.model_validate(doc) for doc in docs]


async def run(
    context: AgentContext,
    *,
    case_id: str,
    rules: RuleSet,
    lift_active: bool,
) -> CommanderVerdict:
    evidence: list[Evidence] = await load_evidence(context, case_id)
    sources = await _load_sources(context)

    outcome = derive_decision(
        evidence=evidence, rules=rules, sources=sources, lift_active=lift_active
    )
    narrative = compose_narrative(case_id, outcome)
    required = list(outcome.requiredBeforeApproval)
    model_used = False

    refinement = await _refine(context, case_id=case_id, outcome=outcome, evidence=evidence)
    if refinement is not None:
        model_used = True
        if refinement.get("narrative"):
            narrative = str(refinement["narrative"]).strip()
        for check in refinement.get("additionalChecks") or []:
            text = str(check).strip()
            if text and text not in required:
                required.append(text)

    verdict = CommanderVerdict(
        caseId=case_id,
        decision=outcome.decision,
        reasons=outcome.reasons,
        evidenceIds=outcome.evidenceIds,
        requiredBeforeApproval=required,
        confidence=outcome.confidence,
        narrative=narrative,
        degradedMode=not model_used,
        modelRef=context.models.text.info.label,
    )
    await _persist(context, verdict=verdict, outcome=outcome, lift_active=lift_active)
    return verdict


async def _refine(
    context: AgentContext,
    *,
    case_id: str,
    outcome: DecisionOutcome,
    evidence: list[Evidence],
) -> dict[str, Any] | None:
    """Ask the shared local text model to improve the explanation. Optional by design."""
    cited = {item.id: item for item in evidence}
    facts = {
        "caseId": case_id,
        "decision": outcome.decision.value,
        "findings": [finding.as_dict() for finding in outcome.findings],
        "citedEvidence": [
            {
                "id": item_id,
                "agent": cited[item_id].agent,
                "type": cited[item_id].evidenceType.value,
                "finding": cited[item_id].finding,
                "severity": cited[item_id].severity.value,
            }
            for item_id in outcome.evidenceIds
            if item_id in cited
        ],
        "mandatorySteps": outcome.requiredBeforeApproval,
    }
    return await context.models.text.complete_json(
        system=_SYSTEM_PROMPT,
        user=(
            "Decision context follows as JSON. Write the narrative for the site controller "
            "and list any additional checks.\n\n" + str(facts)
        ),
    )


async def _persist(
    context: AgentContext,
    *,
    verdict: CommanderVerdict,
    outcome: DecisionOutcome,
    lift_active: bool,
) -> None:
    existing = await context.store.find_one(CASES, {"caseId": verdict.caseId})
    previous_decision = existing.get("decision") if existing else None

    updates = {
        "decision": verdict.decision.value,
        "reasons": verdict.reasons,
        "requiredBeforeApproval": verdict.requiredBeforeApproval,
        "latestEvidenceIds": verdict.evidenceIds,
        "confidence": verdict.confidence,
        "degradedMode": verdict.degradedMode,
        "narrative": verdict.narrative,
        "liftActive": lift_active,
        "updatedAt": utcnow().isoformat().replace("+00:00", "Z"),
    }
    if existing is None:
        case = Case(_id=verdict.caseId, caseId=verdict.caseId, title=f"Critical lift {verdict.caseId}")
        await context.store.insert_one(CASES, {**case.to_doc(), **updates})
    else:
        await context.store.update_one(CASES, {"caseId": verdict.caseId}, updates)

    if previous_decision != verdict.decision.value:
        await context.store.insert_one(
            SITE_EVENTS,
            SiteEvent(
                caseId=verdict.caseId,
                type="decision",
                source="safety-commander",
                payload={
                    "from": previous_decision,
                    "to": verdict.decision.value,
                    "reasons": verdict.reasons,
                    "evidenceIds": verdict.evidenceIds,
                    "anomalies": outcome.anomalies,
                    "confidence": verdict.confidence,
                },
            ).to_doc(),
        )


def decision_banner(decision: Decision) -> str:
    return {
        Decision.APPROVE: "APPROVED",
        Decision.CONDITIONAL_APPROVAL: "CONDITIONAL APPROVAL",
        Decision.HOLD: "HOLD",
        Decision.ESCALATE: "ESCALATE",
    }[decision]
