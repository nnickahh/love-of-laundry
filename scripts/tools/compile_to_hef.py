"""
Hailo AI HAT+ (Hailo-8 / Hailo-8L) Model Conversion & Preparation Tool.
Exports the YOLO model to Hailo-compatible ONNX (opset 11), generates INT8 calibration
dataset, creates the Hailo model script (.alls), and invokes the Hailo Dataflow Compiler (DFC).
"""

import os
import sys
import glob
import cv2
import numpy as np
from pathlib import Path

def prepare_hailo_conversion(
    pt_model_path="runs/detect/garment_inspector_v2/weights/best.pt",
    output_dir="runs/detect/garment_inspector_v2/weights",
    target_hw="hailo8l",  # 'hailo8l' for Raspberry Pi AI HAT+ (13 TOPS) or 'hailo8' for AI HAT+ (26 TOPS)
    imgsz=640,
    calib_samples=64
):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print("=" * 65)
    print(" Hailo AI HAT+ (Hailo-8 / Hailo-8L) HEF Compilation Pipeline")
    print(f" Target Hardware: {target_hw.upper()} (Raspberry Pi 5 AI HAT+)")
    print("=" * 65)

    # 1. Export YOLO to ONNX with opset 11 (strict requirement for Hailo DFC)
    hailo_onnx_path = output_path / "best_hailo.onnx"
    print(f"\n[Step 1/4] Exporting {pt_model_path} to Hailo ONNX (opset=11)...")
    try:
        from ultralytics import YOLO
        model = YOLO(pt_model_path)
        exported = model.export(
            format="onnx",
            opset=11,
            imgsz=imgsz,
            dynamic=False,
            simplify=True
        )
        if os.path.exists(exported) and str(exported) != str(hailo_onnx_path):
            import shutil
            shutil.copy2(exported, str(hailo_onnx_path))
        print(f"  -> ONNX export ready: {hailo_onnx_path}")
    except Exception as e:
        print(f"  Export failed: {e}")
        if not hailo_onnx_path.exists():
            print("  Falling back to best.onnx...")
            hailo_onnx_path = output_path / "best.onnx"

    # 2. Build Calibration Dataset for INT8 Quantization
    calib_npy_path = output_path / "calib_data.npy"
    print(f"\n[Step 2/4] Generating INT8 Calibration Dataset ({calib_samples} frames)...")
    
    img_candidates = []
    for pattern in ["dataset/**/*.jpg", "dataset/**/*.png", "assets/*.*", "edge/static/captures/*.*"]:
        img_candidates.extend(glob.glob(pattern, recursive=True))
    
    valid_images = []
    for p in img_candidates:
        if cv2.haveImageReader(p):
            valid_images.append(p)
        if len(valid_images) >= calib_samples:
            break
            
    if not valid_images:
        print("  Warning: No dataset images found. Generating synthetic calibration images.")
        calib_arr = np.random.randint(0, 255, (calib_samples, imgsz, imgsz, 3), dtype=np.uint8)
    else:
        print(f"  Found {len(valid_images)} sample images for calibration.")
        calib_list = []
        for p in valid_images:
            img = cv2.imread(p)
            if img is None: continue
            h, w = img.shape[:2]
            r = min(imgsz / h, imgsz / w)
            nw, nh = int(w * r), int(h * r)
            resized = cv2.resize(img, (nw, nh))
            canvas = np.full((imgsz, imgsz, 3), 114, dtype=np.uint8)
            dx = (imgsz - nw) // 2
            dy = (imgsz - nh) // 2
            canvas[dy:dy+nh, dx:dx+nw] = resized
            calib_list.append(canvas)
            if len(calib_list) >= calib_samples:
                break
        
        while len(calib_list) < calib_samples:
            calib_list.append(calib_list[len(calib_list) % len(calib_list)])
            
        calib_arr = np.array(calib_list, dtype=np.uint8)
        
    np.save(str(calib_npy_path), calib_arr)
    print(f"  -> Calibration data saved: {calib_npy_path} (Shape: {calib_arr.shape})")

    # 3. Generate Hailo Model Script (.alls)
    alls_path = output_path / "garment_inspector.alls"
    print("\n[Step 3/4] Creating Hailo Model Script (.alls)...")
    alls_content = f"""# Hailo Model Script for Garment Inspector YOLO
# Architecture: {target_hw} (Raspberry Pi AI HAT+)
normalization1 = normalization([0.0, 0.0, 0.0], [255.0, 255.0, 255.0])
nms_postprocess(meta_arch=yolov8, engine=hailort)
"""
    with open(alls_path, "w") as f:
        f.write(alls_content)
    print(f"  -> Model script created: {alls_path}")

    # 4. Check for Hailo Dataflow Compiler (DFC)
    hef_output_path = output_path / "best.hef"
    print("\n[Step 4/4] Checking for Hailo Dataflow Compiler (DFC)...")
    
    try:
        from hailo_sdk_client import ClientRunner
        print(f"  Hailo SDK found! Compiling HEF directly for {target_hw}...")
        runner = ClientRunner(hw_arch=target_hw)
        runner.translate_onnx_model(
            str(hailo_onnx_path),
            "garment_inspector",
            start_node_names=["images"],
            end_node_names=None
        )
        runner.load_model_script(str(alls_path))
        runner.optimize(calib_arr)
        hef = runner.compile()
        with open(hef_output_path, "wb") as f:
            f.write(hef)
        print(f"\n SUCCESS: HEF compiled successfully -> {hef_output_path}")
        return str(hef_output_path)
    except ImportError:
        print("  Hailo Dataflow Compiler Python SDK (hailo_sdk_client) is not installed on this host.")
        print("\n" + "=" * 65)
        print(" [OPTION A] Compile with Hailo Docker (Recommended on PC/Linux):")
        print(f"   docker run --rm -v \"{Path('.').resolve()}\":/workspace -w /workspace hailo-ai/hailo-dataflow-compiler \\")
        print(f"     hailomz compile --ckpt {hailo_onnx_path} --calib-path {calib_npy_path} --hw-arch {target_hw} --output-dir {output_dir}")
        print("\n [OPTION B] Use Pre-configured HailoRT Runner:")
        print(f"   The pipeline has exported the optimized ONNX ({hailo_onnx_path}) and calibration set.")
        print(f"   The Edge server automatically supports HailoRT hardware acceleration whenever 'best.hef' is present on the Pi.")
        print("=" * 65)

    return str(hailo_onnx_path)

if __name__ == "__main__":
    prepare_hailo_conversion()
