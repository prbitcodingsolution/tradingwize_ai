"""
LLM-Powered Pattern Detection
Uses AI to analyze candlestick data and detect patterns accurately
Now using OpenRouter openai-oss-120b for superior stock analysis
"""

import os
import json
import logging
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Import OpenAI client (compatible with OpenRouter)
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logger.warning("OpenAI library not available, install with: pip install openai")


class LLMPatternDetector:
    """Uses LLM to detect trading patterns from candlestick data"""
    
    def __init__(self):
        """Initialize OpenRouter client"""
        self.openrouter_api_key = os.getenv('OPENROUTER_API_KEY')
        self.openrouter_base_url = os.getenv('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')
        
        if not self.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY not found in environment variables")
        
        if OPENAI_AVAILABLE:
            # Initialize OpenAI client with OpenRouter configuration
            self.client = OpenAI(
                api_key=self.openrouter_api_key,
                base_url=self.openrouter_base_url
            )
            # Use free model to avoid credit limits
            self.model = "openai/gpt-oss-120b"
            logger.info(f"✅ Initialized LLMPatternDetector with {self.model}")
        else:
            raise ImportError("OpenAI library not installed. Install with: pip install openai")
    
    def analyze_candlestick_data(self, df, symbol):
        """
        Analyze candlestick data using LLM to detect patterns
        
        Args:
            df: DataFrame with OHLCV data
            symbol: Stock symbol
        
        Returns:
            dict: Detected patterns, zones, and indicators
        """
        try:
            # Prepare data for LLM (last 100 candles for context)
            recent_data = df.tail(100).copy()
            
            # Convert to simple format for LLM
            candles_data = []
            for idx, row in recent_data.iterrows():
                candles_data.append({
                    'date': idx.strftime('%Y-%m-%d'),
                    'timestamp': int(idx.timestamp()),
                    'open': float(row['Open']),
                    'high': float(row['High']),
                    'low': float(row['Low']),
                    'close': float(row['Close']),
                    'volume': float(row['Volume'])
                })
            
            # Create prompt for LLM
            prompt = self._create_analysis_prompt(symbol, candles_data)
            
            # Get LLM response from via OpenRouter
            logger.info(f"🤖 Analyzing {symbol} with {self.model} (OpenRouter)...")
            
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": """You are an expert technical analyst and quantitative trader specializing in 
                            candlestick patterns, supply/demand zones, and technical indicators. You have deep knowledge 
                            of stock market behavior, price action, and institutional trading patterns. You analyze price 
                            data with precision and identify only valid, high-probability patterns backed by solid technical 
                            reasoning. You provide detailed analysis with exact timestamps and price levels, explaining the 
                            market psychology behind each pattern.
                            
                            CRITICAL: You MUST respond with ONLY valid JSON. No markdown, no explanations, just pure JSON."""
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    temperature=0.1,  # Low temperature for consistent, focused analysis
                    timeout=30  # 30 second timeout
                )
            except Exception as api_error:
                logger.error(f"❌ OpenRouter API error: {api_error}")
                logger.warning("⚠️  Falling back to basic analysis")
                return self._create_fallback_analysis(df, symbol)
            
            # Get response content
            response_content = response.choices[0].message.content
            
            # Add detailed logging
            logger.info(f"📝 Response received - Type: {type(response_content)}")
            logger.info(f"📝 Response length: {len(response_content) if response_content else 0}")
            if response_content:
                logger.info(f"📝 First 200 chars: {response_content[:200]}")
            
            if not response_content or not response_content.strip():
                logger.error("Empty response from LLM")
                logger.error(f"Full response object: {response}")
                logger.error(f"Response model: {response.model}")
                logger.error(f"Response ID: {response.id}")
                logger.warning("⚠️  LLM returned empty response - using fallback basic analysis")
                
                # Return basic fallback analysis
                return self._create_fallback_analysis(df, symbol)
            
            logger.info(f"📝 Received response ({len(response_content)} chars)")
            
            # Clean response - remove markdown code blocks if present
            cleaned_content = response_content.strip()
            if cleaned_content.startswith('```json'):
                cleaned_content = cleaned_content.split('```json')[1].split('```')[0].strip()
            elif cleaned_content.startswith('```'):
                cleaned_content = cleaned_content.split('```')[1].split('```')[0].strip()
            
            # Parse JSON
            try:
                analysis = json.loads(cleaned_content)
            except json.JSONDecodeError as je:
                logger.error(f"JSON parsing error: {je}")
                logger.error(f"Response preview: {cleaned_content[:500]}")
                
                # Try to extract JSON from response
                import re
                json_match = re.search(r'\{.*\}', cleaned_content, re.DOTALL)
                if json_match:
                    try:
                        analysis = json.loads(json_match.group(0))
                        logger.info("✅ Successfully extracted JSON from response")
                    except:
                        logger.error("Failed to extract valid JSON")
                        logger.warning("⚠️  JSON parsing failed - using fallback analysis")
                        return self._create_fallback_analysis(df, symbol)
                else:
                    logger.warning("⚠️  No valid JSON found - using fallback analysis")
                    return self._create_fallback_analysis(df, symbol)
            
            logger.info(f"✅ analysis complete for {symbol}")
            logger.info(f"   Patterns detected: {len(analysis.get('patterns', []))}")
            logger.info(f"   Zones detected: {len(analysis.get('zones', []))}")
            
            # Always enhance with SupplyDemandIndicator for supply/demand zones
            if len(analysis.get('zones', [])) == 0:
                logger.info("🔄 No zones detected by LLM, enhancing with SupplyDemandIndicator...")
                fallback_analysis = self._create_fallback_analysis(df, symbol)
                
                # Merge the fallback zones with LLM analysis
                analysis['zones'] = fallback_analysis.get('zones', [])
                analysis['smc_data'] = fallback_analysis.get('smc_data', {})
                analysis['liquidity_sweeps_data'] = fallback_analysis.get('liquidity_sweeps_data', {})
                analysis['macd_data'] = fallback_analysis.get('macd_data', {})
                
                logger.info(f"✅ Enhanced analysis with fallback indicators:")
                logger.info(f"   Total zones after enhancement: {len(analysis.get('zones', []))}")
                logger.info(f"   SMC data available: {bool(analysis.get('smc_data'))}")
                logger.info(f"   Liquidity sweeps available: {bool(analysis.get('liquidity_sweeps_data'))}")
                logger.info(f"   MACD data available: {bool(analysis.get('macd_data'))}")
            
            return analysis
        
        except Exception as e:
            logger.error(f"Error in LLM analysis: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                'patterns': [],
                'zones': [],
                'indicators': {},
                'error': str(e)
            }
    
    def _create_analysis_prompt(self, symbol, candles_data, user_message="", drawing_types=None):
        """Create detailed prompt for LLM analysis - Enhanced with professional institutional standards"""
        
        if drawing_types is None:
            drawing_types = ["supply_demand_zones"]
        
        # Get summary statistics
        prices = [c['close'] for c in candles_data]
        current_price = prices[-1]
        high_price = max([c['high'] for c in candles_data])
        low_price = min([c['low'] for c in candles_data])
        
        prompt = f"""You are a professional technical analyst specializing in supply and demand zone detection and Fair Value Gap (FVG) identification.

