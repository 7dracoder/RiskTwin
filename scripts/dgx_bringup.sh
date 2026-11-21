#!/usr/bin/env bash
# ============================================================
# RiskTwin — DGX GB10 bring-up script
# Run this on the DGX after transfer:  bash scripts/dgx_bringup.sh
#
# What it does (in order):
#  1. MongoDB replica-set via Docker (or native mongod)
#  2. Text model server   — Lightning 30B BF16 via llama.cpp   :8001
#  3. Vision model server — Nemotron 12B VL via llama.cpp       :8002
#  4. ASR server          — Parakeet TDT 0.6B v2 (NeMo / sidecar) :8003
#  5. Python bootstrap + ingest
#  6. FastAPI + Next.js dashboard
# ============================================================
set -euo pipefail

REPO="$HOME/RiskTwin"
MODELS="$HOME/models"
LOGS="$REPO/data/state/logs"
mkdir -p "$LOGS"

cd "$REPO"
source .venv/bin/activate

echo "========================================"
echo " RiskTwin DGX GB10 bring-up"
echo " $(date)"
echo "========================================"

# ---- 0. Sanity -----------------------------------------------------------
if [[ ! -f ".env" ]]; then
  echo "[ERROR] .env not found. Run: cp .env.dgx .env"
  exit 1
fi
echo "[0] .env profile: $(grep RISKTWIN_HOST_PROFILE .env | cut -d= -f2)"

# ---- 1. MongoDB ----------------------------------------------------------
echo ""
echo "[1] Starting MongoDB replica-set..."
if docker info &>/dev/null; then
  if ! docker ps | grep -q risktwin-mongo; then
    docker compose up -d
    echo "    Waiting for MongoDB health..."
    for i in $(seq 1 24); do
      sleep 5
      if docker exec risktwin-mongo mongosh --quiet --eval "db.hello().ok" 2>/dev/null | grep -q 1; then
        break
      fi
      echo "    ... attempt $i/24"
    done
    # Initiate replica set
    docker exec risktwin-mongo mongosh --quiet --eval \
      "try { rs.status() } catch(e) { rs.initiate({_id:'rs0',members:[{_id:0,host:'127.0.0.1:27017'}]}) }" 2>/dev/null || true
    sleep 3
    echo "    MongoDB up: $(docker exec risktwin-mongo mongosh --quiet --eval 'rs.status().myState' 2>/dev/null || echo 'check manually')"
  else
    echo "    MongoDB already running."
  fi
else
  echo "    [WARN] Docker not available. Trying native mongod..."
  if command -v mongod &>/dev/null; then
    mkdir -p /tmp/risktwin-mongo
    mongod --replSet rs0 --dbpath /tmp/risktwin-mongo --bind_ip 127.0.0.1 --port 27017 --fork --logpath "$LOGS/mongod.log"
    sleep 3
    mongosh --quiet --eval "try{rs.status()}catch(e){rs.initiate({_id:'rs0',members:[{_id:0,host:'127.0.0.1:27017'}]})}" || true
  else
    echo "    [ERROR] Neither Docker nor mongod found. Install one of them."
    exit 1
  fi
fi

# ---- 2. llama.cpp server check -------------------------------------------
LLAMA_SERVER=""
for p in \
  "$HOME/llama.cpp/build/bin/llama-server" \
  "/usr/local/bin/llama-server" \
  "$(which llama-server 2>/dev/null)"; do
  if [[ -x "$p" ]]; then
    LLAMA_SERVER="$p"
    break
  fi
done

if [[ -z "$LLAMA_SERVER" ]]; then
  echo ""
  echo "[WARN] llama-server not found. Building llama.cpp with CUDA..."
  if [[ ! -d "$HOME/llama.cpp" ]]; then
    git clone --depth 1 https://github.com/ggerganov/llama.cpp "$HOME/llama.cpp"
  fi
  cmake -S "$HOME/llama.cpp" -B "$HOME/llama.cpp/build" -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release -DLLAMA_SERVER=ON
  cmake --build "$HOME/llama.cpp/build" --config Release -j$(nproc) --target llama-server
  LLAMA_SERVER="$HOME/llama.cpp/build/bin/llama-server"
