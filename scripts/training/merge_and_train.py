"""
merge_and_train.py
Merges the Roboflow clothing and defect datasets, remaps class IDs to a
unified schema, dynamically oversamples minority classes to balance the
dataset, and launches YOLO26s training optimized for laptop GPU speed.
"""

import os
import shutil
import random
import yaml
import torch
from pathlib import Path
from collections import Counter

# -- Output paths -------------------------------------------------------------
MERGED_DIR  = "dataset/merged"
TRAIN_RATIO = 0.75
VAL_RATIO   = 0.15
RANDOM_SEED = 42

# -- Final unified class list --------------------------------------------------
FINAL_CLASSES = [
    "shirt",          # 0  - clothing (tops)
    "jacket",         # 1  - clothing (tops)
    "jeans",          # 2  - clothing (bottoms)
    "underwear",      # 3  - clothing (undergarments)
    "dress",          # 4  - clothing (one-piece)
    "hole",           # 5  - defect
    "tear",           # 6  - defect
    "stain",          # 7  - defect
    "broken_button",  # 8  - defect
    "color_defect",   # 9  - defect
    "foreign_yarn",   # 10 - defect
    "button_hike",    # 11 - defect
    "swing_error",    # 12 - defect
    "shorts",         # 13 - clothing (bottoms)
    "skirt",          # 14 - clothing (bottoms)
]

# Defect class indices
DEFECT_CLASSES = {5, 6, 7, 8, 9, 10, 11, 12}

# -- Source dataset descriptors ------------------------------------------------
SOURCES = []

# -- Dataset 1: cloth-defect-detection (mrkbil-projects) ----------------------
D1_ROOT = "dataset/roboflow/cloth_defect"
D1_YAML = os.path.join(D1_ROOT, "data.yaml")
if os.path.exists(D1_YAML):
    SOURCES.append({
        "root":  D1_ROOT,
        "label": "cloth_defect",
        "remap": {
            0: 8,   # Broken_button  -> broken_button
            1: 11,  # Button_hike    -> button_hike
            2: 9,   # Color_defect   -> color_defect
            3: 10,  # Foreign_yarn   -> foreign_yarn
            4: 5,   # Hole           -> hole
            5: 12,  # Swing_error    -> swing_error
        }
    })

# NOTE: Dataset 2 is DROPPED because it is too noisy and maps all defects to hole.

# -- Dataset 3: garment defects ------------------------------------------------
D3_ROOT = "dataset/roboflow/dataset3"
D3_YAML = os.path.join(D3_ROOT, "data.yaml")
if os.path.exists(D3_YAML):
    SOURCES.append({
        "root":  D3_ROOT,
        "label": "dataset3",
        "remap": {
            0: 5,   # Hole  -> hole
            1: 6,   # Knot  -> tear (closest physical defect)
            2: -1,  # Line  -> DROPPED
            3: 7,   # Stain -> stain
        }
    })

# -- Clothing Dataset: clothing-detection-2 (prebuilt) -------------------------
CLOTHING_ROOT = "dataset/roboflow/clothing_detection_2"
CLOTHING_YAML = os.path.join(CLOTHING_ROOT, "data.yaml")
if os.path.exists(CLOTHING_YAML):
    SOURCES.append({
        "root":  CLOTHING_ROOT,
        "label": "clothing_detection_2",
        "remap": {
            0: 4,   # dress -> dress
            1: -1,  # long_hair -> DROPPED
            2: 2,   # long_pants -> pants/jeans
            3: 0,   # long_shirt -> shirt (FIXED: was mapped to jacket, causing school uniforms to be detected as jackets)
            4: -1,  # medium_hair -> DROPPED
            5: -1,  # no_hair -> DROPPED
            6: -1,  # no_shirt -> DROPPED
            7: -1,  # short_hair -> DROPPED
            8: 13,  # short_pants -> shorts
            9: 0,   # short_shirt -> shirt
            10: 14, # skirt -> skirt
            11: 0,  # sleeveless_shirt -> shirt (not underwear)
        }
    })

# -- Scraped + auto-annotated images -------------------------------------------
SCRAPED_LABELLED = "dataset/labelled"
if os.path.exists(SCRAPED_LABELLED):
    SCRAPED_CLASS_REMAP = {i: i for i in range(15)}  # identity mapping
    SOURCES.append({
        "root":   SCRAPED_LABELLED,
        "label":  "scraped",
        "remap":  SCRAPED_CLASS_REMAP,
        "flat":   True,
    })

# -- DeepFashion clothing dataset ---------------------------------------------
for df_path in ["dataset/deepfashion", "dataset/deepfashion_converted"]:
    if os.path.exists(df_path):
        DF_CLASS_REMAP = {i: i for i in range(15)}  # identity mapping
        SOURCES.append({
            "root":   df_path,
            "label":  "deepfashion",
            "remap":  DF_CLASS_REMAP,
        })
        break

