# Drawing Instruction Module

This module auto-generates TradingView-compatible drawing instructions (JSON) from stock price data. It combines rule-based technical analysis with LLM-powered pattern detection to produce supply/demand zones, candlestick patterns, Smart Money Concept (SMC) structures, Fair Value Gaps, liquidity sweeps, and standard indicators — all output as JSON that TradingView can render as chart drawings.

---

## How It Works — The Pipeline

Every analysis follows the same pipeline regardless of entry point (CLI, API, chat, or Streamlit):

```
User Input (symbol, timeframe, period)
        |
        v
  Symbol Resolver ──── Converts shorthand ("JIO") to NSE format ("JIOFIN.NS")
        |
        v
  Price Fetcher ─────── Fetches OHLCV DataFrame via yfinance or external API
        |
        v
  Analysis Layer ─────── Runs selected detectors in parallel:
        |                  - Zone Detector (supply/demand)
        |                  - Pattern Detector (candlestick patterns)
        |                  - SMC Indicator (BOS, CHoCH, order blocks, FVGs)
        |                  - Supply/Demand Indicator (volume profile zones)
        |                  - Liquidity Sweeps (pivot level sweeps)
        |                  - Indicator Calculator (Bollinger, RSI)
        |                  - MACD Indicator (crossovers, 4-color histogram)
        |                  - LLM Pattern Detector (AI-powered FVG + patterns)
        |
        v
  JSON Builder ────────── Converts all detections to TradingView drawing JSON
        |
        v
  Output ─────────────── JSON array of drawing objects (zones, markers, lines)
```

---

## File-by-File Breakdown

### Data Layer

| File | What It Does |
|------|-------------|
| `symbol_resolver.py` | Maps shorthand stock names to NSE-format symbols. Contains `SYMBOL_MAP` dictionary with 100+ Indian stock mappings. Key function: `resolve_symbol(symbol)`. |
| `price_fetcher.py` | Fetches OHLCV data via **yfinance**. Returns a pandas DataFrame with `[Open, High, Low, Close, Volume, timestamp]` columns. Auto-tries `.NS` suffix for Indian stocks. Key function: `fetch_price_data(symbol, timeframe, period)`. |
| `api_price_fetcher.py` | Alternative data source using an authenticated external API (`/api/v1/mentor/get-forex-data/`). Class `APIPriceFetcher` takes `base_url`, `bearer_token`, `csrf_token`. Supports stocks, forex, crypto. Handles multiple response field naming conventions. Alerts on 401 token expiry. |

### Rule-Based Detection

| File | What It Does |
|------|-------------|
| `zone_detector.py` | Detects institutional supply/demand zones using 3-step validation: **(1)** tight consolidation base (range < 1.5x ATR, body < 50% of range, min 3 candles), **(2)** explosive impulse move (range > 2x base, body > 40% of impulse), **(3)** clean departure (wick ratio < 25%). Outputs Rally-Base-Rally (demand) and Drop-Base-Drop (supply) zones. Key function: `detect_supply_demand_zones(df)`. Also has `filter_overlapping_zones()` to remove duplicates keeping strongest. |
| `pattern_detector.py` | Detects classical candlestick patterns: Hammer, Inverted Hammer, Engulfing (bullish/bearish), Morning/Evening Star, Three White Soldiers, Three Black Crows, Doji variants, Harami, Tweezer, Piercing Line, Dark Cloud Cover. Each pattern returns type, signal (bullish/bearish/neutral), timestamp, price, and human-readable reason. Key function: `detect_candlestick_patterns(df, max_patterns=15)`. |
| `indicator_calculator.py` | Calculates standard technical indicators. Functions: `calculate_bollinger_bands(df, period=20, std_dev=2)` with squeeze detection, `calculate_rsi(df, period=14)` with overbought/oversold signals, `calculate_macd(df, fast=12, slow=26, signal=9)` with crossovers, `calculate_moving_averages(df, periods)`. All return lists of time/price point dicts for TradingView. |

### Advanced Indicators (Smart Money / Institutional)