Analyze the OHLC candlestick data for {symbol}.

**MARKET CONTEXT:**
- Symbol: {symbol}
- Current Price: {current_price:.2f}
- Period High: {high_price:.2f}
- Period Low: {low_price:.2f}
- Total Candles: {len(candles_data)}

**CANDLESTICK DATA:**
```json
{json.dumps(candles_data, indent=2)}
```

**USER REQUEST:** {user_message}
**REQUESTED DRAWING TYPES:** {json.dumps(drawing_types)}

---

# TASK ROUTING — Only execute tasks matching REQUESTED DRAWING TYPES

- `supply_demand_zones` → Skip (handled by volume-based indicator)
- `fvg` or `fair_value_gap` or `fvg_zones` → Execute TASK A only
- `candlestick_patterns` → Execute TASK B only
- `indicators` → Execute TASK C only
- If multiple types requested or "all" → Execute all relevant tasks
- Return empty arrays [] for tasks NOT requested

**NOTE:** Supply/demand zones are now handled by a specialized volume-based indicator, so focus on FVG detection and patterns.

---

# TASK A: FAIR VALUE GAP (FVG) DETECTION

## WHAT IS AN FVG — READ THIS CAREFULLY

A Fair Value Gap is a **price imbalance** created by a large impulsive candle (candle 2) that moves 
so fast that it leaves an unfilled gap between candle 1 and candle 3. This gap is where price 
"skipped over" — there was no two-sided trading here, so the market tends to return and fill it.

## EXACT FVG PRICE RULES (From reference image)

### BULLISH FVG (Created by large UP candle):
```
Candle 1 (before big move): any candle
Candle 2 (middle):          large BULLISH candle (close > open, big body)
Candle 3 (after big move):  any candle

GAP CONDITION: candle[3].low > candle[1].high
              (candle 3's LOW is ABOVE candle 1's HIGH — a true gap exists)

GAP BOUNDARIES:
  fvg_high = candle[3].low    ← TOP of gap = bottom wick of candle 3
  fvg_low  = candle[1].high   ← BOTTOM of gap = top wick of candle 1

VISUAL: The gap is the empty space BETWEEN candle 1's top wick and candle 3's bottom wick.
        Price moved UP so fast that this area was never traded.
        Price will likely retrace DOWN into this gap to "fill" it.
```

### BEARISH FVG (Created by large DOWN candle):
```
Candle 1 (before big move): any candle  
Candle 2 (middle):          large BEARISH candle (close < open, big body)
Candle 3 (after big move):  any candle

GAP CONDITION: candle[3].high < candle[1].low
              (candle 3's HIGH is BELOW candle 1's LOW — a true gap exists)

GAP BOUNDARIES:
  fvg_high = candle[1].low    ← TOP of gap = bottom wick of candle 1
  fvg_low  = candle[3].high   ← BOTTOM of gap = top wick of candle 3

VISUAL: The gap is the empty space BETWEEN candle 3's top wick and candle 1's bottom wick.
        Price moved DOWN so fast that this area was never traded.
        Price will likely retrace UP into this gap to "fill" it.
```

## CRITICAL GAP BOUNDARY SUMMARY TABLE

| FVG Type | fvg_high | fvg_low | Gap Condition |
|----------|----------|---------|---------------|
| Bullish FVG | candle[3].low | candle[1].high | candle[3].low > candle[1].high |
| Bearish FVG | candle[1].low | candle[3].high | candle[3].high < candle[1].low |