# -- Additional YOLO clothing dataset ------------------------------------------
YOLO_DIR = "dataset/yolo"
if os.path.exists(YOLO_DIR):
    SOURCES.append({
        "root":   YOLO_DIR,
        "label":  "yolo_garments",
        "remap": {
            0: 0,   # t-shirt -> shirt
            1: 0,   # blouse -> shirt
            2: 0,   # shirt -> shirt
            3: 0,   # vest -> shirt
            4: 1,   # sweater -> jacket
            5: 13,  # shorts -> shorts
            6: 14,  # skirt -> skirt
            7: 2,   # pants -> jeans/pants
            8: 1,   # jacket -> jacket
            9: 1,   # winter_jacket -> jacket
            10: 4,  # dress -> dress
            11: 4,  # evening_dress -> dress
            12: 4,  # gown -> dress
        }
    })

VALID_IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def collect_samples(source: dict) -> list:
    """Collect all (img_path, label_path, remap) tuples from a source."""
    root  = Path(source["root"])
    remap = source["remap"]
    flat  = source.get("flat", False)
    samples = []

    if flat:
        for cls_dir in sorted(root.iterdir()):
            if not cls_dir.is_dir():
                continue
            for lbl in sorted(cls_dir.glob("*.txt")):
                img = None
                for ext in VALID_IMG_EXTS:
                    c = lbl.with_suffix(ext)
                    if c.exists():
                        img = c
                        break
                if img:
                    samples.append((img, lbl, remap))
    else:
        for split in ["train", "val", "valid", "validation", "test"]:
            img_dir = root / split / "images"
            lbl_dir = root / split / "labels"
            if not img_dir.exists():
                img_dir = root / "images" / split
                lbl_dir = root / "labels" / split
            if not img_dir.exists():
                continue
            for img in sorted(img_dir.iterdir()):
                if img.suffix.lower() not in VALID_IMG_EXTS:
                    continue
                lbl = lbl_dir / (img.stem + ".txt")
                if lbl.exists():
                    samples.append((img, lbl, remap))

    return samples


def remap_label(lbl_path: Path, remap: dict) -> list:
    """Read a YOLO label file and remap class IDs. Returns remapped lines."""
    lines_out = []
    try:
        for line in lbl_path.read_text().strip().splitlines():
            parts = line.strip().split()
            if not parts:
                continue
            orig_id = int(parts[0])
            new_id  = remap.get(orig_id, -1)
            if new_id >= 0:
                lines_out.append(f"{new_id} {' '.join(parts[1:])}")
    except Exception:
        pass
    return lines_out


def oversample_samples(samples: list, target_min: int = 1500, max_multiplier: int = 15) -> list:
    """Dynamically duplicates samples containing minority/rare classes."""
    print("\n" + "=" * 60)
    print("  Oversampling Minority Classes")
    print("=" * 60)

    # Count initial class distributions
    class_counts = Counter()
    sample_classes = []

    for img_path, lbl_path, remap in samples:
        final_ids = []
        lines = remap_label(lbl_path, remap)
        for line in lines:
            final_ids.append(int(line.split()[0]))
        class_counts.update(final_ids)
        sample_classes.append(final_ids)

    print("Initial class counts:")
    for c_id, name in enumerate(FINAL_CLASSES):
        print(f"  Class {c_id:2d} ({name:15}): {class_counts[c_id]} instances")

    oversampled = []
    for idx, (img_path, lbl_path, remap) in enumerate(samples):
        classes = sample_classes[idx]
        if not classes:
            continue

        # Determine multiplier based on the rarest class present in this sample
        multipliers = [1]
        for c in classes:
            orig_count = class_counts[c]
            if 0 < orig_count < target_min:
                # Dynamic multiplier to target target_min instances
                mult = int(min(max_multiplier, target_min / orig_count))
                multipliers.append(mult)

        m = max(multipliers)
        for _ in range(m):
            oversampled.append((img_path, lbl_path, remap))

    # Recount post-oversampling class distributions
    post_counts = Counter()
    for img_path, lbl_path, remap in oversampled:
        lines = remap_label(lbl_path, remap)
        for line in lines:
            post_counts[int(line.split()[0])] = post_counts.get(int(line.split()[0]), 0) + 1

    print("\nBalanced class counts (Post-Oversampling):")
    for c_id, name in enumerate(FINAL_CLASSES):
        print(f"  Class {c_id:2d} ({name:15}): {post_counts[c_id]} instances")
    print("=" * 60)

    return oversampled


def copy_to_split(samples, split_name, img_out, lbl_out):
    img_out.mkdir(parents=True, exist_ok=True)
    lbl_out.mkdir(parents=True, exist_ok=True)
    copied = 0
    for i, (img_path, lbl_path, remap) in enumerate(samples):
        lines = remap_label(lbl_path, remap)
        if not lines:
            continue
        # Unique filename to avoid collisions across datasets
        stem = f"{i:06d}_{img_path.stem}"
        dst_img = img_out / (stem + img_path.suffix)
        dst_lbl = lbl_out / (stem + ".txt")
        shutil.copy2(img_path, dst_img)
        dst_lbl.write_text("\n".join(lines))
        copied += 1
    return copied


