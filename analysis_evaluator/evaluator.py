"""Top-level orchestrator — ties the rule engine, scoring layer and LLM together."""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from . import upstream
from .correct_analysis import build_correct_analysis
from .drawing_parser import parse_drawings
from .focus_window import (
    buffer_for_timeframe,
    extract_focus_window_from_analysis,
    extract_focus_window_from_payload,
    window_candles_around_focus,
)
from .llm_explainer import explain
from .market_structure import classify_trend
from .models import (
    AnalyzeResponse,
    Candle,
    CorrectAnalysis,
    EntryZone,
    Evaluation,
    UserAnalysis,
)
from .optimal_zone import find_optimal_range
from .scorer import aggregate, swing_score, trend_score
from .swing_detector import detect_swings
from .talib_analyzer import analyze as talib_analyze
from .tradingview_builder import BUILDER_REVISION, build_correct_drawings
from .validators import validate_channel, validate_entry_zone, validate_fib

logger = logging.getLogger(__name__)


# Hard cap on candles fed into swing/structure analysis. The full candle set
# is still fetched (so the chart context is intact), but we only run the rule
# engine on the most recent window — older bars don't affect current trade
# decisions and they 10×–30× the latency on long histories.
ANALYSIS_LOOKBACK = int(os.getenv("ANALYSIS_LOOKBACK", "1000"))


@contextmanager
def _phase(name: str, timings: Dict[str, float]) -> Iterator[None]:
    """Time a block, log it, and append the duration (ms) to `timings`."""
    t = time.perf_counter()
    yield
    ms = round((time.perf_counter() - t) * 1000, 1)
    timings[name] = ms
    logger.info("⏱  %s: %.1f ms", name, ms)


def evaluate(
    candles: List[Candle],
    analysis: UserAnalysis,
    *,
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    market: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    timings: Optional[Dict[str, float]] = None,
    focus_window: Optional[tuple] = None,
) -> AnalyzeResponse:
    """Direct mode — caller already has candles and parsed drawings.

    `focus_window` (epoch-second tuple) is the time range the student drew on.
    When provided, the rule engine biases its 'ideal trade setup' to land
    inside that area instead of on the latest candles. In manual mode it's
    derived from `analysis` if not passed explicitly; in upstream mode the
    caller passes it after windowing the candle set around it.
    """
    if not candles:
        raise ValueError("No candles provided")

    timings = timings if timings is not None else {}
    received_count = len(candles)
    # In manual mode the candles arrive un-windowed — keep the focus-aware
    # slice so the analysis lands around the user's drawing instead of the tail.
    if focus_window is None:
        focus_window = extract_focus_window_from_analysis(analysis)
    candles = window_candles_around_focus(candles, focus_window, lookback=ANALYSIS_LOOKBACK)

    # ── Layer 1: rule-based engine ──
    with _phase("swings", timings):
        swings = detect_swings(candles, window=5)
    with _phase("trend", timings):
        trend = classify_trend(swings)
    with _phase("optimal_range", timings):
        optimal = find_optimal_range(candles, swings, trend, focus_window=focus_window)

    with _phase("validators", timings):
        fib_check = validate_fib(analysis.fib, optimal, swings, candles)
        channel_check = validate_channel(analysis.channels, candles)
        entry_check = validate_entry_zone(analysis, optimal, swings)
        trend_check = trend_score(analysis.direction, trend)
        swing_check = swing_score(len(swings))

    # ── Layer 2: scoring ──
    final_score, components = aggregate(trend_check, swing_check, fib_check, channel_check, entry_check)

    evaluation = Evaluation(
        trend=trend_check.label,
        fibonacci=fib_check.label,
        channel=channel_check.label,
        entry_zone=entry_check.label,
    )

    mistakes: List[str] = []
    for chk in (trend_check, swing_check, fib_check, channel_check, entry_check):
        mistakes.extend(chk.mistakes)

    correct = build_correct_analysis(trend, optimal) or _fallback_correct(candles, trend)

    # ── TA-Lib pattern + level detection (separate phase so we can time it) ──
    with _phase("talib", timings):
        talib_result = talib_analyze(candles, swings, trend)

    # ── TradingView drawings for chart rendering ──
    # The chart's visible range needs to cover BOTH the user's drawing area
    # AND the leg the AI picked (it may have started before or ended after
    # the user's zone). Expand to the union of those two spans, plus a
    # ~50-candle buffer on the right edge for zones/OBs.
    setup_window = _compute_setup_window(focus_window, optimal, candles)
    right_edge_time: Optional[int] = None
    if setup_window is not None:
        right_edge_time = setup_window[1] + buffer_for_timeframe(timeframe, n_candles=50)

    with _phase("drawings", timings):
        drawings = build_correct_drawings(
            correct, candles, symbol or "UNKNOWN", timeframe,
            swings=swings, talib_result=talib_result,
            right_edge_time=right_edge_time,
        )

    # ── Layer 3: LLM mentor ──
    with _phase("llm", timings):
        ai_explanation = explain(
            score=final_score,
            evaluation=evaluation,
            mistakes=mistakes,
            correct=correct,
            user_summary={
                "direction": analysis.direction,
                "entry_price": analysis.entry_price,
                "stop_loss": analysis.stop_loss,
                "take_profit": analysis.take_profit,
                "n_zones": len(analysis.zones),
                "n_channels": len(analysis.channels),
                "had_fib": analysis.fib is not None,
            },
            focus_window=focus_window,
        )

    timings["total"] = round(sum(v for k, v in timings.items() if k != "total"), 1)

    # Expose the *setup* window (drawing area ∪ chosen leg span, padded) — this
    # is what the frontend should set as the chart's initial visible range so
    # the entire trade setup is on screen, not cut off mid-leg.
    if setup_window is not None:
        pad = buffer_for_timeframe(timeframe, n_candles=20)
        focus_start = setup_window[0] - pad
        focus_end = setup_window[1] + pad
    else:
        focus_start = focus_window[0] if focus_window else None
        focus_end = focus_window[1] if focus_window else None

    return AnalyzeResponse(
        success=True,
        symbol=symbol,
        timeframe=timeframe,
        market=market,
        start_date=start_date,
        end_date=end_date,
        focus_start_time=focus_start,
        focus_end_time=focus_end,
        score=final_score,
        evaluation=evaluation,
        mistakes=mistakes,
        correct_analysis=correct,
        total_drawings=len(drawings),
        drawings=drawings,
        ai_explanation=ai_explanation,
        debug={
            "candles_received": received_count,
            "candles_analyzed": len(candles),
            "lookback_window": ANALYSIS_LOOKBACK,
            "swing_count": len(swings),
            "detected_trend": trend,
            "optimal_range": _summarize_optimal(optimal),
            "components": [c.__dict__ for c in components],
            "timings_ms": timings,
            "builder_revision": BUILDER_REVISION,
            "drawing_count_by_type": _count_drawings_by_type(drawings),
            "talib": _summarize_talib(talib_result),
            "focus_window": (
                None if focus_window is None
                else {"start_time": focus_start, "end_time": focus_end}
            ),
            "right_edge_time": right_edge_time,
        },
    )


