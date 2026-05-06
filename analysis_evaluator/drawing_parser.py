"""Parse a TradingView `result-screenshot-view` payload into our `UserAnalysis`.

The LMS returns a full TradingView chart layout. We walk
`answer_analysis_json.charts[*].panes[*].sources[*]` and translate the few
drawing tools relevant to chart analysis (Fib, channels, zones, R:R box).
"""

from __future__ import annotations

import bisect
import logging
from typing import Any, Dict, List, Optional

from .models import (
    ChannelInput,
    ChannelLine,
    Candle,
    FibInput,
    UserAnalysis,
    ZoneInput,
)

logger = logging.getLogger(__name__)


_FIB_TYPES = {"LineToolFibRetracement", "LineToolFibTimeZone", "LineToolFibSpeedResistFan"}
_TRENDLINE_TYPES = {"LineToolTrendLine", "LineToolRay", "LineToolExtended"}
_CHANNEL_TYPES = {"LineToolParallelChannel", "LineToolDisjointAngle"}
_ZONE_TYPES = {"LineToolRectangle", "LineToolPriceRange", "LineToolRotatedRectangle"}


def parse_drawings(payload: Dict[str, Any], candles: List[Candle]) -> UserAnalysis:
    """Translate an LMS drawings payload into our internal `UserAnalysis`."""
    sources = _iter_sources(payload)
    times = [c.time for c in candles]

    fib: Optional[FibInput] = None
    channels: List[ChannelInput] = []
    zones: List[ZoneInput] = []
    trendlines: List[ChannelLine] = []  # raw — paired into channels later

    for src in sources:
        stype = src.get("type")
        points = src.get("points") or []

        if stype in _FIB_TYPES and len(points) >= 2 and fib is None:
            fib = _make_fib(points, times)

        elif stype in _CHANNEL_TYPES and len(points) >= 3:
            channels.append(_make_channel_from_parallel(points))

        elif stype in _TRENDLINE_TYPES and len(points) >= 2:
            trendlines.append(_make_line(points))

        elif stype in _ZONE_TYPES and len(points) >= 2:
            zones.append(_make_zone(points))

    # Pair stand-alone trendlines into channels (similar slope, no overlap)
    channels.extend(_pair_trendlines(trendlines))

    # Risk-reward boxes carry entry/SL/TP directly via user_answer
    direction, entry, sl, tp = _extract_trade_levels(payload, sources)

    return UserAnalysis(
        fib=fib,
        channels=channels,
        zones=zones,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        direction=direction,
    )


# ──────────────────────  TradingView walkers  ──────────────────────

