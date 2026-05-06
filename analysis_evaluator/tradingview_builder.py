"""Convert the system's `correct_analysis` into TradingView drawing JSON.

Mirrors the textbook "SIMPLE SELL/BUY SETUP" layout — only the elements
a student needs to see, in plain labels, no busy fib levels or
premium/discount blankets:

    1.  LineToolTrendLine            — DISPLACEMENT line on the impulse leg
    2.  LineToolRiskRewardLong/Short — entry / SL / TP in one tool with auto R:R
    3.  LineToolRectangle            — ORDER BLOCK (last opposite-color candle
                                       before the impulse)
    4.  LineToolNote                 — ENTRY label at the entry zone
    5.  LineToolNote + LineToolTrendLine — BOS badge + dashed line at the broken pivot
    6.  LineToolRectangle ×N         — FVG (Fair Value Gap) imbalances inside impulse
    7.  LineToolNote + LineToolTrendLine — BSL/SSL liquidity badge + line

Earlier revisions also emitted: full fib retracement, trend-based fib
extension, key support/resistance ray, entry flag, trend-bias note,
premium/discount zones, equilibrium label, HTF bias note, HH/HL/LH/LL
swing labels, and a candlestick trigger pattern. All removed for the
"simple setup" educational style — too much visual noise for students.

Tool names and state keys are taken from `charting_library/charting_library.d.ts`.
"""

from __future__ import annotations

import logging
import random
import string
from typing import Any, Dict, List, Optional, Tuple

from .models import Candle, CorrectAnalysis
from .swing_detector import Swing
from .talib_analyzer import TalibAnalysis, analyze as talib_analyze
from .talib_drawings import build_talib_drawings

logger = logging.getLogger(__name__)


# Server-deployment fingerprint — increment when shipping new educational
# extensions so a quick log scan confirms the running process picked up the
# latest code. Shows up in the response under debug.builder_revision.
BUILDER_REVISION = "2026-04-30.pine-bos-choch-v11"


def _uid(k: int = 6) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=k))


_INTERVAL_MAP = {
    "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
    "1h": "60", "2h": "120", "4h": "240",
    "1d": "1D", "1day": "1D", "1D": "1D",
    "1w": "1W", "1W": "1W",
    "1M": "1M",
}


def _interval(timeframe: Optional[str]) -> str:
    if not timeframe:
        return "1D"
    return _INTERVAL_MAP.get(timeframe, timeframe)


def _interval_visibilities() -> Dict[str, Any]:
    return {
        "ticks": True, "seconds": True, "secondsFrom": 1, "secondsTo": 59,
        "minutes": True, "minutesFrom": 1, "minutesTo": 59,
        "hours": True, "hoursFrom": 1, "hoursTo": 24,
        "days": True, "daysFrom": 1, "daysTo": 366,
        "weeks": True, "weeksFrom": 1, "weeksTo": 52,
        "months": True, "monthsFrom": 1, "monthsTo": 12,
        "ranges": True,
    }


# ──────────────────────  Public entry point  ──────────────────────