fi
echo "[2] llama-server: $LLAMA_SERVER"

# ---- 3. Text model :8001 (Lightning 30B BF16) ----------------------------
echo ""
echo "[3] Starting text model server on :8001..."
TEXT_PID_FILE="$LOGS/text_server.pid"
if [[ -f "$TEXT_PID_FILE" ]] && kill -0 "$(cat "$TEXT_PID_FILE")" 2>/dev/null; then
  echo "    Text server already running (PID $(cat "$TEXT_PID_FILE"))."
else
  TEXT_MODEL_DIR="$MODELS/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16"
  if [[ -d "$TEXT_MODEL_DIR" ]]; then
    # Try vLLM first (handles safetensors natively)
    if command -v vllm &>/dev/null || python3 -c "import vllm" 2>/dev/null; then
      nohup python3 -m vllm.entrypoints.openai.api_server \
        --model "$TEXT_MODEL_DIR" \
        --host 127.0.0.1 --port 8001 \
        --served-model-name "nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16" \
        --max-model-len 8192 \
        --tensor-parallel-size 1 \
        > "$LOGS/text_server.log" 2>&1 &
      echo $! > "$TEXT_PID_FILE"
      echo "    Text (vLLM) started PID $(cat "$TEXT_PID_FILE") → $LOGS/text_server.log"
    else
      # Fallback: quantized GGUF via llama.cpp
      NANO_GGUF="$MODELS/NVIDIA-Nemotron3-Nano-4B-Q4_K_M.gguf"
      LLAMA_GGUF="$MODELS/Llama-3.1-Nemotron-70B-Instruct-HF-Q6_K-00001-of-00002.gguf"
      if [[ -f "$LLAMA_GGUF" ]]; then
        USE_GGUF="$LLAMA_GGUF"
        echo "    BF16 dir found but no vLLM. Falling back to Llama 70B Q6_K GGUF (fallback ladder)."
      elif [[ -f "$NANO_GGUF" ]]; then
        USE_GGUF="$NANO_GGUF"
        echo "    [DEGRADED] Using Nano 4B Q4_K_M — label DEGRADED in dashboard."
      else
        echo "    [ERROR] No usable text model found."
        exit 1
      fi
      nohup "$LLAMA_SERVER" \
        -m "$USE_GGUF" \
        --host 127.0.0.1 --port 8001 \
        --ctx-size 8192 --n-gpu-layers 999 \
        --alias "nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16" \
        > "$LOGS/text_server.log" 2>&1 &
      echo $! > "$TEXT_PID_FILE"
      echo "    Text (llama.cpp) started PID $(cat "$TEXT_PID_FILE") → $LOGS/text_server.log"
    fi
  else
    echo "    [WARN] $TEXT_MODEL_DIR not found. Using Llama 70B GGUF fallback."
    LLAMA_GGUF="$MODELS/Llama-3.1-Nemotron-70B-Instruct-HF-Q6_K-00001-of-00002.gguf"
    nohup "$LLAMA_SERVER" \
      -m "$LLAMA_GGUF" \
      --host 127.0.0.1 --port 8001 \
      --ctx-size 8192 --n-gpu-layers 999 \
      --alias "nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16" \
      > "$LOGS/text_server.log" 2>&1 &
    echo $! > "$TEXT_PID_FILE"
    echo "    Text (llama.cpp/70B) started PID $(cat "$TEXT_PID_FILE") → $LOGS/text_server.log"
  fi
fi

# ---- 4. Vision model :8002 (Nemotron 12B VL) -----------------------------
echo ""
echo "[4] Starting vision model server on :8002..."
VLM_PID_FILE="$LOGS/vlm_server.pid"
if [[ -f "$VLM_PID_FILE" ]] && kill -0 "$(cat "$VLM_PID_FILE")" 2>/dev/null; then
  echo "    Vision server already running (PID $(cat "$VLM_PID_FILE"))."