| File | What It Does |
|------|-------------|
| `smc_indicator.py` | **Smart Money Concepts** — class `SMCIndicator`. Detects: Break Of Structure (BOS), Change of Character (CHoCH), Order Blocks (bullish/bearish), Fair Value Gaps with fill tracking, Equal Highs/Lows, Strong/Weak premium/discount levels. Uses data classes `Pivot`, `OrderBlock`, `FairValueGap`, `StructureEvent`. Key params: `swing_length=50`, `internal_length=5`, `ob_filter="atr"`. Methods: `run()`, `plot()`. |
| `supply_demand_indicator.py` | **Volume Profile Zones** — class `SupplyDemandIndicator` (LuxAlgo conversion). Builds volume-at-price profile by distributing bar volume across price bins, then scans top-down for supply and bottom-up for demand where cumulative volume crosses threshold. Key params: `threshold=10%`, `resolution=50`, `last_n_bars=200`. Output: `Zone` objects with top/bottom/avg/vwap. Methods: `run()`, `get_zones()`, `plot()`. |
| `liquidity_sweeps.py` | **Liquidity Sweep Detection** — class `LiquiditySweeps`. Identifies when price wicks through or breaks past pivot levels then reverses back, signaling institutional stop hunts. Two modes: `'wicks'` (wick pierces pivot, closes back) and `'outbreaks'` (close beyond pivot, later closes back). Output: `SweepEvent` with pivot price, sweep bar, direction, and box coordinates. Key params: `swing_len=5`, `mode='wicks'`, `max_bars=300`. |
| `macd_indicator.py` | **MACD with 4-Color Histogram** — class `MACDIndicator` (TradingView-faithful). Histogram uses 4 states: green-strong (positive + rising), green-weak (positive + falling), red-weak (negative + rising), red-strong (negative + falling). Generates crossover alerts for buy/sell signals. Methods: `run()`, `get_data()`, `get_alerts()`, `plot()`. |

### LLM-Powered Detection

| File | What It Does |
|------|-------------|
| `llm_pattern_detector.py` | Class `LLMPatternDetector`. Sends OHLCV data to OpenRouter LLM (`openai/gpt-oss-120b`, temperature=0.1) for three tasks: **(A)** Fair Value Gap detection with gap size validation (>0.1%), fill status, and confidence scoring, **(B)** candlestick pattern recognition on last 15 candles, **(C)** RSI/MACD/support-resistance levels. Has a full **fallback chain** that uses `SupplyDemandIndicator` + `SMCIndicator` + `LiquiditySweeps` + `MACDIndicator` when LLM fails or returns no results. |
| `chat_drawing_agent.py` | Class `ChatDrawingAgent`. Natural language interface — parses user messages like "show me supply demand zones and FVGs" into structured intents using LLM, with keyword-based fallback. Maps keywords to drawing types (e.g., "sweep" -> `liquidity_sweeps`, "smc" -> `smc`). Key method: `generate_from_chat(user_message, symbol, timeframe)`. |

### JSON Output & Orchestration

| File | What It Does |
|------|-------------|
| `json_builder.py` | Converts all detections into TradingView drawing JSON. Zones become `LineToolRectangle` (red=supply, green=demand), patterns become `LineToolNote` markers (positioned above/below candle based on signal), indicators become `TrendLine` objects. Every drawing has: `id`, `type`, `state` (colors, text, visibility), `points` (price + unix timestamp), `metadata` (validation, strength, reason). Key function: `build_drawing_json(symbol, zones, patterns, bollinger, rsi, macd, levels)`. |
| `drawing_generator.py` | **Main orchestrator for rule-based pipeline**. Coordinates: resolve symbol -> fetch data -> run selected detectors -> build JSON. Key function: `generate_drawings(symbol, timeframe, period, tasks, use_api, api_config)`. Convenience wrappers: `generate_zones_only()`, `generate_patterns_only()`, `generate_indicators_only()`, `generate_complete_analysis()`. The `tasks` param controls which detectors run: `["zones", "patterns", "bollinger", "rsi", "macd", "levels"]`. |
| `llm_drawing_generator.py` | **Orchestrator for AI-powered pipeline**. Uses LLM analysis first, then fills gaps with fallback indicators. If LLM returns no zones, adds from `SupplyDemandIndicator`. If no FVGs, adds from fallback. Always includes SMC, liquidity sweeps, and MACD data. Returns drawings + candle data + validation stats. Key function: `generate_drawings_with_llm(symbol, timeframe, use_api, api_config)`. |
| `api_server.py` | Flask REST API (port 5001) with web dashboard. Endpoints: `POST /api/generate` (full analysis), `POST /api/zones`, `POST /api/patterns`, `POST /api/indicators`. Request body accepts `symbol`, `timeframe`, `period`, `tasks`, `use_api`, `api_config`. |
| `__init__.py` | Public API exports: `fetch_price_data`, `detect_supply_demand_zones`, `detect_candlestick_patterns`, `calculate_bollinger_bands`, `build_drawing_json`. |

