"""
Price Data Fetcher
Fetches OHLCV data from various sources
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def fetch_price_data(symbol, timeframe="1d", period="1y"):
    """
    Fetch OHLCV price data for a given symbol
    
    Args:
        symbol (str): Stock symbol (e.g., "AAPL", "RELIANCE.NS")
        timeframe (str): Interval - "1m", "5m", "15m", "1h", "1d", "1wk", "1mo"
        period (str): Period - "1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "max"
    
    Returns:
        pd.DataFrame: OHLCV data with columns [Open, High, Low, Close, Volume]
    """
    try:
        logger.info(f"Fetching data for {symbol} - {timeframe} - {period}")
        
        # Smart symbol handling: Only add .NS for known Indian stocks
        original_symbol = symbol
        
        # List of common US stock symbols (don't add .NS to these)
        us_stocks = ['AAPL', 'MSFT', 'GOOGL', 'GOOG', 'AMZN', 'TSLA', 'META', 'NVDA', 
                     'AMD', 'NFLX', 'DIS', 'BABA', 'INTC', 'CSCO', 'ORCL', 'IBM',
                     'JPM', 'BAC', 'WFC', 'GS', 'MS', 'C', 'V', 'MA', 'PYPL',
                     'KO', 'PEP', 'MCD', 'SBUX', 'NKE', 'WMT', 'TGT', 'COST',
                     'XOM', 'CVX', 'COP', 'SLB', 'BA', 'CAT', 'GE', 'F', 'GM']
        
        # If symbol has no suffix and is not a known US stock, try adding .NS
        if not any(x in symbol for x in ['.NS', '.BO', '.', '^']):
            if symbol.upper() not in us_stocks:
                # Try with .NS first (Indian NSE)
                symbol = f"{symbol}.NS"
                logger.info(f"Trying Indian NSE symbol: {symbol}")
        
        # Fetch data
        ticker = yf.Ticker(symbol)
        df = ticker.history(interval=timeframe, period=period)
        
        # If no data and we added .NS, try without it (might be US stock)
        if df.empty and symbol != original_symbol and symbol.endswith('.NS'):
            logger.warning(f"No data for {symbol}, trying without .NS suffix...")
            symbol = original_symbol
            ticker = yf.Ticker(symbol)
            df = ticker.history(interval=timeframe, period=period)
        
        if df.empty:
            logger.error(f"No data found for {symbol}")
            return None
        
        # Ensure we have required columns
        required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
        if not all(col in df.columns for col in required_cols):
            logger.error(f"Missing required columns in data")
            return None
        
        # Add timestamp column (Unix epoch)
        df['timestamp'] = df.index.astype('int64') // 10**9
        
        logger.info(f"Successfully fetched {len(df)} candles for {symbol}")
        return df
    
    except Exception as e:
        logger.error(f"Error fetching data for {symbol}: {e}")
        return None


def get_latest_price(symbol):
    """Get the latest price for a symbol"""
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period="1d")
        if not data.empty:
            return data['Close'].iloc[-1]
        return None
    except Exception as e:
        logger.error(f"Error getting latest price: {e}")
        return None


def validate_symbol(symbol):
    """Validate if a symbol exists"""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        return 'symbol' in info or 'shortName' in info
    except:
        return False