def build_correct_drawings(
    correct: CorrectAnalysis,
    candles: List[Candle],
    symbol: str,
    timeframe: Optional[str] = None,
    swings: Optional[List[Swing]] = None,
    talib_result: Optional[TalibAnalysis] = None,
    right_edge_time: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Build TradingView-format drawings for the system's correct read.

    `talib_result` is optional — when omitted, the builder runs the TA-Lib
    analyzer itself (pattern detection, S/R levels, CHoCH). Pass it in when
    the caller already ran the analysis (avoids duplicate work + lets the
    evaluator pipe timings into its own debug payload).

    `right_edge_time` (epoch seconds) caps the right edge of zones / R:R box
    / S-R rays so they sit around the user's analysis area instead of running
    out to the latest candle. When omitted, the chart's last candle is used.
    """
    if not candles:
        return []

    interval = _interval(timeframe)
    n = len(candles)
    lo_i = max(0, min(correct.fib_range[0], n - 1))
    hi_i = max(0, min(correct.fib_range[1], n - 1))
    lo_t = candles[lo_i].time
    hi_t = candles[hi_i].time
    lo_p, hi_p = correct.fib_prices

    # Impulse boundaries
    impulse_end_i = max(lo_i, hi_i)
    impulse_start_i = min(lo_i, hi_i)
    impulse_end_time = candles[impulse_end_i].time
    impulse_start_time = candles[impulse_start_i].time
    last_time = candles[-1].time

    # Right edge for visual elements that extend past the impulse — defaults to
    # the chart's last candle, but the evaluator can clamp it to the user's
    # focus window so drawings don't blanket months of unrelated price action.
    drawing_right_edge = right_edge_time if right_edge_time is not None else last_time
    drawing_right_edge = min(drawing_right_edge, last_time)
    drawing_right_edge = max(drawing_right_edge, impulse_end_time)

    # Zones (OB, FVG) are capped to half the impulse duration past the impulse
    # end so they don't blanket the chart.
    impulse_duration = max(impulse_end_time - impulse_start_time, 3600)
    zone_right_edge = min(drawing_right_edge, impulse_end_time + impulse_duration // 2)

    sl_price, tp_price = _stop_and_target(correct, lo_p, hi_p)
    entry_price = (correct.entry_zone.top + correct.entry_zone.bottom) / 2

    # ── Simple-setup drawing flow ─────────────────────────────────────────
    # Mirrors the textbook "SIMPLE SELL SETUP" layout: a handful of clearly
    # labelled elements, no busy fib levels or premium/discount blankets.
    drawings: List[Dict[str, Any]] = []

    def _safe(key: str, fn, multi: bool = False, optional: bool = False):
        try:
            result = fn()
        except Exception:  # noqa: BLE001 — drawings are non-critical
            logger.exception("[simple-setup %s] failed; continuing", key)
            return
        if result is None or (optional and not result):
            return
        if multi:
            drawings.extend(result)
        else:
            drawings.append(result)

    # 1. R:R box — the big colored zone showing risk vs reward
    _safe("rr", lambda: _build_risk_reward(
        symbol, interval, correct,
        entry_price=entry_price, sl_price=sl_price, tp_price=tp_price,
        t_start=impulse_end_time, t_end=drawing_right_edge,
    ))

    # 2. DISPLACEMENT trendline along the impulse leg
    _safe("displacement", lambda: _build_impulse_trendline(
        symbol, interval, lo_t, lo_p, hi_t, hi_p, correct.trend,
    ))

    # 3. (Order Blocks are now detected chart-wide by the talib analyzer,
    #     not just at the displacement leg — see talib_drawings._ob_rect.
    #     The displacement-tied range was too narrow on real data: many
    #     impulses extend an existing trend and have no clear consolidation
    #     phase preceding them. Chart-wide detection picks up every textbook
    #     range+breakout in the visible window.)

    # 4. ENTRY label — small text marker at the entry zone (golden pocket mid)
    _safe("entry", lambda: _build_entry_label(
        symbol, interval, entry_price, impulse_end_time, correct.trend,
    ))

    # 5. (BoS now detected chart-wide by talib_analyzer._detect_bos with
    #     strict SMC trend gating — see talib_drawings._bos_marks. The
    #     displacement-tied version was firing on the FIRST big move out
    #     of a sideways range, but per SMC that's a CHoCH (not BoS). BoS
    #     should only fire on continuation breaks WITHIN an already-
    #     established trend, with a major swing being broken — exactly
    #     what _detect_bos enforces.)

    # 6. FVG (Fair Value Gap) rectangles inside the impulse
    _safe("fvg", lambda: _build_fvg(
        symbol, interval, candles, impulse_start_i, impulse_end_i, correct.trend, zone_right_edge,
    ), multi=True, optional=True)

    # 7. BSL / SSL liquidity line — wick that swept the prior pivot
    _safe("liquidity", lambda: _build_liquidity_sweep(
        symbol, interval, candles, swings or [], impulse_start_i, correct.trend,
    ), multi=True, optional=True)

    # 8. TA-Lib backed extensions:
    #     pattern arrows + insight text + supply/demand zones
    #     support/resistance horizontal rays
    #     CHoCH dotted line + badge (purple — distinct from BOS red/green)
    talib_data = talib_result if talib_result is not None else talib_analyze(candles, swings or [])
    _safe("talib", lambda: build_talib_drawings(
        talib_data, candles, symbol, interval,
        right_edge_time=drawing_right_edge,
    ), multi=True, optional=True)

    logger.info(
        "build_correct_drawings(rev=%s) -> %d drawings (trend=%s, swings=%d, talib_patterns=%d)",
        BUILDER_REVISION, len(drawings), correct.trend, len(swings or []),
        len(talib_data.patterns),
    )
    return drawings


# ──────────────────────  Stop & target calculation  ──────────────────────

def _stop_and_target(correct: CorrectAnalysis, lo_p: float, hi_p: float) -> Tuple[float, float]:
    """Educational defaults:
      - Long: SL just below the swing low, TP at 1.272 fib extension above the high.
      - Short: SL just above the swing high, TP at 1.272 fib extension below the low.
    1.272 is the most-taught conservative target after a golden-pocket entry.
    """
    leg = max(hi_p - lo_p, 1e-9)
    buffer = leg * 0.05
    if correct.trend == "bearish":
        return hi_p + buffer, lo_p - leg * 0.272
    return lo_p - buffer, hi_p + leg * 0.272


# ──────────────────────  1. Displacement trendline  ──────────────────────

def _build_impulse_trendline(
    symbol: str, interval: str, lo_t: int, lo_p: float, hi_t: int, hi_p: float, trend: str,
) -> Dict[str, Any]:
    color = "#089981" if trend == "bullish" else "#F23645" if trend == "bearish" else "#2962FF"
    p1_t, p1_p, p2_t, p2_p = (lo_t, lo_p, hi_t, hi_p) if lo_t <= hi_t else (hi_t, hi_p, lo_t, lo_p)
    return {
        "id": _uid(),
        "type": "LineToolTrendLine",
        "state": {
            "symbol": symbol,
            "interval": interval,
            "frozen": False,
            "visible": True,
            "linecolor": color,
            "linewidth": 2,
            "linestyle": 0,
            "extendLeft": False,
            "extendRight": False,
            "leftEnd": 0,
            "rightEnd": 0,
            "showLabel": True,
            "text": "DISPLACEMENT",
            "textcolor": color,
            "fontsize": 11,
            "bold": True,
            "italic": False,
            "horzLabelsAlign": "center",
            "vertLabelsAlign": "middle",
            "alwaysShowStats": False,
            "showMiddlePoint": False,
            "showPriceLabels": False,
            "showPriceRange": False,
            "showBarsRange": False,
            "showDateTimeRange": False,
            "showPercentage": False,
            "zOrderVersion": 2,
            "symbolStateVersion": 2,
            "intervalsVisibilities": _interval_visibilities(),
        },
        "points": [
            {"price": float(p1_p), "time_t": int(p1_t), "offset": 0},
            {"price": float(p2_p), "time_t": int(p2_t), "offset": 0},
        ],
        "zorder": -4000,
        "linkKey": _uid(12),
        "ownerSource": "_seriesId",
        "userEditEnabled": False,
        "isSelectionEnabled": True,
    }


# ──────────────────────  4. Risk-Reward box  ──────────────────────

def _build_risk_reward(
    symbol: str, interval: str, correct: CorrectAnalysis,
    *,
    entry_price: float, sl_price: float, tp_price: float,
    t_start: int, t_end: int,
) -> Dict[str, Any]:
    """Native TradingView R:R tool — auto-displays the risk:reward ratio."""
    is_long = correct.trend != "bearish"
    tool_type = "LineToolRiskRewardLong" if is_long else "LineToolRiskRewardShort"

    # Distances — TradingView serializes these as raw price deltas. Magnitude
    # only; direction is implied by Long/Short variant.
    stop_distance = abs(entry_price - sl_price)
    profit_distance = abs(tp_price - entry_price)

    # Educational defaults — 1% account risk on a $10k notional account
    account_size = 10_000.0
    risk_pct = 1.0
    risk_amount = account_size * (risk_pct / 100.0)
    qty = round(risk_amount / max(stop_distance, 1e-9), 6) if stop_distance > 0 else 1.0

    # The 4-point structure mirrors the LMS's saved layout (`drawing_instruction/find.py`):
    #   p0,p1: entry line span (defines width of the box on the time axis)
    #   p2:    duplicate entry anchor (TradingView internal)
    #   p3:    stop-side corner (price = SL, time = right edge)
    return {
        "id": _uid(),
        "type": tool_type,
        "state": {
            "symbol": symbol,
            "interval": interval,
            "frozen": False,
            "visible": True,
            "qty": qty,
            "lotSize": 1,
            "accountSize": account_size,
            "risk": f"{risk_pct:.2f}",
            "riskDisplayMode": "percents",
            "riskSize": stop_distance,
            "amountStop": account_size - risk_amount,
            "amountTarget": account_size + (profit_distance * qty),
            "stopLevel": stop_distance,
            "profitLevel": profit_distance,
            "compact": False,
            "fontsize": 12,
            "alwaysShowStats": True,
            "showPriceLabels": True,
            "drawBorder": False,
            "borderColor": "#667b8b",
            "fillBackground": True,
            "fillLabelBackground": True,
            "labelBackgroundColor": "#585858",
            "linecolor": "#787B86",
            "linewidth": 1,
            "textcolor": "#FFFFFF",
            "stopBackground": "rgba(242, 54, 69, 0.2)",
            "stopBackgroundTransparency": 80,
            "profitBackground": "rgba(8, 153, 129, 0.2)",
            "profitBackgroundTransparency": 80,
            "zOrderVersion": 2,
            "symbolStateVersion": 2,
            "intervalsVisibilities": _interval_visibilities(),
        },
        "points": [
            {"price": float(entry_price), "time_t": int(t_start), "offset": 0},
            {"price": float(entry_price), "time_t": int(t_end),   "offset": 0},
            {"price": float(entry_price), "time_t": int(t_start), "offset": 0},
            {"price": float(sl_price),    "time_t": int(t_end),   "offset": 0},
        ],
        "zorder": -5000,
        "linkKey": _uid(12),
        "ownerSource": "_seriesId",
        "userEditEnabled": False,
        "isSelectionEnabled": True,
    }


# Order Block detection used to live here as `_build_order_block` /
# `_find_consolidation_range`. Both moved to `talib_analyzer._detect_order_blocks`,
# which scans the whole chart instead of only the displacement leg — the PDF's
# range+breakout pattern naturally appears at multiple points on a chart, and
# many displacement legs are continuation moves with no consolidation phase
# preceding them.


# BoS detection moved to talib_analyzer._detect_bos (chart-wide, with strict
# SMC trend gating). The displacement-tied version was firing on the FIRST
# big move out of a sideways range — but per SMC that's a CHoCH, not a BoS.
# See talib_drawings._bos_marks for the drawing.


# ──────────────────────  D. Liquidity sweep  ──────────────────────

def _build_liquidity_sweep(
    symbol: str, interval: str,
    candles: List[Candle],
    swings: List["Swing"],
    impulse_start_i: int,
    trend: str,
) -> List[Dict[str, Any]]:
    """Most-recent wick that took out a prior pivot before the impulse and
    closed back inside (failed breakout = stop-hunt). Returns a small "x"
    badge at the wick + a dotted line at the swept level."""
    if not swings:
        return []

    # Bearish impulse: look for wicks ABOVE prior swing-highs (sweep before drop)
    # Bullish impulse: wicks BELOW prior swing-lows
    if trend == "bearish":
        prior = [s for s in swings if s.kind == "HIGH" and s.index < impulse_start_i]
    else:
        prior = [s for s in swings if s.kind == "LOW" and s.index < impulse_start_i]
    if not prior:
        return []
    pivot = prior[-1]

    # Scan the 15 bars leading into the impulse for a candle whose wick crossed
    # the pivot but whose body stayed inside.
    scan_start = max(pivot.index + 1, impulse_start_i - 15)
    sweep_idx: Optional[int] = None
    for i in range(impulse_start_i, scan_start - 1, -1):
        c = candles[i]
        if trend == "bearish" and c.high > pivot.price and c.close <= pivot.price:
            sweep_idx = i
            break
        if trend != "bearish" and c.low < pivot.price and c.close >= pivot.price:
            sweep_idx = i
            break
    if sweep_idx is None:
        return []

    swept_candle = candles[sweep_idx]
    sweep_price = swept_candle.high if trend == "bearish" else swept_candle.low
    color = "#FFC107"  # amber — neutral "warning" tone (works for both directions)

    # Dotted line at the swept level
    line = {
        "id": _uid(),
        "type": "LineToolTrendLine",
        "state": {
            "symbol": symbol,
            "interval": interval,
            "frozen": False,
            "visible": True,
            "linecolor": color,
            "linewidth": 1,
            "linestyle": 1,  # dotted
            "extendLeft": False,
            "extendRight": False,
            "showLabel": False,
            "alwaysShowStats": False,
            "showMiddlePoint": False,
            "showPriceLabels": False,
            "showPriceRange": False,
            "showBarsRange": False,
            "showDateTimeRange": False,
            "showPercentage": False,
            "zOrderVersion": 2,
            "symbolStateVersion": 2,
            "intervalsVisibilities": _interval_visibilities(),
        },
        "points": [
            {"price": float(pivot.price), "time_t": int(pivot.time),         "offset": 0},
            {"price": float(pivot.price), "time_t": int(swept_candle.time),  "offset": 0},
        ],
        "zorder": -3700,
        "linkKey": _uid(12),
        "ownerSource": "_seriesId",
        "userEditEnabled": False,
        "isSelectionEnabled": True,
    }

    # BSL = Buy-Side Liquidity (taken out above), SSL = Sell-Side (below).
    # LineToolText (not LineToolNote) so the label is always visible.
    badge_text = "BSL" if trend == "bearish" else "SSL"
    badge = {
        "id": _uid(),
        "type": "LineToolText",
        "state": {
            "symbol": symbol,
            "interval": interval,
            "frozen": False,
            "visible": True,
            "text": badge_text,
            "fontSize": 11,
            "bold": True,
            "italic": False,
            "color": "#B27600",  # darker amber so the text reads against light backgrounds
            "wordWrap": False,
            "alignment": "center",
            "fillBackground": True,
            "backgroundColor": "rgba(255, 193, 7, 0.95)",
            "borderColor": color,
            "drawBorder": True,
            "zOrderVersion": 2,
            "symbolStateVersion": 2,
            "intervalsVisibilities": _interval_visibilities(),
        },
        "points": [
            {"price": float(sweep_price), "time_t": int(swept_candle.time), "offset": 0},
        ],
        "zorder": -3550,
        "linkKey": _uid(12),
        "ownerSource": "_seriesId",
        "userEditEnabled": False,
        "isSelectionEnabled": True,
    }

    return [line, badge]


# ──────────────────────  6. ENTRY label  ──────────────────────

def _build_entry_label(
    symbol: str, interval: str,
    entry_price: float, anchor_time: int, trend: str,
) -> Dict[str, Any]:
    """Visible 'ENTRY' text label at the entry zone (textbook annotation).

    Uses LineToolText (not LineToolNote) so the label renders directly on the
    chart instead of as a clickable pin marker. Anchored just past the impulse
    end so it sits on the R:R box's edge.
    """
    color = "#F23645" if trend == "bearish" else "#089981"
    return {
        "id": _uid(),
        "type": "LineToolText",
        "state": {
            "symbol": symbol,
            "interval": interval,
            "frozen": False,
            "visible": True,
            "text": "ENTRY",
            "fontSize": 13,
            "bold": True,
            "italic": False,
            "color": color,
            "wordWrap": False,
            "alignment": "center",
            "fillBackground": True,
            "backgroundColor": "rgba(255, 255, 255, 0.95)",
            "borderColor": color,
            "drawBorder": True,
            "zOrderVersion": 2,
            "symbolStateVersion": 2,
            "intervalsVisibilities": _interval_visibilities(),
        },
        "points": [
            {"price": float(entry_price), "time_t": int(anchor_time), "offset": 0},
        ],
        "zorder": -3300,
        "linkKey": _uid(12),
        "ownerSource": "_seriesId",
        "userEditEnabled": False,
        "isSelectionEnabled": True,
    }


# ──────────────────────  7. Fair Value Gap (FVG)  ──────────────────────

def _detect_fvgs(
    candles: List[Candle], start_i: int, end_i: int, trend: str, max_count: int = 2,
) -> List[Dict[str, Any]]:
    """A 3-candle imbalance: candle[i-1] and candle[i+1] don't overlap, leaving
    a gap that price often "fills" later. Bearish FVG → prev.low > next.high."""
    out: List[Dict[str, Any]] = []
    lo, hi = sorted([start_i, end_i])
    for i in range(lo + 1, min(hi, len(candles) - 1)):
        prev = candles[i - 1]
        nxt = candles[i + 1]
        if trend == "bearish" and prev.low > nxt.high:
            out.append({"bar_index": i, "top": prev.low, "bottom": nxt.high, "time": candles[i].time})
        elif trend != "bearish" and prev.high < nxt.low:
            out.append({"bar_index": i, "top": nxt.low, "bottom": prev.high, "time": candles[i].time})
    # Keep the largest gaps (most teachable) first
    out.sort(key=lambda g: g["top"] - g["bottom"], reverse=True)
    return out[:max_count]


def _build_fvg(
    symbol: str, interval: str,
    candles: List[Candle],
    impulse_start_i: int, impulse_end_i: int,
    trend: str, right_edge_time: int,
) -> List[Dict[str, Any]]:
    """One small rectangle per FVG inside the impulse leg. Light blue, faint
    fill — enough to mark the imbalance without dominating the chart."""
    fvgs = _detect_fvgs(candles, impulse_start_i, impulse_end_i, trend)
    if not fvgs:
        return []

    rects: List[Dict[str, Any]] = []
    for fvg in fvgs:
        rects.append({
            "id": _uid(),
            "type": "LineToolRectangle",
            "state": {
                "symbol": symbol,
                "interval": interval,
                "frozen": False,
                "visible": True,
                "fillBackground": True,
                "backgroundColor": "rgba(33, 150, 243, 0.30)",
                "backgroundTransparency": 70,
                "linecolor": "#2196F3",
                "linewidth": 2,
                "linestyle": 0,
                "extendLeft": False,
                "extendRight": False,
                "showLabel": True,
                "text": "FVG",
                "textcolor": "#1976D2",
                "fontsize": 11,
                "bold": True,
                "italic": False,
                "horzLabelsAlign": "left",
                "vertLabelsAlign": "middle",
                "zOrderVersion": 2,
                "symbolStateVersion": 2,
                "intervalsVisibilities": _interval_visibilities(),
            },
            "points": [
                {"price": float(fvg["top"]),    "time_t": int(fvg["time"]),       "offset": 0},
                {"price": float(fvg["bottom"]), "time_t": int(right_edge_time),   "offset": 0},
            ],
            "zorder": -4600,
            "linkKey": _uid(12),
            "ownerSource": "_seriesId",
            "userEditEnabled": False,
            "isSelectionEnabled": True,
        })
    return rects