def evaluate_from_upstream(
    *,
    base_url: str,
    category: str,
    sub_category: str,
    type: str,
    date: str,
    chapter_id: int,
    user_type: str,
    is_challenge_only: bool,
    question_id: Optional[int] = None,
    bearer_token: Optional[str] = None,
    csrf_token: Optional[str] = None,
) -> AnalyzeResponse:
    """Auto-fetch mode — pull candles + drawings from the LMS, then evaluate."""
    timings: Dict[str, float] = {}

    with _phase("fetch_drawings", timings):
        drawings_payload = upstream.fetch_drawings(
            base_url,
            category=category,
            sub_category=sub_category,
            type=type,
            date=date,
            chapter_id=chapter_id,
            user_type=user_type,
            is_challenge_only=is_challenge_only,
            question_id=question_id,
            bearer_token=bearer_token,
            csrf_token=csrf_token,
        )

    pair = drawings_payload.get("pair")
    timeframe = drawings_payload.get("timeframe")
    market = upstream.market_for(drawings_payload.get("market_name"))
    from_date = upstream.isodate_to_ymd(drawings_payload.get("from_date") or "")
    to_date = upstream.isodate_to_ymd(drawings_payload.get("to_date") or "")

    if not (pair and timeframe and from_date and to_date):
        raise ValueError(f"Drawings payload missing required metadata: pair={pair}, tf={timeframe}, from={from_date}, to={to_date}")

    with _phase("fetch_candles", timings):
        candles = upstream.fetch_candles(
            base_url,
            pair=pair,
            from_date=from_date,
            to_date=to_date,
            timeframe=timeframe,
            market=market,
            bearer_token=bearer_token,
            csrf_token=csrf_token,
        )

    # Extract the user's drawing time range BEFORE windowing so we can centre
    # the analysis window on it (otherwise a 9-month chart with a drawing in
    # month 1 would be truncated to the tail and miss the user's area entirely).
    focus_window = extract_focus_window_from_payload(drawings_payload)

    # Window candles around the focus window when one was found; otherwise
    # fall back to the tail-windowing behaviour.
    analysis_candles = window_candles_around_focus(
        candles, focus_window, lookback=ANALYSIS_LOOKBACK,
    )

    with _phase("parse_drawings", timings):
        analysis = parse_drawings(drawings_payload, analysis_candles)

    response = evaluate(
        analysis_candles,
        analysis,
        symbol=pair,
        timeframe=timeframe,
        market=market,
        start_date=from_date,
        end_date=to_date,
        timings=timings,
        focus_window=focus_window,
    )
    response.debug["candles_received"] = len(candles)
    response.debug["upstream"] = {
        "pair": pair,
        "timeframe": timeframe,
        "market": market,
        "question_id": drawings_payload.get("id"),
        "question_no": drawings_payload.get("question_no"),
    }
    return response


# ──────────────────────  helpers  ──────────────────────

