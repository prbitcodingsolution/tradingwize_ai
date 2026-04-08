"""
TradingView Trade Ideas Scraper
Scrapes top trading ideas from TradingView for a given stock symbol using Playwright.
Runs Playwright in a subprocess to avoid Python 3.14/Windows asyncio compatibility issues.
"""

import time
import json
import subprocess
import sys
import os
from typing import List, Dict

# Path to the actual scraper script that runs in a subprocess
_SCRAPER_SCRIPT = os.path.join(os.path.dirname(__file__), "_tradingview_worker.py")

# Cache results for 10 minutes
_cache = {}
_cache_ttl = 600


def scrape_trade_ideas(symbol: str, exchange: str = "NSE", max_ideas: int = 9) -> Dict:
    """
    Scrape trade ideas from TradingView with caching.
    Launches Playwright in a subprocess to avoid event loop issues.

    Args:
        symbol: Stock ticker without exchange suffix (e.g., "TCS", "RELIANCE")
        exchange: Exchange name (default: "NSE")
        max_ideas: Maximum ideas to return (default: 9)

    Returns:
        Dict with symbol, ideas list, and metadata
    """
    clean_symbol = symbol.split('.')[0].upper()
    cache_key = f"{exchange}-{clean_symbol}"

    # Check cache
    if cache_key in _cache:
        cached_time, cached_data = _cache[cache_key]
        if time.time() - cached_time < _cache_ttl:
            print(f"Cache hit for {cache_key} trade ideas")
            return cached_data

    print(f"Scraping trade ideas for {cache_key}...")

    try:
        # Run Playwright in a clean subprocess to avoid asyncio issues
        result = subprocess.run(
            [sys.executable, _SCRAPER_SCRIPT, clean_symbol, exchange, str(max_ideas)],
            capture_output=True,
            text=True,
            timeout=90,
            cwd=os.path.dirname(os.path.dirname(__file__))
        )

        if result.returncode == 0 and result.stdout.strip():
            ideas = json.loads(result.stdout.strip())
        else:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            print(f"Scraper subprocess failed: {error_msg}")
            ideas = []

        output = {
            "symbol": clean_symbol,
            "exchange": exchange,
            "ideas": ideas[:max_ideas],
            "count": len(ideas[:max_ideas]),
            "url": f"https://www.tradingview.com/symbols/{exchange}-{clean_symbol}/ideas/",
            "cached": False,
            "error": None if ideas else "No ideas found"
        }

        # Cache only successful results
        if ideas:
            _cache[cache_key] = (time.time(), output)

        print(f"Found {len(ideas)} trade ideas for {cache_key}")
        return output

    except subprocess.TimeoutExpired:
        print(f"Scraper timed out for {cache_key}")
        return _error_result(clean_symbol, exchange, "Scraping timed out (90s)")
    except json.JSONDecodeError as e:
        print(f"Failed to parse scraper output for {cache_key}: {e}")
        return _error_result(clean_symbol, exchange, f"Parse error: {e}")
    except Exception as e:
        print(f"Error scraping trade ideas for {cache_key}: {e}")
        return _error_result(clean_symbol, exchange, str(e))


def _error_result(symbol: str, exchange: str, error: str) -> Dict:
    return {
        "symbol": symbol,
        "exchange": exchange,
        "ideas": [],
        "count": 0,
        "url": f"https://www.tradingview.com/symbols/{exchange}-{symbol}/ideas/",
        "cached": False,
        "error": error
    }


def clear_cache(symbol: str = None, exchange: str = "NSE"):
    """Clear cached trade ideas. If symbol is None, clear all."""
    if symbol:
        cache_key = f"{exchange}-{symbol.split('.')[0].upper()}"
        _cache.pop(cache_key, None)
    else:
        _cache.clear()
