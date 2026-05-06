"""Step 4 — find the strongest impulse leg followed by a retracement.

Returns the swing pair (low_idx, high_idx) the *system* believes Fibonacci should
be drawn on, plus the resulting entry zone (golden pocket: 0.5–0.618).

Leg selection is quality-scored, not just size-maxed: a leg only wins if it
*looks like a teachable trade setup* — meaningful displacement (≥1% of price),
broke prior structure, retraced cleanly into the golden-pocket band, and was
driven by directional candles (not chop). The previous "max(size)" picker
surfaced micro-legs whenever the user drew on a narrow window — see
`compute_leg_score` for the full breakdown.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .market_structure import Trend
from .models import Candle
from .swing_detector import Swing


@dataclass
class OptimalRange:
    low_index: int
    high_index: int
    low_price: float
    high_price: float
    impulse_size: float            # absolute price move
    impulse_strength: float        # impulse / median swing leg
    has_retracement: bool
    direction: str                 # "up" or "down"

    @property
    def fib_range(self) -> Tuple[int, int]:
        return (self.low_index, self.high_index)

    @property
    def fib_prices(self) -> Tuple[float, float]:
        return (self.low_price, self.high_price)


# Minimum leg size (% of average price) before the leg is considered a real
# displacement. Below this, the picker treats the leg as noise and heavily
# penalises it so micro-legs don't win on a quiet focus window.
_MIN_LEG_SIZE_PCT = 0.01      # 1% — soft penalty below this
_TINY_LEG_SIZE_PCT = 0.005    # 0.5% — heavy penalty (essentially disqualifying)


def find_optimal_range(
    candles: List[Candle],
    swings: List[Swing],
    trend: Trend,
    focus_window: Optional[Tuple[int, int]] = None,
) -> Optional[OptimalRange]:
    """Pick the highest-quality impulse leg with a retracement after it.

    With `focus_window` (epoch seconds), we expand the search to roughly 3×
    the user's drawing width (W on each side) so a narrow drawing area
    doesn't trap us into a micro-leg — there's almost always a stronger,
    teachable setup just outside the exact zone the student traced.

    Without `focus_window`, we fall back to the original behaviour: prefer
    legs in the last ~60% of data. Direction follows the leg, not the global
    trend (so we still produce a useful answer when trend is sideways).
    """
    if len(swings) < 3:
        return None

    # Build leg metadata once, score it per candidate.
    legs: List[Dict[str, Any]] = []
    for i, (a, b) in enumerate(zip(swings, swings[1:])):
        legs.append({"i": i, "a": a, "b": b, "size": abs(b.price - a.price)})
    if not legs:
        return None

    sizes_sorted = sorted(L["size"] for L in legs)
    median_size = sizes_sorted[len(sizes_sorted) // 2] or 1e-9
    avg_price = (sum(c.close for c in candles) / len(candles)) if candles else 1.0
    avg_price = avg_price or 1.0
    n_legs = len(legs)

    # ── Step 1: pick the candidate set ────────────────────────────────────
    candidates: List[Dict[str, Any]] = []
    if focus_window is not None:
        start_t, end_t = focus_window
        width = max(end_t - start_t, 50 * 3600)  # ≥ 50h floor for very narrow drawings
        # Search in a band of [start - W, end + W] — gives the picker room to
        # find a strong leg that began before or extended past the user's zone.
        search_start = start_t - width
        search_end = end_t + width
        for L in legs:
            if L["i"] >= n_legs - 1:
                continue  # need a swing after to confirm retracement exists
            t_min = min(L["a"].time, L["b"].time)
            t_max = max(L["a"].time, L["b"].time)
            if t_max < search_start or t_min > search_end:
                continue
            candidates.append(L)

    if not candidates:
        # Fallback path — recent legs with a retracement (original behaviour).
        n = len(candles)
        cutoff = int(n * 0.4)
        for L in legs:
            if L["i"] >= n_legs - 1:
                continue
            if L["b"].index < cutoff:
                continue
            candidates.append(L)

    if not candidates:
        candidates = [L for L in legs if L["i"] < n_legs - 1] or legs

    # ── Step 2: score each candidate by trade-setup quality ───────────────
    scored = [
        (compute_leg_score(L, swings, candles, median_size, avg_price), L)
        for L in candidates
    ]
    score, best = max(scored, key=lambda x: x[0]["composite"])
    a, b, size = best["a"], best["b"], best["size"]

    # Direction & ordering: low_index should hold the lower price.
    if a.price <= b.price:
        low_swing, high_swing, direction = a, b, "up"
    else:
        low_swing, high_swing, direction = b, a, "down"

    last_index = len(candles) - 1
    has_retrace = max(a.index, b.index) < last_index - 1

    return OptimalRange(
        low_index=low_swing.index,
        high_index=high_swing.index,
        low_price=low_swing.price,
        high_price=high_swing.price,
        impulse_size=size,
        impulse_strength=size / median_size,
        has_retracement=has_retrace,
        direction=direction,
    )


def compute_leg_score(
    leg: Dict[str, Any],
    swings: List[Swing],
    candles: List[Candle],
    median_size: float,
    avg_price: float,
) -> Dict[str, float]:
    """Composite score for a candidate leg — higher is better.

    Components (each surfaced in the result for debugging / tuning):
      - `strength`        size / median_size — base impulse magnitude
      - `size_factor`     0..1 multiplier penalising legs <1% / <0.5% of price
      - `structure_break` +0.5 when end-swing extends past prior same-kind extreme
      - `retrace_quality` +0.4 for a clean 0.382–0.786 retracement after the leg,
                          -0.3 if the next swing fully reversed the leg (>100%)
      - `clean_impulse`   +0.3 when ≥60% of candles inside the leg close in the
                          leg's direction (filters chop)
    """
    a, b = leg["a"], leg["b"]
    size = leg["size"]
    is_bullish = b.price > a.price

    strength = size / median_size

    size_pct = size / avg_price
    if size_pct < _TINY_LEG_SIZE_PCT:
        size_factor = 0.2
    elif size_pct < _MIN_LEG_SIZE_PCT:
        size_factor = 0.5
    elif size_pct < 0.02:
        size_factor = 0.8
    else:
        size_factor = 1.0

    # Structure break bonus — did the leg extend past the prior same-kind extreme?
    prior = swings[: leg["i"]]
    structure_break = 0.0
    if is_bullish:
        prior_highs = [p.price for p in prior if p.kind == "HIGH"]
        if prior_highs and b.price > max(prior_highs):
            structure_break = 0.5
    else:
        prior_lows = [p.price for p in prior if p.kind == "LOW"]
        if prior_lows and b.price < min(prior_lows):
            structure_break = 0.5

    # Retracement quality — what did price do AFTER the leg's end-swing?
    retrace_quality = 0.0
    if leg["i"] + 1 < len(swings) and size > 0:
        nxt = swings[leg["i"] + 1]
        retrace_pct = abs(nxt.price - b.price) / size
        if 0.382 <= retrace_pct <= 0.786:
            retrace_quality = 0.4
        elif retrace_pct > 1.0:
            retrace_quality = -0.3

    # Clean-impulse bonus — most candles inside the leg should close in-direction.
    clean_impulse = 0.0
    i_lo = min(a.index, b.index)
    i_hi = max(a.index, b.index)
    if i_hi > i_lo:
        window = candles[i_lo : i_hi + 1]
        up = sum(1 for c in window if c.close > c.open)
        same_dir = up / len(window) if is_bullish else (len(window) - up) / len(window)
        if same_dir >= 0.6:
            clean_impulse = 0.3

    composite = strength * size_factor * (1.0 + structure_break + retrace_quality + clean_impulse)
    return {
        "composite": composite,
        "strength": strength,
        "size_factor": size_factor,
        "structure_break": structure_break,
        "retrace_quality": retrace_quality,
        "clean_impulse": clean_impulse,
    }


def golden_pocket(rng: OptimalRange) -> Tuple[float, float]:
    """0.5 → 0.618 retracement band, returned as (top, bottom)."""
    lo, hi = rng.low_price, rng.high_price
    rng_size = hi - lo
    level_50 = hi - 0.5 * rng_size
    level_618 = hi - 0.618 * rng_size
    top, bottom = max(level_50, level_618), min(level_50, level_618)
    return top, bottom
