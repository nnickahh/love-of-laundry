import os
import time
from ultralytics import YOLOE

def run_detection(model, image_path, classes, conf_threshold, save_name):
    print(f"\n--- Running detection for classes: {classes} (conf >= {conf_threshold}) ---")
    
    # Configure classes
    model.set_classes(classes)
    
    # Run inference
    start_time = time.time()
    results = model.predict(image_path, device=0, conf=conf_threshold)
    inference_time = (time.time() - start_time) * 1000
    print(f"Inference completed in {inference_time:.2f} ms.")
    
    result = results[0]
    if len(result.boxes) == 0:
        print("No detections.")
    else:
        for box in result.boxes:
            class_id = int(box.cls[0].item())
            class_name = classes[class_id]
            confidence = box.conf[0].item()
            xyxy = box.xyxy[0].tolist()
            print(f"Detected: {class_name:12} | Confidence: {confidence:.2f} | Box: [{', '.join(f'{coord:.1f}' for coord in xyxy)}]")
            
    # Save visualized result
    output_dir = "results"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, save_name)
    result.save(filename=output_path)
    print(f"Visualized result saved to: {output_path}")

def main():
    image_path = "assets/test_clothing.png"
    if not os.path.exists(image_path):
        print(f"Error: Test image '{image_path}' not found. Please place a test image in the directory.")
        return

    # Load YOLOE open-vocabulary model
    print("Loading YOLOE-26s open-vocabulary model...")
    model = YOLOE("yoloe-26s-seg.pt")
    
    # Test 1: General Clothing Detection (High Confidence)
    # Using "clothing" as a super-class yields high confidence detections
    run_detection(
        model=model, 
        image_path=image_path, 
        classes=["clothing"], 
        conf_threshold=0.15, 
        save_name="detected_clothing_general.png"
    )
    
    # Test 2: Fine-Grained Clothing Sorting (Zero-Shot, Low Confidence)
    # Open-vocabulary zero-shot classification for specific garments
    run_detection(
        model=model, 
        image_path=image_path, 
        classes=["shirt", "pants"], 
        conf_threshold=0.02, 
        save_name="detected_clothing_sorted.png"
    )
    
    print("\n========================================================")
    print("All tests completed successfully!")
    print("For production sorting, we recommend fine-tuning YOLO26s")
    print("on a custom dataset of your specific garment types.")
    print("========================================================")

if __name__ == "__main__":
    main()
