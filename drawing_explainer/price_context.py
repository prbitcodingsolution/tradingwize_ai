"""Turns raw candle data into a compact, LLM-ready price-context summary.

The LLM can't reason over 5,000 raw candles — it'd blow context and the
relevant signal is buried. We boil candles down to:

  - Aggregate stats (chart high/low, ATR-like volatility)
  - Detected swing highs/lows (local-extrema, configurable lookback)
  - A focused recent window of OHLC bars centred on the decision candle
  - Touch counts on each swing (how many times price re-tested it)

These are the landmarks the LLM uses to decide if a user's trendline is
anchored on a real swing or drawn through random noise.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _epoch_to_iso(t: Optional[int]) -> Optional[str]:
    if t is None:
        return None
    try:
        return datetime.fromtimestamp(int(t), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    except (TypeError, ValueError, OSError):
        return None


def detect_swings(
    candles: List[Dict[str, Any]],
    *,
    window: int = 5,
) -> List[Dict[str, Any]]:
    """Return swing highs/lows using a strict local-extrema test.

    A candle at index `i` is a swing high if its `high` is the max in the
    window `[i-window, i+window]`. Same logic for lows.
    """
    n = len(candles)
    if n < 2 * window + 1:
        return []

    swings: List[Dict[str, Any]] = []
    for i in range(window, n - window):
        h = candles[i]["high"]
        l = candles[i]["low"]
        is_high = all(candles[j]["high"] <= h for j in range(i - window, i + window + 1) if j != i)
        is_low = all(candles[j]["low"] >= l for j in range(i - window, i + window + 1) if j != i)

        if is_high:
            swings.append({
                "kind": "high",
                "index": i,
                "price": round(h, 6),
                "time": _epoch_to_iso(candles[i]["time"]),
            })
        if is_low:
            swings.append({
                "kind": "low",
                "index": i,
                "price": round(l, 6),
                "time": _epoch_to_iso(candles[i]["time"]),
            })

    return swings


def _count_touches(
    candles: List[Dict[str, Any]],
    price: float,
    tolerance: float,
    *,
    after_index: int = 0,
) -> int:
    """How many later candles' wicks come within `tolerance` of `price`."""
    n = 0
    for c in candles[after_index + 1:]:
        if c["low"] - tolerance <= price <= c["high"] + tolerance:
            n += 1
    return n


def _atr_like(candles: List[Dict[str, Any]], period: int = 14) -> float:
    """Average true-range proxy: mean of `(high-low)` over the last N bars."""
    sample = candles[-period:] if len(candles) > period else candles
    if not sample:
        return 0.0
    return sum(c["high"] - c["low"] for c in sample) / len(sample)


def build_price_context(
    candles: List[Dict[str, Any]],
    *,
    decision_time_t: Optional[int] = None,
    recent_window: int = 80,
    swing_lookback: int = 5,
    max_swings: int = 30,
) -> Optional[Dict[str, Any]]:
    """Return an LLM-ready price-context dict, or None if no candles.

    Args:
      candles: full candle list for the question's pair/timeframe/date-range.
      decision_time_t: epoch-seconds of the candle the question was decided on
        (`user_answer.current_data.question.time / 1000`). When given, the
        recent window is centred just before this candle so the LLM sees the
        same view the student did.
      recent_window: how many bars to expose verbatim.
      swing_lookback: lookback used for swing detection.
      max_swings: cap on swing list (newest preferred).
    """
    if not candles:
        return None

    n = len(candles)
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]

    overall_high = max(highs)
    overall_low = min(lows)
    overall_high_idx = highs.index(overall_high)
    overall_low_idx = lows.index(overall_low)

    avg_range = _atr_like(candles, period=14)
    swings_all = detect_swings(candles, window=swing_lookback)

    # Touch counts so the LLM knows which swings were retested (= stronger).
    tolerance = avg_range * 0.25 if avg_range else 0.0
    for s in swings_all:
        s["retests"] = _count_touches(candles, s["price"], tolerance, after_index=s["index"])

    # Keep the newest `max_swings` since recent structure dominates trade decisions.
    swings = swings_all[-max_swings:] if len(swings_all) > max_swings else swings_all

    # Decision candle resolution.
    decision_idx: Optional[int] = None
    if decision_time_t is not None:
        for i, c in enumerate(candles):
            if c["time"] >= decision_time_t:
                decision_idx = i
                break

    if decision_idx is not None:
        start = max(0, decision_idx - recent_window)
        end = min(n, decision_idx + 1)
    else:
        start = max(0, n - recent_window)
        end = n

    recent = [
        {
            "i": i,
            "time": _epoch_to_iso(candles[i]["time"]),
            "o": round(candles[i]["open"], 6),
            "h": round(candles[i]["high"], 6),
            "l": round(candles[i]["low"], 6),
            "c": round(candles[i]["close"], 6),
        }
        for i in range(start, end)
    ]

    # Most-recent swing high/low — landmarks the LLM should reference for
    # stop placement and trend direction.
    last_swing_high = next(
        (s for s in reversed(swings_all) if s["kind"] == "high"), None
    )
    last_swing_low = next(
        (s for s in reversed(swings_all) if s["kind"] == "low"), None
    )

    return {
        "candle_count": n,
        "first_candle_time": _epoch_to_iso(candles[0]["time"]),
        "last_candle_time": _epoch_to_iso(candles[-1]["time"]),
        "overall_high": {
            "price": round(overall_high, 6),
            "index": overall_high_idx,
            "time": _epoch_to_iso(candles[overall_high_idx]["time"]),
        },
        "overall_low": {
            "price": round(overall_low, 6),
            "index": overall_low_idx,
            "time": _epoch_to_iso(candles[overall_low_idx]["time"]),
        },
        "avg_range_14": round(avg_range, 6),
        "swing_count": len(swings_all),
        "swings_recent": swings,
        "last_swing_high": last_swing_high,
        "last_swing_low": last_swing_low,
        "decision_index": decision_idx,
        "recent_window": recent,
    }
