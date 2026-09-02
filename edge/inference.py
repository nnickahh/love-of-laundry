import os
import cv2
import threading
import collections
import numpy as np
from pathlib import Path

try:
    import onnxruntime as ort
    HAS_ORT = True
except ImportError:
    HAS_ORT = False

try:
    from hailo_platform import (
        VDevice, HEF, ConfigureParams, InputVStreamParams, OutputVStreamParams,
        InferVStreams, HailoStreamInterface
    )
    HAS_HAILO = True
except ImportError:
    HAS_HAILO = False

# Default classes from trained garment & defect detection dataset
DEFAULT_CLASSES = [
    "shirt", "jacket", "jeans", "underwear", "dress",
    "hole", "tear", "stain", "broken_button", "color_defect",
    "foreign_yarn", "button_hike", "swing_error", "shorts", "skirt"
]

def letterbox(img, new_shape=(640, 640), color=(114, 114, 114)):
    """Resizes and pads image while strictly maintaining aspect ratio (crucial for accurate YOLO defect detection)."""
    h, w = img.shape[:2]
    r = min(new_shape[0] / h, new_shape[1] / w)
    new_unpad = int(round(w * r)), int(round(h * r))
    dw, dh = new_shape[1] - new_unpad[0], new_shape[0] - new_unpad[1]
    dw, dh = dw / 2.0, dh / 2.0
    if (w, h) != new_unpad:
        img = cv2.resize(img, new_unpad, interpolation=cv2.INTER_LINEAR)
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    img = cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    return img, r, (dw, dh)

def unletterbox_box(norm_box, orig_shape, ratio, pad, imgsz=640):
    """Maps letterboxed blob coordinates back to original frame dimensions."""
    h, w = orig_shape
    dw, dh = pad
    bx1 = norm_box[0] * imgsz if norm_box[0] <= 1.0 else norm_box[0]
    by1 = norm_box[1] * imgsz if norm_box[1] <= 1.0 else norm_box[1]
    bx2 = norm_box[2] * imgsz if norm_box[2] <= 1.0 else norm_box[2]
    by2 = norm_box[3] * imgsz if norm_box[3] <= 1.0 else norm_box[3]

    x1 = max(0.0, min(1.0, float((bx1 - dw) / (w * ratio))))
    y1 = max(0.0, min(1.0, float((by1 - dh) / (h * ratio))))
    x2 = max(0.0, min(1.0, float((bx2 - dw) / (w * ratio))))
    y2 = max(0.0, min(1.0, float((by2 - dh) / (h * ratio))))
    return [x1, y1, x2, y2]

