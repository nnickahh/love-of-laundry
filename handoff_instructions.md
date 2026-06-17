# Laptop Setup & Model Training Handoff Instructions

Follow these steps on your **ASUS TUF Gaming F15 laptop** to install the dependencies, download the datasets, balance the class distributions, and run the training at maximum hardware speed.

---

## Prerequisites (On the Laptop)

1. Make sure you have **Python 3.11** installed.
2. Verify that your NVIDIA GPU drivers are up-to-date to support CUDA 12.1.

---

## Step 1 — Copy the Project to Your Laptop

Copy the entire `garment-inspection-system` project directory from your desktop to your laptop (via a USB drive, local network share, or Git).

---

## Step 2 — Create Virtual Environment & Install Packages

Open a terminal (Command Prompt or PowerShell) inside the `garment-inspection-system` directory on your laptop and run the following commands:

```powershell
# 1. Create the virtual environment
python -m venv .venv

# 2. Activate the virtual environment
.venv\Scripts\activate

# 3. Install PyTorch with CUDA 12.1 acceleration (Crucial for RTX 4060 training speed)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121

# 4. Install other dependencies (ultralytics, fastapi, roboflow, etc.)
pip install -r requirements.txt
```

---

## Step 3 — Download the Datasets

Run the download script to retrieve the defect datasets and the new 17,017-image clothing dataset:

```powershell
python download_roboflow.py
```

*This will download `dataset/roboflow/cloth_defect`, `dataset/roboflow/dataset3`, and `dataset/roboflow/clothing_detection_2` using your Roboflow API key.*

---

## Step 4 — Merge, Oversample & Start Training

Launch the main training script. This script will automatically balance the dataset (oversampling `stain` and other defects to ~1,500+ samples) and run YOLO26s for 100 epochs on your RTX 4060:

```powershell
python merge_and_train.py
```

### What to expect during training:
- **Auto-Balancing Logs**: Before training starts, you will see printouts of the original class counts followed by the new balanced counts (where defects are boosted).
- **Max Utilization**: The training will automatically use 8 CPU workers, Float16 mixed precision (`amp=True`), and a batch size of 32 to saturate the RTX 4060.
- **Estimated Duration**: **~2 to 3.5 hours**. The laptop will run hot as it utilizes the full GPU power.

---

## Step 5 — Verify Live YOLO Overlay

Once training completes and saves weights to `runs/detect/garment_inspector_v2/weights/best.pt`, you can test live inference:

1. **Start the Cloud Server**:
   ```powershell
   .venv\Scripts\python -m uvicorn cloud.main:app --port 8080
   ```
2. **Start the Edge Server**:
   ```powershell
   .venv\Scripts\python -m uvicorn edge.main:app --port 8000
   ```
3. Open your browser to `http://localhost:8000/static/index.html`.
4. Click **Start Live Feed** and check the **Live YOLO Overlay** box. 
5. The live stream will now display real-time bounding boxes overlaying the new garment types and defect classes!