else
  # Nemotron 12B VL — try vLLM (best support for VL models)
  if command -v vllm &>/dev/null || python3 -c "import vllm" 2>/dev/null; then
    VLM_MODEL=""
    # Look for Nemotron 12B VL in various possible locations
    for candidate in \
      "$MODELS/NVIDIA-Nemotron-Nano-12B-v2-VL" \
      "$MODELS/Nemotron-Nano-12B-v2-VL" \
      "$MODELS/nvidia-nemotron-nano-12b-v2-vl"; do
      if [[ -d "$candidate" ]]; then
        VLM_MODEL="$candidate"
        break
      fi
    done

    if [[ -n "$VLM_MODEL" ]]; then
      nohup python3 -m vllm.entrypoints.openai.api_server \
        --model "$VLM_MODEL" \
        --host 127.0.0.1 --port 8002 \
        --served-model-name "nvidia/NVIDIA-Nemotron-Nano-12B-v2-VL" \
        --max-model-len 4096 \
        --tensor-parallel-size 1 \
        > "$LOGS/vlm_server.log" 2>&1 &
      echo $! > "$VLM_PID_FILE"
      echo "    Vision (vLLM / Nemotron 12B VL) started PID $(cat "$VLM_PID_FILE")"
    else
      # Fallback: VILA-HD-8B
      VILA_DIR="$MODELS/VILA-HD-8B-PS3-1.5K-SigLIP"
      if [[ -d "$VILA_DIR" ]]; then
        echo "    [WARN] Nemotron 12B VL not found. Falling back to VILA-HD-8B."
        nohup python3 -m vllm.entrypoints.openai.api_server \
          --model "$VILA_DIR" \
          --host 127.0.0.1 --port 8002 \
          --served-model-name "nvidia/NVIDIA-Nemotron-Nano-12B-v2-VL" \
          --max-model-len 4096 \
          > "$LOGS/vlm_server.log" 2>&1 &
        echo $! > "$VLM_PID_FILE"
        echo "    Vision (vLLM / VILA-HD fallback) started PID $(cat "$VLM_PID_FILE")"
      else
        echo "    [WARN] No VLM model found. Vision will use deterministic CV fallback."
        # Patch env to deterministic for vision
        sed -i 's/^RISKTWIN_VLM_BACKEND=.*/RISKTWIN_VLM_BACKEND=deterministic/' .env
      fi
    fi
  else
    echo "    [WARN] vLLM not available for VLM. Vision will use deterministic CV fallback."
    sed -i 's/^RISKTWIN_VLM_BACKEND=.*/RISKTWIN_VLM_BACKEND=deterministic/' .env
  fi
fi

# ---- 5. ASR server :8003 (Parakeet TDT 0.6B v2) -------------------------
echo ""
echo "[5] Starting ASR server on :8003..."
ASR_PID_FILE="$LOGS/asr_server.pid"
if [[ -f "$ASR_PID_FILE" ]] && kill -0 "$(cat "$ASR_PID_FILE")" 2>/dev/null; then
  echo "    ASR server already running (PID $(cat "$ASR_PID_FILE"))."
else
  # Parakeet served via NeMo ASR local server or transcript sidecar fallback
  PARAKEET_NEMO="$MODELS/parakeet-tdt-0.6b-v2.nemo"
  if [[ -f "$PARAKEET_NEMO" ]]; then
    # Check if nemo_asr_server or triton is available
    if python3 -c "import nemo.collections.asr as nemo_asr" 2>/dev/null; then
      cat > "$LOGS/parakeet_server.py" << 'PYEOF'
"""Minimal OpenAI-compatible /v1/audio/transcriptions endpoint wrapping NeMo Parakeet."""
import io, tempfile, os, uvicorn
from fastapi import FastAPI, File, UploadFile, Form
from fastapi.responses import JSONResponse
import nemo.collections.asr as nemo_asr

MODEL_PATH = os.environ.get("PARAKEET_MODEL", os.path.expanduser("~/models/parakeet-tdt-0.6b-v2.nemo"))
app = FastAPI()
_model = None

def get_model():
    global _model
    if _model is None:
        _model = nemo_asr.models.ASRModel.restore_from(MODEL_PATH)
        _model.eval()
    return _model

@app.post("/v1/audio/transcriptions")
async def transcribe(file: UploadFile = File(...), model: str = Form(default="parakeet-tdt-0.6b-v2")):
    audio_bytes = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    try:
        transcripts = get_model().transcribe([tmp_path])
        text = transcripts[0] if transcripts else ""
    finally:
        os.unlink(tmp_path)
    return JSONResponse({"text": text, "model": model})

