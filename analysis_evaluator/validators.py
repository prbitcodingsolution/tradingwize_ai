"""Steps 5–7 — deterministic validators for Fib, channel, and entry zone.

Each validator returns (score 0..1, label, list[mistake]).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from .models import (
    Candle,
    ChannelInput,
    EvalLabel,
    FibInput,
    UserAnalysis,
    ZoneInput,
)
from .optimal_zone import OptimalRange, golden_pocket
from .swing_detector import Swing


@dataclass
class CheckResult:
    score: float                # 0..1
    label: EvalLabel
    mistakes: List[str]


# ─────────────────────────  Fibonacci  ─────────────────────────

def validate_fib(
    user: Optional[FibInput],
    optimal: Optional[OptimalRange],
    swings: List[Swing],
    candles: List[Candle],
) -> CheckResult:
    if user is None or user.start_index is None or user.end_index is None:
        return CheckResult(0.0, "missing", ["No Fibonacci drawn"])

    if optimal is None:
        return CheckResult(0.5, "weak", ["Could not detect a clean impulse to compare against"])

    user_lo, user_hi = sorted([user.start_index, user.end_index])
    opt_lo, opt_hi = optimal.low_index, optimal.high_index

    # Tolerance scales with the optimal range — bigger leg = more slack on swing match.
    leg_span = max(opt_hi - opt_lo, 1)
    tol = max(2, int(leg_span * 0.1))

    matches_lo = abs(user_lo - opt_lo) <= tol
    matches_hi = abs(user_hi - opt_hi) <= tol

    nearest_swings = [s.index for s in swings]
    near_swing_lo = any(abs(user_lo - i) <= tol for i in nearest_swings)
    near_swing_hi = any(abs(user_hi - i) <= tol for i in nearest_swings)

    if matches_lo and matches_hi:
        return CheckResult(1.0, "correct", [])
    if (matches_lo or matches_hi) and (near_swing_lo and near_swing_hi):
        return CheckResult(0.7, "partially correct", ["Fibonacci anchors on a minor swing rather than the dominant impulse"])
    if near_swing_lo and near_swing_hi:
        return CheckResult(0.5, "partially correct", ["Fibonacci drawn on a minor swing, not the main move"])
    return CheckResult(0.15, "incorrect", ["Fibonacci drawn between non-swing points (random anchors)"])


# ─────────────────────────  Channel  ─────────────────────────

def validate_channel(channels: List[ChannelInput], candles: List[Candle]) -> CheckResult:
    if not channels:
        return CheckResult(0.0, "missing", ["No channel / parallel trendlines drawn"])

    ch = channels[0]  # evaluate the first channel only — extras are ignored
    if ch.upper is None or ch.lower is None:
        return CheckResult(0.3, "weak", ["Channel needs both upper and lower trendlines"])

    s_up = _slope(ch.upper.p1_time, ch.upper.p1_price, ch.upper.p2_time, ch.upper.p2_price)
    s_lo = _slope(ch.lower.p1_time, ch.lower.p1_price, ch.lower.p2_time, ch.lower.p2_price)
    if s_up is None or s_lo is None:
        return CheckResult(0.2, "weak", ["Channel anchors collapse to a single time point"])

    denom = max(abs(s_up), abs(s_lo), 1e-9)
    slope_diff = abs(s_up - s_lo) / denom

    upper_touches = _count_touches(candles, ch.upper, kind="upper")
    lower_touches = _count_touches(candles, ch.lower, kind="lower")
    touches = upper_touches + lower_touches

    mistakes: List[str] = []
    score = 0.0

    if slope_diff < 0.1:
        score += 0.5
    elif slope_diff < 0.25:
        score += 0.3
        mistakes.append("Channel lines are not perfectly parallel")
    else:
        mistakes.append("Trendlines are not parallel")

    if touches >= 4:
        score += 0.5
    elif touches >= 2:
        score += 0.3
        mistakes.append("Channel has too few price touches to be confirmed")
    else:
        mistakes.append("Channel barely touches the price action")

    label: EvalLabel = (
        "correct" if score >= 0.85
        else "weak" if score >= 0.5
        else "incorrect"
    )
    return CheckResult(min(score, 1.0), label, mistakes)


# ─────────────────────────  Entry zone  ─────────────────────────

def validate_entry_zone(
    user: UserAnalysis,
    optimal: Optional[OptimalRange],
    swings: List[Swing],
) -> CheckResult:
    user_zone = _resolve_user_entry_zone(user)
    if user_zone is None:
        return CheckResult(0.0, "missing", ["No entry zone defined"])

    user_top, user_bottom = user_zone

    if optimal is None:
        return CheckResult(0.4, "weak", ["No detected impulse — entry zone cannot be confirmed by confluence"])

    confluence = 0
    mistakes: List[str] = []

    # 1. Overlap with golden pocket (0.5–0.618)
    gp_top, gp_bottom = golden_pocket(optimal)
    if _overlap(user_top, user_bottom, gp_top, gp_bottom):
        confluence += 1
    else:
        mistakes.append("Entry zone does not overlap the 0.5–0.618 retracement")

    # 2. Near a swing high/low (support / resistance)
    swing_band = max((optimal.high_price - optimal.low_price) * 0.05, 1e-9)
    if any(_near(s.price, (user_top + user_bottom) / 2, swing_band) for s in swings):
        confluence += 1
    else:
        mistakes.append("Entry zone is not aligned with any prior swing level")

    # 3. Direction consistency: in an uptrend, entries belong below the impulse high
    if optimal.direction == "up" and user_top > optimal.high_price:
        mistakes.append("Long entry placed above the impulse high — wrong side of the move")
    elif optimal.direction == "down" and user_bottom < optimal.low_price:
        mistakes.append("Short entry placed below the impulse low — wrong side of the move")
    else:
        confluence += 1

    score = confluence / 3.0
    label: EvalLabel = (
        "correct" if confluence == 3
        else "partially correct" if confluence == 2
        else "weak" if confluence == 1
        else "invalid"
    )
    return CheckResult(score, label, mistakes)


# ─────────────────────────  helpers  ─────────────────────────

def _resolve_user_entry_zone(user: UserAnalysis) -> Optional[Tuple[float, float]]:
    """Pick the user's entry zone — explicit zones first, then entry/SL spread."""
    for z in user.zones:
        if z.label and z.label.lower() in {"entry", "demand", "supply"}:
            return (z.top, z.bottom)
    if user.zones:
        z = user.zones[0]
        return (z.top, z.bottom)
    if user.entry_price is not None and user.stop_loss is not None:
        return (max(user.entry_price, user.stop_loss), min(user.entry_price, user.stop_loss))
    return None


