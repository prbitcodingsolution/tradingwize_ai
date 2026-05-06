"""
TradingView Trade Ideas & Minds Scraper
Scrapes top trading ideas and community minds/insights from TradingView.
Runs Playwright in a subprocess to avoid Python 3.14/Windows asyncio compatibility issues.

Supports:
  Ideas:
  - Stocks:  exchange="NSE"  → https://www.tradingview.com/symbols/NSE-TCS/ideas/
  - Forex:   exchange=""     → https://www.tradingview.com/symbols/XAUUSD/ideas/
  - Crypto:  exchange=""     → https://www.tradingview.com/symbols/BTCUSD/ideas/

  Minds (community insights with chart images only):
  - https://www.tradingview.com/symbols/NSE-JIOFIN/minds/
"""

import re
import time
import json
import subprocess
import sys
import os
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import List, Dict

# Path to the actual scraper script that runs in a subprocess
_SCRAPER_SCRIPT = os.path.join(os.path.dirname(__file__), "_tradingview_worker.py")

# Cache results for 10 minutes
_cache = {}
_cache_ttl = 600

# Sentinel used when we cannot parse an idea's time_posted — these end up
# at the bottom of the time-sorted list.
_UNKNOWN_TIME = datetime.min.replace(tzinfo=timezone.utc)


def _build_tv_symbol(symbol: str, exchange: str) -> str:
    """
    Build TradingView URL symbol path.
    Stocks:  "NSE-TCS"   (exchange prefix)
    Forex:   "XAUUSD"    (no prefix)
    Crypto:  "BTCUSD"    (no prefix)
    """
    if exchange:
        return f"{exchange}-{symbol}"
    return symbol


def _parse_time_posted(time_str: str) -> datetime:
    """
    Parse a TradingView idea/mind `time_posted` into a timezone-aware
    datetime suitable for descending sort and recency filtering.

    Accepts three shapes the worker can emit:
      1. ISO 8601 (e.g. "2026-04-13T08:12:34.000Z") — used on some
         TradingView pages for the <time datetime="..."> attribute.
      2. RFC 2822 (e.g. "Wed, 12 Nov 2025 07:45:40 GMT") — observed
         in the live DOM on /minds/ pages. THIS is the shape minds
         actually emit; missing this format silently dropped every mind
         as "unparseable" when the recency filter ran.
      3. Human text fallback (e.g. "2 hours ago", "a day ago",
         "just now") for the very rare case a `<time>` element has
         only a text child with no datetime attribute.

    Unparseable values return `_UNKNOWN_TIME` (year 0001) so they sink
    to the bottom of sorts and are dropped by recency filters rather
    than crashing the pipeline.
    """
    if not time_str or not isinstance(time_str, str):
        return _UNKNOWN_TIME

    time_str = time_str.strip()
    if not time_str:
        return _UNKNOWN_TIME

    # --- Path 1: ISO 8601 ---
    # fromisoformat in Python 3.11+ understands the trailing Z, but fall
    # back to an explicit replace for older interpreters and to catch
    # fractional seconds in non-standard formats.
    iso_candidate = time_str.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso_candidate)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass

    # --- Path 2: RFC 2822 (the format TradingView /minds/ actually uses) ---
    # Examples: "Wed, 12 Nov 2025 07:45:40 GMT"
    #           "Wed, 12 Nov 2025 07:45:40 +0000"
    # parsedate_to_datetime raises (TypeError, ValueError, IndexError)
    # depending on the failure mode — catch broadly.
    if "," in time_str and any(ch.isalpha() for ch in time_str):
        try:
            dt = parsedate_to_datetime(time_str)
            if dt is not None:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
        except (TypeError, ValueError, IndexError):
            pass

    # --- Path 3: relative-time text fallback ---
    now = datetime.now(timezone.utc)
    lowered = time_str.lower()

    if lowered in ("just now", "now", "moments ago", "a moment ago"):
        return now

    # Numeric form: "<N> <unit> ago"
    match = re.match(
        r"(\d+)\s*(second|minute|hour|day|week|month|year)s?\s*ago",
        lowered,
    )
    if match:
        num = int(match.group(1))
        unit = match.group(2)
    else:
        # Singular form: "a minute ago" / "an hour ago"
        match = re.match(
            r"(?:a|an)\s+(second|minute|hour|day|week|month|year)\s+ago",
            lowered,
        )
        if not match:
            return _UNKNOWN_TIME
        num = 1
        unit = match.group(1)

    unit_to_delta = {
        "second": timedelta(seconds=num),
        "minute": timedelta(minutes=num),
        "hour": timedelta(hours=num),
        "day": timedelta(days=num),
        "week": timedelta(weeks=num),
        "month": timedelta(days=num * 30),  # approximation
        "year": timedelta(days=num * 365),  # approximation
    }
    return now - unit_to_delta[unit]