class GarmentDetector:
    """Wraps YOLO model loading and inference logic with dual OpenCV DNN, ONNXRuntime, and Hailo AI HAT+ NPU support."""
    def __init__(self, model_path=None):
        if model_path is None:
            # Check env var first
            env_path = os.environ.get("MODEL_PATH")
            if env_path and Path(env_path).exists():
                model_path = env_path
            else:
                # Fallback pathing order (prefers deepfashion_phase2 50-epoch converged weights)
                paths = [
                    "runs/detect/deepfashion_phase2/weights/best.hef",
                    "runs/detect/deepfashion_phase2/weights/best.onnx",
                    "runs/detect/deepfashion_phase2/weights/best.pt",
                    "runs/detect/garment_inspector_v2/weights/best.hef",
                    "best.hef",
                    "runs/detect/garment_inspector_v2/weights/best.onnx",
                    "best.onnx",
                    "runs/detect/garment_inspector_v2/weights/best.pt",
                    "runs/detect/garment_inspector_v1/weights/best.pt",
                    "runs/detect/garment_inspector/weights/best.pt",
                    "best.pt",
                    "yolo26s.pt"
                ]
                for p in paths:
                    if Path(p).exists():
                        model_path = p
                        break
                if model_path is None:
                    model_path = "runs/detect/deepfashion_phase2/weights/best.onnx"
                    
        self.model_path = str(model_path)
        self.is_hef = self.model_path.endswith(".hef")
        self.is_onnx = self.model_path.endswith(".onnx")
        if "deepfashion" in self.model_path.lower():
            self.class_names = ['t-shirt', 'blouse', 'shirt', 'sweater', 'shorts', 'skirt', 'pants', 'jacket', 'winter jacket']
        else:
            self.class_names = DEFAULT_CLASSES
        self.clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        self.lock = threading.Lock()
        
        # Temporal smoothing buffer to prevent label jumping/jitter across frames
        self._garment_history = collections.deque(maxlen=7)
        self._history_lock = threading.Lock()
        
        # Identify which classes are considered defects
        self.defect_classes = {"hole", "tear", "stain", "broken_button", "color_defect", "foreign_yarn", "button_hike", "swing_error"}
        self.garment_aliases = {
            "shirt": "shirt",
            "t_shirt": "shirt",
            "tshirt": "shirt",
            "polo": "shirt",
            "school_uniform": "shirt",
            "uniform": "shirt",
            "uniform_shirt": "shirt",
            "school_uniform_shirt": "shirt",
            "blouse": "blouse",
            "top": "top",
            "tops": "top",
            "kurti": "kurti",
            "dress": "dress",
            "dresses": "dress",
            "gown": "gown",
            "evening_dress": "gown",
            "evening dress": "gown",
            "saree": "saree",
            "lehenga": "lehenga",
            "skirt": "skirt",
            "skirts": "skirt",
            "pants": "pants",
            "trousers": "pants",
            "trouser": "pants",
            "long_pants": "pants",
            "slacks": "pants",
            "school_uniform_pants": "pants",
            "palazzo": "pants",
            "jeans": "pants",
            "leggings": "leggings",
            "shorts": "shorts",
            "jumpsuit": "jumpsuit",
            "tracksuit": "tracksuit",
            "suit": "suit",
            "cardigan": "cardigan",
            "jacket": "jacket",
            "jackets": "jacket",
            "blazer": "jacket",
            "coat": "coat",
            "coats": "coat",
            "sweater": "sweater",
            "sweatshirt": "sweater",
            "hoodie": "jacket",
            "vest": "vest",
            "vests": "vest",
            "underwear": "shorts",
            "briefs": "shorts",
            "underpants": "shorts",
            "boxers": "shorts",
            "boxer_shorts": "shorts",
        }
        self.garment_classes = set(self.garment_aliases.values())

        if self.is_hef:
            self.hef = None
            self.vdevice = None
            if HAS_HAILO:
                try:
                    print(f"Loading Hailo AI HAT+ NPU Engine from: {self.model_path} (Hailo-8 / Hailo-8L)")
                    self.hef = HEF(self.model_path)
                    self.vdevice = VDevice()
                    configure_params = ConfigureParams.create_from_hef(self.hef, interface=HailoStreamInterface.PCIe)
                    self.network_group = self.vdevice.configure(self.hef, configure_params)[0]
                    self.network_group_params = self.network_group.create_params()
                    self.input_vstream_info = self.hef.get_input_vstream_infos()[0]
                    self.output_vstream_info = self.hef.get_output_vstream_infos()[0]
                    self.input_vstreams_params = InputVStreamParams.make_from_network_group(self.network_group, quantized=False, format_type=np.float32)
                    self.output_vstreams_params = OutputVStreamParams.make_from_network_group(self.network_group, quantized=False, format_type=np.float32)
                    self.device = "hailo_npu"
                except Exception as e:
                    print(f"Hailo initialization failed ({e}), falling back to ONNX/CPU")
                    self.is_hef = False
                    self.is_onnx = True
            else:
                print("HailoRT platform not installed on host. Falling back to ONNX/CPU")
                self.is_hef = False
                self.is_onnx = True

        self.model_imgsz = 640
        if self.is_onnx:
            self.ort_session = None
            self.ort_input_name = None
            if HAS_ORT:
                try:
                    opts = ort.SessionOptions()
                    # Limit to 2 threads on Pi/embedded to prevent 100% CPU lockup & voltage drop
                    opts.intra_op_num_threads = min(2, os.cpu_count() or 2)
                    opts.inter_op_num_threads = 1
                    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
                    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                    self.ort_session = ort.InferenceSession(self.model_path, opts)
                    input_meta = self.ort_session.get_inputs()[0]
                    self.ort_input_name = input_meta.name
                    shape = input_meta.shape
                    if len(shape) == 4 and isinstance(shape[2], int) and shape[2] > 0:
                        self.model_imgsz = int(shape[2])
                    print(f"Loading ONNXRuntime Engine from: {self.model_path} (imgsz={self.model_imgsz}, threads={opts.intra_op_num_threads})")
                except Exception as e:
                    print(f"ONNXRuntime init failed ({e}), falling back to OpenCV DNN")
                    self.ort_session = None

            if self.ort_session is None:
                print(f"Loading OpenCV DNN ONNX Engine from: {self.model_path} (Lightweight CPU mode)")
                cv2.setNumThreads(2)
                self.net = cv2.dnn.readNetFromONNX(self.model_path)
            else:
                self.net = None

            self.model = None
            self.device = "cpu"
        elif not self.is_hef:
            # Lazy import ultralytics only if .pt weights are used
            try:
                import torch
                from ultralytics import YOLO
                if os.environ.get("DEVICE"):
                    self.device = os.environ.get("DEVICE")
                elif os.environ.get("USE_GPU") == "0":
                    self.device = "cpu"
                else:
                    self.device = 0 if torch.cuda.is_available() else "cpu"
                print(f"Loading YOLO detector from: {self.model_path} (Device: {self.device})")
                self.model = YOLO(self.model_path)
            except ImportError:
                raise RuntimeError(
                    f"Loading '{self.model_path}' requires ultralytics/torch. "
                    "Use the ONNX model 'best.onnx' for fast CPU inference without PyTorch."
                )

    def _enhance_frame(self, frame: np.ndarray) -> np.ndarray:
        """Applies gentle adaptive histogram equalization to improve contrast in difficult lighting."""
        try:
            lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            l_eq = self.clahe.apply(l)
            merged = cv2.merge((l_eq, a, b))
            return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)
        except Exception:
            return frame

    def _refine_garment_label(self, cls_name: str, score: float, norm_box: list, orig_w: int = 640, orig_h: int = 480) -> tuple:
        """
        Accurately differentiates:
        - SHIRT / T-SHIRT: Upper body garments (tops, polos, tshirts, uniforms)
        - JACKET: Outerwear, hoodies, blazers, coats
        - PANTS: Long bottoms (jeans, slacks, long trousers)
        - SHORTS: Lower body compact bottoms (located in lower half of frame)
        - DRESS / SKIRT: Dresses and skirts
        """
        x1, y1, x2, y2 = norm_box
        w_px = max(1.0, (x2 - x1) * orig_w)
        h_px = max(1.0, (y2 - y1) * orig_h)
        aspect_ratio = h_px / w_px
        h_norm = y2 - y1

        c = cls_name.lower().strip().replace(' ', '_').replace('-', '_')

        # 1. JACKET: If jacket/coat is detected, prioritize JACKET
        if c in ['jacket', 'coat', 'winter_jacket', 'hoodie', 'blazer']:
            return 'jacket', score

        # 2. TSHIRT / SHIRTS
        if c in ['shirt', 't_shirt', 'tshirt', 'polo', 'uniform', 'uniform_shirt', 'school_uniform', 'long_shirt', 'long_sleeve', 'blouse', 'top']:
            return 'shirt', score

        # 3. PANTS vs SHORTS
        if c in ['jeans', 'pants', 'trousers', 'slacks', 'long_pants']:
            if aspect_ratio < 1.05 and h_norm < 0.45 and y1 > 0.35:
                return 'shorts', score
            return 'pants', score

        if c in ['shorts', 'short_pants', 'underwear', 'briefs', 'underpants', 'boxers']:
            # If the box starts in upper frame or covers upper torso/chest (y1 < 0.35), it's a shirt
            if y1 < 0.35:
                return 'shirt', score
            # If the box is long vertically, it's pants
            if aspect_ratio >= 1.15 and h_norm >= 0.50:
                return 'pants', score
            return 'shorts', score

        if c in ['dress', 'gown']:
            if y1 < 0.25 and h_norm < 0.55:
                return 'shirt', score
            return 'dress', score

        if c in ['skirt', 'skirts']:
            if y1 < 0.30 and h_norm < 0.50:
                return 'shirt', score
            return 'skirt', score

        return c, score

    def _is_face_region(self, norm_box: list) -> bool:
        """
        Returns True if the bounding box represents an isolated head/face rather than a garment.
        A face is located in the upper frame (y1 < 0.20, y2 < 0.42), is compact (w < 0.40, h < 0.38),
        and does not span the torso/shoulders.
        """
        x1, y1, x2, y2 = norm_box
        w_norm = max(0.0, x2 - x1)
        h_norm = max(0.0, y2 - y1)
        box_area = w_norm * h_norm

        if y1 <= 0.22 and y2 <= 0.44 and w_norm <= 0.42 and h_norm <= 0.38 and box_area <= 0.14:
            return True
        return False

    def _is_background_clutter(self, norm_box: list, score: float = 1.0) -> bool:
        """
        Returns True if a bounding box is background clutter rather than a garment:
        - Extremely sliver-like boxes (slits/lines on walls/floors)
        - Boxes too small (< 3.0% of frame)
        """
        x1, y1, x2, y2 = norm_box
        w_norm = max(0.0, x2 - x1)
        h_norm = max(0.0, y2 - y1)
        box_area = w_norm * h_norm

        # Reject full-screen low-confidence background artifacts
        if w_norm >= 0.98 and h_norm >= 0.98 and score < 0.40:
            return True
        # Reject thin sliver artifacts
        if w_norm < 0.10 or h_norm < 0.10:
            return True
        # Reject tiny background noise (< 3.0% of frame)
        if box_area < 0.030:
            return True
        return False

    def _is_box_inside(self, inner_box: list, outer_box: list, tolerance: float = 0.08) -> bool:
        """Returns True if inner_box (e.g. defect) is located inside or overlapping outer_box (garment)."""
        ix1, iy1, ix2, iy2 = inner_box
        ox1, oy1, ox2, oy2 = outer_box
        icx = (ix1 + ix2) / 2.0
        icy = (iy1 + iy2) / 2.0
        return (ox1 - tolerance <= icx <= ox2 + tolerance) and (oy1 - tolerance <= icy <= oy2 + tolerance)

    def _predict_onnx(self, frame, conf=0.15, iou=0.45, imgsz=640) -> dict:
        orig_h, orig_w = frame.shape[:2]
        target_imgsz = getattr(self, "model_imgsz", 640)
        
        # Calibrated garment threshold: sensitive to real clothing while rejecting background noise
        garment_conf_thresh = max(0.10, conf if conf is not None else 0.15)
        defect_conf_thresh = 0.25

        letterbox_img, ratio, (dw, dh) = letterbox(frame, new_shape=(target_imgsz, target_imgsz))
        blob = cv2.dnn.blobFromImage(letterbox_img, 1.0 / 255.0, (target_imgsz, target_imgsz), swapRB=True, crop=False)

        # High-Speed Single-Pass Execution (ONNXRuntime with fallback to cv2.dnn)
        if self.ort_session is not None:
            outputs = self.ort_session.run(None, {self.ort_input_name: blob})[0]
        else:
            with self.lock:
                self.net.setInput(blob)
                outputs = self.net.forward()
        
        cand_boxes = []
        cand_scores = []
        cand_cls_names = []
        cand_norm_boxes = []

        if len(outputs.shape) == 3 and outputs.shape[2] == 6:
            detections = outputs[0]
            # Check if any jacket detection is present in the frame
            has_jacket_feature = any(
                int(det[5]) < len(self.class_names) and self.class_names[int(det[5])] == 'jacket' and float(det[4]) >= 0.010
                for det in detections
            )

            for det in detections:
                score = float(det[4])
                cls_id = int(det[5])
                cls_name = self.class_names[cls_id] if cls_id < len(self.class_names) else str(cls_id)

                is_defect_cls = cls_name in self.defect_classes
                thresh = defect_conf_thresh if is_defect_cls else garment_conf_thresh
                if score < thresh:
                    continue

                # Unletterbox coordinates back to original frame
                norm_b = unletterbox_box(det[:4], (orig_h, orig_w), ratio, (dw, dh), imgsz=target_imgsz)
                x1_norm, y1_norm, x2_norm, y2_norm = norm_b
                w_norm = x2_norm - x1_norm
                h_norm = y2_norm - y1_norm

                if is_defect_cls:
                    # Ignore defect candidates located directly on face or tiny noise
                    if self._is_face_region(norm_b) or (w_norm < 0.02 or h_norm < 0.02):
                        continue
                else:
                    # Filter out head/face detections and background clutter
                    if self._is_face_region(norm_b) or self._is_background_clutter(norm_b, score=score):
                        continue

                # Disambiguate garment labels
                weight = 1.0
                if not is_defect_cls:
                    cls_name, score = self._refine_garment_label(cls_name, score, norm_b, orig_w=orig_w, orig_h=orig_h)
                    if cls_name == 'shirt':
                        weight = 1.6
                    elif cls_name == 'jacket':
                        weight = 1.5
                    elif cls_name == 'pants':
                        weight = 1.3
                    elif cls_name in ['shorts', 'skirt']:
                        weight = 1.0

                x1_px = int(x1_norm * orig_w)
                y1_px = int(y1_norm * orig_h)
                w_px = max(1, int(w_norm * orig_w))
                h_px = max(1, int(h_norm * orig_h))

                cand_boxes.append([x1_px, y1_px, w_px, h_px])
                cand_scores.append(score * weight)
                cand_cls_names.append(cls_name)
                cand_norm_boxes.append(norm_b)

        clean_boxes = []
        garment_candidates = []
        raw_defects = []
        detected_garment = "unknown"
        status = "clean"

        # Apply Non-Maximum Suppression to deduplicate overlapping boxes
        if cand_boxes:
            indices = cv2.dnn.NMSBoxes(cand_boxes, cand_scores, score_threshold=garment_conf_thresh, nms_threshold=iou)
            if len(indices) > 0:
                for idx in (indices.flatten() if hasattr(indices, 'flatten') else indices):
                    i = int(idx)
                    cls_name = cand_cls_names[i]
                    score = cand_scores[i]
                    norm_box = cand_norm_boxes[i]
                    
                    x1, y1, x2, y2 = norm_box
                    box_area = max(0.0, x2 - x1) * max(0.0, y2 - y1)

                    normalized_name = self.garment_aliases.get(
                        cls_name.lower().strip().replace(' ', '_').replace('-', '_'),
                        cls_name.lower().strip()
                    )

                    if normalized_name in self.garment_classes:
                        # Genuine calibrated display confidence (uninflated)
                        display_conf = round(min(0.99, max(0.01, score)), 2)

                        garment_candidates.append({
                            "label": normalized_name,
                            "confidence": display_conf,
                            "raw_score": score,
                            "box": norm_box,
                            "area": box_area
                        })
                    elif cls_name in self.defect_classes:
                        if score >= defect_conf_thresh:
                            raw_defects.append({
                                "label": cls_name,
                                "confidence": round(score, 2),
                                "box": norm_box
                            })

        # Include valid garment candidates in clean_boxes (sorted with primary foremost)
        if garment_candidates:
            def _candidate_rank(item):
                lbl = item["label"]
                boost = 1.8 if lbl == "shirt" else (1.6 if lbl == "jacket" else (1.4 if lbl == "pants" else 1.0))
                return item["raw_score"] * boost * (item["area"] ** 0.5)

            garment_candidates.sort(key=_candidate_rank, reverse=True)
            detected_garment = garment_candidates[0]["label"]

            for g in garment_candidates:
                clean_boxes.append({
                    "label": g["label"],
                    "confidence": g["confidence"],
                    "box": g["box"]
                })

            # Only display defect boxes if they are located inside a detected garment
            garment_boxes = [g["box"] for g in garment_candidates]
            defects = []
            for d in raw_defects:
                if any(self._is_box_inside(d["box"], gb) for gb in garment_boxes):
                    defects.append(d)
                    clean_boxes.append(d)
                    status = "defective"
        else:
            defects = []

        # Temporal smoothing for live overlay (smooths out 1-frame jitter while transitioning cleanly when clothing changes)
        if clean_boxes and clean_boxes[0]["label"] in self.garment_classes:
            primary_label = clean_boxes[0]["label"]
            with self._history_lock:
                if len(self._garment_history) > 0 and self._garment_history[-1] != primary_label:
                    if list(self._garment_history).count(primary_label) >= 2 or len(self._garment_history) <= 3:
                        self._garment_history.clear()
                self._garment_history.append(primary_label)
                counts = collections.Counter(self._garment_history)
                detected_garment = counts.most_common(1)[0][0]
                clean_boxes[0]["label"] = detected_garment
        else:
            with self._history_lock:
                self._garment_history.clear()

        return {
            "garment_type": detected_garment,
            "status": status,
            "defects": defects,
            "boxes": clean_boxes
        }

    def _predict_hailo(self, frame, conf=0.15, iou=0.45, imgsz=640) -> dict:
        """Executes ultra-low latency NPU hardware accelerated inference via HailoRT on Raspberry Pi AI HAT+."""
        orig_h, orig_w = frame.shape[:2]
        garment_conf_thresh = max(0.10, conf if conf is not None else 0.15)
        defect_conf_thresh = 0.25

        letterbox_img, ratio, (dw, dh) = letterbox(frame, new_shape=(imgsz, imgsz))
        norm_img = (letterbox_img.astype(np.float32) / 255.0)[np.newaxis, ...]

        with self.lock:
            with self.network_group.activate(self.network_group_params):
                with InferVStreams(self.network_group, self.input_vstreams_params, self.output_vstreams_params) as infer_pipeline:
                    input_data = {self.input_vstream_info.name: norm_img}
                    results = infer_pipeline.infer(input_data)
                    outputs = results[self.output_vstream_info.name]

        cand_boxes = []
        cand_scores = []
        cand_cls_names = []
        cand_norm_boxes = []

        if len(outputs.shape) == 3 and outputs.shape[2] == 6:
            detections = outputs[0]
            for det in detections:
                score = float(det[4])
                cls_id = int(det[5])
                cls_name = self.class_names[cls_id] if cls_id < len(self.class_names) else str(cls_id)

                is_defect_cls = cls_name in self.defect_classes
                thresh = defect_conf_thresh if is_defect_cls else garment_conf_thresh
                if score < thresh:
                    continue

                norm_b = unletterbox_box(det[:4], (orig_h, orig_w), ratio, (dw, dh), imgsz=imgsz)
                x1_norm, y1_norm, x2_norm, y2_norm = norm_b
                w_norm = x2_norm - x1_norm
                h_norm = y2_norm - y1_norm
                box_area = w_norm * h_norm

                if is_defect_cls:
                    if self._is_face_region(norm_b) or (w_norm < 0.02 or h_norm < 0.02):
                        continue
                else:
                    if self._is_face_region(norm_b) or self._is_background_clutter(norm_b, score=score):
                        continue

                weight = 1.0
                if not is_defect_cls:
                    cls_name, score = self._refine_garment_label(cls_name, score, norm_b, orig_w=orig_w, orig_h=orig_h)
                    if cls_name == 'shirt':
                        weight = 1.6
                    elif cls_name == 'jacket':
                        weight = 1.5
                    elif cls_name == 'pants':
                        weight = 1.3
                    elif cls_name in ['shorts', 'skirt']:
                        weight = 1.0

                x1_px = int(x1_norm * orig_w)
                y1_px = int(y1_norm * orig_h)
                w_px = max(1, int(w_norm * orig_w))
                h_px = max(1, int(h_norm * orig_h))

                cand_boxes.append([x1_px, y1_px, w_px, h_px])
                cand_scores.append(score * weight)
                cand_cls_names.append(cls_name)
                cand_norm_boxes.append(norm_b)

        clean_boxes = []
        garment_candidates = []
        raw_defects = []
        detected_garment = "unknown"
        status = "clean"

        if cand_boxes:
            indices = cv2.dnn.NMSBoxes(cand_boxes, cand_scores, score_threshold=garment_conf_thresh, nms_threshold=iou)
            if len(indices) > 0:
                for idx in (indices.flatten() if hasattr(indices, 'flatten') else indices):
                    i = int(idx)
                    cls_name = cand_cls_names[i]
                    score = cand_scores[i]
                    norm_box = cand_norm_boxes[i]
                    x1, y1, x2, y2 = norm_box
                    box_area = max(0.0, x2 - x1) * max(0.0, y2 - y1)

                    normalized_name = self.garment_aliases.get(
                        cls_name.lower().strip().replace(' ', '_').replace('-', '_'),
                        cls_name.lower().strip()
                    )

                    if normalized_name in self.garment_classes:
                        display_conf = round(min(0.99, max(0.01, score)), 2)
                        garment_candidates.append({
                            "label": normalized_name,
                            "confidence": display_conf,
                            "raw_score": score,
                            "box": norm_box,
                            "area": box_area
                        })
                    elif cls_name in self.defect_classes:
                        if score >= defect_conf_thresh:
                            raw_defects.append({
                                "label": cls_name,
                                "confidence": round(score, 2),
                                "box": norm_box
                            })

        if garment_candidates:
            def _candidate_rank(item):
                lbl = item["label"]
                boost = 1.8 if lbl == "shirt" else (1.6 if lbl == "jacket" else (1.4 if lbl == "pants" else 1.0))
                return item["raw_score"] * boost * (item["area"] ** 0.5)

            garment_candidates.sort(key=_candidate_rank, reverse=True)
            detected_garment = garment_candidates[0]["label"]
            for g in garment_candidates:
                clean_boxes.append({
                    "label": g["label"],
                    "confidence": g["confidence"],
                    "box": g["box"]
                })

            # Only display defect boxes if they are located inside a detected garment
            garment_boxes = [g["box"] for g in garment_candidates]
            defects = []
            for d in raw_defects:
                if any(self._is_box_inside(d["box"], gb) for gb in garment_boxes):
                    defects.append(d)
                    clean_boxes.append(d)
                    status = "defective"
        else:
            defects = []

        return {
            "garment_type": detected_garment,
            "status": status,
            "defects": defects,
            "boxes": clean_boxes
        }

    def predict_frame(self, frame, conf=0.05, iou=0.45, imgsz=640) -> dict:
        """Runs bounding box detection on a single frame with aspect-ratio preserving letterbox."""
        if getattr(self, "is_hef", False) and HAS_HAILO and getattr(self, "network_group", None):
            try:
                return self._predict_hailo(frame, conf=conf, iou=iou, imgsz=imgsz)
            except Exception as e:
                print(f"[HailoRT Error] {e}, falling back to ONNX")
        if self.is_onnx:
            return self._predict_onnx(frame, conf=conf, iou=iou, imgsz=imgsz)
            
        results = self.model.predict(
            source=frame,
            conf=max(0.04, conf if conf is not None else 0.08),
            iou=iou,
            imgsz=imgsz,
            verbose=False,
            device=self.device
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
            
            if cls_name == "underwear" and confidence < 0.20:
                continue
                
            xyxy = box.xyxy[0].tolist()
            norm_box = [
                max(0.0, min(1.0, xyxy[0] / w)),
                max(0.0, min(1.0, xyxy[1] / h)),
                max(0.0, min(1.0, xyxy[2] / w)),
                max(0.0, min(1.0, xyxy[3] / h))
            ]

            if self._is_face_region(norm_box):
                continue

            is_defect_cls = cls_name in self.defect_classes
            if not is_defect_cls:
                cls_name, confidence = self._refine_garment_label(cls_name, confidence, norm_box)
            
            disp_conf = round(min(0.99, max(0.01, confidence)), 2)

            all_boxes.append({
                "label": cls_name,
                "confidence": disp_conf,
                "box": norm_box
            })
            
            normalized_name = self.garment_aliases.get(cls_name.lower().strip().replace(' ', '_').replace('-', '_'), cls_name.lower().strip())
            if normalized_name in self.garment_classes:
                if confidence > max_garment_conf:
                    detected_garment = normalized_name
                    max_garment_conf = confidence
            elif cls_name in self.defect_classes:
                status = "defective"
                defects.append({
                    "label": cls_name,
                    "confidence": round(confidence, 2),
                    "box": norm_box
                })
                
        return {
            "garment_type": detected_garment,
            "status": status,
            "defects": defects,
            "boxes": all_boxes
        }
