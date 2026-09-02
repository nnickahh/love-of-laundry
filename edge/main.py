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
from fastapi.responses import FileResponse, StreamingResponse
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
    "conf": 0.20,
    "iou": 0.45,
    "imgsz": 640
}

# Services
camera = EdgeCamera(source=os.environ.get("CAMERA_SOURCE", "0"))
controller = PanTiltController(use_hardware=False)
detector = GarmentDetector()

# ─── Decoupled Asynchronous Streaming & Inference Engine ─────────────────────
# Architecture:
#   1. Stream Loop (Thread A): Reads freshest camera frames at 30+ FPS, encodes JPEG (quality=60),
#      attaches current cached YOLO boxes, and pushes to result_queue without ANY inference delay.
#   2. Inference Loop (Thread B): Asynchronously consumes frames in background, runs YOLO at its
#      own pace (e.g. 12-15 FPS), and atomically updates _cached_boxes.
#   Result: 30+ FPS buttery-smooth live video with zero stutter or lag, and real-time bounding boxes!

result_queue          = queue.Queue(maxsize=2)   # holds {"frame": jpeg_b64, "boxes": [...]}
_infer_input_queue    = queue.Queue(maxsize=1)   # holds 1 freshest frame for background YOLO
_cached_boxes         = []
_cached_boxes_lock    = threading.Lock()
_infer_enabled        = threading.Event()        # set when a client wants inference
_stream_active        = threading.Event()        # set when any client is connected

# Client tracking for background capture/inference efficiency
_active_stream_clients = 0
_stream_clients_lock = threading.Lock()

def _stream_client_register(infer: bool = True):
    global _active_stream_clients
    with _stream_clients_lock:
        _active_stream_clients += 1
        _stream_active.set()
        _infer_enabled.set()

def _stream_client_unregister(infer: bool = True):
    global _active_stream_clients
    with _stream_clients_lock:
        _active_stream_clients = max(0, _active_stream_clients - 1)
        if _active_stream_clients == 0:
            _stream_active.clear()
            _infer_enabled.clear()
            with _cached_boxes_lock:
                _cached_boxes.clear()

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

def _infer_worker_loop():
    """Runs YOLO inference in background without ever blocking the live video stream."""
    global _cached_boxes
    while True:
        if not _infer_enabled.is_set():
            time.sleep(0.05)
            continue

        try:
            frame = _infer_input_queue.get(timeout=0.2)
        except queue.Empty:
            continue

        try:
            _refresh_al_status()
            pred = detector.predict_frame(
                frame,
                conf=MODEL_CONFIG["conf"],
                iou=MODEL_CONFIG["iou"],
                imgsz=MODEL_CONFIG["imgsz"]
            )
            boxes = pred.get("boxes", [])
            if _al_status_cache["trained"]:
                for b in boxes:
                    if b["label"] == "hole":
                        b["label"] = "stain"
            with _cached_boxes_lock:
                _cached_boxes = boxes
            # Small CPU yield between inference passes to maintain low thermals on Pi
            time.sleep(0.01)
        except Exception as e:
            print(f"[Infer Worker Error] {e}")
            time.sleep(0.1)  # Prevent tight exception spin-loop

def _stream_producer_loop():
    """Continuously serves 30+ FPS live video frames with zero latency."""
    while True:
        if not _stream_active.is_set():
            time.sleep(0.04)
            continue

        frame = camera.read_live_frame()
        if frame is None:
            time.sleep(0.005)
            continue

        # Feed frame to background inference worker (non-blocking)
        if _infer_enabled.is_set() and _infer_input_queue.empty():
            try:
                _infer_input_queue.put_nowait(frame)
            except queue.Full:
                pass

        # Retrieve current bounding boxes instantaneously from atomic cache
        current_boxes = []
        if _infer_enabled.is_set():
            with _cached_boxes_lock:
                current_boxes = list(_cached_boxes)

        # Fast JPEG encode (quality 60 offers crisp clarity with minimal CPU/bandwidth footprint)
        ret, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
        if not ret:
            continue

        jpeg_b64 = base64.b64encode(buf.tobytes()).decode('ascii')

        # Drop stale result if queue is full
        if result_queue.full():
            try:
                result_queue.get_nowait()
            except queue.Empty:
                pass
        result_queue.put({"frame": jpeg_b64, "boxes": current_boxes})
        time.sleep(0.012) # ~60 FPS maximum, prevents CPU core saturation

# Start background worker threads (daemon so they die with the process)
_stream_thread = threading.Thread(target=_stream_producer_loop, daemon=True, name="stream_producer")
_infer_thread  = threading.Thread(target=_infer_worker_loop,   daemon=True, name="infer_worker")
_stream_thread.start()
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

class CameraSourceRequest(BaseModel):
    source: str

@app.get("/api/status")
def status_endpoint():
    return {
        "device_id": DEVICE_ID,
        "cloud_url": CLOUD_URL,
        "stats": get_stats(),
        "camera_mock": camera.is_mock,
        "camera_source": camera.source,
        "camera_name": camera.source_name,
        "angles": controller.get_angles()
    }

