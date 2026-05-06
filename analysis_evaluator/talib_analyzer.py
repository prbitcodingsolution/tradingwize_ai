"""TA-Lib backed pattern + level detection for the /analyze endpoint.

Runs three families of analysis on the candle window:

1. **Candlestick patterns** — every CDL* function in TA-Lib is invoked. Each
   non-zero output bar becomes a `PatternHit` (bullish/bearish + signal name).
2. **Support / resistance levels** — pivot-based horizontal levels plus
   Bollinger upper/lower (BBANDS) and Parabolic SAR snapshots.
3. **CHoCH (Change of Character)** — a *trend reversal* break, separate from
   BOS which is a continuation break. Detected from the swing sequence.

TA-Lib is an optional dependency. When the import fails (Linux without the C
library, fresh dev container, etc.) the analyzer returns empty results so the
rest of the pipeline keeps working — drawings degrade gracefully rather than
500'ing the API.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Tuple

from .models import Candle
from .swing_detector import Swing

logger = logging.getLogger(__name__)


try:
    import numpy as np  # noqa: F401 — used inside the try via talib's array inputs
    import talib  # type: ignore
    _TALIB_AVAILABLE = True
except Exception:  # noqa: BLE001 — numpy/talib both optional from this module's POV
    _TALIB_AVAILABLE = False
    logger.warning(
        "TA-Lib not available — talib_analyzer will return empty results. "
        "Install with `pip install TA-Lib` to enable candlestick pattern drawings."
    )


# ──────────────────────  Pattern catalog  ──────────────────────
#
# Curated subset from the TA-Lib pattern recognition family. Skipped:
#  - "long line" / "short line" / "high wave" / "spinning top" — too noisy,
#    fire on most candles, generate visual clutter.
#  - "marubozu" variants — already implied by the displacement leg.
#  - Multi-bar continuation patterns that overlap (RISEFALL3METHODS etc).
#
# Each entry: (talib_func_name, human_readable_label, "reversal" | "continuation").
PATTERN_CATALOG: List[Tuple[str, str, str]] = [
    # --- Reversal: bullish ---
    ("CDLHAMMER",            "Hammer",              "reversal"),
    ("CDLINVERTEDHAMMER",    "Inverted Hammer",     "reversal"),
    ("CDLENGULFING",         "Engulfing",           "reversal"),
    ("CDLMORNINGSTAR",       "Morning Star",        "reversal"),
    ("CDLMORNINGDOJISTAR",   "Morning Doji Star",   "reversal"),
    ("CDLPIERCING",          "Piercing Line",       "reversal"),
    ("CDL3WHITESOLDIERS",    "Three White Soldiers","reversal"),
    ("CDLDRAGONFLYDOJI",     "Dragonfly Doji",      "reversal"),
    ("CDL3INSIDE",           "Three Inside",        "reversal"),
    ("CDL3OUTSIDE",          "Three Outside",       "reversal"),
    ("CDLABANDONEDBABY",     "Abandoned Baby",      "reversal"),
    ("CDLBELTHOLD",          "Belt Hold",           "reversal"),
    ("CDLBREAKAWAY",         "Breakaway",           "reversal"),
    ("CDLHARAMI",            "Harami",              "reversal"),
    ("CDLHARAMICROSS",       "Harami Cross",        "reversal"),
    # --- Reversal: bearish ---
    ("CDLSHOOTINGSTAR",      "Shooting Star",       "reversal"),
    ("CDLHANGINGMAN",        "Hanging Man",         "reversal"),
    ("CDLEVENINGSTAR",       "Evening Star",        "reversal"),
    ("CDLEVENINGDOJISTAR",   "Evening Doji Star",   "reversal"),
    ("CDLDARKCLOUDCOVER",    "Dark Cloud Cover",    "reversal"),
    ("CDL3BLACKCROWS",       "Three Black Crows",   "reversal"),
    ("CDL2CROWS",            "Two Crows",           "reversal"),
    ("CDLGRAVESTONEDOJI",    "Gravestone Doji",     "reversal"),
    ("CDLUPSIDEGAP2CROWS",   "Upside Gap Two Crows","reversal"),
    # --- Continuation ---
    ("CDLDOJI",              "Doji",                "indecision"),
    ("CDLDOJISTAR",          "Doji Star",           "indecision"),
    ("CDLTRISTAR",           "Tri-Star",            "reversal"),
]


# ──────────────────────  Public dataclasses  ──────────────────────

@dataclass
class PatternHit:
    """One non-zero output bar from a TA-Lib CDL* function."""
    name: str                                       # human-readable label
    talib_func: str                                 # original CDL function name
    bar_index: int
    time: int
    price: float                                    # candle close
    bias: Literal["bullish", "bearish"]
    pattern_type: Literal["reversal", "continuation", "indecision"]
    strength: int                                   # absolute value of TA-Lib output (100 / 200 / etc.)


@dataclass
class SupportResistance:
    """A horizontal price level that acted as S/R, plus the bar where it formed."""
    kind: Literal["support", "resistance"]
    price: float
    anchor_index: int
    anchor_time: int
    touches: int = 1                                # how many swings confirm the level


@dataclass
class OrderBlock:
    """SMC-style Order Block: the **last opposite-color candle before a strong
    displacement leg that broke market structure**.

    Per the institutional / Smart Money Concept interpretation:
      - **Bullish OB** = last BEARISH candle before a strong bullish displacement
                         that broke a prior swing high (BOS bullish).
                         Acts as future demand — price returns and bounces up.
      - **Bearish OB** = last BULLISH candle before a strong bearish displacement
                         that broke a prior swing low (BOS bearish).
                         Acts as future supply — price returns and rejects down.

    Validation rules (rejected if any fail):
      1. Displacement must be impulsive: ≥ 2 strong same-direction candles
         (each body ≥ 1.2× rolling average body).
      2. Displacement must break structure (close past prior swing high/low).
      3. The OB candle must NOT be inside a sideways consolidation — there
         must be a clear directional sequence from OB → displacement.
      4. OBs invalidated by a later close past the OB on the wrong side
         are dropped (price already filled them).

    Zone width follows the textbook tight definition:
      - Bullish OB (bearish candle): top = open, bottom = low
        (body + downside wick — the absorption zone)
      - Bearish OB (bullish candle): top = high, bottom = open
        (body + upside wick — the absorption zone)
    """
    kind: Literal["bullish", "bearish"]
    top: float
    bottom: float
    candle_index: int                               # the OB candle itself (last opposite color)
    candle_time: int
    displacement_start_index: int                   # first candle of the impulse leg
    displacement_end_index: int                     # last candle of the impulse leg
    displacement_strength: float                    # impulse total body / avg_body
    structure_break: bool                           # did the displacement close past a prior pivot?
    fvg_inside: bool                                # is there a 3-candle imbalance in the displacement?
    test_count: int                                 # how many times price has tagged the OB after creation
    is_fresh: bool                                  # True iff test_count == 0


@dataclass
class SupplyDemandZone:
    """Same SMC pattern as Order Block but **without** the structure-break
    requirement. A zone marks the last opposite-color candle before a strong
    displacement; an OB is the strict subset that also broke structure.

    Concretely:
      - Strong displacement + last opposite candle + BOS  → **OrderBlock**
      - Strong displacement + last opposite candle (no BOS) → **SupplyDemandZone**

    The detection function deduplicates: any zone whose price/time overlaps
    a detected OB is dropped to avoid double-drawing the same level.
    """
    kind: Literal["supply", "demand"]
    top: float
    bottom: float
    candle_index: int                               # the OB-style anchor candle
    candle_time: int
    displacement_start_index: int
    displacement_end_index: int
    displacement_strength: float                    # impulse total body / avg_body
    test_count: int
    is_fresh: bool


@dataclass
class BoS:
    """Break of Structure — continuation break in an ALREADY-ESTABLISHED trend.

    Per the user's strict SMC spec:
      - **Bullish BoS**: while bullish trend is established (HH+HL pattern),
        price closes strongly ABOVE the most recent prior Higher-High.
        Confirms the trend continues.
      - **Bearish BoS**: while bearish trend is established (LH+LL pattern),
        price closes strongly BELOW the most recent prior Lower-Low.

    Distinct from CHoCH: BoS = continuation; CHoCH = reversal. The first big
    move out of a sideways range is a CHoCH, not a BoS — only subsequent
    moves within the new trend qualify as BoS.
    """
    direction: Literal["bullish", "bearish"]
    pivot_index: int
    pivot_price: float
    pivot_time: int
    break_index: int
    break_time: int


@dataclass
class CHoCH:
    """Change of Character — first break of structure in the OPPOSITE direction.

    Distinct from BOS: BOS = continuation break; CHoCH = reversal break.
    """
    direction: Literal["bullish", "bearish"]        # direction of the NEW trend after the break
    pivot_index: int                                # the pivot that got broken
    pivot_price: float
    pivot_time: int
    break_index: int
    break_time: int


@dataclass
class TalibAnalysis:
    """Aggregate output handed to the drawing builder."""
    patterns: List[PatternHit] = field(default_factory=list)
    support_resistance: List[SupportResistance] = field(default_factory=list)
    zones: List[SupplyDemandZone] = field(default_factory=list)
    order_blocks: List[OrderBlock] = field(default_factory=list)
    bbands: Optional[Dict[str, List[float]]] = None  # {"upper": [...], "middle": [...], "lower": [...]}
    sar: Optional[List[float]] = None                # one value per candle
    choch: Optional[CHoCH] = None
    bos: Optional[BoS] = None
    available: bool = False                          # True iff TA-Lib was importable


# ──────────────────────  Public API  ──────────────────────

def analyze(
    candles: List[Candle],
    swings: List[Swing],
    trend: Optional[str] = None,
    *,
    max_patterns: int = 12,
    pattern_window: int = 200,
) -> TalibAnalysis:
    """Run the full TA-Lib pipeline. Returns empty result if TA-Lib is missing.

    `trend` (optional, "bullish"/"bearish"/"sideways") — when provided, the OB
    and SD detectors apply a market-structure filter that drops counter-trend
    zones (the user spec: "in a bearish trend, ignore weak bullish OBs").

    `pattern_window` — only return pattern hits from the last N candles (older
    hits clutter the chart and have no actionable trade value).

    `max_patterns` — keep at most N pattern hits, sorted by recency. Multiple
    patterns can fire on the same bar; we deduplicate per-bar to the strongest.
    """
    if not candles:
        return TalibAnalysis()

    current_price = candles[-1].close

    if not _TALIB_AVAILABLE:
        # Still compute structural CHoCH + pivot-based S/R + SD zones + OBs —
        # none of these need TA-Lib. Only the candlestick patterns and
        # BBANDS/SAR are skipped.
        bos_event, choch_event = _detect_structure_breaks(swings, candles)
        return TalibAnalysis(
            patterns=[],
            support_resistance=_pivot_levels(swings, current_price),
            zones=_detect_supply_demand_zones(candles, swings, trend),
            order_blocks=_detect_order_blocks(candles, swings, trend),
            choch=choch_event,
            bos=bos_event,
            available=False,
        )

    opens, highs, lows, closes = _to_arrays(candles)

    patterns = _detect_patterns(
        candles, opens, highs, lows, closes,
        window=pattern_window, limit=max_patterns,
    )
    bbands = _bollinger(closes)
    sar = _parabolic_sar(highs, lows)
    # S/R: only main pivot-based levels — BBANDS were dropped (dynamic levels
    # added too much noise to a chart that already shows displacement/OB/FVG).
    sr_levels = _pivot_levels(swings, current_price)
    zones = _detect_supply_demand_zones(candles, swings, trend)
    obs = _detect_order_blocks(candles, swings, trend)

    bos_event, choch_event = _detect_structure_breaks(swings, candles)
    return TalibAnalysis(
        patterns=patterns,
        support_resistance=sr_levels,
        zones=zones,
        order_blocks=obs,
        bbands=bbands,
        sar=sar,
        choch=choch_event,
        bos=bos_event,
        available=True,
    )


# ──────────────────────  Internals  ──────────────────────

def _to_arrays(candles: List[Candle]):
    """Convert candle list to numpy arrays (TA-Lib expects double[])."""
    import numpy as np
    return (
        np.array([c.open for c in candles], dtype="float64"),
        np.array([c.high for c in candles], dtype="float64"),
        np.array([c.low for c in candles], dtype="float64"),
        np.array([c.close for c in candles], dtype="float64"),
    )


def _detect_patterns(
    candles: List[Candle],
    opens, highs, lows, closes,
    *,
    window: int,
    limit: int,
    min_spacing: int = 3,
) -> List[PatternHit]:
    """Run every catalog function, collect non-zero hits, dedup per bar AND
    enforce a minimum bar spacing between hits so insight text doesn't stack.
    """
    hits_by_bar: Dict[int, PatternHit] = {}
    n = len(candles)
    cutoff = max(0, n - window)

    for func_name, label, ptype in PATTERN_CATALOG:
        fn = getattr(talib, func_name, None)
        if fn is None:
            continue
        try:
            out = fn(opens, highs, lows, closes)
        except Exception:  # noqa: BLE001 — never let a single pattern kill the run
            logger.exception("TA-Lib %s failed", func_name)
            continue

        for i in range(cutoff, n):
            v = int(out[i])
            if v == 0:
                continue
            bias: Literal["bullish", "bearish"] = "bullish" if v > 0 else "bearish"
            hit = PatternHit(
                name=label,
                talib_func=func_name,
                bar_index=i,
                time=candles[i].time,
                price=candles[i].close,
                bias=bias,
                pattern_type=ptype,  # type: ignore[arg-type]
                strength=abs(v),
            )
            existing = hits_by_bar.get(i)
            # Keep the strongest signal per bar; reversal patterns beat indecision.
            if existing is None or _pattern_priority(hit) > _pattern_priority(existing):
                hits_by_bar[i] = hit

    # Sort by recency (most recent first).
    ordered = sorted(hits_by_bar.values(), key=lambda h: h.bar_index, reverse=True)

    # Spacing filter — keep only the strongest hit within any `min_spacing` bars.
    # Without this, three consecutive bars all firing patterns produce three
    # stacked text labels and arrows that overlap visually.
    spaced: List[PatternHit] = []
    for hit in ordered:
        if any(abs(hit.bar_index - kept.bar_index) < min_spacing for kept in spaced):
            continue
        spaced.append(hit)
        if len(spaced) >= limit:
            break
    return spaced


def _pattern_priority(hit: PatternHit) -> int:
    type_score = {"reversal": 3, "continuation": 2, "indecision": 1}.get(hit.pattern_type, 0)
    return type_score * 1000 + hit.strength


def _bollinger(closes) -> Optional[Dict[str, List[float]]]:
    try:
        upper, middle, lower = talib.BBANDS(closes, timeperiod=20, nbdevup=2, nbdevdn=2)
        return {
            "upper":  [float(x) if x == x else 0.0 for x in upper],   # NaN-safe
            "middle": [float(x) if x == x else 0.0 for x in middle],
            "lower":  [float(x) if x == x else 0.0 for x in lower],
        }
    except Exception:  # noqa: BLE001
        logger.exception("BBANDS failed")
        return None


def _parabolic_sar(highs, lows) -> Optional[List[float]]:
    try:
        out = talib.SAR(highs, lows, acceleration=0.02, maximum=0.2)
        return [float(x) if x == x else 0.0 for x in out]
    except Exception:  # noqa: BLE001
        logger.exception("SAR failed")
        return None


# ──────────────────────  S/R level detection  ──────────────────────
#
# Goal: emit only the **main** support / resistance levels — the ones a
# learner can identify at a glance, not every cluster of swing pivots.
#
# Rules:
#   1. **Cluster swings within 1% price tolerance** (was 0.3%) — merge nearby
#      pivots so we don't get 3 lines stacked at almost-the-same level.
#   2. **Drop single-touch clusters** — a level needs ≥ 2 swings touching it
#      to count as "tested" S/R.
#   3. **Filter by current price** — keep only levels above current price as
#      resistance and below current price as support; ignore irrelevant
#      historical levels that price has moved well past.
#   4. **Cap at 2 per side** — at most 2 resistances + 2 supports = 4 total.
#      Picked by `(touches DESC, distance_from_price ASC, recency DESC)`.
#   5. **Drop BBANDS-derived levels entirely** — they're dynamic, change every
#      bar, and add noise on a chart that already has displacement / OB / FVG.

_SR_CLUSTER_TOLERANCE = 0.010           # 1.0% — wider clustering, fewer lines
_SR_MIN_TOUCHES = 2
_SR_MAX_PER_SIDE = 2
_SR_MAX_DISTANCE_RATIO = 0.30           # ignore levels > 30% away from current price


def _pivot_levels(swings: List[Swing], current_price: float) -> List[SupportResistance]:
    """Return at most 4 main S/R levels (≤ 2 per side, ≥ 2 touches each)."""
    if not swings or current_price <= 0:
        return []

    levels: List[SupportResistance] = []
    for kind in ("HIGH", "LOW"):
        same_kind = [s for s in swings if s.kind == kind]
        if len(same_kind) < _SR_MIN_TOUCHES:
            continue
        same_kind.sort(key=lambda s: s.price)

        # Cluster by 1% price tolerance
        clusters: List[List[Swing]] = []
        current: List[Swing] = []
        for s in same_kind:
            if not current:
                current = [s]
                continue
            anchor_price = current[0].price
            if anchor_price > 0 and abs(s.price - anchor_price) / anchor_price <= _SR_CLUSTER_TOLERANCE:
                current.append(s)
            else:
                clusters.append(current)
                current = [s]
        if current:
            clusters.append(current)

        for cluster in clusters:
            if len(cluster) < _SR_MIN_TOUCHES:
                continue                # drop single-touch clusters
            avg_price = sum(s.price for s in cluster) / len(cluster)

            # Side filter: resistances above price, supports below
            if kind == "HIGH" and avg_price <= current_price:
                continue
            if kind == "LOW" and avg_price >= current_price:
                continue

            # Distance filter — ignore irrelevant historical levels
            distance_ratio = abs(avg_price - current_price) / current_price
            if distance_ratio > _SR_MAX_DISTANCE_RATIO:
                continue

            # Anchor time = the most recent swing in the cluster (so the line
            # extends from where the level was last validated, not from the
            # earliest historical touch).
            most_recent = max(cluster, key=lambda s: s.index)
            levels.append(SupportResistance(
                kind="resistance" if kind == "HIGH" else "support",
                price=avg_price,
                anchor_index=most_recent.index,
                anchor_time=most_recent.time,
                touches=len(cluster),
            ))

    # Score each level: touches first, then proximity, then recency
    def _score(lvl: SupportResistance) -> tuple:
        distance_ratio = abs(lvl.price - current_price) / current_price if current_price > 0 else 1.0
        return (lvl.touches, -distance_ratio, lvl.anchor_index)

    # Pick top-N per side
    resistances = sorted([l for l in levels if l.kind == "resistance"], key=_score, reverse=True)
    supports = sorted([l for l in levels if l.kind == "support"], key=_score, reverse=True)
    return resistances[:_SR_MAX_PER_SIDE] + supports[:_SR_MAX_PER_SIDE]


# ──────────────────────  SMC displacement / OB / SD detection  ──────────────────────
#
# Per institutional / Smart Money Concept rules (user spec, supersedes the older
# Wyckoff-style range+breakout approach):
#
#   1. A **displacement leg** is ≥2 strong same-direction candles, each body
#      ≥ DISPLACEMENT_BODY_RATIO × rolling average body.
#   2. The **OB candidate candle** is the LAST opposite-color candle immediately
#      preceding the displacement leg (e.g. last bearish candle before a bullish
#      displacement = bullish OB).
#   3. **OrderBlock** = candidate where the displacement also CLOSED past the
#      most recent prior swing pivot (BOS — break of structure).
#   4. **SupplyDemandZone** = candidate without a structure break — same
#      institutional footprint but lower-conviction, drawn distinctly.
#   5. The zone uses the OB candle's BODY plus the wick on the displacement
#      side (textbook tight zone), not the full high-low.
#   6. Both detections drop:
#        - Zones with `test_count > 2` (over-tested, weak)
#        - Zones broken by a later close past the zone on the wrong side
#        - Counter-trend OBs in strongly trending markets (market structure filter)


_DISPLACEMENT_BODY_RATIO = 1.2          # each leg candle must be ≥ 1.2× avg body
_DISPLACEMENT_MIN_LENGTH = 2            # minimum candles in the leg
_DISPLACEMENT_MAX_LENGTH = 6            # don't chain forever — the leg is a *push*
_OB_LOOKBACK = 12                       # how far back to walk for the last opposite candle
_MAX_TEST_COUNT = 2                     # > 2 tests → weak, drop


@dataclass
class _DisplacementLeg:
    start_index: int
    end_index: int
    direction: Literal["bull", "bear"]
    total_body: float                   # sum of bodies across the leg


def _find_displacement_legs(candles: List[Candle], avg_body: float) -> List[_DisplacementLeg]:
    """Identify all impulsive same-direction sequences in the candle window."""
    n = len(candles)
    legs: List[_DisplacementLeg] = []
    bodies = [abs(c.close - c.open) for c in candles]
    threshold = _DISPLACEMENT_BODY_RATIO * avg_body

    i = 0
    while i < n - 1:
        if bodies[i] < threshold:
            i += 1
            continue
        c = candles[i]
        if c.close == c.open:
            i += 1
            continue
        is_bull = c.close > c.open

        # Walk forward collecting same-direction strong candles
        leg_start = i
        leg_end = i
        for j in range(i + 1, min(i + _DISPLACEMENT_MAX_LENGTH, n)):
            cj = candles[j]
            same_dir = (is_bull and cj.close > cj.open) or (not is_bull and cj.close < cj.open)
            if same_dir and bodies[j] >= threshold * 0.7:    # follow-through can be slightly weaker
                leg_end = j
            else:
                break

        # Need ≥ _DISPLACEMENT_MIN_LENGTH strong candles total
        strong_count = sum(1 for k in range(leg_start, leg_end + 1) if bodies[k] >= threshold)
        if strong_count >= _DISPLACEMENT_MIN_LENGTH:
            legs.append(_DisplacementLeg(
                start_index=leg_start,
                end_index=leg_end,
                direction="bull" if is_bull else "bear",
                total_body=sum(bodies[leg_start:leg_end + 1]),
            ))
            i = leg_end + 1
        else:
            i += 1
    return legs


def _last_opposite_candle(
    candles: List[Candle], before_index: int, want_bullish: bool, lookback: int = _OB_LOOKBACK,
) -> Optional[int]:
    """Walk backwards from `before_index - 1` returning the index of the most
    recent candle whose body color matches `want_bullish`. Returns None if no
    such candle exists in the lookback window or if the candle is exactly at
    the start of the window."""
    start = max(0, before_index - lookback)
    for i in range(before_index - 1, start - 1, -1):
        c = candles[i]
        if want_bullish and c.close > c.open:
            return i
        if not want_bullish and c.close < c.open:
            return i
    return None


def _has_fvg_in_leg(candles: List[Candle], leg: _DisplacementLeg) -> bool:
    """A 3-candle imbalance somewhere inside the displacement leg."""
    for i in range(leg.start_index + 1, leg.end_index):
        prev = candles[i - 1]
        nxt = candles[i + 1]
        if leg.direction == "bull" and prev.high < nxt.low:
            return True
        if leg.direction == "bear" and prev.low > nxt.high:
            return True
    return False


def _structure_broken(
    candles: List[Candle], swings: List[Swing], leg: _DisplacementLeg,
) -> bool:
    """Did any candle in the displacement close past the most recent prior
    swing pivot in the leg's direction? That's BOS by definition."""
    if leg.direction == "bull":
        prior = [s for s in swings if s.kind == "HIGH" and s.index < leg.start_index]
        if not prior:
            return False
        pivot_price = prior[-1].price
        return any(candles[k].close > pivot_price for k in range(leg.start_index, leg.end_index + 1))
    else:
        prior = [s for s in swings if s.kind == "LOW" and s.index < leg.start_index]
        if not prior:
            return False
        pivot_price = prior[-1].price
        return any(candles[k].close < pivot_price for k in range(leg.start_index, leg.end_index + 1))


def _ob_zone_bounds(candles: List[Candle], ob_idx: int, ob_kind: Literal["bullish", "bearish"]) -> tuple:
    """Tight zone: candle body + the wick on the displacement-facing side.

    - Bullish OB (bearish candle, future demand): body + LOWER wick
        top = open, bottom = low
    - Bearish OB (bullish candle, future supply): body + UPPER wick
        top = high, bottom = open
    """
    c = candles[ob_idx]
    if ob_kind == "bullish":
        return (c.open, c.low)        # top, bottom
    return (c.high, c.open)


def _zone_lifecycle(
    candles: List[Candle], top: float, bottom: float, kind_is_bullish: bool, after_index: int,
) -> tuple:
    """Walk forward from `after_index + 1` and return `(test_count, is_fresh, is_broken)`.

    - **Test** = candle wicks into the zone but doesn't close past it.
    - **Broken** = candle closes past the zone on the wrong side (bullish OB
      broken when a candle closes BELOW bottom; bearish OB broken when a
      candle closes ABOVE top).
    """
    test_count = 0
    in_zone = False
    is_broken = False
    for j in range(after_index + 1, len(candles)):
        cj = candles[j]
        if kind_is_bullish:
            if cj.close < bottom:
                is_broken = True
                break
            touching = cj.low <= top
        else:
            if cj.close > top:
                is_broken = True
                break
            touching = cj.high >= bottom

        # Count a test only on the entry into the zone, not every bar inside it.
        if touching and not in_zone:
            test_count += 1
            in_zone = True
        elif not touching and in_zone:
            in_zone = False

    return test_count, (test_count == 0), is_broken


def _smc_candidates(
    candles: List[Candle], swings: List[Swing],
) -> List[tuple]:
    """Return all SMC OB candidates as
    `(ob_idx, ob_kind, leg, structure_break, fvg, top, bottom, test_count, is_fresh)`.
    OB and SD detectors filter this list with their own rules."""
    n = len(candles)
    if n < 5:
        return []
    bodies = [abs(c.close - c.open) for c in candles]
    avg_body = (sum(bodies) / n) or 1e-9

    legs = _find_displacement_legs(candles, avg_body)
    out: List[tuple] = []
    for leg in legs:
        ob_kind: Literal["bullish", "bearish"] = (
            "bullish" if leg.direction == "bull" else "bearish"
        )
        # Bullish OB = last bearish candle before bullish displacement (and vice versa)
        want_bullish_color = (leg.direction == "bear")
        ob_idx = _last_opposite_candle(candles, leg.start_index, want_bullish=want_bullish_color)
        if ob_idx is None:
            continue

        top, bottom = _ob_zone_bounds(candles, ob_idx, ob_kind)
        if top <= bottom:
            continue

        test_count, is_fresh, is_broken = _zone_lifecycle(
            candles, top, bottom, kind_is_bullish=(ob_kind == "bullish"),
            after_index=leg.end_index,
        )
        if is_broken:
            continue

        sb = _structure_broken(candles, swings, leg)
        fvg = _has_fvg_in_leg(candles, leg)

        out.append((ob_idx, ob_kind, leg, sb, fvg, top, bottom, test_count, is_fresh))
    return out


def _market_structure_filter(
    items: list, kind_attr: str, trend: Optional[str],
) -> list:
    """In a strongly-trending market, drop counter-trend zones — they're the
    "weak bullish OBs in a bearish trend" the user flagged.

    `kind_attr` is the attribute name holding 'bullish'/'bearish' (OB) or
    'demand'/'supply' (SD) — the function maps both to a directional bias.
    """
    if trend not in ("bullish", "bearish"):
        return items

    def _aligned(item) -> bool:
        v = getattr(item, kind_attr)
        if trend == "bullish":
            return v in ("bullish", "demand")
        return v in ("bearish", "supply")

    aligned = [i for i in items if _aligned(i)]
    counter = [i for i in items if not _aligned(i)]
    # Keep all aligned + at most ONE recent counter-trend zone (so the chart
    # still surfaces the strongest opposing level for context).
    return aligned + counter[:1]


def _dedup_overlap(items: list, kind_attr: str, top_attr: str, bottom_attr: str,
                    overlap_skip: float = 0.5, max_items: int = 4) -> list:
    """Drop same-kind items that overlap > `overlap_skip` of the candidate's size."""
    deduped: list = []
    for it in items:
        size = max(getattr(it, top_attr) - getattr(it, bottom_attr), 1e-9)
        skip = False
        for kept in deduped:
            if getattr(kept, kind_attr) != getattr(it, kind_attr):
                continue
            ot = min(getattr(it, top_attr), getattr(kept, top_attr))
            ob_ = max(getattr(it, bottom_attr), getattr(kept, bottom_attr))
            if ot > ob_ and (ot - ob_) / size > overlap_skip:
                skip = True
                break
        if skip:
            continue
        deduped.append(it)
        if len(deduped) >= max_items:
            break
    return deduped


