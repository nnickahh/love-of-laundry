#!/bin/bash
# Hailo AI HAT+ (Hailo-8 / Hailo-8L) HEF Compilation Script (Linux / macOS)

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR"

echo "================================================================="
echo " Hailo AI HAT+ (Hailo-8 / Hailo-8L) HEF Compilation"
echo "================================================================="

echo "[1/2] Preparing Hailo ONNX and INT8 Calibration Dataset..."
python3 scripts/tools/compile_to_hef.py

echo ""
echo "[2/2] Compiling to HEF with Hailo Dataflow Compiler Docker..."
docker run --rm -v "$PROJECT_DIR":/workspace -w /workspace hailo-ai/hailo-dataflow-compiler \
  hailomz compile \
    --ckpt runs/detect/garment_inspector_v2/weights/best_hailo.onnx \
    --calib-path runs/detect/garment_inspector_v2/weights/calib_data.npy \
    --hw-arch hailo8l \
    --output-dir runs/detect/garment_inspector_v2/weights

if [ -f "runs/detect/garment_inspector_v2/weights/garment_inspector.hef" ]; then
    cp runs/detect/garment_inspector_v2/weights/garment_inspector.hef runs/detect/garment_inspector_v2/weights/best.hef
    echo ""
    echo "================================================================="
    echo " SUCCESS: Compiled to runs/detect/garment_inspector_v2/weights/best.hef!"
    echo " Run ./transfer_to_pi.ps1 to deploy to your Raspberry Pi 5 AI HAT+!"
    echo "================================================================="
fi
