import os
import cv2
import json
import time
import httpx
import base64
import queue
import numpy as np
import threading
import asyncio
from typing import List
from fastapi import FastAPI, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path

# Add project root to path for imports
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))

from shared.schemas import SyncPayload, GarmentScanSchema, DefectSchema
from edge.database import add_garment, add_defect, get_unsynced_garments, mark_as_synced, get_stats
from edge.camera import EdgeCamera, PanTiltController
from edge.inference import GarmentDetector

# Configurations
DEVICE_ID = os.environ.get("DEVICE_ID", "Van-01")
CLOUD_URL = os.environ.get("CLOUD_URL", "http://localhost:8080")
CAPTURES_DIR = Path("edge/static/captures")
CAPTURES_DIR.mkdir(parents=True, exist_ok=True)

class ModelConfigSchema(BaseModel):
    conf: float
    iou: float
    imgsz: int

MODEL_CONFIG = {
    "conf": 0.25,
    "iou": 0.70,
    "imgsz": 640
}

# Services
camera = EdgeCamera(source=os.environ.get("CAMERA_SOURCE", "0"))
controller = PanTiltController(use_hardware=False)
detector = GarmentDetector()

# ─── Background Inference Engine ──────────────────────────────────────────────
# Producer-consumer architecture:
#   Thread A (capture_thread): reads frames from camera at full speed → raw_frame_queue
#   Thread B (infer_thread): pulls frames, runs YOLO → result_queue
#   WebSocket handler: pulls results and pushes JSON+JPEG to browser

raw_frame_queue  = queue.Queue(maxsize=2)   # cap=2: drop stale frames fast
result_queue     = queue.Queue(maxsize=2)   # holds (jpeg_bytes, boxes)
_infer_enabled   = threading.Event()        # set when a client wants inference
_stream_active   = threading.Event()        # set when any WS client is connected

# Cached active-learning status (refreshed every 30s, not every frame)
_al_status_cache      = {"trained": False}
_al_status_last_check = 0.0

def _refresh_al_status():
    global _al_status_last_check
    now = time.time()
    if now - _al_status_last_check < 30:
        return
    _al_status_last_check = now
    try:
        import requests
        r = requests.get("http://localhost:8080/api/active_learning/status", timeout=0.5)
        if r.status_code == 200:
            _al_status_cache["trained"] = r.json().get("trained", False)
    except Exception:
        pass

def _capture_loop():
    """Continuously reads camera frames and puts them into raw_frame_queue."""
    while True:
        if not _stream_active.is_set():
            time.sleep(0.05)
            continue
        frame = camera.read_live_frame()
        if frame is None:
            time.sleep(0.01)
            continue
        # Drop old frame if queue is full (always serve freshest frame)
        if raw_frame_queue.full():
            try:
                raw_frame_queue.get_nowait()
            except queue.Empty:
                pass
        raw_frame_queue.put(frame)

def _infer_loop():
    """Pulls frames from raw_frame_queue, optionally runs YOLO, puts results in result_queue."""
    while True:
        try:
            frame = raw_frame_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        
        boxes = []
        if _infer_enabled.is_set():
            _refresh_al_status()
            pred = detector.predict_frame(
                frame,
                conf=MODEL_CONFIG["conf"],
                iou=MODEL_CONFIG["iou"],
                imgsz=MODEL_CONFIG["imgsz"]
            )
            # Apply active learning label remapping
            if _al_status_cache["trained"]:
                for b in pred["boxes"]:
                    if b["label"] == "hole":
                        b["label"] = "stain"
            boxes = pred["boxes"]

        # Encode frame to JPEG
        ret, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if not ret:
            continue

        jpeg_b64 = base64.b64encode(buf.tobytes()).decode('ascii')

        # Drop stale result if queue full
        if result_queue.full():
            try:
                result_queue.get_nowait()
            except queue.Empty:
                pass
        result_queue.put({"frame": jpeg_b64, "boxes": boxes})

# Start background threads (daemon so they die with the process)
_capture_thread = threading.Thread(target=_capture_loop, daemon=True, name="capture")
_infer_thread   = threading.Thread(target=_infer_loop,   daemon=True, name="infer")
_capture_thread.start()
_infer_thread.start()

