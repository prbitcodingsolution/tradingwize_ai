"""
API-Based Price Data Fetcher
Fetches OHLCV data from external API endpoint
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class APIPriceFetcher:
    """Fetches price data from external API"""
    
    def __init__(self, base_url, bearer_token=None, csrf_token=None):
        """
        Initialize API fetcher
        
        Args:
            base_url (str): Base API URL (e.g., 'http://192.168.0.126:8000')
            bearer_token (str): Bearer token for authorization (optional)
            csrf_token (str): CSRF token (optional)
        """
        self.base_url = base_url.rstrip('/')
        self.bearer_token = bearer_token
        self.csrf_token = csrf_token
        
        self.headers = {
            'accept': 'application/json'
        }
        
        # Only add authorization if token is provided
        if bearer_token:
            self.headers['authorization'] = f'Bearer {bearer_token}'
        
        if csrf_token:
            self.headers['X-CSRFToken'] = csrf_token
    
    def fetch_price_data(self, symbol, timeframe="1d", from_date=None, to_date=None, market="stocks"):
        """
        Fetch OHLCV price data for a given symbol
        
        Args:
            symbol (str): Stock symbol (e.g., "ONGC.NS", "RELIANCE.NS")
            timeframe (str): Interval - "1m", "5m", "15m", "1h", "1d", "1w", "1M"
            from_date (str): Start date in YYYY-MM-DD format
            to_date (str): End date in YYYY-MM-DD format
            market (str): Market type - "stocks", "forex", "crypto"
        
        Returns:
            pd.DataFrame: OHLCV data with columns [Open, High, Low, Close, Volume, timestamp]
        """
        try:
            # Set default dates if not provided
            if not to_date:
                to_date = datetime.now().strftime('%Y-%m-%d')
            
            if not from_date:
                # Default to 1 year ago
                from_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
            
            logger.info(f"Fetching data for {symbol} from {from_date} to {to_date}")
            
            # Build API URL
            endpoint = f"{self.base_url}/api/v1/mentor/get-forex-data/"
            
            params = {
                'pair': symbol,
                'from': from_date,
                'to': to_date,
                'market': market,
                'timeframe': timeframe
            }
            
            # Make API request
            logger.info(f"API Request: {endpoint}")
            logger.info(f"Params: {params}")
            
            response = requests.get(
                endpoint,
                params=params,
                headers=self.headers,
                timeout=30
            )
            
            # Check response status
            if response.status_code == 401:
                logger.error(f"❌ Authentication Error (401): Token is invalid or expired")
                logger.error(f"   Response: {response.text}")
                logger.error(f"\n🔧 FIX: Update API_BEARER_TOKEN in .env file with a new token")
                logger.error(f"   Get new token from: {self.base_url}")
                raise ValueError("Failed to fetch price data: API token is invalid or expired. Please update API_BEARER_TOKEN in .env file.")
            
            if response.status_code != 200:
                logger.error(f"API Error: {response.status_code} - {response.text}")
                raise ValueError(f"Failed to fetch price data: API returned status {response.status_code}")
            
            # Parse JSON response
            data = response.json()
            
            # Check if data is valid
            if not data or 'data' not in data:
                logger.error(f"Invalid API response format: {data}")
                raise ValueError(f"Invalid API response format - missing 'data' field")
            
            candles = data.get('data', [])
            
            if not candles:
                logger.warning(f"No candle data returned for {symbol}")
                raise ValueError(f"No candle data returned for {symbol}")
            
            # Convert to DataFrame
            df = self._convert_to_dataframe(candles)
            
            if df is None or df.empty:
                logger.error(f"Failed to convert API data to DataFrame")
                raise ValueError("Failed to convert API data to DataFrame")
            
            logger.info(f"Successfully fetched {len(df)} candles for {symbol}")
            return df
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error fetching data: {e}")
            raise ValueError(f"Network error: {e}")
        
        except ValueError as ve:
            # Re-raise ValueError (includes our custom errors and token errors)
            raise ve
        
        except Exception as e:
            logger.error(f"Error fetching data for {symbol}: {e}")
            raise ValueError(f"Unexpected error: {e}")
    
    def _convert_to_dataframe(self, candles):
        """
        Convert API candle data to pandas DataFrame
        
        Expected API format:
        [
            {
                "time": 1640995200,  // Unix timestamp
                "open": 100.5,
                "high": 102.3,
                "low": 99.8,
                "close": 101.2,
                "volume": 1000000
            },
            ...
        ]
        
        Alternative formats also supported:
        - "timestamp" instead of "time"
        - "o", "h", "l", "c", "v" instead of full names
        """
        try:
            if not candles:
                return None
            
            # Detect format from first candle
            first_candle = candles[0]
            
            # Map different possible field names
            time_field = None
            for field in ['time', 'timestamp', 't', 'date']:
                if field in first_candle:
                    time_field = field
                    break
            
            if not time_field:
                logger.error("No time field found in candle data")
                return None
            
            # Map OHLCV fields
            field_mapping = {
                'open': ['open', 'o', 'Open'],
                'high': ['high', 'h', 'High'],
                'low': ['low', 'l', 'Low'],
                'close': ['close', 'c', 'Close'],
                'volume': ['volume', 'v', 'Volume', 'vol']
            }
            
            # Extract data
            data_dict = {
                'timestamp': [],
                'Open': [],
                'High': [],
                'Low': [],
                'Close': [],
                'Volume': []
            }
            
            for candle in candles:
                # Get timestamp
                timestamp = candle.get(time_field)
                if timestamp is None:
                    continue
                
                # Convert to datetime if needed
                if isinstance(timestamp, (int, float)):
                    # Unix timestamp
                    dt = pd.to_datetime(timestamp, unit='s')
                else:
                    # String date
                    dt = pd.to_datetime(timestamp)
                
                data_dict['timestamp'].append(dt)
                
                # Get OHLCV values
                for target_field, possible_fields in field_mapping.items():
                    value = None
                    for field in possible_fields:
                        if field in candle:
                            value = candle[field]
                            break
                    
                    # Use 0 as default for missing values
                    if value is None:
                        value = 0
                    
                    data_dict[target_field.capitalize()].append(float(value))
            
            # Create DataFrame
            df = pd.DataFrame(data_dict)
            
            # Set timestamp as index
            df.set_index('timestamp', inplace=True)
            df.index.name = None
            
            # Sort by timestamp
            df.sort_index(inplace=True)
            
            # Add Unix timestamp column
            df['timestamp'] = df.index.astype('int64') // 10**9
            
            # Validate data
            required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
            if not all(col in df.columns for col in required_cols):
                logger.error(f"Missing required columns in DataFrame")
                return None
            
            return df
        
        except Exception as e:
            logger.error(f"Error converting candles to DataFrame: {e}")
            return None
    
    def get_latest_price(self, symbol, market="stocks"):
        """Get the latest price for a symbol"""
        try:
            # Fetch last 2 days of data
            to_date = datetime.now().strftime('%Y-%m-%d')
            from_date = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
            
            df = self.fetch_price_data(symbol, "1d", from_date, to_date, market)
            
            if df is not None and not df.empty:
                return df['Close'].iloc[-1]
            
            return None
        
        except Exception as e:
            logger.error(f"Error getting latest price: {e}")
            return None
    
    def validate_symbol(self, symbol, market="stocks"):
        """Validate if a symbol exists by trying to fetch data"""
        try:
            to_date = datetime.now().strftime('%Y-%m-%d')
            from_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
            
            df = self.fetch_price_data(symbol, "1d", from_date, to_date, market)
            
            return df is not None and not df.empty
        
        except:
            return False


# Convenience function for backward compatibility
def fetch_price_data_from_api(symbol, timeframe="1d", from_date=None, to_date=None, 
                               base_url=None, bearer_token=None, csrf_token=None, market="stocks"):
    """
    Convenience function to fetch price data from API
    
    Args:
        symbol (str): Stock symbol
        timeframe (str): Timeframe
        from_date (str): Start date (YYYY-MM-DD)
        to_date (str): End date (YYYY-MM-DD)
        base_url (str): API base URL
        bearer_token (str): Bearer token
        csrf_token (str): CSRF token (optional)
        market (str): Market type
    
    Returns:
        pd.DataFrame: OHLCV data
    """
    if not base_url or not bearer_token:
        logger.error("base_url and bearer_token are required")
        return None
    
    fetcher = APIPriceFetcher(base_url, bearer_token, csrf_token)
    return fetcher.fetch_price_data(symbol, timeframe, from_date, to_date, market)


# CLI testing
if __name__ == "__main__":
    import sys
    
    # Example usage
    BASE_URL = "http://192.168.0.126:8000"
    BEARER_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzcyNTIxMzQ0LCJpYXQiOjE3NzI1MTA1NDQsImp0aSI6IjYzYzE1YjI0MGY4ZTQ5YjQ5MzdjNTY4NmViYjhlMDBmIiwidXNlcl9pZCI6MywidmVyIjoxODZ9.tO6AYXQlEg-Z1mcszRBwu75HJEkm2IyuCy_Ql3cmik4"
    CSRF_TOKEN = "afmpb9wewmMjFhB5PP3uOYLmGXFJPvwIrUi5Olty5ydrkJLMd6w3TsGLGRz7wqeo"
    
    if len(sys.argv) < 2:
        print("Usage: python api_price_fetcher.py <SYMBOL>")
        print("Example: python api_price_fetcher.py ONGC.NS")
        sys.exit(1)
    
    symbol = sys.argv[1]
    
    print(f"\n{'='*70}")
    print(f"Testing API Price Fetcher for {symbol}")
    print(f"{'='*70}\n")
    
    fetcher = APIPriceFetcher(BASE_URL, BEARER_TOKEN, CSRF_TOKEN)
    
    df = fetcher.fetch_price_data(
        symbol=symbol,
        timeframe="1d",
        from_date="2025-01-01",
        to_date="2026-03-03",
        market="stocks"
    )
    
    if df is not None:
        print(f"\n✅ Successfully fetched {len(df)} candles")
        print(f"\nFirst 5 rows:")
        print(df.head())
        print(f"\nLast 5 rows:")
        print(df.tail())
        print(f"\nData shape: {df.shape}")
        print(f"Columns: {df.columns.tolist()}")
    else:
        print("\n❌ Failed to fetch data")
