"""
Main Drawing Generator
Orchestrates the entire pipeline: fetch data → detect → build JSON
"""

import logging
from .price_fetcher import fetch_price_data
from .api_price_fetcher import APIPriceFetcher
from .zone_detector import detect_supply_demand_zones, detect_key_levels
from .pattern_detector import detect_candlestick_patterns
from .indicator_calculator import (
    calculate_bollinger_bands,
    calculate_rsi,
    calculate_macd,
    calculate_moving_averages
)
from .json_builder import build_drawing_json
from .symbol_resolver import resolve_symbol

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def generate_drawings(symbol, timeframe="1d", period="1y", tasks=None, 
                     use_api=False, api_config=None):
    """
    Main function to generate drawing instructions
    
    Args:
        symbol (str): Stock symbol (will be auto-resolved to NSE format)
        timeframe (str): Chart timeframe
        period (str): Data period (for yfinance) or ignored if use_api=True
        tasks (list): List of tasks to perform
                     ['zones', 'patterns', 'bollinger', 'rsi', 'macd', 'levels']
                     If None, performs all tasks
        use_api (bool): If True, use external API instead of yfinance
        api_config (dict): API configuration with keys:
                          - base_url: API base URL
                          - bearer_token: Bearer token
                          - csrf_token: CSRF token (optional)
                          - from_date: Start date (YYYY-MM-DD)
                          - to_date: End date (YYYY-MM-DD)
                          - market: Market type (default: 'stocks')
    
    Returns:
        dict: Complete drawing JSON
    """
    try:
        # Resolve symbol to correct NSE format
        original_symbol = symbol
        symbol = resolve_symbol(symbol)
        
        if original_symbol != symbol:
            logger.info(f"Symbol resolved: {original_symbol} -> {symbol}")
        
        logger.info(f"Starting drawing generation for {symbol}")
        
        # Default to all tasks
        if tasks is None:
            tasks = ['zones', 'patterns', 'bollinger', 'rsi', 'macd', 'levels']
        
        # Step 1: Fetch price data
        logger.info("Step 1: Fetching price data...")
        
        if use_api and api_config:
            # Use external API
            logger.info("Using external API for data fetching...")
            fetcher = APIPriceFetcher(
                base_url=api_config.get('base_url'),
                bearer_token=api_config.get('bearer_token'),
                csrf_token=api_config.get('csrf_token')
            )
            
            df = fetcher.fetch_price_data(
                symbol=symbol,
                timeframe=timeframe,
                from_date=api_config.get('from_date'),
                to_date=api_config.get('to_date'),
                market=api_config.get('market', 'stocks')
            )
        else:
            # Use yfinance
            logger.info("Using yfinance for data fetching...")
            df = fetch_price_data(symbol, timeframe, period)
        
        if df is None or df.empty:
            return {
                'symbol': symbol,
                'error': 'Failed to fetch price data',
                'total_drawings': 0,
                'drawings': []
            }
        
        logger.info(f"Fetched {len(df)} candles")
        
        # Step 2: Detect zones
        zones = None
        if 'zones' in tasks:
            logger.info("Step 2: Detecting supply/demand zones...")
            zones = detect_supply_demand_zones(df)
            logger.info(f"Detected {len(zones)} zones")
        
        # Step 3: Detect patterns
        patterns = None
        if 'patterns' in tasks:
            logger.info("Step 3: Detecting candlestick patterns...")
            patterns = detect_candlestick_patterns(df)
            logger.info(f"Detected {len(patterns)} patterns")
        
        # Step 4: Calculate Bollinger Bands
        bollinger = None
        if 'bollinger' in tasks:
            logger.info("Step 4: Calculating Bollinger Bands...")
            bollinger = calculate_bollinger_bands(df)
        
        # Step 5: Calculate RSI
        rsi = None
        if 'rsi' in tasks:
            logger.info("Step 5: Calculating RSI...")
            rsi = calculate_rsi(df)
        
        # Step 6: Calculate MACD
        macd = None
        if 'macd' in tasks:
            logger.info("Step 6: Calculating MACD...")
            macd = calculate_macd(df)
        
        # Step 7: Detect key levels
        levels = None
        if 'levels' in tasks:
            logger.info("Step 7: Detecting key levels...")
            levels = detect_key_levels(df)
            logger.info(f"Detected {len(levels)} key levels")
        
        # Step 8: Build JSON
        logger.info("Step 8: Building drawing JSON...")
        drawings = build_drawing_json(
            symbol=symbol,
            zones=zones,
            patterns=patterns,
            bollinger=bollinger,
            rsi=rsi,
            macd=macd,
            levels=levels
        )
        
        result = {
            'symbol': symbol,
            'total_drawings': len(drawings),
            'drawings': drawings
        }
        
        logger.info(f"✅ Successfully generated {len(drawings)} drawings for {symbol}")
        return result
    
    except Exception as e:
        logger.error(f"Error generating drawings: {e}")
        return {
            'symbol': symbol,
            'error': str(e),
            'total_drawings': 0,
            'drawings': []
        }


