"""
JSON Drawing Instruction Builder
Converts detected zones, patterns, and indicators into TradingView drawing JSON format
"""

import random
import string
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def generate_unique_id():
    """Generate unique ID for drawing objects (TradingView format: 6 chars)"""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=6))


def build_drawing_json(symbol, zones=None, patterns=None, bollinger=None, rsi=None, macd=None, levels=None):
    """
    Build complete drawing JSON from all detections (TradingView format)
    
    Args:
        symbol (str): Stock symbol
        zones (list): Supply/demand zones
        patterns (list): Candlestick patterns
        bollinger (dict): Bollinger Bands data
        rsi (dict): RSI data
        macd (dict): MACD data
        levels (list): Key support/resistance levels
    
    Returns:
        list: Array of TradingView drawing objects
    """
    drawings = []
    
    try:
        # Add zones
        if zones:
            for zone in zones:
                drawings.append(build_zone_json(zone, symbol))
        
        # Add patterns
        if patterns:
            for pattern in patterns:
                drawings.append(build_pattern_json(pattern, symbol))
        
        # Add Bollinger Bands
        if bollinger:
            drawings.extend(build_bollinger_json(bollinger, symbol))
        
        # Add RSI signals
        if rsi:
            drawings.extend(build_rsi_json(rsi, symbol))
        
        # Add MACD signals
        if macd:
            drawings.extend(build_macd_json(macd, symbol))
        
        # Add key levels
        if levels:
            for level in levels:
                drawings.append(build_level_json(level, symbol))
        
        logger.info(f"Built {len(drawings)} drawing instructions for {symbol}")
        return drawings
    
    except Exception as e:
        logger.error(f"Error building drawing JSON: {e}")
        return []


def build_zone_json(zone, symbol):
    """Build JSON for supply/demand zone (TradingView Rectangle format)"""
    zone_id = generate_unique_id()
    
    # Color based on zone type
    if zone['type'] == 'supply':
        fill_color = 'rgba(255, 82, 82, 0.2)'  # Red with transparency
        line_color = '#FF5252'
        text = '🔴 SUPPLY ZONE'
    else:
        fill_color = 'rgba(76, 175, 80, 0.2)'  # Green with transparency
        line_color = '#4CAF50'
        text = '🟢 DEMAND ZONE'
    
    # Build enhanced reason with validation info
    reason_parts = [zone.get('reason', '')]
    
    # Add validation status if available
    validation = zone.get('validation', {})
    if validation:
        status_parts = []
        if validation.get('base_tight'):
            status_parts.append('✅ Base Tight')
        if validation.get('impulse_strong'):
            status_parts.append('✅ Impulse Strong')
        if validation.get('departure_clean'):
            status_parts.append('✅ Clean Departure')
        if validation.get('all_criteria_met'):
            status_parts.append('✅ All Validated')
        
        if status_parts:
            reason_parts.append(' | ' + ' | '.join(status_parts))
    
    # Add confidence level
    confidence = zone.get('confidence', 0)
    if confidence >= 90:
        confidence_text = 'High Confidence'
    elif confidence >= 75:
        confidence_text = 'Medium Confidence'
    else:
        confidence_text = 'Lower Confidence'
    
    reason_parts.append(f' | {confidence_text}')
    
    return {
        'id': zone_id,
        'type': 'LineToolRectangle',
        'state': {
            'symbol': symbol,
            'interval': '1D',
            'frozen': False,
            'visible': True,
            'fillBackground': True,
            'backgroundColor': fill_color,
            'backgroundTransparency': 80,
            'linecolor': line_color,
            'linewidth': 2,
            'linestyle': 0,  # Solid line
            'extendLeft': False,
            'extendRight': False,
            'showLabel': True,
            'text': text,
            'textcolor': '#FFFFFF',
            'fontsize': 12,
            'bold': True,
            'italic': False,
            'zOrderVersion': 2,
            'symbolStateVersion': 2,
            'intervalsVisibilities': {
                'ticks': True, 'seconds': True, 'secondsFrom': 1, 'secondsTo': 59,
                'minutes': True, 'minutesFrom': 1, 'minutesTo': 59,
                'hours': True, 'hoursFrom': 1, 'hoursTo': 24,
                'days': True, 'daysFrom': 1, 'daysTo': 366,
                'weeks': True, 'weeksFrom': 1, 'weeksTo': 52,
                'months': True, 'monthsFrom': 1, 'monthsTo': 12,
                'ranges': True
            }
        },
        'points': [
            {
                'price': zone['high'],
                'time_t': zone['start_time'],
                'offset': 0
            },
            {
                'price': zone['low'],
                'time_t': zone['end_time'],
                'offset': 0
            }
        ],
        'zorder': -5000,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False,
        'isSelectionEnabled': True,
        'metadata': {
            'base_candles': zone.get('base_candles', 0),
            'impulse_candles': zone.get('impulse_candles', 0),
            'base_range': zone.get('base_range', 0),
            'impulse_range': zone.get('impulse_range', 0),
            'impulse_strength': zone.get('impulse_strength', 0),
            'wick_ratio': zone.get('wick_ratio', 0),
            'is_fresh': zone.get('is_fresh', True),
            'validation': validation,
            'full_reason': ' '.join(reason_parts)
        }
    }


def build_pattern_json(pattern, symbol):
    """Build JSON for candlestick pattern (TradingView Note format)"""
    pattern_id = generate_unique_id()
    
    # Calculate proper placement price based on pattern type
    # Bullish patterns: place below the candle (at low - offset)
    # Bearish patterns: place above the candle (at high + offset)
    candle_range = pattern['high'] - pattern['low']
    offset = candle_range * 0.15  # 15% of candle range for spacing
    
    if pattern['signal'] == 'bullish':
        # Place below the candle
        placement_price = pattern['low'] - offset
        icon = '📈'
        bg_color = 'rgba(76, 175, 80, 0.7)'
        marker_color = '#4CAF50'
    elif pattern['signal'] == 'bearish':
        # Place above the candle
        placement_price = pattern['high'] + offset
        icon = '📉'
        bg_color = 'rgba(255, 82, 82, 0.7)'
        marker_color = '#FF5252'
    else:
        # Neutral patterns: place at close price
        placement_price = pattern['price']
        icon = '⚠️'
        bg_color = 'rgba(255, 193, 7, 0.7)'
        marker_color = '#FFC107'
    
    # Pattern name formatting
    pattern_name = pattern['type'].replace('_', ' ').title()
    
    return {
        'id': pattern_id,
        'type': 'LineToolNote',
        'state': {
            'symbol': symbol,
            'interval': '1D',
            'frozen': False,
            'visible': True,
            'fixedSize': True,
            'text': f"{icon} {pattern_name}",
            'title': '',
            'bold': False,
            'italic': False,
            'fontSize': 14,
            'textColor': '#FFFFFF',
            'backgroundColor': bg_color,
            'backgroundTransparency': 0,
            'borderColor': marker_color,
            'markerColor': marker_color,
            'zOrderVersion': 2,
            'symbolStateVersion': 2,
            'intervalsVisibilities': {
                'ticks': True, 'seconds': True, 'secondsFrom': 1, 'secondsTo': 59,
                'minutes': True, 'minutesFrom': 1, 'minutesTo': 59,
                'hours': True, 'hoursFrom': 1, 'hoursTo': 24,
                'days': True, 'daysFrom': 1, 'daysTo': 366,
                'weeks': True, 'weeksFrom': 1, 'weeksTo': 52,
                'months': True, 'monthsFrom': 1, 'monthsTo': 12,
                'ranges': True
            }
        },
        'points': [
            {
                'price': placement_price,  # Use calculated placement price
                'time_t': pattern['timestamp'],
                'offset': 0
            }
        ],
        'zorder': -7500,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False,
        'isSelectionEnabled': True
    }


def build_bollinger_json(bollinger, symbol):
    """Build JSON for Bollinger Bands (TradingView Line format)"""
    drawings = []
    
    if not bollinger or not bollinger.get('upper'):
        return drawings
    
    # Upper Band
    upper_points = [{'price': p['price'], 'time_t': p['time'], 'offset': 0} for p in bollinger['upper']]
    drawings.append({
        'id': generate_unique_id(),
        'type': 'LineToolTrendLine',
        'state': {
            'symbol': symbol,
            'interval': '1D',
            'frozen': False,
            'visible': True,
            'linecolor': '#2196F3',
            'linewidth': 1,
            'linestyle': 2,  # Dashed
            'extendLeft': False,
            'extendRight': False,
            'showLabel': True,
            'text': f'BB Upper ({bollinger["period"]}, {bollinger["std_dev"]}σ)',
            'textcolor': '#2196F3',
            'fontsize': 10,
            'bold': False,
            'italic': False,
            'zOrderVersion': 2,
            'symbolStateVersion': 2,
            'intervalsVisibilities': {
                'ticks': True, 'seconds': True, 'secondsFrom': 1, 'secondsTo': 59,
                'minutes': True, 'minutesFrom': 1, 'minutesTo': 59,
                'hours': True, 'hoursFrom': 1, 'hoursTo': 24,
                'days': True, 'daysFrom': 1, 'daysTo': 366,
                'weeks': True, 'weeksFrom': 1, 'weeksTo': 52,
                'months': True, 'monthsFrom': 1, 'monthsTo': 12,
                'ranges': True
            }
        },
        'points': [upper_points[0], upper_points[-1]] if len(upper_points) >= 2 else upper_points,
        'zorder': -6000,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False,
        'isSelectionEnabled': True
    })
    
    # Middle Band
    middle_points = [{'price': p['price'], 'time_t': p['time'], 'offset': 0} for p in bollinger['middle']]
    drawings.append({
        'id': generate_unique_id(),
        'type': 'LineToolTrendLine',
        'state': {
            'symbol': symbol,
            'interval': '1D',
            'frozen': False,
            'visible': True,
            'linecolor': '#9C27B0',
            'linewidth': 1,
            'linestyle': 0,  # Solid
            'extendLeft': False,
            'extendRight': False,
            'showLabel': True,
            'text': f'BB Middle (SMA {bollinger["period"]})',
            'textcolor': '#9C27B0',
            'fontsize': 10,
            'bold': False,
            'italic': False,
            'zOrderVersion': 2,
            'symbolStateVersion': 2,
            'intervalsVisibilities': {
                'ticks': True, 'seconds': True, 'secondsFrom': 1, 'secondsTo': 59,
                'minutes': True, 'minutesFrom': 1, 'minutesTo': 59,
                'hours': True, 'hoursFrom': 1, 'hoursTo': 24,
                'days': True, 'daysFrom': 1, 'daysTo': 366,
                'weeks': True, 'weeksFrom': 1, 'weeksTo': 52,
                'months': True, 'monthsFrom': 1, 'monthsTo': 12,
                'ranges': True
            }
        },
        'points': [middle_points[0], middle_points[-1]] if len(middle_points) >= 2 else middle_points,
        'zorder': -6000,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False,
        'isSelectionEnabled': True
    })
    
    # Lower Band
    lower_points = [{'price': p['price'], 'time_t': p['time'], 'offset': 0} for p in bollinger['lower']]
    drawings.append({
        'id': generate_unique_id(),
        'type': 'LineToolTrendLine',
        'state': {
            'symbol': symbol,
            'interval': '1D',
            'frozen': False,
            'visible': True,
            'linecolor': '#2196F3',
            'linewidth': 1,
            'linestyle': 2,  # Dashed
            'extendLeft': False,
            'extendRight': False,
            'showLabel': True,
            'text': f'BB Lower ({bollinger["period"]}, {bollinger["std_dev"]}σ)',
            'textcolor': '#2196F3',
            'fontsize': 10,
            'bold': False,
            'italic': False,
            'zOrderVersion': 2,
            'symbolStateVersion': 2,
            'intervalsVisibilities': {
                'ticks': True, 'seconds': True, 'secondsFrom': 1, 'secondsTo': 59,
                'minutes': True, 'minutesFrom': 1, 'minutesTo': 59,
                'hours': True, 'hoursFrom': 1, 'hoursTo': 24,
                'days': True, 'daysFrom': 1, 'daysTo': 366,
                'weeks': True, 'weeksFrom': 1, 'weeksTo': 52,
                'months': True, 'monthsFrom': 1, 'monthsTo': 12,
                'ranges': True
            }
        },
        'points': [lower_points[0], lower_points[-1]] if len(lower_points) >= 2 else lower_points,
        'zorder': -6000,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False,
        'isSelectionEnabled': True
    })
    
    # Add squeeze markers
    for squeeze in bollinger.get('squeezes', []):
        drawings.append({
            'id': generate_unique_id(),
            'type': 'LineToolNote',
            'state': {
                'symbol': symbol,
                'interval': '1D',
                'frozen': False,
                'visible': True,
                'fixedSize': True,
                'text': '🔥 BB Squeeze',
                'title': '',
                'bold': False,
                'italic': False,
                'fontSize': 12,
                'textColor': '#FFFFFF',
                'backgroundColor': 'rgba(255, 152, 0, 0.7)',
                'backgroundTransparency': 0,
                'borderColor': '#FF9800',
                'markerColor': '#FF9800',
                'zOrderVersion': 2,
                'symbolStateVersion': 2,
                'intervalsVisibilities': {
                    'ticks': True, 'seconds': True, 'secondsFrom': 1, 'secondsTo': 59,
                    'minutes': True, 'minutesFrom': 1, 'minutesTo': 59,
                    'hours': True, 'hoursFrom': 1, 'hoursTo': 24,
                    'days': True, 'daysFrom': 1, 'daysTo': 366,
                    'weeks': True, 'weeksFrom': 1, 'weeksTo': 52,
                    'months': True, 'monthsFrom': 1, 'monthsTo': 12,
                    'ranges': True
                }
            },
            'points': [
                {
                    'price': squeeze['price'],
                    'time_t': squeeze['timestamp'],
                    'offset': 0
                }
            ],
            'zorder': -7500,
            'linkKey': generate_unique_id() + generate_unique_id(),
            'ownerSource': '_seriesId',
            'userEditEnabled': False,
            'isSelectionEnabled': True
        })
    
    return drawings


def build_rsi_json(rsi, symbol):
    """Build JSON for RSI signals (TradingView Note format)"""
    drawings = []
    
    if not rsi:
        return drawings
    
    # Overbought signals
    for signal in rsi.get('overbought', []):
        drawings.append({
            'id': generate_unique_id(),
            'type': 'LineToolNote',
            'state': {
                'symbol': symbol,
                'interval': '1D',
                'frozen': False,
                'visible': True,
                'fixedSize': True,
                'text': '⚠️ RSI Overbought',
                'title': '',
                'bold': False,
                'italic': False,
                'fontSize': 12,
                'textColor': '#FFFFFF',
                'backgroundColor': 'rgba(255, 82, 82, 0.7)',
                'backgroundTransparency': 0,
                'borderColor': '#FF5252',
                'markerColor': '#FF5252',
                'zOrderVersion': 2,
                'symbolStateVersion': 2,
                'intervalsVisibilities': {
                    'ticks': True, 'seconds': True, 'secondsFrom': 1, 'secondsTo': 59,
                    'minutes': True, 'minutesFrom': 1, 'minutesTo': 59,
                    'hours': True, 'hoursFrom': 1, 'hoursTo': 24,
                    'days': True, 'daysFrom': 1, 'daysTo': 366,
                    'weeks': True, 'weeksFrom': 1, 'weeksTo': 52,
                    'months': True, 'monthsFrom': 1, 'monthsTo': 12,
                    'ranges': True
                }
            },
            'points': [
                {
                    'price': signal['price'],
                    'time_t': signal['timestamp'],
                    'offset': 0
                }
            ],
            'zorder': -7500,
            'linkKey': generate_unique_id() + generate_unique_id(),
            'ownerSource': '_seriesId',
            'userEditEnabled': False,
            'isSelectionEnabled': True
        })
    
    # Oversold signals
    for signal in rsi.get('oversold', []):
        drawings.append({
            'id': generate_unique_id(),
            'type': 'LineToolNote',
            'state': {
                'symbol': symbol,
                'interval': '1D',
                'frozen': False,
                'visible': True,
                'fixedSize': True,
                'text': '⚠️ RSI Oversold',
                'title': '',
                'bold': False,
                'italic': False,
                'fontSize': 12,
                'textColor': '#FFFFFF',
                'backgroundColor': 'rgba(76, 175, 80, 0.7)',
                'backgroundTransparency': 0,
                'borderColor': '#4CAF50',
                'markerColor': '#4CAF50',
                'zOrderVersion': 2,
                'symbolStateVersion': 2,
                'intervalsVisibilities': {
                    'ticks': True, 'seconds': True, 'secondsFrom': 1, 'secondsTo': 59,
                    'minutes': True, 'minutesFrom': 1, 'minutesTo': 59,
                    'hours': True, 'hoursFrom': 1, 'hoursTo': 24,
                    'days': True, 'daysFrom': 1, 'daysTo': 366,
                    'weeks': True, 'weeksFrom': 1, 'weeksTo': 52,
                    'months': True, 'monthsFrom': 1, 'monthsTo': 12,
                    'ranges': True
                }
            },
            'points': [
                {
                    'price': signal['price'],
                    'time_t': signal['timestamp'],
                    'offset': 0
                }
            ],
            'zorder': -7500,
            'linkKey': generate_unique_id() + generate_unique_id(),
            'ownerSource': '_seriesId',
            'userEditEnabled': False,
            'isSelectionEnabled': True
        })
    
    return drawings