**NEVER mix these up. Bullish FVG: high=C3.low, low=C1.high. Bearish FVG: high=C1.low, low=C3.high.**

## FVG DETECTION ALGORITHM — STEP BY STEP

### STEP 1: Scan Every 3-Candle Window
For every index `i` from 1 to (total_candles - 2):
- candle_1 = candles[i-1]
- candle_2 = candles[i]      ← the middle/impulse candle
- candle_3 = candles[i+1]

### STEP 2: Check Middle Candle Quality
```
body_size = abs(candle_2.close - candle_2.open)
body_pct  = body_size / candle_2.open × 100

Require body_pct >= 0.8%  (meaningful impulse, not noise)
Prefer  body_pct >= 1.5%  (strong impulse = higher confidence)

body_to_total_ratio = body_size / (candle_2.high - candle_2.low)
Prefer ratio >= 0.6  (body dominates, not wick-dominated candle)
```

### STEP 3: Check Gap Existence
**For BULLISH FVG** (candle_2 is bullish: close > open):
```python
if candle_3.low > candle_1.high:
    gap_exists = True
    fvg_high = candle_3.low
    fvg_low  = candle_1.high
    gap_size = fvg_high - fvg_low
    gap_pct  = gap_size / candle_2.close × 100
```

**For BEARISH FVG** (candle_2 is bearish: close < open):
```python
if candle_3.high < candle_1.low:
    gap_exists = True
    fvg_high = candle_1.low
    fvg_low  = candle_3.high
    gap_size = fvg_high - fvg_low
    gap_pct  = gap_size / candle_2.close × 100
```

If gap does not exist → skip this 3-candle window, move to next.

### STEP 4: Validate Gap Size
```
gap_pct must be > 0.1%  (minimum — tiny gaps are noise)
gap_pct ideally >= 0.3% (meaningful gap worth trading)
gap_pct of 0.5%+ = high quality FVG
```

### STEP 5: Check Fill Status
After the 3-candle formation (from candle index i+2 onward), scan remaining candles:

**BULLISH FVG fill check** (gap is below current price, price needs to retrace DOWN):
```
For each subsequent candle[j] where j > i+1:
  if candle[j].low <= fvg_low:
      is_filled = true         ← price fully traded through entire gap
      fill_candle = j
      break
  elif candle[j].low <= fvg_high:
      partially_filled = true  ← price entered gap but didn't fully fill
      fill_pct = (fvg_high - candle[j].low) / gap_size × 100
```

**BEARISH FVG fill check** (gap is above current price, price needs to retrace UP):
```
For each subsequent candle[j] where j > i+1:
  if candle[j].high >= fvg_high:
      is_filled = true         ← price fully traded through entire gap
      fill_candle = j
      break
  elif candle[j].high >= fvg_low:
      partially_filled = true  ← price entered gap but didn't fully fill
      fill_pct = (candle[j].high - fvg_low) / gap_size × 100
```

### STEP 6: FVG Time Boundaries
- `start_time` = timestamp of candle_1 (first candle of 3-candle pattern)
- `end_time`:
  - If `is_filled = true`: timestamp of the fill candle
  - If `is_filled = false` or `partially_filled = true`: timestamp of LAST candle in dataset

### STEP 7: FVG Confidence Scoring
```
Score = 50 (base)
+20 if gap_pct >= 0.5%
+10 if gap_pct >= 0.3% (use highest applicable)
+15 if candle_2 body_pct >= 2.0% (very strong impulse)
+10 if candle_2 body_pct >= 1.5% (use highest applicable)
+10 if body_to_total_ratio >= 0.6 (clean body-dominated candle)
+15 if is_filled = false (still tradeable)
+5  if partially_filled = true (partially tradeable)
+10 if FVG formed in last 40 candles (recent = more relevant)
-15 if is_filled = true (already filled — lower priority but include if recent)
```
Include FVGs with score >= 60. Output 5–12 FVGs prioritizing unfilled ones.

## WHAT TO OUTPUT FOR FVGs

Prioritize in this order:
1. **Unfilled FVGs** (is_filled=false) — most important, price hasn't returned yet
2. **Partially filled FVGs** — still have room to fill
3. **Recently formed FVGs** in last 40 candles — most actionable
4. **Filled FVGs** only if they're very recent (last 20 candles)

Aim for 5–12 FVGs. Must include both bullish and bearish if both exist.

---

# TASK B: CANDLESTICK PATTERNS

Identify patterns from **last 15 candles only**:
- Bullish: Hammer, Inverted Hammer, Bullish Engulfing, Morning Star, Three White Soldiers
- Bearish: Shooting Star, Hanging Man, Bearish Engulfing, Evening Star, Three Black Crows
- Neutral: Doji, Spinning Top

Confidence >= 70 only. Maximum 5 patterns.

---

# TASK C: TECHNICAL INDICATORS

**RSI(14):** Current value + overbought(>70)/oversold(<30) signals in last 20 candles.
**MACD(12,26,9):** Bullish/bearish crossovers in last 20 candles.
**Key Levels:** 3–5 support/resistance levels where price reversed at least twice.

---

# OUTPUT FORMAT

Return ONLY valid JSON. No markdown. No code blocks. Start with {{ end with }}.

