"""Rules Retrieval Agent — the exact applicable rule, not a safety summary.

Retrieval is deterministic on `ruleKey` and `tags` against the indexed local
document chunks (spec section 7.3). Every returned rule carries its document, page
and the numeric limit the risk engine will actually apply, so the decision can be
traced back to a specific line of an approved document.
"""

from __future__ import annotations

import logging

from agents.base import AgentContext, write_evidence
from packages.contracts import DocumentChunk, EvidenceType, Severity
from packages.media.documents import (
    RULE_EXCLUSION_ZONE_CLEAR,
    RULE_HUMAN_APPROVAL,
    RULE_MAX_LOAD_UTILISATION,
    RULE_MAX_WIND_GUST,
    RULE_RESTART_PROCEDURE,
    RULE_STALE_DATA_ACTION,
)
from packages.risk_engine import RuleSet, build_ruleset
from packages.storage.base import DOCUMENTS

logger = logging.getLogger(__name__)

AGENT_NAME = "rules-retrieval"

# The rules a lift-clearance decision depends on.
REQUIRED_RULE_KEYS = [
    RULE_MAX_WIND_GUST,
    RULE_MAX_LOAD_UTILISATION,
    RULE_EXCLUSION_ZONE_CLEAR,
    RULE_STALE_DATA_ACTION,
    RULE_HUMAN_APPROVAL,
    RULE_RESTART_PROCEDURE,
]


async def retrieve_chunks(context: AgentContext, rule_keys: list[str] | None = None) -> list[DocumentChunk]:
    keys = rule_keys or REQUIRED_RULE_KEYS
    docs = await context.store.find(DOCUMENTS, {"ruleKey": {"$in": keys}})
    return [DocumentChunk.model_validate(doc) for doc in docs]


async def load_ruleset(context: AgentContext) -> RuleSet:
    """Build the applicable ruleset without writing evidence, for read paths."""
    return build_ruleset(await retrieve_chunks(context))


async def run(context: AgentContext, *, case_id: str) -> tuple[list[str], RuleSet]:
    """Retrieve the applicable rules and write one policy evidence item per rule."""
    chunks = await retrieve_chunks(context)
    rules = build_ruleset(chunks)

    if not chunks:
        record = await write_evidence(
            context,
            case_id=case_id,
            agent=AGENT_NAME,
            evidence_type=EvidenceType.POLICY_EVIDENCE,
            finding=(
                "No lift plan or safety SOP has been indexed, so no applicable rule can be "
                "retrieved. A clearance cannot be authorised without the governing rule."
            ),
            confidence=1.0,
            severity=Severity.HIGH,
            source_refs=["documents:none"],
            detail={"ruleKey": None, "retrieved": 0},
        )
        return [record.id], rules

    written: list[str] = []
    for rule_key, citation in sorted(rules.citations.items()):
        limit_text = (
            f" Limit: {citation.value:g} {citation.unit}."
            if citation.value is not None
            else (f" Value: {citation.unit}." if citation.unit else "")
        )
        excerpt = " ".join(citation.text.split())
        if len(excerpt) > 260:
            excerpt = excerpt[:257] + "..."
        record = await write_evidence(
            context,
            case_id=case_id,
            agent=AGENT_NAME,
            evidence_type=EvidenceType.POLICY_EVIDENCE,
            finding=(
                f"{rule_key} retrieved from {citation.title}, page {citation.page}.{limit_text} "
                f"\u201c{excerpt}\u201d"
            ),
            confidence=1.0,
            severity=Severity.INFO,
            source_refs=[f"document:{citation.documentId}:p{citation.page}"],
            detail={
                "ruleKey": rule_key,
                "ruleValue": citation.value,
                "ruleUnit": citation.unit,
                "documentId": citation.documentId,
                "documentTitle": citation.title,
                "page": citation.page,
                "citation": citation.ref,
            },
        )
        written.append(record.id)

    missing = rules.missing
    if missing:
        record = await write_evidence(
            context,
            case_id=case_id,
            agent=AGENT_NAME,
            evidence_type=EvidenceType.POLICY_EVIDENCE,
            finding=(
                "Indexed documents do not state the following required limits: "
                f"{', '.join(missing)}. The case cannot be cleared against a missing rule."
            ),
            confidence=1.0,
            severity=Severity.HIGH,
            source_refs=["documents:incomplete"],
            detail={"ruleKey": None, "missing": missing},
        )
        written.append(record.id)

    return written, rules
