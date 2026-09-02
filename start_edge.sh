#!/bin/bash
# Raspberry Pi 5 Edge Server Startup Script

# Activate virtual environment if present
if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d "$HOME/lol_project" ]; then
    source "$HOME/lol_project/bin/activate"
elif [ -d "lol_project" ]; then
    source lol_project/bin/activate
fi

# Limit multi-threading overhead to protect Pi 5 thermal & power budget
export OMP_NUM_THREADS=2
export OPENBLAS_NUM_THREADS=2
export MKL_NUM_THREADS=2
export NUMEXPR_NUM_THREADS=2

# Default environment configuration
export DEVICE_ID="${DEVICE_ID:-RPi5-01}"
export CLOUD_URL="${CLOUD_URL:-http://172.20.116.72:8080}"
export USE_GPU="0"

# ── Ensure Time Synchronization (Singapore SGT) ─────────────────────────────
timedatectl set-timezone Asia/Singapore 2>/dev/null || true
timedatectl set-ntp true 2>/dev/null || true

# ── Virtual Memory Check ─────────────────────────────────────────────────────
SWAP_TOTAL=$(free -m 2>/dev/null | awk '/^Swap:/ {print $2}')
if [ -n "$SWAP_TOTAL" ] && [ "$SWAP_TOTAL" -lt 500 ] 2>/dev/null; then
    echo ""
    echo "  ⚠  WARNING: Swap space is only ${SWAP_TOTAL} MB."
    echo "     Run: sudo ./scripts/setup_swap.sh"
    echo ""
fi

echo "=================================================="
echo " Starting Laundry Vision Edge Server on Raspberry Pi 5"
echo " Device ID:      $DEVICE_ID"
echo " Cloud URL:      $CLOUD_URL"
echo " Camera Source:  $CAMERA_SOURCE"
echo " CPU Threads:    2 (Optimized for Pi 5 Stability)"
echo " Edge UI:        http://0.0.0.0:8000/static/index.html"
echo "=================================================="

python3 -m uvicorn edge.main:app --host 0.0.0.0 --port 8000