def _detect_order_blocks(
    candles: List[Candle],
    swings: Optional[List[Swing]] = None,
    trend: Optional[str] = None,
    *,
    max_obs: int = 3,
) -> List[OrderBlock]:
    """Strict SMC OB: candidate must have a structure break (BOS).

    The structure-break filter is what makes an OB "institutional" rather than
    just a continuation footprint — the displacement broke a prior swing pivot,
    proving the institutional move shifted market structure.
    """
    swings = swings or []
    cands = _smc_candidates(candles, swings)

    obs: List[OrderBlock] = []
    for ob_idx, ob_kind, leg, sb, fvg, top, bottom, test_count, is_fresh in cands:
        if not sb:
            continue                                # OBs require BOS
        if test_count > _MAX_TEST_COUNT:
            continue                                # > 2 tests → weak, drop
        obs.append(OrderBlock(
            kind=ob_kind,
            top=top,
            bottom=bottom,
            candle_index=ob_idx,
            candle_time=candles[ob_idx].time,
            displacement_start_index=leg.start_index,
            displacement_end_index=leg.end_index,
            displacement_strength=leg.total_body / max(
                sum(abs(c.close - c.open) for c in candles) / max(len(candles), 1), 1e-9),
            structure_break=sb,
            fvg_inside=fvg,
            test_count=test_count,
            is_fresh=is_fresh,
        ))

    # Most-recent first, with FVG-confirmed OBs preferred (better setups)
    obs.sort(key=lambda o: (o.displacement_end_index, o.fvg_inside, o.is_fresh,
                             o.displacement_strength), reverse=True)
    obs = _market_structure_filter(obs, "kind", trend)
    return _dedup_overlap(obs, "kind", "top", "bottom", max_items=max_obs)


