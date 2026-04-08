"""
LLM-Powered Drawing Generator
Uses AI analysis to generate accurate drawing instructions
"""

import logging

# Try absolute imports first, then relative
try:
    from llm_pattern_detector import detect_patterns_with_llm
    from api_price_fetcher import APIPriceFetcher
    from json_builder import build_drawing_json_from_llm
    from symbol_resolver import resolve_symbol
except ImportError:
    from .llm_pattern_detector import detect_patterns_with_llm
    from .api_price_fetcher import APIPriceFetcher
    from .json_builder import build_drawing_json_from_llm
    from .symbol_resolver import resolve_symbol

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def generate_drawings_with_llm(symbol, timeframe="1d", use_api=True, api_config=None):
    """
    Generate drawing instructions using LLM analysis
    
    Args:
        symbol (str): Stock symbol (will be auto-resolved to NSE format)
        timeframe (str): Chart timeframe
        use_api (bool): Use external API for data
        api_config (dict): API configuration
    
    Returns:
        dict: Complete drawing JSON with LLM-detected patterns
    """
    try:
        # Resolve symbol — use market from api_config so US/forex symbols don't get .NS suffix
        original_symbol = symbol
        _market = (api_config or {}).get('market', 'stock')
        symbol = resolve_symbol(symbol, market=_market)

        if original_symbol != symbol:
            logger.info(f"Symbol resolved: {original_symbol} -> {symbol}")
        
        logger.info(f"Starting LLM-powered drawing generation for {symbol}")
        
        # Step 1: Fetch price data
        logger.info("Step 1: Fetching price data from API...")
        
        if not api_config:
            return {
                'symbol': symbol,
                'error': 'API configuration required',
                'total_drawings': 0,
                'drawings': []
            }
        
        df = None
        data_source = "unknown"
        
        # Try API first
        try:
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
            data_source = "external_api"
            logger.info(f"✅ Fetched {len(df)} candles from API")
            
        except ValueError as api_error:
            logger.warning(f"⚠️  API fetch failed: {api_error}")
            logger.info("🔄 Attempting yfinance fallback...")
            
            # Fallback to yfinance
            try:
                import yfinance as yf
                from datetime import datetime

                start_date = api_config.get('from_date', '2025-01-01')
                end_date = api_config.get('to_date', datetime.now().strftime('%Y-%m-%d'))

                # Convert symbol to yfinance format for non-stock markets
                # Strip any =X suffix first to get the clean symbol
                yf_symbol = symbol
                if yf_symbol.endswith('=X'):
                    yf_symbol = yf_symbol[:-2]
                if yf_symbol.endswith('=F'):
                    yf_symbol = yf_symbol[:-2]

                yf_market = api_config.get('market', 'stocks').lower()
                if yf_market == 'forex':
                    # Precious metals / commodities need futures format on yfinance
                    _FOREX_YF_MAP = {
                        'XAUUSD': 'GC=F',   # Gold
                        'XAGUSD': 'SI=F',    # Silver
                        'XPTUSD': 'PL=F',    # Platinum
                        'XPDUSD': 'PA=F',    # Palladium
                        'WTIUSD': 'CL=F',    # Crude Oil WTI
                        'BCOUSD': 'BZ=F',    # Brent Crude
                        'NGUSD':  'NG=F',    # Natural Gas
                    }
                    if yf_symbol.upper() in _FOREX_YF_MAP:
                        yf_symbol = _FOREX_YF_MAP[yf_symbol.upper()]
                    elif not yf_symbol.endswith('=X'):
                        # Regular forex pairs use =X (e.g. EURUSD=X)
                        yf_symbol = f"{yf_symbol}=X"
                elif yf_market == 'crypto':
                    # yfinance uses -USD suffix for crypto (e.g. BTC-USD, ETH-USD)
                    if not yf_symbol.endswith('-USD') and 'USD' not in yf_symbol:
                        yf_symbol = f"{yf_symbol}-USD"

                logger.info(f"Downloading {yf_symbol} data from yfinance ({start_date} to {end_date})...")
                ticker = yf.Ticker(yf_symbol)
                df = ticker.history(start=start_date, end=end_date, interval='1d')
                
                if df is None or df.empty:
                    raise ValueError("No data returned from yfinance")
                
                # Standardize column names
                df = df.rename(columns={
                    'Open': 'Open',
                    'High': 'High',
                    'Low': 'Low',
                    'Close': 'Close',
                    'Volume': 'Volume'
                })
                
                # Add timestamp column
                df['timestamp'] = df.index.astype('int64') // 10**9
                
                data_source = "yfinance_fallback"
                logger.info(f"✅ Successfully fetched {len(df)} candles from yfinance fallback")
                
            except ImportError:
                logger.error("❌ yfinance not installed. Install with: pip install yfinance")
                return {
                    'symbol': symbol,
                    'error': 'Failed to fetch price data: API token expired and yfinance not installed',
                    'total_drawings': 0,
                    'drawings': [],
                    'help': 'Run: python refresh_api_token.py OR pip install yfinance'
                }
            except Exception as yf_error:
                logger.error(f"❌ Yfinance fallback also failed: {yf_error}")
                return {
                    'symbol': symbol,
                    'error': f'Failed to fetch price data from both API and yfinance. API: {str(api_error)}. Yfinance: {str(yf_error)}',
                    'total_drawings': 0,
                    'drawings': [],
                    'help': 'Please update API_BEARER_TOKEN in .env file or check symbol format'
                }
        
        # Check if we got data
        if df is None or df.empty:
            return {
                'symbol': symbol,
                'error': 'Failed to fetch price data from all sources',
                'total_drawings': 0,
                'drawings': []
            }
        
        logger.info(f"Fetched {len(df)} candles")
        
        # Convert DataFrame to JSON-serializable format
        candles_data = []
        for idx, row in df.iterrows():
            candles_data.append({
                'timestamp': int(idx.timestamp()),
                'date': idx.strftime('%Y-%m-%d'),
                'open': float(row['Open']),
                'high': float(row['High']),
                'low': float(row['Low']),
                'close': float(row['Close']),
                'volume': float(row['Volume'])
            })
        
        # Step 2: Analyze with LLM
        logger.info("Step 2: Analyzing data with LLM (AI-powered detection)...")
        analysis = detect_patterns_with_llm(df, symbol)
        
        if 'error' in analysis:
            logger.error(f"LLM analysis error: {analysis['error']}")
            return {
                'symbol': symbol,
                'error': f"LLM analysis failed: {analysis['error']}",
                'total_drawings': 0,
                'drawings': [],
                'candles': candles_data  # Include candles even on error
            }
        
        # Check if LLM returned meaningful results
        zones_count = len(analysis.get('zones', []))
        patterns_count = len(analysis.get('patterns', []))
        fvg_zones_count = len(analysis.get('fvg_zones', []))
        
        logger.info(f"LLM detected {patterns_count} patterns")
        logger.info(f"LLM detected {zones_count} zones")
        logger.info(f"LLM detected {fvg_zones_count} FVG zones")
        
        # Debug: Log the analysis structure
        logger.info(f"Analysis keys: {list(analysis.keys())}")
        if 'fvg_zones' in analysis:
            logger.info(f"FVG zones in analysis: {analysis['fvg_zones']}")
        else:
            logger.warning("⚠️  No 'fvg_zones' key found in LLM analysis")
        
        # CRITICAL FIX: If LLM didn't detect zones, use fallback for zones (regardless of patterns)
        if zones_count == 0:
            logger.warning("⚠️  LLM detected 0 zones - using fallback analysis for zones")
            # Try absolute import first, then relative
            try:
                from llm_pattern_detector import LLMPatternDetector
            except ImportError:
                from .llm_pattern_detector import LLMPatternDetector
            detector = LLMPatternDetector()
            fallback_analysis = detector._create_fallback_analysis(df, symbol)
            
            # Add zones from fallback to the LLM analysis
            fallback_zones = fallback_analysis.get('zones', [])
            if fallback_zones:
                analysis['zones'] = fallback_zones
                logger.info(f"✅ Added {len(fallback_zones)} zones from fallback analysis")
            
            # Also add other indicators from fallback if not present
            if not analysis.get('smc_data'):
                analysis['smc_data'] = fallback_analysis.get('smc_data', {})
            if not analysis.get('liquidity_sweeps_data'):
                analysis['liquidity_sweeps_data'] = fallback_analysis.get('liquidity_sweeps_data', {})
            if not analysis.get('macd_data'):
                analysis['macd_data'] = fallback_analysis.get('macd_data', {})
            
            logger.info(f"✅ Enhanced LLM analysis with fallback zones and indicators")
        
        # If LLM didn't detect any zones or patterns at all, replace entire analysis
        elif zones_count == 0 and patterns_count == 0:
            logger.warning("⚠️  LLM detected nothing - using complete fallback analysis")
            # Try absolute import first, then relative
            try:
                from llm_pattern_detector import LLMPatternDetector
            except ImportError:
                from .llm_pattern_detector import LLMPatternDetector
            detector = LLMPatternDetector()
            analysis = detector._create_fallback_analysis(df, symbol)
            logger.info(f"Fallback detected {len(analysis.get('patterns', []))} patterns and {len(analysis.get('zones', []))} zones")
            logger.info(f"Fallback detected {len(analysis.get('fvg_zones', []))} FVG zones")
        
        # CRITICAL FIX: If LLM didn't generate FVG zones, add them from fallback analysis
        elif fvg_zones_count == 0:
            logger.warning("⚠️  LLM didn't generate FVG zones - adding from fallback analysis")
            # Try absolute import first, then relative
            try:
                from llm_pattern_detector import LLMPatternDetector
            except ImportError:
                from .llm_pattern_detector import LLMPatternDetector
            detector = LLMPatternDetector()
            fallback_analysis = detector._create_fallback_analysis(df, symbol)
            
            # Add FVG zones from fallback to the LLM analysis
            fallback_fvg_zones = fallback_analysis.get('fvg_zones', [])
            if fallback_fvg_zones:
                analysis['fvg_zones'] = fallback_fvg_zones
                logger.info(f"✅ Added {len(fallback_fvg_zones)} FVG zones from fallback analysis")
            else:
                logger.info("ℹ️  No FVG zones found in fallback analysis either")
            
            # CRITICAL FIX: Also add SMC data from fallback analysis
            fallback_smc_data = fallback_analysis.get('smc_data', {})
            if fallback_smc_data:
                analysis['smc_data'] = fallback_smc_data
                logger.info(f"✅ Added SMC data from fallback analysis")
                logger.info(f"   Swing structures: {len(fallback_smc_data.get('swing_structure', []))}")
                logger.info(f"   Internal structures: {len(fallback_smc_data.get('internal_structure', []))}")
                logger.info(f"   Swing order blocks: {len(fallback_smc_data.get('swing_obs', []))}")
                logger.info(f"   Internal order blocks: {len(fallback_smc_data.get('internal_obs', []))}")
            else:
                logger.info("ℹ️  No SMC data found in fallback analysis")
        
        # Step 3: Build drawing JSON from LLM analysis
        logger.info("Step 3: Building drawing instructions from LLM analysis...")
        
        # Use the new LLM-specific builder function
        drawings = build_drawing_json_from_llm(symbol, analysis)
        
        # Add validation summary to result
        zones = analysis.get('zones', [])
        valid_zones = [z for z in zones if z.get('validation', {}).get('all_criteria_met', False)]
        
        # Calculate validation statistics
        validation_stats = {
            'total_zones': len(zones),
            'valid_zones': len(valid_zones),
            'zones_with_validation': [z.get('type') for z in zones if z.get('validation', {}).get('all_criteria_met', False)],
            'validation_details': zones
        }
        
        result = {
            'symbol': symbol,
            'total_drawings': len(drawings),
            'drawings': drawings,
            'candles': candles_data,  # Include fetched candles data
            'total_candles': len(candles_data),
            'llm_summary': analysis.get('summary', ''),
            'analysis_method': 'LLM-powered (AI)',
            'data_source': data_source,  # Track where data came from
            'confidence': 'high',
            'validation_summary': validation_stats
        }
        
        logger.info(f"✅ Successfully generated {len(drawings)} LLM-powered drawings for {symbol}")
        logger.info(f"✅ Returning {len(candles_data)} candles data")
        logger.info(f"✅ Zone validation: {len(valid_zones)}/{len(zones)} valid zones")
        return result
    
    except Exception as e:
        logger.error(f"Error in LLM drawing generation: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            'symbol': symbol,
            'error': str(e),
            'total_drawings': 0,
            'drawings': []
        }


