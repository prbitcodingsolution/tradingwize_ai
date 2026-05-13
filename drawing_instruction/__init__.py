# Drawing Instruction Generator Package
"""
Auto-generates TradingView drawing instructions from price data analysis
"""

# Submodule eager-imports below pull in pandas/numpy/yfinance, which are not
# always available (e.g. slim Vercel serverless deploy). Wrap each one so the
# package still imports — consumers like `chat_drawing_agent` don't need these
# helpers, and code that does will import the submodule directly.
try:
    from .price_fetcher import fetch_price_data
except Exception:
    fetch_price_data = None

try:
    from .zone_detector import detect_supply_demand_zones
except Exception:
    detect_supply_demand_zones = None

try:
    from .pattern_detector import detect_candlestick_patterns
except Exception:
    detect_candlestick_patterns = None

try:
    from .indicator_calculator import calculate_bollinger_bands
except Exception:
    calculate_bollinger_bands = None

try:
    from .json_builder import build_drawing_json
except Exception:
    build_drawing_json = None

__all__ = [
    'fetch_price_data',
    'detect_supply_demand_zones',
    'detect_candlestick_patterns',
    'calculate_bollinger_bands',
    'build_drawing_json'
]
