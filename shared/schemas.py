from pydantic import BaseModel, Field
from typing import List, Optional

class DefectSchema(BaseModel):
    label: str = Field(..., description="Type of defect (e.g., hole, tear, stain)")
    confidence: float = Field(..., description="Confidence score from 0.0 to 1.0")
    box: List[float] = Field(..., description="Bounding box [x1, y1, x2, y2] relative to image size")

class GarmentScanSchema(BaseModel):
    local_id: int = Field(..., description="Local PK ID on the Edge device")
    garment_type: str = Field(..., description="Type of garment (e.g., shirt, jeans, underwear)")
    status: str = Field(..., description="Status of the garment ('clean' or 'defective')")
    created_at: str = Field(..., description="Timestamp of scanning on the Edge device")
    meta_angle: Optional[dict] = Field(None, description="Metadata containing pan-tilt angles during scan")
    defects: List[DefectSchema] = Field(default=[], description="List of detected defects")

class SyncPayload(BaseModel):
    device_id: str = Field(..., description="Unique ID of the Edge device (e.g., Outlet-1, Van-A)")
    garment: GarmentScanSchema = Field(..., description="The garment scan data to sync")
