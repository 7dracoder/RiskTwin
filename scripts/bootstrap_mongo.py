#!/usr/bin/env python3
"""Prepare the durable store: replica set, collections and indexes.

MongoDB Change Streams require a replica set, so the runtime host runs MongoDB
Community as a single-node replica set (spec section 7.1). This script initiates
that replica set when it is not configured yet, then creates every collection and
index the agents query.

On the build console (`RISKTWIN_STORAGE_BACKEND=file`) there is no MongoDB to
configure. The script then prints the exact commands to run on the DGX and
prepares the local journal instead, so the same command works in both profiles.
"""

from __future__ import annotations

import argparse
import asyncio

from _common import banner, configure_logging, field  # noqa: I001 - fixes sys.path

from packages.config import Settings, get_settings
from packages.storage import build_store
from packages.storage.base import ALL_COLLECTIONS, INDEX_SPECS

REPLICA_SET_HINT = """\
Run these on the runtime host once, before starting the API:

  mongod --replSet rs0 --dbpath /data/risktwin --bind_ip 127.0.0.1 --port 27017
  mongosh --eval 'rs.initiate({_id: "rs0", members: [{_id: 0, host: "127.0.0.1:27017"}]})'

Then: cp .env.dgx .env && python scripts/bootstrap_mongo.py
"""


async def initiate_replica_set(settings: Settings) -> str:
    """Initiate the single-node replica set if the server has none."""
    from pymongo import AsyncMongoClient
    from pymongo.errors import OperationFailure, PyMongoError

    client = AsyncMongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)
    try:
        hello = await client.admin.command("hello")
        if hello.get("setName"):
            return f"already a replica set member of {hello['setName']!r}"
        try:
            await client.admin.command(
                "replSetInitiate",
                {
                    "_id": "rs0",
                    "members": [{"_id": 0, "host": "127.0.0.1:27017"}],
                },
            )
        except OperationFailure as exc:
            return f"replSetInitiate refused: {exc}"
        for _ in range(30):
            await asyncio.sleep(1)
            hello = await client.admin.command("hello")
            if hello.get("setName") and hello.get("isWritablePrimary"):
                return "initiated replica set rs0 and elected primary"
        return "initiated rs0 but no primary was elected within 30s"
    except PyMongoError as exc:
        return f"cannot reach {settings.mongodb_uri}: {exc}"
    finally:
        await client.close()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-replica-set",
        action="store_true",
        help="only create collections and indexes",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)

    settings = get_settings()
    banner("RiskTwin store bootstrap")
    field("host profile", settings.host_profile)
    field("storage backend", settings.storage_backend)

    if settings.storage_backend == "mongodb":
        field("mongodb uri", settings.mongodb_uri)
        field("database", settings.mongodb_db)
        if not args.skip_replica_set:
            field("replica set", await initiate_replica_set(settings))
    else:
        field("state dir", settings.path(settings.state_dir))
        print("\n  No MongoDB in this profile. Change Streams are emulated by the")
        print("  append-only local journal; the MongoDB code path is unchanged.")
        print()
        print(REPLICA_SET_HINT)

    store = build_store(settings)
    await store.connect()
    created = await store.ensure_indexes()
    health = await store.health()
    await store.close()

    banner("Result")
    field("collections declared", len(ALL_COLLECTIONS))
    field("index specs declared", sum(len(specs) for specs in INDEX_SPECS.values()))
    field("indexes created", len(created))
    field("change feed", health.get("changeFeed"))
    field("ok", health.get("ok"))
    for name in created:
        print(f"    index {name}")
    return 0 if health.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