def generate_zones_only(symbol, timeframe="1d", period="1y", use_api=False, api_config=None):
    """Generate only supply/demand zones"""
    return generate_drawings(symbol, timeframe, period, tasks=['zones'], use_api=use_api, api_config=api_config)


def generate_patterns_only(symbol, timeframe="1d", period="1y", use_api=False, api_config=None):
    """Generate only candlestick patterns"""
    return generate_drawings(symbol, timeframe, period, tasks=['patterns'], use_api=use_api, api_config=api_config)


def generate_indicators_only(symbol, timeframe="1d", period="1y", use_api=False, api_config=None):
    """Generate only technical indicators"""
    return generate_drawings(symbol, timeframe, period, tasks=['bollinger', 'rsi', 'macd'], use_api=use_api, api_config=api_config)


def generate_complete_analysis(symbol, timeframe="1d", period="1y", use_api=False, api_config=None):
    """Generate complete analysis with all features"""
    return generate_drawings(symbol, timeframe, period, tasks=None, use_api=use_api, api_config=api_config)


# CLI interface for testing
if __name__ == "__main__":
    import sys
    import json
    
    if len(sys.argv) < 2:
        print("Usage: python drawing_generator.py <SYMBOL> [timeframe] [period]")
        print("Example: python drawing_generator.py AAPL 1d 1y")
        print("Or with API: python drawing_generator.py ONGC.NS 1d --api")
        sys.exit(1)
    
    symbol = sys.argv[1]
    timeframe = sys.argv[2] if len(sys.argv) > 2 else "1d"
    period = sys.argv[3] if len(sys.argv) > 3 else "1y"
    
    # Check for API mode
    use_api = '--api' in sys.argv
    
    # API configuration
    api_config = None
    if use_api:
        api_config = {
            'base_url': 'http://192.168.0.126:8000',
            'bearer_token': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzcyNTIxMzQ0LCJpYXQiOjE3NzI1MTA1NDQsImp0aSI6IjYzYzE1YjI0MGY4ZTQ5YjQ5MzdjNTY4NmViYjhlMDBmIiwidXNlcl9pZCI6MywidmVyIjoxODZ9.tO6AYXQlEg-Z1mcszRBwu75HJEkm2IyuCy_Ql3cmik4',
            'csrf_token': 'afmpb9wewmMjFhB5PP3uOYLmGXFJPvwIrUi5Olty5ydrkJLMd6w3TsGLGRz7wqeo',
            'from_date': '2025-01-01',
            'to_date': '2026-03-03',
            'market': 'stocks'
        }
    
    print(f"\n{'='*70}")
    print(f"Generating Drawing Instructions for {symbol}")
    print(f"Mode: {'API' if use_api else 'yfinance'}")
    print(f"{'='*70}\n")
    
    result = generate_complete_analysis(symbol, timeframe, period, use_api=use_api, api_config=api_config)
    
    # Save to file
    output_file = f"drawing_output_{symbol}_{timeframe}.json"
    with open(output_file, 'w') as f:
        json.dump(result, f, indent=2)
    
    print(f"\n{'='*70}")
    print(f"✅ Generated {result['total_drawings']} drawings")
    print(f"📁 Saved to: {output_file}")
    print(f"{'='*70}\n")