def _sort_ideas_by_time_desc(ideas: List[Dict]) -> List[Dict]:
    """Sort ideas newest-first by parsed `time_posted`."""
    return sorted(
        ideas,
        key=lambda idea: _parse_time_posted(idea.get("time_posted", "")),
        reverse=True,
    )


def _filter_within_last_days(items: List[Dict], days: int) -> List[Dict]:
    """
    Keep only items whose `time_posted` parses to within the last `days`
    days. Items with an unparseable `time_posted` are DROPPED — we can't
    verify they're recent so we err on the side of exclusion.

    Used to scope TradingView minds to "posted in the last month" without
    showing stale community chatter.
    """
    if days <= 0:
        return list(items)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    kept: List[Dict] = []
    for item in items:
        parsed = _parse_time_posted(item.get("time_posted", ""))
        # Drop unknown/unparseable timestamps — _UNKNOWN_TIME is year 0001.
        if parsed == _UNKNOWN_TIME:
            continue
        if parsed >= cutoff:
            kept.append(item)
    return kept


def scrape_trade_ideas(symbol: str, exchange: str = "NSE", max_ideas: int = 9) -> Dict:
    """
    Scrape trade ideas from TradingView with caching.
    Launches Playwright in a subprocess to avoid event loop issues.

    Args:
        symbol: Ticker symbol (e.g., "TCS", "RELIANCE", "XAUUSD", "BTCUSD")
        exchange: Exchange name (e.g., "NSE", "NASDAQ"). Use "" for forex/crypto.
        max_ideas: Maximum ideas to return (default: 9)

    Returns:
        Dict with symbol, ideas list, and metadata
    """
    clean_symbol = symbol.split('.')[0].upper()
    tv_symbol = _build_tv_symbol(clean_symbol, exchange)
    cache_key = tv_symbol

    # Check cache
    if cache_key in _cache:
        cached_time, cached_data = _cache[cache_key]
        if time.time() - cached_time < _cache_ttl:
            print(f"Cache hit for {cache_key} trade ideas")
            return cached_data

    print(f"Scraping trade ideas for {cache_key}...")

    # Ask the worker for a larger pool than the user requested so we have
    # enough items to sort by recency. TradingView's /ideas/ page is
    # popularity-sorted by default, so if we only fetched `max_ideas`
    # cards we'd be sorting the top-N-popular ideas by time — not the
    # actual N latest. Fetching ~3x (floor of 25) gives a reasonable
    # pool without slowing the scrape materially.
    fetch_count = max(max_ideas * 3, 25)

    try:
        # Run Playwright in a clean subprocess to avoid asyncio issues
        result = subprocess.run(
            [sys.executable, _SCRAPER_SCRIPT, clean_symbol, exchange, str(fetch_count)],
            capture_output=True,
            text=True,
            timeout=90,
            cwd=os.path.dirname(os.path.dirname(__file__))
        )

        # Always surface any worker stderr — the worker prints
        # diagnostics (article count, consent banners, region blocks)
        # when it couldn't extract any cards. Without this the parent
        # only sees "Found 0 trade ideas" and has no idea why.
        if result.stderr and result.stderr.strip():
            _err_head = result.stderr.strip().splitlines()[-5:]
            for _line in _err_head:
                print(f"[worker] {_line}")

        if result.returncode == 0 and result.stdout.strip():
            ideas = json.loads(result.stdout.strip())
        else:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            print(f"Scraper subprocess failed: {error_msg}")
            ideas = []

        # Sort newest-first by parsed time_posted, then trim to the
        # caller's requested size.
        if ideas:
            ideas = _sort_ideas_by_time_desc(ideas)
        trimmed_ideas = ideas[:max_ideas]

        output = {
            "symbol": clean_symbol,
            "exchange": exchange,
            "ideas": trimmed_ideas,
            "count": len(trimmed_ideas),
            "url": f"https://www.tradingview.com/symbols/{tv_symbol}/ideas/",
            "cached": False,
            "error": None if ideas else "No ideas found"
        }

        # Cache only successful results
        if ideas:
            _cache[cache_key] = (time.time(), output)

        print(f"Found {len(ideas)} trade ideas for {cache_key} "
              f"(returning {len(trimmed_ideas)} newest)")
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
    tv_symbol = _build_tv_symbol(symbol, exchange)
    return {
        "symbol": symbol,
        "exchange": exchange,
        "ideas": [],
        "count": 0,
        "url": f"https://www.tradingview.com/symbols/{tv_symbol}/ideas/",
        "cached": False,
        "error": error
    }


