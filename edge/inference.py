import os
from pathlib import Path
from ultralytics import YOLO

class GarmentDetector:
    """Wraps YOLOv8 model loading and inference logic."""
    def __init__(self, model_path=None):
        if model_path is None:
            # Fallback pathing order
            paths = [
                "runs/detect/garment_inspector_v2/weights/best.pt",
                "runs/detect/garment_inspector_v1/weights/best.pt",
                "runs/detect/garment_inspector/weights/best.pt",
                "yolo26s.pt" # generic pretrained if nothing else is trained yet
            ]
            for p in paths:
                if Path(p).exists():
                    model_path = p
                    break
            if model_path is None:
                model_path = "yolo26s.pt"
                
        print(f"Loading YOLO detector from: {model_path}")
        self.model = YOLO(model_path)
        
        # Identify which classes are considered defects
        self.defect_classes = {"hole", "tear", "stain", "broken_button", "color_defect", "foreign_yarn", "button_hike", "swing_error"}
        self.garment_classes = {"shirt", "jacket", "jeans", "underwear", "dress", "shorts", "skirt"}

    def predict_frame(self, frame, conf=0.25, iou=0.70, imgsz=640) -> dict:
        """Runs bounding box detection on a single frame.
        
        Returns:
            dict: {
                "garment_type": str,      # Detected garment (e.g., 'shirt') or 'unknown'
                "status": str,            # 'clean' or 'defective'
                "defects": list[dict],    # list of defects detected
                "boxes": list[dict]       # all bounding boxes formatted for frontend drawing
            }
        """
        results = self.model.predict(
            source=frame,
            conf=conf,
            iou=iou,
            imgsz=imgsz,
            verbose=False,
            device=0 if os.environ.get("USE_GPU", "1") == "1" else "cpu"
        )
        
        result = results[0]
        detected_garment = "unknown"
        max_garment_conf = 0.0
        
        defects = []
        all_boxes = []
        status = "clean"
        
        h, w = frame.shape[:2]
        
        for box in result.boxes:
            cls_id = int(box.cls[0].item())
            cls_name = self.model.names[cls_id]
            
            confidence = float(box.conf[0].item())
            
            # Suppress low-confidence underwear detections (e.g. false positives on shorts/other garments)
            if cls_name == "underwear" and confidence < 0.65:
                continue
                
            xyxy = box.xyxy[0].tolist() # [x1, y1, x2, y2]
            
            # Normalize box relative to frame size for scaling on UI canvas
            norm_box = [
                xyxy[0] / w,
                xyxy[1] / h,
                xyxy[2] / w,
                xyxy[3] / h
            ]
            
            all_boxes.append({
                "label": cls_name,
                "confidence": confidence,
                "box": norm_box
            })
            
            if cls_name in self.garment_classes:
                # Keep the garment with the highest confidence
                if confidence > max_garment_conf:
                    detected_garment = cls_name
                    max_garment_conf = confidence
            elif cls_name in self.defect_classes:
                status = "defective"
                defects.append({
                    "label": cls_name,
                    "confidence": confidence,
                    "box": norm_box
                })
                
        return {
            "garment_type": detected_garment,
            "status": status,
            "defects": defects,
            "boxes": all_boxes
        }