def _detect_supply_demand_zones(
    candles: List[Candle],
    swings: Optional[List[Swing]] = None,
    trend: Optional[str] = None,
    *,
    max_zones: int = 4,
) -> List[SupplyDemandZone]:
    """Same SMC pattern as OB but **without** the BOS requirement.

    Filters out candidates that would also qualify as an OB (structure-break
    candidates are rendered as OBs instead, avoiding double-drawing).
    """
    swings = swings or []
    cands = _smc_candidates(candles, swings)

    zones: List[SupplyDemandZone] = []
    for ob_idx, ob_kind, leg, sb, _fvg, top, bottom, test_count, is_fresh in cands:
        if sb:
            continue                                # structure-break ones become OBs
        if test_count > _MAX_TEST_COUNT:
            continue
        kind: Literal["supply", "demand"] = "demand" if ob_kind == "bullish" else "supply"
        zones.append(SupplyDemandZone(
            kind=kind,
            top=top,
            bottom=bottom,
            candle_index=ob_idx,
            candle_time=candles[ob_idx].time,
            displacement_start_index=leg.start_index,
            displacement_end_index=leg.end_index,
            displacement_strength=leg.total_body / max(
                sum(abs(c.close - c.open) for c in candles) / max(len(candles), 1), 1e-9),
            test_count=test_count,
            is_fresh=is_fresh,
        ))

    zones.sort(key=lambda z: (z.displacement_end_index, z.is_fresh,
                                z.displacement_strength), reverse=True)
    zones = _market_structure_filter(zones, "kind", trend)
    return _dedup_overlap(zones, "kind", "top", "bottom", max_items=max_zones)


