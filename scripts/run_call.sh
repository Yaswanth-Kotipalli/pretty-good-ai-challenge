#!/usr/bin/env bash
set -euo pipefail

# scripts/run_call.sh - Run a single test call without terminal juggling.
# Uses a permanent ngrok static domain.
# Sequence (load-bearing):
#   1. Read PORT (default 5000) and PUBLIC_BASE_URL from .env.
#   2. Poll until $PORT is free (up to 10s).
#   3. Start Flask on $PORT -> wait for http://127.0.0.1:$PORT/health (up to 30s).
#   4. Start ngrok http --url=<host> $PORT -> logs/tunnel.log.
#   5. Verify $PUBLIC_BASE_URL/health through tunnel (up to 60s).
#   6. Start LiveKit worker -> wait for registration.
#   7. Execute call runner.
#   8. Clean up all background processes on exit (EXIT/INT/TERM trap).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

mkdir -p logs recordings transcripts

PYTHON="${PROJECT_ROOT}/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="python3"
fi

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <scenario_id> [--test-number +1...]" >&2
  echo "Example: $0 book_physical --test-number +17288809412" >&2
  exit 1
fi

# Clear mock entries from recordings/pending.jsonl if present (e.g. CA1/RS1 fixtures)
if [[ -f "recordings/pending.jsonl" ]]; then
  if grep -qE '(CA1|RS1)' recordings/pending.jsonl 2>/dev/null; then
    echo "[run_call] Clearing mock CA1/RS1 fixture entries from recordings/pending.jsonl..."
    grep -vE '(CA1|RS1)' recordings/pending.jsonl > recordings/pending.jsonl.tmp || true
    mv recordings/pending.jsonl.tmp recordings/pending.jsonl
  fi
fi

# 1. Read PORT and PUBLIC_BASE_URL from .env (never write to .env)
if [[ ! -f .env ]]; then
  echo "[run_call] ERROR: .env file not found. Copy .env.example to .env and configure credentials." >&2
  exit 1
fi

