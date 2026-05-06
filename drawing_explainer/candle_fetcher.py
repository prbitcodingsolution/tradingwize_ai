"""Fetches OHLCV candlestick data for one pair/timeframe/date-range from
`/api/v1/mentor/get-forex-data/` on the LMS.

This is what gives the LLM ground truth to validate the user's drawings
against — without it the model is just guessing whether a trendline is
anchored on a real swing or not.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from .api_client import DEFAULT_BASE_URL

logger = logging.getLogger(__name__)


# Map drawing-API `market_name` values to candle-API `market` param values.
_MARKET_MAP = {
    "FX": "forex",
    "Forex": "forex",
    "Stocks": "stocks",
    "Stock": "stocks",
    "Crypto": "crypto",
    "Cryptocurrency": "crypto",
}


def market_for(market_name: Optional[str]) -> str:
    if not market_name:
        return "stocks"
    return _MARKET_MAP.get(market_name, market_name.lower())


def isodate_to_ymd(iso: str) -> str:
    """`'2024-01-01T00:00:00'` → `'2024-01-01'`."""
    if not iso:
        return ""
    return iso.split("T")[0] if "T" in iso else iso


def _headers(bearer_token: Optional[str]) -> Dict[str, str]:
    h = {"Accept": "application/json"}
    if bearer_token:
        h["Authorization"] = f"Bearer {bearer_token}"
    return h


def fetch_candles(
    *,
    pair: str,
    from_date: str,
    to_date: str,
    timeframe: str,
    market: str = "stocks",
    base_url: str = DEFAULT_BASE_URL,
    bearer_token: Optional[str] = None,
    timeout: int = 30,
    verify_ssl: bool = False,
) -> List[Dict[str, Any]]:
    """GET `/api/v1/mentor/get-forex-data/` and return a list of normalized
    candle dicts: `{time (epoch sec), open, high, low, close, volume}`.

    Returns `[]` rather than raising when the endpoint says "no data" so a
    single missing question doesn't fail the whole session.
    """
    bearer_token = bearer_token or os.getenv("DRAWING_EXPLAINER_BEARER_TOKEN")

    url = f"{base_url.rstrip('/')}/api/v1/mentor/get-forex-data/"
    params = {
        "pair": pair,
        "from": from_date,
        "to": to_date,
        "market": market,
        "timeframe": timeframe,
    }
    logger.info("Fetching candles: %s %s", url, params)

    try:
        resp = requests.get(
            url,
            params=params,
            headers=_headers(bearer_token),
            timeout=timeout,
            verify=verify_ssl,
        )
        resp.raise_for_status()
        payload = resp.json()
    except requests.HTTPError as exc:
        logger.warning("Candle fetch HTTP %s for %s: %s", exc.response.status_code, pair, exc)
        return []
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Candle fetch failed for %s: %s", pair, exc)
        return []

    raw = payload.get("data") if isinstance(payload, dict) else payload
    if not raw:
        logger.info("No candle data returned for %s", pair)
        return []

    return [_normalize(c) for c in raw]


def _normalize(c: Dict[str, Any]) -> Dict[str, Any]:
    """Accept both `time/open/high/...` and `t/o/h/l/c/v` shapes; return a
    plain dict with epoch-second `time` and float OHLCV."""
    def _pick(keys, default=0):
        for k in keys:
            if k in c and c[k] is not None:
                return c[k]
        return default

    time_val = _pick(["time", "timestamp", "t", "date"], None)
    if time_val is None:
        return {"time": 0, "open": 0.0, "high": 0.0, "low": 0.0, "close": 0.0, "volume": 0.0}

    if isinstance(time_val, (int, float)):
        # ms → s if it looks like milliseconds
        time_val = int(time_val // 1000) if time_val > 10**12 else int(time_val)
    elif isinstance(time_val, str):
        try:
            time_val = int(datetime.fromisoformat(time_val.replace("Z", "+00:00")).timestamp())
        except ValueError:
            time_val = 0

    return {
        "time": int(time_val),
        "open": float(_pick(["open", "o", "Open"], 0)),
        "high": float(_pick(["high", "h", "High"], 0)),
        "low": float(_pick(["low", "l", "Low"], 0)),
        "close": float(_pick(["close", "c", "Close"], 0)),
        "volume": float(_pick(["volume", "v", "Volume", "vol"], 0)),
    }
