"""
Candlestick Pattern Detector
Detects various candlestick patterns from OHLCV data
"""

import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


def detect_candlestick_patterns(df, max_patterns=15):
    """
    Detect candlestick patterns from price data with quality filtering
    
    Args:
        df (pd.DataFrame): OHLCV data
        max_patterns (int): Maximum number of patterns to return (most recent/significant)
    
    Returns:
        list: List of pattern dictionaries
    """
    patterns = []
    
    if df is None or len(df) < 3:
        return patterns
    
    try:
        # Detect various patterns
        patterns.extend(detect_engulfing(df))
        patterns.extend(detect_doji(df))
        patterns.extend(detect_hammer(df))
        patterns.extend(detect_shooting_star(df))
        patterns.extend(detect_hanging_man(df))
        patterns.extend(detect_morning_evening_star(df))
        patterns.extend(detect_three_soldiers_crows(df))
        patterns.extend(detect_piercing_dark_cloud(df))
        patterns.extend(detect_harami(df))
        patterns.extend(detect_tweezer(df))
        
        # Sort by index (most recent first)
        patterns.sort(key=lambda x: x['index'], reverse=True)
        
        # Limit to max_patterns most recent
        patterns = patterns[:max_patterns]
        
        # Sort back by index (chronological order)
        patterns.sort(key=lambda x: x['index'])
        
        logger.info(f"Detected {len(patterns)} high-quality candlestick patterns")
        return patterns
    
    except Exception as e:
        logger.error(f"Error detecting patterns: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return []


def detect_engulfing(df):
    """Detect bullish and bearish engulfing patterns with stricter criteria"""
    patterns = []
    
    for i in range(1, len(df)):
        prev = df.iloc[i-1]
        curr = df.iloc[i]
        
        prev_body = abs(prev['Close'] - prev['Open'])
        curr_body = abs(curr['Close'] - curr['Open'])
        
        # Skip if bodies are too small (doji-like candles)
        prev_range = prev['High'] - prev['Low']
        curr_range = curr['High'] - curr['Low']
        
        if prev_body < prev_range * 0.3 or curr_body < curr_range * 0.3:
            continue  # Bodies too small, not significant
        
        # Bullish Engulfing - STRICTER CRITERIA
        if (prev['Close'] < prev['Open'] and  # Previous bearish
            curr['Close'] > curr['Open'] and  # Current bullish
            curr['Open'] <= prev['Close'] and  # Opens at or below prev close
            curr['Close'] >= prev['Open'] and  # Closes at or above prev open
            curr_body > prev_body * 1.5):  # Current body 50% larger (stricter)
            
            # Additional filter: Check if it's at a significant level
            # Look for downtrend before pattern
            if i >= 5:
                recent_trend = df['Close'].iloc[i-5:i].mean()
                if curr['Close'] > recent_trend:  # Breaking above recent average
                    patterns.append({
                        'type': 'bullish_engulfing',
                        'index': i,
                        'timestamp': int(df.index[i].timestamp()),
                        'price': float(curr['Close']),
                        'high': float(curr['High']),
                        'low': float(curr['Low']),
                        'reason': 'Bullish Engulfing: Strong reversal signal. '
                                 'Buyers overwhelmed sellers, engulfing previous bearish candle. '
                                 'Potential upward move expected.',
                        'signal': 'bullish'
                    })
        
        # Bearish Engulfing - STRICTER CRITERIA
        if (prev['Close'] > prev['Open'] and  # Previous bullish
            curr['Close'] < curr['Open'] and  # Current bearish
            curr['Open'] >= prev['Close'] and  # Opens at or above prev close
            curr['Close'] <= prev['Open'] and  # Closes at or below prev open
            curr_body > prev_body * 1.5):  # Current body 50% larger (stricter)
            
            # Additional filter: Check if it's at a significant level
            # Look for uptrend before pattern
            if i >= 5:
                recent_trend = df['Close'].iloc[i-5:i].mean()
                if curr['Close'] < recent_trend:  # Breaking below recent average
                    patterns.append({
                        'type': 'bearish_engulfing',
                        'index': i,
                        'timestamp': int(df.index[i].timestamp()),
                        'price': float(curr['Close']),
                        'high': float(curr['High']),
                        'low': float(curr['Low']),
                        'reason': 'Bearish Engulfing: Strong reversal signal. '
                                 'Sellers overwhelmed buyers, engulfing previous bullish candle. '
                                 'Potential downward move expected.',
                        'signal': 'bearish'
                    })
    
    return patterns


def detect_doji(df):
    """Detect doji patterns (regular, dragonfly, gravestone)"""
    patterns = []
    
    for i in range(len(df)):
        candle = df.iloc[i]
        
        body = abs(candle['Close'] - candle['Open'])
        total_range = candle['High'] - candle['Low']
        upper_shadow = candle['High'] - max(candle['Open'], candle['Close'])
        lower_shadow = min(candle['Open'], candle['Close']) - candle['Low']
        
        if total_range == 0:
            continue
        
        # Regular Doji: Very small body relative to range
        if body / total_range < 0.1:
            # Dragonfly Doji: Long lower shadow, no upper shadow
            if lower_shadow > total_range * 0.6 and upper_shadow < total_range * 0.1:
                patterns.append({
                    'type': 'dragonfly_doji',
                    'index': i,
                    'timestamp': int(df.index[i].timestamp()),
                    'price': float((candle['Open'] + candle['Close']) / 2),
                    'high': float(candle['High']),
                    'low': float(candle['Low']),
                    'reason': 'Dragonfly Doji: Bullish reversal signal. '
                             'Long lower shadow shows strong rejection of lower prices. '
                             'Buyers took control after sellers pushed down.',
                    'signal': 'bullish'
                })
            
            # Gravestone Doji: Long upper shadow, no lower shadow
            elif upper_shadow > total_range * 0.6 and lower_shadow < total_range * 0.1:
                patterns.append({
                    'type': 'gravestone_doji',
                    'index': i,
                    'timestamp': int(df.index[i].timestamp()),
                    'price': float((candle['Open'] + candle['Close']) / 2),
                    'high': float(candle['High']),
                    'low': float(candle['Low']),
                    'reason': 'Gravestone Doji: Bearish reversal signal. '
                             'Long upper shadow shows strong rejection of higher prices. '
                             'Sellers took control after buyers pushed up.',
                    'signal': 'bearish'
                })
            
            # Regular Doji: Balanced shadows
            else:
                patterns.append({
                    'type': 'doji',
                    'index': i,
                    'timestamp': int(df.index[i].timestamp()),
                    'price': float((candle['Open'] + candle['Close']) / 2),
                    'high': float(candle['High']),
                    'low': float(candle['Low']),
                    'reason': 'Doji: Indecision candle. Open and close nearly equal. '
                             'Market uncertainty - potential reversal or continuation. '
                             'Wait for confirmation.',
                    'signal': 'neutral'
                })
    
    return patterns


def detect_hammer(df):
    """Detect hammer and inverted hammer patterns"""
    patterns = []
    
    for i in range(len(df)):
        candle = df.iloc[i]
        
        body = abs(candle['Close'] - candle['Open'])
        upper_shadow = candle['High'] - max(candle['Open'], candle['Close'])
        lower_shadow = min(candle['Open'], candle['Close']) - candle['Low']
        total_range = candle['High'] - candle['Low']
        
        if total_range == 0:
            continue
        
        # Hammer: Long lower shadow, small body at top
        if (lower_shadow > body * 2 and
            upper_shadow < body * 0.5 and
            body / total_range < 0.3):
            
            patterns.append({
                'type': 'hammer',
                'index': i,
                'timestamp': int(df.index[i].timestamp()),
                'price': float(candle['Close']),
                'high': float(candle['High']),
                'low': float(candle['Low']),
                'reason': 'Hammer: Bullish reversal pattern. '
                         'Long lower shadow shows buyers rejected lower prices. '
                         'Potential bottom formation.',
                'signal': 'bullish'
            })
        
        # Inverted Hammer: Long upper shadow, small body at bottom
        if (upper_shadow > body * 2 and
            lower_shadow < body * 0.5 and
            body / total_range < 0.3):
            
            patterns.append({
                'type': 'inverted_hammer',
                'index': i,
                'timestamp': int(df.index[i].timestamp()),
                'price': float(candle['Close']),
                'high': float(candle['High']),
                'low': float(candle['Low']),
                'reason': 'Inverted Hammer: Potential bullish reversal. '
                         'Buyers pushed price up but couldn\'t hold. '
                         'Needs confirmation.',
                'signal': 'bullish'
            })
    
    return patterns


def detect_shooting_star(df):
    """Detect shooting star patterns"""
    patterns = []
    
    for i in range(len(df)):
        candle = df.iloc[i]
        
        body = abs(candle['Close'] - candle['Open'])
        upper_shadow = candle['High'] - max(candle['Open'], candle['Close'])
        lower_shadow = min(candle['Open'], candle['Close']) - candle['Low']
        total_range = candle['High'] - candle['Low']
        
        if total_range == 0:
            continue
        
        # Shooting Star: Long upper shadow, small body at bottom, appears at top
        if (upper_shadow > body * 2 and
            lower_shadow < body * 0.5 and
            body / total_range < 0.3 and
            i > 0 and df.iloc[i-1]['Close'] > df.iloc[i-1]['Open']):  # After uptrend
            
            patterns.append({
                'type': 'shooting_star',
                'index': i,
                'timestamp': int(df.index[i].timestamp()),
                'price': float(candle['Close']),
                'high': float(candle['High']),
                'low': float(candle['Low']),
                'reason': 'Shooting Star: Bearish reversal pattern. '
                         'Buyers pushed price up but sellers took control. '
                         'Potential top formation.',
                'signal': 'bearish'
            })
    
    return patterns


def detect_morning_evening_star(df):
    """Detect morning star and evening star patterns"""
    patterns = []
    
    for i in range(2, len(df)):
        first = df.iloc[i-2]
        second = df.iloc[i-1]
        third = df.iloc[i]
        
        first_body = abs(first['Close'] - first['Open'])
        second_body = abs(second['Close'] - second['Open'])
        third_body = abs(third['Close'] - third['Open'])
        
        # Morning Star: Bearish -> Small -> Bullish
        if (first['Close'] < first['Open'] and  # First bearish
            second_body < first_body * 0.3 and  # Second small
            third['Close'] > third['Open'] and  # Third bullish
            third['Close'] > (first['Open'] + first['Close']) / 2):  # Third closes above midpoint
            
            patterns.append({
                'type': 'morning_star',
                'index': i,
                'timestamp': int(df.index[i].timestamp()),
                'price': float(third['Close']),
                'high': float(third['High']),
                'low': float(second['Low']),
                'reason': 'Morning Star: Strong bullish reversal pattern. '
                         'Three-candle pattern showing shift from selling to buying pressure. '
                         'High probability upward move.',
                'signal': 'bullish'
            })
        
        # Evening Star: Bullish -> Small -> Bearish
        if (first['Close'] > first['Open'] and  # First bullish
            second_body < first_body * 0.3 and  # Second small
            third['Close'] < third['Open'] and  # Third bearish
            third['Close'] < (first['Open'] + first['Close']) / 2):  # Third closes below midpoint
            
            patterns.append({
                'type': 'evening_star',
                'index': i,
                'timestamp': int(df.index[i].timestamp()),
                'price': float(third['Close']),
                'high': float(second['High']),
                'low': float(third['Low']),
                'reason': 'Evening Star: Strong bearish reversal pattern. '
                         'Three-candle pattern showing shift from buying to selling pressure. '
                         'High probability downward move.',
                'signal': 'bearish'
            })
    
    return patterns



def detect_hanging_man(df):
    """Detect hanging man patterns (bearish version of hammer at top)"""
    patterns = []
    
    for i in range(1, len(df)):
        candle = df.iloc[i]
        prev = df.iloc[i-1]
        
        body = abs(candle['Close'] - candle['Open'])
        upper_shadow = candle['High'] - max(candle['Open'], candle['Close'])
        lower_shadow = min(candle['Open'], candle['Close']) - candle['Low']
        total_range = candle['High'] - candle['Low']
        
        if total_range == 0:
            continue
        
        # Hanging Man: Long lower shadow, small body at top, appears after uptrend
        if (lower_shadow > body * 2 and
            upper_shadow < body * 0.5 and
            body / total_range < 0.3 and
            prev['Close'] > prev['Open']):  # After uptrend
            
            patterns.append({
                'type': 'hanging_man',
                'index': i,
                'timestamp': int(df.index[i].timestamp()),
                'price': float(candle['Close']),
                'high': float(candle['High']),
                'low': float(candle['Low']),
                'reason': 'Hanging Man: Bearish reversal pattern at top. '
                         'Long lower shadow shows sellers testing lower prices. '
                         'Potential top formation.',
                'signal': 'bearish'
            })
    
    return patterns


def detect_three_soldiers_crows(df):
    """Detect three white soldiers and three black crows patterns"""
    patterns = []
    
    for i in range(2, len(df)):
        first = df.iloc[i-2]
        second = df.iloc[i-1]
        third = df.iloc[i]
        
        # Three White Soldiers: Three consecutive bullish candles
        if (first['Close'] > first['Open'] and
            second['Close'] > second['Open'] and
            third['Close'] > third['Open'] and
            second['Close'] > first['Close'] and
            third['Close'] > second['Close'] and
            second['Open'] > first['Open'] and
            third['Open'] > second['Open']):
            
            patterns.append({
                'type': 'three_white_soldiers',
                'index': i,
                'timestamp': int(df.index[i].timestamp()),
                'price': float(third['Close']),
                'high': float(third['High']),
                'low': float(first['Low']),
                'reason': 'Three White Soldiers: Strong bullish reversal pattern. '
                         'Three consecutive bullish candles with higher closes. '
                         'Strong buying momentum.',
                'signal': 'bullish'
            })
        
        # Three Black Crows: Three consecutive bearish candles
        if (first['Close'] < first['Open'] and
            second['Close'] < second['Open'] and
            third['Close'] < third['Open'] and
            second['Close'] < first['Close'] and
            third['Close'] < second['Close'] and
            second['Open'] < first['Open'] and
            third['Open'] < second['Open']):
            
            patterns.append({
                'type': 'three_black_crows',
                'index': i,
                'timestamp': int(df.index[i].timestamp()),
                'price': float(third['Close']),
                'high': float(first['High']),
                'low': float(third['Low']),
                'reason': 'Three Black Crows: Strong bearish reversal pattern. '
                         'Three consecutive bearish candles with lower closes. '
                         'Strong selling momentum.',
                'signal': 'bearish'
            })
    
    return patterns


def detect_piercing_dark_cloud(df):
    """Detect piercing line and dark cloud cover patterns"""
    patterns = []
    
    for i in range(1, len(df)):
        prev = df.iloc[i-1]
        curr = df.iloc[i]
        
        prev_body = abs(prev['Close'] - prev['Open'])
        curr_body = abs(curr['Close'] - curr['Open'])
        
        # Piercing Line: Bearish candle followed by bullish that closes above midpoint
        if (prev['Close'] < prev['Open'] and  # Previous bearish
            curr['Close'] > curr['Open'] and  # Current bullish
            curr['Open'] < prev['Low'] and  # Opens below previous low
            curr['Close'] > (prev['Open'] + prev['Close']) / 2 and  # Closes above midpoint
            curr['Close'] < prev['Open']):  # But below previous open
            
            patterns.append({
                'type': 'piercing_line',
                'index': i,
                'timestamp': int(df.index[i].timestamp()),
                'price': float(curr['Close']),
                'high': float(curr['High']),
                'low': float(curr['Low']),
                'reason': 'Piercing Line: Bullish reversal pattern. '
                         'Strong buying pressure pierces through previous bearish candle. '
                         'Potential bottom formation.',
                'signal': 'bullish'
            })
        
        # Dark Cloud Cover: Bullish candle followed by bearish that closes below midpoint
        if (prev['Close'] > prev['Open'] and  # Previous bullish
            curr['Close'] < curr['Open'] and  # Current bearish
            curr['Open'] > prev['High'] and  # Opens above previous high
            curr['Close'] < (prev['Open'] + prev['Close']) / 2 and  # Closes below midpoint
            curr['Close'] > prev['Open']):  # But above previous open
            
            patterns.append({
                'type': 'dark_cloud_cover',
                'index': i,
                'timestamp': int(df.index[i].timestamp()),
                'price': float(curr['Close']),
                'high': float(curr['High']),
                'low': float(curr['Low']),
                'reason': 'Dark Cloud Cover: Bearish reversal pattern. '
                         'Strong selling pressure covers previous bullish candle. '
                         'Potential top formation.',
                'signal': 'bearish'
            })
    
    return patterns


def detect_harami(df):
    """Detect harami patterns (bullish and bearish)"""
    patterns = []
    
    for i in range(1, len(df)):
        prev = df.iloc[i-1]
        curr = df.iloc[i]
        
        prev_body = abs(prev['Close'] - prev['Open'])
        curr_body = abs(curr['Close'] - curr['Open'])
        
        # Check if current candle is inside previous candle's body
        prev_high_body = max(prev['Open'], prev['Close'])
        prev_low_body = min(prev['Open'], prev['Close'])
        curr_high_body = max(curr['Open'], curr['Close'])
        curr_low_body = min(curr['Open'], curr['Close'])
        
        is_inside = (curr_high_body < prev_high_body and curr_low_body > prev_low_body)
        
        if not is_inside or curr_body > prev_body * 0.5:
            continue
        
        # Bullish Harami: Large bearish followed by small bullish inside
        if prev['Close'] < prev['Open'] and curr['Close'] > curr['Open']:
            patterns.append({
                'type': 'bullish_harami',
                'index': i,
                'timestamp': int(df.index[i].timestamp()),
                'price': float(curr['Close']),
                'high': float(prev['High']),
                'low': float(prev['Low']),
                'reason': 'Bullish Harami: Reversal pattern. '
                         'Small bullish candle inside large bearish candle. '
                         'Selling momentum weakening.',
                'signal': 'bullish'
            })
        
        # Bearish Harami: Large bullish followed by small bearish inside
        if prev['Close'] > prev['Open'] and curr['Close'] < curr['Open']:
            patterns.append({
                'type': 'bearish_harami',
                'index': i,
                'timestamp': int(df.index[i].timestamp()),
                'price': float(curr['Close']),
                'high': float(prev['High']),
                'low': float(prev['Low']),
                'reason': 'Bearish Harami: Reversal pattern. '
                         'Small bearish candle inside large bullish candle. '
                         'Buying momentum weakening.',
                'signal': 'bearish'
            })
    
    return patterns


def detect_tweezer(df):
    """Detect tweezer top and tweezer bottom patterns"""
    patterns = []
    
    for i in range(1, len(df)):
        prev = df.iloc[i-1]
        curr = df.iloc[i]
        
        # Tweezer Top: Two candles with same high (resistance)
        high_diff = abs(prev['High'] - curr['High'])
        high_tolerance = (prev['High'] + curr['High']) / 2 * 0.002  # 0.2% tolerance
        
        if (high_diff < high_tolerance and
            prev['Close'] > prev['Open'] and  # First bullish
            curr['Close'] < curr['Open']):  # Second bearish
            
            patterns.append({
                'type': 'tweezer_top',
                'index': i,
                'timestamp': int(df.index[i].timestamp()),
                'price': float(curr['Close']),
                'high': float(max(prev['High'], curr['High'])),
                'low': float(min(prev['Low'], curr['Low'])),
                'reason': 'Tweezer Top: Bearish reversal pattern. '
                         'Two candles with matching highs showing resistance. '
                         'Buyers failed to push higher twice.',
                'signal': 'bearish'
            })
        
        # Tweezer Bottom: Two candles with same low (support)
        low_diff = abs(prev['Low'] - curr['Low'])
        low_tolerance = (prev['Low'] + curr['Low']) / 2 * 0.002  # 0.2% tolerance
        
        if (low_diff < low_tolerance and
            prev['Close'] < prev['Open'] and  # First bearish
            curr['Close'] > curr['Open']):  # Second bullish
            
            patterns.append({
                'type': 'tweezer_bottom',
                'index': i,
                'timestamp': int(df.index[i].timestamp()),
                'price': float(curr['Close']),
                'high': float(max(prev['High'], curr['High'])),
                'low': float(min(prev['Low'], curr['Low'])),
                'reason': 'Tweezer Bottom: Bullish reversal pattern. '
                         'Two candles with matching lows showing support. '
                         'Sellers failed to push lower twice.',
                'signal': 'bullish'
            })
    
    return patterns
