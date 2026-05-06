"""Extract the time window the student was analysing.

The chart shown to the student often spans far more candles than the area they
actually drew on (e.g. a 2024–2026 chart with a single zone in Aug 2025). The
evaluator must produce its "ideal trade setup" within the student's drawing
area, not on the most recent candles. This module owns that extraction.

We pull `time_t` from EVERY drawing point in the LMS payload (under
`answer_analysis_json.charts[*].panes[*].sources[*].points[*].time_t`) plus
trade-level anchors. The min/max across those is the focus window.
"""

from __future__ import annotations

import bisect
import logging
from typing import Any, Dict, List, Optional, Tuple

from .models import Candle, UserAnalysis

logger = logging.getLogger(__name__)


# Drawings whose time anchors are pure UI noise (textbook annotations from the
# course author, not the student's analysis). These would widen the focus window
# without representing what the student actually drew.
_IGNORED_DRAWING_TYPES = {
    "MainSeries",
    "Study",
    "VolumeProfile",
    "LineToolHorzLine",  # often a course-author marker spanning the chart
    "LineToolVertLine",
    "LineToolHorzRay",
}


def extract_focus_window_from_payload(payload: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    """Walk the raw LMS drawings payload and return (min_time, max_time) in epoch
    seconds, covering every student-drawn anchor. Returns None when no time
    anchors are present (e.g. price-only `user_answer` with no chart drawings)."""
    times: List[int] = []
    aaj = payload.get("answer_analysis_json") or {}
    for chart in aaj.get("charts", []) or []:
        for pane in chart.get("panes", []) or []:
            for src in pane.get("sources", []) or []:
                if src.get("type") in _IGNORED_DRAWING_TYPES:
                    continue
                for pt in src.get("points") or []:
                    t = pt.get("time_t")
                    if isinstance(t, (int, float)) and t > 0:
                        times.append(int(t))

    if not times:
        return None

    return (min(times), max(times))


def extract_focus_window_from_analysis(analysis: UserAnalysis) -> Optional[Tuple[int, int]]:
    """Fallback for manual mode (caller already parsed drawings into UserAnalysis).

    Reads timestamps off Fib/channel/zone fields. Will return None for drawings
    that arrived as price-only inputs (entry/SL/TP without time anchors).
    """
    times: List[int] = []

    if analysis.fib:
        if analysis.fib.start_time:
            times.append(int(analysis.fib.start_time))
        if analysis.fib.end_time:
            times.append(int(analysis.fib.end_time))

    for ch in analysis.channels:
        for line in (ch.upper, ch.lower):
            if line is None:
                continue
            times.append(int(line.p1_time))
            times.append(int(line.p2_time))

    for z in analysis.zones:
        if z.start_time:
            times.append(int(z.start_time))
        if z.end_time:
            times.append(int(z.end_time))

    times = [t for t in times if t > 0]
    return (min(times), max(times)) if times else None


def window_candles_around_focus(
    candles: List[Candle],
    focus_window: Optional[Tuple[int, int]],
    *,
    lookback: int,
) -> List[Candle]:
    """Return up to `lookback` candles centred on the focus window.

    Without a focus window we fall back to the tail (current behaviour). With
    one, the window straddles the focus area so the swing detector and zone
    builder operate on candles around where the student drew — not the most
    recent bars (which are usually months past the student's analysis).
    """
    n = len(candles)
    if n <= lookback:
        return candles
    if focus_window is None:
        return candles[-lookback:]

    start_t, end_t = focus_window
    times = [c.time for c in candles]

    lo = bisect.bisect_left(times, start_t)
    hi = bisect.bisect_right(times, end_t)
    if hi <= lo:
        # The focus window doesn't intersect any candle — fall back to tail.
        logger.warning(
            "Focus window [%s, %s] doesn't intersect candle range — using tail",
            start_t, end_t,
        )
        return candles[-lookback:]

    # Centre `lookback` candles on the focus window.
    span = hi - lo
    if span >= lookback:
        # Focus window already wider than lookback — trim equally on both ends.
        excess = span - lookback
        return candles[lo + excess // 2 : lo + excess // 2 + lookback]

    pad_each = (lookback - span) // 2
    new_lo = max(0, lo - pad_each)
    new_hi = min(n, hi + pad_each)

    # Refill if we hit a chart edge.
    if new_hi - new_lo < lookback:
        if new_lo == 0:
            new_hi = min(n, new_lo + lookback)
        elif new_hi == n:
            new_lo = max(0, new_hi - lookback)

    return candles[new_lo:new_hi]


def buffer_for_timeframe(timeframe: Optional[str], n_candles: int = 50) -> int:
    """Return `n_candles` worth of seconds for the given timeframe, used as
    padding around the focus window when clamping zone right-edges."""
    seconds_per = {
        "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
        "1h": 3600, "2h": 7200, "4h": 14400,
        "1d": 86400, "1day": 86400, "1D": 86400,
        "1w": 604800, "1W": 604800,
        "1M": 2592000,
    }
    return n_candles * seconds_per.get(timeframe or "1h", 3600)
