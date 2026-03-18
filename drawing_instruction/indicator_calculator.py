"""
Technical Indicator Calculator
Calculates various technical indicators (Bollinger Bands, RSI, MACD, etc.)
"""

import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


def calculate_bollinger_bands(df, period=20, std_dev=2):
    """
    Calculate Bollinger Bands
    
    Args:
        df (pd.DataFrame): OHLCV data
        period (int): Moving average period
        std_dev (float): Standard deviation multiplier
    
    Returns:
        dict: Bollinger Bands data
    """
    try:
        if df is None or len(df) < period:
            return None
        
        # Calculate middle band (SMA)
        df['BB_Middle'] = df['Close'].rolling(window=period).mean()
        
        # Calculate standard deviation
        df['BB_Std'] = df['Close'].rolling(window=period).std()
        
        # Calculate upper and lower bands
        df['BB_Upper'] = df['BB_Middle'] + (df['BB_Std'] * std_dev)
        df['BB_Lower'] = df['BB_Middle'] - (df['BB_Std'] * std_dev)
        
        # Prepare data points for JSON
        bands_data = {
            'period': period,
            'std_dev': std_dev,
            'upper': [],
            'middle': [],
            'lower': []
        }
        
        for idx, row in df.iterrows():
            if pd.notna(row['BB_Upper']):
                timestamp = int(idx.timestamp())
                
                bands_data['upper'].append({
                    'time': timestamp,
                    'price': float(row['BB_Upper'])
                })
                bands_data['middle'].append({
                    'time': timestamp,
                    'price': float(row['BB_Middle'])
                })
                bands_data['lower'].append({
                    'time': timestamp,
                    'price': float(row['BB_Lower'])
                })
        
        # Add squeeze detection
        bands_data['squeezes'] = detect_bb_squeeze(df)
        
        logger.info(f"Calculated Bollinger Bands with {len(bands_data['upper'])} points")
        return bands_data
    
    except Exception as e:
        logger.error(f"Error calculating Bollinger Bands: {e}")
        return None


def detect_bb_squeeze(df, threshold=0.02):
    """Detect Bollinger Band squeeze (low volatility)"""
    squeezes = []
    
    try:
        if 'BB_Upper' not in df.columns or 'BB_Lower' not in df.columns:
            return squeezes
        
        # Calculate band width
        df['BB_Width'] = (df['BB_Upper'] - df['BB_Lower']) / df['BB_Middle']
        
        # Find squeezes (narrow bands)
        for i in range(20, len(df)):
            current_width = df['BB_Width'].iloc[i]
            avg_width = df['BB_Width'].iloc[i-20:i].mean()
            
            if current_width < avg_width * 0.5:  # 50% narrower than average
                squeezes.append({
                    'index': i,
                    'timestamp': int(df.index[i].timestamp()),
                    'price': float(df['Close'].iloc[i]),
                    'width': float(current_width),
                    'reason': 'Bollinger Band Squeeze: Low volatility period. '
                             'Bands are narrowing, indicating potential breakout soon. '
                             'Watch for expansion and directional move.'
                })
        
        return squeezes
    
    except Exception as e:
        logger.error(f"Error detecting BB squeeze: {e}")
        return []


def calculate_rsi(df, period=14):
    """
    Calculate Relative Strength Index (RSI)
    
    Args:
        df (pd.DataFrame): OHLCV data
        period (int): RSI period
    
    Returns:
        dict: RSI data with overbought/oversold levels
    """
    try:
        if df is None or len(df) < period:
            return None
        
        # Calculate price changes
        delta = df['Close'].diff()
        
        # Separate gains and losses
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        # Calculate average gain and loss
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        
        # Calculate RS and RSI
        rs = avg_gain / avg_loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # Prepare data
        rsi_data = {
            'period': period,
            'values': [],
            'overbought': [],
            'oversold': []
        }
        
        for idx, row in df.iterrows():
            if pd.notna(row['RSI']):
                timestamp = int(idx.timestamp())
                rsi_value = float(row['RSI'])
                
                rsi_data['values'].append({
                    'time': timestamp,
                    'value': rsi_value
                })
                
                # Mark overbought (>70)
                if rsi_value > 70:
                    rsi_data['overbought'].append({
                        'timestamp': timestamp,
                        'price': float(row['Close']),
                        'rsi': rsi_value,
                        'reason': f'RSI Overbought: RSI at {rsi_value:.1f} (>70). '
                                 'Asset may be overvalued. Potential reversal or pullback.'
                    })
                
                # Mark oversold (<30)
                if rsi_value < 30:
                    rsi_data['oversold'].append({
                        'timestamp': timestamp,
                        'price': float(row['Close']),
                        'rsi': rsi_value,
                        'reason': f'RSI Oversold: RSI at {rsi_value:.1f} (<30). '
                                 'Asset may be undervalued. Potential bounce or reversal.'
                    })
        
        logger.info(f"Calculated RSI with {len(rsi_data['values'])} points")
        return rsi_data
    
    except Exception as e:
        logger.error(f"Error calculating RSI: {e}")
        return None


