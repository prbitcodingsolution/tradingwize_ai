# Feature 2: AI Zone Marking on Charts

This module handles automated detection and marking of trading zones on chart images based on user requirements and AI analysis.

## Purpose
- **Zone Detection**: Identify key trading zones on price charts
- **Mark Zones**: Automatically mark support/resistance zones with user-defined requirements
- **Batch Processing**: Process multiple chart images efficiently
- **Web Interface**: Interactive UI for zone marking and adjustment

## Key Files
- `ai_zone_server_ANALYSIS.py` - Zone detection and analysis server
- `batch_detect.py` - Batch process multiple chart images
- `upload_and_detect.py` - Upload and detect zones in images
- `web_detector.py` - Web-based zone detector interface
- `AI_TUTOR_FIXED.html` - Fixed zone marking interface
- `AI_TUTOR_CORRECT_ZONES.html` - Zone correction interface

## Usage

```bash
# Run zone detection server
python feature_2_zone_marking/ai_zone_server_ANALYSIS.py

# Batch detect zones in images
python feature_2_zone_marking/batch_detect.py --input-dir ./images

# Upload and detect single image
python feature_2_zone_marking/upload_and_detect.py --image ./chart.png

# Web interface
python feature_2_zone_marking/web_detector.py
```

## Zone Types
- **Support Zones**: Areas where price tends to bounce upward
- **Resistance Zones**: Areas where price tends to reverse downward
- **Entry Zones**: Optimal zones for opening positions
- **Exit Zones**: Zones for taking profits

## Configuration
See `../config.yaml` for zone detection parameters.

## Output
- Marked chart images with zone annotations
- JSON data with zone coordinates and confidence scores