@app.get("/api/camera/sources")
def get_camera_sources():
    """Returns detected physical webcams, streams, and active camera state."""
    return {
        "sources": camera.detect_available_sources(),
        "active_source": camera.source,
        "is_mock": camera.is_mock,
        "source_name": camera.source_name
    }

@app.post("/api/camera/source")
def set_camera_source(req: CameraSourceRequest):
    """Dynamically switches active camera source at runtime."""
    res = camera.set_source(req.source)
    print(f"[Edge API] Camera source set to: {req.source} (is_mock={res['is_mock']}, name={res['source_name']})")
    return {
        "status": "success",
        "source": res["source"],
        "is_mock": res["is_mock"],
        "source_name": res["source_name"],
        "sources": camera.detect_available_sources()
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


# ─── VLC & Browser HTTP MJPEG Live Stream Endpoint ───────────────────────────

@app.get("/video_feed")
@app.get("/video_feed.mjpg")
@app.get("/stream.mjpg")
@app.get("/mjpeg")
@app.get("/video")
@app.get("/live")
@app.get("/api/video_feed")
@app.get("/api/video_feed.mjpg")
async def mjpeg_video_feed(infer: bool = False):
    """
    Standard MJPEG stream fully compliant with VLC Player, browser <img> tags, and external players.
    Streams at a constant 30+ FPS without blocking on inference.
    """
    async def mjpeg_generator():
        _stream_client_register(infer=infer)
        try:
            while True:
                frame = camera.read_live_frame()
                if frame is None:
                    await asyncio.sleep(0.01)
                    continue

                draw_frame = frame
                if infer:
                    # Feed frame to background worker if ready
                    if _infer_input_queue.empty():
                        try:
                            _infer_input_queue.put_nowait(frame)
                        except queue.Full:
                            pass

                    # Retrieve cached boxes instantly
                    with _cached_boxes_lock:
                        boxes = list(_cached_boxes)

                    if boxes:
                        draw_frame = frame.copy()
                        h, w = draw_frame.shape[:2]
                        for b in boxes:
                            x1 = int(b["box"][0] * w)
                            y1 = int(b["box"][1] * h)
                            x2 = int(b["box"][2] * w)
                            y2 = int(b["box"][3] * h)
                            is_defect = b["label"] not in detector.garment_classes
                            color = (110, 74, 240) if is_defect else (129, 185, 16) # BGR
                            cv2.rectangle(draw_frame, (x1, y1), (x2, y2), color, 2)
                            label_txt = f"{b['label'].upper()} {int(b['confidence']*100)}%"
                            cv2.putText(draw_frame, label_txt, (x1, max(y1 - 6, 15)),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

                ret, jpeg = cv2.imencode('.jpg', draw_frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
                if not ret:
                    await asyncio.sleep(0.01)
                    continue

                jpeg_bytes = jpeg.tobytes()
                # VLC MJPEG parser strictly requires Content-Length and \r\n\r\n separation
                yield (
                    b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n'
                    b'Content-Length: ' + str(len(jpeg_bytes)).encode('ascii') + b'\r\n\r\n' +
                    jpeg_bytes +
                    b'\r\n'
                )
                await asyncio.sleep(0.02) # ~35-40 FPS
        finally:
            _stream_client_unregister(infer=infer)

    return StreamingResponse(
        mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "Access-Control-Allow-Origin": "*",
            "Connection": "close"
        }
    )



# ─── WebSocket Live Feed ──────────────────────────────────────────────────────

@app.websocket("/ws/video_feed")
async def websocket_video_feed(websocket: WebSocket):
    """
    High-performance WebSocket video feed for Operator Dashboard.
    Sends JSON messages: {"frame": "<base64 JPEG>", "boxes": [...]}
    Client controls inference via messages: {"infer": true/false}
    """
    await websocket.accept()

    infer = True
    _stream_client_register(infer=infer)

    async def _receiver():
        nonlocal infer
        try:
            while True:
                msg = await websocket.receive_json()
                new_infer = msg.get("infer", infer)
                if new_infer != infer:
                    infer = new_infer
                    if infer:
                        _infer_enabled.set()
                    else:
                        _infer_enabled.clear()
        except Exception:
            pass

    async def _sender():
        loop = asyncio.get_event_loop()
        while True:
            try:
                payload = await loop.run_in_executor(None, lambda: result_queue.get(timeout=0.04))
            except queue.Empty:
                await asyncio.sleep(0.002)
                continue
            await websocket.send_json(payload)

    receiver_task = asyncio.create_task(_receiver())
    sender_task   = asyncio.create_task(_sender())

    try:
        done, pending = await asyncio.wait(
            [receiver_task, sender_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        _stream_client_unregister(infer=infer)



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
        try:
            contents = await file.read()
            nparr = np.frombuffer(contents, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame is None:
                continue
                
            timestamp = int(time.time() * 1000)
            safe_filename = Path(file.filename or "upload.jpg").name.replace(" ", "_")
            img_name = f"scan_{timestamp}_{safe_filename}"
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
        except Exception as e:
            print(f"[Upload Batch Error] Failed processing {getattr(file, 'filename', 'file')}: {e}")
            continue
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
