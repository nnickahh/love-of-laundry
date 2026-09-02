"""
train.py
Fine-tunes YOLO26s on the custom garment inspection dataset using the RTX 3080.
Expected training time: ~15-30 minutes for 50 epochs on RTX 3080.
"""
from pathlib import Path
from ultralytics import YOLO

DATA_YAML   = "dataset/yolo/data.yaml"
BASE_MODEL  = "yolo26s.pt"       # pretrained YOLO26s (auto-downloaded by ultralytics)
OUTPUT_NAME = "garment_inspector"
EPOCHS      = 50
IMG_SIZE    = 640
PATIENCE    = 15                  # early stop if no improvement for N epochs


def main():
    data_path = Path(DATA_YAML)
    if not data_path.exists():
        print(f"ERROR: {DATA_YAML} not found. Run build_dataset.py first.")
        return

    print("=" * 60)
    print("  YOLO26s Garment Inspector — Fine-Tuning")
    print("=" * 60)
    print(f"  Base model : {BASE_MODEL}")
    print(f"  Dataset    : {DATA_YAML}")
    print(f"  Epochs     : {EPOCHS}")
    print(f"  Image size : {IMG_SIZE}")
    print(f"  GPU        : RTX 3080 (device=0)")
    print("=" * 60)

    model = YOLO(BASE_MODEL)

    results = model.train(
        data     = DATA_YAML,
        epochs   = EPOCHS,
        imgsz    = IMG_SIZE,
        device   = 0,            # RTX 3080
        batch    = -1,           # auto batch size based on GPU VRAM
        patience = PATIENCE,
        name     = OUTPUT_NAME,
        exist_ok = True,
        plots    = True,         # save training curves
        save     = True,
        verbose  = True,
    )

    # Report best model location
    best_model = Path("runs/detect") / OUTPUT_NAME / "weights" / "best.pt"
    print("\n" + "=" * 60)
    print("Training complete!")
    print(f"  Best model  : {best_model}")
    print(f"  mAP50       : {results.results_dict.get('metrics/mAP50(B)', 'N/A'):.4f}")
    print(f"  mAP50-95    : {results.results_dict.get('metrics/mAP50-95(B)', 'N/A'):.4f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
