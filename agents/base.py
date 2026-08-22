"""Shared agent context and the single validated path for writing evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from packages.config import Settings
from packages.contracts import (
    AgentEvidenceEnvelope,
    Evidence,
    EvidenceType,
    Severity,
)
from packages.inference import InferenceSuite
from packages.runtime import AgentRuntime, PolicyEngine
from packages.storage.base import EVIDENCE, Store


@dataclass(slots=True)
class AgentContext:
    """Everything an agent role is allowed to touch."""

    store: Store
    settings: Settings
    models: InferenceSuite
    runtime: AgentRuntime
    policy: PolicyEngine


async def write_evidence(
    context: AgentContext,
    *,
    case_id: str,
    agent: str,
    evidence_type: EvidenceType,
    finding: str,
    confidence: float,
    severity: Severity,
    source_refs: list[str],
    detail: dict[str, Any] | None = None,
    model_generated: bool = False,
    model_ref: str | None = None,
) -> Evidence:
    """Validate an agent finding against the contract, then persist it.

    Agents never write to the store directly; validation happens here so a
    malformed or out-of-range agent result can never reach the case record
    (spec section 6.3).
    """
    envelope = AgentEvidenceEnvelope(
        caseId=case_id,
        agent=agent,
        evidenceType=evidence_type,
        sourceRefs=source_refs,
        finding=finding,
        confidence=confidence,
        severity=severity,
        detail=detail or {},
    )
    record = Evidence(
        caseId=envelope.caseId,
        agent=envelope.agent,
        evidenceType=envelope.evidenceType,
        sourceRefs=envelope.sourceRefs,
        finding=envelope.finding,
        confidence=envelope.confidence,
        severity=envelope.severity,
        timestamp=envelope.timestamp,
        detail=envelope.detail,
        modelGenerated=model_generated,
        modelRef=model_ref,
    )
    await context.store.insert_one(EVIDENCE, record.to_doc())
    return record


async def load_evidence(context: AgentContext, case_id: str) -> list[Evidence]:
    docs = await context.store.find(
        EVIDENCE, {"caseId": case_id}, sort=[("timestamp", 1)]
    )
    return [Evidence.model_validate(doc) for doc in docs]
