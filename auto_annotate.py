"""
auto_annotate.py
Uses YOLOE-26s to auto-generate YOLO-format bounding box labels
for scraped garment and defect images.

For each image it:
  1. Runs inference with class-appropriate prompts
  2. Writes a .txt label file (YOLO format) alongside the image
  3. Skips images with no detections above the confidence threshold
"""
import os
import shutil
from pathlib import Path
from PIL import Image
from ultralytics import YOLOE

# ── Config ──────────────────────────────────────────────────────────────────
RAW_DIR    = "dataset/raw"
LABELLED_DIR = "dataset/labelled"

# Final class list used during training
CLASSES = ["shirt", "jacket", "jeans", "underwear", "dress", "hole", "tear", "stain"]

# YOLOE prompts per raw class — maps raw folder name → (training class id, prompts)
CLASS_CONFIG = {
    "shirt":     (0, ["shirt", "clothing"]),
    "jacket":    (1, ["jacket", "hoodie", "coat", "clothing"]),
    "jeans":     (2, ["jeans", "pants", "trousers", "clothing"]),
    "underwear": (3, ["underwear", "briefs", "socks", "clothing"]),
    "dress":     (4, ["dress", "skirt", "blouse", "clothing"]),
    "hole":      (5, ["hole", "damage", "torn fabric"]),
    "tear":      (6, ["tear", "rip", "damage"]),
    "stain":     (7, ["stain", "dirt", "damage"]),
}

# Confidence thresholds
GARMENT_CONF = 0.02  # garments need looser threshold (open vocab zero-shot)
DEFECT_CONF  = 0.01  # defects are even harder to zero-shot detect

DEFECT_CLASSES = {"hole", "tear", "stain"}

VALID_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def load_model():
    print("Loading YOLOE-26s model...")
    return YOLOE("yoloe-26s-seg.pt")


def annotate_image(model, img_path: Path, class_id: int, prompts: list[str],
                   conf_thresh: float, out_label_path: Path) -> bool:
    """Run inference and write YOLO label file. Returns True if any detection saved."""
    try:
        img = Image.open(img_path)
        w, h = img.size
        if min(w, h) < 100:   # skip tiny images
            return False
    except Exception:
        return False

    try:
        model.set_classes(prompts)
        results = model.predict(str(img_path), device=0, conf=conf_thresh, verbose=False)
    except Exception as e:
        print(f"  Error on {img_path.name}: {e}")
        return False

    result = results[0]
    if len(result.boxes) == 0:
        return False

    # Write YOLO format: class_id cx cy w h  (all normalised 0-1)
    lines = []
    for box in result.boxes:
        x1, y1, x2, y2 = box.xyxy[0].tolist()
        cx = ((x1 + x2) / 2) / w
        cy = ((y1 + y2) / 2) / h
        bw = (x2 - x1) / w
        bh = (y2 - y1) / h
        # clamp
        cx, cy, bw, bh = [max(0.0, min(1.0, v)) for v in [cx, cy, bw, bh]]
        if bw > 0.01 and bh > 0.01:
            lines.append(f"{class_id} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")

    if not lines:
        return False

    out_label_path.write_text("\n".join(lines))
    return True


def main():
    print("=" * 60)
    print("  Auto-Annotation with YOLOE-26s")
    print("=" * 60)

    model = load_model()
    os.makedirs(LABELLED_DIR, exist_ok=True)

    total_annotated = 0
    total_skipped = 0

    for raw_cls, (class_id, prompts) in CLASS_CONFIG.items():
        raw_cls_dir = Path(RAW_DIR) / raw_cls
        if not raw_cls_dir.exists():
            print(f"\n[{raw_cls}] Directory not found, skipping.")
            continue

        out_cls_dir = Path(LABELLED_DIR) / raw_cls
        out_cls_dir.mkdir(parents=True, exist_ok=True)

        is_defect = raw_cls in DEFECT_CLASSES
        conf = DEFECT_CONF if is_defect else GARMENT_CONF

        images = [p for p in raw_cls_dir.iterdir() if p.suffix.lower() in VALID_EXTS]
        print(f"\n[{raw_cls}] Processing {len(images)} images "
              f"(class_id={class_id}, prompts={prompts}, conf={conf})...")

        cls_annotated = 0
        cls_skipped = 0
        for img_path in images:
            # Copy image to labelled dir
            dest_img = out_cls_dir / img_path.name
            label_path = out_cls_dir / (img_path.stem + ".txt")

            # Skip if already processed
            if label_path.exists():
                cls_annotated += 1
                continue

            shutil.copy2(img_path, dest_img)
            success = annotate_image(
                model, dest_img, class_id, prompts, conf, label_path)

            if success:
                cls_annotated += 1
            else:
                cls_skipped += 1
                # Remove copied image that has no annotation
                dest_img.unlink(missing_ok=True)

        print(f"  → Annotated: {cls_annotated}, Skipped (no detection): {cls_skipped}")
        total_annotated += cls_annotated
        total_skipped += cls_skipped

    print("\n" + "=" * 60)
    print(f"Auto-annotation complete!")
    print(f"  Total annotated : {total_annotated}")
    print(f"  Total skipped   : {total_skipped}")
    print(f"  Labelled data   : {LABELLED_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