def build_macd_json(macd, symbol):
    """Build JSON for MACD crossovers (TradingView Note format)"""
    drawings = []
    
    if not macd:
        return drawings
    
    for crossover in macd.get('crossovers', []):
        icon = '📈' if crossover['type'] == 'bullish' else '📉'
        bg_color = 'rgba(76, 175, 80, 0.7)' if crossover['type'] == 'bullish' else 'rgba(255, 82, 82, 0.7)'
        marker_color = '#4CAF50' if crossover['type'] == 'bullish' else '#FF5252'
        
        drawings.append({
            'id': generate_unique_id(),
            'type': 'LineToolNote',
            'state': {
                'symbol': symbol,
                'interval': '1D',
                'frozen': False,
                'visible': True,
                'fixedSize': True,
                'text': f"{icon} MACD {crossover['type'].title()}",
                'title': '',
                'bold': False,
                'italic': False,
                'fontSize': 12,
                'textColor': '#FFFFFF',
                'backgroundColor': bg_color,
                'backgroundTransparency': 0,
                'borderColor': marker_color,
                'markerColor': marker_color,
                'zOrderVersion': 2,
                'symbolStateVersion': 2,
                'intervalsVisibilities': {
                    'ticks': True, 'seconds': True, 'secondsFrom': 1, 'secondsTo': 59,
                    'minutes': True, 'minutesFrom': 1, 'minutesTo': 59,
                    'hours': True, 'hoursFrom': 1, 'hoursTo': 24,
                    'days': True, 'daysFrom': 1, 'daysTo': 366,
                    'weeks': True, 'weeksFrom': 1, 'weeksTo': 52,
                    'months': True, 'monthsFrom': 1, 'monthsTo': 12,
                    'ranges': True
                }
            },
            'points': [
                {
                    'price': crossover['price'],
                    'time_t': crossover['timestamp'],
                    'offset': 0
                }
            ],
            'zorder': -7500,
            'linkKey': generate_unique_id() + generate_unique_id(),
            'ownerSource': '_seriesId',
            'userEditEnabled': False,
            'isSelectionEnabled': True
        })
    
    return drawings


def build_level_json(level, symbol):
    """Build JSON for support/resistance level (TradingView Horizontal Line format)"""
    level_id = generate_unique_id()
    
    line_color = '#FF5252' if level['type'] == 'resistance' else '#4CAF50'
    text = f"{'🔴 Resistance' if level['type'] == 'resistance' else '🟢 Support'}"
    
    # Handle timestamp - may not be present in LLM output
    timestamp = level.get('timestamp', 0)
    
    return {
        'id': level_id,
        'type': 'LineToolHorzLine',
        'state': {
            'symbol': symbol,
            'interval': '1D',
            'frozen': False,
            'visible': True,
            'linecolor': line_color,
            'linewidth': 2,
            'linestyle': 0,  # Solid
            'showLabel': True,
            'text': text,
            'textcolor': line_color,
            'fontsize': 11,
            'bold': True,
            'italic': False,
            'horzLabelsAlign': 'right',
            'vertLabelsAlign': 'middle',
            'zOrderVersion': 2,
            'symbolStateVersion': 2,
            'intervalsVisibilities': {
                'ticks': True, 'seconds': True, 'secondsFrom': 1, 'secondsTo': 59,
                'minutes': True, 'minutesFrom': 1, 'minutesTo': 59,
                'hours': True, 'hoursFrom': 1, 'hoursTo': 24,
                'days': True, 'daysFrom': 1, 'daysTo': 366,
                'weeks': True, 'weeksFrom': 1, 'weeksTo': 52,
                'months': True, 'monthsFrom': 1, 'monthsTo': 12,
                'ranges': True
            }
        },
        'points': [
            {
                'price': level['price'],
                'time_t': timestamp,
                'offset': 0
            }
        ],
        'zorder': -6500,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False,
        'isSelectionEnabled': True
    }


def build_fvg_json(fvg, symbol):
    """Build JSON for Fair Value Gap (FVG) zone (TradingView Rectangle format)"""
    fvg_id = generate_unique_id()
    
    # Color based on FVG type - matching your chart images
    if fvg['type'] == 'bullish_fvg':
        fill_color = 'rgba(76, 175, 80, 0.15)'  # Light green like your chart
        line_color = '#4CAF50'
        text = '🟢 BULLISH FVG'
    else:
        fill_color = 'rgba(156, 39, 176, 0.15)'  # Purple/magenta like your chart
        line_color = '#9C27B0'
        text = '🔴 BEARISH FVG'
    
    # Build reason with gap information
    gap_percentage = fvg.get('gap_percentage', 0)
    reason = f"{text}: {gap_percentage:.1f}% gap - Fair Value Gap (untested area)"
    
    return {
        'id': fvg_id,
        'type': 'LineToolRectangle',
        'state': {
            'symbol': symbol,
            'interval': '1D',
            'frozen': False,
            'visible': True,
            'fillBackground': True,
            'backgroundColor': fill_color,
            'backgroundTransparency': 85,  # More transparent like your chart
            'linecolor': line_color,
            'linewidth': 1,  # Thin border
            'linestyle': 0,  # Solid line
            'extendLeft': False,
            'extendRight': False,  # Don't extend - keep FVG to 3-candle pattern only
            'showLabel': True,
            'text': text,
            'textcolor': '#FFFFFF',
            'fontsize': 11,
            'bold': False,
            'italic': False,
            'zOrderVersion': 2,
            'symbolStateVersion': 2,
            'intervalsVisibilities': {
                'ticks': True, 'seconds': True, 'secondsFrom': 1, 'secondsTo': 59,
                'minutes': True, 'minutesFrom': 1, 'minutesTo': 59,
                'hours': True, 'hoursFrom': 1, 'hoursTo': 24,
                'days': True, 'daysFrom': 1, 'daysTo': 366,
                'weeks': True, 'weeksFrom': 1, 'weeksTo': 52,
                'months': True, 'monthsFrom': 1, 'monthsTo': 12,
                'ranges': True
            }
        },
        'points': [
            {
                'price': fvg['high'],  # Top of the gap
                'time_t': fvg['start_time'],
                'offset': 0
            },
            {
                'price': fvg['low'],   # Bottom of the gap
                'time_t': fvg['end_time'],
                'offset': 0
            }
        ],
        'zorder': -4000,  # Above zones but below patterns
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False,
        'isSelectionEnabled': True,
        'metadata': {
            'gap_size': fvg.get('gap_size', 0),
            'gap_percentage': gap_percentage,
            'middle_candle_index': fvg.get('middle_candle_index', 0),
            'middle_candle_size': fvg.get('middle_candle_size', 0),
            'is_filled': fvg.get('is_filled', False),
            'fill_probability': fvg.get('fill_probability', 'medium'),
            'confidence': fvg.get('confidence', 75),
            'full_reason': reason,
            'fvg_type': fvg['type'],  # Add this to help with filtering
            'pattern_description': 'Fair Value Gap - untested price area that acts as support/resistance'
        }
    }


