"""Durable case state and the change feed that drives the agent loop."""

from packages.config import Settings, get_settings
from packages.storage.base import (
    ACTIONS,
    AGENT_RUNS,
    ALL_COLLECTIONS,
    CASES,
    DOCUMENTS,
    EVIDENCE,
    INDEX_SPECS,
    NOTIFICATIONS,
    POLICY_LOG,
    REDACTION_MANIFEST,
    REPLAY_STATE,
    SITE_EVENTS,
    SITE_MODEL,
    SOURCE_MANIFEST,
    TELEMETRY,
    TELEMETRY_RECORDINGS,
    WORKER_POSITIONS,
    ChangeEvent,
    Store,
)
from packages.storage.file_store import FileStore
from packages.storage.mongo_store import MongoStore

__all__ = [
    "ACTIONS",
    "AGENT_RUNS",
    "ALL_COLLECTIONS",
    "CASES",
    "DOCUMENTS",
    "EVIDENCE",
    "INDEX_SPECS",
    "NOTIFICATIONS",
    "POLICY_LOG",
    "REDACTION_MANIFEST",
    "REPLAY_STATE",
    "SITE_EVENTS",
    "SITE_MODEL",
    "SOURCE_MANIFEST",
    "TELEMETRY",
    "TELEMETRY_RECORDINGS",
    "WORKER_POSITIONS",
    "ChangeEvent",
    "FileStore",
    "MongoStore",
    "Store",
    "build_store",
    "open_store",
]


def build_store(settings: Settings | None = None) -> Store:
    settings = settings or get_settings()
    if settings.storage_backend == "mongodb":
        return MongoStore(settings.mongodb_uri, settings.mongodb_db)
    return FileStore(settings.path(settings.state_dir))


async def open_store(settings: Settings | None = None) -> Store:
    store = build_store(settings)
    await store.connect()
    return store
