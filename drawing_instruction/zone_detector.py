"""
Supply & Demand Zone Detector
Professional algorithm based on institutional order flow and price action:
1. Consolidation Base: Tight sideways range with small-bodied candles
2. Explosive Move: Strong impulsive breakout proving order imbalance
3. Speed of Departure: Quick exit with minimal wicks back into base

Based on professional methodology from QuantCrawler and institutional trading concepts.
"""

import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


def detect_supply_demand_zones(df, lookback=200, min_base_candles=3, max_base_candles=10, 
                               min_impulse_candles=2, min_impulse_strength=2.0, max_wick_ratio=0.25):
    """
    Detect supply and demand zones using professional institutional methodology
    
    Professional Three-Step Validation:
    1. Consolidation/Base Formation: Tight range with small bodies (where orders accumulate)
    2. Strong Impulsive Move: Explosive directional move (proves order imbalance)
    3. Speed of Departure: Quick exit with minimal wicks (confirms strong rejection)
    
    Args:
        df (pd.DataFrame): OHLCV data with DatetimeIndex
        lookback (int): Number of recent candles to analyze (default: 200)
        min_base_candles (int): Minimum candles in base (default: 3)
        max_base_candles (int): Maximum candles in base (default: 10)
        min_impulse_candles (int): Minimum candles in impulse (default: 2)
        min_impulse_strength (float): Minimum impulse/base ratio (default: 2.0 = impulse 2x larger than base)
        max_wick_ratio (float): Maximum wick back into base (default: 0.25 = 25%)
    
    Returns:
        list: List of valid supply/demand zone dictionaries
    """
    zones = []
    
    if df is None or len(df) < lookback:
        logger.warning(f"Insufficient data: {len(df) if df is not None else 0} candles (need {lookback})")
        return zones
    
    try:
        # Use recent data
        recent_df = df.tail(lookback).copy().reset_index(drop=True)
        
        # Calculate ATR for volatility measurement
        recent_df['TR'] = np.maximum(
            recent_df['High'] - recent_df['Low'],
            np.maximum(
                abs(recent_df['High'] - recent_df['Close'].shift(1)),
                abs(recent_df['Low'] - recent_df['Close'].shift(1))
            )
        )
        recent_df['ATR'] = recent_df['TR'].rolling(window=14).mean()
        
        # Calculate average candle body size for reference
        recent_df['Body'] = abs(recent_df['Close'] - recent_df['Open'])
        avg_body = recent_df['Body'].mean()
        
        logger.info(f"Scanning {len(recent_df)} candles for supply/demand zones...")
        
        # Scan for valid base + impulse patterns
        for base_size in range(min_base_candles, max_base_candles + 1):
            for i in range(base_size + 5, len(recent_df) - min_impulse_candles - 2):
                # STEP 1: CONSOLIDATION BASE DETECTION
                base_start = i - base_size
                base_end = i
                base_candles = recent_df.iloc[base_start:base_end]
                
                # Calculate base characteristics
                base_high = float(base_candles['High'].max())
                base_low = float(base_candles['Low'].min())
                base_range = base_high - base_low
                
                if base_range == 0:
                    continue  # Invalid base
                
                # Base must be tight (small range relative to ATR)
                avg_atr = float(base_candles['ATR'].mean())
                if avg_atr == 0 or base_range > avg_atr * 1.5:
                    continue  # Base too wide, not consolidation
                
                # Base candles must have small bodies (consolidation characteristic)
                base_bodies = float(base_candles['Body'].mean())
                body_to_range_ratio = base_bodies / base_range if base_range > 0 else 1
                if body_to_range_ratio > 0.5:  # Bodies should be < 50% of range
                    continue  # Bodies too large, not tight consolidation
                
                # STEP 2: EXPLOSIVE IMPULSIVE MOVE DETECTION
                # Look for strong directional move immediately after base
                impulse_start = base_end
                impulse_end = min(impulse_start + 5, len(recent_df))  # Check up to 5 candles
                
                if impulse_end - impulse_start < min_impulse_candles:
                    continue
                
                impulse_candles = recent_df.iloc[impulse_start:impulse_end]
                
                # Calculate impulse characteristics
                impulse_high = float(impulse_candles['High'].max())
                impulse_low = float(impulse_candles['Low'].min())
                impulse_range = impulse_high - impulse_low
                impulse_bodies = float(impulse_candles['Body'].mean())
                
                # Impulse must be significantly larger than base (proves order imbalance)
                if impulse_range < base_range * min_impulse_strength:
                    continue  # Impulse not strong enough (must be 2x+ larger than base)
                
                # Impulse must have large bodies (strong directional candles)
                impulse_body_ratio = impulse_bodies / impulse_range if impulse_range > 0 else 0
                if impulse_body_ratio < 0.4:  # Bodies should be > 40% of range
                    continue  # Bodies too small, not strong impulse
                
                # Determine direction: Rally-Base-Rally (RBR) or Drop-Base-Drop (DBD)
                impulse_net_move = float(impulse_candles['Close'].iloc[-1] - impulse_candles['Open'].iloc[0])
                
                # STEP 3: SPEED OF DEPARTURE (Minimal Wick Interference)
                # Check if price quickly left the base without grinding back
                post_impulse_start = impulse_end
                post_impulse_end = min(impulse_end + 3, len(recent_df))
                
                if post_impulse_end > post_impulse_start:
                    post_candles = recent_df.iloc[post_impulse_start:post_impulse_end]
                    post_low = float(post_candles['Low'].min())
                    post_high = float(post_candles['High'].max())
                else:
                    post_low = impulse_low
                    post_high = impulse_high
                
                # RALLY-BASE-RALLY (RBR) = DEMAND ZONE
                if impulse_net_move > 0:
                    # Bullish impulse - check if price drifted back down into base
                    wick_into_base = max(0, base_high - post_low)
                    wick_ratio = wick_into_base / base_range if base_range > 0 else 0
                    
                    # Wick interference must be minimal (< 25%)
                    if wick_ratio > max_wick_ratio:
                        continue  # Too much wick back into base, not clean departure
                    
                    # Check if zone is "fresh" (not retested yet)
                    future_start = post_impulse_end
                    future_end = len(recent_df)
                    is_fresh = True
                    
                    if future_end > future_start:
                        future_candles = recent_df.iloc[future_start:future_end]
                        future_low = float(future_candles['Low'].min())
                        
                        # If price came back and closed below zone, it's tested
                        if future_low <= base_high:
                            is_fresh = False
                    
                    # Valid DEMAND zone
                    zones.append({
                        'type': 'demand',
                        'start_index': base_start,
                        'end_index': base_end,
                        'start_time': int(df.index[len(df) - lookback + base_start].timestamp()),
                        'end_time': int(df.index[len(df) - lookback + base_end].timestamp()),
                        'high': float(base_high),
                        'low': float(base_low),
                        'base_range': float(base_range),
                        'impulse_range': float(impulse_range),
                        'impulse_strength': float(impulse_range / base_range),
                        'wick_ratio': float(wick_ratio),
                        'is_fresh': is_fresh,
                        'pattern': 'RBR',  # Rally-Base-Rally
                        'reason': f"{'🆕 FRESH ' if is_fresh else ''}Demand Zone (RBR): "
                                 f"Tight base ₹{base_low:.2f}-₹{base_high:.2f} "
                                 f"followed by explosive rally ({impulse_range/base_range:.1f}x base size). "
                                 f"Quick departure with {wick_ratio*100:.0f}% wick interference. "
                                 f"Institutional buy orders likely unfilled."
                    })
                
                # DROP-BASE-DROP (DBD) = SUPPLY ZONE
                elif impulse_net_move < 0:
                    # Bearish impulse - check if price drifted back up into base
                    wick_into_base = max(0, post_high - base_low)
                    wick_ratio = wick_into_base / base_range if base_range > 0 else 0
                    
                    # Wick interference must be minimal (< 25%)
                    if wick_ratio > max_wick_ratio:
                        continue  # Too much wick back into base, not clean departure
                    
                    # Check if zone is "fresh" (not retested yet)
                    future_start = post_impulse_end
                    future_end = len(recent_df)
                    is_fresh = True
                    
                    if future_end > future_start:
                        future_candles = recent_df.iloc[future_start:future_end]
                        future_high = float(future_candles['High'].max())
                        
                        # If price came back and closed above zone, it's tested
                        if future_high >= base_low:
                            is_fresh = False
                    
                    # Valid SUPPLY zone
                    zones.append({
                        'type': 'supply',
                        'start_index': base_start,
                        'end_index': base_end,
                        'start_time': int(df.index[len(df) - lookback + base_start].timestamp()),
                        'end_time': int(df.index[len(df) - lookback + base_end].timestamp()),
                        'high': float(base_high),
                        'low': float(base_low),
                        'base_range': float(base_range),
                        'impulse_range': float(impulse_range),
                        'impulse_strength': float(impulse_range / base_range),
                        'wick_ratio': float(wick_ratio),
                        'is_fresh': is_fresh,
                        'pattern': 'DBD',  # Drop-Base-Drop
                        'reason': f"{'🆕 FRESH ' if is_fresh else ''}Supply Zone (DBD): "
                                 f"Tight base ₹{base_low:.2f}-₹{base_high:.2f} "
                                 f"followed by explosive drop ({impulse_range/base_range:.1f}x base size). "
                                 f"Quick departure with {wick_ratio*100:.0f}% wick interference. "
                                 f"Institutional sell orders likely unfilled."
                    })
        
        # Filter overlapping zones - keep strongest
        zones = filter_overlapping_zones(zones)
        
        # Prioritize fresh zones and sort by impulse strength
        zones.sort(key=lambda x: (x['is_fresh'], x['impulse_strength']), reverse=True)
        
        # Limit to top 5 most relevant zones
        zones = zones[:5]
        
        logger.info(f"✅ Detected {len(zones)} valid supply/demand zones")
        for zone in zones:
            logger.info(f"  - {zone['type'].upper()} ({zone['pattern']}): "
                       f"₹{zone['low']:.2f}-₹{zone['high']:.2f}, "
                       f"Strength: {zone['impulse_strength']:.1f}x, "
                       f"Fresh: {zone['is_fresh']}")
        
        return zones
    
    except Exception as e:
        logger.error(f"❌ Error detecting zones: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return []


def filter_overlapping_zones(zones):
    """
    Remove overlapping zones, keeping the strongest and freshest
    
    Priority:
    1. Fresh zones over tested zones
    2. Higher impulse strength
    3. Cleaner departure (lower wick ratio)
    """
    if not zones:
        return zones
    
    # Sort by priority: fresh first, then impulse strength, then wick ratio
    zones.sort(key=lambda x: (x['is_fresh'], x['impulse_strength'], -x['wick_ratio']), reverse=True)
    
    filtered = []
    for zone in zones:
        overlaps = False
        for existing in filtered:
            # Check if zones overlap significantly (>50% overlap)
            overlap_high = min(zone['high'], existing['high'])
            overlap_low = max(zone['low'], existing['low'])
            
            if overlap_high > overlap_low:
                overlap_size = overlap_high - overlap_low
                zone_size = zone['high'] - zone['low']
                existing_size = existing['high'] - existing['low']
                
                # If overlap is >50% of either zone, consider them overlapping
                if (overlap_size / zone_size > 0.5) or (overlap_size / existing_size > 0.5):
                    overlaps = True
                    break
        
        if not overlaps:
            filtered.append(zone)
    
    return filtered


def detect_key_levels(df, lookback=50):
    """
    Detect key support and resistance levels
    
    Args:
        df (pd.DataFrame): OHLCV data
        lookback (int): Number of candles to analyze
    
    Returns:
        list: List of key level dictionaries
    """
    levels = []
    
    try:
        recent_data = df.tail(lookback)
        
        # Find swing highs and lows
        for i in range(2, len(recent_data) - 2):
            # Swing high
            if (recent_data['High'].iloc[i] > recent_data['High'].iloc[i-1] and
                recent_data['High'].iloc[i] > recent_data['High'].iloc[i-2] and
                recent_data['High'].iloc[i] > recent_data['High'].iloc[i+1] and
                recent_data['High'].iloc[i] > recent_data['High'].iloc[i+2]):
                
                levels.append({
                    'type': 'resistance',
                    'price': float(recent_data['High'].iloc[i]),
                    'timestamp': int(recent_data.index[i].timestamp()),
                    'reason': 'Swing high - price rejected at this level'
                })
            
            # Swing low
            if (recent_data['Low'].iloc[i] < recent_data['Low'].iloc[i-1] and
                recent_data['Low'].iloc[i] < recent_data['Low'].iloc[i-2] and
                recent_data['Low'].iloc[i] < recent_data['Low'].iloc[i+1] and
                recent_data['Low'].iloc[i] < recent_data['Low'].iloc[i+2]):
                
                levels.append({
                    'type': 'support',
                    'price': float(recent_data['Low'].iloc[i]),
                    'timestamp': int(recent_data.index[i].timestamp()),
                    'reason': 'Swing low - price bounced from this level'
                })
        
        return levels
    
    except Exception as e:
        logger.error(f"Error detecting key levels: {e}")
        return []
