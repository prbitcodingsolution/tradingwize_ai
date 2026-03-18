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