def build_drawing_json_from_llm(symbol, llm_analysis):
    """
    Build drawing JSON directly from LLM analysis output
    
    Args:
        symbol (str): Stock symbol
        llm_analysis (dict): Raw LLM analysis with patterns, zones, indicators
    
    Returns:
        list: Array of TradingView drawing objects
    """
    drawings = []
    
    try:
        # Extract data from LLM analysis
        patterns = llm_analysis.get('patterns', [])
        zones = llm_analysis.get('zones', [])
        fvg_zones = llm_analysis.get('fvg_zones', [])  # Add FVG zones
        smc_data = llm_analysis.get('smc_data', {})  # Add SMC data
        indicators = llm_analysis.get('indicators', {})
        
        # Add zones with validation
        for zone in zones:
            # Ensure validation field exists
            if 'validation' not in zone:
                zone['validation'] = {
                    'base_tight': zone.get('base_range', 999) <= 1.5,  # Simplified check
                    'impulse_strong': zone.get('impulse_strength', 0) >= 2.0,
                    'departure_clean': zone.get('wick_ratio', 1) <= 0.25,
                    'all_criteria_met': zone.get('confidence', 0) >= 85
                }
            drawings.append(build_zone_json(zone, symbol))
        
        # Add FVG zones
        for fvg in fvg_zones:
            drawings.append(build_fvg_json(fvg, symbol))

        # Add FVG Order-Block drawings (Pine `FVG Order Blocks [BigBeluga]`)
        fvg_ob_data = llm_analysis.get('fvg_ob_data', {})
        if fvg_ob_data and (fvg_ob_data.get('bull_blocks') or fvg_ob_data.get('bear_blocks')):
            logger.info(
                f"🔧 Processing FVG-OB data — "
                f"bull={len(fvg_ob_data.get('bull_blocks', []))} / "
                f"bear={len(fvg_ob_data.get('bear_blocks', []))}"
            )
            try:
                fvg_ob_drawings = build_fvg_ob_drawings(fvg_ob_data, symbol)
                drawings.extend(fvg_ob_drawings)
                logger.info(f"✅ Added {len(fvg_ob_drawings)} FVG-OB drawings")
            except Exception as e:
                logger.error(f"Error processing FVG-OB data: {e}")
        else:
            logger.info(f"ℹ️  No FVG-OB data present - skipping FVG order-block drawings")

        # Add Supply / Demand Zone drawings (Pine `Supply and Demand Zones [BigBeluga]`)
        sdz_data = llm_analysis.get('supply_demand_zones_data', {})
        if sdz_data and (sdz_data.get('supply_zones') or sdz_data.get('demand_zones')):
            logger.info(
                f"🔧 Processing Supply/Demand Zones data — "
                f"supply={len(sdz_data.get('supply_zones', []))} / "
                f"demand={len(sdz_data.get('demand_zones', []))}"
            )
            try:
                sdz_drawings = build_supply_demand_zones_drawings(sdz_data, symbol)
                drawings.extend(sdz_drawings)
                logger.info(f"✅ Added {len(sdz_drawings)} Supply/Demand Zone drawings")
            except Exception as e:
                logger.error(f"Error processing Supply/Demand Zones data: {e}")
        else:
            logger.info(f"ℹ️  No Supply/Demand Zones data present - skipping SDZ drawings")

        # Add SMC drawings
        if smc_data:
            logger.info(f"🔧 Processing SMC data for JSON building...")
            logger.info(f"   SMC data keys: {list(smc_data.keys())}")
            
            # Get the dataframe index for timestamp conversion
            df_index = smc_data.get('df_index')
            logger.info(f"   DataFrame index available: {df_index is not None}")
            
            # Add swing structures (BOS/CHoCH)
            swing_structures = smc_data.get('swing_structure', [])
            logger.info(f"   Swing structures: {len(swing_structures)}")
            for structure in swing_structures:
                logger.info(f"     Adding swing structure: {structure.tag}")
                drawings.append(build_smc_structure_json(structure, symbol, df_index))
            
            # Add internal structures (dashed lines)
            internal_structures = smc_data.get('internal_structure', [])
            logger.info(f"   Internal structures: {len(internal_structures)}")
            for structure in internal_structures:
                logger.info(f"     Adding internal structure: {structure.tag}")
                structure_json = build_smc_structure_json(structure, symbol, df_index)
                # Make internal structures dashed
                structure_json['state']['linestyle'] = 2  # Dashed
                structure_json['state']['linewidth'] = 1  # Thinner
                structure_json['metadata']['structure_type'] = f"Internal {structure.tag}"
                drawings.append(structure_json)
            
            # Add swing order blocks
            swing_obs = smc_data.get('swing_obs', [])
            logger.info(f"   Swing order blocks: {len(swing_obs)}")
            for ob in swing_obs:
                logger.info(f"     Adding swing order block: bias={ob.bias}")
                drawings.append(build_smc_order_block_json(ob, symbol, is_internal=False, df_index=df_index))
            
            # Add internal order blocks
            internal_obs = smc_data.get('internal_obs', [])
            logger.info(f"   Internal order blocks: {len(internal_obs)}")
            for ob in internal_obs:
                logger.info(f"     Adding internal order block: bias={ob.bias}")
                drawings.append(build_smc_order_block_json(ob, symbol, is_internal=True, df_index=df_index))
            
            # Add SMC FVGs (different from regular FVGs)
            smc_fvgs = smc_data.get('smc_fvgs', [])
            logger.info(f"   SMC FVGs: {len(smc_fvgs)}")
            for fvg in smc_fvgs:
                logger.info(f"     Adding SMC FVG: bias={getattr(fvg, 'bias', 'unknown')}")
                try:
                    # Convert SMC FVG object to dictionary format expected by build_fvg_json
                    # SMC FairValueGap has: top, bottom, bias, left_idx, right_idx
                    fvg_dict = {
                        'type': 'bullish_fvg' if getattr(fvg, 'bias', 1) == 1 else 'bearish_fvg',
                        'start_time': int(getattr(fvg, 'left_idx', 0) * 86400),  # Convert index to timestamp
                        'end_time': int(getattr(fvg, 'right_idx', 0) * 86400),
                        'high': getattr(fvg, 'top', 0),
                        'low': getattr(fvg, 'bottom', 0),
                        'gap_size': abs(getattr(fvg, 'top', 0) - getattr(fvg, 'bottom', 0)),
                        'gap_percentage': abs(getattr(fvg, 'top', 0) - getattr(fvg, 'bottom', 0)) / max(getattr(fvg, 'top', 1), getattr(fvg, 'bottom', 1)) * 100,
                        'middle_candle_index': int((getattr(fvg, 'left_idx', 0) + getattr(fvg, 'right_idx', 0)) / 2),
                        'middle_candle_size': abs(getattr(fvg, 'top', 0) - getattr(fvg, 'bottom', 0)),
                        'is_filled': False,  # SMC FVGs are typically unfilled when detected
                        'fill_probability': 'high',  # SMC FVGs are considered high probability
                        'confidence': 90  # SMC FVGs have high confidence
                    }
                    
                    # Build FVG JSON and add SMC-specific metadata
                    fvg_json = build_fvg_json(fvg_dict, symbol)
                    fvg_json['metadata']['smc_type'] = 'smc_fvg'
                    fvg_json['metadata']['smc_fvg_type'] = fvg_dict['type']
                    fvg_json['metadata']['full_reason'] = f"🔥 SMC FVG: {fvg_dict['gap_percentage']:.1f}% gap - Smart Money Fair Value Gap"
                    drawings.append(fvg_json)
                    logger.info(f"     ✅ Successfully added SMC FVG: {fvg_dict['type']}")
                except Exception as e:
                    logger.error(f"Error processing SMC FVG: {e}")
                    # Skip this FVG and continue with others
                    continue
            
            # Add equal levels
            equal_levels = smc_data.get('equal_levels', [])
            logger.info(f"   Equal levels: {len(equal_levels)}")
            for eq in equal_levels:
                drawings.append(build_smc_equal_level_json(eq, symbol, df_index))
            
            # Add premium/discount zones
            swing_top = smc_data.get('swing_top')
            swing_bottom = smc_data.get('swing_bottom')
            logger.info(f"   Swing top: {swing_top}, Swing bottom: {swing_bottom}")
            if swing_top is not None and swing_bottom is not None and not (np.isnan(swing_top) or np.isnan(swing_bottom)):
                logger.info(f"     Adding premium/discount zones")
                drawings.append(build_smc_premium_discount_json(swing_top, swing_bottom, symbol, 'premium'))
                drawings.append(build_smc_premium_discount_json(swing_top, swing_bottom, symbol, 'discount'))
                drawings.append(build_smc_premium_discount_json(swing_top, swing_bottom, symbol, 'equilibrium'))
            else:
                logger.info(f"     Skipping premium/discount zones (invalid swing levels)")
        else:
            logger.warning(f"⚠️  No SMC data found in analysis - SMC drawings will not be generated")
        
        # Add Liquidity Sweeps drawings
        liquidity_sweeps_data = llm_analysis.get('liquidity_sweeps_data', {})
        if liquidity_sweeps_data:
            logger.info(f"🔧 Processing Liquidity Sweeps data for JSON building...")
            
            # Get the dataframe index for timestamp conversion
            df_index = liquidity_sweeps_data.get('df_index')
            logger.info(f"   DataFrame index available: {df_index is not None}")
            
            # Get sweeps data
            sweeps = liquidity_sweeps_data.get('sweeps', [])
            logger.info(f"   Liquidity sweeps: {len(sweeps)}")
            
            # Process each sweep and create drawings
            for sweep_dict in sweeps:
                try:
                    # Convert sweep dictionary to object-like structure for JSON builders
                    class SweepObj:
                        def __init__(self, sweep_data):
                            self.pivot_price = sweep_data.get('pivot_price', 0)
                            self.sweep_bar = sweep_data.get('bar_index', 0)
                            self.dot_price = sweep_data.get('pivot_price', 0)  # Use pivot as fallback
                            self.direction = 1 if sweep_data.get('direction') == 'bullish' else -1
                            self.kind = sweep_data.get('kind', 'wick')
                            self.box_top = sweep_data.get('box_top', 0)
                            self.box_bottom = sweep_data.get('box_bottom', 0)
                            self.box_left = sweep_data.get('bar_index', 0)
                            self.box_right = min(sweep_data.get('bar_index', 0) + 20, len(df_index)-1 if df_index is not None else sweep_data.get('bar_index', 0) + 20)
                            self.broken = sweep_data.get('broken', False)
                    
                    sweep_obj = SweepObj(sweep_dict)
                    
                    # Create sweep box
                    logger.info(f"     Adding liquidity sweep box: {sweep_dict.get('direction')} {sweep_dict.get('kind')}")
                    drawings.append(build_liquidity_sweep_box_json(sweep_obj, symbol, df_index))
                    
                    # Create pivot line
                    logger.info(f"     Adding liquidity sweep pivot line at {sweep_obj.pivot_price:.2f}")
                    drawings.append(build_liquidity_sweep_line_json(sweep_obj, symbol, df_index))
                    
                    # Create sweep dot
                    logger.info(f"     Adding liquidity sweep dot at {sweep_obj.dot_price:.2f}")
                    drawings.append(build_liquidity_sweep_dot_json(sweep_obj, symbol, df_index))
                    
                except Exception as e:
                    logger.error(f"Error processing liquidity sweep: {e}")
                    continue
            
            logger.info(f"✅ Successfully processed {len(sweeps)} liquidity sweeps")
        else:
            logger.warning(f"⚠️  No Liquidity Sweeps data found in analysis - Liquidity Sweeps drawings will not be generated")
        
        # Add MACD drawings
        macd_data = llm_analysis.get('macd_data', {})
        if macd_data and not macd_data.get('macd_df', pd.DataFrame()).empty:
            logger.info(f"🔧 Processing MACD data for JSON building...")
            
            # Get the dataframe index for timestamp conversion
            df_index = macd_data.get('df_index')
            logger.info(f"   DataFrame index available: {df_index is not None}")
            
            try:
                # Add MACD line
                macd_line = build_macd_line_json(macd_data, symbol, 'macd', df_index)
                if macd_line:
                    logger.info(f"     Adding MACD line")
                    drawings.append(macd_line)
                
                # Add Signal line
                signal_line = build_macd_line_json(macd_data, symbol, 'signal', df_index)
                if signal_line:
                    logger.info(f"     Adding Signal line")
                    drawings.append(signal_line)
                
                # Add Zero line
                zero_line = build_macd_zero_line_json(symbol)
                logger.info(f"     Adding Zero line")
                drawings.append(zero_line)
                
                # Add MACD alerts
                alerts = macd_data.get('alerts', [])
                logger.info(f"     Processing {len(alerts)} MACD alerts")
                for alert in alerts[-10:]:  # Limit to last 10 alerts
                    alert_drawing = build_macd_alert_json(alert, symbol, df_index)
                    if alert_drawing:
                        logger.info(f"       Adding alert: {alert['type']} at {alert['date']}")
                        drawings.append(alert_drawing)
                
                # Add current status
                status_drawing = build_macd_current_status_json(macd_data, symbol, df_index)
                logger.info(f"     Adding MACD current status")
                drawings.append(status_drawing)
                
                logger.info(f"✅ Successfully processed MACD data - {macd_data.get('trend', 'neutral')} trend")
                
            except Exception as e:
                logger.error(f"Error processing MACD data: {e}")
        else:
            logger.warning(f"⚠️  No MACD data found in analysis - MACD drawings will not be generated")

        # Add Liquidity Swings (LuxAlgo) drawings
        liquidity_data = llm_analysis.get('liquidity_data', {})
        if liquidity_data and (liquidity_data.get('high_zones') or liquidity_data.get('low_zones')):
            logger.info(
                f"🔧 Processing Liquidity Swings data — "
                f"highs={len(liquidity_data.get('high_zones', []))} / "
                f"lows={len(liquidity_data.get('low_zones', []))}"
            )
            try:
                liq_drawings = build_liquidity_swings_drawings(liquidity_data, symbol)
                drawings.extend(liq_drawings)
                logger.info(f"✅ Added {len(liq_drawings)} liquidity-swings drawings")
            except Exception as e:
                logger.error(f"Error processing Liquidity Swings data: {e}")
        else:
            logger.info(f"ℹ️  No Liquidity Swings data present - skipping liquidity drawings")

        # Add Order Block Finder (wugamlo) drawings
        ob_finder_data = llm_analysis.get('ob_finder_data', {})
        if ob_finder_data and (ob_finder_data.get('bull_obs') or ob_finder_data.get('bear_obs')):
            logger.info(
                f"🔧 Processing OB-Finder data — "
                f"bull={len(ob_finder_data.get('bull_obs', []))} / "
                f"bear={len(ob_finder_data.get('bear_obs', []))}"
            )
            try:
                ob_drawings = build_ob_finder_drawings(ob_finder_data, symbol)
                drawings.extend(ob_drawings)
                logger.info(f"✅ Added {len(ob_drawings)} OB-finder drawings")
            except Exception as e:
                logger.error(f"Error processing OB-Finder data: {e}")
        else:
            logger.info(f"ℹ️  No OB-Finder data present - skipping OB-finder drawings")

        # Add Price-Action / SMC (BigBeluga) drawings
        price_action_data = llm_analysis.get('price_action_data', {})
        if price_action_data and (
            price_action_data.get('events') or price_action_data.get('order_blocks')
        ):
            logger.info(
                f"🔧 Processing Price-Action SMC data — "
                f"events={len(price_action_data.get('events', []))}, "
                f"obs={len(price_action_data.get('order_blocks', []))}"
            )
            try:
                pa_drawings = build_pa_drawings(price_action_data, symbol)
                drawings.extend(pa_drawings)
                logger.info(f"✅ Added {len(pa_drawings)} price-action SMC drawings")
            except Exception as e:
                logger.error(f"Error processing Price-Action data: {e}")
        else:
            logger.info(f"ℹ️  No Price-Action data present - skipping SMC drawings")

        # Add Market Structure (zigzag + MSB + OB/BB) drawings.
        # We emit even when there are 0 MSB events, as long as the pivots/zigzag
        # skeleton is present — it's still useful structural context.
        market_structure_data = llm_analysis.get('market_structure_data', {})
        has_events = bool(market_structure_data.get('events'))
        has_zigzag = bool(market_structure_data.get('zigzag_lines'))
        if market_structure_data and (has_events or has_zigzag):
            logger.info(f"🔧 Processing Market Structure data for JSON building...")
            logger.info(
                f"   MSB events: {len(market_structure_data.get('events', []))} | "
                f"zigzag segments: {len(market_structure_data.get('zigzag_lines', []))}"
            )
            try:
                ms_drawings = build_market_structure_drawings(market_structure_data, symbol)
                drawings.extend(ms_drawings)
                logger.info(f"✅ Added {len(ms_drawings)} market-structure drawings")
            except Exception as e:
                logger.error(f"Error processing Market Structure data: {e}")
        else:
            logger.info(f"ℹ️  No Market Structure data present - skipping MSB drawings")

        # Add patterns
        for pattern in patterns:
            drawings.append(build_pattern_json(pattern, symbol))
        
        # Process RSI signals
        rsi_data = indicators.get('rsi', {})
        if rsi_data:
            rsi_formatted = {
                'overbought': rsi_data.get('overbought_signals', []),
                'oversold': rsi_data.get('oversold_signals', [])
            }
            drawings.extend(build_rsi_json(rsi_formatted, symbol))
        
        # Process MACD signals
        macd_data = indicators.get('macd', {})
        if macd_data:
            macd_crossovers = []
            
            # Bullish crossovers
            for crossover in macd_data.get('bullish_crossovers', []):
                macd_crossovers.append({
                    'type': 'bullish',
                    'timestamp': crossover['timestamp'],
                    'price': crossover['price']
                })
            
            # Bearish crossovers
            for crossover in macd_data.get('bearish_crossovers', []):
                macd_crossovers.append({
                    'type': 'bearish',
                    'timestamp': crossover['timestamp'],
                    'price': crossover['price']
                })
            
            macd_formatted = {'crossovers': macd_crossovers}
            drawings.extend(build_macd_json(macd_formatted, symbol))
        
        # Process key levels
        key_levels = indicators.get('key_levels', [])
        for level in key_levels:
            drawings.append(build_level_json(level, symbol))
        
        # Note: Bollinger Bands from LLM are current values only, not historical
        # We skip them as they need historical data points for proper visualization
        
        logger.info(f"Built {len(drawings)} drawing instructions from LLM analysis for {symbol}")
        return drawings
    
    except Exception as e:
        logger.error(f"Error building drawing JSON from LLM: {e}")
        logger.error(f"Traceback:", exc_info=True)
        # Return empty list instead of crashing
        return []
    
    except Exception as e:
        logger.error(f"Error building drawing JSON from LLM: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return []


def build_smc_structure_json(structure, symbol, df_index=None):
    """Build JSON for SMC structure (BOS/CHoCH) - TradingView Horizontal Line format"""
    structure_id = generate_unique_id()
    
    # Color based on structure type and bias
    if structure.bias == 1:  # BULLISH
        line_color = '#089981'  # Green
        text = f'🟢 {structure.tag}'
    else:  # BEARISH
        line_color = '#F23645'  # Red
        text = f'🔴 {structure.tag}'
    
    # Convert bar index to timestamp
    if df_index is not None and structure.bar_index < len(df_index):
        timestamp = int(df_index[structure.bar_index].timestamp())
    else:
        timestamp = int(structure.bar_index * 86400)  # Fallback
    
    return {
        'id': structure_id,
        'type': 'LineToolHorzLine',
        'state': {
            'symbol': symbol,
            'interval': '1D',
            'frozen': False,
            'visible': True,
            'linecolor': line_color,
            'linewidth': 2,
            'linestyle': 0 if structure.tag == 'BOS' else 2,  # Solid for BOS, dashed for CHoCH
            'showLabel': True,
            'text': text,
            'textcolor': line_color,
            'fontsize': 11,
            'bold': True,
            'italic': False,
            'horzLabelsAlign': 'right',
            'vertLabelsAlign': 'middle',
            'zOrderVersion': 2,
            'symbolStateVersion': 2,
            'intervalsVisibilities': {
                'ticks': True, 'seconds': True, 'secondsFrom': 1, 'secondsTo': 59,
                'minutes': True, 'minutesFrom': 1, 'minutesTo': 59,
                'hours': True, 'hoursFrom': 1, 'hoursTo': 24,
                'days': True, 'daysFrom': 1, 'daysTo': 366,
                'weeks': True, 'weeksFrom': 1, 'weeksTo': 52,
                'months': True, 'monthsFrom': 1, 'monthsTo': 12,
                'ranges': True
            }
        },
        'points': [
            {
                'price': structure.price,
                'time_t': timestamp,
                'offset': 0
            }
        ],
        'zorder': -6500,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False,
        'isSelectionEnabled': True,
        'metadata': {
            'smc_type': 'structure',
            'structure_type': structure.tag,
            'structure_bias': 'bullish' if structure.bias == 1 else 'bearish',
            'full_reason': f'{structure.tag} - {text}'
        }
    }


def build_smc_order_block_json(order_block, symbol, is_internal=False, df_index=None):
    """Build JSON for SMC Order Block - TradingView Rectangle format"""
    ob_id = generate_unique_id()
    
    # Color based on order block bias and type
    if order_block.bias == 1:  # BULLISH
        if is_internal:
            fill_color = 'rgba(49, 121, 245, 0.3)'  # Light blue
            line_color = '#3179f5'
            text = '🔵 Internal Bull OB'
        else:
            fill_color = 'rgba(24, 72, 204, 0.3)'  # Darker blue
            line_color = '#1848cc'
            text = '🟦 Bull OB'
    else:  # BEARISH
        if is_internal:
            fill_color = 'rgba(247, 124, 128, 0.3)'  # Light red
            line_color = '#f77c80'
            text = '🔴 Internal Bear OB'
        else:
            fill_color = 'rgba(178, 40, 51, 0.3)'  # Darker red
            line_color = '#b22833'
            text = '🟥 Bear OB'
    
    # Convert bar index to timestamp
    if df_index is not None and order_block.bar_index < len(df_index):
        start_timestamp = int(df_index[order_block.bar_index].timestamp())
        end_timestamp = int(df_index[-1].timestamp())  # Extend to end of data
    else:
        start_timestamp = int(order_block.bar_index * 86400)  # Fallback
        end_timestamp = start_timestamp + 86400 * 50  # Extend 50 bars
    
    return {
        'id': ob_id,
        'type': 'LineToolRectangle',
        'state': {
            'symbol': symbol,
            'interval': '1D',
            'frozen': False,
            'visible': True,
            'fillBackground': True,
            'backgroundColor': fill_color,
            'backgroundTransparency': 70,
            'linecolor': line_color,
            'linewidth': 1,
            'linestyle': 0,  # Solid line
            'extendLeft': False,
            'extendRight': True,  # Extend right for order blocks
            'showLabel': True,
            'text': text,
            'textcolor': '#FFFFFF',
            'fontsize': 10,
            'bold': False,
            'italic': False,
            'zOrderVersion': 2,
            'symbolStateVersion': 2,
            'intervalsVisibilities': {
                'ticks': True, 'seconds': True, 'secondsFrom': 1, 'secondsTo': 59,
                'minutes': True, 'minutesFrom': 1, 'minutesTo': 59,
                'hours': True, 'hoursFrom': 1, 'hoursTo': 24,
                'days': True, 'daysFrom': 1, 'daysTo': 366,
                'weeks': True, 'weeksFrom': 1, 'weeksTo': 52,
                'months': True, 'monthsFrom': 1, 'monthsTo': 12,
                'ranges': True
            }
        },
        'points': [
            {
                'price': order_block.bar_high,
                'time_t': start_timestamp,
                'offset': 0
            },
            {
                'price': order_block.bar_low,
                'time_t': end_timestamp,
                'offset': 0
            }
        ],
        'zorder': -5500,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False,
        'isSelectionEnabled': True,
        'metadata': {
            'smc_type': 'order_block',
            'order_block_type': 'internal' if is_internal else 'swing',
            'order_block_bias': 'bullish' if order_block.bias == 1 else 'bearish',
            'full_reason': text
        }
    }


def build_smc_equal_level_json(equal_level, symbol, df_index=None):
    """Build JSON for SMC Equal High/Low - TradingView Trend Line format"""
    eq_id = generate_unique_id()
    
    # Color based on equal level type
    if equal_level.kind == 'EQH':
        line_color = '#F23645'  # Red for Equal Highs
        text = '🔴 EQH'
    else:
        line_color = '#089981'  # Green for Equal Lows
        text = '🟢 EQL'
    
    # Convert bar indices to timestamps
    if df_index is not None:
        if equal_level.idx1 < len(df_index) and equal_level.idx2 < len(df_index):
            timestamp1 = int(df_index[equal_level.idx1].timestamp())
            timestamp2 = int(df_index[equal_level.idx2].timestamp())
        else:
            timestamp1 = int(equal_level.idx1 * 86400)  # Fallback
            timestamp2 = int(equal_level.idx2 * 86400)
    else:
        timestamp1 = int(equal_level.idx1 * 86400)  # Fallback
        timestamp2 = int(equal_level.idx2 * 86400)
    
    return {
        'id': eq_id,
        'type': 'LineToolTrendLine',
        'state': {
            'symbol': symbol,
            'interval': '1D',
            'frozen': False,
            'visible': True,
            'linecolor': line_color,
            'linewidth': 1,
            'linestyle': 3,  # Dotted line
            'extendLeft': False,
            'extendRight': False,
            'showLabel': True,
            'text': text,
            'textcolor': line_color,
            'fontsize': 9,
            'bold': False,
            'italic': False,
            'zOrderVersion': 2,
            'symbolStateVersion': 2,
            'intervalsVisibilities': {
                'ticks': True, 'seconds': True, 'secondsFrom': 1, 'secondsTo': 59,
                'minutes': True, 'minutesFrom': 1, 'minutesTo': 59,
                'hours': True, 'hoursFrom': 1, 'hoursTo': 24,
                'days': True, 'daysFrom': 1, 'daysTo': 366,
                'weeks': True, 'weeksFrom': 1, 'weeksTo': 52,
                'months': True, 'monthsFrom': 1, 'monthsTo': 12,
                'ranges': True
            }
        },
        'points': [
            {
                'price': equal_level.price,
                'time_t': timestamp1,
                'offset': 0
            },
            {
                'price': equal_level.price,
                'time_t': timestamp2,
                'offset': 0
            }
        ],
        'zorder': -6000,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False,
        'isSelectionEnabled': True,
        'metadata': {
            'smc_type': 'equal_level',
            'equal_level_type': equal_level.kind.lower(),
            'full_reason': f'{text} - Equal {equal_level.kind[2:]} at {equal_level.price:.2f}'
        }
    }


def build_smc_premium_discount_json(swing_top, swing_bottom, symbol, zone_type):
    """Build JSON for SMC Premium/Discount zones - TradingView Rectangle format"""
    zone_id = generate_unique_id()
    
    # Calculate zone boundaries
    price_range = swing_top - swing_bottom
    
    if zone_type == 'premium':
        zone_high = swing_top
        zone_low = swing_top - 0.25 * price_range
        fill_color = 'rgba(242, 54, 69, 0.06)'  # Light red
        line_color = '#F23645'
        text = '🔴 Premium'
    elif zone_type == 'discount':
        zone_high = swing_bottom + 0.25 * price_range
        zone_low = swing_bottom
        fill_color = 'rgba(8, 153, 129, 0.06)'  # Light green
        line_color = '#089981'
        text = '🟢 Discount'
    else:  # equilibrium
        zone_high = 0.525 * swing_top + 0.475 * swing_bottom
        zone_low = 0.525 * swing_bottom + 0.475 * swing_top
        fill_color = 'rgba(135, 139, 148, 0.05)'  # Light gray
        line_color = '#878b94'
        text = '⚪ EQ'
    
    return {
        'id': zone_id,
        'type': 'LineToolRectangle',
        'state': {
            'symbol': symbol,
            'interval': '1D',
            'frozen': False,
            'visible': True,
            'fillBackground': True,
            'backgroundColor': fill_color,
            'backgroundTransparency': 94,
            'linecolor': line_color,
            'linewidth': 0,  # No border
            'linestyle': 0,
            'extendLeft': True,
            'extendRight': True,
            'showLabel': True,
            'text': text,
            'textcolor': line_color,
            'fontsize': 10,
            'bold': False,
            'italic': False,
            'zOrderVersion': 1,
            'symbolStateVersion': 2,
            'intervalsVisibilities': {
                'ticks': True, 'seconds': True, 'secondsFrom': 1, 'secondsTo': 59,
                'minutes': True, 'minutesFrom': 1, 'minutesTo': 59,
                'hours': True, 'hoursFrom': 1, 'hoursTo': 24,
                'days': True, 'daysFrom': 1, 'daysTo': 366,
                'weeks': True, 'weeksFrom': 1, 'weeksTo': 52,
                'months': True, 'monthsFrom': 1, 'monthsTo': 12,
                'ranges': True
            }
        },
        'points': [
            {
                'price': zone_high,
                'time_t': 0,  # Start from beginning
                'offset': 0
            },
            {
                'price': zone_low,
                'time_t': int(86400 * 365 * 10),  # Extend far into future
                'offset': 0
            }
        ],
        'zorder': -8000,  # Behind everything
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False,
        'isSelectionEnabled': True,
        'metadata': {
            'smc_type': 'premium_discount',
            'zone_type': zone_type,
            'full_reason': f'{text} zone - {zone_type.title()} area'
        }
    }


def build_liquidity_sweep_box_json(sweep, symbol, df_index=None):
    """Build JSON for Liquidity Sweep Box - TradingView Rectangle format"""
    sweep_id = generate_unique_id()
    
    # Convert bar indices to timestamps if df_index is provided
    if df_index is not None and hasattr(df_index, '__getitem__'):
        try:
            start_time = int(df_index[sweep.box_left].timestamp())
            end_time = int(df_index[min(sweep.box_right, len(df_index)-1)].timestamp())
        except (IndexError, AttributeError):
            start_time = sweep.box_left * 86400  # Fallback: assume daily bars
            end_time = sweep.box_right * 86400
    else:
        start_time = sweep.box_left * 86400
        end_time = sweep.box_right * 86400
    
    # Color based on sweep direction
    if sweep.direction == 1:  # Bullish sweep
        fill_color = 'rgba(8, 153, 129, 0.15)'  # Green with transparency
        line_color = '#089981'
        text = '🟢 Bull Sweep ↑'
    else:  # Bearish sweep
        fill_color = 'rgba(242, 54, 69, 0.15)'  # Red with transparency
        line_color = '#f23645'
        text = '🔴 Bear Sweep ↓'
    
    # Add sweep type to text
    text += f' ({sweep.kind})'
    
    # Add broken indicator
    if sweep.broken:
        text += ' ✗'
    
    return {
        'id': sweep_id,
        'type': 'LineToolRectangle',
        'state': {
            'symbol': symbol,
            'interval': '1D',
            'frozen': False,
            'visible': True,
            'fillBackground': True,
            'backgroundColor': fill_color,
            'backgroundTransparency': 85,
            'linecolor': line_color,
            'linewidth': 1,
            'linestyle': 0,  # Solid line
            'extendLeft': False,
            'extendRight': False,
            'showLabel': True,
            'text': text,
            'textcolor': line_color,
            'fontsize': 10,
            'bold': True,
            'italic': False,
            'zOrderVersion': 3,
            'symbolStateVersion': 2,
            'intervalsVisibilities': {
                'ticks': True, 'seconds': True, 'secondsFrom': 1, 'secondsTo': 59,
                'minutes': True, 'minutesFrom': 1, 'minutesTo': 59,
                'hours': True, 'hoursFrom': 1, 'hoursTo': 24,
                'days': True, 'daysFrom': 1, 'daysTo': 366,
                'weeks': True, 'weeksFrom': 1, 'weeksTo': 52,
                'months': True, 'monthsFrom': 1, 'monthsTo': 12,
                'ranges': True
            }
        },
        'points': [
            {
                'price': sweep.box_top,
                'time_t': start_time,
                'offset': 0
            },
            {
                'price': sweep.box_bottom,
                'time_t': end_time,
                'offset': 0
            }
        ],
        'zorder': -3000,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False,
        'isSelectionEnabled': True,
        'metadata': {
            'sweep_type': 'liquidity_sweep',
            'pivot_price': sweep.pivot_price,
            'sweep_direction': 'bullish' if sweep.direction == 1 else 'bearish',
            'sweep_kind': sweep.kind,
            'broken': sweep.broken,
            'full_reason': f'{text} - Pivot at {sweep.pivot_price:.2f}'
        }
    }


def build_liquidity_sweep_line_json(sweep, symbol, df_index=None):
    """Build JSON for Liquidity Sweep Pivot Line - TradingView Horizontal Line format"""
    line_id = generate_unique_id()
    
    # Convert bar indices to timestamps if df_index is provided
    if df_index is not None and hasattr(df_index, '__getitem__'):
        try:
            start_time = int(df_index[sweep.box_left].timestamp())
            end_time = int(df_index[min(sweep.box_right, len(df_index)-1)].timestamp())
        except (IndexError, AttributeError):
            start_time = sweep.box_left * 86400
            end_time = sweep.box_right * 86400
    else:
        start_time = sweep.box_left * 86400
        end_time = sweep.box_right * 86400
    
    # Color and style based on sweep direction and type
    if sweep.direction == 1:  # Bullish sweep
        line_color = '#089981'
    else:  # Bearish sweep
        line_color = '#f23645'
    
    # Line style based on sweep kind
    line_style = 2 if sweep.kind == 'wick' else 1  # Dotted for wick, dashed for outbreak
    
    return {
        'id': line_id,
        'type': 'LineToolHorzLine',
        'state': {
            'symbol': symbol,
            'interval': '1D',
            'frozen': False,
            'visible': True,
            'linecolor': line_color,
            'linewidth': 1,
            'linestyle': line_style,
            'extendLeft': False,
            'extendRight': False,
            'showLabel': False,
            'zOrderVersion': 4,
            'symbolStateVersion': 2,
            'intervalsVisibilities': {
                'ticks': True, 'seconds': True, 'secondsFrom': 1, 'secondsTo': 59,
                'minutes': True, 'minutesFrom': 1, 'minutesTo': 59,
                'hours': True, 'hoursFrom': 1, 'hoursTo': 24,
                'days': True, 'daysFrom': 1, 'daysTo': 366,
                'weeks': True, 'weeksFrom': 1, 'weeksTo': 52,
                'months': True, 'monthsFrom': 1, 'monthsTo': 12,
                'ranges': True
            }
        },
        'points': [
            {
                'price': sweep.pivot_price,
                'time_t': start_time,
                'offset': 0
            },
            {
                'price': sweep.pivot_price,
                'time_t': end_time,
                'offset': 0
            }
        ],
        'zorder': -2000,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False,
        'isSelectionEnabled': True,
        'metadata': {
            'sweep_type': 'pivot_line',
            'pivot_price': sweep.pivot_price,
            'sweep_direction': 'bullish' if sweep.direction == 1 else 'bearish',
            'sweep_kind': sweep.kind,
            'full_reason': f'Pivot level at {sweep.pivot_price:.2f} - {sweep.kind} sweep'
        }
    }


def build_liquidity_sweep_dot_json(sweep, symbol, df_index=None):
    """Build JSON for Liquidity Sweep Dot - TradingView Note format"""
    dot_id = generate_unique_id()
    
    # Convert bar index to timestamp if df_index is provided
    if df_index is not None and hasattr(df_index, '__getitem__'):
        try:
            sweep_time = int(df_index[sweep.sweep_bar].timestamp())
        except (IndexError, AttributeError):
            sweep_time = sweep.sweep_bar * 86400
    else:
        sweep_time = sweep.sweep_bar * 86400
    
    # Color based on sweep direction
    if sweep.direction == 1:  # Bullish sweep
        color = '#089981'
        icon = '🟢'
    else:  # Bearish sweep
        color = '#f23645'
        icon = '🔴'
    
    return {
        'id': dot_id,
        'type': 'LineToolNote',
        'state': {
            'symbol': symbol,
            'interval': '1D',
            'frozen': False,
            'visible': True,
            'showLabel': True,
            'text': icon,
            'textcolor': color,
            'fontsize': 12,
            'bold': True,
            'italic': False,
            'backgroundColor': 'rgba(0, 0, 0, 0)',
            'backgroundTransparency': 100,
            'bordercolor': color,
            'borderwidth': 0,
            'zOrderVersion': 5,
            'symbolStateVersion': 2,
            'intervalsVisibilities': {
                'ticks': True, 'seconds': True, 'secondsFrom': 1, 'secondsTo': 59,
                'minutes': True, 'minutesFrom': 1, 'minutesTo': 59,
                'hours': True, 'hoursFrom': 1, 'hoursTo': 24,
                'days': True, 'daysFrom': 1, 'daysTo': 366,
                'weeks': True, 'weeksFrom': 1, 'weeksTo': 52,
                'months': True, 'monthsFrom': 1, 'monthsTo': 12,
                'ranges': True
            }
        },
        'points': [
            {
                'price': sweep.dot_price,
                'time_t': sweep_time,
                'offset': 0
            }
        ],
        'zorder': -1000,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False,
        'isSelectionEnabled': True,
        'metadata': {
            'sweep_type': 'sweep_dot',
            'pivot_price': sweep.pivot_price,
            'dot_price': sweep.dot_price,
            'sweep_direction': 'bullish' if sweep.direction == 1 else 'bearish',
            'sweep_kind': sweep.kind,
            'full_reason': f'Sweep dot at {sweep.dot_price:.2f} - {sweep.kind} sweep of {sweep.pivot_price:.2f}'
        }
    }

def build_macd_line_json(macd_data, symbol, line_type='macd', df_index=None):
    """Build JSON for MACD Line - TradingView Trend Line format"""
    line_id = generate_unique_id()
    
    # Get MACD dataframe
    macd_df = macd_data.get('macd_df', pd.DataFrame())
    if macd_df.empty:
        return None
    
    # Select the line type
    if line_type == 'macd':
        values = macd_df['macd'].values
        line_color = '#2962ff'  # Blue
        text = 'MACD Line'
    elif line_type == 'signal':
        values = macd_df['signal'].values
        line_color = '#ff6d00'  # Orange
        text = 'Signal Line'
    else:
        return None
    
    # Filter out NaN values and get valid points
    valid_indices = ~pd.isna(values)
    if not valid_indices.any():
        return None
    
    valid_values = values[valid_indices]
    valid_positions = np.where(valid_indices)[0]
    
    # Convert indices to timestamps if df_index is provided
    if df_index is not None and hasattr(df_index, '__getitem__'):
        try:
            start_time = int(df_index[valid_positions[0]].timestamp())
            end_time = int(df_index[valid_positions[-1]].timestamp())
        except (IndexError, AttributeError):
            start_time = valid_positions[0] * 86400
            end_time = valid_positions[-1] * 86400
    else:
        start_time = valid_positions[0] * 86400
        end_time = valid_positions[-1] * 86400
    
    return {
        'id': line_id,
        'type': 'LineToolTrendLine',
        'state': {
            'symbol': symbol,
            'interval': '1D',
            'frozen': False,
            'visible': True,
            'linecolor': line_color,
            'linewidth': 2,
            'linestyle': 0,  # Solid line
            'extendLeft': False,
            'extendRight': False,
            'showLabel': True,
            'text': text,
            'textcolor': line_color,
            'fontsize': 10,
            'bold': True,
            'italic': False,
            'zOrderVersion': 4,
            'symbolStateVersion': 2,
            'intervalsVisibilities': {
                'ticks': True, 'seconds': True, 'secondsFrom': 1, 'secondsTo': 59,
                'minutes': True, 'minutesFrom': 1, 'minutesTo': 59,
                'hours': True, 'hoursFrom': 1, 'hoursTo': 24,
                'days': True, 'daysFrom': 1, 'daysTo': 366,
                'weeks': True, 'weeksFrom': 1, 'weeksTo': 52,
                'months': True, 'monthsFrom': 1, 'monthsTo': 12,
                'ranges': True
            }
        },
        'points': [
            {
                'price': float(valid_values[0]),
                'time_t': start_time,
                'offset': 0
            },
            {
                'price': float(valid_values[-1]),
                'time_t': end_time,
                'offset': 0
            }
        ],
        'zorder': -2000,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False,
        'isSelectionEnabled': True,
        'metadata': {
            'macd_type': line_type,
            'macd_value': float(valid_values[-1]),
            'full_reason': f'{text} - Current value: {valid_values[-1]:.4f}'
        }
    }


def build_macd_zero_line_json(symbol):
    """Build JSON for MACD Zero Line - TradingView Horizontal Line format"""
    zero_line_id = generate_unique_id()
    
    return {
        'id': zero_line_id,
        'type': 'LineToolHorzLine',
        'state': {
            'symbol': symbol,
            'interval': '1D',
            'frozen': False,
            'visible': True,
            'linecolor': '#787b86',
            'linewidth': 1,
            'linestyle': 0,  # Solid line
            'extendLeft': True,
            'extendRight': True,
            'showLabel': False,
            'zOrderVersion': 2,
            'symbolStateVersion': 2,
            'intervalsVisibilities': {
                'ticks': True, 'seconds': True, 'secondsFrom': 1, 'secondsTo': 59,
                'minutes': True, 'minutesFrom': 1, 'minutesTo': 59,
                'hours': True, 'hoursFrom': 1, 'hoursTo': 24,
                'days': True, 'daysFrom': 1, 'daysTo': 366,
                'weeks': True, 'weeksFrom': 1, 'weeksTo': 52,
                'months': True, 'monthsFrom': 1, 'monthsTo': 12,
                'ranges': True
            }
        },
        'points': [
            {
                'price': 0.0,
                'time_t': 0,
                'offset': 0
            },
            {
                'price': 0.0,
                'time_t': int(86400 * 365 * 10),  # Extend far into future
                'offset': 0
            }
        ],
        'zorder': -5000,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False,
        'isSelectionEnabled': True,
        'metadata': {
            'macd_type': 'zero_line',
            'full_reason': 'MACD Zero Line - Reference level'
        }
    }


def build_macd_alert_json(alert, symbol, df_index=None):
    """Build JSON for MACD Alert - TradingView Note format"""
    alert_id = generate_unique_id()
    
    # Convert bar index to timestamp if df_index is provided
    if df_index is not None and hasattr(df_index, '__getitem__'):
        try:
            alert_time = int(df_index[alert['bar_index']].timestamp())
        except (IndexError, AttributeError):
            alert_time = alert['bar_index'] * 86400
    else:
        alert_time = alert['bar_index'] * 86400
    
    # Color and icon based on alert type
    if alert['type'] == 'Falling→Rising':
        color = '#089981'  # Green
        icon = '🟢'
        text = f"{icon} F→R\nMACD: {alert['macd']:.3f}\nHist: {alert['hist']:.3f}"
    else:  # Rising→Falling
        color = '#f23645'  # Red
        icon = '🔴'
        text = f"{icon} R→F\nMACD: {alert['macd']:.3f}\nHist: {alert['hist']:.3f}"
    
    # Use histogram value for positioning (above/below zero line)
    price_position = alert['hist']
    
    return {
        'id': alert_id,
        'type': 'LineToolNote',
        'state': {
            'symbol': symbol,
            'interval': '1D',
            'frozen': False,
            'visible': True,
            'showLabel': True,
            'text': text,
            'textcolor': color,
            'fontsize': 9,
            'bold': True,
            'italic': False,
            'backgroundColor': 'rgba(0, 0, 0, 0.8)',
            'backgroundTransparency': 20,
            'bordercolor': color,
            'borderwidth': 1,
            'zOrderVersion': 5,
            'symbolStateVersion': 2,
            'intervalsVisibilities': {
                'ticks': True, 'seconds': True, 'secondsFrom': 1, 'secondsTo': 59,
                'minutes': True, 'minutesFrom': 1, 'minutesTo': 59,
                'hours': True, 'hoursFrom': 1, 'hoursTo': 24,
                'days': True, 'daysFrom': 1, 'daysTo': 366,
                'weeks': True, 'weeksFrom': 1, 'weeksTo': 52,
                'months': True, 'monthsFrom': 1, 'monthsTo': 12,
                'ranges': True
            }
        },
        'points': [
            {
                'price': price_position,
                'time_t': alert_time,
                'offset': 0
            }
        ],
        'zorder': -1000,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False,
        'isSelectionEnabled': True,
        'metadata': {
            'macd_type': 'alert',
            'alert_type': alert['type'],
            'macd_value': alert['macd'],
            'signal_value': alert['signal'],
            'histogram_value': alert['hist'],
            'full_reason': f"MACD Alert: {alert['type']} at {alert['date']} - Histogram: {alert['hist']:.4f}"
        }
    }


def build_macd_current_status_json(macd_data, symbol, df_index=None):
    """Build JSON for MACD Current Status - TradingView Note format"""
    status_id = generate_unique_id()
    
    # Get current values
    latest_macd = macd_data.get('latest_macd', 0)
    latest_signal = macd_data.get('latest_signal', 0)
    latest_histogram = macd_data.get('latest_histogram', 0)
    trend = macd_data.get('trend', 'neutral')
    momentum = macd_data.get('momentum', 'neutral')
    
    # Get latest timestamp
    if df_index is not None and hasattr(df_index, '__getitem__'):
        try:
            latest_time = int(df_index[-1].timestamp())
        except (IndexError, AttributeError):
            latest_time = len(df_index) * 86400
    else:
        latest_time = int(pd.Timestamp.now().timestamp())
    
    # Color based on trend
    if trend == 'bullish':
        color = '#089981'  # Green
        icon = '📈'
    elif trend == 'bearish':
        color = '#f23645'  # Red
        icon = '📉'
    else:
        color = '#787b86'  # Gray
        icon = '➡️'
    
    # Create status text
    text = f"{icon} MACD Status\nTrend: {trend.title()}\nMomentum: {momentum.title()}\nMACD: {latest_macd:.4f}\nSignal: {latest_signal:.4f}\nHist: {latest_histogram:.4f}"
    
    return {
        'id': status_id,
        'type': 'LineToolNote',
        'state': {
            'symbol': symbol,
            'interval': '1D',
            'frozen': False,
            'visible': True,
            'showLabel': True,
            'text': text,
            'textcolor': color,
            'fontsize': 10,
            'bold': True,
            'italic': False,
            'backgroundColor': 'rgba(0, 0, 0, 0.9)',
            'backgroundTransparency': 10,
            'bordercolor': color,
            'borderwidth': 2,
            'zOrderVersion': 6,
            'symbolStateVersion': 2,
            'intervalsVisibilities': {
                'ticks': True, 'seconds': True, 'secondsFrom': 1, 'secondsTo': 59,
                'minutes': True, 'minutesFrom': 1, 'minutesTo': 59,
                'hours': True, 'hoursFrom': 1, 'hoursTo': 24,
                'days': True, 'daysFrom': 1, 'daysTo': 366,
                'weeks': True, 'weeksFrom': 1, 'weeksTo': 52,
                'months': True, 'monthsFrom': 1, 'monthsTo': 12,
                'ranges': True
            }
        },
        'points': [
            {
                'price': latest_histogram,  # Position at histogram level
                'time_t': latest_time,
                'offset': 0
            }
        ],
        'zorder': -500,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False,
        'isSelectionEnabled': True,
        'metadata': {
            'macd_type': 'status',
            'macd_value': latest_macd,
            'signal_value': latest_signal,
            'histogram_value': latest_histogram,
            'trend': trend,
            'momentum': momentum,
            'full_reason': f"MACD Current Status: {trend.title()} trend, {momentum.title()} momentum"
        }
    }


# =====================================================================
#  Market Structure (MSB-OB) builders
# =====================================================================
def _ms_index_to_time(df_index, bar_index, fallback_days=1):
    """Convert a bar index into a unix timestamp using df_index when
    available; fall back to 1-day-per-bar scaling from bar 0 otherwise."""
    try:
        if df_index is not None and 0 <= int(bar_index) < len(df_index):
            return int(df_index[int(bar_index)].timestamp())
    except Exception:
        pass
    return int(int(bar_index) * 86400 * fallback_days)


_MS_INTERVALS_VISIBILITIES = {
    'ticks': True, 'seconds': True, 'secondsFrom': 1, 'secondsTo': 59,
    'minutes': True, 'minutesFrom': 1, 'minutesTo': 59,
    'hours': True, 'hoursFrom': 1, 'hoursTo': 24,
    'days': True, 'daysFrom': 1, 'daysTo': 366,
    'weeks': True, 'weeksFrom': 1, 'weeksTo': 52,
    'months': True, 'monthsFrom': 1, 'monthsTo': 12,
    'ranges': True,
}


def _ms_chart_right_edge_ts(df_index, buffer_days=10):
    """Timestamp of the rightmost bar + buffer (used to extend boxes/lines
    across the entire chart like the Pine `bar_index + 10` pattern)."""
    if df_index is not None and len(df_index) > 0:
        try:
            return int(df_index[-1].timestamp()) + int(buffer_days) * 86400
        except Exception:
            pass
    return None


def build_market_structure_zigzag_json(segment, symbol, df_index=None):
    """Blue TrendLine connecting two consecutive pivots — matches the Pine
    `show_zigzag` output visible in TradingView."""
    line_id = generate_unique_id()
    start_time = _ms_index_to_time(df_index, segment.get('start_idx', 0))
    end_time = _ms_index_to_time(df_index, segment.get('end_idx', 0))

    return {
        'id': line_id,
        'type': 'LineToolTrendLine',
        'state': {
            'symbol': symbol,
            'interval': '1D',
            'frozen': False,
            'visible': True,
            'linecolor': '#2962FF',
            'linewidth': 2,
            'linestyle': 0,
            'extendLeft': False,
            'extendRight': False,
            'showLabel': False,
            'text': '',
            'textcolor': '#2962FF',
            'fontsize': 9,
            'bold': False,
            'italic': False,
            'zOrderVersion': 4,
            'symbolStateVersion': 2,
            'intervalsVisibilities': _MS_INTERVALS_VISIBILITIES,
        },
        'points': [
            {'price': float(segment.get('start_price', 0)), 'time_t': start_time, 'offset': 0},
            {'price': float(segment.get('end_price', 0)), 'time_t': end_time, 'offset': 0},
        ],
        'zorder': -3500,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False,
        'isSelectionEnabled': True,
        'metadata': {
            'market_structure_type': 'zigzag',
            'ms_direction': segment.get('direction', 'up'),
            'full_reason': f"ZigZag {segment.get('direction', 'up')} leg"
        }
    }


def build_market_structure_line_json(event, symbol, df_index=None):
    """Horizontal MSB break line (TradingView TrendLine) drawn at the broken
    pivot price. Bullish → green, bearish → red; matches the Pine script's
    `line.new(h1i, h1, h0i, h1, ...)` / `line.new(l1i, l1, l0i, l1, ...)`.
    """
    line_id = generate_unique_id()

    direction = event.get('direction', 'bullish')
    msb = event.get('msb', {})

    if direction == 'bullish':
        line_color = '#089981'
    else:
        line_color = '#F23645'

    start_time = _ms_index_to_time(df_index, msb.get('start_idx', 0))
    end_time = _ms_index_to_time(df_index, msb.get('end_idx', msb.get('start_idx', 0)))

    return {
        'id': line_id,
        'type': 'LineToolTrendLine',
        'state': {
            'symbol': symbol,
            'interval': '1D',
            'frozen': False,
            'visible': True,
            'linecolor': line_color,
            'linewidth': 3,
            'linestyle': 0,
            'extendLeft': False,
            'extendRight': False,
            'showLabel': True,
            'text': 'MSB',
            'textcolor': line_color,
            'fontsize': 12,
            'bold': True,
            'italic': False,
            'horzLabelsAlign': 'center',
            'vertLabelsAlign': 'top' if direction == 'bullish' else 'bottom',
            'zOrderVersion': 4,
            'symbolStateVersion': 2,
            'intervalsVisibilities': _MS_INTERVALS_VISIBILITIES,
        },
        'points': [
            {'price': float(msb.get('start_price', 0)), 'time_t': start_time, 'offset': 0},
            {'price': float(msb.get('end_price', msb.get('start_price', 0))), 'time_t': end_time, 'offset': 0},
        ],
        'zorder': -2500,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False,
        'isSelectionEnabled': True,
        'metadata': {
            'market_structure_type': 'msb_line',
            'ms_direction': direction,
            'full_reason': f"Market Structure Break ({direction}) at {msb.get('start_price', 0):.2f}"
        }
    }


def build_market_structure_label_json(event, symbol, df_index=None):
    """MSB text label anchored near the MSB break — bullish labels sit above
    the line, bearish labels below, matching Pine's `label.style_label_down`
    / `label.style_label_up` pick."""
    label_id = generate_unique_id()

    direction = event.get('direction', 'bullish')
    if direction == 'bullish':
        color = '#089981'
    else:
        color = '#F23645'

    label_time = _ms_index_to_time(df_index, event.get('label_idx', 0))

    return {
        'id': label_id,
        'type': 'LineToolNote',
        'state': {
            'symbol': symbol,
            'interval': '1D',
            'frozen': False,
            'visible': True,
            'showLabel': True,
            'text': 'MSB',
            'textcolor': color,
            'fontsize': 12,
            'bold': True,
            'italic': False,
            'backgroundColor': 'rgba(19, 23, 34, 0.85)',
            'backgroundTransparency': 15,
            'bordercolor': color,
            'borderwidth': 1,
            'zOrderVersion': 5,
            'symbolStateVersion': 2,
            'intervalsVisibilities': _MS_INTERVALS_VISIBILITIES,
        },
        'points': [
            {'price': float(event.get('label_price', 0)), 'time_t': label_time, 'offset': 0}
        ],
        'zorder': -1500,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False,
        'isSelectionEnabled': True,
        'metadata': {
            'market_structure_type': 'msb_label',
            'ms_direction': direction,
            'full_reason': f"Market Structure Break ({direction})"
        }
    }


def build_market_structure_box_json(event, symbol, kind, df_index=None):
    """OB / BB / MB rectangle for a single MSB event.

    The Pine script paints these boxes from the source candle to `bar_index
    + 10` and keeps extending the right edge on each new bar — i.e. the box
    spans from the OB candle all the way to (just past) the current bar.
    We mirror that by ending at `last_ts + 10 days`. Invalidated boxes are
    still rendered but faded and flagged so downstream consumers can filter.
    """
    box_id = generate_unique_id()

    box = event.get(kind, {})
    tag = box.get('tag', '')
    direction = event.get('direction', 'bullish')
    invalidated = box.get('invalidated_at') is not None
    is_ob = kind == 'ob'

    # Palette — Bu/Be-OB + Bu/Be-BB in the Pine defaults are both green/red.
    # We dim the BB a touch so it is distinguishable from the main OB.
    if direction == 'bullish':
        base_line = '#089981'
        fill_alpha = 0.28 if is_ob else 0.18
        fill_color = f"rgba(8, 153, 129, {fill_alpha})"
    else:
        base_line = '#F23645'
        fill_alpha = 0.28 if is_ob else 0.18
        fill_color = f"rgba(242, 54, 69, {fill_alpha})"

    # Faded visuals when the OB/BB has been taken out by price
    if invalidated:
        fill_color = fill_color.replace(
            f"{fill_alpha})",
            f"{max(fill_alpha / 3, 0.05):.2f})",
        )

    line_color = base_line
    text_color = '#ffffff'
    text = tag  # e.g. "Bu-OB", "Bu-BB", "Bu-MB", "Be-OB", "Be-BB", "Be-MB"

    start_idx = int(box.get('start_idx', 0))
    start_time = _ms_index_to_time(df_index, start_idx)

    # Extend the right edge all the way to the chart's right side — Pine
    # keeps updating `box.set_right(box, bar_index + 10)` every bar.
    right_ts = _ms_chart_right_edge_ts(df_index, buffer_days=10)
    if right_ts is None:
        right_ts = start_time + 10 * 86400
    # If the box was invalidated, stop it at the break bar rather than
    # letting it run to the present — matches Pine's `delete_boxes=true`.
    if invalidated and df_index is not None:
        inv_bar = int(box.get('invalidated_at', 0))
        right_ts = _ms_index_to_time(df_index, inv_bar)

    return {
        'id': box_id,
        'type': 'LineToolRectangle',
        'state': {
            'symbol': symbol,
            'interval': '1D',
            'frozen': False,
            'visible': True,
            'fillBackground': True,
            'backgroundColor': fill_color,
            'backgroundTransparency': 70 if not invalidated else 85,
            'linecolor': line_color,
            'linewidth': 2 if is_ob and not invalidated else 1,
            'linestyle': 0 if is_ob else 2,
            'extendLeft': False,
            'extendRight': False,
            'showLabel': True,
            'text': text,
            'textcolor': text_color,
            'fontsize': 11,
            'bold': True,
            'italic': False,
            'horzLabelsAlign': 'right',
            'vertLabelsAlign': 'middle',
            'zOrderVersion': 2,
            'symbolStateVersion': 2,
            'intervalsVisibilities': _MS_INTERVALS_VISIBILITIES,
        },
        'points': [
            {'price': float(box.get('high', 0)), 'time_t': start_time, 'offset': 0},
            {'price': float(box.get('low', 0)), 'time_t': right_ts, 'offset': 0},
        ],
        'zorder': -4000 if is_ob else -4200,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False,
        'isSelectionEnabled': True,
        'metadata': {
            'market_structure_type': 'order_block' if is_ob else 'breaker_block',
            'ms_direction': direction,
            'ms_tag': tag,
            'invalidated': invalidated,
            'full_reason': f"{tag} — {direction} Market Structure"
                           + (' (invalidated)' if invalidated else ''),
        }
    }


def build_market_structure_drawings(ms_data, symbol, include_invalidated=False, zigzag=True):
    """Fan out zigzag lines + MSB line/label + OB/BB rectangles for every
    event produced by the MarketStructureIndicator.

    Parameters
    ----------
    ms_data : dict
        Output of `MarketStructureIndicator.get_data()`.
    include_invalidated : bool
        When False (default) we skip OB/BB rectangles that price has already
        broken through — matches Pine's `delete_boxes = true` default.
    zigzag : bool
        When True we also emit the zigzag skeleton as blue TrendLines.
    """
    if not ms_data:
        return []

    events = ms_data.get('events', [])
    df_index = ms_data.get('df_index')
    zigzag_lines = ms_data.get('zigzag_lines', []) if zigzag else []

    drawings = []

    # 1) ZigZag skeleton first (painted under everything else)
    for seg in zigzag_lines:
        try:
            drawings.append(build_market_structure_zigzag_json(seg, symbol, df_index))
        except Exception as e:
            logger.error(f"Error building zigzag segment: {e}")
            continue

    # 2) MSB lines / labels / boxes per event
    for ev in events:
        try:
            drawings.append(build_market_structure_line_json(ev, symbol, df_index))
            drawings.append(build_market_structure_label_json(ev, symbol, df_index))
            for kind in ('ob', 'bb'):
                box = ev.get(kind)
                if not box:
                    continue
                if not include_invalidated and box.get('invalidated_at') is not None:
                    continue
                drawings.append(build_market_structure_box_json(ev, symbol, kind, df_index))
        except Exception as e:
            logger.error(f"Error building market-structure drawing: {e}")
            continue

    logger.info(
        f"Built {len(drawings)} market-structure drawings "
        f"(events={len(events)}, zigzag_segments={len(zigzag_lines)})"
    )
    return drawings


# =====================================================================
#  FVG Order Blocks (BigBeluga Pine port) builders
# =====================================================================
def _fvg_ob_right_edge_ts(df_index, buffer_days=15):
    """Right edge used by FVG order-blocks — Pine extends to `bar_index+15`
    on the last bar, we replicate that by pushing the timestamp 15 days
    past the final data point."""
    if df_index is not None and len(df_index) > 0:
        try:
            return int(df_index[-1].timestamp()) + int(buffer_days) * 86400
        except Exception:
            pass
    return None


def _fvg_ob_bar_to_time(df_index, bar_index, fallback_days=1):
    """Bar index → unix timestamp. Indices beyond the end of df_index are
    projected forward by `fallback_days` per bar (Pine's `bar_index + 5`
    can point into the future)."""
    try:
        bar_index = int(bar_index)
        if df_index is None or len(df_index) == 0:
            return bar_index * 86400 * fallback_days
        n = len(df_index)
        if 0 <= bar_index < n:
            return int(df_index[bar_index].timestamp())
        # Beyond the right edge → project forward from last timestamp
        if bar_index >= n:
            return int(df_index[-1].timestamp()) + (bar_index - (n - 1)) * 86400 * fallback_days
        return int(df_index[0].timestamp()) + bar_index * 86400 * fallback_days
    except Exception:
        return int(int(bar_index) * 86400 * fallback_days)


def build_fvg_gap_box_json(block, symbol, df_index=None):
    """The small grey rectangle marking the raw imbalance area.

    Pine paints this from `bar_index-1` to `bar_index+5` using the chart
    foreground colour at ~70–90% transparency and labels the box with
    the gap %. We mirror that styling but with enough opacity that the
    box is actually visible — TradingView combines `backgroundTransparency`
    with the rgba alpha multiplicatively, so naïve low-alpha colours
    render effectively invisible.
    """
    box_id = generate_unique_id()

    direction = block.get('direction', 'bullish')
    gap_pct = float(block.get('gap_pct', 0.0))

    # Visible grey band (matches Pine's `chart.fg_color` at ~70% transparency).
    # Stronger gap % → slightly darker fill, like Pine's `color.from_gradient`.
    alpha_fill = max(0.22, min(0.55, gap_pct / 4.0))  # 0.22–0.55 range
    fill_color = f'rgba(180, 186, 200, {alpha_fill:.2f})'
    line_color = 'rgba(180, 186, 200, 0.85)'
    text_color = '#e1e4ea'

    left_time = _fvg_ob_bar_to_time(df_index, block.get('gap_left_idx', 0))
    right_time = _fvg_ob_bar_to_time(df_index, block.get('gap_right_idx', 0))

    sign = '' if direction == 'bullish' else '-'
    text = f"{sign}{gap_pct:.2f}%"

    return {
        'id': box_id,
        'type': 'LineToolRectangle',
        'state': {
            'symbol': symbol,
            'interval': '1D',
            'frozen': False,
            'visible': True,
            'fillBackground': True,
            'backgroundColor': fill_color,
            'backgroundTransparency': 35,      # keep most of the rgba alpha
            'linecolor': line_color,
            'linewidth': 1,
            'linestyle': 0,
            'extendLeft': False,
            'extendRight': False,
            'showLabel': True,
            'text': text,
            'textcolor': text_color,
            'fontsize': 10,
            'bold': False,
            'italic': False,
            'horzLabelsAlign': 'center',
            'vertLabelsAlign': 'middle',
            'zOrderVersion': 2,
            'symbolStateVersion': 2,
            'intervalsVisibilities': _MS_INTERVALS_VISIBILITIES,
        },
        'points': [
            {'price': float(block.get('gap_top', 0)), 'time_t': left_time, 'offset': 0},
            {'price': float(block.get('gap_bottom', 0)), 'time_t': right_time, 'offset': 0},
        ],
        'zorder': -4500,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False,
        'isSelectionEnabled': True,
        'metadata': {
            'fvg_ob_type': 'fvg_gap',
            'fvg_type': 'bullish_fvg' if direction == 'bullish' else 'bearish_fvg',
            'fvg_direction': direction,
            'gap_size': abs(float(block.get('gap_top', 0)) - float(block.get('gap_bottom', 0))),
            'gap_percentage': gap_pct,
            'full_reason': f"FVG {direction} gap — {gap_pct:.2f}%",
        }
    }


def build_fvg_order_block_json(block, symbol, df_index=None):
    """The main green/red order-block zone that extends right across the
    chart — the Pine script's primary trade-actionable output."""
    box_id = generate_unique_id()

    direction = block.get('direction', 'bullish')
    gap_pct = float(block.get('gap_pct', 0.0))
    invalidated = block.get('invalidated_at') is not None

    if direction == 'bullish':
        base_line = '#14be94'
        base_alpha = 0.25
        fill_color = f"rgba(20, 190, 148, {base_alpha})"
    else:
        base_line = '#c21919'
        base_alpha = 0.25
        fill_color = f"rgba(194, 25, 25, {base_alpha})"

    if invalidated:
        fill_color = f"rgba(180, 186, 200, 0.10)"
        line_color = 'rgba(180, 186, 200, 0.6)'
    else:
        line_color = base_line

    text_color = '#ffffff'

    left_time = _fvg_ob_bar_to_time(df_index, block.get('gap_left_idx', 0))
    # Right edge: Pine `last_bar_index` that later gets pushed to `bar_index + 15`
    if invalidated and df_index is not None:
        right_time = _fvg_ob_bar_to_time(df_index, int(block.get('invalidated_at', 0)))
    else:
        right_time = _fvg_ob_right_edge_ts(df_index, buffer_days=15)
        if right_time is None:
            right_time = left_time + 15 * 86400

    sign = '' if direction == 'bullish' else '-'
    text = f"{sign}{gap_pct:.2f}%"

    return {
        'id': box_id,
        'type': 'LineToolRectangle',
        'state': {
            'symbol': symbol,
            'interval': '1D',
            'frozen': False,
            'visible': True,
            'fillBackground': True,
            'backgroundColor': fill_color,
            'backgroundTransparency': 70 if not invalidated else 85,
            'linecolor': line_color,
            'linewidth': 1,
            'linestyle': 0,
            'extendLeft': False,
            'extendRight': False,
            'showLabel': True,
            'text': text,
            'textcolor': text_color,
            'fontsize': 11,
            'bold': True,
            'italic': False,
            'horzLabelsAlign': 'right',
            'vertLabelsAlign': 'middle',
            'zOrderVersion': 2,
            'symbolStateVersion': 2,
            'intervalsVisibilities': _MS_INTERVALS_VISIBILITIES,
        },
        'points': [
            {'price': float(block.get('ob_top', 0)), 'time_t': left_time, 'offset': 0},
            {'price': float(block.get('ob_bottom', 0)), 'time_t': right_time, 'offset': 0},
        ],
        'zorder': -4100,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False,
        'isSelectionEnabled': True,
        'metadata': {
            'fvg_ob_type': 'fvg_order_block',
            'fvg_type': 'bullish_fvg' if direction == 'bullish' else 'bearish_fvg',
            'fvg_direction': direction,
            'gap_size': abs(float(block.get('ob_top', 0)) - float(block.get('ob_bottom', 0))),
            'gap_percentage': gap_pct,
            'atr': float(block.get('atr', 0)),
            'invalidated': invalidated,
            'full_reason': (
                f"FVG Order Block ({direction}) — {gap_pct:.2f}% gap, ATR-wide zone"
                + (' (invalidated)' if invalidated else '')
            ),
        }
    }


def build_fvg_ob_drawings(fvg_ob_data, symbol, include_invalidated=False):
    """Fan out gap boxes + order-block zones for every FVG detected by
    the `FVGOrderBlocksIndicator`.

    Respects per-block flags set by the indicator:
      * `render_gap` — emit the small grey gap rectangle (historical record)
      * `render_ob`  — emit the coloured ATR-wide OB zone that extends right

    Pine keeps *every* gap label but only the most-recent `box_amount`
    active OB zones per side; we mirror that via the flags.

    `include_invalidated=True` forces emission of broken OB zones (faded);
    leave False to match Pine's default `show_broken = false`.
    """
    if not fvg_ob_data:
        return []

    bull = fvg_ob_data.get('bull_blocks', [])
    bear = fvg_ob_data.get('bear_blocks', [])
    df_index = fvg_ob_data.get('df_index')

    drawings = []
    gap_count = ob_count = 0
    for block in list(bull) + list(bear):
        try:
            # Gap rectangle — always emitted (marks historical imbalance).
            if block.get('render_gap', True):
                drawings.append(build_fvg_gap_box_json(block, symbol, df_index))
                gap_count += 1

            # OB zone — emitted only if the indicator flagged it active
            # (survives overlap suppression + box_amount cap).
            render_ob = block.get('render_ob', True)
            if not render_ob and include_invalidated:
                # caller explicitly asked for invalidated/suppressed OBs
                render_ob = block.get('invalidated_at') is not None
            if render_ob:
                drawings.append(build_fvg_order_block_json(block, symbol, df_index))
                ob_count += 1
        except Exception as e:
            logger.error(f"Error building FVG-OB drawing: {e}")
            continue

    logger.info(
        f"Built {len(drawings)} FVG-OB drawings "
        f"(gap_labels={gap_count}, active_OBs={ob_count}; "
        f"bull={len(bull)}, bear={len(bear)})"
    )
    return drawings


# =====================================================================
#  Supply / Demand Zones (BigBeluga Pine port) builders
# =====================================================================
# Pine defaults: supply = orange (#FFA500), demand = #009fd4 (cyan-blue).
_SDZ_SUPPLY_LINE = '#FF9800'
_SDZ_SUPPLY_FILL = 'rgba(255, 152, 0, 0.18)'
_SDZ_DEMAND_LINE = '#009FD4'
_SDZ_DEMAND_FILL = 'rgba(0, 159, 212, 0.18)'
_SDZ_INACTIVE_LINE = 'rgba(180, 186, 200, 0.7)'
_SDZ_INACTIVE_FILL = 'rgba(180, 186, 200, 0.10)'


def _sdz_format_volume(v: float) -> str:
    """Pine `format.volume`-style human-readable volume (e.g. 1.2M, 3.4K)."""
    try:
        v = float(v)
    except Exception:
        return str(v)
    sign = '-' if v < 0 else ''
    v = abs(v)
    if v >= 1e9:
        return f"{sign}{v/1e9:.2f}B"
    if v >= 1e6:
        return f"{sign}{v/1e6:.2f}M"
    if v >= 1e3:
        return f"{sign}{v/1e3:.1f}K"
    return f"{sign}{v:.0f}"


def _sdz_bar_to_time(df_index, bar_index, fallback_days=1):
    """Bar index → unix timestamp. Indices beyond df_index project forward
    at one bar / day (Pine boxes extend to `bar_index + 100`)."""
    try:
        bar_index = int(bar_index)
        if df_index is None or len(df_index) == 0:
            return bar_index * 86400 * fallback_days
        n = len(df_index)
        if 0 <= bar_index < n:
            return int(df_index[bar_index].timestamp())
        if bar_index >= n:
            return int(df_index[-1].timestamp()) + (bar_index - (n - 1)) * 86400 * fallback_days
        return int(df_index[0].timestamp()) + bar_index * 86400 * fallback_days
    except Exception:
        return int(int(bar_index) * 86400 * fallback_days)


def _sdz_right_edge_ts(df_index, buffer_days=15):
    """Right edge of an active Supply/Demand box — Pine extends to
    `bar_index + 100` and applies `extend.right`. We push past the last
    bar by `buffer_days` to keep the visual but bounded."""
    if df_index is not None and len(df_index) > 0:
        try:
            return int(df_index[-1].timestamp()) + int(buffer_days) * 86400
        except Exception:
            pass
    return None


def build_supply_demand_zone_json(zone, symbol, df_index=None):
    """Single LineToolRectangle representing one supply or demand zone.

    Pine semantics replicated:
      * Box left edge anchored at the *base* candle (Pine `bar_index - i`).
      * Right edge extends past the last bar (Pine `set_extend(extend.right)`).
      * Label text — Pine: `"Supply: " + delta + " | " + share%`
      * Mitigated boxes get a dashed border (`border_style = dashed`).
      * Invalidated boxes (close beyond the zone) get a faded fill +
        truncated right edge (no point extending a broken zone).
    """
    box_id = generate_unique_id()

    direction = zone.get('direction', 'supply')
    delta = float(zone.get('delta', 0.0))
    share = float(zone.get('share_pct', 0.0))
    invalidated = zone.get('invalidated_at') is not None
    mitigated = zone.get('mitigated_at') is not None

    if direction == 'supply':
        line_color = _SDZ_SUPPLY_LINE
        fill_color = _SDZ_SUPPLY_FILL
        label = f"Supply: {_sdz_format_volume(delta)} | {share:.0f}%"
    else:
        line_color = _SDZ_DEMAND_LINE
        fill_color = _SDZ_DEMAND_FILL
        label = f"Demand: {_sdz_format_volume(delta)} | {share:.0f}%"

    if invalidated:
        line_color = _SDZ_INACTIVE_LINE
        fill_color = _SDZ_INACTIVE_FILL

    # Mitigation -> dashed border. Pine: `border_style = line.style_dashed`.
    linestyle = 2 if mitigated and not invalidated else 0
    linewidth = 1 if mitigated else 2

    left_time = _sdz_bar_to_time(df_index, zone.get('base_idx', zone.get('bar_index', 0)))
    if invalidated:
        right_time = _sdz_bar_to_time(df_index, int(zone.get('invalidated_at', 0)))
    else:
        right_time = _sdz_right_edge_ts(df_index, buffer_days=15)
        if right_time is None:
            right_time = left_time + 100 * 86400

    return {
        'id': box_id,
        'type': 'LineToolRectangle',
        'state': {
            'symbol': symbol,
            'interval': '1D',
            'frozen': False,
            'visible': True,
            'fillBackground': True,
            'backgroundColor': fill_color,
            'backgroundTransparency': 75 if not invalidated else 88,
            'linecolor': line_color,
            'linewidth': linewidth,
            'linestyle': linestyle,
            'extendLeft': False,
            'extendRight': not invalidated,
            'showLabel': True,
            'text': label,
            'textcolor': '#FFFFFF',
            'fontsize': 11,
            'bold': True,
            'italic': False,
            'horzLabelsAlign': 'right',
            'vertLabelsAlign': 'middle',
            'zOrderVersion': 2,
            'symbolStateVersion': 2,
            'intervalsVisibilities': _MS_INTERVALS_VISIBILITIES,
        },
        'points': [
            {'price': float(zone.get('top', 0)), 'time_t': left_time, 'offset': 0},
            {'price': float(zone.get('bottom', 0)), 'time_t': right_time, 'offset': 0},
        ],
        'zorder': -4400,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False,
        'isSelectionEnabled': True,
        'metadata': {
            'sdz_type': 'supply_zone' if direction == 'supply' else 'demand_zone',
            'sdz_direction': direction,
            'sdz_delta': delta,
            'sdz_share_pct': share,
            'sdz_atr': float(zone.get('atr', 0)),
            'mitigated': mitigated,
            'invalidated': invalidated,
            # Mark this drawing as belonging to the BigBeluga supply/demand
            # zones bucket so the chat-agent filter can route on it. We also
            # set the legacy `base_candles` key so the existing
            # `supply_demand_zones` filter (which keys on `base_candles`)
            # picks the drawing up without further changes.
            'base_candles': 1,
            'full_reason': (
                f"{direction.title()} zone — Δ {_sdz_format_volume(delta)}, "
                f"{share:.0f}% of total volume"
                + (' (mitigated)' if mitigated and not invalidated else '')
                + (' (invalidated)' if invalidated else '')
            ),
        }
    }


def build_supply_demand_zones_drawings(sdz_data, symbol, include_invalidated=False):
    """Fan out one rectangle per supply/demand zone produced by
    `SupplyDemandZonesIndicator`.

    Respects the `render` flag set by the indicator's overlap-suppression
    and per-side cap. Invalidated zones are rendered as faded boxes when
    `include_invalidated=True`; otherwise they are skipped entirely
    (matches Pine's `b.delete()` on close-beyond).
    """
    if not sdz_data:
        return []

    supply = sdz_data.get('supply_zones', [])
    demand = sdz_data.get('demand_zones', [])
    df_index = sdz_data.get('df_index')

    drawings = []
    rendered_supply = rendered_demand = 0
    for zone in list(supply) + list(demand):
        try:
            if not zone.get('render', True):
                continue
            if zone.get('invalidated_at') is not None and not include_invalidated:
                continue
            drawings.append(build_supply_demand_zone_json(zone, symbol, df_index))
            if zone.get('direction') == 'supply':
                rendered_supply += 1
            else:
                rendered_demand += 1
        except Exception as e:
            logger.error(f"Error building Supply/Demand Zone drawing: {e}")
            continue

    logger.info(
        f"Built {len(drawings)} Supply/Demand Zone drawings "
        f"(supply={rendered_supply}, demand={rendered_demand}; "
        f"raw supply={len(supply)}, raw demand={len(demand)})"
    )
    return drawings


# =====================================================================
#  Price-Action / Smart Money Concepts (BigBeluga) builders
# =====================================================================
_PA_UP_COLOR = '#089981'
_PA_DN_COLOR = '#F23645'


def _pa_bar_to_time(df_index, bar_index):
    """Bar index → unix timestamp using the provided DatetimeIndex.

    `bar_index` may point beyond the end of df_index (right-extending
    boxes), in which case we project forward at 1 bar / day.
    """
    try:
        bar_index = int(bar_index)
    except Exception:
        return 0
    if df_index is None or len(df_index) == 0:
        return bar_index * 86400
    n = len(df_index)
    if 0 <= bar_index < n:
        return int(df_index[bar_index].timestamp())
    if bar_index >= n:
        return int(df_index[-1].timestamp()) + (bar_index - (n - 1)) * 86400
    return int(df_index[0].timestamp())


def _pa_chart_right_edge_ts(df_index, buffer_days=10):
    if df_index is None or len(df_index) == 0:
        return None
    try:
        return int(df_index[-1].timestamp()) + int(buffer_days) * 86400
    except Exception:
        return None


def _format_volume(v: float) -> str:
    """Human-readable volume — matches Pine's `format.volume` output style
    (e.g. 1.2M, 3.4K, 125).
    """
    try:
        v = float(v)
    except Exception:
        return str(v)
    if v >= 1e9:
        return f"{v/1e9:.2f}B"
    if v >= 1e6:
        return f"{v/1e6:.2f}M"
    if v >= 1e3:
        return f"{v/1e3:.1f}K"
    return f"{v:.0f}"


def build_pa_structure_line_json(event, symbol, df_index=None):
    """Horizontal LineToolTrendLine from the origin pivot to the break bar
    at the broken price level — represents the Pine `drawms` line with an
    inline label ("BOS" / "CHoCH" / "x" for sweeps).

    The text is painted on the trendline itself via `showLabel=True` so we
    don't have to emit a separate LineToolNote for every event — that was
    causing TradingView to render a giant location-pin per event and
    flooding the chart.
    """
    line_id = generate_unique_id()

    direction = event.get('direction', 'bullish')
    etype = event.get('type', 'BOS')
    color = _PA_UP_COLOR if direction == 'bullish' else _PA_DN_COLOR

    # Solid for confirmed BOS, dashed for CHoCH, dotted for sweeps
    # (matches Pine's line.style_solid / line.style_dashed / line.style_dotted).
    style_map = {'BOS': 0, 'CHoCH': 2, 'sweep': 3}
    linestyle = style_map.get(etype, 0)

    # Pine labels sweeps with 'x'; everything else keeps its event name.
    label_text = 'x' if etype == 'sweep' else etype

    start_time = _pa_bar_to_time(df_index, event.get('origin_bar', 0))
    end_time = _pa_bar_to_time(df_index, event.get('bar_index', 0))
    price = float(event.get('price', 0))

    return {
        'id': line_id,
        'type': 'LineToolTrendLine',
        'state': {
            'symbol': symbol, 'interval': '1D',
            'frozen': False, 'visible': True,
            'linecolor': color,
            'linewidth': 2 if etype == 'BOS' else 1,
            'linestyle': linestyle,
            'extendLeft': False, 'extendRight': False,
            'showLabel': True,
            'text': label_text,
            'textcolor': color,
            'fontsize': 9,
            'bold': etype == 'BOS',
            'italic': False,
            'horzLabelsAlign': 'center',
            'vertLabelsAlign': 'top' if direction == 'bullish' else 'bottom',
            'zOrderVersion': 4, 'symbolStateVersion': 2,
            'intervalsVisibilities': _MS_INTERVALS_VISIBILITIES,
        },
        'points': [
            {'price': price, 'time_t': start_time, 'offset': 0},
            {'price': price, 'time_t': end_time, 'offset': 0},
        ],
        'zorder': -2200,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False, 'isSelectionEnabled': True,
        'metadata': {
            'price_action_type': 'structure_line',
            'pa_event_type': etype,
            'pa_direction': direction,
            'full_reason': f"{etype} ({direction}) at {price:.2f}"
        }
    }


def build_pa_structure_label_json(event, symbol, df_index=None):
    """Text label at the break bar: 'BOS', 'CHoCH', or 'x' (sweep)."""
    label_id = generate_unique_id()

    direction = event.get('direction', 'bullish')
    etype = event.get('type', 'BOS')
    color = _PA_UP_COLOR if direction == 'bullish' else _PA_DN_COLOR

    # Pine shows 'x' for sweeps, otherwise the event type.
    text = 'x' if etype == 'sweep' else etype
    origin_bar = int(event.get('origin_bar', 0))
    break_bar = int(event.get('bar_index', 0))
    label_bar = (origin_bar + break_bar) // 2
    label_time = _pa_bar_to_time(df_index, label_bar)

    return {
        'id': label_id,
        'type': 'LineToolNote',
        'state': {
            'symbol': symbol, 'interval': '1D',
            'frozen': False, 'visible': True,
            'showLabel': True,
            'text': text,
            'textcolor': color,
            'fontsize': 11, 'bold': True, 'italic': False,
            'backgroundColor': 'rgba(19, 23, 34, 0.85)',
            'backgroundTransparency': 15,
            'bordercolor': color, 'borderwidth': 1,
            'zOrderVersion': 5, 'symbolStateVersion': 2,
            'intervalsVisibilities': _MS_INTERVALS_VISIBILITIES,
        },
        'points': [
            {'price': float(event.get('price', 0)), 'time_t': label_time, 'offset': 0}
        ],
        'zorder': -1500,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False, 'isSelectionEnabled': True,
        'metadata': {
            'price_action_type': 'structure_label',
            'pa_event_type': etype,
            'pa_direction': direction,
            'full_reason': f"{etype} label ({direction})"
        }
    }


def build_pa_order_block_json(ob, symbol, df_index=None):
    """The main order-block rectangle — spans from the pivot bar to either
    the chart's right edge (if still active) or the invalidation bar.
    Colour encodes direction; opacity is faded when `render_active=False`
    or when the OB has been mitigated."""
    box_id = generate_unique_id()

    direction = ob.get('direction', 'bullish')
    invalidated = ob.get('invalidated_at') is not None
    active = ob.get('render_active', True) and not invalidated

    if direction == 'bullish':
        base_rgb = '8, 153, 129'
        line_color = _PA_UP_COLOR
    else:
        base_rgb = '242, 54, 69'
        line_color = _PA_DN_COLOR

    fill_alpha = 0.22 if active else 0.08
    fill_color = f'rgba({base_rgb}, {fill_alpha:.2f})'

    left_time = _pa_bar_to_time(df_index, ob.get('bar_index', 0))
    if invalidated:
        right_time = _pa_bar_to_time(df_index, int(ob.get('invalidated_at', 0)))
    else:
        right_time = _pa_chart_right_edge_ts(df_index, buffer_days=10) or (left_time + 10 * 86400)

    volume_text = _format_volume(ob.get('volume', 0))
    # Pine displays "X.XM (Y%)" — volume share of the OB's side.
    share = ob.get('volume_share_pct')
    if share is not None:
        label_text = f"{volume_text} ({int(share)}%)"
    else:
        label_text = volume_text

    return {
        'id': box_id,
        'type': 'LineToolRectangle',
        'state': {
            'symbol': symbol, 'interval': '1D',
            'frozen': False, 'visible': True,
            'fillBackground': True,
            'backgroundColor': fill_color,
            'backgroundTransparency': 75 if active else 90,
            'linecolor': line_color,
            'linewidth': 1,
            'linestyle': 0,
            'extendLeft': False, 'extendRight': False,
            'showLabel': True,
            'text': label_text,
            'textcolor': '#ffffff',
            'fontsize': 10, 'bold': True, 'italic': False,
            'horzLabelsAlign': 'right',
            'vertLabelsAlign': 'middle',
            'zOrderVersion': 2, 'symbolStateVersion': 2,
            'intervalsVisibilities': _MS_INTERVALS_VISIBILITIES,
        },
        'points': [
            {'price': float(ob.get('top', 0)), 'time_t': left_time, 'offset': 0},
            {'price': float(ob.get('bottom', 0)), 'time_t': right_time, 'offset': 0},
        ],
        'zorder': -4300,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False, 'isSelectionEnabled': True,
        'metadata': {
            'price_action_type': 'volumetric_ob',
            'pa_direction': direction,
            'pa_event_type': ob.get('event_type', ''),
            'ob_volume': ob.get('volume', 0),
            'ob_volume_share_pct': share,
            'invalidated': invalidated,
            'full_reason': (
                f"{direction} OB at {ob.get('event_type', '')} — vol {label_text}"
                + (' (mitigated)' if invalidated else '')
            ),
        }
    }


def build_pa_ob_midline_json(ob, symbol, df_index=None):
    """Dashed horizontal mid-line through each active OB (Pine `showline`)."""
    line_id = generate_unique_id()

    direction = ob.get('direction', 'bullish')
    invalidated = ob.get('invalidated_at') is not None
    color = _PA_UP_COLOR if direction == 'bullish' else _PA_DN_COLOR

    left_time = _pa_bar_to_time(df_index, ob.get('bar_index', 0))
    if invalidated:
        right_time = _pa_bar_to_time(df_index, int(ob.get('invalidated_at', 0)))
    else:
        right_time = _pa_chart_right_edge_ts(df_index, buffer_days=10) or (left_time + 10 * 86400)

    avg = float(ob.get('avg', 0))

    return {
        'id': line_id,
        'type': 'LineToolTrendLine',
        'state': {
            'symbol': symbol, 'interval': '1D',
            'frozen': False, 'visible': True,
            'linecolor': color,
            'linewidth': 1,
            'linestyle': 2,   # dashed
            'extendLeft': False, 'extendRight': False,
            'showLabel': False,
            'text': '', 'textcolor': color,
            'fontsize': 9, 'bold': False, 'italic': False,
            'zOrderVersion': 4, 'symbolStateVersion': 2,
            'intervalsVisibilities': _MS_INTERVALS_VISIBILITIES,
        },
        'points': [
            {'price': avg, 'time_t': left_time, 'offset': 0},
            {'price': avg, 'time_t': right_time, 'offset': 0},
        ],
        'zorder': -3800,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False, 'isSelectionEnabled': True,
        'metadata': {
            'price_action_type': 'ob_midline',
            'pa_direction': direction,
            'full_reason': f"{direction} OB mid-line @ {avg:.2f}",
        }
    }


def build_pa_drawings(pa_data, symbol, include_invalidated=False, swing_limit=30):
    """Fan out every price-action / SMC drawing from the indicator payload.

    Parameters
    ----------
    pa_data : dict
        Output of `PriceActionSMCIndicator.get_data()`.
    include_invalidated : bool
        When True, render faded versions of broken OBs (historical context).
    swing_limit : int
        Render at most the last `swing_limit` structure events — matches
        Pine's `swingLimit` (default 100) but defaulting lower here to
        keep the chart readable on narrow windows. Set to 0 for all.
    """
    if not pa_data:
        return []

    events = pa_data.get('events', [])
    obs = pa_data.get('order_blocks', [])
    df_index = pa_data.get('df_index')

    # Compute per-side volume share for active OBs (Pine shows "X.XM (Y%)"
    # where Y is the OB's share of the total active-OB volume on its side).
    active_bulls = [
        ob for ob in obs
        if ob.get('direction') == 'bullish'
        and ob.get('invalidated_at') is None
        and ob.get('render_active', True)
    ]
    active_bears = [
        ob for ob in obs
        if ob.get('direction') == 'bearish'
        and ob.get('invalidated_at') is None
        and ob.get('render_active', True)
    ]
    for side_list in (active_bulls, active_bears):
        total_vol = sum(float(o.get('volume', 0)) for o in side_list)
        for o in side_list:
            if total_vol > 0:
                o['volume_share_pct'] = round(float(o.get('volume', 0)) / total_vol * 100.0)
            else:
                o['volume_share_pct'] = 0

    drawings = []
    event_counts = {}

    # Cap events to the most recent `swing_limit`. Events are already in
    # chronological order in the indicator, so slicing from the tail keeps
    # the freshest structure visible — closer to what Pine renders.
    if swing_limit and len(events) > swing_limit:
        rendered_events = events[-swing_limit:]
    else:
        rendered_events = events

    # 1) Structure lines — label text is baked into the trendline so we
    #    no longer emit a separate LineToolNote per event (those were
    #    rendering as giant location pins and flooding the chart).
    for ev in rendered_events:
        try:
            drawings.append(build_pa_structure_line_json(ev, symbol, df_index))
            k = f"{ev.get('type')} {ev.get('direction')}"
            event_counts[k] = event_counts.get(k, 0) + 1
        except Exception as e:
            logger.error(f"Error building price-action structure drawing: {e}")

    # 2) Volumetric order blocks (+ midlines). Skip silent/invalidated unless
    #    the caller explicitly wants them.
    active_obs = 0
    for ob in obs:
        try:
            if not include_invalidated and ob.get('invalidated_at') is not None:
                continue
            if not include_invalidated and not ob.get('render_active', True):
                continue
            drawings.append(build_pa_order_block_json(ob, symbol, df_index))
            drawings.append(build_pa_ob_midline_json(ob, symbol, df_index))
            active_obs += 1
        except Exception as e:
            logger.error(f"Error building price-action OB drawing: {e}")

    logger.info(
        f"Built {len(drawings)} price-action SMC drawings "
        f"(events rendered={len(rendered_events)}/{len(events)}, "
        f"active_OBs={active_obs}, event_breakdown={event_counts})"
    )
    return drawings


# =====================================================================
#  Order Block Finder (wugamlo) builders
# =====================================================================
_OB_FINDER_UP = '#089981'
_OB_FINDER_DN = '#F23645'


def build_ob_finder_rect_json(ob, symbol, df_index=None):
    """Rectangle for a wugamlo Order Block. Pine draws extending-left
    channels only for the LATEST bull/bear OB — we render every tracked
    OB as a right-extending rectangle so the user sees the historical
    institutional levels the way the existing OB products (MSB, SMC,
    FVG-OB) present theirs.
    """
    box_id = generate_unique_id()
    direction = ob.get('direction', 'bullish')
    invalidated = ob.get('invalidated_at') is not None

    if direction == 'bullish':
        base_rgb = '8, 153, 129'
        line_color = _OB_FINDER_UP
    else:
        base_rgb = '242, 54, 69'
        line_color = _OB_FINDER_DN

    # Active OB → vivid fill; broken → faded grey-ish
    if not invalidated:
        fill_alpha = 0.25
        fill_color = f'rgba({base_rgb}, {fill_alpha:.2f})'
    else:
        fill_alpha = 0.10
        fill_color = f'rgba({base_rgb}, {fill_alpha:.2f})'

    left_time = _pa_bar_to_time(df_index, ob.get('bar_index', 0))
    if invalidated:
        right_time = _pa_bar_to_time(df_index, int(ob.get('invalidated_at', 0)))
    else:
        right_time = _pa_chart_right_edge_ts(df_index, buffer_days=10) or (left_time + 10 * 86400)

    move_pct = float(ob.get('move_pct', 0.0))
    # Matches Pine's "Bullish OB"/"Bearish OB" label style; include move %
    # so the user sees how strong the triggering sequence was.
    text = f"{'Bull' if direction == 'bullish' else 'Bear'} OB · {move_pct:.1f}%"

    return {
        'id': box_id,
        'type': 'LineToolRectangle',
        'state': {
            'symbol': symbol, 'interval': '1D',
            'frozen': False, 'visible': True,
            'fillBackground': True,
            'backgroundColor': fill_color,
            'backgroundTransparency': 75 if not invalidated else 88,
            'linecolor': line_color,
            'linewidth': 1,
            'linestyle': 0 if not invalidated else 2,
            'extendLeft': False, 'extendRight': False,
            'showLabel': True,
            'text': text,
            'textcolor': '#ffffff',
            'fontsize': 10, 'bold': True, 'italic': False,
            'horzLabelsAlign': 'right',
            'vertLabelsAlign': 'middle',
            'zOrderVersion': 2, 'symbolStateVersion': 2,
            'intervalsVisibilities': _MS_INTERVALS_VISIBILITIES,
        },
        'points': [
            {'price': float(ob.get('high', 0)), 'time_t': left_time, 'offset': 0},
            {'price': float(ob.get('low', 0)), 'time_t': right_time, 'offset': 0},
        ],
        'zorder': -4200,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False, 'isSelectionEnabled': True,
        'metadata': {
            'ob_finder_type': 'order_block',
            'ob_direction': direction,
            'move_pct': move_pct,
            'volume': float(ob.get('volume', 0)),
            'invalidated': invalidated,
            'full_reason': (
                f"{direction.title()} Order Block — {move_pct:.1f}% move"
                + (' (mitigated)' if invalidated else '')
            )
        }
    }


def build_ob_finder_avg_line_json(ob, symbol, df_index=None):
    """Dashed mid-line through each OB at its `avg` — Pine's solid
    equilibrium line (we use dashed to stay consistent with the other
    OB products' mid-lines in this codebase).
    """
    line_id = generate_unique_id()
    direction = ob.get('direction', 'bullish')
    invalidated = ob.get('invalidated_at') is not None
    color = _OB_FINDER_UP if direction == 'bullish' else _OB_FINDER_DN

    left_time = _pa_bar_to_time(df_index, ob.get('bar_index', 0))
    if invalidated:
        right_time = _pa_bar_to_time(df_index, int(ob.get('invalidated_at', 0)))
    else:
        right_time = _pa_chart_right_edge_ts(df_index, buffer_days=10) or (left_time + 10 * 86400)

    avg = float(ob.get('avg', 0))

    return {
        'id': line_id,
        'type': 'LineToolTrendLine',
        'state': {
            'symbol': symbol, 'interval': '1D',
            'frozen': False, 'visible': True,
            'linecolor': color,
            'linewidth': 1,
            'linestyle': 2,   # dashed
            'extendLeft': False, 'extendRight': False,
            'showLabel': False,
            'text': '', 'textcolor': color,
            'fontsize': 9, 'bold': False, 'italic': False,
            'zOrderVersion': 4, 'symbolStateVersion': 2,
            'intervalsVisibilities': _MS_INTERVALS_VISIBILITIES,
        },
        'points': [
            {'price': avg, 'time_t': left_time, 'offset': 0},
            {'price': avg, 'time_t': right_time, 'offset': 0},
        ],
        'zorder': -3700,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False, 'isSelectionEnabled': True,
        'metadata': {
            'ob_finder_type': 'ob_avg_line',
            'ob_direction': direction,
            'full_reason': f"{direction} OB mid-line @ {avg:.2f}"
        }
    }


def build_ob_finder_drawings(ob_data, symbol, include_invalidated=True):
    """Fan out OB rectangle + mid-line for every detected order block.

    Parameters
    ----------
    ob_data : dict
        Output of `OrderBlockFinderIndicator.get_data()`.
    include_invalidated : bool
        Pine paints mitigated OBs too (just doesn't hide them). Default
        True matches that behaviour; set False to drop broken OBs.
    """
    if not ob_data:
        return []

    bulls = ob_data.get('bull_obs', [])
    bears = ob_data.get('bear_obs', [])
    df_index = ob_data.get('df_index')

    drawings = []
    rendered = 0
    faded = 0
    for ob in list(bulls) + list(bears):
        if not ob.get('render_active', True):
            continue
        if not include_invalidated and ob.get('invalidated_at') is not None:
            continue
        try:
            drawings.append(build_ob_finder_rect_json(ob, symbol, df_index))
            drawings.append(build_ob_finder_avg_line_json(ob, symbol, df_index))
            rendered += 1
            if ob.get('invalidated_at') is not None:
                faded += 1
        except Exception as e:
            logger.error(f"Error building OB-finder drawing: {e}")
            continue

    logger.info(
        f"Built {len(drawings)} OB-finder drawings "
        f"(bull={len(bulls)}, bear={len(bears)}, "
        f"rendered={rendered}, faded={faded})"
    )
    return drawings


# =====================================================================
#  Liquidity Swings (LuxAlgo) builders
# =====================================================================
_LIQ_HIGH_COLOR = '#F23645'   # matches Pine `color.red` default for swing-high liquidity
_LIQ_LOW_COLOR  = '#089981'   # matches Pine `color.teal` default for swing-low liquidity


def build_liquidity_level_line_json(zone, symbol, df_index=None):
    """Horizontal level line at the pivot price. Solid until the level
    has been swept (Pine's `crossed` flag), dashed after. The label text
    on the line is the accumulated volume formatted like Pine's
    `format.volume` (e.g. 1.2M / 345K). Equal-H/L clusters (stacked stop
    orders — high-conviction liquidity) are prefixed with EQH / EQL and
    drawn bolder.
    """
    line_id = generate_unique_id()

    is_high = zone.get('direction') == 'high'
    swept = zone.get('crossed_at') is not None
    is_cluster = bool(zone.get('is_cluster', False))
    color = _LIQ_HIGH_COLOR if is_high else _LIQ_LOW_COLOR

    start_time = _pa_bar_to_time(df_index, zone.get('pivot_bar', 0))
    if swept:
        end_time = _pa_bar_to_time(df_index, int(zone.get('crossed_at', 0)))
    else:
        end_time = _pa_chart_right_edge_ts(df_index, buffer_days=10) or (start_time + 10 * 86400)

    price = float(zone.get('pivot_price', 0))
    volume_text = _format_volume(zone.get('volume', 0))
    # Pine's fix #4 annotation — mark cluster levels so the user can spot
    # stacked-stop liquidity at a glance.
    if is_cluster:
        label_prefix = 'EQH · ' if is_high else 'EQL · '
        label_text = f"{label_prefix}{volume_text}"
    else:
        label_text = volume_text

    return {
        'id': line_id,
        'type': 'LineToolTrendLine',
        'state': {
            'symbol': symbol, 'interval': '1D',
            'frozen': False, 'visible': True,
            'linecolor': color,
            # Thicker + bold for clusters (high-conviction liquidity)
            'linewidth': 3 if is_cluster else 2,
            'linestyle': 2 if swept else 0,   # dashed after sweep
            'extendLeft': False, 'extendRight': False,
            'showLabel': True,
            'text': label_text,
            'textcolor': color,
            'fontsize': 11 if is_cluster else 10,
            'bold': is_cluster,
            'italic': False,
            'horzLabelsAlign': 'right',
            'vertLabelsAlign': 'top' if is_high else 'bottom',
            'zOrderVersion': 4, 'symbolStateVersion': 2,
            'intervalsVisibilities': _MS_INTERVALS_VISIBILITIES,
        },
        'points': [
            {'price': price, 'time_t': start_time, 'offset': 0},
            {'price': price, 'time_t': end_time, 'offset': 0},
        ],
        'zorder': -2100,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False, 'isSelectionEnabled': True,
        'metadata': {
            'liquidity_type': 'level_line',
            'liq_direction': zone.get('direction'),
            'pivot_price': price,
            'touch_count': zone.get('count', 0),
            'accumulated_volume': zone.get('volume', 0),
            'swept': swept,
            'is_cluster': is_cluster,
            'full_reason': (
                f"Liquidity {'high' if is_high else 'low'} @ {price:.2f} — "
                f"{zone.get('count', 0)} touches, vol {volume_text}"
                + (' [EQH cluster]' if is_cluster and is_high else '')
                + (' [EQL cluster]' if is_cluster and not is_high else '')
                + (' (swept)' if swept else ' (live)')
            )
        }
    }


def build_liquidity_zone_box_json(zone, symbol, df_index=None):
    """The wick-to-body (or full-range) rectangle right at the pivot
    candle — where liquidity physically rests. Pine paints it with
    the swing colour at ~80% transparency; equal-H/L clusters get a
    stronger fill and a visible border (Pine's fix #5).

    The right edge extends as price keeps interacting with the level,
    stopping at the sweep bar once crossed.
    """
    box_id = generate_unique_id()

    is_high = zone.get('direction') == 'high'
    swept = zone.get('crossed_at') is not None
    is_cluster = bool(zone.get('is_cluster', False))

    if is_high:
        base_rgb = '242, 54, 69'
        line_color = _LIQ_HIGH_COLOR
    else:
        base_rgb = '8, 153, 129'
        line_color = _LIQ_LOW_COLOR

    # Fix #5: cluster zones get a visibly stronger fill (equal highs/lows
    # indicate stacked stop orders → higher-conviction liquidity).
    if is_cluster:
        fill_alpha = 0.38 if not swept else 0.16
    else:
        fill_alpha = 0.18 if not swept else 0.08
    fill_color = f'rgba({base_rgb}, {fill_alpha:.2f})'

    left_time = _pa_bar_to_time(df_index, zone.get('pivot_bar', 0))
    if swept:
        right_time = _pa_bar_to_time(df_index, int(zone.get('crossed_at', 0)))
    else:
        right_time = _pa_chart_right_edge_ts(df_index, buffer_days=10) or (left_time + 10 * 86400)

    top = float(zone.get('zone_top', 0))
    btm = float(zone.get('zone_bottom', 0))

    return {
        'id': box_id,
        'type': 'LineToolRectangle',
        'state': {
            'symbol': symbol, 'interval': '1D',
            'frozen': False, 'visible': True,
            'fillBackground': True,
            'backgroundColor': fill_color,
            'backgroundTransparency': (60 if is_cluster else 80) if not swept else 90,
            'linecolor': line_color,
            # Bordered rectangle for clusters — visually distinguishes
            # stacked-stop zones from single-tap liquidity.
            'linewidth': 2 if (is_cluster and not swept) else 0,
            'linestyle': 0,
            'extendLeft': False, 'extendRight': False,
            'showLabel': False,
            'text': '',
            'textcolor': '#ffffff',
            'fontsize': 9, 'bold': False, 'italic': False,
            'zOrderVersion': 2, 'symbolStateVersion': 2,
            'intervalsVisibilities': _MS_INTERVALS_VISIBILITIES,
        },
        'points': [
            {'price': top, 'time_t': left_time, 'offset': 0},
            {'price': btm, 'time_t': right_time, 'offset': 0},
        ],
        'zorder': -4600,
        'linkKey': generate_unique_id() + generate_unique_id(),
        'ownerSource': '_seriesId',
        'userEditEnabled': False, 'isSelectionEnabled': True,
        'metadata': {
            'liquidity_type': 'zone_box',
            'liq_direction': zone.get('direction'),
            'swept': swept,
            'is_cluster': is_cluster,
            'touch_count': zone.get('count', 0),
            'accumulated_volume': zone.get('volume', 0),
            'full_reason': (
                f"Liquidity zone ({'high' if is_high else 'low'}) "
                f"{btm:.2f}–{top:.2f}"
                + (' [cluster]' if is_cluster else '')
                + (' (swept)' if swept else '')
            )
        }
    }


def build_liquidity_swings_drawings(liquidity_data, symbol,
                                    include_unswept_only=False,
                                    include_below_filter=False):
    """Fan out level lines + zone boxes for every liquidity swing.

    Parameters
    ----------
    liquidity_data : dict
        Output of `LiquiditySwingsIndicator.get_data()`.
    include_unswept_only : bool
        When True, skip zones that price has already closed through.
    include_below_filter : bool
        When False (default) skip zones whose count/volume failed the
        filter threshold (Pine's `filterValue` gate).
    """
    if not liquidity_data:
        return []

    highs = liquidity_data.get('high_zones', [])
    lows = liquidity_data.get('low_zones', [])
    df_index = liquidity_data.get('df_index')

    drawings = []
    rendered = 0
    for zone in list(highs) + list(lows):
        if not zone.get('render_active', True):
            continue
        if include_unswept_only and zone.get('crossed_at') is not None:
            continue
        if not include_below_filter and not zone.get('passed_filter', True):
            continue
        try:
            drawings.append(build_liquidity_level_line_json(zone, symbol, df_index))
            drawings.append(build_liquidity_zone_box_json(zone, symbol, df_index))
            rendered += 1
        except Exception as e:
            logger.error(f"Error building liquidity-swings drawing: {e}")
            continue

    logger.info(
        f"Built {len(drawings)} liquidity-swings drawings "
        f"(highs={len(highs)}, lows={len(lows)}, rendered={rendered})"
    )
    return drawings