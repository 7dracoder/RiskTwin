"""MongoDB-backed store using real Change Streams.

This is the graded path (spec section 7): MongoDB Community running as a local
single-node replica set on the runtime host. Change Streams require the replica
set, which `scripts/bootstrap_mongo.sh` configures.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError

from packages.storage.base import (
    ALL_COLLECTIONS,
    INDEX_SPECS,
    ChangeEvent,
)


class MongoStore:
    backend = "mongodb-change-streams"

    def __init__(self, uri: str, database: str) -> None:
        self._uri = uri
        self._database_name = database
        self._client: AsyncMongoClient | None = None

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #

    async def connect(self) -> None:
        if self._client is not None:
            return
        self._client = AsyncMongoClient(self._uri, serverSelectionTimeoutMS=5000, tz_aware=False)
        await self._client.admin.command("ping")

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    @property
    def _db(self):
        if self._client is None:
            raise RuntimeError("MongoStore.connect() was not awaited")
        return self._client[self._database_name]

    async def ensure_indexes(self) -> list[str]:
        created: list[str] = []
        existing = set(await self._db.list_collection_names())
        for collection in ALL_COLLECTIONS:
            if collection not in existing:
                await self._db.create_collection(collection)
        for collection, specs in INDEX_SPECS.items():
            for spec in specs:
                name = await self._db[collection].create_index(spec)
                created.append(f"{collection}.{name}")
        return created

    async def health(self) -> dict[str, Any]:
        try:
            status = await self._client.admin.command("hello")  # type: ignore[union-attr]
            replica_set = status.get("setName")
            return {
                "backend": self.backend,
                "ok": True,
                "changeFeed": "mongodb-change-stream" if replica_set else "UNAVAILABLE",
                "replicaSet": replica_set,
                "database": self._database_name,
            }
        except PyMongoError as exc:
            return {"backend": self.backend, "ok": False, "error": str(exc)}

    # ------------------------------------------------------------------ #
    # writes
    # ------------------------------------------------------------------ #

    async def insert_one(self, collection: str, document: dict[str, Any]) -> dict[str, Any]:
        await self._db[collection].insert_one(dict(document))
        return document

    async def update_one(
        self, collection: str, query: dict[str, Any], updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        payload = updates if any(k.startswith("$") for k in updates) else {"$set": updates}
        return await self._db[collection].find_one_and_update(
            query, payload, return_document=True
        )

    async def upsert(
        self, collection: str, query: dict[str, Any], document: dict[str, Any]
    ) -> dict[str, Any]:
        payload = {k: v for k, v in document.items() if k != "_id"}
        result = await self._db[collection].find_one_and_update(
            query,
            {"$set": payload, "$setOnInsert": {"_id": document["_id"]}},
            upsert=True,
            return_document=True,
        )
        return result or document

    async def delete_many(self, collection: str, query: dict[str, Any] | None = None) -> int:
        result = await self._db[collection].delete_many(query or {})
        return result.deleted_count

    # ------------------------------------------------------------------ #
    # reads
    # ------------------------------------------------------------------ #

    async def find_one(
        self, collection: str, query: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        return await self._db[collection].find_one(query or {})

    async def find(
        self,
        collection: str,
        query: dict[str, Any] | None = None,
        sort: list[tuple[str, int]] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        cursor = self._db[collection].find(query or {})
        if sort:
            cursor = cursor.sort(sort)
        if limit is not None:
            cursor = cursor.limit(limit)
        return [doc async for doc in cursor]

    async def count(self, collection: str, query: dict[str, Any] | None = None) -> int:
        return await self._db[collection].count_documents(query or {})

    # ------------------------------------------------------------------ #
    # change feed
    # ------------------------------------------------------------------ #

    async def watch(
        self, collections: list[str] | None = None
    ) -> AsyncIterator[ChangeEvent]:
        pipeline: list[dict[str, Any]] = []
        if collections:
            pipeline.append({"$match": {"ns.coll": {"$in": collections}}})
        async with self._db.watch(pipeline, full_document="updateLookup") as stream:
            async for change in stream:
                yield ChangeEvent(
                    collection=change.get("ns", {}).get("coll", ""),
                    operation=change.get("operationType", ""),
                    document=change.get("fullDocument") or {},
                )
