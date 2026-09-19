#!/usr/bin/env bash
set -euo pipefail

# scripts/run_call.sh - Run a single test call without terminal juggling.
# Starts cloudflared tunnel, Flask server, and LiveKit worker, verifies health,
# runs the requested scenario, and cleanly shuts down background processes on exit.

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

# Read PORT from .env (default 5000)
PORT="5000"
if [[ -f .env ]]; then
  ENV_PORT=$(grep -E '^PORT=' .env 2>/dev/null | cut -d '=' -f2- | tr -d ' "'\''' | tr -d '\r' || true)
  if [[ -n "$ENV_PORT" ]]; then
    PORT="$ENV_PORT"
  fi
fi

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
  if [[ -n "${SERVER_PID:-}" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "[run_call] Stopping server (PID $SERVER_PID)..."
    kill "$SERVER_PID" 2>/dev/null || true
  fi
  if [[ -n "${TUNNEL_PID:-}" ]] && kill -0 "$TUNNEL_PID" 2>/dev/null; then
    echo "[run_call] Stopping cloudflared tunnel (PID $TUNNEL_PID)..."
    kill "$TUNNEL_PID" 2>/dev/null || true
  fi
  wait 2>/dev/null || true
  exit "$exit_code"
}
trap cleanup EXIT INT TERM

# 1. Start cloudflared tunnel
echo "[run_call] Starting cloudflared tunnel on port $PORT..."
rm -f logs/tunnel.log
cloudflared tunnel --url "http://localhost:$PORT" > logs/tunnel.log 2>&1 &
TUNNEL_PID=$!

TUNNEL_URL=""
for ((i=1; i<=60; i++)); do
  if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
    echo "[run_call] ERROR: cloudflared tunnel failed to start. See logs/tunnel.log:" >&2
    tail -n 20 logs/tunnel.log >&2
    exit 1
  fi
  TUNNEL_URL=$(grep -o -E 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' logs/tunnel.log 2>/dev/null | head -n 1 || true)
  if [[ -n "$TUNNEL_URL" ]]; then
    break
  fi
  sleep 1
done

if [[ -z "$TUNNEL_URL" ]]; then
  echo "[run_call] ERROR: Timed out waiting for trycloudflare.com URL after 60s. See logs/tunnel.log:" >&2
  tail -n 20 logs/tunnel.log >&2
  exit 1
fi
echo "[run_call] Tunnel active: $TUNNEL_URL"

# 2. Write PUBLIC_BASE_URL into .env
echo "[run_call] Updating PUBLIC_BASE_URL in .env..."
"$PYTHON" -c "
import sys
url = sys.argv[1]
try:
    with open('.env', 'r') as f:
        lines = f.read().splitlines()
except FileNotFoundError:
    lines = []

found = False
new_lines = []
for line in lines:
    if line.startswith('PUBLIC_BASE_URL='):
        new_lines.append(f'PUBLIC_BASE_URL={url}')
        found = True
    else:
        new_lines.append(line)
if not found:
    new_lines.append(f'PUBLIC_BASE_URL={url}')

with open('.env', 'w') as f:
    f.write('\n'.join(new_lines) + '\n')
" "$TUNNEL_URL"

# 3. Start Flask server
echo "[run_call] Starting Flask server on port $PORT..."
rm -f logs/server.log
PORT="$PORT" "$PYTHON" -m pgai_challenge.server > logs/server.log 2>&1 &
SERVER_PID=$!

echo "[run_call] Verifying server health through tunnel ($TUNNEL_URL/health)..."
SERVER_OK=0
for ((i=1; i<=30; i++)); do
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "[run_call] ERROR: Flask server died. See logs/server.log:" >&2
    tail -n 20 logs/server.log >&2
    exit 1
  fi
  if curl -sf --connect-timeout 3 "$TUNNEL_URL/health" >/dev/null 2>&1; then
    SERVER_OK=1
    break
  fi
  sleep 1
done

if [[ $SERVER_OK -ne 1 ]]; then
  echo "[run_call] ERROR: Server never returned ok via tunnel ($TUNNEL_URL/health) after 30s. See logs/server.log:" >&2
  tail -n 20 logs/server.log >&2
  exit 1
fi
echo "[run_call] Server verified healthy via tunnel."

# 4. Start LiveKit worker
echo "[run_call] Starting LiveKit worker..."
rm -f logs/worker.log
set -a
[ -f .env ] && source .env
set +a
"$PYTHON" -m pgai_challenge.worker start > logs/worker.log 2>&1 &
WORKER_PID=$!

echo "[run_call] Waiting for worker to register with LiveKit Cloud..."
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

# 5. Run the call runner
echo "[run_call] Executing call runner..."
SCENARIO="$1"
shift
if [[ "$SCENARIO" == --* ]]; then
  "$PYTHON" -m pgai_challenge.runner "$SCENARIO" "$@"
else
  "$PYTHON" -m pgai_challenge.runner --scenario "$SCENARIO" "$@"
fi

# 6. Post-call summary & artifacts
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
