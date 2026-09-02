import cv2
import numpy as np
import time
import os
from pathlib import Path

# Check potential ONNX model paths
possible_paths = [
    "best.onnx",
    "runs/detect/garment_inspector_v2/weights/best.onnx",
    "weights/best.onnx",
]

model_path = None
for p in possible_paths:
    if os.path.exists(p):
        model_path = p
        break

if not model_path:
    print(f"ERROR: Could not find best.onnx in any of: {possible_paths}")
    exit(1)

print(f"Loading {model_path} into OpenCV DNN Engine...")
net = cv2.dnn.readNetFromONNX(model_path)

# Prepare 640x640 dummy image
dummy_img = np.random.randint(0, 255, (640, 640, 3), dtype=np.uint8)
blob = cv2.dnn.blobFromImage(dummy_img, 1.0 / 255.0, (640, 640), swapRB=True, crop=False)
net.setInput(blob)

print("Warming up engine (5 runs)...")
for _ in range(5):
    net.forward()

print("Running 50 benchmark iterations...")
latencies = []
for i in range(50):
    t0 = time.perf_counter()
    outputs = net.forward()
    t1 = time.perf_counter()
    latencies.append((t1 - t0) * 1000)

mean_ms = sum(latencies) / len(latencies)
fps = 1000.0 / mean_ms

print("\n" + "=" * 50)
print("  RASPBERRY PI ONNX INFERENCE RESULT")
print("=" * 50)
print(f"  Model Loaded: {model_path}")
print(f"  Mean Latency: {mean_ms:.2f} ms")
print(f"  Speed:        {fps:.2f} FPS")
print("=" * 50)