# ──────────────────────  CHoCH detection  ──────────────────────

# ──────────────────────  Major-swing filter (shared by BoS and CHoCH)  ──────────────────────
#
# Per the user's SMC spec ("internal vs external structure"): minor swings are
# noise — they create false BoS/CHoCH signals. A "major" (external) swing is
# one whose price magnitude into AND out of it is at least N × ATR. This drops
# small wiggles that aren't part of the meaningful trend structure.

def _atr(candles: List[Candle]) -> float:
    """Simple ATR proxy = mean candle high-low across the window."""
    if not candles:
        return 1e-9
    return (sum(c.high - c.low for c in candles) / len(candles)) or 1e-9


def _avg_body(candles: List[Candle]) -> float:
    if not candles:
        return 1e-9
    return (sum(abs(c.close - c.open) for c in candles) / len(candles)) or 1e-9


def major_swings(swings: List[Swing], candles: List[Candle], *, atr_multiple: float = 1.5) -> List[Swing]:
    """Drop swings whose move-in OR move-out magnitude is < `atr_multiple` × ATR.

    Endpoints are always kept — without them the alternation pattern breaks.
    If filtering reduces the count below 3, we fall back to the original list
    (low-volatility datasets shouldn't produce zero swings).
    """
    if len(swings) < 3:
        return swings
    threshold = _atr(candles) * atr_multiple

    out: List[Swing] = [swings[0]]
    for i in range(1, len(swings) - 1):
        cur = swings[i]
        in_move = abs(cur.price - swings[i - 1].price)
        out_move = abs(swings[i + 1].price - cur.price)
        if in_move >= threshold and out_move >= threshold:
            out.append(cur)
    out.append(swings[-1])

    if len(out) < 3:
        return swings
    return out


