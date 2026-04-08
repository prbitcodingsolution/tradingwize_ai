"""
Flask API Server for Drawing Instruction Generator
Provides REST API endpoints for generating drawing instructions
"""

from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import logging
import json
from datetime import datetime

from .drawing_generator import (
    generate_complete_analysis,
    generate_zones_only,
    generate_patterns_only,
    generate_indicators_only
)

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@app.route('/')
def index():
    """Main UI page"""
    return render_template_string(HTML_TEMPLATE)


@app.route('/api/generate', methods=['POST'])
def generate_drawings_api():
    """
    Generate drawing instructions
    
    Request JSON:
    {
        "symbol": "AAPL",
        "timeframe": "1d",
        "period": "1y",
        "tasks": ["zones", "patterns", "bollinger"],  // optional
        "use_api": false,  // use external API instead of yfinance
        "api_config": {    // API configuration (only if use_api=true)
            "base_url": "http://192.168.0.126:8000",
            "bearer_token": "eyJhbG...",
            "csrf_token": "afmpb9w...",
            "from_date": "2025-01-01",
            "to_date": "2026-03-03",
            "market": "stocks"
        }
    }
    """
    try:
        data = request.json
        
        symbol = data.get('symbol')
        if not symbol:
            return jsonify({'error': 'Symbol is required'}), 400
        
        timeframe = data.get('timeframe', '1d')
        period = data.get('period', '1y')
        tasks = data.get('tasks', None)
        use_api = data.get('use_api', False)
        api_config = data.get('api_config', None)
        
        logger.info(f"API request: {symbol} - {timeframe} - {period}")
        logger.info(f"Using API: {use_api}")
        
        from .drawing_generator import generate_drawings
        result = generate_drawings(symbol, timeframe, period, tasks, use_api=use_api, api_config=api_config)
        
        return jsonify(result)
    
    except Exception as e:
        logger.error(f"API error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/zones', methods=['POST'])
def generate_zones_api():
    """Generate only supply/demand zones"""
    try:
        data = request.json
        symbol = data.get('symbol')
        timeframe = data.get('timeframe', '1d')
        period = data.get('period', '1y')
        use_api = data.get('use_api', False)
        api_config = data.get('api_config', None)
        
        result = generate_zones_only(symbol, timeframe, period, use_api=use_api, api_config=api_config)
        return jsonify(result)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/patterns', methods=['POST'])
def generate_patterns_api():
    """Generate only candlestick patterns"""
    try:
        data = request.json
        symbol = data.get('symbol')
        timeframe = data.get('timeframe', '1d')
        period = data.get('period', '1y')
        use_api = data.get('use_api', False)
        api_config = data.get('api_config', None)
        
        result = generate_patterns_only(symbol, timeframe, period, use_api=use_api, api_config=api_config)
        return jsonify(result)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/indicators', methods=['POST'])
def generate_indicators_api():
    """Generate only technical indicators"""
    try:
        data = request.json
        symbol = data.get('symbol')
        timeframe = data.get('timeframe', '1d')
        period = data.get('period', '1y')
        use_api = data.get('use_api', False)
        api_config = data.get('api_config', None)
        
        result = generate_indicators_only(symbol, timeframe, period, use_api=use_api, api_config=api_config)
        return jsonify(result)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# HTML Template
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📊 Auto Drawing Generator</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        
        header {
            text-align: center;
            color: white;
            margin-bottom: 30px;
        }
        
        header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
        }
        
        .card {
            background: white;
            border-radius: 15px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.3);
            padding: 30px;
            margin-bottom: 20px;
        }
        
        .input-group {
            margin-bottom: 20px;
        }
        
        label {
            display: block;
            font-weight: 600;
            margin-bottom: 8px;
            color: #333;
        }
        
        input, select {
            width: 100%;
            padding: 12px;
            border: 2px solid #ddd;
            border-radius: 8px;
            font-size: 1em;
        }
        
        input:focus, select:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 5px rgba(102, 126, 234, 0.5);
        }
        
        .checkbox-group {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 10px;
            margin: 15px 0;
        }
        
        .checkbox-item {
            display: flex;
            align-items: center;
            padding: 10px;
            background: #f5f5f5;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .checkbox-item:hover {
            background: #e8e8ff;
        }
        
        .checkbox-item input {
            width: auto;
            margin-right: 8px;
        }
        
        .btn {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 15px 30px;
            border-radius: 25px;
            cursor: pointer;
            font-size: 1.1em;
            font-weight: 600;
            transition: transform 0.2s;
            width: 100%;
            margin-top: 10px;
        }
        
        .btn:hover {
            transform: scale(1.02);
        }
        
        .btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
        }
        
        .loading {
            display: none;
            text-align: center;
            padding: 30px;
        }
        
        .spinner {
            border: 4px solid #f3f3f3;
            border-top: 4px solid #667eea;
            border-radius: 50%;
            width: 50px;
            height: 50px;
            animation: spin 1s linear infinite;
            margin: 0 auto 15px;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        .result {
            display: none;
        }
        
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }
        
        .stat-card {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 10px;
            text-align: center;
        }
        
        .stat-number {
            font-size: 2.5em;
            font-weight: bold;
            margin-bottom: 5px;
        }
        
        .stat-label {
            font-size: 0.9em;
            opacity: 0.9;
        }
        
        .json-output {
            background: #1e1e1e;
            color: #d4d4d4;
            padding: 20px;
            border-radius: 10px;
            max-height: 500px;
            overflow-y: auto;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
            white-space: pre-wrap;
            word-wrap: break-word;
        }
        
        .download-btn {
            background: #4CAF50;
            margin-top: 15px;
        }
        
        .message {
            padding: 15px;
            border-radius: 8px;
            margin: 15px 0;
        }
        
        .success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        
        .error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📊 Auto Drawing Generator</h1>
            <p>Generate TradingView drawing instructions from price data analysis</p>
        </header>
        
        <div class="card">
            <h2 style="margin-bottom: 20px;">⚙️ Configuration</h2>
            
            <div class="input-group">
                <label>Stock Symbol:</label>
                <input type="text" id="symbol" placeholder="AAPL, RELIANCE.NS, TCS.NS" value="AAPL">
            </div>
            
            <div class="input-group">
                <label>Timeframe:</label>
                <select id="timeframe">
                    <option value="1m">1 Minute</option>
                    <option value="5m">5 Minutes</option>
                    <option value="15m">15 Minutes</option>
                    <option value="1h">1 Hour</option>
                    <option value="1d" selected>1 Day</option>
                    <option value="1wk">1 Week</option>
                    <option value="1mo">1 Month</option>
                </select>
            </div>
            
            <div class="input-group">
                <label>Period:</label>
                <select id="period">
                    <option value="1d">1 Day</option>
                    <option value="5d">5 Days</option>
                    <option value="1mo">1 Month</option>
                    <option value="3mo">3 Months</option>
                    <option value="6mo">6 Months</option>
                    <option value="1y" selected>1 Year</option>
                    <option value="2y">2 Years</option>
                    <option value="5y">5 Years</option>
                </select>
            </div>
            
            <div class="input-group">
                <label>Select Analysis Tasks:</label>
                <div class="checkbox-group">
                    <label class="checkbox-item">
                        <input type="checkbox" name="task" value="zones" checked>
                        Supply/Demand Zones
                    </label>
                    <label class="checkbox-item">
                        <input type="checkbox" name="task" value="patterns" checked>
                        Candlestick Patterns
                    </label>
                    <label class="checkbox-item">
                        <input type="checkbox" name="task" value="bollinger" checked>
                        Bollinger Bands
                    </label>
                    <label class="checkbox-item">
                        <input type="checkbox" name="task" value="rsi" checked>
                        RSI Signals
                    </label>
                    <label class="checkbox-item">
                        <input type="checkbox" name="task" value="macd" checked>
                        MACD Crossovers
                    </label>
                    <label class="checkbox-item">
                        <input type="checkbox" name="task" value="levels" checked>
                        Key Levels
                    </label>
                </div>
            </div>
            
            <button class="btn" onclick="generateDrawings()">
                🚀 Generate Drawings
            </button>
        </div>
        
        <div id="loadingDiv" class="card loading">
            <div class="spinner"></div>
            <p>Analyzing price data and generating drawings...</p>
        </div>
        
        <div id="resultDiv" class="card result">
            <h2>✅ Results</h2>
            
            <div class="stats" id="stats"></div>
            
            <div id="messageDiv"></div>
            
            <h3 style="margin: 20px 0 10px 0;">JSON Output:</h3>
            <div class="json-output" id="jsonOutput"></div>
            
            <button class="btn download-btn" onclick="downloadJSON()">
                💾 Download JSON
            </button>
        </div>
    </div>
    
    <script>
        let currentResult = null;
        
        async function generateDrawings() {
            const symbol = document.getElementById('symbol').value.trim();
            const timeframe = document.getElementById('timeframe').value;
            const period = document.getElementById('period').value;
            
            if (!symbol) {
                alert('Please enter a stock symbol');
                return;
            }
            
            // Get selected tasks
            const tasks = Array.from(document.querySelectorAll('input[name="task"]:checked'))
                .map(cb => cb.value);
            
            if (tasks.length === 0) {
                alert('Please select at least one analysis task');
                return;
            }
            
            // Show loading
            document.getElementById('loadingDiv').style.display = 'block';
            document.getElementById('resultDiv').style.display = 'none';
            
            try {
                const response = await fetch('/api/generate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ symbol, timeframe, period, tasks })
                });
                
                const result = await response.json();
                currentResult = result;
                
                // Hide loading
                document.getElementById('loadingDiv').style.display = 'none';
                
                if (result.error) {
                    showError(result.error);
                } else {
                    showResults(result);
                }
            } catch (error) {
                document.getElementById('loadingDiv').style.display = 'none';
                showError('Error: ' + error.message);
            }
        }
        
        function showResults(result) {
            document.getElementById('resultDiv').style.display = 'block';
            
            // Count different types
            const counts = {
                zones: 0,
                patterns: 0,
                indicators: 0,
                levels: 0
            };
            
            result.drawings.forEach(d => {
                const dtype = d.type || '';
                
                if (dtype === 'LineToolRectangle') {
                    counts.zones++;
                } else if (dtype === 'LineToolNote') {
                    // Check if it's a pattern by looking at the text
                    const text = (d.state && d.state.text) ? d.state.text.toLowerCase() : '';
                    const patternKeywords = [
                        'engulfing', 'doji', 'hammer', 'star', 'shooting',
                        'hanging', 'soldiers', 'crows', 'piercing', 'cloud',
                        'harami', 'tweezer', 'dragonfly', 'gravestone'
                    ];
                    
                    if (patternKeywords.some(keyword => text.includes(keyword))) {
                        counts.patterns++;
                    } else {
                        counts.indicators++;
                    }
                } else if (dtype === 'LineToolHorzLine') {
                    counts.levels++;
                } else if (dtype === 'LineToolTrendLine') {
                    counts.indicators++;
                } else {
                    counts.indicators++;
                }
            });
            
            // Show stats
            document.getElementById('stats').innerHTML = `
                <div class="stat-card">
                    <div class="stat-number">${result.total_drawings}</div>
                    <div class="stat-label">Total Drawings</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">${counts.zones}</div>
                    <div class="stat-label">Zones</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">${counts.patterns}</div>
                    <div class="stat-label">Patterns</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">${counts.indicators}</div>
                    <div class="stat-label">Indicators</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">${counts.levels}</div>
                    <div class="stat-label">Key Levels</div>
                </div>
            `;
            
            // Show success message
            document.getElementById('messageDiv').innerHTML = `
                <div class="message success">
                    ✅ Successfully generated ${result.total_drawings} drawing instructions for ${result.symbol}
                </div>
            `;
            
            // Show JSON
            document.getElementById('jsonOutput').textContent = JSON.stringify(result, null, 2);
        }
        
        function showError(error) {
            document.getElementById('resultDiv').style.display = 'block';
            document.getElementById('stats').innerHTML = '';
            document.getElementById('messageDiv').innerHTML = `
                <div class="message error">
                    ❌ Error: ${error}
                </div>
            `;
            document.getElementById('jsonOutput').textContent = '';
        }
        
        function downloadJSON() {
            if (!currentResult) return;
            
            const dataStr = JSON.stringify(currentResult, null, 2);
            const dataBlob = new Blob([dataStr], { type: 'application/json' });
            const url = URL.createObjectURL(dataBlob);
            const link = document.createElement('a');
            link.href = url;
            link.download = `drawings_${currentResult.symbol}_${Date.now()}.json`;
            link.click();
            URL.revokeObjectURL(url);
        }
    </script>
