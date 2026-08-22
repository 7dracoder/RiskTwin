"""Storage abstraction shared by both backends.

The agent loop is driven by a change feed, not by polling. On the DGX that feed is
a real MongoDB Change Stream; on a machine without MongoDB it is a local
append-only journal with the same semantics, so no application code changes when
the project is transferred.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol, runtime_checkable

# Collection names (spec section 7.2).
CASES = "cases"
SITE_EVENTS = "site_events"
EVIDENCE = "evidence"
SITE_MODEL = "site_model"
DOCUMENTS = "documents"
TELEMETRY_RECORDINGS = "telemetry_recordings"
REPLAY_STATE = "replay_state"
TELEMETRY = "telemetry"
WORKER_POSITIONS = "worker_positions"
SOURCE_MANIFEST = "source_manifest"
NOTIFICATIONS = "notifications"
ACTIONS = "actions"
AGENT_RUNS = "agent_runs"
POLICY_LOG = "policy_log"
REDACTION_MANIFEST = "redaction_manifest"

ALL_COLLECTIONS = [
    CASES,
    SITE_EVENTS,
    EVIDENCE,
    SITE_MODEL,
    DOCUMENTS,
    TELEMETRY_RECORDINGS,
    REPLAY_STATE,
    TELEMETRY,
    WORKER_POSITIONS,
    SOURCE_MANIFEST,
    NOTIFICATIONS,
    ACTIONS,
    AGENT_RUNS,
    POLICY_LOG,
    REDACTION_MANIFEST,
]

# Index definitions (spec section 7.3).
INDEX_SPECS: dict[str, list[list[tuple[str, int]]]] = {
    SITE_EVENTS: [[("caseId", 1), ("timestamp", 1)]],
    EVIDENCE: [[("caseId", 1), ("severity", -1), ("timestamp", 1)]],
    TELEMETRY_RECORDINGS: [[("recordingId", 1), ("checksum", 1)]],
    REPLAY_STATE: [[("caseId", 1), ("status", 1)]],
    TELEMETRY: [[("caseId", 1), ("kind", 1), ("timestamp", -1)]],
    WORKER_POSITIONS: [[("caseId", 1), ("workerAlias", 1), ("timestamp", -1)]],
    SOURCE_MANIFEST: [[("sourceId", 1), ("status", 1), ("retrievedAt", -1)]],
    NOTIFICATIONS: [[("workerAlias", 1), ("status", 1), ("sentAt", -1)]],
    DOCUMENTS: [[("ruleKey", 1), ("tags", 1)]],
    ACTIONS: [[("caseId", 1), ("status", 1)]],
    AGENT_RUNS: [[("caseId", 1), ("agent", 1), ("startedAt", -1)]],
    SITE_MODEL: [[("siteModelId", 1), ("version", -1)]],
    POLICY_LOG: [[("caseId", 1), ("timestamp", -1)]],
}


@dataclass(slots=True)
class ChangeEvent:
    """One change-feed notification."""

    collection: str
    operation: str
    document: dict[str, Any] = field(default_factory=dict)


def _compare(value: Any, condition: Any) -> bool:
    if isinstance(condition, dict):
        for operator, operand in condition.items():
            if operator == "$in":
                if value not in operand:
                    return False
            elif operator == "$nin":
                if value in operand:
                    return False
            elif operator == "$ne":
                if value == operand:
                    return False
            elif operator == "$gte":
                if value is None or value < operand:
                    return False
            elif operator == "$lte":
                if value is None or value > operand:
                    return False
            elif operator == "$gt":
                if value is None or value <= operand:
                    return False
            elif operator == "$lt":
                if value is None or value >= operand:
                    return False
            elif operator == "$exists":
                if (value is not None) != bool(operand):
                    return False
            else:
                raise ValueError(f"unsupported query operator {operator!r}")
        return True
    return value == condition


def matches(document: dict[str, Any], query: dict[str, Any] | None) -> bool:
    """Minimal MongoDB-style matcher: equality plus the handful of operators the
    RiskTwin queries actually use."""
    if not query:
        return True
    for key, condition in query.items():
        if not _compare(document.get(key), condition):
            return False
    return True


def sort_documents(
    documents: list[dict[str, Any]], sort: list[tuple[str, int]] | None
) -> list[dict[str, Any]]:
    if not sort:
        return documents
    result = list(documents)
    for key, direction in reversed(sort):
        result.sort(
            key=lambda doc, k=key: (doc.get(k) is None, _sort_key(doc.get(k))),
            reverse=direction < 0,
        )
    return result


def _sort_key(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str)):
        return value
    return str(value)


def apply_updates(document: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    """Support the `$set` / `$push` subset used by the agents."""
    result = dict(document)
    if not any(key.startswith("$") for key in updates):
        result.update(updates)
        return result
    for operator, payload in updates.items():
        if operator == "$set":
            result.update(payload)
        elif operator == "$push":
            for key, value in payload.items():
                existing = list(result.get(key) or [])
                existing.append(value)
                result[key] = existing
        elif operator == "$addToSet":
            for key, value in payload.items():
                existing = list(result.get(key) or [])
                if value not in existing:
                    existing.append(value)
                result[key] = existing
        else:
            raise ValueError(f"unsupported update operator {operator!r}")
    return result


@runtime_checkable
class Store(Protocol):
    """The storage surface every RiskTwin component uses."""

    backend: str

    async def connect(self) -> None: ...

    async def close(self) -> None: ...

    async def ensure_indexes(self) -> list[str]: ...

    async def insert_one(self, collection: str, document: dict[str, Any]) -> dict[str, Any]: ...

    async def find_one(
        self, collection: str, query: dict[str, Any] | None = None
    ) -> dict[str, Any] | None: ...

    async def find(
        self,
        collection: str,
        query: dict[str, Any] | None = None,
        sort: list[tuple[str, int]] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]: ...

    async def update_one(
        self, collection: str, query: dict[str, Any], updates: dict[str, Any]
    ) -> dict[str, Any] | None: ...

    async def upsert(
        self, collection: str, query: dict[str, Any], document: dict[str, Any]
    ) -> dict[str, Any]: ...

    async def count(self, collection: str, query: dict[str, Any] | None = None) -> int: ...

    async def delete_many(self, collection: str, query: dict[str, Any] | None = None) -> int: ...

    def watch(self, collections: list[str] | None = None) -> AsyncIterator[ChangeEvent]: ...

    async def health(self) -> dict[str, Any]: ...