@app.get("/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8003)
PYEOF
      PARAKEET_MODEL="$PARAKEET_NEMO" nohup python3 "$LOGS/parakeet_server.py" \
        > "$LOGS/asr_server.log" 2>&1 &
      echo $! > "$ASR_PID_FILE"
      echo "    ASR (NeMo Parakeet) started PID $(cat "$ASR_PID_FILE") → $LOGS/asr_server.log"
    else
      echo "    [WARN] NeMo not installed. ASR falls back to transcript sidecar."
      sed -i 's/^RISKTWIN_ASR_BACKEND=.*/RISKTWIN_ASR_BACKEND=deterministic/' .env
    fi
  else
    echo "    [WARN] $PARAKEET_NEMO not found. ASR falls back to transcript sidecar."
    sed -i 's/^RISKTWIN_ASR_BACKEND=.*/RISKTWIN_ASR_BACKEND=deterministic/' .env
  fi
fi

# ---- 6. Wait for model servers -------------------------------------------
echo ""
echo "[6] Waiting 30 s for model servers to initialise..."
sleep 30

# Poll :8001 text
for i in $(seq 1 10); do
  if curl -sf http://127.0.0.1:8001/health > /dev/null 2>&1 || \
     curl -sf http://127.0.0.1:8001/v1/models > /dev/null 2>&1; then
    echo "    :8001 text model READY"
    break
  fi
  echo "    Waiting for :8001 ... ($i/10)"
  sleep 10
done

# ---- 7. Bootstrap MongoDB -----------------------------------------------
echo ""
echo "[7] Bootstrapping MongoDB..."
python scripts/bootstrap_mongo.py && echo "    bootstrap OK"

# ---- 8. Ingest cleared data ---------------------------------------------
echo ""
echo "[8] Ingesting cleared data..."
python scripts/ingest_cleared_data.py && echo "    ingest OK"

# ---- 9. Smoke test -------------------------------------------------------
echo ""
echo "[9] Running smoke test (static checks only)..."
python scripts/smoke_test_local_inference.py --skip-requests && echo "    smoke OK"

# ---- 10. FastAPI ---------------------------------------------------------
echo ""
echo "[10] Starting FastAPI on :8000..."
API_PID_FILE="$LOGS/api_server.pid"
nohup python -m uvicorn apps.api.main:app \
  --host 0.0.0.0 --port 8000 --reload \
  > "$LOGS/api_server.log" 2>&1 &
echo $! > "$API_PID_FILE"
echo "    FastAPI PID $(cat "$API_PID_FILE") → $LOGS/api_server.log"

# ---- 11. Dashboard -------------------------------------------------------
echo ""
echo "[11] Building and starting Next.js dashboard..."
DASH_PID_FILE="$LOGS/dashboard.pid"
cd apps/dashboard
npm install --silent 2>&1 | tail -3
npm run build 2>&1 | tail -5
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 nohup npm start \
  -- --port 3000 \
  > "$LOGS/dashboard.log" 2>&1 &
echo $! > "$DASH_PID_FILE"
cd "$REPO"
echo "    Dashboard PID $(cat "$DASH_PID_FILE") → $LOGS/dashboard.log"

# ---- Done ----------------------------------------------------------------
echo ""
echo "========================================"
echo " RiskTwin services started"
echo "========================================"
LAN_IP=$(hostname -I | awk '{print $1}')
echo "  Controller dashboard : http://${LAN_IP}:3000"
echo "  Worker page          : http://${LAN_IP}:3000/worker"
echo "  API docs             : http://127.0.0.1:8000/docs"
echo "  API health           : http://127.0.0.1:8000/api/health"
echo ""
echo "  Text model log  : $LOGS/text_server.log"
echo "  Vision log      : $LOGS/vlm_server.log"
echo "  ASR log         : $LOGS/asr_server.log"
echo "  API log         : $LOGS/api_server.log"
echo "  Dashboard log   : $LOGS/dashboard.log"
echo ""
echo "  Run tests:  .venv/bin/python -m pytest tests -q"
echo "  Full smoke: .venv/bin/python scripts/smoke_test_local_inference.py"
echo "========================================"
