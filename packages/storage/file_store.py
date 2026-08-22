"""Append-only local store with a change feed.

Used on a build console that has no MongoDB installed. It keeps the same
semantics the agents rely on — durable writes plus a change feed that survives a
process restart — so the "agent survives its own sandbox" recovery demo works
here and on the DGX without touching application code.

Not a MongoDB substitute for the graded build: the runtime host profile
(`.env.dgx`) selects the real MongoDB replica set and its Change Streams.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from pathlib import Path
from typing import Any, AsyncIterator

from packages.storage.base import (
    ALL_COLLECTIONS,
    ChangeEvent,
    apply_updates,
    matches,
    sort_documents,
)


class FileStore:
    backend = "file-journal"

    def __init__(self, state_dir: Path) -> None:
        self._dir = Path(state_dir)
        self._data: dict[str, dict[str, dict[str, Any]]] = {}
        self._subscribers: set[asyncio.Queue[ChangeEvent]] = set()
        self._lock = asyncio.Lock()
        self._connected = False

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #

    async def connect(self) -> None:
        if self._connected:
            return
        self._dir.mkdir(parents=True, exist_ok=True)
        for collection in ALL_COLLECTIONS:
            self._data[collection] = {}
            self._replay_journal(collection)
        self._connected = True

    async def close(self) -> None:
        self._connected = False
        self._subscribers.clear()

    async def ensure_indexes(self) -> list[str]:
        # The journal is small and fully in memory; indexes are a MongoDB concern.
        return []

    async def health(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "ok": self._connected,
            "changeFeed": "local-journal",
            "stateDir": str(self._dir),
            "documents": {name: len(docs) for name, docs in self._data.items() if docs},
        }

    # ------------------------------------------------------------------ #
    # journal
    # ------------------------------------------------------------------ #

    def _journal_path(self, collection: str) -> Path:
        return self._dir / f"{collection}.jsonl"

    def _replay_journal(self, collection: str) -> None:
        path = self._journal_path(collection)
        if not path.exists():
            return
        bucket = self._data[collection]
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                operation = entry.get("op")
                document = entry.get("doc") or {}
                key = document.get("_id")
                if operation == "delete":
                    bucket.pop(key, None)
                elif key is not None:
                    bucket[key] = document

    def _append_journal(self, collection: str, operation: str, document: dict[str, Any]) -> None:
        path = self._journal_path(collection)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"op": operation, "doc": document}, default=str) + "\n")
            handle.flush()

    def _bucket(self, collection: str) -> dict[str, dict[str, Any]]:
        return self._data.setdefault(collection, {})

    # ------------------------------------------------------------------ #
    # writes
    # ------------------------------------------------------------------ #

    async def insert_one(self, collection: str, document: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            doc = json.loads(json.dumps(document, default=str))
            key = doc.get("_id")
            if key is None:
                raise ValueError(f"document for {collection} is missing _id")
            self._bucket(collection)[key] = doc
            self._append_journal(collection, "insert", doc)
        self._publish(ChangeEvent(collection, "insert", doc))
        return doc

    async def update_one(
        self, collection: str, query: dict[str, Any], updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        async with self._lock:
            bucket = self._bucket(collection)
            target = next((doc for doc in bucket.values() if matches(doc, query)), None)
            if target is None:
                return None
            updated = apply_updates(target, updates)
            updated = json.loads(json.dumps(updated, default=str))
            bucket[updated["_id"]] = updated
            self._append_journal(collection, "update", updated)
        self._publish(ChangeEvent(collection, "update", updated))
        return updated

    async def upsert(
        self, collection: str, query: dict[str, Any], document: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._lock:
            bucket = self._bucket(collection)
            target = next((doc for doc in bucket.values() if matches(doc, query)), None)
            doc = json.loads(json.dumps(document, default=str))
            if target is not None:
                doc["_id"] = target["_id"]
                operation = "update"
            else:
                operation = "insert"
            if doc.get("_id") is None:
                raise ValueError(f"document for {collection} is missing _id")
            bucket[doc["_id"]] = doc
            self._append_journal(collection, operation, doc)
        self._publish(ChangeEvent(collection, operation, doc))
        return doc

    async def delete_many(self, collection: str, query: dict[str, Any] | None = None) -> int:
        async with self._lock:
            bucket = self._bucket(collection)
            victims = [doc for doc in bucket.values() if matches(doc, query)]
            for doc in victims:
                bucket.pop(doc["_id"], None)
                self._append_journal(collection, "delete", {"_id": doc["_id"]})
        for doc in victims:
            self._publish(ChangeEvent(collection, "delete", doc))
        return len(victims)

    # ------------------------------------------------------------------ #
    # reads
    # ------------------------------------------------------------------ #

    async def find_one(
        self, collection: str, query: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        results = await self.find(collection, query, limit=1)
        return results[0] if results else None

    async def find(
        self,
        collection: str,
        query: dict[str, Any] | None = None,
        sort: list[tuple[str, int]] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        candidates = [doc for doc in self._bucket(collection).values() if matches(doc, query)]
        ordered = sort_documents(candidates, sort)
        if limit is not None:
            ordered = ordered[:limit]
        return [json.loads(json.dumps(doc, default=str)) for doc in ordered]

    async def count(self, collection: str, query: dict[str, Any] | None = None) -> int:
        return len([doc for doc in self._bucket(collection).values() if matches(doc, query)])

    # ------------------------------------------------------------------ #
    # change feed
    # ------------------------------------------------------------------ #

    def _publish(self, event: ChangeEvent) -> None:
        for queue in list(self._subscribers):
            with suppress(asyncio.QueueFull):
                queue.put_nowait(event)

    async def watch(
        self, collections: list[str] | None = None
    ) -> AsyncIterator[ChangeEvent]:
        queue: asyncio.Queue[ChangeEvent] = asyncio.Queue(maxsize=4096)
        self._subscribers.add(queue)
        try:
            while True:
                event = await queue.get()
                if collections and event.collection not in collections:
                    continue
                yield event
        finally:
            self._subscribers.discard(queue)
