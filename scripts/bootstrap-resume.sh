#!/usr/bin/env bash
# Restart services stopped by bootstrap-prep.sh.
# Run manually: bash /opt/scripts/bootstrap-resume.sh

set -euo pipefail

echo "=== Bootstrap resume: restarting services ==="

echo "[1/3] Starting infinity (BGE reranker)..."
docker start infinity && echo "      infinity started" || echo "      ERROR: could not start infinity"

echo "[2/3] Starting openviking..."
docker start openviking && echo "      openviking started" || echo "      ERROR: could not start openviking"

echo "[3/3] Starting n8n and n8n-python-runner..."
docker start n8n n8n-n8n-python-runner-1 && echo "      n8n started" || echo "      ERROR: could not start n8n"

echo ""
echo "Note: nomic-embed-text will reload in Ollama automatically on next use."
echo ""
echo "=== VRAM after resume ==="
nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader,nounits | awk -F, '{printf "  Used: %d MB   Free: %d MB\n", $1, $2}'

echo ""
echo "All services resumed."