def main():
    print("=" * 60)
    print("  Merging Datasets")
    print("=" * 60)

    if not SOURCES:
        print("ERROR: No source datasets found. Download datasets first.")
        return

    # Collect all samples
    all_samples = []
    for src in SOURCES:
        s = collect_samples(src)
        print(f"  [{src['label']:20}] {len(s):5d} samples")
        all_samples.extend(s)

    print(f"\n  TOTAL COLLECTED: {len(all_samples)} samples")

    if len(all_samples) == 0:
        print("ERROR: No samples collected!")
        return

    # Apply oversampling to balance classes
    balanced_samples = oversample_samples(all_samples, target_min=1500, max_multiplier=15)

    # Shuffle and split
    random.seed(RANDOM_SEED)
    random.shuffle(balanced_samples)
    n = len(balanced_samples)
    n_train = int(n * TRAIN_RATIO)
    n_val   = int(n * VAL_RATIO)
    train   = balanced_samples[:n_train]
    val     = balanced_samples[n_train:n_train + n_val]
    test    = balanced_samples[n_train + n_val:]
    print(f"\n  Split: {len(train)} train / {len(val)} val / {len(test)} test")

    # Clean previous merge directory if exists
    merged = Path(MERGED_DIR)
    if merged.exists():
        print(f"Cleaning previous merged dataset directory: {merged}")
        import subprocess
        subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(merged)], check=False)
        if merged.exists():
            shutil.rmtree(merged, ignore_errors=True)

    # Copy files
    print("\nCopying files to merged split structures...")
    for split_name, split_samples in [("train", train), ("val", val), ("test", test)]:
        n_copied = copy_to_split(
            split_samples,
            split_name,
            merged / "images" / split_name,
            merged / "labels" / split_name,
        )
        print(f"  {split_name:5}: {n_copied} images written")

    # If one of the splits is empty, make sure the directories still exist
    for split_name in ["train", "val", "test"]:
        (merged / "images" / split_name).mkdir(parents=True, exist_ok=True)
        (merged / "labels" / split_name).mkdir(parents=True, exist_ok=True)

    # Write data.yaml
    yaml_path = merged / "data.yaml"
    data_yaml = {
        "path" : str(merged.resolve()),
        "train": "images/train",
        "val"  : "images/val",
        "test" : "images/test",
        "nc"   : len(FINAL_CLASSES),
        "names": FINAL_CLASSES,
    }
    with open(yaml_path, "w") as f:
        yaml.dump(data_yaml, f, default_flow_style=False, sort_keys=False)

    print(f"\n  data.yaml -> {yaml_path}")
    print(f"  Classes ({len(FINAL_CLASSES)}): {FINAL_CLASSES}")

    # ── Launch training ───────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  Launching YOLO26s Fine-Tuning (Laptop Optimized)")
    print("=" * 60)

    from ultralytics import YOLO

    model = YOLO("yolo26s.pt")

    use_cuda = torch.cuda.is_available()
    if use_cuda:
        device = 0
        batch = 16
        workers = 2
        amp = True
        print("CUDA available — using GPU training")
    else:
        device = "cpu"
        batch = 16
        workers = 2
        amp = False
        print("CUDA not available — falling back to CPU training (batch=16, workers=2)")

    last_ckpt = Path("runs/detect/garment_inspector_v2/weights/last.pt")
    resume = last_ckpt.exists()
    if resume:
        print(f"Resuming from checkpoint: {last_ckpt}")
    else:
        print("No checkpoint found; starting a fresh training run")

    results = model.train(
        data     = str(yaml_path),
        epochs   = 20,
        imgsz    = 640,
        device   = device,
        batch    = batch,
        workers  = workers,
        amp      = amp,
        patience = 10,
        name     = "garment_inspector_v2",
        exist_ok = True,
        plots    = True,
        save     = True,
        verbose  = True,
        resume   = resume,
        cls      = 1.5,
    )

    best = Path("runs/detect/garment_inspector_v2/weights/best.pt")
    print("\n" + "=" * 60)
    print("Training complete!")
    print(f"  Best model : {best}")
    try:
        print(f"  mAP50      : {results.results_dict.get('metrics/mAP50(B)', 'N/A'):.4f}")
        print(f"  mAP50-95   : {results.results_dict.get('metrics/mAP50-95(B)', 'N/A'):.4f}")
    except Exception:
        pass
    print("=" * 60)

    if best.exists():
        print("\nExporting best.pt to ONNX format...")
        try:
            best_model = YOLO(str(best))
            best_model.export(format="onnx", imgsz=640, dynamic=False)
            print(f"  ONNX export successful -> runs/detect/garment_inspector_v2/weights/best.onnx")
        except Exception as e:
            print(f"  ONNX export error: {e}")


if __name__ == "__main__":
    main()
