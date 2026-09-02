import os
import json
import shutil
from datetime import datetime
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from typing import List
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pathlib import Path

# Add project root to path for imports
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))

from shared.schemas import SyncPayload
from cloud.database import add_synced_garment, add_synced_defect, get_all_garments, get_reports, delete_garments

UPLOADS_DIR = Path("cloud/uploads")
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Garment Central Cloud Server")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static mounts
app.mount("/uploads", StaticFiles(directory="cloud/uploads"), name="uploads")
if Path("cloud/static").exists():
    app.mount("/static", StaticFiles(directory="cloud/static"), name="static")

# Root route: serve the Cloud operations dashboard
@app.get("/")
def root():
    return FileResponse("cloud/static/dashboard.html")

@app.post("/api/sync")
async def sync_endpoint(
    payload: str = Form(..., description="JSON serialized SyncPayload string"),
    file: UploadFile = File(..., description="Captured garment snapshot")
):
    try:
        # 1. Parse payload JSON string
        payload_data = json.loads(payload)
        sync_data = SyncPayload(**payload_data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid payload format: {e}")
    
    # 2. Save uploaded snapshot
    file_extension = Path(file.filename).suffix
    # Prefix filename with device_id to avoid collisions
    dst_filename = f"{sync_data.device_id}_{file.filename}"
    dst_path = UPLOADS_DIR / dst_filename
    
    try:
        with dst_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save image upload: {e}")
        
    # 3. Save garment scan to central database
    g = sync_data.garment
    
    # Auto-correct edge clock drift (e.g. Raspberry Pi running without NTP / on fake-hwclock)
    now_dt = datetime.now()
    scan_time = g.created_at
    try:
        dt = datetime.fromisoformat(scan_time)
        if abs((now_dt - dt.replace(tzinfo=None)).total_seconds()) > 7200:
            scan_time = now_dt.isoformat()
    except Exception:
        scan_time = now_dt.isoformat()

    cloud_id = add_synced_garment(
        device_id=sync_data.device_id,
        local_id=g.local_id,
        garment_type=g.garment_type,
        status=g.status,
        image_url=f"/uploads/{dst_filename}",
        created_at=scan_time,
        meta_angle=g.meta_angle
    )
    
    # Add defects
    for d in g.defects:
        add_synced_defect(
            garment_id=cloud_id,
            label=d.label,
            confidence=d.confidence,
            box=d.box
        )
        
    print(f"[Cloud API] Sync successful: Device {sync_data.device_id} -> Local ID {g.local_id} registered as Cloud ID {cloud_id}")
    return {"status": "success", "cloud_id": cloud_id}

@app.get("/api/reports")
def reports_endpoint():
    return get_reports()

@app.get("/api/garments")
def garments_endpoint():
    return get_all_garments()

class DeleteGarmentsRequest(BaseModel):
    garment_ids: List[int]

@app.post("/api/garments/delete")
def delete_garments_endpoint(payload: DeleteGarmentsRequest):
    try:
        image_urls = delete_garments(payload.garment_ids)
        deleted_files = 0
        for img_url in image_urls:
            if img_url.startswith("/uploads/"):
                filename = img_url[len("/uploads/"):]
                file_path = UPLOADS_DIR / filename
                if file_path.exists() and file_path.is_file():
                    try:
                        file_path.unlink()
                        deleted_files += 1
                    except Exception as e:
                        print(f"[Cloud API] Error deleting file {file_path}: {e}")
        print(f"[Cloud API] Deleted {len(payload.garment_ids)} database records and {deleted_files} files from disk.")
        return {"status": "success", "deleted_count": len(payload.garment_ids), "deleted_files": deleted_files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Active Learning Mock State ─────────────────────────────────────────────
ACTIVE_LEARNING_TRAINED = False

@app.get("/api/active_learning/status")
def get_active_learning_status():
    global ACTIVE_LEARNING_TRAINED
    return {"trained": ACTIVE_LEARNING_TRAINED}

@app.post("/api/active_learning/retrain")
def post_active_learning_retrain():
    global ACTIVE_LEARNING_TRAINED
    ACTIVE_LEARNING_TRAINED = True
    print("[Cloud Active Learning] Active learning retraining mock triggered. Model upgraded to v1.1.0 (Stain precision: 94.8%)")
    return {"status": "success", "trained": ACTIVE_LEARNING_TRAINED, "version": "v1.1.0"}

@app.post("/api/active_learning/reset")
def post_active_learning_reset():
    global ACTIVE_LEARNING_TRAINED
    ACTIVE_LEARNING_TRAINED = False
    print("[Cloud Active Learning] Active learning status reset. Model reverted to v1.0.0")
    return {"status": "success", "trained": ACTIVE_LEARNING_TRAINED, "version": "v1.0.0"}

