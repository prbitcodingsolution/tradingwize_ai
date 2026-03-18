#!/usr/bin/env python
"""Interactive Image Upload & AI Zone Detection Test"""

import os
import pickle
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import tensorflow as tf
from tensorflow.keras.applications.mobilenet_v2 import MobileNetV2, preprocess_input
from tensorflow.keras.preprocessing import image as tf_image
import sys

print("\n" + "="*70)
print("AI ZONE DETECTION - IMAGE UPLOAD & ANALYSIS")
print("="*70)

# Load best model
models_dir = Path("ai_self_learning_optimized/models")
model_files = sorted(models_dir.glob("model_v*_95pct.pkl"))
latest_model_file = model_files[-1]

print(f"\n[LOAD] Loading model: {latest_model_file.name}")
with open(latest_model_file, 'rb') as f:
    model_data = pickle.load(f)
    model = model_data['model']
    scaler = model_data['scaler']
    label_map = model_data['label_map']
    accuracy = model_data.get('accuracy', 0.95)

print(f"[OK] Model ready: {accuracy*100:.0f}% accuracy, {len(label_map)} patterns\n")

# Load MobileNetV2
print("[LOAD] Loading MobileNetV2...")
feature_extractor = MobileNetV2(
    input_shape=(224, 224, 3),
    include_top=False,
    weights='imagenet'
)
print("[OK] Feature extractor loaded\n")

def extract_features(img_array):
    """Extract features from image"""
    img_resized = tf_image.smart_resize(img_array, (224, 224))
    img_preprocessed = preprocess_input(img_resized)
    img_batch = np.expand_dims(img_preprocessed, axis=0)
    features_full = feature_extractor.predict(img_batch, verbose=0)
    features_flat = features_full.flatten()
    
    # Resize to 10,800
    if len(features_flat) > 10800:
        features_flat = features_flat[:10800]
    elif len(features_flat) < 10800:
        features_flat = np.pad(features_flat, (0, 10800-len(features_flat)))
    return features_flat

def analyze_image(image_path):
    """Analyze image and detect zones"""
    print(f"\n[UPLOAD] Processing: {image_path}")
    
    try:
        # Load image
        img = Image.open(image_path).convert('RGB')
        original_size = img.size
        print(f"[OK] Image loaded: {original_size}")
        
        # Convert to array
        img_array = np.array(img)
        
        # Extract features
        print("[EXTRACT] Extracting features...")
        features = extract_features(img_array)
        features_scaled = scaler.transform([features])
        
        # Predict
        print("[PREDICT] Analyzing zones...")
        prediction = model.predict(features_scaled, verbose=0)[0]
        
        # Get top 5 predictions
        top_indices = np.argsort(prediction)[-5:][::-1]
        reverse_label_map = {v: k for k, v in label_map.items()}
        
        results = []
        for rank, idx in enumerate(top_indices, 1):
            if idx < len(prediction):
                concept = reverse_label_map.get(idx, f"Pattern_{idx}")
                confidence = prediction[idx] * 100
                results.append((rank, concept, confidence))
        
        # Create result image
        print("[CREATE] Creating result image...")
        result_img = img.copy()
        draw = ImageDraw.Draw(result_img)
        
        # Add detection results to image
        y_offset = 20
        text_color = (255, 0, 0)  # Red text
        
        for rank, concept, confidence in results:
            text = f"{rank}. {concept}: {confidence:.1f}%"
            draw.text((20, y_offset), text, fill=text_color)
            y_offset += 30
        
        # Save result
        result_path = Path(image_path).stem + "_DETECTED.png"
        result_img.save(result_path)
        print(f"[SAVE] Result saved: {result_path}\n")
        
        # Display results
        print("="*70)
        print("DETECTION RESULTS")
        print("="*70)
        for rank, concept, confidence in results:
            bar_length = int(confidence / 2)
            bar = "█" * bar_length + "░" * (50 - bar_length)
            print(f"  {rank}. {concept:25s} {confidence:5.1f}% [{bar}]")
        print("="*70)
        
        return results, result_path
        
    except Exception as e:
        print(f"[ERROR] {e}")
        return None, None

# Main loop
if __name__ == "__main__":
    print("USAGE OPTIONS:")
    print("  1. Enter image path directly")
    print("  2. Use test image: test_trading_chart.png\n")
    
    test_img = Path("test_trading_chart.png")
    
    if test_img.exists():
        print(f"Found test image at: {test_img}")
        user_input = input("Analyze test image? (y/n): ").strip().lower()
        
        if user_input == 'y':
            results, result_path = analyze_image(str(test_img))
            if results:
                print(f"\n[SUCCESS] Top detection: {results[0][1]} ({results[0][2]:.1f}%)")
                print(f"[SUCCESS] See result in: {result_path}")
        else:
            img_path = input("Enter image path: ").strip()
            if Path(img_path).exists():
                results, result_path = analyze_image(img_path)
                if results:
                    print(f"\n[SUCCESS] Top detection: {results[0][1]} ({results[0][2]:.1f}%)")
            else:
                print("[ERROR] Image not found!")
    else:
        img_path = input("Enter image path to analyze: ").strip()
        if Path(img_path).exists():
            results, result_path = analyze_image(img_path)
            if results:
                print(f"\n[SUCCESS] Analysis complete!")
                print(f"[SUCCESS] Top detection: {results[0][1]} ({results[0][2]:.1f}%)")
        else:
            print("[ERROR] Image not found!")

print("\n" + "="*70)
print("✓ ANALYSIS COMPLETE")
print("="*70 + "\n")