PORT="5000"
ENV_PORT=$(grep -E '^PORT=' .env 2>/dev/null | cut -d '=' -f2- | tr -d ' "'\''' | tr -d '\r' || true)
if [[ -n "$ENV_PORT" ]]; then
  PORT="$ENV_PORT"
fi

PUBLIC_BASE_URL=$(grep -E '^PUBLIC_BASE_URL=' .env 2>/dev/null | cut -d '=' -f2- | tr -d ' "'\''' | tr -d '\r' || true)
if [[ -z "$PUBLIC_BASE_URL" ]]; then
  echo "[run_call] ERROR: PUBLIC_BASE_URL is not set in .env." >&2
  echo "Claim a free permanent static domain at https://dashboard.ngrok.com -> Domains" >&2
  echo "and set PUBLIC_BASE_URL=https://your-name.ngrok-free.app in .env" >&2
  exit 1
fi

# Normalize URL and extract host
if [[ "$PUBLIC_BASE_URL" != http* ]]; then
  PUBLIC_BASE_URL="https://${PUBLIC_BASE_URL}"
fi
PUBLIC_BASE_URL="${PUBLIC_BASE_URL%/}"
NGROK_DOMAIN=$(echo "$PUBLIC_BASE_URL" | sed -e 's|^https://||' -e 's|^http://||' -e 's|/.*$||')

TUNNEL_PID=""
SERVER_PID=""
WORKER_PID=""

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM
  echo ""
  echo "[run_call] Shutting down background processes..."
  if [[ -n "${WORKER_PID:-}" ]] && kill -0 "$WORKER_PID" 2>/dev/null; then
    echo "[run_call] Stopping worker (PID $WORKER_PID)..."
    kill "$WORKER_PID" 2>/dev/null || true
  fi
  if [[ -n "${TUNNEL_PID:-}" ]] && kill -0 "$TUNNEL_PID" 2>/dev/null; then
    echo "[run_call] Stopping ngrok tunnel (PID $TUNNEL_PID)..."
    kill "$TUNNEL_PID" 2>/dev/null || true
  fi
  if [[ -n "${SERVER_PID:-}" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "[run_call] Stopping server (PID $SERVER_PID)..."
    kill "$SERVER_PID" 2>/dev/null || true
  fi
  wait 2>/dev/null || true
  exit "$exit_code"
}
trap cleanup EXIT INT TERM

# 2. Poll until $PORT is actually free (up to 10s)
echo "[run_call] Checking if port $PORT is free..."
PORT_FREE=0
for ((i=1; i<=10; i++)); do
  if ! lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    PORT_FREE=1
    break
  fi
  sleep 1
done

if [[ $PORT_FREE -ne 1 ]]; then
  echo "[run_call] ERROR: Port $PORT is already in use by another process after waiting 10s." >&2
  echo "Current process holding port $PORT:" >&2
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >&2 || true
  echo "Stop the process above (or set PORT=5050 in .env if on macOS AirPlay) and retry." >&2
  exit 1
fi

# 3. Start Flask on $PORT -> logs/server.log; wait for http://127.0.0.1:$PORT/health (up to 30s)
echo "[run_call] Starting Flask server on port $PORT..."
rm -f logs/server.log
PORT="$PORT" "$PYTHON" -m pgai_challenge.server > logs/server.log 2>&1 &
SERVER_PID=$!

echo "[run_call] Waiting for Flask server on http://127.0.0.1:$PORT/health (up to 30s)..."
SERVER_OK=0
for ((i=1; i<=30; i++)); do
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "[run_call] ERROR: Flask server died. See logs/server.log:" >&2
    tail -n 20 logs/server.log >&2
    exit 1
  fi
  if curl -sf --connect-timeout 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    SERVER_OK=1
    break
  fi
  sleep 1
done

if [[ $SERVER_OK -ne 1 ]]; then
  echo "[run_call] ERROR: Flask server never became healthy on http://127.0.0.1:$PORT/health after 30s." >&2
  echo "--- logs/server.log (last 20 lines) ---" >&2
  tail -n 20 logs/server.log >&2 || true
  exit 1
fi
echo "[run_call] Flask server listening on 127.0.0.1:$PORT."

# 4. Start ngrok tunnel for static domain
echo "[run_call] Starting ngrok tunnel for domain $NGROK_DOMAIN on port $PORT..."
rm -f logs/tunnel.log

if ! command -v ngrok >/dev/null 2>&1; then
  echo "[run_call] ERROR: ngrok binary not found in PATH." >&2
  echo "Please install ngrok (e.g. 'brew install ngrok/ngrok/ngrok' on macOS)" >&2
  echo "and configure your authtoken with 'ngrok config add-authtoken <token>'." >&2
  exit 1
fi

ngrok http --url="$NGROK_DOMAIN" "$PORT" > logs/tunnel.log 2>&1 &
TUNNEL_PID=$!

# 5. Health-check $PUBLIC_BASE_URL/health for up to 60s
echo "[run_call] Verifying tunnel health via $PUBLIC_BASE_URL/health (up to 60s)..."
TUNNEL_OK=0
for ((i=1; i<=60; i++)); do
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "[run_call] ERROR: Flask server died while waiting for tunnel. See logs/server.log:" >&2
    tail -n 20 logs/server.log >&2
    exit 1
  fi
  if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
    echo "[run_call] ERROR: ngrok tunnel died unexpectedly. See logs/tunnel.log:" >&2
    tail -n 20 logs/tunnel.log >&2
    exit 1
  fi
  if curl -sf --connect-timeout 3 "$PUBLIC_BASE_URL/health" >/dev/null 2>&1; then
    TUNNEL_OK=1
    break
  fi
  sleep 1
done

if [[ $TUNNEL_OK -ne 1 ]]; then
  echo "[run_call] ERROR: Health check through $PUBLIC_BASE_URL/health failed after 60s." >&2
  echo "--- logs/server.log (last 20 lines) ---" >&2
  tail -n 20 logs/server.log >&2 || true
  echo "--- logs/tunnel.log (last 20 lines) ---" >&2
  tail -n 20 logs/tunnel.log >&2 || true
  exit 1
fi
echo "[run_call] Tunnel verified healthy: $PUBLIC_BASE_URL"

# 6. Start LiveKit worker
echo "[run_call] Starting LiveKit worker..."
rm -f logs/worker.log
set -a
[ -f .env ] && source .env
set +a
"$PYTHON" -m pgai_challenge.worker start > logs/worker.log 2>&1 &
WORKER_PID=$!

echo "[run_call] Waiting for worker to register with LiveKit Cloud (up to 60s)..."
WORKER_REGISTERED=0
for ((i=1; i<=60; i++)); do
  if ! kill -0 "$WORKER_PID" 2>/dev/null; then
    echo "[run_call] ERROR: LiveKit worker died. See logs/worker.log:" >&2
    tail -n 20 logs/worker.log >&2
    exit 1
  fi
  if grep -i -E "registered worker|worker_registered|registered" logs/worker.log >/dev/null 2>&1; then
    WORKER_REGISTERED=1
    break
  fi
  sleep 1
done

if [[ $WORKER_REGISTERED -ne 1 ]]; then
  echo "[run_call] ERROR: LiveKit worker failed to register after 60s. Last 20 lines of logs/worker.log:" >&2
  tail -n 20 logs/worker.log >&2
  exit 1
fi
echo "[run_call] LiveKit worker registered successfully."

# 7. Run the call runner
echo "[run_call] Executing call runner..."
SCENARIO="$1"
shift
if [[ "$SCENARIO" == --* ]]; then
  "$PYTHON" -m pgai_challenge.runner "$SCENARIO" "$@"
else
  "$PYTHON" -m pgai_challenge.runner --scenario "$SCENARIO" "$@"
fi

# 8. Post-call summary & artifacts
echo ""
echo "========================================="
echo "=== Worker Log (Last 30 lines) ==="
echo "========================================="
if [[ -f logs/worker.log ]]; then
  tail -n 30 logs/worker.log || true
fi

if [[ -f "recordings/pending.jsonl" && -s "recordings/pending.jsonl" ]]; then
  echo ""
  echo "[run_call] Downloading queued recordings..."
  "$PYTHON" -m pgai_challenge.recording || true
fi

echo ""
echo "========================================="
echo "=== Produced Artifacts ==="
echo "========================================="
TRANSCRIPTS=$(find transcripts -type f \( -name "*.txt" -o -name "*.jsonl" \) 2>/dev/null | sort || true)
if [[ -n "$TRANSCRIPTS" ]]; then
  echo "Transcripts:"
  echo "$TRANSCRIPTS"
else
  echo "Transcripts: (none found)"
fi

RECORDINGS=$(find recordings -type f -name "*.mp3" 2>/dev/null | sort || true)
if [[ -n "$RECORDINGS" ]]; then
  echo "Recordings:"
  echo "$RECORDINGS"
else
  echo "Recordings: (none found)"
fi
