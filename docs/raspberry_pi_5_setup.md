# Raspberry Pi 5 Setup & Model Deployment Guide

This guide explains how to copy the model file (`best.pt` / `best.onnx`) and project files to your **Raspberry Pi 5**, install the environment, and run live inference.

---

## 1. Transfer Model and Files to Raspberry Pi 5

Choose one of the following methods to transfer the project and weights to your Raspberry Pi:

### Method A: Secure Copy (`scp`) via Network (Recommended)
From your Windows PC / Laptop terminal (PowerShell), replace `<pi-user>` (usually `pi` or your custom username) and `<pi-ip>` (e.g., `192.168.1.50`):

```powershell
# 1. Create directory on Raspberry Pi
ssh <pi-user>@<pi-ip> "mkdir -p ~/laundry_vision/runs/detect/garment_inspector_v2/weights"

# 2. Copy the model weights (.onnx or .pt)
scp runs\detect\garment_inspector_v2\weights\best.onnx <pi-user>@<pi-ip>:~/laundry_vision/runs/detect/garment_inspector_v2/weights/
scp runs\detect\garment_inspector_v2\weights\best.pt <pi-user>@<pi-ip>:~/laundry_vision/runs/detect/garment_inspector_v2/weights/

# 3. Copy the codebase (edge service, scripts, and static files)
scp -r edge shared scripts test_onnx.py requirements.txt start_edge.sh <pi-user>@<pi-ip>:~/laundry_vision/
```

### Method B: USB Flash Drive
1. Copy the `laundry_vision` project folder or the `runs/detect/garment_inspector_v2/weights/best.onnx` file to a USB thumb drive.
2. Insert the USB drive into the Raspberry Pi 5 USB 3.0 port.
3. Copy the files into your home directory (e.g. `~/laundry_vision`).

### Method C: Git Clone
If your code is pushed to GitHub / GitLab:
```bash
git clone https://github.com/Skithrills/laundry_vision.git ~/laundry_vision
cd ~/laundry_vision
```

---

## 2. Install Dependencies on Raspberry Pi 5

Open a terminal on your Raspberry Pi 5:

```bash
cd ~/laundry_vision

# 1. Update system packages
sudo apt update && sudo apt install -y python3-pip python3-venv libgl1-mesa-glx

# 2. Create and activate a Python virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install required Python packages
pip install --upgrade pip
pip install ultralytics opencv-python fastapi uvicorn httpx pydantic numpy
```

---

## 3. Test & Benchmark Model Loading on Raspberry Pi 5

Run the built-in benchmark script to verify OpenCV DNN loads `best.onnx`:

```bash
python3 test_onnx.py
```

You should see output similar to:
```text
==================================================
  RASPBERRY PI ONNX INFERENCE RESULT
==================================================
  Model Loaded: runs/detect/garment_inspector_v2/weights/best.onnx
  Mean Latency: ~35.00 ms
  Speed:        ~28.50 FPS
==================================================
```

---

## 4. Run the Full Edge Service on Raspberry Pi 5

To start the real-time camera inspection server and operator interface:

```bash
# Make start script executable
chmod +x start_edge.sh

# Run the Edge server
./start_edge.sh
```

Or run directly with environment variables:
```bash
export DEVICE_ID="RPi5-Van-01"
export CLOUD_URL="http://<YOUR_LAPTOP_OR_CLOUD_IP>:8080"
export CAMERA_SOURCE="0"   # "0" for USB camera / Pi Camera (or path to test image/video)
export USE_GPU="0"

python3 -m uvicorn edge.main:app --host 0.0.0.0 --port 8000
```

### Accessing the Web UI:
- On the Raspberry Pi browser: `http://localhost:8000/static/index.html`
- From any device on the same local network: `http://<RASPBERRY_PI_IP>:8000/static/index.html`

---

## 5. Raspberry Pi AI HAT+ (Hailo-8 / Hailo-8L NPU) Hardware Acceleration (60–100+ FPS)

The **Raspberry Pi AI HAT+** contains a **Hailo-8** (26 TOPS) or **Hailo-8L** (13 TOPS) NPU accelerator over PCIe that triples inference frame rates (from ~28 FPS CPU to 75–100+ FPS NPU) with ~0% CPU utilization.

### A. Enable PCIe Gen 3 on Raspberry Pi 5
Edit `/boot/firmware/config.txt` on your Raspberry Pi:
```bash
sudo nano /boot/firmware/config.txt
```
Add the following lines at the bottom:
```ini
# Enable PCIe Gen 3 for Raspberry Pi AI HAT+
dtparam=pciex1
dtparam=pciex1_gen=3
```
Save and reboot:
```bash
sudo reboot
```

### B. Install Hailo Drivers and Runtime on Raspberry Pi
```bash
sudo apt update
sudo apt install -y hailo-all python3-hailort dkms

# Verify Hailo NPU is detected
hailortcli fw-control identify
```
You should see:
```text
Device: Hailo-8L / Hailo-8
Firmware Version: 4.x.x
```

### C. Compile & Transfer the HEF Model
1. On your PC / Laptop, run the automated HEF preparation and compilation tool:
   ```bash
   # Windows
   scripts\tools\compile_hef.bat

   # Linux / Mac
   ./scripts/tools/compile_hef.sh
   ```
2. Deploy `best.hef` to the Raspberry Pi:
   ```powershell
   .\transfer_to_pi.ps1
   ```
3. Start the Edge Server:
   ```bash
   ./start_edge.sh
   ```
   The engine will automatically detect the AI HAT+ and log:
   `Loading Hailo AI HAT+ NPU Engine from: runs/detect/garment_inspector_v2/weights/best.hef (Hardware Acceleration)`

---

## 6. Virtual Memory Setup (Swap + ZRAM) — Prevent OOM Crashes

The Raspberry Pi 5 has limited RAM (4GB/8GB). Running YOLO inference + camera + web server simultaneously can exhaust physical memory, causing the Linux OOM killer to **terminate the process**. Virtual memory (swap) ensures the system **slows down instead of crashing**.

### Quick Setup (One Command)

```bash
cd ~/laundry_vision
sudo ./scripts/setup_swap.sh
sudo reboot
```

### What It Configures

| Component | What It Does | Speed |
|---|---|---|
| **ZRAM** (compressed RAM swap) | Compresses inactive memory pages in RAM itself | ⚡ Fast (in-memory) |
| **Disk swap** (2 GB on SD card) | Safety net when RAM + ZRAM are full | 🐢 Slow (SD card I/O) |
| **Kernel tuning** (`vm.swappiness=10`) | Keeps ONNX model in physical RAM, avoids swapping unless critical | — |
| **GPU memory** (16 MB) | Frees ~100+ MB RAM reserved for unused VideoCore GPU | — |

### Verify After Reboot

```bash
# Check swap is active
free -h

# Expected output (example for 4GB Pi):
#               total   used   free   shared  buff/cache  available
# Mem:          3.7Gi   1.2Gi  1.8Gi  50Mi    700Mi       2.3Gi
# Swap:         3.9Gi   0B     3.9Gi    <-- ZRAM + disk swap active
```

### Lower Inference Resolution (Additional FPS Boost)

The `start_edge.sh` script defaults to `INFER_IMGSZ=320` on the Pi (vs. 640 on desktop). This reduces memory usage by **4× per frame** and roughly triples inference speed:

```bash
# Override if needed:
export INFER_IMGSZ=416   # Balanced (accuracy vs. speed)
export INFER_IMGSZ=320   # Fastest (recommended for Pi CPU)
export INFER_IMGSZ=640   # Full accuracy (desktop/NPU only)
```
