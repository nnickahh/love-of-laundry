import sqlite3
import json
from datetime import datetime

DB_PATH = "central_cloud.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create devices table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS devices (
            device_id TEXT PRIMARY KEY,
            name TEXT,
            location TEXT,
            last_active TEXT
        )
    """)
    
    # Create garments table (central record)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS garments (
            garment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            local_device_garment_id INTEGER NOT NULL,
            garment_type TEXT NOT NULL,
            status TEXT NOT NULL,
            image_url TEXT NOT NULL,
            created_at TEXT NOT NULL,
            synced_at TEXT NOT NULL,
            meta_angle TEXT,
            FOREIGN KEY (device_id) REFERENCES devices (device_id)
        )
    """)
    
    # Create defects table (central record)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS defects (
            defect_id INTEGER PRIMARY KEY AUTOINCREMENT,
            garment_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            confidence REAL NOT NULL,
            box TEXT NOT NULL,
            FOREIGN KEY (garment_id) REFERENCES garments (garment_id) ON DELETE CASCADE
        )
    """)
    
    conn.commit()
    conn.close()

def register_device(device_id: str, name: str = None, location: str = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    
    # Insert or update
    cursor.execute("""
        INSERT INTO devices (device_id, name, location, last_active)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(device_id) DO UPDATE SET
            last_active = excluded.last_active,
            name = COALESCE(name, excluded.name),
            location = COALESCE(location, excluded.location)
    """, (device_id, name or device_id, location or "Unknown Location", now))
    
    conn.commit()
    conn.close()

def add_synced_garment(device_id: str, local_id: int, garment_type: str, status: str, image_url: str, created_at: str, meta_angle: dict = None) -> int:
    # Auto register device on upload
    register_device(device_id)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check for existing record to prevent duplicates (delta updates)
    cursor.execute("""
        SELECT garment_id FROM garments 
        WHERE device_id = ? AND local_device_garment_id = ?
    """, (device_id, local_id))
    existing = cursor.fetchone()
    if existing:
        conn.close()
        return existing[0]
        
    synced_at = datetime.now().isoformat()
    meta_angle_str = json.dumps(meta_angle) if meta_angle else None
    
    cursor.execute("""
        INSERT INTO garments (device_id, local_device_garment_id, garment_type, status, image_url, created_at, synced_at, meta_angle)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (device_id, local_id, garment_type, status, image_url, created_at, synced_at, meta_angle_str))
    
    garment_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return garment_id

def add_synced_defect(garment_id: int, label: str, confidence: float, box: list):
    conn = get_db_connection()
    cursor = conn.cursor()
    box_str = json.dumps(box)
    
    cursor.execute("""
        INSERT INTO defects (garment_id, label, confidence, box)
        VALUES (?, ?, ?, ?)
    """, (garment_id, label, confidence, box_str))
    
    conn.commit()
    conn.close()

def get_all_garments(limit=50) -> list:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT g.*, d.name as device_name, d.location as device_location
        FROM garments g
        LEFT JOIN devices d ON g.device_id = d.device_id
        ORDER BY g.garment_id DESC
        LIMIT ?
    """, (limit,))
    
    rows = cursor.fetchall()
    garments = []
    
    for r in rows:
        g_id = r["garment_id"]
        cursor.execute("SELECT * FROM defects WHERE garment_id = ?", (g_id,))
        defects = [{
            "label": d["label"],
            "confidence": d["confidence"],
            "box": json.loads(d["box"])
        } for d in cursor.fetchall()]
        
        garments.append({
            "id": g_id,
            "garment_id": g_id,
            "device_id": r["device_id"],
            "device_name": r["device_name"],
            "device_location": r["device_location"],
            "local_id": r["local_device_garment_id"],
            "garment_type": r["garment_type"],
            "status": r["status"],
            "image_url": r["image_url"],
            "created_at": r["created_at"],
            "synced_at": r["synced_at"],
            "meta_angle": json.loads(r["meta_angle"]) if r["meta_angle"] else None,
            "defects": defects
        })
        
    conn.close()
    return garments

def delete_garments(garment_ids: list) -> list:
    if not garment_ids:
        return []
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get image URLs first
    placeholders = ",".join("?" for _ in garment_ids)
    cursor.execute(f"SELECT image_url FROM garments WHERE garment_id IN ({placeholders})", garment_ids)
    image_urls = [r["image_url"] for r in cursor.fetchall()]
    
    # Delete associated defects
    cursor.execute(f"DELETE FROM defects WHERE garment_id IN ({placeholders})", garment_ids)
    
    # Delete garments
    cursor.execute(f"DELETE FROM garments WHERE garment_id IN ({placeholders})", garment_ids)
    
    conn.commit()
    conn.close()
    
    return image_urls

def get_reports() -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Totals
    cursor.execute("SELECT COUNT(*) FROM garments")
    total_scans = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM garments WHERE status = 'defective'")
    defective_scans = cursor.fetchone()[0]
    
    clean_scans = total_scans - defective_scans
    defect_rate = (defective_scans / total_scans * 100) if total_scans > 0 else 0.0
    
    # Scans per garment type
    cursor.execute("SELECT garment_type, COUNT(*) FROM garments GROUP BY garment_type")
    garment_breakdown = {row[0]: row[1] for row in cursor.fetchall()}
    
    # Scans per defect type
    cursor.execute("SELECT label, COUNT(*) FROM defects GROUP BY label")
    defect_breakdown = {row[0]: row[1] for row in cursor.fetchall()}
    
    # Active devices
    cursor.execute("SELECT device_id, name, location, last_active FROM devices ORDER BY last_active DESC")
    devices = [{
        "device_id": r[0],
        "name": r[1],
        "location": r[2],
        "last_active": r[3]
    } for r in cursor.fetchall()]
    
    conn.close()
    return {
        "total_scans": total_scans,
        "clean_scans": clean_scans,
        "defective_scans": defective_scans,
        "defect_rate_percent": round(defect_rate, 2),
        "garment_breakdown": garment_breakdown,
        "defect_breakdown": defect_breakdown,
        "active_devices": devices
    }

# Initialize DB on import
init_db()