### Reference Docs

| File | What It Does |
|------|-------------|
| `ZONE_VALIDATION_GUIDE.md` | Detailed methodology document explaining the 3-step institutional zone validation logic. |
| `requirements.txt` | Module-specific dependencies: yfinance, pandas, numpy, flask, flask-cors, python-dateutil. |

---

## How to Run

### CLI — Generate drawings to JSON file

```bash
# From the project root
python -m drawing_instruction.drawing_generator RELIANCE.NS 1d 1y
# Output: drawing_output_RELIANCE.NS_1d.json
```

### Python — Import and call directly

```python
from drawing_instruction.drawing_generator import generate_complete_analysis

# Rule-based analysis
result = generate_complete_analysis("TCS.NS", timeframe="1d", period="1y")
print(f"Generated {result['total_drawings']} drawings")

# Only zones
from drawing_instruction.drawing_generator import generate_zones_only
zones = generate_zones_only("RELIANCE.NS", timeframe="1d", period="6mo")

# LLM-powered analysis (uses AI + fallback indicators)
from drawing_instruction.llm_drawing_generator import generate_drawings_with_llm
result = generate_drawings_with_llm("INFY.NS", timeframe="1d")

# Chat-based (natural language)
from drawing_instruction.chat_drawing_agent import ChatDrawingAgent
agent = ChatDrawingAgent()
result = agent.generate_from_chat("show me supply demand zones and FVGs", symbol="TCS.NS", timeframe="1d")
```

### Flask API

```bash
python -m drawing_instruction.api_server
# Dashboard: http://localhost:5001
```

```bash
# POST request example
curl -X POST http://localhost:5001/api/generate \
  -H "Content-Type: application/json" \
  -d '{"symbol": "RELIANCE.NS", "timeframe": "1d", "period": "1y", "tasks": ["zones", "patterns"]}'
```

### Using external API data source instead of yfinance

```python
result = generate_complete_analysis(
    "RELIANCE",
    timeframe="1d",
    period="1y",
    use_api=True,
    api_config={
        "base_url": "http://192.168.0.126:8000",
        "bearer_token": "your-token",
        "csrf_token": "your-csrf",
        "from_date": "2025-01-01",
        "to_date": "2026-03-03",
        "market": "stocks"
    }
)
```

### Streamlit Integration

The module is integrated into the main app's sidebar under "Drawing Generator":

```bash
streamlit run app_advanced.py
# Then select Drawing Generator from sidebar
```

---

## Output JSON Format

Every drawing object follows TradingView's format:

```json
{
  "id": "unique-uuid",
  "type": "LineToolRectangle",
  "state": {
    "symbol": "NSE:RELIANCE",
    "interval": "1D",
    "fillColor": "#FF5252",
    "transparency": 80,
    "text": "SUPPLY ZONE",
    "visible": true
  },
  "points": [
    { "price": 2450.50, "time_t": 1710000000, "offset": 0 },
    { "price": 2430.00, "time_t": 1710500000, "offset": 0 }
  ],
  "zorder": 0,
  "metadata": {
    "zone_type": "supply",
    "impulse_strength": 2.5,
    "is_fresh": true,
    "reason": "DBD pattern: 4-candle base, impulse 2.5x base range, clean departure",
    "validation": {
      "base_tight": true,
      "impulse_strong": true,
      "departure_clean": true,
      "all_criteria_met": true
    }
  }
}
```