</body>
</html>
"""


@app.route('/api/trade-ideas/<symbol>', methods=['GET'])
def get_trade_ideas(symbol):
    """
    Fetch top trade ideas from TradingView for a given stock symbol.

    GET /api/trade-ideas/TCS
    GET /api/trade-ideas/RELIANCE?exchange=NSE&max_ideas=9
    """
    exchange = request.args.get('exchange', 'NSE')
    max_ideas = int(request.args.get('max_ideas', 9))

    try:
        from utils.tradingview_ideas_scraper import scrape_trade_ideas
        result = scrape_trade_ideas(symbol, exchange=exchange, max_ideas=max_ideas)
        return jsonify(result)
    except ImportError:
        # If running as module, adjust import path
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from utils.tradingview_ideas_scraper import scrape_trade_ideas
        result = scrape_trade_ideas(symbol, exchange=exchange, max_ideas=max_ideas)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error fetching trade ideas for {symbol}: {e}")
        return jsonify({
            "symbol": symbol,
            "exchange": exchange,
            "ideas": [],
            "count": 0,
            "error": str(e)
        }), 500


if __name__ == '__main__':
    print("\n" + "="*70)
    print("🚀 Starting Auto Drawing Generator API Server")
    print("="*70)
    print("\n📱 Open: http://localhost:5001")
    print("\nAPI Endpoints:")
    print("  POST /api/generate    - Generate all drawings")
    print("  POST /api/zones       - Generate zones only")
    print("  POST /api/patterns    - Generate patterns only")
    print("  POST /api/indicators  - Generate indicators only")
    print("  GET  /api/trade-ideas/<symbol> - Fetch TradingView trade ideas")
    print("\n" + "="*70 + "\n")
    
    app.run(host='0.0.0.0', port=5001, debug=False)