def _iter_sources(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    aaj = payload.get("answer_analysis_json") or {}
    for chart in aaj.get("charts", []) or []:
        for pane in chart.get("panes", []) or []:
            for src in pane.get("sources", []) or []:
                out.append(src)
    return out


# ──────────────────────  per-tool conversion  ──────────────────────

def _make_fib(points: List[Dict[str, Any]], times: List[int]) -> FibInput:
    p0, p1 = points[0], points[1]
    return FibInput(
        start_index=_time_to_index(p0.get("time_t"), times),
        end_index=_time_to_index(p1.get("time_t"), times),
        start_price=_f(p0.get("price")),
        end_price=_f(p1.get("price")),
        start_time=_i(p0.get("time_t")),
        end_time=_i(p1.get("time_t")),
    )


def _make_line(points: List[Dict[str, Any]]) -> ChannelLine:
    p0, p1 = points[0], points[1]
    return ChannelLine(
        p1_time=_i(p0.get("time_t")) or 0,
        p1_price=_f(p0.get("price")) or 0.0,
        p2_time=_i(p1.get("time_t")) or 0,
        p2_price=_f(p1.get("price")) or 0.0,
    )


def _make_channel_from_parallel(points: List[Dict[str, Any]]) -> ChannelInput:
    # TradingView parallel channel: 3 anchor points (p0,p1 = main line; p2 = parallel offset)
    p0, p1, p2 = points[0], points[1], points[2]
    main = ChannelLine(
        p1_time=_i(p0.get("time_t")) or 0,
        p1_price=_f(p0.get("price")) or 0.0,
        p2_time=_i(p1.get("time_t")) or 0,
        p2_price=_f(p1.get("price")) or 0.0,
    )
    # Parallel line: shift main by (p2 - point_on_main_at_p2_time)
    if main.p2_time != main.p1_time:
        slope = (main.p2_price - main.p1_price) / (main.p2_time - main.p1_time)
        on_main_at_p2 = main.p1_price + slope * ((_i(p2.get("time_t")) or 0) - main.p1_time)
        offset = (_f(p2.get("price")) or 0.0) - on_main_at_p2
    else:
        offset = (_f(p2.get("price")) or 0.0) - main.p1_price

    parallel = ChannelLine(
        p1_time=main.p1_time,
        p1_price=main.p1_price + offset,
        p2_time=main.p2_time,
        p2_price=main.p2_price + offset,
    )
    upper, lower = (main, parallel) if main.p1_price + main.p2_price >= parallel.p1_price + parallel.p2_price else (parallel, main)
    return ChannelInput(upper=upper, lower=lower)


def _make_zone(points: List[Dict[str, Any]]) -> ZoneInput:
    prices = [_f(p.get("price")) or 0.0 for p in points]
    times = [_i(p.get("time_t")) or 0 for p in points]
    return ZoneInput(
        top=max(prices),
        bottom=min(prices),
        start_time=min(times) if times else None,
        end_time=max(times) if times else None,
    )


def _pair_trendlines(lines: List[ChannelLine]) -> List[ChannelInput]:
    """Best-effort pairing of trendlines into channels by slope similarity."""
    paired: List[ChannelInput] = []
    used = [False] * len(lines)
    for i, a in enumerate(lines):
        if used[i]:
            continue
        sa = _slope(a)
        for j in range(i + 1, len(lines)):
            if used[j]:
                continue
            b = lines[j]
            sb = _slope(b)
            if sa is None or sb is None:
                continue
            denom = max(abs(sa), abs(sb), 1e-9)
            if abs(sa - sb) / denom < 0.15:  # within 15% slope diff = parallel
                upper, lower = (a, b) if (a.p1_price + a.p2_price) >= (b.p1_price + b.p2_price) else (b, a)
                paired.append(ChannelInput(upper=upper, lower=lower))
                used[i] = used[j] = True
                break
    return paired


def _extract_trade_levels(payload: Dict[str, Any], sources: List[Dict[str, Any]]):
    """Pull entry/SL/TP from `user_answer` first, fall back to RiskReward source."""
    ua = payload.get("user_answer") or {}
    direction = ua.get("answer_buy_sell")
    entry = _f(ua.get("buy_price"))
    sl = _f(ua.get("stop_loss_price"))
    tp = _f(ua.get("take_profit_price"))
    if entry is not None and sl is not None and tp is not None:
        return direction, entry, sl, tp

    for src in sources:
        if src.get("type") in {"LineToolRiskRewardLong", "LineToolRiskRewardShort"}:
            state = src.get("state") or {}
            pts = src.get("points") or []
            if entry is None and pts:
                entry = _f(pts[0].get("price"))
            sl = sl if sl is not None else _f(state.get("stopLevel"))
            tp = tp if tp is not None else _f(state.get("profitLevel"))
            direction = direction or ("buy" if "Long" in src["type"] else "sell")
            break
    return direction, entry, sl, tp


# ──────────────────────  helpers  ──────────────────────

def _time_to_index(time_t: Any, times: List[int]) -> Optional[int]:
    if time_t is None or not times:
        return None
    t = int(time_t)
    idx = bisect.bisect_left(times, t)
    if idx >= len(times):
        return len(times) - 1
    if idx > 0 and abs(times[idx - 1] - t) <= abs(times[idx] - t):
        return idx - 1
    return idx


def _slope(line: ChannelLine) -> Optional[float]:
    dt = line.p2_time - line.p1_time
    return None if dt == 0 else (line.p2_price - line.p1_price) / dt


def _f(v: Any) -> Optional[float]:
    return float(v) if v is not None else None


def _i(v: Any) -> Optional[int]:
    return int(v) if v is not None else None