Drawing types used: `LineToolRectangle` (zones), `LineToolNote` (pattern markers), `TrendLine` (indicator lines/bands).

---

## Two Analysis Pipelines

### 1. Rule-Based Pipeline (`drawing_generator.py`)

Uses deterministic algorithms only. You pick which tasks to run:

| Task | Detector | What It Finds |
|------|----------|---------------|
| `zones` | `zone_detector.py` | Supply/demand zones with 3-step institutional validation |
| `patterns` | `pattern_detector.py` | 15+ candlestick patterns (hammer, engulfing, doji, star, etc.) |
| `bollinger` | `indicator_calculator.py` | Bollinger Bands with squeeze detection |
| `rsi` | `indicator_calculator.py` | RSI overbought/oversold signals |
| `macd` | `indicator_calculator.py` | MACD crossovers |
| `levels` | `indicator_calculator.py` | Key support/resistance levels |

### 2. LLM-Powered Pipeline (`llm_drawing_generator.py`)

Sends OHLCV data to OpenRouter LLM for analysis, then fills gaps with fallback indicators:

1. LLM analyzes candle data for FVGs, patterns, and indicator levels
2. If LLM returns no zones -> `SupplyDemandIndicator` (volume profile) fills in
3. If LLM returns no FVGs -> fallback analysis adds them
4. Always appends: SMC structures, liquidity sweeps, MACD data
5. Builds combined TradingView JSON

The fallback chain ensures you always get results even if the LLM call fails or times out.

---

## Key Detection Algorithms

### Supply/Demand Zone Validation (zone_detector.py)

Three-step institutional methodology. A zone is only marked valid when ALL three pass:

1. **Base Formation** — tight sideways consolidation where institutional orders accumulate
   - Min 3 candles, max 10
   - Range < 1.5x ATR(14)
   - Body-to-range ratio < 0.5

2. **Impulse Move** — explosive breakout proving order imbalance
   - Range > 2x base range
   - Body-to-range ratio > 0.4

3. **Departure Speed** — clean exit confirming strong rejection
   - Wick ratio < 25% of base range
   - No retests within 3 candles

Zone types: **RBR** (Rally-Base-Rally = demand), **DBD** (Drop-Base-Drop = supply).

### Smart Money Concepts (smc_indicator.py)

Detects institutional footprints: Break Of Structure (BOS) for trend continuation, Change of Character (CHoCH) for reversals, Order Blocks where institutions placed large orders, Fair Value Gaps showing price imbalance, and Equal Highs/Lows marking liquidity pools.

### Liquidity Sweeps (liquidity_sweeps.py)

Identifies stop hunts where price wicks through or breaks past a pivot level then reverses back. Two detection modes: wick sweeps (intra-bar) and outbreak retests (close beyond, then return).

---

## Adding a New Indicator or Detector

1. Create your detector function/class in a new `.py` file in this folder
2. It should accept a pandas DataFrame (OHLCV) and return a list of detection dicts
3. Add a builder function in `json_builder.py` to convert detections to TradingView JSON
4. Wire it into `drawing_generator.py` — add a new task name and call your detector when that task is selected
5. Export from `__init__.py` if it should be part of the public API

---

## Environment Variables

The LLM-powered features require these (loaded from `.env` in project root):

- `OPENROUTER_API_KEY` — for LLM calls in `llm_pattern_detector.py` and `chat_drawing_agent.py`
- `OPENROUTER_BASE_URL` — OpenRouter endpoint (default: `https://openrouter.ai/api/v1`)

The rule-based pipeline (`drawing_generator.py`) has no env var requirements — it only needs yfinance (public API).

The external API data source (`api_price_fetcher.py`) requires bearer/CSRF tokens passed at runtime, not from env vars.
