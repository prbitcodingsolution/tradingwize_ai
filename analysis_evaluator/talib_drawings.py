"""Convert `TalibAnalysis` → TradingView drawing JSON.

Drawing-type → educational-meaning map (kept intentionally minimal so the
chart stays readable for students):

    LineToolRectangle (green/red)          → supply / demand zones (base+impulse)
    LineToolHorzRay                        → support / resistance lines
    LineToolTrendLine (dotted purple)      → CHoCH (distinct from BOS)
    LineToolNote (purple badge)            → CHoCH label

Per-pattern arrow flags and insight text labels were intentionally REMOVED —
they overlapped, stacked, and made the chart hard to read. Pattern detection
still runs (see TalibAnalysis.patterns) so the LLM explainer + debug payload
can reference patterns without polluting the chart.

Tool names + state shapes copied from `charting_library/charting_library.d.ts`
and the existing `tradingview_builder.py`.
"""

from __future__ import annotations

import logging
import random
import string
from typing import Any, Dict, List, Optional

from .models import Candle
from .talib_analyzer import BoS, CHoCH, OrderBlock, SupplyDemandZone, SupportResistance, TalibAnalysis

logger = logging.getLogger(__name__)


# ──────────────────────  Color palette  ──────────────────────

BULL_COLOR = "#089981"          # green — demand zones
BEAR_COLOR = "#F23645"          # red — supply zones
CHOCH_COLOR = "#9C27B0"         # purple — distinct from BOS red/green
SR_SUPPORT_COLOR = "#26A69A"    # teal
SR_RESISTANCE_COLOR = "#EF5350" # coral
DEMAND_FILL = "rgba(8, 153, 129, 0.10)"
SUPPLY_FILL = "rgba(242, 54, 69, 0.10)"


def _uid(k: int = 6) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=k))


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

