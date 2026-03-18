"""
Data Fetcher Module for TradingView MCP Visualization
Fetches OHLC data for stocks identified by MCP scanner
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple
import time


class OHLCDataFetcher:
    """Fetch OHLC data for stock visualization"""
    
    # Timeframe mapping for yfinance
    TIMEFRAME_MAP = {
        '1m': '1m',
        '5m': '5m',
        '15m': '15m',
        '30m': '30m',
        '1h': '1h',
        '1d': '1d',
        '1wk': '1wk',
        '1mo': '1mo'
    }
    
    # Period mapping for different timeframes
    PERIOD_MAP = {
        '1m': '7d',      # 1 minute data - last 7 days
        '5m': '60d',     # 5 minute data - last 60 days
        '15m': '60d',    # 15 minute data - last 60 days
        '30m': '60d',    # 30 minute data - last 60 days
        '1h': '730d',    # 1 hour data - last 2 years
        '1d': '2y',      # Daily data - last 2 years
        '1wk': '5y',     # Weekly data - last 5 years
        '1mo': '10y'     # Monthly data - last 10 years
    }
    
    def __init__(self):
        self.cache = {}  # Simple in-memory cache
        self.cache_ttl = 300  # 5 minutes cache TTL
    
    def _get_cache_key(self, symbol: str, timeframe: str) -> str:
        """Generate cache key"""
        return f"{symbol}_{timeframe}"
    
    def _is_cache_valid(self, cache_entry: Dict) -> bool:
        """Check if cache entry is still valid"""
        if not cache_entry:
            return False
        
        cache_time = cache_entry.get('timestamp', 0)
        current_time = time.time()
        
        return (current_time - cache_time) < self.cache_ttl
    
    def fetch_ohlc(
        self, 
        symbol: str, 
        timeframe: str = '1d',
        period: Optional[str] = None,
        use_cache: bool = True
    ) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
        """
        Fetch OHLC data for a symbol
        
        Args:
            symbol: Stock symbol (e.g., "RELIANCE.NS", "TCS.NS")
            timeframe: Timeframe for data ('1m', '5m', '15m', '1h', '1d', etc.)
            period: Period to fetch (e.g., '1d', '5d', '1mo', '1y'). Auto-determined if None
            use_cache: Whether to use cached data
            
        Returns:
            Tuple of (DataFrame with OHLC data, error message if any)
        """
        print(f"📊 Fetching OHLC data for {symbol} ({timeframe})...")
        
        # Check cache first
        if use_cache:
            cache_key = self._get_cache_key(symbol, timeframe)
            cache_entry = self.cache.get(cache_key)
            
            if cache_entry and self._is_cache_valid(cache_entry):
                print(f"   ✅ Using cached data for {symbol}")
                return cache_entry['data'], None
        
        try:
            # Validate timeframe
            if timeframe not in self.TIMEFRAME_MAP:
                return None, f"Invalid timeframe: {timeframe}. Valid options: {list(self.TIMEFRAME_MAP.keys())}"
            
            # Determine period if not provided
            if period is None:
                period = self.PERIOD_MAP.get(timeframe, '1y')
            
            # Fetch data from yfinance
            ticker = yf.Ticker(symbol)
            
            # Download historical data
            df = ticker.history(
                period=period,
                interval=self.TIMEFRAME_MAP[timeframe],
                actions=False  # Don't include dividends/splits
            )
            
            if df.empty:
                return None, f"No data available for {symbol}"
            
            # Clean up the dataframe
            df = df.reset_index()
            
            # Rename columns to standard format
            column_mapping = {
                'Date': 'datetime',
                'Datetime': 'datetime',
                'Open': 'open',
                'High': 'high',
                'Low': 'low',
                'Close': 'close',
                'Volume': 'volume'
            }
            
            df = df.rename(columns=column_mapping)
            
            # Ensure we have required columns
            required_cols = ['datetime', 'open', 'high', 'low', 'close', 'volume']
            if not all(col in df.columns for col in required_cols):
                return None, f"Missing required columns in data for {symbol}"
            
            # Sort by datetime
            df = df.sort_values('datetime')
            
            # Cache the result
            cache_key = self._get_cache_key(symbol, timeframe)
            self.cache[cache_key] = {
                'data': df,
                'timestamp': time.time()
            }
            
            print(f"   ✅ Fetched {len(df)} candles for {symbol}")
            return df, None
            
        except Exception as e:
            error_msg = f"Error fetching data for {symbol}: {str(e)}"
            print(f"   ❌ {error_msg}")
            return None, error_msg
    
    def fetch_multiple(
        self,
        symbols: list,
        timeframe: str = '1d',
        period: Optional[str] = None
    ) -> Dict[str, Tuple[Optional[pd.DataFrame], Optional[str]]]:
        """
        Fetch OHLC data for multiple symbols
        
        Args:
            symbols: List of stock symbols
            timeframe: Timeframe for data
            period: Period to fetch
            
        Returns:
            Dictionary mapping symbol to (DataFrame, error) tuple
        """
        results = {}
        
        for symbol in symbols:
            df, error = self.fetch_ohlc(symbol, timeframe, period)
            results[symbol] = (df, error)
        
        return results
    
    def clear_cache(self):
        """Clear the data cache"""
        self.cache = {}
        print("✅ Cache cleared")
    
    def get_latest_price(self, symbol: str) -> Optional[float]:
        """
        Get the latest price for a symbol
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Latest close price or None
        """
        df, error = self.fetch_ohlc(symbol, timeframe='1d', period='1d')
        
        if df is not None and not df.empty:
            return float(df['close'].iloc[-1])
        
        return None


# Singleton instance
_fetcher_instance = None

def get_data_fetcher() -> OHLCDataFetcher:
    """Get singleton instance of data fetcher"""
    global _fetcher_instance
    if _fetcher_instance is None:
        _fetcher_instance = OHLCDataFetcher()
    return _fetcher_instance