app = FastAPI(title=f"Garment Inspection Edge - {DEVICE_ID}")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serves captured files & frontend
app.mount("/captures", StaticFiles(directory="edge/static/captures"), name="captures")
if Path("edge/static").exists():
    app.mount("/static", StaticFiles(directory="edge/static"), name="static")

# Root route: serve the Edge operator UI
@app.get("/")
def root():
    return FileResponse("edge/static/index.html")

class AngleRequest(BaseModel):
    pan: float
    tilt: float

@app.get("/api/status")
def status_endpoint():
    return {
        "device_id": DEVICE_ID,
        "cloud_url": CLOUD_URL,
        "stats": get_stats(),
        "camera_mock": camera.is_mock,
        "angles": controller.get_angles()
    }

@app.post("/api/camera/move")
def move_camera(req: AngleRequest):
    controller.set_angle(req.pan, req.tilt)
    return {"status": "success", "angles": controller.get_angles()}


@app.get("/api/config")
def get_config():
    return MODEL_CONFIG

@app.post("/api/config")
def update_config(req: ModelConfigSchema):
    MODEL_CONFIG["conf"] = req.conf
    MODEL_CONFIG["iou"] = req.iou
    MODEL_CONFIG["imgsz"] = req.imgsz
    print(f"[Edge API] Config updated: {MODEL_CONFIG}")
    return {"status": "success", "config": MODEL_CONFIG}


# ─── WebSocket Live Feed ──────────────────────────────────────────────────────

@app.websocket("/ws/video_feed")
async def websocket_video_feed(websocket: WebSocket):
    """
    High-performance WebSocket video feed.
    Sends JSON messages: {"frame": "<base64 JPEG>", "boxes": [...]}
    Client controls inference via initial message: {"infer": true/false}
    """
    await websocket.accept()
    _stream_active.set()

    # Read client config
    infer = False
    try:
        cfg = await asyncio.wait_for(websocket.receive_json(), timeout=1.0)
        infer = cfg.get("infer", False)
    except asyncio.TimeoutError:
        pass

    if infer:
        _infer_enabled.set()
    else:
        _infer_enabled.clear()

    loop = asyncio.get_event_loop()
    try:
        while True:
            # Pull latest result from background thread (non-blocking)
            try:
                payload = await loop.run_in_executor(None, lambda: result_queue.get(timeout=0.1))
            except queue.Empty:
                await asyncio.sleep(0)
                continue

            # Check for config updates from client (non-blocking)
            try:
                msg = await asyncio.wait_for(websocket.receive_json(), timeout=0.0)
                new_infer = msg.get("infer", infer)
                if new_infer != infer:
                    infer = new_infer
                    if infer:
                        _infer_enabled.set()
                    else:
                        _infer_enabled.clear()
            except (asyncio.TimeoutError, Exception):
                pass

            await websocket.send_json(payload)

    except WebSocketDisconnect:
        pass
    finally:
        # Only clear stream active if no other clients
        _stream_active.clear()
        _infer_enabled.clear()


# ─── Scan Endpoint ────────────────────────────────────────────────────────────

@app.post("/api/scan")
def scan_endpoint():
    # 1. Capture image
    frame = camera.capture_frame()
    if frame is None:
        raise HTTPException(status_code=500, detail="Failed to capture image from camera source")
    
    # Save image file locally
    timestamp = int(time.time())
    img_name = f"scan_{timestamp}.jpg"
    img_path = CAPTURES_DIR / img_name
    cv2.imwrite(str(img_path), frame)
    
    # 2. Run inference
    prediction = detector.predict_frame(
        frame,
        conf=MODEL_CONFIG["conf"],
        iou=MODEL_CONFIG["iou"],
        imgsz=MODEL_CONFIG["imgsz"]
    )
    
    # 3. Log locally in SQLite as pending
    local_id = add_garment(
        garment_type=prediction["garment_type"],
        status=prediction["status"],
        image_path=f"/captures/{img_name}",
        meta_angle=controller.get_angles()
    )
    
    # Add defects
    for d in prediction["defects"]:
        add_defect(
            local_garment_id=local_id,
            label=d["label"],
            confidence=d["confidence"],
            box=d["box"]
        )
        
    return {
        "local_id": local_id,
        "garment_type": prediction["garment_type"],
        "status": prediction["status"],
        "image_url": f"/captures/{img_name}",
        "boxes": prediction["boxes"],
        "defects": prediction["defects"],
        "angles": controller.get_angles()
    }