def build_talib_drawings(
    analysis: TalibAnalysis,
    candles: List[Candle],
    symbol: str,
    interval: str,
    right_edge_time: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Build the full set of TA-Lib derived drawings for one symbol/timeframe.

    `right_edge_time` (epoch seconds) clamps where zones/OBs/S-R rays end on
    the time axis so they don't extend out to the latest candle when the
    analysis is focused on an older window. Defaults to the chart's last
    candle when omitted.
    """
    if not candles:
        return []

    drawings: List[Dict[str, Any]] = []
    last_time = candles[-1].time
    edge_time = min(right_edge_time, last_time) if right_edge_time is not None else last_time

    # NOTE: pattern arrows + insight text are intentionally NOT emitted as chart
    # drawings — they cluttered the chart with overlapping flags and labels and
    # made the analysis hard for students to read. The patterns are still
    # detected (see TalibAnalysis.patterns) so the debug payload + LLM explainer
    # can reference them; they just don't render visually.

    # 1. Support / resistance horizontal rays
    for level in analysis.support_resistance:
        try:
            drawings.append(_sr_line(level, symbol, interval, edge_time))
        except Exception:  # noqa: BLE001
            logger.exception("[talib S/R %s] failed; continuing", level.kind)

    # 2. Supply / demand zones — base+impulse rectangles extending right
    for zone in analysis.zones:
        try:
            drawings.append(_zone_rect(zone, candles, symbol, interval, edge_time))
        except Exception:  # noqa: BLE001
            logger.exception("[talib zone %s] failed; continuing", zone.kind)

    # 3. Order Blocks — range+breakout rectangles (PDF accumulation/distribution)
    for ob in analysis.order_blocks:
        try:
            drawings.append(_ob_rect(ob, symbol, interval, edge_time))
        except Exception:  # noqa: BLE001
            logger.exception("[talib OB %s] failed; continuing", ob.kind)

    # 4. CHoCH dotted line + badge (distinct purple — separate from BOS)
    if analysis.choch is not None:
        try:
            drawings.extend(_choch_marks(analysis.choch, candles, symbol, interval))
        except Exception:  # noqa: BLE001
            logger.exception("[talib choch] failed; continuing")

    # 5. BoS dashed line + badge (continuation in established trend)
    if analysis.bos is not None:
        try:
            drawings.extend(_bos_marks(analysis.bos, candles, symbol, interval))
        except Exception:  # noqa: BLE001
            logger.exception("[talib bos] failed; continuing")

    logger.info(
        "build_talib_drawings -> %d drawings (sr=%d, zones=%d, obs=%d, choch=%s, bos=%s, talib_available=%s, patterns_detected_but_hidden=%d)",
        len(drawings), len(analysis.support_resistance),
        len(analysis.zones), len(analysis.order_blocks), analysis.choch is not None,
        analysis.bos is not None, analysis.available,
        len(analysis.patterns),
    )
    return drawings


# ──────────────────────  Supply / Demand zones  ──────────────────────

def _zone_rect(
    zone: SupplyDemandZone,
    candles: List[Candle],
    symbol: str,
    interval: str,
    last_time: int,
) -> Dict[str, Any]:
    """SMC supply/demand zone rectangle.

    - Left edge: the OB-style anchor candle's time (last opposite candle before
      the displacement leg).
    - Right edge: chart's last candle.
    - Top/bottom: tight body+wick of the anchor candle (NOT the full
      consolidation high/low — that produced over-wide zones in the prior version).
    - Label includes test count when > 0 so students see weakening at a glance.
    """
    if zone.kind == "demand":
        line_color = BULL_COLOR
        fill_color = DEMAND_FILL
        prefix = "DEMAND"
    else:
        line_color = BEAR_COLOR
        fill_color = SUPPLY_FILL
        prefix = "SUPPLY"

    if zone.is_fresh:
        label = f"FRESH {prefix}"
    elif zone.test_count == 1:
        label = f"TESTED {prefix}"
    else:
        label = f"WEAK {prefix} ×{zone.test_count}"

    return {
        "id": _uid(),
        "type": "LineToolRectangle",
        "state": {
            "symbol": symbol,
            "interval": interval,
            "frozen": False,
            "visible": True,
            "fillBackground": True,
            "backgroundColor": fill_color,
            "backgroundTransparency": 88,
            "linecolor": line_color,
            "linewidth": 1,
            "linestyle": 0,
            "extendLeft": False,
            "extendRight": False,
            "showLabel": True,
            "text": label,
            "textcolor": line_color,
            "fontsize": 10,
            "bold": True,
            "italic": False,
            "horzLabelsAlign": "right",
            "vertLabelsAlign": "middle",
            "zOrderVersion": 2,
            "symbolStateVersion": 2,
            "intervalsVisibilities": _interval_visibilities(),
        },
        "points": [
            {"price": float(zone.top),    "time_t": int(zone.candle_time), "offset": 0},
            {"price": float(zone.bottom), "time_t": int(last_time),         "offset": 0},
        ],
        "zorder": -4400,  # behind FVG/OB but above main series
        "linkKey": _uid(12),
        "ownerSource": "_seriesId",
        "userEditEnabled": False,
        "isSelectionEnabled": True,
    }


# ──────────────────────  Order Block rectangle  ──────────────────────

def _ob_rect(
    ob: OrderBlock,
    symbol: str,
    interval: str,
    last_time: int,
) -> Dict[str, Any]:
    """SMC Order Block rectangle (last opposite candle before BOS displacement).

    Visually distinct from supply/demand zones:
      - **Solid border** (linewidth 2 vs SD zones' 1) — OBs broke structure
        and carry higher conviction.
      - **Stronger fill** (18% vs SD's 10%).
      - **Label** notes FVG presence ("BULLISH OB+FVG") for the highest-quality
        setups (PDF rule: imbalance inside displacement = stronger OB).
    """
    if ob.kind == "bullish":
        line_color = BULL_COLOR
        fill_color = "rgba(8, 153, 129, 0.18)"
        prefix = "BULLISH OB"
    else:
        line_color = BEAR_COLOR
        fill_color = "rgba(242, 54, 69, 0.18)"
        prefix = "BEARISH OB"

    if ob.fvg_inside:
        prefix = f"{prefix}+FVG"

    if ob.is_fresh:
        label = f"FRESH {prefix}"
    elif ob.test_count == 1:
        label = f"TESTED {prefix}"
    else:
        label = f"WEAK {prefix} ×{ob.test_count}"

    return {
        "id": _uid(),
        "type": "LineToolRectangle",
        "state": {
            "symbol": symbol,
            "interval": interval,
            "frozen": False,
            "visible": True,
            "fillBackground": True,
            "backgroundColor": fill_color,
            "backgroundTransparency": 82,
            "linecolor": line_color,
            "linewidth": 2,
            "linestyle": 0,
            "extendLeft": False,
            "extendRight": False,
            "showLabel": True,
            "text": label,
            "textcolor": line_color,
            "fontsize": 11,
            "bold": True,
            "italic": False,
            "horzLabelsAlign": "left",
            "vertLabelsAlign": "top",
            "zOrderVersion": 2,
            "symbolStateVersion": 2,
            "intervalsVisibilities": _interval_visibilities(),
        },
        "points": [
            {"price": float(ob.top),    "time_t": int(ob.candle_time), "offset": 0},
            {"price": float(ob.bottom), "time_t": int(last_time),       "offset": 0},
        ],
        "zorder": -4250,  # behind FVG, in front of S/D zones (so OBs are prominent)
        "linkKey": _uid(12),
        "ownerSource": "_seriesId",
        "userEditEnabled": False,
        "isSelectionEnabled": True,
    }


# ──────────────────────  3. Support / Resistance lines  ──────────────────────

def _sr_line(level: SupportResistance, symbol: str, interval: str, last_time: int) -> Dict[str, Any]:
    """A horizontal trendline from the anchor pivot to the chart's right edge.

    Uses LineToolTrendLine (with two points at the same price) instead of
    LineToolHorzRay because the latter doesn't render reliably across all
    TradingView library builds when serialized as JSON. Two-point horizontal
    trendlines are the standard pattern used by every other S/R-style line in
    `tradingview_builder.py`.
    """
    color = SR_SUPPORT_COLOR if level.kind == "support" else SR_RESISTANCE_COLOR
    label = "SUPPORT" if level.kind == "support" else "RESISTANCE"
    if level.touches > 1:
        label = f"{label} ×{level.touches}"

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
            "extendRight": True,
            "leftEnd": 0,
            "rightEnd": 0,
            "showLabel": True,
            "text": label,
            "textcolor": color,
            "fontsize": 11,
            "bold": True,
            "italic": False,
            "horzLabelsAlign": "right",
            "vertLabelsAlign": "middle",
            "alwaysShowStats": False,
            "showMiddlePoint": False,
            "showPriceLabels": True,
            "showPriceRange": False,
            "showBarsRange": False,
            "showDateTimeRange": False,
            "showPercentage": False,
            "zOrderVersion": 2,
            "symbolStateVersion": 2,
            "intervalsVisibilities": _interval_visibilities(),
        },
        "points": [
            {"price": float(level.price), "time_t": int(level.anchor_time), "offset": 0},
            {"price": float(level.price), "time_t": int(last_time),         "offset": 0},
        ],
        "zorder": -3900,
        "linkKey": _uid(12),
        "ownerSource": "_seriesId",
        "userEditEnabled": False,
        "isSelectionEnabled": True,
    }


# ──────────────────────  4. CHoCH (Change of Character)  ──────────────────────

def _choch_marks(
    choch: CHoCH, candles: List[Candle], symbol: str, interval: str,
) -> List[Dict[str, Any]]:
    """Dotted purple line at the broken pivot + 'CHoCH' badge at the break bar.

    Distinct from BOS in two ways:
      - Color: purple (BOS uses red/green directional)
      - Linestyle: 1 (dotted) vs BOS's 2 (dashed)
      - Badge text: 'CHoCH' vs BOS's 'BOS'
    """
    line = {
        "id": _uid(),
        "type": "LineToolTrendLine",
        "state": {
            "symbol": symbol,
            "interval": interval,
            "frozen": False,
            "visible": True,
            "linecolor": CHOCH_COLOR,
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
            {"price": float(choch.pivot_price), "time_t": int(choch.pivot_time), "offset": 0},
            {"price": float(choch.pivot_price), "time_t": int(choch.break_time), "offset": 0},
        ],
        "zorder": -3750,
        "linkKey": _uid(12),
        "ownerSource": "_seriesId",
        "userEditEnabled": False,
        "isSelectionEnabled": True,
    }

    # Use LineToolText so the "CHoCH" label is always visible on the chart
    # (LineToolNote renders only as a small pin marker until clicked).
    badge = {
        "id": _uid(),
        "type": "LineToolText",
        "state": {
            "symbol": symbol,
            "interval": interval,
            "frozen": False,
            "visible": True,
            "text": "CHoCH",
            "fontSize": 12,
            "bold": True,
            "italic": False,
            "color": CHOCH_COLOR,
            "wordWrap": False,
            "alignment": "center",
            "fillBackground": True,
            "backgroundColor": "rgba(255, 255, 255, 0.95)",
            "borderColor": CHOCH_COLOR,
            "drawBorder": True,
            "zOrderVersion": 2,
            "symbolStateVersion": 2,
            "intervalsVisibilities": _interval_visibilities(),
        },
        "points": [
            {"price": float(choch.pivot_price), "time_t": int(choch.break_time), "offset": 0},
        ],
        "zorder": -3550,
        "linkKey": _uid(12),
        "ownerSource": "_seriesId",
        "userEditEnabled": False,
        "isSelectionEnabled": True,
    }

    return [line, badge]


# ──────────────────────  5. BoS (Break of Structure — continuation)  ──────────────────────

def _bos_marks(
    bos: BoS, candles: List[Candle], symbol: str, interval: str,
) -> List[Dict[str, Any]]:
    """Dashed directional line at the broken pivot + 'BOS' badge.

    Distinct from CHoCH:
      - **Color**: green (bullish BoS) / red (bearish BoS) — directional
        (CHoCH uses neutral purple — it's a regime change)
      - **Linestyle**: 2 (dashed) — vs CHoCH's 1 (dotted)
      - **Badge text**: 'BOS' — vs 'CHoCH'
    """
    color = BULL_COLOR if bos.direction == "bullish" else BEAR_COLOR

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
            "linestyle": 2,  # dashed
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
            {"price": float(bos.pivot_price), "time_t": int(bos.pivot_time), "offset": 0},
            {"price": float(bos.pivot_price), "time_t": int(bos.break_time), "offset": 0},
        ],
        "zorder": -3800,
        "linkKey": _uid(12),
        "ownerSource": "_seriesId",
        "userEditEnabled": False,
        "isSelectionEnabled": True,
    }

    badge = {
        "id": _uid(),
        "type": "LineToolText",
        "state": {
            "symbol": symbol,
            "interval": interval,
            "frozen": False,
            "visible": True,
            "text": "BOS",
            "fontSize": 12,
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
            {"price": float(bos.pivot_price), "time_t": int(bos.break_time), "offset": 0},
        ],
        "zorder": -3600,
        "linkKey": _uid(12),
        "ownerSource": "_seriesId",
        "userEditEnabled": False,
        "isSelectionEnabled": True,
    }

    return [line, badge]
