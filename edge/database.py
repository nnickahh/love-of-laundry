import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = "edge_garments.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create garments table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS garments (
            local_id INTEGER PRIMARY KEY AUTOINCREMENT,
            cloud_id INTEGER,
            garment_type TEXT NOT NULL,
            status TEXT NOT NULL,
            image_path TEXT NOT NULL,
            sync_status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL,
            meta_angle TEXT
        )
    """)
    
    # Create defects table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS defects (
            defect_id INTEGER PRIMARY KEY AUTOINCREMENT,
            local_garment_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            confidence REAL NOT NULL,
            box TEXT NOT NULL,
            FOREIGN KEY (local_garment_id) REFERENCES garments (local_id) ON DELETE CASCADE
        )
    """)
    
    conn.commit()
    conn.close()

def add_garment(garment_type: str, status: str, image_path: str, meta_angle: dict = None) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    created_at = datetime.now().isoformat()
    meta_angle_str = json.dumps(meta_angle) if meta_angle else None
    
    cursor.execute("""
        INSERT INTO garments (garment_type, status, image_path, created_at, meta_angle)
        VALUES (?, ?, ?, ?, ?)
    """, (garment_type, status, image_path, created_at, meta_angle_str))
    
    local_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return local_id

def add_defect(local_garment_id: int, label: str, confidence: float, box: list):
    conn = get_db_connection()
    cursor = conn.cursor()
    box_str = json.dumps(box)
    
    cursor.execute("""
        INSERT INTO defects (local_garment_id, label, confidence, box)
        VALUES (?, ?, ?, ?)
    """, (local_garment_id, label, confidence, box_str))
    
    conn.commit()
    conn.close()

def get_unsynced_garments() -> list:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM garments WHERE sync_status = 'pending'
    """)
    garment_rows = cursor.fetchall()
    
    unsynced = []
    for g in garment_rows:
        g_id = g['local_id']
        cursor.execute("SELECT * FROM defects WHERE local_garment_id = ?", (g_id,))
        defect_rows = cursor.fetchall()
        
        defects = []
        for d in defect_rows:
            defects.append({
                "label": d["label"],
                "confidence": d["confidence"],
                "box": json.loads(d["box"])
            })
            
        unsynced.append({
            "local_id": g_id,
            "garment_type": g["garment_type"],
            "status": g["status"],
            "image_path": g["image_path"],
            "created_at": g["created_at"],
            "meta_angle": json.loads(g["meta_angle"]) if g["meta_angle"] else None,
            "defects": defects
        })
        
    conn.close()
    return unsynced

def mark_as_synced(local_id: int, cloud_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE garments
        SET sync_status = 'synced', cloud_id = ?
        WHERE local_id = ?
    """, (cloud_id, local_id))
    conn.commit()
    conn.close()

def get_stats() -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM garments WHERE sync_status = 'pending'")
    pending = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM garments WHERE sync_status = 'synced'")
    synced = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM garments WHERE status = 'defective'")
    defective = cursor.fetchone()[0]
    
    conn.close()
    return {
        "pending": pending,
        "synced": synced,
        "total": pending + synced,
        "defective": defective
    }

# Initialize DB on import
init_db()