def _classify_swing_trend(swings: List[Swing], lookback: int = 4) -> Literal["bullish", "bearish", "sideways"]:
    """Classify trend from the last `lookback` swings.

    Bullish: highs trend up AND lows trend up (HH/HL pattern).
    Bearish: highs trend down AND lows trend down (LH/LL pattern).
    """
    recent = swings[-lookback:] if len(swings) >= lookback else swings
    highs = [s for s in recent if s.kind == "HIGH"]
    lows = [s for s in recent if s.kind == "LOW"]
    if len(highs) < 2 or len(lows) < 2:
        return "sideways"
    bull = (highs[-1].price > highs[0].price) + (lows[-1].price > lows[0].price)
    bear = (highs[-1].price < highs[0].price) + (lows[-1].price < lows[0].price)
    if bull >= 2 and bear == 0:
        return "bullish"
    if bear >= 2 and bull == 0:
        return "bearish"
    return "sideways"


# ──────────────────────  Structure breaks (BoS + CHoCH)  ──────────────────────
#
# Detection logic ported from the "Multi Length Market Structure (BoS + ChoCh)"
# Pine Script indicator (Uncle_the_shooter, MPL-2.0). The Pine Script's elegant
# state-machine approach replaced the earlier strict-trend-gated detector,
# which was over-restrictive (suppressed valid BoS on real data with mixed
# global structure).
#
# Algorithm:
#   1. Compute pivot highs/lows (already done by `detect_swings(window=5)`,
#      equivalent to Pine's `ta.pivothigh(high, 5, 5)`).
#   2. Apply the major-swing filter so internal noise pivots aren't tracked.
#   3. Walk forward through candles. For each bar, find the most-recent
#      UNBROKEN pivot high (and low) formed before the bar.
#   4. If `close > last_unbroken_high`: it's a break-up event. Mark that
#      pivot as broken (so it can't trigger again).
#   5. If `close < last_unbroken_low`: break-down event.
#   6. Classify each event:
#        - First break, or break in the SAME direction as the last → **BoS**
#          (continuation — confirms the existing direction).
#        - Break in the OPPOSITE direction of the last → **CHoCH**
#          (reversal — direction flipped).
#   7. Return the most recent BoS and the most recent CHoCH.
#
# This is much cleaner than tracking "established trend" via swing patterns:
# the trend state IS the last break direction, and structure events naturally
# alternate between continuation and reversal.