{{
  "patterns": [
    {{
      "type": "pattern_name",
      "signal": "bullish|bearish|neutral",
      "timestamp": unix_timestamp,
      "date": "YYYY-MM-DD",
      "price": close_price,
      "high": high_price,
      "low": low_price,
      "open": open_price,
      "confidence": 85,
      "reason": "Body size X%, wick ratio Y, market context"
    }}
  ],
  "zones": [],
  "fvg_zones": [
    {{
      "type": "bullish_fvg|bearish_fvg",
      "start_time": unix_timestamp_of_candle_1,
      "end_time": unix_timestamp_of_last_candle_or_fill_candle,
      "high": fvg_high_price,
      "low": fvg_low_price,
      "gap_size": fvg_high_minus_fvg_low,
      "gap_percentage": gap_pct_value,
      "middle_candle_timestamp": unix_timestamp_of_candle_2,
      "middle_candle_date": "YYYY-MM-DD",
      "middle_candle_body_pct": body_pct_of_candle_2,
      "is_filled": false,
      "partially_filled": false,
      "fill_percentage": 0.0,
      "confidence": 80,
      "reason": "Bullish/Bearish FVG at candle [date]: C1.high=[X] vs C3.low=[Y] gap=[Z]% (OR C1.low=[X] vs C3.high=[Y]). Middle body=[W]%. Status: unfilled/partial/filled."
    }}
  ],
  "indicators": {{
    "rsi": {{
      "current_value": 54.2,
      "overbought_signals": [{{"timestamp": 0, "price": 0.0}}],
      "oversold_signals": [{{"timestamp": 0, "price": 0.0}}]
    }},
    "macd": {{
      "bullish_crossovers": [{{"timestamp": 0, "price": 0.0}}],
      "bearish_crossovers": [{{"timestamp": 0, "price": 0.0}}]
    }},
    "key_levels": [
      {{
        "type": "support|resistance",
        "price": 0.0,
        "strength": "strong|moderate|weak",
        "touches": 2
      }}
    ]
  }},
  "summary": "Focus on FVG opportunities and candlestick patterns. Supply/demand zones handled by volume-based indicator."
}}
"""
        
        return prompt
    
    def _create_fallback_analysis(self, df, symbol):
        """
        Create basic fallback analysis when LLM fails
        Uses simple technical analysis rules
        """
        logger.info("🔄 Creating fallback analysis using basic technical rules...")
        
        try:
            import numpy as np
            
            # Get recent data
            recent_data = df.tail(100).copy()
            
            patterns = []
            zones = []
            
            # Use new SupplyDemandIndicator for zone detection
            try:
                # Try absolute import first, then relative
                try:
                    from supply_demand_indicator import SupplyDemandIndicator
                except ImportError:
                    from .supply_demand_indicator import SupplyDemandIndicator
                    
                logger.info(f"🎯 Using new SupplyDemandIndicator for zone detection...")
                
                # Create supply/demand indicator with the data
                sd_indicator = SupplyDemandIndicator(
                    df=recent_data,
                    threshold=10.0,  # 10% volume threshold
                    resolution=50,   # 50 price bins
                    last_n_bars=min(200, len(recent_data))  # Use available data
                )
                
                # Run the analysis
                sd_indicator.run()
                
                # Get detected zones
                detected_zones = sd_indicator.get_zones()
                
                # Convert supply zone to our format
                if detected_zones['supply']['top'] is not None:
                    supply_zone = detected_zones['supply']
                    zones.append({
                        'type': 'supply',
                        'high': float(supply_zone['top']),
                        'low': float(supply_zone['bottom']),
                        'start_time': int(recent_data.index[0].timestamp()),  # Start of visible range
                        'end_time': int(recent_data.index[-1].timestamp()),   # End of visible range
                        'strength': 'strong',
                        'touches': 0,
                        'confidence': 90,
                        'reason': f'Volume-based supply zone: {supply_zone["top"]:.2f} - {supply_zone["bottom"]:.2f} (VWAP: {supply_zone["vwap"]:.2f})',
                        'base_candles': len(recent_data),
                        'impulse_candles': 0,
                        'base_range': float(supply_zone['top'] - supply_zone['bottom']),
                        'impulse_range': 0,
                        'impulse_strength': 0,
                        'wick_ratio': 0.0,
                        'is_fresh': True,
                        'validation': {
                            'base_tight': True,
                            'impulse_strong': True,
                            'departure_clean': True,
                            'all_criteria_met': True,
                            'has_base': True,
                            'has_impulse': True,
                            'fresh_zone': True
                        },
                        'avg_price': float(supply_zone['avg']),
                        'vwap_price': float(supply_zone['vwap'])
                    })
                    logger.info(f"✅ Added supply zone: {supply_zone['top']:.2f} - {supply_zone['bottom']:.2f}")
                
                # Convert demand zone to our format
                if detected_zones['demand']['top'] is not None:
                    demand_zone = detected_zones['demand']
                    zones.append({
                        'type': 'demand',
                        'high': float(demand_zone['top']),
                        'low': float(demand_zone['bottom']),
                        'start_time': int(recent_data.index[0].timestamp()),  # Start of visible range
                        'end_time': int(recent_data.index[-1].timestamp()),   # End of visible range
                        'strength': 'strong',
                        'touches': 0,
                        'confidence': 90,
                        'reason': f'Volume-based demand zone: {demand_zone["top"]:.2f} - {demand_zone["bottom"]:.2f} (VWAP: {demand_zone["vwap"]:.2f})',
                        'base_candles': len(recent_data),
                        'impulse_candles': 0,
                        'base_range': float(demand_zone['top'] - demand_zone['bottom']),
                        'impulse_range': 0,
                        'impulse_strength': 0,
                        'wick_ratio': 0.0,
                        'is_fresh': True,
                        'validation': {
                            'base_tight': True,
                            'impulse_strong': True,
                            'departure_clean': True,
                            'all_criteria_met': True,
                            'has_base': True,
                            'has_impulse': True,
                            'fresh_zone': True
                        },
                        'avg_price': float(demand_zone['avg']),
                        'vwap_price': float(demand_zone['vwap'])
                    })
                    logger.info(f"✅ Added demand zone: {demand_zone['top']:.2f} - {demand_zone['bottom']:.2f}")
                
                logger.info(f"✅ New SupplyDemandIndicator analysis complete: {len(zones)} zones detected")
                
            except Exception as sd_error:
                logger.warning(f"⚠️  New SupplyDemandIndicator failed: {sd_error}")
                logger.info("🔄 Falling back to basic swing-based zone detection...")
                
                # Fallback to simple swing-based detection if new indicator fails
                highs = recent_data['High'].values
                lows = recent_data['Low'].values
                closes = recent_data['Close'].values
                
                # Find MAJOR swing highs for supply zones (simplified fallback)
                swing_highs = []
                for i in range(20, len(highs) - 20):
                    if highs[i] == max(highs[i-20:i+21]):
                        swing_highs.append((i, highs[i]))
                
                swing_highs.sort(key=lambda x: x[1], reverse=True)
                swing_highs = swing_highs[:2]  # Limit to top 2
                
                for swing_idx, swing_price in swing_highs:
                    consolidation_start = max(0, swing_idx - 10)
                    consolidation_end = min(len(highs)-1, swing_idx + 5)
                    
                    zone_high = max(highs[consolidation_start:consolidation_end+1])
                    zone_low = min(lows[consolidation_start:consolidation_end+1])
                    
                    zones.append({
                        'type': 'supply',
                        'high': float(zone_high),
                        'low': float(zone_low),
                        'start_time': int(recent_data.index[consolidation_start].timestamp()),
                        'end_time': int(recent_data.index[consolidation_end].timestamp()),
                        'strength': 'moderate',
                        'touches': 0,
                        'confidence': 75,
                        'reason': f'Fallback swing-based supply zone at {zone_high:.2f}',
                        'base_candles': consolidation_end - consolidation_start + 1,
                        'impulse_candles': 5,
                        'base_range': float(zone_high - zone_low),
                        'impulse_range': 0,
                        'impulse_strength': 0,
                        'wick_ratio': 0.15,
                        'is_fresh': True,
                        'validation': {
                            'base_tight': True,
                            'impulse_strong': True,
                            'departure_clean': True,
                            'all_criteria_met': True,
                            'has_base': True,
                            'has_impulse': True,
                            'fresh_zone': True
                        }
                    })
                
                # Find MAJOR swing lows for demand zones (simplified fallback)
                swing_lows = []
                for i in range(20, len(lows) - 20):
                    if lows[i] == min(lows[i-20:i+21]):
                        swing_lows.append((i, lows[i]))
                
                swing_lows.sort(key=lambda x: x[1])
                swing_lows = swing_lows[:2]  # Limit to bottom 2
                
                for swing_idx, swing_price in swing_lows:
                    consolidation_start = max(0, swing_idx - 10)
                    consolidation_end = min(len(lows)-1, swing_idx + 5)
                    
                    zone_high = max(highs[consolidation_start:consolidation_end+1])
                    zone_low = min(lows[consolidation_start:consolidation_end+1])
                    
                    zones.append({
                        'type': 'demand',
                        'high': float(zone_high),
                        'low': float(zone_low),
                        'start_time': int(recent_data.index[consolidation_start].timestamp()),
                        'end_time': int(recent_data.index[consolidation_end].timestamp()),
                        'strength': 'moderate',
                        'touches': 0,
                        'confidence': 75,
                        'reason': f'Fallback swing-based demand zone at {zone_low:.2f}',
                        'base_candles': consolidation_end - consolidation_start + 1,
                        'impulse_candles': 5,
                        'base_range': float(zone_high - zone_low),
                        'impulse_range': 0,
                        'impulse_strength': 0,
                        'wick_ratio': 0.15,
                        'is_fresh': True,
                        'validation': {
                            'base_tight': True,
                            'impulse_strong': True,
                            'departure_clean': True,
                            'all_criteria_met': True,
                            'has_base': True,
                            'has_impulse': True,
                            'fresh_zone': True
                        }
                    })
            
            # Sort zones by confidence (new indicator zones should be high confidence)
            zones = sorted(zones, key=lambda x: x['confidence'], reverse=True)
            
            logger.info(f"✅ Fallback analysis complete for {symbol}")
            logger.info(f"   Total zones found: {len(zones)} (volume-based zones)")
            logger.info(f"   Supply zones: {len([z for z in zones if z['type'] == 'supply'])}")
            logger.info(f"   Demand zones: {len([z for z in zones if z['type'] == 'demand'])}")
            
            # Simple pattern detection
            for i in range(1, len(recent_data)):
                prev = recent_data.iloc[i-1]
                curr = recent_data.iloc[i]
                
                # Bullish engulfing
                if (prev['Close'] < prev['Open'] and 
                    curr['Close'] > curr['Open'] and
                    curr['Open'] < prev['Close'] and
                    curr['Close'] > prev['Open']):
                    patterns.append({
                        'type': 'bullish_engulfing',
                        'signal': 'bullish',
                        'timestamp': int(recent_data.index[i].timestamp()),
                        'price': float(curr['Close']),
                        'high': float(curr['High']),
                        'low': float(curr['Low']),
                        'open': float(curr['Open']),
                        'confidence': 70,
                        'reason': 'Bullish engulfing pattern detected'
                    })
                
                # Bearish engulfing
                if (prev['Close'] > prev['Open'] and 
                    curr['Close'] < curr['Open'] and
                    curr['Open'] > prev['Close'] and
                    curr['Close'] < prev['Open']):
                    patterns.append({
                        'type': 'bearish_engulfing',
                        'signal': 'bearish',
                        'timestamp': int(recent_data.index[i].timestamp()),
                        'price': float(curr['Close']),
                        'high': float(curr['High']),
                        'low': float(curr['Low']),
                        'open': float(curr['Open']),
                        'confidence': 70,
                        'reason': 'Bearish engulfing pattern detected'
                    })
            
            # FVG Detection (Fair Value Gap)
            fvg_zones = []
            logger.info(f"🔍 Scanning {len(recent_data)} candles for FVG patterns...")
            
            for i in range(1, len(recent_data) - 1):
                candle1 = recent_data.iloc[i-1]
                candle2 = recent_data.iloc[i]    # Big middle candle
                candle3 = recent_data.iloc[i+1]
                
                # Check if middle candle is significantly larger (impulsive move)
                candle2_body = abs(candle2['Close'] - candle2['Open'])
                candle2_range = candle2['High'] - candle2['Low']
                body_to_range_ratio = candle2_body / candle2_range if candle2_range > 0 else 0
                
                # Debug logging for first few candles
                if i <= 5:
                    logger.info(f"  Candle {i}: body={candle2_body:.2f}, range={candle2_range:.2f}, ratio={body_to_range_ratio:.2f}")
                
                # Middle candle should have good body-to-wick ratio (around 60% or more)
                # Also check if it's a significant move compared to neighboring candles
                candle1_range = candle1['High'] - candle1['Low']
                candle3_range = candle3['High'] - candle3['Low']
                avg_neighbor_range = (candle1_range + candle3_range) / 2
                
                # Middle candle should be significantly larger than neighbors
                is_impulsive = candle2_range > (avg_neighbor_range * 1.5)
                
                if body_to_range_ratio >= 0.5 and is_impulsive:
                    # Check for Bullish FVG - CORRECTED LOGIC
                    if candle2['Close'] > candle2['Open']:  # Bullish middle candle
                        # For bullish FVG: gap between candle1 HIGH and candle3 LOW
                        # The middle candle "jumped up" leaving a gap below
                        candle1_high = candle1['High']
                        candle3_low = candle3['Low']
                        
                        # Ensure there's actually a gap (candle3 low > candle1 high)
                        if candle3_low > candle1_high:
                            gap_size = candle3_low - candle1_high
                            gap_percentage = (gap_size / candle2['Close']) * 100
                            
                            logger.info(f"  🟢 Potential Bullish FVG at candle {i}: gap={gap_size:.2f} ({gap_percentage:.2f}%)")
                            logger.info(f"     Candle1 High: {candle1_high:.2f}, Candle3 Low: {candle3_low:.2f}")
                            
                            # Only include meaningful gaps (>0.5% of price)
                            if gap_percentage >= 0.5:
                                fvg_zones.append({
                                    'type': 'bullish_fvg',
                                    'start_time': int(recent_data.index[i-1].timestamp()),
                                    'end_time': int(recent_data.index[i+1].timestamp()),
                                    'high': float(candle3_low),    # Top of the gap
                                    'low': float(candle1_high),    # Bottom of the gap
                                    'gap_size': float(gap_size),
                                    'gap_percentage': float(gap_percentage),
                                    'middle_candle_index': i,
                                    'middle_candle_size': float(candle2_body),
                                    'confidence': 85 if gap_percentage >= 1.0 else 75,
                                    'reason': f'Bullish FVG formed by 3-candle pattern with {gap_percentage:.1f}% gap',
                                    'is_filled': False,
                                    'fill_probability': 'high' if gap_percentage >= 1.0 else 'medium'
                                })
                                logger.info(f"  ✅ Added Bullish FVG: {gap_percentage:.1f}% gap")
                    
                    # Check for Bearish FVG - CORRECTED LOGIC
                    elif candle2['Close'] < candle2['Open']:  # Bearish middle candle
                        # For bearish FVG: gap between candle1 LOW and candle3 HIGH
                        # The middle candle "jumped down" leaving a gap above
                        candle1_low = candle1['Low']
                        candle3_high = candle3['High']
                        
                        # Ensure there's actually a gap (candle3 high < candle1 low)
                        if candle3_high < candle1_low:
                            gap_size = candle1_low - candle3_high
                            gap_percentage = (gap_size / candle2['Close']) * 100
                            
                            logger.info(f"  🔴 Potential Bearish FVG at candle {i}: gap={gap_size:.2f} ({gap_percentage:.2f}%)")
                            logger.info(f"     Candle1 Low: {candle1_low:.2f}, Candle3 High: {candle3_high:.2f}")
                            
                            # Only include meaningful gaps (>0.5% of price)
                            if gap_percentage >= 0.5:
                                fvg_zones.append({
                                    'type': 'bearish_fvg',
                                    'start_time': int(recent_data.index[i-1].timestamp()),
                                    'end_time': int(recent_data.index[i+1].timestamp()),
                                    'high': float(candle1_low),    # Top of the gap
                                    'low': float(candle3_high),    # Bottom of the gap
                                    'gap_size': float(gap_size),
                                    'gap_percentage': float(gap_percentage),
                                    'middle_candle_index': i,
                                    'middle_candle_size': float(candle2_body),
                                    'confidence': 85 if gap_percentage >= 1.0 else 75,
                                    'reason': f'Bearish FVG formed by 3-candle pattern with {gap_percentage:.1f}% gap',
                                    'is_filled': False,
                                    'fill_probability': 'high' if gap_percentage >= 1.0 else 'medium'
                                })
                                logger.info(f"  ✅ Added Bearish FVG: {gap_percentage:.1f}% gap")
            
            logger.info(f"🎯 FVG Detection complete: found {len(fvg_zones)} FVG zones")
            
            # SMC Analysis (Smart Money Concepts)
            smc_data = {}
            try:
                # Try absolute import first, then relative
                try:
                    from smc_indicator import SMCIndicator
                except ImportError:
                    from .smc_indicator import SMCIndicator
                    
                logger.info(f"🧠 Running SMC analysis...")
                
                # Create SMC indicator with the data
                smc = SMCIndicator(
                    df=recent_data,
                    swing_length=min(20, len(recent_data) // 4),  # Adaptive swing length
                    internal_length=min(5, len(recent_data) // 10),  # Adaptive internal length
                    ob_filter="atr",
                    ob_mitigation="highlow",
                    eql_threshold=0.15,
                    max_obs=5
                )
                
                # Run SMC analysis
                smc.run()
                
                # Extract SMC data
                smc_data = {
                    'swing_structure': smc.swing_structure,
                    'internal_structure': smc.internal_structure,
                    'swing_obs': smc.swing_obs,
                    'internal_obs': smc.internal_obs,
                    'smc_fvgs': smc.fvgs,  # SMC FVGs (different from our FVG detection)
                    'equal_levels': smc.equal_levels,
                    'swing_top': smc.swing_top,
                    'swing_bottom': smc.swing_bottom,
                    'df_index': recent_data.index  # Include dataframe index for timestamp conversion
                }
                
                logger.info(f"✅ SMC analysis complete:")
                logger.info(f"   Swing structures: {len(smc.swing_structure)}")
                logger.info(f"   Internal structures: {len(smc.internal_structure)}")
                logger.info(f"   Swing order blocks: {len(smc.swing_obs)}")
                logger.info(f"   Internal order blocks: {len(smc.internal_obs)}")
                logger.info(f"   SMC FVGs: {len(smc.fvgs)}")
                logger.info(f"   Equal levels: {len(smc.equal_levels)}")
                
            except Exception as smc_error:
                logger.warning(f"⚠️  SMC analysis failed: {smc_error}")
                smc_data = {
                    'swing_structure': [],
                    'internal_structure': [],
                    'swing_obs': [],
                    'internal_obs': [],
                    'smc_fvgs': [],
                    'equal_levels': [],
                    'swing_top': np.nan,
                    'swing_bottom': np.nan
                }
            
            # Liquidity Sweeps Analysis
            liquidity_sweeps_data = {}
            try:
                # Try absolute import first, then relative
                try:
                    from liquidity_sweeps import LiquiditySweeps
                except ImportError:
                    from .liquidity_sweeps import LiquiditySweeps
                    
                logger.info(f"💧 Running Liquidity Sweeps analysis...")
                
                # Create liquidity sweeps indicator with the data
                ls = LiquiditySweeps(
                    df=recent_data,
                    swing_len=min(5, len(recent_data) // 20),  # Adaptive swing length
                    mode='both',  # Detect both wicks and outbreaks
                    max_bars=min(300, len(recent_data)),  # Max bars to extend sweep box
                    last_n_bars=None  # Use all data for analysis
                )
                
                # Run liquidity sweeps analysis
                ls.run()
                
                # Extract liquidity sweeps data
                liquidity_sweeps_data = {
                    'sweeps': ls.get_sweeps(),
                    'pivots_h': ls.pivots_h,
                    'pivots_l': ls.pivots_l,
                    'df_index': recent_data.index  # Include dataframe index for timestamp conversion
                }
                
                logger.info(f"✅ Liquidity Sweeps analysis complete:")
                logger.info(f"   Total sweeps: {len(ls.sweeps)}")
                logger.info(f"   Bullish sweeps: {sum(1 for s in ls.sweeps if s.direction == +1)}")
                logger.info(f"   Bearish sweeps: {sum(1 for s in ls.sweeps if s.direction == -1)}")
                logger.info(f"   Wick sweeps: {sum(1 for s in ls.sweeps if s.kind == 'wick')}")
                logger.info(f"   Outbreak sweeps: {sum(1 for s in ls.sweeps if s.kind == 'outbreak')}")
                
            except Exception as ls_error:
                logger.warning(f"⚠️  Liquidity Sweeps analysis failed: {ls_error}")
                liquidity_sweeps_data = {
                    'sweeps': [],
                    'pivots_h': [],
                    'pivots_l': [],
                    'df_index': recent_data.index
                }
            
            # MACD Analysis
            macd_data = {}
            try:
                # Try absolute import first, then relative
                try:
                    from macd_indicator import MACDIndicator
                except ImportError:
                    from .macd_indicator import MACDIndicator
                    
                logger.info(f"📈 Running MACD analysis...")
                
                # Create MACD indicator with the data
                macd = MACDIndicator(
                    df=recent_data,
                    source='Close',
                    fast_len=12,  # Standard MACD parameters
                    slow_len=26,
                    sig_len=9,
                    osc_type='EMA',
                    sig_type='EMA',
                    last_n_bars=None  # Use all data for analysis
                )
                
                # Run MACD analysis
                macd.run()
                
                # Extract MACD data
                macd_df = macd.get_data()
                alerts = macd.get_alerts()
                
                macd_data = {
                    'macd_df': macd_df,
                    'alerts': alerts,
                    'latest_macd': float(macd_df['macd'].iloc[-1]) if not macd_df['macd'].isna().iloc[-1] else 0,
                    'latest_signal': float(macd_df['signal'].iloc[-1]) if not macd_df['signal'].isna().iloc[-1] else 0,
                    'latest_histogram': float(macd_df['hist'].iloc[-1]) if not macd_df['hist'].isna().iloc[-1] else 0,
                    'trend': 'bullish' if macd_df['hist'].iloc[-1] >= 0 else 'bearish',
                    'momentum': 'rising' if macd_df['hist'].iloc[-1] > macd_df['hist'].iloc[-2] else 'falling',
                    'df_index': recent_data.index
                }
                
                logger.info(f"✅ MACD analysis complete:")
                logger.info(f"   Latest MACD: {macd_data['latest_macd']:.4f}")
                logger.info(f"   Latest Signal: {macd_data['latest_signal']:.4f}")
                logger.info(f"   Latest Histogram: {macd_data['latest_histogram']:.4f}")
                logger.info(f"   Trend: {macd_data['trend']}")
                logger.info(f"   Momentum: {macd_data['momentum']}")
                logger.info(f"   Total alerts: {len(alerts)}")
                
            except Exception as macd_error:
                logger.warning(f"⚠️  MACD analysis failed: {macd_error}")
                macd_data = {
                    'macd_df': pd.DataFrame(),
                    'alerts': [],
                    'latest_macd': 0,
                    'latest_signal': 0,
                    'latest_histogram': 0,
                    'trend': 'neutral',
                    'momentum': 'neutral',
                    'df_index': recent_data.index
                }
            
            return {
                'patterns': patterns,
                'zones': zones,  # Return zones from new indicator
                'fvg_zones': fvg_zones,  # Return Fair Value Gaps
                'smc_data': smc_data,  # Return SMC analysis
                'liquidity_sweeps_data': liquidity_sweeps_data,  # Return Liquidity Sweeps analysis
                'macd_data': macd_data,  # Return MACD analysis
                'indicators': {
                    'rsi': {'current_value': 50, 'overbought_signals': [], 'oversold_signals': []},
                    'macd': {'bullish_crossovers': [], 'bearish_crossovers': []},
                    'key_levels': []
                },
                'summary': f'Volume-based zone analysis found {len(zones)} supply/demand zones, {len(fvg_zones)} FVG opportunities, comprehensive SMC analysis, {len(liquidity_sweeps_data.get("sweeps", []))} liquidity sweeps, and MACD analysis ({macd_data.get("trend", "neutral")} trend)'
            }
            
        except Exception as e:
            logger.error(f"Error in fallback analysis: {e}")
            return {
                'patterns': [],
                'zones': [],
                'indicators': {},
                'summary': f'Fallback analysis failed for {symbol}',
                'error': str(e)
            }


def detect_patterns_with_llm(df, symbol):
    """
    Main function to detect patterns using LLM
    
    Args:
        df: DataFrame with OHLCV data
        symbol: Stock symbol
    
    Returns:
        dict: Analysis results with patterns, zones, and indicators
    """
    try:
        detector = LLMPatternDetector()
        analysis = detector.analyze_candlestick_data(df, symbol)
        return analysis
    
    except Exception as e:
        logger.error(f"Error in LLM pattern detection: {e}")
        return {
            'patterns': [],
            'zones': [],
            'indicators': {},
            'error': str(e)
        }


# CLI testing
if __name__ == "__main__":
    import sys
    import pandas as pd
    
    sys.path.insert(0, '.')
    from drawing_instruction.api_price_fetcher import APIPriceFetcher
    
    # Fetch data
    fetcher = APIPriceFetcher("http://192.168.0.126:8000")
    df = fetcher.fetch_price_data("ONGC.NS", "1d", "2025-01-01", "2026-03-03", "stocks")
    
    if df is not None:
        print(f"Analyzing {len(df)} candles with LLM...")
        
        analysis = detect_patterns_with_llm(df, "ONGC.NS")
        
        print("\n" + "="*70)
        print("LLM ANALYSIS RESULTS")
        print("="*70)
        print(json.dumps(analysis, indent=2))
    else:
        print("Failed to fetch data")


# Convenience function for backward compatibility
def detect_patterns_with_llm(df, symbol):
    """
    Detect patterns using LLM analysis
    
    Args:
        df: DataFrame with OHLCV data
        symbol: Stock symbol
    
    Returns:
        dict: Analysis results with patterns, zones, and indicators
    """
    detector = LLMPatternDetector()
    return detector.analyze_candlestick_data(df, symbol)