def _count_drawings_by_type(drawings: List[Dict[str, Any]]) -> Dict[str, int]:
    """Quick breakdown for the debug payload — at a glance shows whether
    every educational extension actually emitted on the running server."""
    out: Dict[str, int] = {}
    for d in drawings:
        key = d.get("type", "unknown")
        text = (d.get("state") or {}).get("text") or ""
        # Tag the educational extensions with a readable name when the type alone is ambiguous
        if text == "ORDER BLOCK":
            key = "EDU_order_block"
        elif text == "ENTRY":
            key = "EDU_entry"
        elif text == "BOS":
            key = "EDU_bos_badge"
        elif text == "CHoCH":
            key = "EDU_choch_badge"
        elif text in ("BSL", "SSL"):
            key = "EDU_liquidity_badge"
        elif text == "FVG":
            key = "EDU_fvg"
        elif text == "DISPLACEMENT":
            key = "EDU_displacement"
        elif "DEMAND" in text or "SUPPLY" in text:
            key = "EDU_supply_demand_zone"
        elif "BULLISH OB" in text or "BEARISH OB" in text:
            key = "EDU_order_block"
        elif text.startswith("SUPPORT") or text.startswith("RESISTANCE"):
            key = "EDU_support_resistance"
        out[key] = out.get(key, 0) + 1
    return out


def _summarize_talib(t) -> Dict[str, Any]:
    """Compact view of the TalibAnalysis for the debug payload."""
    if t is None:
        return {"available": False}
    return {
        "available": t.available,
        "patterns_detected": len(t.patterns),
        "patterns": [
            {"name": p.name, "bias": p.bias, "type": p.pattern_type, "bar_index": p.bar_index}
            for p in t.patterns
        ],
        "support_resistance_levels": len(t.support_resistance),
        "supply_demand_zones": [
            {
                "kind": z.kind,
                "top": round(z.top, 4),
                "bottom": round(z.bottom, 4),
                "candle_index": z.candle_index,
                "displacement_start_index": z.displacement_start_index,
                "displacement_end_index": z.displacement_end_index,
                "displacement_strength": round(z.displacement_strength, 2),
                "test_count": z.test_count,
                "is_fresh": z.is_fresh,
            }
            for z in t.zones
        ],
        "order_blocks": [
            {
                "kind": ob.kind,
                "top": round(ob.top, 4),
                "bottom": round(ob.bottom, 4),
                "candle_index": ob.candle_index,
                "displacement_start_index": ob.displacement_start_index,
                "displacement_end_index": ob.displacement_end_index,
                "displacement_strength": round(ob.displacement_strength, 2),
                "structure_break": ob.structure_break,
                "fvg_inside": ob.fvg_inside,
                "test_count": ob.test_count,
                "is_fresh": ob.is_fresh,
            }
            for ob in t.order_blocks
        ],
        "choch": (
            None if t.choch is None else
            {"direction": t.choch.direction, "pivot_index": t.choch.pivot_index, "break_index": t.choch.break_index}
        ),
    }


def _summarize_optimal(opt) -> Optional[Dict[str, Any]]:
    if opt is None:
        return None
    return {
        "low_index": opt.low_index,
        "high_index": opt.high_index,
        "low_price": opt.low_price,
        "high_price": opt.high_price,
        "direction": opt.direction,
        "impulse_strength": round(opt.impulse_strength, 3),
        "has_retracement": opt.has_retracement,
    }


def _compute_setup_window(
    focus_window: Optional[tuple],
    optimal,  # OptimalRange
    candles: List[Candle],
) -> Optional[tuple]:
    """Union of the user's drawing area and the chosen impulse leg's span.

    The user drew on a specific window; the picker may have selected a leg
    that started slightly before or extended past that window (because the
    expanded search admits the strongest setup nearby). We want the chart
    visible range to cover BOTH so the displacement, OB, retracement, and
    R:R box are all on screen.
    """
    leg_span: Optional[tuple] = None
    if optimal is not None and candles:
        i_lo = min(optimal.low_index, optimal.high_index)
        i_hi = max(optimal.low_index, optimal.high_index)
        i_lo = max(0, min(i_lo, len(candles) - 1))
        i_hi = max(0, min(i_hi, len(candles) - 1))
        leg_span = (candles[i_lo].time, candles[i_hi].time)

    if focus_window is None and leg_span is None:
        return None
    if focus_window is None:
        return leg_span
    if leg_span is None:
        return focus_window
    return (min(focus_window[0], leg_span[0]), max(focus_window[1], leg_span[1]))


def _fallback_correct(candles: List[Candle], trend) -> CorrectAnalysis:
    """When no impulse can be detected, return chart-extreme range so the response stays well-formed."""
    highs = [(c.high, i) for i, c in enumerate(candles)]
    lows = [(c.low, i) for i, c in enumerate(candles)]
    hi_p, hi_i = max(highs)
    lo_p, lo_i = min(lows)
    mid = (hi_p + lo_p) / 2
    band = (hi_p - lo_p) * 0.1
    return CorrectAnalysis(
        trend=trend,
        fib_range=(lo_i, hi_i),
        fib_prices=(lo_p, hi_p),
        key_levels=[0.5, 0.618],
        entry_zone=EntryZone(top=mid + band, bottom=mid - band),
    )