# CLI interface
if __name__ == "__main__":
    import sys
    import json
    from datetime import datetime
    
    if len(sys.argv) < 2:
        print("Usage: python llm_drawing_generator.py <SYMBOL>")
        print("Example: python llm_drawing_generator.py ONGC.NS")
        sys.exit(1)
    
    symbol = sys.argv[1]
    
    # API configuration
    api_config = {
        'base_url': 'http://192.168.0.126:8000',
        'from_date': '2025-01-01',
        'to_date': '2026-03-03',
        'market': 'stocks'
    }
    
    print(f"\n{'='*70}")
    print(f"LLM-Powered Drawing Generation for {symbol}")
    print(f"{'='*70}\n")
    
    result = generate_drawings_with_llm(symbol, "1d", use_api=True, api_config=api_config)
    
    if 'error' not in result:
        print(f"✅ Generated {result['total_drawings']} drawings")
        print(f"\nLLM Summary: {result.get('llm_summary', 'N/A')}")
        
        # Print validation summary
        validation = result.get('validation_summary', {})
        if validation:
            print(f"\n📊 Zone Validation Summary:")
            print(f"   Total zones detected: {validation.get('total_zones', 0)}")
            print(f"   Valid zones (all criteria met): {validation.get('valid_zones', 0)}")
            print(f"   Valid zone types: {', '.join(validation.get('zones_with_validation', [])) if validation.get('zones_with_validation') else 'None'}")
        
        # Save to file
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = f"drawings_{symbol}_LLM_{timestamp}.json"
        with open(output_file, 'w') as f:
            json.dump(result, f, indent=2)
        
        print(f"\n📁 Saved to: {output_file}")
    else:
        print(f"❌ Error: {result['error']}")