# Helper functions still used by other detectors (zones, OBs, CHoCH alignment
# in higher-level code). Keep available even though _detect_structure_breaks
# itself no longer uses them.

def _established_trend_at(
    swings: List[Swing],
    min_separation: float = 0.0,
) -> Literal["bullish", "bearish", "sideways"]:
    """Classify trend by the last 2 highs and last 2 lows. Returns "sideways"
    unless both show clear HH+HL (bullish) or LH+LL (bearish) with at least
    `min_separation` price difference. Used by other detectors that want a
    snapshot trend; not used by structure-break tracking itself."""
    highs = [s for s in swings if s.kind == "HIGH"]
    lows = [s for s in swings if s.kind == "LOW"]
    if len(highs) < 2 or len(lows) < 2:
        return "sideways"
    last_hh = highs[-1].price > highs[-2].price + min_separation
    last_hl = lows[-1].price > lows[-2].price + min_separation
    if last_hh and last_hl:
        return "bullish"
    last_lh = highs[-1].price + min_separation < highs[-2].price
    last_ll = lows[-1].price + min_separation < lows[-2].price
    if last_lh and last_ll:
        return "bearish"
    return "sideways"


def _detect_structure_breaks(
    swings: List[Swing], candles: Optional[List[Candle]] = None,
) -> tuple:
    """Pine-Script-derived BoS/CHoCH state machine.

    Returns `(last_bos, last_choch)` — the most recent event of each kind
    after walking the full candle stream chronologically.
    """
    if not candles or len(swings) < 2:
        return (None, None)

    # Major-swing filter: drops minor pivots so structure breaks only fire on
    # meaningful levels. Equivalent to picking a longer pivot length in Pine.
    swings_major = major_swings(swings, candles)
    if not swings_major:
        return (None, None)

    high_pivots = sorted([s for s in swings_major if s.kind == "HIGH"], key=lambda s: s.index)
    low_pivots = sorted([s for s in swings_major if s.kind == "LOW"], key=lambda s: s.index)
    if not high_pivots and not low_pivots:
        return (None, None)

    broken_high_indices: set = set()
    broken_low_indices: set = set()
    last_break_dir = 0                          # 1 = up, -1 = down, 0 = none yet
    last_bos: Optional[BoS] = None
    last_choch: Optional[CHoCH] = None

    # Pointers walk forward through pivot lists so we don't rescan from the
    # beginning every bar (O(N + M) total instead of O(N × M)).
    high_idx = 0    # next high pivot to consider as "active" once its index <= bar
    low_idx = 0

    for i in range(len(candles)):
        c = candles[i]

        # Advance pointers so they reference the NEWEST pivot whose index < i.
        while high_idx + 1 < len(high_pivots) and high_pivots[high_idx + 1].index < i:
            high_idx += 1
        while low_idx + 1 < len(low_pivots) and low_pivots[low_idx + 1].index < i:
            low_idx += 1

        # Find the most recent UNBROKEN pivot of each kind formed before i.
        last_unbroken_high: Optional[Swing] = None
        for k in range(high_idx, -1, -1):
            hp = high_pivots[k]
            if hp.index >= i:
                continue
            if hp.index in broken_high_indices:
                continue
            last_unbroken_high = hp
            break

        last_unbroken_low: Optional[Swing] = None
        for k in range(low_idx, -1, -1):
            lp = low_pivots[k]
            if lp.index >= i:
                continue
            if lp.index in broken_low_indices:
                continue
            last_unbroken_low = lp
            break

        # Break-up: close exceeds the last unbroken pivot high.
        if last_unbroken_high is not None and c.close > last_unbroken_high.price:
            broken_high_indices.add(last_unbroken_high.index)
            if last_break_dir == -1:
                # Direction flipped from down to up → CHoCH
                last_choch = CHoCH(
                    direction="bullish",
                    pivot_index=last_unbroken_high.index,
                    pivot_price=last_unbroken_high.price,
                    pivot_time=last_unbroken_high.time,
                    break_index=i,
                    break_time=c.time,
                )
            else:
                # First break or continuation → BoS
                last_bos = BoS(
                    direction="bullish",
                    pivot_index=last_unbroken_high.index,
                    pivot_price=last_unbroken_high.price,
                    pivot_time=last_unbroken_high.time,
                    break_index=i,
                    break_time=c.time,
                )
            last_break_dir = 1

        # Break-down: close goes below the last unbroken pivot low. (Can't
        # happen on the same bar as a break-up since high pivot > low pivot.)
        elif last_unbroken_low is not None and c.close < last_unbroken_low.price:
            broken_low_indices.add(last_unbroken_low.index)
            if last_break_dir == 1:
                last_choch = CHoCH(
                    direction="bearish",
                    pivot_index=last_unbroken_low.index,
                    pivot_price=last_unbroken_low.price,
                    pivot_time=last_unbroken_low.time,
                    break_index=i,
                    break_time=c.time,
                )
            else:
                last_bos = BoS(
                    direction="bearish",
                    pivot_index=last_unbroken_low.index,
                    pivot_price=last_unbroken_low.price,
                    pivot_time=last_unbroken_low.time,
                    break_index=i,
                    break_time=c.time,
                )
            last_break_dir = -1

    return (last_bos, last_choch)


# Backwards-compatible thin wrappers — older code calls these by name.
def _detect_choch(swings: List[Swing], candles: Optional[List[Candle]] = None) -> Optional[CHoCH]:
    """Backwards-compat wrapper — delegates to `_detect_structure_breaks`."""
    return _detect_structure_breaks(swings, candles)[1]


def _detect_bos(swings: List[Swing], candles: Optional[List[Candle]] = None) -> Optional[BoS]:
    """Backwards-compat wrapper — delegates to `_detect_structure_breaks`."""
    return _detect_structure_breaks(swings, candles)[0]
