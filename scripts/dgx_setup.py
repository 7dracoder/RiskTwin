#!/usr/bin/env python3
"""Bootstrap script: initialise MongoDB replica set, then run RiskTwin bootstrap."""
import time
import subprocess
import sys

# --- Step 1: RS init ----------------------------------------------------------
import pymongo

print("=== Step 1: MongoDB Replica Set Init ===")
client = pymongo.MongoClient(
    "mongodb://127.0.0.1:27017/?directConnection=true",
    serverSelectionTimeoutMS=10000,
)
try:
    status = client.admin.command("replSetGetStatus")
    print(f"  Replica set already initialised — state: {status.get('myState')}")
except Exception as e:
    print(f"  Not yet initialised ({e}). Initiating...")
    try:
        result = client.admin.command({
            "replSetInitiate": {
                "_id": "rs0",
                "members": [{"_id": 0, "host": "127.0.0.1:27017"}]
            }
        })
        print(f"  rs.initiate: {result.get('ok')}")
    except Exception as e2:
        print(f"  initiate error (may already be done): {e2}")
    time.sleep(5)
    try:
        status = client.admin.command("replSetGetStatus")
        print(f"  RS state: {status.get('myState')}")
    except Exception as e3:
        print(f"  Could not get status: {e3}")
        sys.exit(1)

# Wait until primary
for _ in range(20):
    try:
        hello = client.admin.command("hello")
        if hello.get("isWritablePrimary") or hello.get("ismaster"):
            print("  Primary is up — RS ready.")
            break
    except Exception:
        pass
    print("  Waiting for primary...")
    time.sleep(2)
else:
    print("  [WARN] Primary not confirmed. Proceeding anyway.")

client.close()
print()

# --- Step 2: Run bootstrap_mongo.py ------------------------------------------
print("=== Step 2: bootstrap_mongo.py ===")
r = subprocess.run([sys.executable, "scripts/bootstrap_mongo.py"])
if r.returncode != 0:
    print("  [ERROR] bootstrap_mongo.py failed")
    sys.exit(r.returncode)
print("  bootstrap OK")
print()

# --- Step 3: Run ingest_cleared_data.py --------------------------------------
print("=== Step 3: ingest_cleared_data.py ===")
r = subprocess.run([sys.executable, "scripts/ingest_cleared_data.py"])
if r.returncode != 0:
    print("  [ERROR] ingest_cleared_data.py failed")
    sys.exit(r.returncode)
print("  ingest OK")
print()

# --- Step 4: Smoke test (static only) ----------------------------------------
print("=== Step 4: smoke_test (static checks) ===")
r = subprocess.run([sys.executable, "scripts/smoke_test_local_inference.py", "--skip-requests"])
print(f"  smoke result: exit {r.returncode}")
print()

# --- Step 5: Run pytest -------------------------------------------------------
print("=== Step 5: pytest ===")
r = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q", "--tb=short"])
print(f"  pytest exit: {r.returncode}")
