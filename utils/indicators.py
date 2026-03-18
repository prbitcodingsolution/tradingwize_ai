"""
Technical Indicators Module for TradingView MCP Visualization
Computes Bollinger Bands and other indicators locally
"""

import pandas as pd
import numpy as np
from typing import Tuple, Optional


class TechnicalIndicators:
    """Compute technical indicators for stock visualization"""
    
    @staticmethod
    def calculate_bollinger_bands(
        df: pd.DataFrame,
        period: int = 20,
        std_dev: float = 2.0,
        price_column: str = 'close'
    ) -> pd.DataFrame:
        """
        Calculate Bollinger Bands
        
        Args:
            df: DataFrame with OHLC data
            period: Period for SMA calculation (default: 20)
            std_dev: Number of standard deviations (default: 2.0)
            price_column: Column to use for calculation (default: 'close')
            
        Returns:
            DataFrame with added columns: bb_middle, bb_upper, bb_lower, bb_width, bb_percent
        """
        df = df.copy()
        
        # Calculate middle band (SMA)
        df['bb_middle'] = df[price_column].rolling(window=period).mean()
        
        # Calculate standard deviation
        rolling_std = df[price_column].rolling(window=period).std()
        
        # Calculate upper and lower bands
        df['bb_upper'] = df['bb_middle'] + (rolling_std * std_dev)
        df['bb_lower'] = df['bb_middle'] - (rolling_std * std_dev)
        
        # Calculate Bollinger Band width (for squeeze detection)
        df['bb_width'] = df['bb_upper'] - df['bb_lower']
        
        # Calculate %B (position within bands)
        # %B = (Price - Lower Band) / (Upper Band - Lower Band)
        df['bb_percent'] = (df[price_column] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])
        
        return df
    
    @staticmethod
    def detect_bollinger_squeeze(
        df: pd.DataFrame,
        lookback: int = 125,
        threshold_percentile: float = 5.0
    ) -> Tuple[bool, float, str]:
        """
        Detect Bollinger Band squeeze
        
        A squeeze occurs when the Bollinger Band width is at its lowest level
        compared to recent history, indicating low volatility and potential breakout
        
        Args:
            df: DataFrame with Bollinger Bands calculated
            lookback: Number of periods to look back for comparison
            threshold_percentile: Percentile threshold for squeeze detection
            
        Returns:
            Tuple of (is_squeeze, current_width_percentile, explanation)
        """
        if 'bb_width' not in df.columns:
            return False, 0.0, "Bollinger Bands not calculated"
        
        # Get recent width values
        recent_widths = df['bb_width'].tail(lookback)
        
        if len(recent_widths) < lookback:
            return False, 0.0, f"Insufficient data (need {lookback} periods)"
        
        # Get current width
        current_width = df['bb_width'].iloc[-1]
        
        # Calculate percentile rank of current width
        percentile_rank = (recent_widths < current_width).sum() / len(recent_widths) * 100
        
        # Squeeze detected if current width is in lowest percentile
        is_squeeze = percentile_rank <= threshold_percentile
        
        if is_squeeze:
            explanation = f"Bollinger Squeeze detected! Current band width is in the lowest {percentile_rank:.1f}% of the last {lookback} periods. This indicates extremely low volatility and potential for a significant breakout."
        else:
            explanation = f"No squeeze detected. Current band width is at {percentile_rank:.1f}% percentile (threshold: {threshold_percentile}%)."
        
        return is_squeeze, percentile_rank, explanation
    
    @staticmethod
    def calculate_sma(df: pd.DataFrame, period: int, column: str = 'close') -> pd.DataFrame:
        """Calculate Simple Moving Average"""
        df = df.copy()
        df[f'sma_{period}'] = df[column].rolling(window=period).mean()
        return df
    
    @staticmethod
    def calculate_ema(df: pd.DataFrame, period: int, column: str = 'close') -> pd.DataFrame:
        """Calculate Exponential Moving Average"""
        df = df.copy()
        df[f'ema_{period}'] = df[column].ewm(span=period, adjust=False).mean()
        return df
    
    @staticmethod
    def calculate_rsi(df: pd.DataFrame, period: int = 14, column: str = 'close') -> pd.DataFrame:
        """
        Calculate Relative Strength Index (RSI)
        
        Args:
            df: DataFrame with OHLC data
            period: Period for RSI calculation (default: 14)
            column: Column to use for calculation
            
        Returns:
            DataFrame with added 'rsi' column
        """
        df = df.copy()
        
        # Calculate price changes
        delta = df[column].diff()
        
        # Separate gains and losses
        gains = delta.where(delta > 0, 0)
        losses = -delta.where(delta < 0, 0)
        
        # Calculate average gains and losses
        avg_gains = gains.rolling(window=period).mean()
        avg_losses = losses.rolling(window=period).mean()
        
        # Calculate RS and RSI
        rs = avg_gains / avg_losses
        df['rsi'] = 100 - (100 / (1 + rs))
        
        return df
    
    @staticmethod
    def calculate_macd(
        df: pd.DataFrame,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
        column: str = 'close'
    ) -> pd.DataFrame:
        """
        Calculate MACD (Moving Average Convergence Divergence)
        
        Args:
            df: DataFrame with OHLC data
            fast_period: Fast EMA period (default: 12)
            slow_period: Slow EMA period (default: 26)
            signal_period: Signal line period (default: 9)
            column: Column to use for calculation
            
        Returns:
            DataFrame with added 'macd', 'macd_signal', 'macd_histogram' columns
        """
        df = df.copy()
        
        # Calculate EMAs
        ema_fast = df[column].ewm(span=fast_period, adjust=False).mean()
        ema_slow = df[column].ewm(span=slow_period, adjust=False).mean()
        
        # Calculate MACD line
        df['macd'] = ema_fast - ema_slow
        
        # Calculate signal line
        df['macd_signal'] = df['macd'].ewm(span=signal_period, adjust=False).mean()
        
        # Calculate histogram
        df['macd_histogram'] = df['macd'] - df['macd_signal']
        
        return df
    
    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """
        Calculate Average True Range (ATR)
        
        Args:
            df: DataFrame with OHLC data
            period: Period for ATR calculation (default: 14)
            
        Returns:
            DataFrame with added 'atr' column
        """
        df = df.copy()
        
        # Calculate True Range
        df['tr1'] = df['high'] - df['low']
        df['tr2'] = abs(df['high'] - df['close'].shift())
        df['tr3'] = abs(df['low'] - df['close'].shift())
        
        df['true_range'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
        
        # Calculate ATR
        df['atr'] = df['true_range'].rolling(window=period).mean()
        
        # Clean up temporary columns
        df = df.drop(['tr1', 'tr2', 'tr3', 'true_range'], axis=1)
        
        return df
    
    @staticmethod
    def add_all_indicators(
        df: pd.DataFrame,
        bb_period: int = 20,
        bb_std: float = 2.0,
        rsi_period: int = 14,
        include_macd: bool = True,
        include_atr: bool = True
    ) -> pd.DataFrame:
        """
        Add all common technical indicators to DataFrame
        
        Args:
            df: DataFrame with OHLC data
            bb_period: Bollinger Bands period
            bb_std: Bollinger Bands standard deviation
            rsi_period: RSI period
            include_macd: Whether to include MACD
            include_atr: Whether to include ATR
            
        Returns:
            DataFrame with all indicators added
        """
        df = TechnicalIndicators.calculate_bollinger_bands(df, bb_period, bb_std)
        df = TechnicalIndicators.calculate_rsi(df, rsi_period)
        
        if include_macd:
            df = TechnicalIndicators.calculate_macd(df)
        
        if include_atr:
            df = TechnicalIndicators.calculate_atr(df)
        
        return df


# Convenience function
def add_bollinger_bands(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
    """Convenience function to add Bollinger Bands"""
    return TechnicalIndicators.calculate_bollinger_bands(df, period, std_dev)


def detect_squeeze(df: pd.DataFrame, lookback: int = 125) -> Tuple[bool, float, str]:
    """Convenience function to detect Bollinger squeeze"""
    return TechnicalIndicators.detect_bollinger_squeeze(df, lookback)