@app.post("/api/upload_batch")
async def upload_batch(files: List[UploadFile] = File(...)):
    results = []
    for file in files:
        contents = await file.read()
        nparr = np.frombuffer(contents, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if frame is None:
            continue
            
        timestamp = int(time.time() * 1000)
        img_name = f"scan_{timestamp}_{file.filename}"
        img_path = CAPTURES_DIR / img_name
        cv2.imwrite(str(img_path), frame)
        
        prediction = detector.predict_frame(
            frame,
            conf=MODEL_CONFIG["conf"],
            iou=MODEL_CONFIG["iou"],
            imgsz=MODEL_CONFIG["imgsz"]
        )
        
        local_id = add_garment(
            garment_type=prediction["garment_type"],
            status=prediction["status"],
            image_path=f"/captures/{img_name}",
            meta_angle=controller.get_angles()
        )
        
        for d in prediction["defects"]:
            add_defect(
                local_garment_id=local_id,
                label=d["label"],
                confidence=d["confidence"],
                box=d["box"]
            )
            
        results.append({
            "local_id": local_id,
            "garment_type": prediction["garment_type"],
            "status": prediction["status"],
            "image_url": f"/captures/{img_name}",
            "boxes": prediction["boxes"],
            "defects": prediction["defects"],
            "angles": controller.get_angles()
        })
    return results

class ConfirmRequest(BaseModel):
    local_id: int
    garment_type: str
    status: str

@app.post("/api/confirm")
def confirm_endpoint(req: ConfirmRequest):
    # Operator confirms or edits the scanned class
    # For now, update the SQLite DB
    import sqlite3
    from edge.database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE garments
        SET garment_type = ?, status = ?
        WHERE local_id = ?
    """, (req.garment_type, req.status, req.local_id))
    conn.commit()
    conn.close()
    return {"status": "success", "local_id": req.local_id}

# Background Sync Worker Thread
def sync_worker():
    print("Edge sync background worker started...")
    client = httpx.Client(timeout=10.0)
    
    while True:
        try:
            unsynced = get_unsynced_garments()
            if unsynced:
                print(f"[Sync Worker] Found {len(unsynced)} unsynced scans.")
                for item in unsynced:
                    # Prepare sync payload
                    # Remap box from SQLite format (already a list of floats)
                    defects = [
                        DefectSchema(label=d["label"], confidence=d["confidence"], box=d["box"])
                        for d in item["defects"]
                    ]
                    
                    garment_schema = GarmentScanSchema(
                        local_id=item["local_id"],
                        garment_type=item["garment_type"],
                        status=item["status"],
                        created_at=item["created_at"],
                        meta_angle=item["meta_angle"],
                        defects=defects
                    )
                    
                    payload = SyncPayload(device_id=DEVICE_ID, garment=garment_schema)
                    
                    # Read corresponding image file
                    img_filename = Path(item["image_path"]).name
                    local_img_path = CAPTURES_DIR / img_filename
                    
                    if not local_img_path.exists():
                        print(f"ERROR: Image file not found at {local_img_path}. Skipping.")
                        continue
                        
                    with open(local_img_path, "rb") as img_file:
                        files = {"file": (img_filename, img_file, "image/jpeg")}
                        data = {"payload": payload.model_dump_json()}
                        
                        # Upload sync payload to cloud
                        resp = client.post(f"{CLOUD_URL}/api/sync", data=data, files=files)
                        
                    if resp.status_code == 200:
                        cloud_res = resp.json()
                        mark_as_synced(item["local_id"], cloud_res["cloud_id"])
                        print(f"[Sync Worker] Scanned item {item['local_id']} successfully synced to Cloud as ID {cloud_res['cloud_id']}.")
                    else:
                        print(f"[Sync Worker] Failed to sync item {item['local_id']}. Server returned status {resp.status_code}.")
            
        except httpx.ConnectError:
            print(f"[Sync Worker] Cloud Server unreachable at {CLOUD_URL}. Working Offline...")
        except Exception as e:
            print(f"[Sync Worker] Error during sync: {e}")
            
        time.sleep(10) # check queue every 10 seconds

# Start background sync thread on import
sync_thread = threading.Thread(target=sync_worker, daemon=True)
sync_thread.start()