def _slope(t1: int, p1: float, t2: int, p2: float) -> Optional[float]:
    return None if t2 == t1 else (p2 - p1) / (t2 - t1)


def _line_value_at(line, t: int) -> float:
    s = _slope(line.p1_time, line.p1_price, line.p2_time, line.p2_price)
    if s is None:
        return line.p1_price
    return line.p1_price + s * (t - line.p1_time)


def _count_touches(candles: List[Candle], line, *, kind: str, tol_ratio: float = 0.005) -> int:
    """A 'touch' is a candle whose high (upper line) or low (lower line) is within
    `tol_ratio` (default 0.5%) of the projected line price."""
    if not candles:
        return 0
    t_min = min(line.p1_time, line.p2_time)
    t_max = max(line.p1_time, line.p2_time)
    avg_price = (line.p1_price + line.p2_price) / 2 or 1.0
    tol = abs(avg_price) * tol_ratio
    count = 0
    for c in candles:
        if c.time < t_min or c.time > t_max:
            continue
        proj = _line_value_at(line, c.time)
        target = c.high if kind == "upper" else c.low
        if abs(target - proj) <= tol:
            count += 1
    return count


def _overlap(a_top: float, a_bottom: float, b_top: float, b_bottom: float) -> bool:
    return min(a_top, b_top) >= max(a_bottom, b_bottom)


def _near(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol
