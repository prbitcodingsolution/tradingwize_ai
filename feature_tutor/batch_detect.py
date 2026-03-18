#!/usr/bin/env python
"""Batch Image Upload & Zone Detection Analyzer"""

import pickle
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw
import tensorflow as tf
from tensorflow.keras.applications.mobilenet_v2 import MobileNetV2, preprocess_input
from tensorflow.keras.preprocessing import image as tf_image

print("\n" + "="*70)
print("BATCH IMAGE ZONE DETECTION ANALYZER")
print("="*70)

# Load model
models_dir = Path("ai_self_learning_optimized/models")
model_files = sorted(models_dir.glob("model_v*_95pct.pkl"))
latest_model_file = model_files[-1]

print(f"\n[LOAD] Model: {latest_model_file.name}")
with open(latest_model_file, 'rb') as f:
    model_data = pickle.load(f)
    model = model_data['model']
    scaler = model_data['scaler']
    label_map = model_data['label_map']

print(f"[LOAD] MobileNetV2...")
feature_extractor = MobileNetV2(
    input_shape=(224, 224, 3),
    include_top=False,
    weights='imagenet'
)
print("[OK] Ready to analyze images\n")

def extract_features(img_array):
    """Extract features from image"""
    img_resized = tf_image.smart_resize(img_array, (224, 224))
    img_preprocessed = preprocess_input(img_resized)
    img_batch = np.expand_dims(img_preprocessed, axis=0)
    features_full = feature_extractor.predict(img_batch, verbose=0)
    features_flat = features_full.flatten()
    
    if len(features_flat) > 10800:
        features_flat = features_flat[:10800]
    elif len(features_flat) < 10800:
        features_flat = np.pad(features_flat, (0, 10800-len(features_flat)))
    return features_flat

# Create sample images if they don't exist
test_img_path = Path("test_trading_chart.png")
if not test_img_path.exists():
    print("[CREATE] Generating test trading chart...")
    chart_array = np.ones((300, 600, 3), dtype=np.uint8) * 240
    np.random.seed(42)
    for x in range(50, 550, 30):
        open_price = np.random.randint(100, 200)
        close_price = np.random.randint(100, 200)
        high = max(open_price, close_price) + np.random.randint(5, 15)
        low = min(open_price, close_price) - np.random.randint(5, 15)
        
        y_high = 250 - high
        y_low = 250 - low
        y_open = 250 - open_price
        y_close = 250 - close_price
        
        color = (50, 150, 50) if close_price > open_price else (200, 50, 50)
        chart_array[int(y_close):int(y_open), x:x+15] = color
        chart_array[int(y_high):int(y_low), x+7] = (100, 100, 100)
    
    for i in range(0, 300, 50):
        chart_array[i, :] = (200, 200, 200)
    
    img = Image.fromarray(chart_array.astype('uint8'))
    img.save(test_img_path)
    print(f"[OK] Saved: {test_img_path}\n")

# Analyze all PNG images
image_files = list(Path(".").glob("*.png")) + list(Path(".").glob("test_*.png"))
image_files = [f for f in image_files if "DETECTED" not in f.name]

if not image_files:
    image_files = [test_img_path]

print(f"Found {len(image_files)} image(s) to analyze:\n")

for img_file in image_files:
    try:
        print(f"[ANALYZE] {img_file.name}")
        print("-" * 70)
        
        # Load and analyze
        img = Image.open(img_file).convert('RGB')
        img_array = np.array(img)
        
        features = extract_features(img_array)
        features_scaled = scaler.transform([features])
        prediction = model.predict(features_scaled, verbose=0)[0]
        
        # Get top 5
        top_indices = np.argsort(prediction)[-5:][::-1]
        reverse_label_map = {v: k for k, v in label_map.items()}
        
        results = []
        for rank, idx in enumerate(top_indices, 1):
            if idx < len(prediction):
                concept = reverse_label_map.get(idx, f"Pattern_{idx}")
                confidence = prediction[idx] * 100
                results.append((rank, concept, confidence))
                
                bar_length = int(confidence / 2)
                bar = "█" * bar_length + "░" * (50 - bar_length)
                print(f"  {rank}. {concept:25s} {confidence:5.1f}% [{bar}]")
        
        # Create result image
        result_img = img.copy()
        draw = ImageDraw.Draw(result_img)
        
        y_offset = 10
        for rank, concept, confidence in results:
            text = f"{rank}. {concept}: {confidence:.1f}%"
            # Draw with background
            bbox = draw.textbbox((20, y_offset), text)
            draw.rectangle(bbox, fill=(50, 50, 50))
            draw.text((20, y_offset), text, fill=(255, 255, 0))
            y_offset += 25
        
        result_path = img_file.stem + "_DETECTED.png"
        result_img.save(result_path)
        print(f"\n[SAVE] Result: {result_path}")
        print(f"[OK] Top Detection: {results[0][1].upper()} ({results[0][2]:.1f}%)")
        print()
        
    except Exception as e:
        print(f"[ERROR] {img_file.name}: {e}\n")

print("="*70)
print("✓ ANALYSIS COMPLETE - Check *_DETECTED.png files for results")
print("="*70 + "\n")
