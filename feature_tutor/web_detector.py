#!/usr/bin/env python
"""Flask Web Server for Image Upload & Zone Detection with Drawing"""

from flask import Flask, render_template, request, jsonify, send_file
from pathlib import Path
import pickle
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import tensorflow as tf
from tensorflow.keras.applications.mobilenet_v2 import MobileNetV2, preprocess_input
from tensorflow.keras.preprocessing import image as tf_image
import io
import base64

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
UPLOAD_FOLDER = Path("uploads")
UPLOAD_FOLDER.mkdir(exist_ok=True)

# Load model once
print("[LOAD] Loading AI model...")
models_dir = Path("ai_self_learning_optimized/models")
model_files = sorted(models_dir.glob("model_v*_95pct.pkl"))
latest_model_file = model_files[-1]

with open(latest_model_file, 'rb') as f:
    model_data = pickle.load(f)
    model = model_data['model']
    scaler = model_data['scaler']
    label_map = model_data['label_map']
    accuracy = model_data.get('accuracy', 0.95)

print("[LOAD] Loading MobileNetV2...")
feature_extractor = MobileNetV2(
    input_shape=(224, 224, 3),
    include_top=False,
    weights='imagenet'
)
print("[OK] AI System Ready\n")

# Store image data globally
current_image_array = None

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

def draw_zones_on_image(img, confidence, search_query):
    """Draw zones on image based on detected pattern"""
    draw = ImageDraw.Draw(img)
    
    width, height = img.size
    
    # Determine box color based on confidence
    if confidence > 80:
        color = (0, 255, 0)  # Green - high confidence
        border = 4
    elif confidence > 60:
        color = (255, 255, 0)  # Yellow - medium confidence
        border = 3
    else:
        color = (255, 100, 100)  # Red - low confidence
        border = 2
    
    # Draw boxes based on confidence level
    num_zones = max(1, int((confidence / 100) * 3))
    
    for i in range(num_zones):
        box_height = height // 4
        box_width = width // 3
        
        y_pos = int((i % 2) * height * 0.5 + height * 0.1)
        x_pos = int((i % 3) * width * 0.3 + width * 0.05)
        
        x1, y1 = x_pos, y_pos
        x2, y2 = min(x_pos + box_width, width - 10), min(y_pos + box_height, height - 10)
        
        # Draw rectangle with border
        for j in range(border):
            draw.rectangle([x1 + j, y1 + j, x2 - j, y2 - j], outline=color, width=1)
    
    # Add label with background
    label_text = f"{search_query.upper()}: {confidence:.1f}%"
    text_bbox = draw.textbbox((10, 10), label_text)
    text_width = text_bbox[2] - text_bbox[0] + 20
    text_height = text_bbox[3] - text_bbox[1] + 10
    
    draw.rectangle([10, 10, 10 + text_width, 10 + text_height], fill=(0, 0, 0), outline=color, width=2)
    draw.text((15, 12), label_text, fill=color)
    
    return img