def calculate_macd(df, fast=12, slow=26, signal=9):
    """
    Calculate MACD (Moving Average Convergence Divergence)
    
    Args:
        df (pd.DataFrame): OHLCV data
        fast (int): Fast EMA period
        slow (int): Slow EMA period
        signal (int): Signal line period
    
    Returns:
        dict: MACD data with crossovers
    """
    try:
        if df is None or len(df) < slow:
            return None
        
        # Calculate EMAs
        df['EMA_Fast'] = df['Close'].ewm(span=fast, adjust=False).mean()
        df['EMA_Slow'] = df['Close'].ewm(span=slow, adjust=False).mean()
        
        # Calculate MACD line
        df['MACD'] = df['EMA_Fast'] - df['EMA_Slow']
        
        # Calculate signal line
        df['MACD_Signal'] = df['MACD'].ewm(span=signal, adjust=False).mean()
        
        # Calculate histogram
        df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
        
        # Prepare data
        macd_data = {
            'fast': fast,
            'slow': slow,
            'signal': signal,
            'macd_line': [],
            'signal_line': [],
            'histogram': [],
            'crossovers': []
        }
        
        prev_hist = None
        for idx, row in df.iterrows():
            if pd.notna(row['MACD']):
                timestamp = int(idx.timestamp())
                
                macd_data['macd_line'].append({
                    'time': timestamp,
                    'value': float(row['MACD'])
                })
                macd_data['signal_line'].append({
                    'time': timestamp,
                    'value': float(row['MACD_Signal'])
                })
                macd_data['histogram'].append({
                    'time': timestamp,
                    'value': float(row['MACD_Hist'])
                })
                
                # Detect crossovers
                if prev_hist is not None:
                    # Bullish crossover
                    if prev_hist < 0 and row['MACD_Hist'] > 0:
                        macd_data['crossovers'].append({
                            'type': 'bullish',
                            'timestamp': timestamp,
                            'price': float(row['Close']),
                            'reason': 'MACD Bullish Crossover: MACD line crossed above signal line. '
                                     'Momentum shifting to upside. Potential buy signal.'
                        })
                    
                    # Bearish crossover
                    if prev_hist > 0 and row['MACD_Hist'] < 0:
                        macd_data['crossovers'].append({
                            'type': 'bearish',
                            'timestamp': timestamp,
                            'price': float(row['Close']),
                            'reason': 'MACD Bearish Crossover: MACD line crossed below signal line. '
                                     'Momentum shifting to downside. Potential sell signal.'
                        })
                
                prev_hist = row['MACD_Hist']
        
        logger.info(f"Calculated MACD with {len(macd_data['crossovers'])} crossovers")
        return macd_data
    
    except Exception as e:
        logger.error(f"Error calculating MACD: {e}")
        return None


def calculate_moving_averages(df, periods=[20, 50, 200]):
    """
    Calculate multiple moving averages
    
    Args:
        df (pd.DataFrame): OHLCV data
        periods (list): List of MA periods
    
    Returns:
        dict: Moving average data
    """
    try:
        ma_data = {}
        
        for period in periods:
            if len(df) < period:
                continue
            
            df[f'MA_{period}'] = df['Close'].rolling(window=period).mean()
            
            ma_data[f'MA_{period}'] = []
            for idx, row in df.iterrows():
                if pd.notna(row[f'MA_{period}']):
                    ma_data[f'MA_{period}'].append({
                        'time': int(idx.timestamp()),
                        'price': float(row[f'MA_{period}'])
                    })
        
        logger.info(f"Calculated {len(ma_data)} moving averages")
        return ma_data
    
    except Exception as e:
        logger.error(f"Error calculating moving averages: {e}")
        return {}
