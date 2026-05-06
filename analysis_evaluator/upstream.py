"""Fetch candles and student drawings from the LMS upstream APIs."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests

from .models import Candle

logger = logging.getLogger(__name__)


# Map drawings-API `market_name` to candles-API `market` param
_MARKET_MAP = {
    "FX": "forex",
    "Forex": "forex",
    "Stocks": "stocks",
    "Stock": "stocks",
    "Crypto": "crypto",
    "Cryptocurrency": "crypto",
}


def _headers(bearer: Optional[str], csrf: Optional[str]) -> Dict[str, str]:
    h = {"accept": "application/json"}
    if bearer:
        h["authorization"] = f"Bearer {bearer}"
    if csrf:
        h["X-CSRFToken"] = csrf
    return h


def fetch_drawings(
    base_url: str,
    *,
    category: str,
    sub_category: str,
    type: str,
    date: str,
    chapter_id: int,
    user_type: str = "student",
    is_challenge_only: bool = True,
    question_id: Optional[int] = None,
    bearer_token: Optional[str] = None,
    csrf_token: Optional[str] = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    """GET /api/v1/learning/result-screenshot-view/ — returns one drawing record.

    The endpoint may return either:
      - a single object (the shape shown in `drawing_instruction/find.py`), or
      - a list / paginated wrapper (`{"results": [...]}` / `{"data": [...]}`)
    We unwrap to the first item that looks like a real chart record.
    """
    url = f"{base_url.rstrip('/')}/api/v1/learning/result-screenshot-view/"
    params = {
        "category": category,
        "sub_category": sub_category,
        "type": type,
        "date": date,
        "chapter_id": chapter_id,
        "user_type": user_type,
        "is_challenge_only": str(is_challenge_only).lower(),
    }
    logger.info("Fetching drawings: %s %s", url, params)
    resp = requests.get(url, params=params, headers=_headers(bearer_token, csrf_token), timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    return _unwrap_drawing_record(payload, question_id=question_id)


def _unwrap_drawing_record(payload: Any, *, question_id: Optional[int] = None) -> Dict[str, Any]:
    """Return one chart record from a possibly-wrapped LMS response.

    The result-screenshot-view endpoint returns a session wrapper:
      `{ id, content_title, ..., questions: [ {pair, timeframe, ...}, ... ] }`
    where each item in `questions` is the chart record we actually evaluate.
    Older / alternative shapes are also handled (single dict, list, results-wrapper).
    """
    def has_meta(d: Any) -> bool:
        return isinstance(d, dict) and "pair" in d and "timeframe" in d

    # Already a chart record
    if has_meta(payload):
        return payload

    # Bare list of chart records
    if isinstance(payload, list):
        for item in payload:
            if has_meta(item):
                return item
        raise ValueError(
            f"Drawings list contained no record with chart metadata. "
            f"Got {len(payload)} items; first item keys: "
            f"{list(payload[0].keys()) if payload and isinstance(payload[0], dict) else 'n/a'}"
        )

    if isinstance(payload, dict):
        # Session wrapper: choose a question by `id`, else the first valid one
        questions = payload.get("questions")
        if isinstance(questions, list) and questions:
            if question_id is not None:
                for q in questions:
                    if isinstance(q, dict) and q.get("id") == question_id:
                        if not has_meta(q):
                            raise ValueError(
                                f"Question id={question_id} found but missing chart metadata "
                                f"(pair/timeframe). Keys: {list(q.keys())}"
                            )
                        return q
                raise ValueError(
                    f"question_id={question_id} not found. Available ids: "
                    f"{[q.get('id') for q in questions if isinstance(q, dict)]}"
                )
            for q in questions:
                if has_meta(q):
                    return q
            raise ValueError(
                f"`questions` array has {len(questions)} entries but none carry chart metadata. "
                f"First item keys: {list(questions[0].keys()) if isinstance(questions[0], dict) else 'n/a'}"
            )

        # Generic paginated wrappers
        for key in ("results", "data", "items", "records"):
            inner = payload.get(key)
            if isinstance(inner, list):
                for item in inner:
                    if has_meta(item):
                        return item
            elif has_meta(inner):
                return inner

        raise ValueError(
            f"Drawings payload missing chart metadata. Top-level keys: {list(payload.keys())}. "
            f"Expected `pair`/`timeframe` at root, or under `questions`/`results`/`data`/`items`/`records`."
        )

    raise ValueError(f"Unexpected drawings payload type: {type(payload).__name__}")


def fetch_candles(
    base_url: str,
    *,
    pair: str,
    from_date: str,
    to_date: str,
    timeframe: str,
    market: str = "stocks",
    bearer_token: Optional[str] = None,
    csrf_token: Optional[str] = None,
    timeout: int = 30,
) -> List[Candle]:
    """GET /api/v1/mentor/get-forex-data/ — returns a list of Candle."""
    url = f"{base_url.rstrip('/')}/api/v1/mentor/get-forex-data/"
    params = {
        "pair": pair,
        "from": from_date,
        "to": to_date,
        "market": market,
        "timeframe": timeframe,
    }
    logger.info("Fetching candles: %s %s", url, params)
    resp = requests.get(url, params=params, headers=_headers(bearer_token, csrf_token), timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()

    raw = payload.get("data") if isinstance(payload, dict) else payload
    if not raw:
        raise ValueError(f"No candles returned for {pair}")

    return [_normalize_candle(c) for c in raw]


def _normalize_candle(c: Dict[str, Any]) -> Candle:
    """Accept both `time/open/high/...` and `t/o/h/l/c/v` shapes."""
    def _pick(keys: List[str], default=None):
        for k in keys:
            if k in c and c[k] is not None:
                return c[k]
        return default

    time_val = _pick(["time", "timestamp", "t", "date"])
    if time_val is None:
        raise ValueError(f"Candle missing time field: {c}")

    # Some upstreams return ms; normalize to seconds.
    if isinstance(time_val, (int, float)) and time_val > 10**12:
        time_val = int(time_val // 1000)
    elif isinstance(time_val, str):
        # ISO string → epoch seconds
        from datetime import datetime
        time_val = int(datetime.fromisoformat(time_val.replace("Z", "+00:00")).timestamp())

    return Candle(
        time=int(time_val),
        open=float(_pick(["open", "o", "Open"], 0)),
        high=float(_pick(["high", "h", "High"], 0)),
        low=float(_pick(["low", "l", "Low"], 0)),
        close=float(_pick(["close", "c", "Close"], 0)),
        volume=float(_pick(["volume", "v", "Volume", "vol"], 0)),
    )


def market_for(market_name: Optional[str]) -> str:
    if not market_name:
        return "stocks"
    return _MARKET_MAP.get(market_name, market_name.lower())


def isodate_to_ymd(iso: str) -> str:
    """`'2024-01-01T00:00:00'` → `'2024-01-01'`."""
    return iso.split("T")[0] if "T" in iso else iso
