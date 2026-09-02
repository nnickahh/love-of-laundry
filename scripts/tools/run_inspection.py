"""
run_inspection.py
MVP garment inspection demo.
Loads the trained YOLO26s model and runs bounding-box detection
on a single image, a folder of images, or a live webcam feed.

Usage:
  python run_inspection.py                          # live webcam
  python scripts/tools/run_inspection.py --source assets/test_clothing.png
  python run_inspection.py --source dataset/raw/shirt/
  python run_inspection.py --source video.mp4
"""
import argparse
import os
from pathlib import Path
from ultralytics import YOLO

# Colour map per class (BGR for OpenCV / RGB passed to ultralytics)
CLASS_COLOURS = {
    "shirt"    : (100, 180, 255),
    "jacket"   : (50,  150, 50),
    "jeans"    : (30,   80, 200),
    "underwear": (200, 100, 200),
    "dress"    : (255, 160,  50),
    "hole"     : (255,  50,  50),   # red — defect
    "tear"     : (255, 100,   0),   # orange — defect
    "stain"    : (180,  60, 255),   # purple — defect
}

BEST_MODEL = "runs/detect/garment_inspector_v1/weights/best.pt"


def run(source, conf=0.25, show=True):
    model_path = BEST_MODEL
    if not Path(model_path).exists():
        # Fallback: try last.pt
        last = Path("runs/detect/garment_inspector_v1/weights/last.pt")
        if last.exists():
            model_path = str(last)
        else:
            print(f"ERROR: Trained model not found at {BEST_MODEL}")
            print("Please run train.py first.")
            return

    print(f"Loading model: {model_path}")
    model = YOLO(model_path)

    print(f"Running inspection on: {source}")
    results = model.predict(
        source    = source,
        conf      = conf,
        device    = 0,
        show      = show,       # display results window
        save      = True,       # save annotated images to runs/detect/predict/
        line_width= 2,
        verbose   = True,
    )

    # Print detection summary
    print("\n" + "=" * 60)
    print("Inspection Results:")
    print("=" * 60)
    for r in results:
        path = Path(r.path).name if hasattr(r, "path") else "image"
        if len(r.boxes) == 0:
            print(f"  {path}: No detections")
        else:
            for box in r.boxes:
                cls_id = int(box.cls[0].item())
                cls_name = model.names[cls_id]
                conf_val = box.conf[0].item()
                xyxy = [f"{v:.0f}" for v in box.xyxy[0].tolist()]
                tag = "⚠️  DEFECT" if cls_name in {"hole", "tear", "stain"} else "✓  garment"
                print(f"  {tag}  {cls_name:12}  conf={conf_val:.2f}  box=[{', '.join(xyxy)}]")

    save_dir = model.predictor.save_dir if hasattr(model, "predictor") else "runs/detect/predict"
    print(f"\nAnnotated images saved to: {save_dir}")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Garment Inspection MVP")
    parser.add_argument("--source", default="0",
                        help="Image path, folder, video, or 0 for webcam (default: 0)")
    parser.add_argument("--conf",   type=float, default=0.25,
                        help="Confidence threshold (default: 0.25)")
    parser.add_argument("--no-show", action="store_true",
                        help="Disable display window")
    args = parser.parse_args()

    run(
        source = args.source,
        conf   = args.conf,
        show   = not args.no_show,
    )