def scrape_tradingview_minds(
    symbol: str,
    exchange: str = "NSE",
    max_minds: int = 9,
    recency_days: int = 30,
) -> Dict:
    """
    Scrape minds/insights from TradingView — only posts with chart images.
    URL: https://www.tradingview.com/symbols/{exchange}-{symbol}/minds/

    Minds older than `recency_days` (default 30) are dropped, so the
    caller always sees community chatter from within the last month.
    Items whose `time_posted` cannot be parsed are also dropped to avoid
    silently showing stale content.

    Args:
        symbol: Ticker symbol (e.g., "TCS", "JIOFIN")
        exchange: Exchange name (e.g., "NSE"). Use "" for forex/crypto.
        max_minds: Maximum minds to return after filtering (default: 9)
        recency_days: Only keep minds posted within this many days
                      (default: 30 = last month). Pass 0 to disable.

    Returns:
        Dict with symbol, minds list (only those with images and within
        the recency window, newest-first), and metadata.
    """
    clean_symbol = symbol.split('.')[0].upper()
    tv_symbol = _build_tv_symbol(clean_symbol, exchange)
    cache_key = f"{tv_symbol}_minds"

    # Check cache
    if cache_key in _cache:
        cached_time, cached_data = _cache[cache_key]
        if time.time() - cached_time < _cache_ttl:
            print(f"Cache hit for {cache_key}")
            return cached_data

    print(f"Scraping TradingView minds for {tv_symbol} "
          f"(last {recency_days}d)...")

    # Over-fetch from the worker so the recency filter still has enough
    # to work with. A month's worth of recent minds is often mixed in
    # with older posts on the page, so we ask for ~4x what we need and
    # trim after filtering + sorting.
    fetch_count = max(max_minds * 4, 40)

    try:
        result = subprocess.run(
            [sys.executable, _SCRAPER_SCRIPT, clean_symbol, exchange, str(fetch_count), "minds"],
            capture_output=True,
            text=True,
            timeout=90,
            cwd=os.path.dirname(os.path.dirname(__file__))
        )

        if result.returncode == 0 and result.stdout.strip():
            minds = json.loads(result.stdout.strip())
        else:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            print(f"Minds scraper subprocess failed: {error_msg}")
            minds = []

        raw_count = len(minds)

        # Filter to recency window, then sort newest-first, then trim.
        if minds and recency_days > 0:
            minds = _filter_within_last_days(minds, recency_days)
        if minds:
            minds = _sort_ideas_by_time_desc(minds)
        trimmed_minds = minds[:max_minds]

        if raw_count and not trimmed_minds:
            error = (f"No minds posted within the last {recency_days} days "
                     f"({raw_count} older minds were filtered out)")
        elif not raw_count:
            error = "No minds with images found"
        else:
            error = None

        output = {
            "symbol": clean_symbol,
            "exchange": exchange,
            "minds": trimmed_minds,
            "count": len(trimmed_minds),
            "url": f"https://www.tradingview.com/symbols/{tv_symbol}/minds/",
            "recency_days": recency_days,
            "cached": False,
            "error": error,
        }

        if trimmed_minds:
            _cache[cache_key] = (time.time(), output)

        print(f"Found {raw_count} minds for {tv_symbol}, "
              f"{len(trimmed_minds)} within last {recency_days}d")
        return output

    except subprocess.TimeoutExpired:
        print(f"Minds scraper timed out for {tv_symbol}")
        return _minds_error_result(clean_symbol, exchange, "Scraping timed out (90s)")
    except json.JSONDecodeError as e:
        print(f"Failed to parse minds scraper output for {tv_symbol}: {e}")
        return _minds_error_result(clean_symbol, exchange, f"Parse error: {e}")
    except Exception as e:
        print(f"Error scraping minds for {tv_symbol}: {e}")
        return _minds_error_result(clean_symbol, exchange, str(e))


def _minds_error_result(symbol: str, exchange: str, error: str) -> Dict:
    tv_symbol = _build_tv_symbol(symbol, exchange)
    return {
        "symbol": symbol,
        "exchange": exchange,
        "minds": [],
        "count": 0,
        "url": f"https://www.tradingview.com/symbols/{tv_symbol}/minds/",
        "cached": False,
        "error": error
    }


def clear_cache(symbol: str = None, exchange: str = "NSE"):
    """Clear cached trade ideas and minds. If symbol is None, clear all."""
    if symbol:
        clean_symbol = symbol.split('.')[0].upper()
        cache_key = _build_tv_symbol(clean_symbol, exchange)
        _cache.pop(cache_key, None)
        _cache.pop(f"{cache_key}_minds", None)
    else:
        _cache.clear()
