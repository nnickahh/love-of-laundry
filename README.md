# love of laundry

[![python](https://img.shields.io/badge/python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![yolo](https://img.shields.io/badge/yolo-custom_object_detection-00FFFF)](https://docs.ultralytics.com/)
[![fastapi](https://img.shields.io/badge/fastapi-edge_%26_cloud-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![opencv](https://img.shields.io/badge/opencv-real--time_vision-5C3EE8?logo=opencv&logoColor=white)](https://opencv.org/)
[![sqlite](https://img.shields.io/badge/sqlite-offline_sync-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)

**love of laundry** is a real-time edge-to-cloud ai garment inspection and defect tracking system. it deploys custom-trained yolo object detection models on local edge nodes (raspberry pi / local inspection stations) with a live fastapi operator overlay, offline-first sqlite caching, and automated background synchronization to a central cloud analytics dashboard.

---

## system architecture

```mermaid
graph TD
    subgraph edge system
        Camera["camera source"] -->|capture| Inference["yolo inference engine"]
        Inference -->|overlay| LiveFeed["operator live ui"]
        Inference -->|local log| EdgeDB[("edge sqlite db")]
        Inference -->|sync payload| SyncThread["background sync thread"]
    end

    subgraph cloud system
        SyncThread -->|http post| CloudAPI["cloud rest api"]
        CloudAPI -->|store reports| CloudDB[("cloud sqlite db")]
        CloudAPI -->|dashboard web app| AdminDashboard["admin web ui"]
    end
```

- **edge server (`edge/`)**: lightweight fastapi service running on local edge nodes (e.g., raspberry pi) to capture camera frames, perform local yolo inference (`runs/detect/garment_inspector_v2/weights/best.pt`), stream an annotated live overlay to station operators, and cache inspection logs locally.
- **cloud server (`cloud/`)**: central management service that ingests synced garment inspection reports and serves an administrative web dashboard to monitor defect distributions across all active edge stations.
- **shared module (`shared/`)**: unified data schemas and validation models shared between the edge and cloud microservices.

---

## key features

- **real-time edge defect detection**: custom-trained yolo weights detect stains, tears, and garment defects directly at the inspection station with low latency.
- **offline-first sqlite resilience**: edge stations log every scan locally to sqlite and automatically synchronize pending reports in the background when cloud connectivity is available.
- **live operator hud**: browser-based operator view with real-time bounding box overlays and confidence telemetry.
- **centralized cloud analytics**: multi-node aggregation dashboard tracking inspection throughput and defect categories across stations.

---

## installation & setup

ensure you have **python 3.11+** installed.

### quick start
custom-trained model weights are included in `runs/detect/garment_inspector_v2/weights/best.pt`, allowing you to run inference immediately out of the box:

1. **clone & set up virtual environment**:
   ```powershell
   git clone https://github.com/nnickahh/love-of-laundry.git
   cd love-of-laundry
   python -m venv .venv
   .venv\Scripts\activate
   ```
2. **install dependencies**:
   ```powershell
   pip install -r requirements.txt
   ```
3. **launch the servers**:
   follow the [running the servers](#running-the-servers) instructions below to start the cloud dashboard and edge operator ui. databases and model weights initialize automatically on first launch.

---

### custom training & dataset setup (optional)
to customize the dataset or retrain the garment inspection model:

1. **install pytorch with cuda acceleration** (for gpu training):
   ```powershell
   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
   ```
2. **download & balance datasets**:
   ```powershell
   python scripts/training/download_roboflow.py
   ```
3. **train the model**:
   ```powershell
   python scripts/training/merge_and_train.py
   ```

---

## running the servers

### 1. start the cloud server
launches the central analytics dashboard at `http://localhost:8080`:
```powershell
.venv\Scripts\python -m uvicorn cloud.main:app --port 8080
```

### 2. start the edge server
launches the edge inspection node and operator ui at `http://localhost:8000/static/index.html`:
```powershell
$env:DEVICE_ID="Van-01"
$env:CLOUD_URL="http://localhost:8080"
$env:CAMERA_SOURCE="assets/test_clothing.png" # or a camera index e.g., "0"
.venv\Scripts\python -m uvicorn edge.main:app --port 8000
```

---

## verification

run the automated end-to-end integration suite to verify edge-to-cloud synchronization:
```powershell
python scripts/tools/verify_system.py
```
this script boots test instances of both servers, triggers an edge garment scan, verifies background sqlite database synchronization, and reports system health.

---

## author

**nick fong** ([@nnickahh](https://github.com/nnickahh))