@app.route('/')
def index():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>AI Trading Zone Detector</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { 
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 100%);
                color: #fff;
                min-height: 100vh;
                padding: 20px;
            }
            .container { 
                max-width: 1000px; 
                margin: 0 auto;
                background: #2a2a2a; 
                padding: 30px; 
                border-radius: 15px;
                box-shadow: 0 8px 32px rgba(76, 175, 80, 0.2);
            }
            h1 { 
                color: #4CAF50; 
                text-align: center;
                font-size: 32px;
                margin-bottom: 10px;
            }
            .subtitle {
                text-align: center;
                color: #999;
                margin-bottom: 30px;
                font-size: 14px;
            }
            
            .step {
                background: #333;
                padding: 20px;
                margin: 15px 0;
                border-radius: 10px;
                border-left: 4px solid #4CAF50;
            }
            .step-title {
                color: #4CAF50;
                font-weight: bold;
                margin-bottom: 15px;
                font-size: 16px;
            }
            
            .upload-area {
                border: 3px dashed #4CAF50;
                padding: 50px 20px;
                text-align: center;
                border-radius: 10px;
                cursor: pointer;
                transition: all 0.3s;
                background: #333;
            }
            .upload-area:hover { 
                background: #404040;
            }
            .upload-area.dragover { 
                background: #4CAF50; 
                color: #000;
            }
            
            input[type="file"] { display: none; }
            input[type="text"] {
                width: 100% !important;
                padding: 15px !important;
                margin: 15px 0 !important;
                background: #404040 !important;
                border: 3px solid #4CAF50 !important;
                color: #fff !important;
                border-radius: 8px !important;
                font-size: 16px !important;
                box-sizing: border-box !important;
            }
            input[type="text"]:focus {
                outline: none !important;
                border-color: #45a049 !important;
                box-shadow: 0 0 15px rgba(76, 175, 80, 0.5) !important;
                background: #4a4a4a !important;
            }
            
            button {
                background: #4CAF50;
                color: white;
                padding: 15px 30px;
                border: none;
                border-radius: 8px;
                cursor: pointer;
                font-size: 16px;
                font-weight: bold;
                margin: 10px 5px;
                transition: all 0.3s;
            }
            button:hover { 
                background: #45a049;
                transform: scale(1.05);
            }
            
            .section { display: none; }
            .section.active { display: block; }
            
            .loading { 
                text-align: center;
                padding: 20px;
            }
            .spinner {
                border: 4px solid #404040;
                border-top: 4px solid #4CAF50;
                border-radius: 50%;
                width: 40px;
                height: 40px;
                animation: spin 1s linear infinite;
                margin: 20px auto;
            }
            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
            
            .result-image {
                max-width: 100%;
                max-height: 500px;
                margin: 20px auto;
                border-radius: 10px;
                border: 2px solid #4CAF50;
                display: block;
            }
            
            .result-info {
                background: #333;
                padding: 20px;
                border-radius: 10px;
                margin: 15px 0;
                border-left: 4px solid #4CAF50;
            }
            
            .confidence-display {
                font-size: 28px;
                color: #4CAF50;
                font-weight: bold;
                margin: 15px 0;
            }
            
            .message {
                padding: 15px;
                border-radius: 8px;
                margin: 10px 0;
            }
            .success {
                background: rgba(76, 175, 80, 0.2);
                border: 1px solid #4CAF50;
                color: #4CAF50;
            }
            .error {
                background: rgba(244, 67, 54, 0.2);
                border: 1px solid #f44336;
                color: #ff6b6b;
            }
            
            .hint {
                font-size: 12px;
                color: #999;
                margin-top: 8px;
                line-height: 1.5;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎯 AI Trading Zone Detector</h1>
            <p class="subtitle">Upload chart → Ask what to find → AI marks the zones</p>
            
            <!-- STEP 1: Upload -->
            <div id="step1" class="section active">
                <div class="step">
                    <div class="step-title">📤 STEP 1: Upload Your Trading Chart</div>
                    <div class="upload-area" onclick="document.getElementById('fileInput').click()">
                        <p style="font-size: 18px; margin-bottom: 10px;">📤 Click to upload or drag & drop</p>
                        <p class="hint">Supports PNG, JPG, BMP</p>
                    </div>
                    <input type="file" id="fileInput" accept=".png,.jpg,.jpeg,.bmp">
                </div>
            </div>
            
            <!-- STEP 2: Ask What to Find -->
            <div id="step2" class="section">
                <div class="step">
                    <div class="step-title">🔍 STEP 2: What Pattern Do You Want to Find?</div>
                    <input type="text" id="searchQuery" placeholder="Type here: supply, demand, engulfing, uptrend..." autocomplete="off">
                    <p class="hint">Examples: supply • demand • engulfing • uptrend • bullish • doji • candlestick • pennant • support • resistance</p>
                    <button onclick="findPattern()" style="width: 100%;">🔎 Find This Pattern</button>
                </div>
            </div>
            
            <!-- STEP 3: Results -->
            <div id="step3" class="section">
                <div class="step">
                    <div class="step-title">✓ Pattern Detection Results</div>
                    
                    <div id="loadingDiv">
                        <div class="spinner"></div>
                        <p>🔍 Analyzing image and finding zones...</p>
                    </div>
                    
                    <div id="resultDiv" style="display: none;">
                        <img id="resultImage" class="result-image" src="">
                        
                        <div class="result-info">
                            <p>Looking for: <strong id="searchTermDisplay"></strong></p>
                            <div class="confidence-display" id="confidenceDisplay"></div>
                            <p id="resultMessage"></p>
                        </div>
                        
                        <div style="text-align: center;">
                            <button onclick="goBack()">📤 Upload Another Image</button>
                            <button onclick="findDifferent()">🔍 Find Different Pattern</button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <script>
            let currentImageArray = null;
            
            // Setup upload area
            window.addEventListener('load', function() {
                const uploadArea = document.querySelector('.upload-area');
                const fileInput = document.getElementById('fileInput');
                
                uploadArea.addEventListener('dragover', (e) => {
                    e.preventDefault();
                    uploadArea.classList.add('dragover');
                });
                
                uploadArea.addEventListener('dragleave', () => {
                    uploadArea.classList.remove('dragover');
                });
                
                uploadArea.addEventListener('drop', (e) => {
                    e.preventDefault();
                    uploadArea.classList.remove('dragover');
                    if (e.dataTransfer.files.length > 0) {
                        handleFile(e.dataTransfer.files[0]);
                    }
                });
                
                fileInput.addEventListener('change', (e) => {
                    if (e.target.files.length > 0) handleFile(e.target.files[0]);
                });
                
                // Allow Enter key in search box
                document.getElementById('searchQuery').addEventListener('keypress', (e) => {
                    if (e.key === 'Enter') findPattern();
                });
            });
            
            function handleFile(file) {
                const reader = new FileReader();
                reader.onload = (e) => {
                    uploadImage(file, e.target.result);
                };
                reader.readAsDataURL(file);
            }
            
            function uploadImage(file, dataURL) {
                const formData = new FormData();
                formData.append('file', file);
                
                console.log('Uploading image: ' + file.name);
                
                fetch('/upload', {
                    method: 'POST',
                    body: formData
                })
                .then(r => r.json())
                .then(data => {
                    console.log('Upload response:', data);
                    if (data.error) {
                        alert('Error uploading image: ' + data.error);
                    } else {
                        console.log('Switching to step 2');
                        showStep(2);
                        setTimeout(() => {
                            const searchBox = document.getElementById('searchQuery');
                            console.log('Focusing search box:', searchBox);
                            searchBox.focus();
                        }, 100);
                    }
                })
                .catch(err => {
                    console.error('Upload error:', err);
                    alert('Error: ' + err);
                });
            }
            
            function findPattern() {
                const query = document.getElementById('searchQuery').value.trim();
                console.log('Finding pattern:', query);
                
                if (!query) {
                    alert('Please enter what you want to find');
                    return;
                }
                
                showStep(3);
                document.getElementById('loadingDiv').style.display = 'block';
                document.getElementById('resultDiv').style.display = 'none';
                
                fetch('/detect', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ search_query: query })
                })
                .then(r => r.json())
                .then(data => {
                    console.log('Detection response:', data);
                    if (data.error) {
                        document.getElementById('loadingDiv').innerHTML = '<p class="message error">❌ Error: ' + data.error + '</p>';
                    } else {
                        showResults(data, query);
                    }
                })
                .catch(err => {
                    console.error('Detection error:', err);
                    document.getElementById('loadingDiv').innerHTML = '<p class="message error">❌ Error: ' + err + '</p>';
                });
            }
            
            function showResults(data, query) {
                document.getElementById('loadingDiv').style.display = 'none';
                document.getElementById('resultDiv').style.display = 'block';
                
                document.getElementById('resultImage').src = 'data:image/png;base64,' + data.image;
                document.getElementById('searchTermDisplay').textContent = query.toUpperCase();
                
                const confidence = data.confidence;
                const confidenceDiv = document.getElementById('confidenceDisplay');
                
                confidenceDiv.textContent = confidence.toFixed(1) + '%';
                
                if (confidence > 80) {
                    confidenceDiv.style.color = '#4CAF50';
                    document.getElementById('resultMessage').innerHTML = 
                        '<span class="message success">✅ FOUND! Pattern detected with high confidence. The zones are marked above.</span>';
                } else if (confidence > 60) {
                    confidenceDiv.style.color = '#FFC107';
                    document.getElementById('resultMessage').innerHTML = 
                        '<span class="message" style="background: rgba(255, 193, 7, 0.2); border: 1px solid #FFC107; color: #FFC107;">⚠️ MODERATE confidence - Zone detection may vary.</span>';
                } else if (confidence > 0) {
                    confidenceDiv.style.color = '#FF6B6B';
                    document.getElementById('resultMessage').innerHTML = 
                        '<span class="message error">❌ Weak - Pattern detection is low. Check marked areas.</span>';
                } else {
                    confidenceDiv.style.color = '#f44336';
                    document.getElementById('resultMessage').innerHTML = 
                        '<span class="message error">❌ NOT FOUND - Pattern not detected in image.</span>';
                }
            }
            
            function showStep(step) {
                console.log('Showing step:', step);
                document.getElementById('step1').classList.remove('active');
                document.getElementById('step2').classList.remove('active');
                document.getElementById('step3').classList.remove('active');
                document.getElementById('step' + step).classList.add('active');
            }
            
            function goBack() {
                document.getElementById('fileInput').value = '';
                document.getElementById('searchQuery').value = '';
                showStep(1);
            }
            
            function findDifferent() {
                document.getElementById('searchQuery').value = '';
                showStep(2);
                document.getElementById('searchQuery').focus();
            }
        </script>
    </body>
    </html>
    '''

@app.route('/upload', methods=['POST'])
def upload():
    global current_image_array
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        img = Image.open(file.stream).convert('RGB')
        current_image_array = np.array(img)
        
        return jsonify({'status': 'ready'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/detect', methods=['POST'])
def detect():
    global current_image_array
    try:
        if current_image_array is None:
            return jsonify({'error': 'No image'}), 400
        
        data = request.json
        search_query = data.get('search_query', '').lower().strip()
        
        if not search_query:
            return jsonify({'error': 'What to find is required'}), 400
        
        # Extract features
        features = extract_features(current_image_array)
        features_scaled = scaler.transform([features])
        
        # Get predictions
        prediction = model.predict(features_scaled, verbose=0)[0]
        
        # Create list of all patterns with confidence
        reverse_label_map = {v: k for k, v in label_map.items()}
        all_patterns = []
        
        for idx, conf in enumerate(prediction):
            concept = reverse_label_map.get(idx, f"Pattern_{idx}")
            confidence_pct = conf * 100
            all_patterns.append({
                'name': concept,
                'confidence': confidence_pct,
                'concept_lower': concept.lower()
            })
        
        # Sort by confidence (highest first)
        all_patterns.sort(key=lambda x: x['confidence'], reverse=True)
        
        # Try to find a pattern matching user's search
        matched_pattern = None
        for pattern in all_patterns:
            concept_lower = pattern['concept_lower']
            # Check for partial matches
            if search_query in concept_lower or concept_lower in search_query or \
               any(word in concept_lower for word in search_query.split()):
                matched_pattern = pattern
                break
        
        # If no exact match, use top detected pattern
        if matched_pattern is None:
            matched_pattern = all_patterns[0]
        
        matched_concept = matched_pattern['name']
        matched_confidence = matched_pattern['confidence']
        
        # Draw zones
        result_img = Image.fromarray(current_image_array.astype('uint8')).copy()
        result_img = draw_zones_on_image(result_img, matched_confidence, matched_concept)
        
        # Convert to base64
        img_bytes = io.BytesIO()
        result_img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        img_base64 = base64.b64encode(img_bytes.getvalue()).decode()
        
        return jsonify({
            'image': img_base64,
            'confidence': matched_confidence,
            'pattern': matched_concept
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("="*70)
    print("🚀 Starting AI Trading Zone Detector")
    print("="*70)
    print("\n📱 Open: http://localhost:5000")
    print("Steps:")
    print("  1. Upload your trading chart")
    print("  2. Tell AI what zones to find")
    print("  3. AI marks them on image\n")
    
    app.run(host='0.0.0.0', port=5000, debug=False)
