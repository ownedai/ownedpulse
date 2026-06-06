#!/usr/bin/env bash
# Free VRAM and stop non-essential services before a full bootstrap run.
# Run manually: bash /opt/scripts/bootstrap-prep.sh
# Undo with:    bash /opt/scripts/bootstrap-resume.sh

set -euo pipefail

echo "=== Bootstrap prep: freeing VRAM and stopping non-essential services ==="

echo "[1/4] Unloading nomic-embed-text from Ollama..."
ollama stop nomic-embed-text 2>/dev/null && echo "      nomic-embed-text unloaded" || echo "      nomic-embed-text was not loaded (ok)"

echo "[2/4] Stopping infinity (BGE reranker)..."
docker stop infinity && echo "      infinity stopped" || echo "      infinity was not running (ok)"

echo "[3/4] Stopping openviking..."
docker stop openviking && echo "      openviking stopped" || echo "      openviking was not running (ok)"

echo "[4/4] Stopping n8n and n8n-python-runner..."
docker stop n8n n8n-n8n-python-runner-1 && echo "      n8n stopped" || echo "      n8n was not running (ok)"

echo ""
echo "=== VRAM after prep ==="
nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader,nounits | awk -F, '{printf "  Used: %d MB   Free: %d MB\n", $1, $2}'

echo ""
echo "Ready for bootstrap. Run bootstrap-resume.sh when done."
