"""
build_dataset.py
Splits the auto-annotated images into train/val/test sets (70/20/10),
copies files into the correct YOLO directory structure,
and generates the data.yaml config required for YOLO26s training.
"""
import os
import shutil
import random
import yaml
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────
LABELLED_DIR  = "dataset/labelled"
YOLO_DATASET  = "dataset/yolo"
# Love of Laundry garment categories
CLASSES       = [
    "t-shirt",      #tops
    "blouse",       
    "shirt",        
    "vest",         
    "sweater",      
    "shorts",       #bottoms
    "skirt",        
    "pants",        
    "jacket",       #outerwear
    "winter_jacket",
    "dress",        #dresses
    "evening_dress",
    "gown"
]
TRAIN_RATIO   = 0.70
VAL_RATIO     = 0.20
TEST_RATIO    = 0.10
RANDOM_SEED   = 42
VALID_EXTS    = {".jpg", ".jpeg", ".png", ".bmp"}


def collect_samples():
    """Collect all (image_path, label_path) pairs from labelled directory."""
    samples = []
    labelled = Path(LABELLED_DIR)
    for cls_dir in labelled.iterdir():
        if not cls_dir.is_dir():
            continue
        for label_path in cls_dir.glob("*.txt"):
            # Find matching image
            img_path = None
            for ext in VALID_EXTS:
                candidate = label_path.with_suffix(ext)
                if candidate.exists():
                    img_path = candidate
                    break
            if img_path:
                samples.append((img_path, label_path))
    return samples


def split(samples):
    """Split samples into train/val/test."""
    random.seed(RANDOM_SEED)
    random.shuffle(samples)
    n = len(samples)
    n_train = int(n * TRAIN_RATIO)
    n_val   = int(n * VAL_RATIO)
    train = samples[:n_train]
    val   = samples[n_train:n_train + n_val]
    test  = samples[n_train + n_val:]
    return train, val, test


def copy_split(samples, split_name):
    """Copy images and labels into YOLO directory structure."""
    img_dir = Path(YOLO_DATASET) / "images" / split_name
    lbl_dir = Path(YOLO_DATASET) / "labels"  / split_name
    img_dir.mkdir(parents=True, exist_ok=True)
    lbl_dir.mkdir(parents=True, exist_ok=True)

    for img_path, lbl_path in samples:
        shutil.copy2(img_path, img_dir / img_path.name)
        shutil.copy2(lbl_path, lbl_dir / lbl_path.name)

    print(f"  {split_name:5}: {len(samples)} samples → {img_dir}")


def write_yaml():
    """Write the data.yaml file for YOLO training."""
    yolo_abs = str(Path(YOLO_DATASET).resolve())
    data = {
        "path" : yolo_abs,
        "train": "images/train",
        "val"  : "images/val",
        "test" : "images/test",
        "nc"   : len(CLASSES),
        "names": CLASSES,
    }
    yaml_path = Path(YOLO_DATASET) / "data.yaml"
    with open(yaml_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    print(f"\ndata.yaml written to: {yaml_path}")
    return yaml_path


def main():
    print("=" * 60)
    print("  Building YOLO Dataset")
    print("=" * 60)

    samples = collect_samples()
    if not samples:
        print("ERROR: No labelled samples found in", LABELLED_DIR)
        print("Run auto_annotate.py first.")
        return

    print(f"\nTotal annotated samples: {len(samples)}")
    train, val, test = split(samples)
    print(f"Split: {len(train)} train / {len(val)} val / {len(test)} test")

    # Class distribution
    print("\nCopying files...")
    copy_split(train, "train")
    copy_split(val,   "val")
    copy_split(test,  "test")

    yaml_path = write_yaml()

    print("\n" + "=" * 60)
    print("Dataset build complete!")
    print(f"  YOLO dataset : {YOLO_DATASET}")
    print(f"  data.yaml    : {yaml_path}")
    print(f"  Classes ({len(CLASSES)}): {', '.join(CLASSES)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
