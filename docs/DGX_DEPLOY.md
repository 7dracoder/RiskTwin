# Runtime host (Dell Pro Max with GB10)

This is the only profile that may serve the scored demo. Author on the MacBook, transfer the tree, then integrate **on the Dell**. Laptop inference is not the submission path.

## 0. Transfer

Copy the repository onto the Dell (USB, `rsync` over the private LAN, etc.). Do not push secrets. `.env` is gitignored; use the committed profiles:

```bash
cp .env.dgx .env
```

## 1. MongoDB Community, replica set

Change Streams need a replica set. Either:

```bash
docker compose up -d
python scripts/bootstrap_mongo.py
```

or a host `mongod`:

```bash
mongod --replSet rs0 --dbpath /data/risktwin --bind_ip 127.0.0.1 --port 27017
mongosh --eval 'rs.initiate({_id: "rs0", members: [{_id: 0, host: "127.0.0.1:27017"}]})'
python scripts/bootstrap_mongo.py
```

Confirm `GET /api/health` later reports `changeFeed: mongodb-change-stream` and a replica set name.

## 2. Local model servers (loopback only)

Bind every server to `127.0.0.1`. Suggested ports match `.env.dgx`:

| Port | Modality | First-choice model |
| --- | --- | --- |
| 8001 | text | NVIDIA Nemotron 3.5 Lightning 30B A3B NVFP4 |
| 8002 | vision | NVIDIA Nemotron Nano 12B v2 VL NVFP4-QAD |
| 8003 | speech | NVIDIA Parakeet Unified English 0.6B |

Day-of order from the spec:

1. Smoke-test Parakeet on the radio clip.
2. Smoke-test Nano V2 VL 12B on four local frames; fall back to Nano VL 8B or Qwen inside 15–20 minutes.
3. Write both outputs as evidence.
4. Start Lightning 30B and confirm it reasons over **stored evidence**, not raw files.

Limit concurrent text generations to one or two. One primary text model; agent specialisation is not extra weights.

If a server fails to start, set the matching backend in `.env` to `deterministic` and **say degraded model mode**. Do not silently claim VLM/ASR quality.

## 3. Frameworks

Install OpenShell, OpenClaw and NemoClaw per NVIDIA’s local docs for the GB10 image you actually have. Then:

```
RISKTWIN_OPENSHELL_BACKEND=native
RISKTWIN_AGENT_RUNTIME=openclaw
RISKTWIN_LIFECYCLE=nemoclaw
```

If a package is missing, the code falls back to the shim and the dashboard reports `mode: shim`. Fix the install before judging; do not hide the gap.

## 4. Bring-up

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python scripts/smoke_test_local_inference.py   # must PASS with public egress denied
python scripts/bootstrap_mongo.py
python scripts/ingest_cleared_data.py
python -m pytest tests -q                     # sanity after transfer
python -m uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
```

Dashboard:

```bash
cd apps/dashboard && npm install && npm run build && npm start
```

`RISKTWIN_API_HOST=0.0.0.0` serves the Worker API on the private LAN. MongoDB and model ports stay on `127.0.0.1`.

## 5. Event LAN (Mode A)

Put the Dell, the controller laptop/tablet, and demo phones on the **same private LAN**. If venue Wi-Fi isolates clients, use an organizer-approved router.

Worker URL: `http://<DGX-LAN-IP>:3000/worker`

No model endpoint and no MongoDB port on that URL. Wi-Fi is transport only.

## 6. Local-first gate before the pitch

- `python scripts/smoke_test_local_inference.py` → PASS
- Disconnect or deny public egress
- Dashboard shows `degraded model mode` only if a modality really is deterministic
- Recovery: restart uvicorn; banner shows recovered from store

## 7. Record for the submission README

After the Dell smoke test, write down:

- Exact model ids and revisions that answered
- OpenClaw / NemoClaw / OpenShell versions
- MongoDB version and replica set name
- Checksums from `scripts/ingest_cleared_data.py --report …`

Those lines are what judges should see, not the configured-but-unused fallbacks.
