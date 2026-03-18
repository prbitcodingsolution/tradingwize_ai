"""
Smart Money Concepts (SMC) Indicator - Python Implementation
============================================================
Converted from LuxAlgo's Pine Script SMC indicator.
Draws: BOS, CHoCH, Order Blocks, Fair Value Gaps, Equal Highs/Lows,
       Premium/Discount Zones, Strong/Weak Highs & Lows.

Requirements:
    pip install pandas numpy matplotlib yfinance

Usage:
    from smc_indicator import SMCIndicator
    import yfinance as yf

    df = yf.download("AAPL", period="6mo", interval="1d")
    smc = SMCIndicator(df)
    smc.run()
    smc.plot()
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyArrowPatch
import warnings
warnings.filterwarnings("ignore")


# ─────────────────────────────────────────────────────────────
#  CONSTANTS
# ─────────────────────────────────────────────────────────────
BULLISH = 1
BEARISH = -1

GREEN   = "#089981"
RED     = "#F23645"
BLUE    = "#2157f3"
GRAY    = "#878b94"


# ─────────────────────────────────────────────────────────────
#  DATA STRUCTURES
# ─────────────────────────────────────────────────────────────
class Pivot:
    """Represents a swing pivot point (high or low)."""
    def __init__(self):
        self.current_level = np.nan
        self.last_level    = np.nan
        self.crossed       = False
        self.bar_index     = -1

class Trend:
    """Tracks the current trend bias."""
    def __init__(self):
        self.bias = 0   # 0 = unknown, BULLISH = 1, BEARISH = -1

class OrderBlock:
    """Represents an order block zone."""
    def __init__(self, bar_high, bar_low, bar_index, bias):
        self.bar_high  = bar_high
        self.bar_low   = bar_low
        self.bar_index = bar_index
        self.bias      = bias   # BULLISH or BEARISH

class FairValueGap:
    """Represents a fair value gap."""
    def __init__(self, top, bottom, bias, left_idx, right_idx):
        self.top       = top
        self.bottom    = bottom
        self.bias      = bias
        self.left_idx  = left_idx
        self.right_idx = right_idx

class StructureEvent:
    """A detected BOS or CHoCH event."""
    def __init__(self, bar_index, price, tag, bias):
        self.bar_index = bar_index
        self.price     = price
        self.tag       = tag    # 'BOS' or 'CHoCH'
        self.bias      = bias   # BULLISH or BEARISH

class EqualLevel:
    """Equal high or equal low detection."""
    def __init__(self, idx1, idx2, price, kind):
        self.idx1  = idx1
        self.idx2  = idx2
        self.price = price
        self.kind  = kind   # 'EQH' or 'EQL'


# ─────────────────────────────────────────────────────────────
#  MAIN INDICATOR CLASS
# ─────────────────────────────────────────────────────────────
class SMCIndicator:
    """
    Smart Money Concepts indicator.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe with columns: Open, High, Low, Close, Volume.
        Index should be datetime.
    swing_length : int
        Lookback length for swing structure detection (default 50).
    internal_length : int
        Lookback length for internal structure detection (default 5).
    ob_filter : str
        Order block filter method: 'atr' or 'range'.
    ob_mitigation : str
        Order block mitigation source: 'close' or 'highlow'.
    eql_length : int
        Bars confirmation for equal highs/lows (default 3).
    eql_threshold : float
        Sensitivity for equal highs/lows detection (default 0.1).
    max_obs : int
        Max order blocks to display per side (default 5).
    """

    def __init__(
        self,
        df: pd.DataFrame,
        swing_length:    int   = 50,
        internal_length: int   = 5,
        ob_filter:       str   = "atr",
        ob_mitigation:   str   = "highlow",
        eql_length:      int   = 3,
        eql_threshold:   float = 0.1,
        max_obs:         int   = 5,
    ):
        # ── normalise column names ──────────────────────────────
        self.df = df.copy()
        self.df.columns = [c.capitalize() for c in self.df.columns]
        self.df = self.df.reset_index(drop=False)

        # keep a plain integer index for all internal arrays
        self.n = len(self.df)

        self.swing_length    = swing_length
        self.internal_length = internal_length
        self.ob_filter       = ob_filter
        self.ob_mitigation   = ob_mitigation
        self.eql_length      = eql_length
        self.eql_threshold   = eql_threshold
        self.max_obs         = max_obs

        # ── result containers ───────────────────────────────────
        self.swing_structure:    list[StructureEvent] = []
        self.internal_structure: list[StructureEvent] = []
        self.swing_obs:          list[OrderBlock]     = []
        self.internal_obs:       list[OrderBlock]     = []
        self.fvgs:               list[FairValueGap]   = []
        self.equal_levels:       list[EqualLevel]     = []

        # strong / weak high-low
        self.strong_high: float = np.nan
        self.weak_high:   float = np.nan
        self.strong_low:  float = np.nan
        self.weak_low:    float = np.nan
        self.strong_high_idx: int = 0
        self.strong_low_idx:  int = 0

        # premium / discount
        self.swing_top:    float = np.nan
        self.swing_bottom: float = np.nan
        self.swing_top_idx: int  = 0

    # ────────────────────────────────────────────────────────
    #  HELPERS
    # ────────────────────────────────────────────────────────
    def _atr(self, period=200):
        """Average True Range."""
        hi, lo, cl = (self.df["High"].values,
                      self.df["Low"].values,
                      self.df["Close"].values)
        tr = np.maximum(hi - lo,
             np.maximum(np.abs(hi - np.roll(cl, 1)),
                        np.abs(lo - np.roll(cl, 1))))
        tr[0] = hi[0] - lo[0]
        atr = pd.Series(tr).rolling(period, min_periods=1).mean().values
        return atr

    def _volatility_measure(self):
        hi  = self.df["High"].values
        lo  = self.df["Low"].values
        cl  = self.df["Close"].values
        tr  = np.maximum(hi - lo,
              np.maximum(np.abs(hi - np.roll(cl, 1)),
                         np.abs(lo - np.roll(cl, 1))))
        tr[0] = hi[0] - lo[0]
        if self.ob_filter == "atr":
            return self._atr(200)
        else:
            return np.cumsum(tr) / (np.arange(self.n) + 1)

    def _get_leg(self, i, size):
        """Return leg direction at bar i using lookback = size."""
        if i < size:
            return 0
        window_hi = self.df["High"].values[i - size: i]
        window_lo = self.df["Low"].values[i - size: i]
        hi_i = self.df["High"].values[i - size]
        lo_i = self.df["Low"].values[i - size]
        if hi_i > window_hi.max():
            return 0   # bearish leg
        if lo_i < window_lo.min():
            return 1   # bullish leg
        return -99     # no change

    # ────────────────────────────────────────────────────────
    #  SWING DETECTION  (the core leg() logic from Pine)
    # ────────────────────────────────────────────────────────
    def _detect_swings(self, size):
        """
        Detect pivot highs and lows using a rolling leg approach.
        Returns two lists: pivot_highs, pivot_lows
        Each entry: (bar_index_of_pivot, price)
        """
        hi = self.df["High"].values
        lo = self.df["Low"].values

        pivot_highs = []
        pivot_lows  = []

        prev_leg = None

        for i in range(size, self.n):
            # highest / lowest over the NEXT `size` bars after pivot candidate
            if i + size > self.n:
                break

            is_ph = hi[i] == hi[max(0, i - size): i + size + 1].max()
            is_pl = lo[i] == lo[max(0, i - size): i + size + 1].min()

            # simple pivot: confirmed `size` bars later → record at i
            if is_ph:
                pivot_highs.append((i, hi[i]))
            if is_pl:
                pivot_lows.append((i, lo[i]))

        return pivot_highs, pivot_lows

    # ────────────────────────────────────────────────────────
    #  STRUCTURE (BOS / CHoCH)
    # ────────────────────────────────────────────────────────
    def _detect_structure(self, pivot_highs, pivot_lows, internal=False):
        """
        Given pivot highs and lows, detect BOS and CHoCH events.
        Mirrors displayStructure() from Pine Script.
        """
        cl = self.df["Close"].values
        events: list[StructureEvent] = []

        trend_bias  = 0
        ph_ptr      = 0   # pointer into pivot_highs
        pl_ptr      = 0   # pointer into pivot_lows
        ph_crossed  = False
        pl_crossed  = False

        # merge pivots into chronological order
        all_pivots = sorted(
            [("H", idx, price) for idx, price in pivot_highs] +
            [("L", idx, price) for idx, price in pivot_lows],
            key=lambda x: x[1]
        )

        last_ph = (None, np.nan)   # (bar_idx, price)
        last_pl = (None, np.nan)   # (bar_idx, price)
        ph_cross = False
        pl_cross = False

        # ── walk bars and check for crossovers ─────────────────
        for kind, pivot_idx, pivot_price in all_pivots:
            if kind == "H":
                last_ph = (pivot_idx, pivot_price)
                ph_cross = False
            else:
                last_pl = (pivot_idx, pivot_price)
                pl_cross = False

        # Re-do properly: track last pivot high / low in order
        last_ph_idx, last_ph_price = None, np.nan
        last_pl_idx, last_pl_price = None, np.nan
        ph_crossed_flag = False
        pl_crossed_flag = False

        pivot_q = sorted(
            [("H", i, p) for i, p in pivot_highs] +
            [("L", i, p) for i, p in pivot_lows],
            key=lambda x: x[1]
        )

        # We iterate bar by bar and check crossovers with latest pivot
        active_ph = None  # (idx, price, crossed)
        active_pl = None

        # index pivot events by bar
        ph_by_bar = {i: p for i, p in pivot_highs}
        pl_by_bar = {i: p for i, p in pivot_lows}

        trend_bias  = 0
        active_ph   = None   # [idx, price, crossed]
        active_pl   = None

        for i in range(self.n):
            # update active pivots when we hit their bar
            if i in ph_by_bar:
                active_ph = [i, ph_by_bar[i], False]
            if i in pl_by_bar:
                active_pl = [i, pl_by_bar[i], False]

            # check bullish crossover (close > last pivot high)
            if (active_ph is not None and
                    not active_ph[2] and
                    cl[i] > active_ph[1]):

                tag = "CHoCH" if trend_bias == BEARISH else "BOS"
                events.append(StructureEvent(i, active_ph[1], tag, BULLISH))
                active_ph[2] = True
                trend_bias   = BULLISH

                # store order block
                ob = self._build_ob(active_ph[0], i, BULLISH)
                if ob:
                    (self.internal_obs if internal else self.swing_obs).append(ob)

            # check bearish crossover (close < last pivot low)
            if (active_pl is not None and
                    not active_pl[2] and
                    cl[i] < active_pl[1]):

                tag = "CHoCH" if trend_bias == BULLISH else "BOS"
                events.append(StructureEvent(i, active_pl[1], tag, BEARISH))
                active_pl[2] = True
                trend_bias   = BEARISH

                ob = self._build_ob(active_pl[0], i, BEARISH)
                if ob:
                    (self.internal_obs if internal else self.swing_obs).append(ob)

        return events

    # ────────────────────────────────────────────────────────
    #  ORDER BLOCKS
    # ────────────────────────────────────────────────────────
    def _build_ob(self, pivot_idx, break_idx, bias):
        """Find the best order block candle between pivot and break."""
        if pivot_idx is None or break_idx <= pivot_idx:
            return None

        vol   = self._volatility_measure()
        hi    = self.df["High"].values
        lo    = self.df["Low"].values

        segment_hi = hi[pivot_idx: break_idx]
        segment_lo = lo[pivot_idx: break_idx]

        # high-volatility bars get inverted (same logic as parsedHigh/parsedLow)
        parsed_hi = np.where(
            (hi[pivot_idx: break_idx] - lo[pivot_idx: break_idx]) >= 2 * vol[pivot_idx: break_idx],
            lo[pivot_idx: break_idx],
            hi[pivot_idx: break_idx]
        )
        parsed_lo = np.where(
            (hi[pivot_idx: break_idx] - lo[pivot_idx: break_idx]) >= 2 * vol[pivot_idx: break_idx],
            hi[pivot_idx: break_idx],
            lo[pivot_idx: break_idx]
        )

        if bias == BULLISH:
            local_idx = int(np.argmin(parsed_lo))
        else:
            local_idx = int(np.argmax(parsed_hi))

        bar_idx = pivot_idx + local_idx
        return OrderBlock(hi[bar_idx], lo[bar_idx], bar_idx, bias)

    def _mitigate_obs(self, obs: list[OrderBlock]):
        """Remove order blocks that have been mitigated by price."""
        cl = self.df["Close"].values
        hi = self.df["High"].values
        lo = self.df["Low"].values

        surviving = []
        for ob in obs:
            mitigated = False
            for i in range(ob.bar_index + 1, self.n):
                if ob.bias == BEARISH:
                    src = cl[i] if self.ob_mitigation == "close" else hi[i]
                    if src > ob.bar_high:
                        mitigated = True
                        break
                else:
                    src = cl[i] if self.ob_mitigation == "close" else lo[i]
                    if src < ob.bar_low:
                        mitigated = True
                        break
            if not mitigated:
                surviving.append(ob)
        return surviving

    # ────────────────────────────────────────────────────────
    #  FAIR VALUE GAPS
    # ────────────────────────────────────────────────────────
    def _detect_fvgs(self):
        hi = self.df["High"].values
        lo = self.df["Low"].values
        cl = self.df["Close"].values
        op = self.df["Open"].values

        fvgs = []
        for i in range(2, self.n):
            # bullish FVG: candle[i] low > candle[i-2] high
            if lo[i] > hi[i - 2] and cl[i - 1] > hi[i - 2]:
                fvgs.append(FairValueGap(
                    top=lo[i], bottom=hi[i - 2],
                    bias=BULLISH,
                    left_idx=i - 1, right_idx=i
                ))
            # bearish FVG: candle[i] high < candle[i-2] low
            if hi[i] < lo[i - 2] and cl[i - 1] < lo[i - 2]:
                fvgs.append(FairValueGap(
                    top=lo[i - 2], bottom=hi[i],
                    bias=BEARISH,
                    left_idx=i - 1, right_idx=i
                ))

        # remove mitigated FVGs
        surviving = []
        for fvg in fvgs:
            mitigated = False
            for i in range(fvg.right_idx + 1, self.n):
                if fvg.bias == BULLISH and lo[i] < fvg.bottom:
                    mitigated = True
                    break
                if fvg.bias == BEARISH and hi[i] > fvg.top:
                    mitigated = True
                    break
            if not mitigated:
                surviving.append(fvg)

        return surviving

    # ────────────────────────────────────────────────────────
    #  EQUAL HIGHS / LOWS
    # ────────────────────────────────────────────────────────
    def _detect_equal_levels(self, pivot_highs, pivot_lows):
        atr = self._atr(200)
        levels = []

        # EQH
        for i in range(1, len(pivot_highs)):
            idx1, p1 = pivot_highs[i - 1]
            idx2, p2 = pivot_highs[i]
            threshold = self.eql_threshold * atr[idx2]
            if abs(p1 - p2) < threshold:
                levels.append(EqualLevel(idx1, idx2, (p1 + p2) / 2, "EQH"))

        # EQL
        for i in range(1, len(pivot_lows)):
            idx1, p1 = pivot_lows[i - 1]
            idx2, p2 = pivot_lows[i]
            threshold = self.eql_threshold * atr[idx2]
            if abs(p1 - p2) < threshold:
                levels.append(EqualLevel(idx1, idx2, (p1 + p2) / 2, "EQL"))

        return levels

    # ────────────────────────────────────────────────────────
    #  STRONG / WEAK HIGH & LOW  +  PREMIUM / DISCOUNT
    # ────────────────────────────────────────────────────────
    def _detect_trailing_extremes(self):
        hi = self.df["High"].values
        lo = self.df["Low"].values

        self.swing_top      = hi.max()
        self.swing_bottom   = lo.min()
        self.swing_top_idx  = int(np.argmax(hi))
        self.swing_bot_idx  = int(np.argmin(lo))

        # strong/weak based on last swing structure bias
        if self.swing_structure:
            last = self.swing_structure[-1]
            if last.bias == BULLISH:
                self.strong_low  = self.swing_bottom
                self.weak_high   = self.swing_top
                self.strong_high = np.nan
                self.weak_low    = np.nan
            else:
                self.strong_high = self.swing_top
                self.weak_low    = self.swing_bottom
                self.strong_low  = np.nan
                self.weak_high   = np.nan
        else:
            self.strong_high = self.swing_top
            self.strong_low  = self.swing_bottom

    # ────────────────────────────────────────────────────────
    #  RUN ALL DETECTIONS
    # ────────────────────────────────────────────────────────
    def run(self):
        """Run all SMC detections. Call this before plot()."""

        # 1. Detect swing pivots at two lookback sizes
        swing_ph, swing_pl       = self._detect_swings(self.swing_length)
        internal_ph, internal_pl = self._detect_swings(self.internal_length)

        # 2. Market structure
        self.swing_structure    = self._detect_structure(swing_ph, swing_pl, internal=False)
        self.internal_structure = self._detect_structure(internal_ph, internal_pl, internal=True)

        # 3. Mitigate order blocks
        self.swing_obs    = self._mitigate_obs(self.swing_obs)[-self.max_obs:]
        self.internal_obs = self._mitigate_obs(self.internal_obs)[-self.max_obs:]

        # 4. Fair value gaps
        self.fvgs = self._detect_fvgs()

        # 5. Equal highs / lows
        self.equal_levels = self._detect_equal_levels(swing_ph, swing_pl)

        # 6. Trailing extremes (strong/weak + premium/discount)
        self._detect_trailing_extremes()

        print(f"[SMC] Swing BOS/CHoCH    : {len(self.swing_structure)}")
        print(f"[SMC] Internal BOS/CHoCH : {len(self.internal_structure)}")
        print(f"[SMC] Swing OBs          : {len(self.swing_obs)}")
        print(f"[SMC] Internal OBs       : {len(self.internal_obs)}")
        print(f"[SMC] FVGs               : {len(self.fvgs)}")
        print(f"[SMC] Equal Levels       : {len(self.equal_levels)}")

    # ────────────────────────────────────────────────────────
    #  PLOTTING
    # ────────────────────────────────────────────────────────
    def plot(self, last_n_bars: int = 200, figsize=(22, 12)):
        """
        Plot the SMC indicator on a candlestick chart.

        Parameters
        ----------
        last_n_bars : int
            How many recent bars to display (default 200).
        figsize : tuple
            Figure size.
        """
        df   = self.df.tail(last_n_bars).copy()
        df   = df.reset_index(drop=True)
        offset = len(self.df) - last_n_bars   # bar index offset

        hi = df["High"].values
        lo = df["Low"].values
        op = df["Open"].values
        cl = df["Close"].values
        n  = len(df)

        fig, ax = plt.subplots(figsize=figsize, facecolor="#131722")
        ax.set_facecolor("#131722")
        ax.tick_params(colors="white")
        ax.spines["bottom"].set_color("#2a2e39")
        ax.spines["top"].set_color("#2a2e39")
        ax.spines["left"].set_color("#2a2e39")
        ax.spines["right"].set_color("#2a2e39")

        # ── 1. Candlesticks ────────────────────────────────────
        for i in range(n):
            color = GREEN if cl[i] >= op[i] else RED
            # body
            ax.bar(i, abs(cl[i] - op[i]),
                   bottom=min(cl[i], op[i]),
                   color=color, width=0.6, zorder=3)
            # wick
            ax.plot([i, i], [lo[i], hi[i]],
                    color=color, linewidth=0.8, zorder=3)

        # ── 2. Swing Structure (BOS / CHoCH) ──────────────────
        for ev in self.swing_structure:
            idx = ev.bar_index - offset
            if not (0 <= idx < n):
                continue
            color = GREEN if ev.bias == BULLISH else RED
            ls    = "-"
            ax.axhline(ev.price, xmin=idx / n, xmax=1.0,
                       color=color, linewidth=1.2, linestyle=ls,
                       alpha=0.9, zorder=4)
            va    = "top" if ev.bias == BULLISH else "bottom"
            ax.text(idx, ev.price, f" {ev.tag}",
                    color=color, fontsize=6.5, va=va, zorder=5)

        # ── 3. Internal Structure (dashed) ────────────────────
        for ev in self.internal_structure:
            idx = ev.bar_index - offset
            if not (0 <= idx < n):
                continue
            color = GREEN if ev.bias == BULLISH else RED
            ax.axhline(ev.price, xmin=idx / n, xmax=1.0,
                       color=color, linewidth=0.8, linestyle="--",
                       alpha=0.6, zorder=4)
            va = "top" if ev.bias == BULLISH else "bottom"
            ax.text(idx, ev.price, f" {ev.tag}",
                    color=color, fontsize=5.5, va=va, alpha=0.8, zorder=5)

        # ── 4. Swing Order Blocks ─────────────────────────────
        for ob in self.swing_obs:
            idx = ob.bar_index - offset
            if not (0 <= idx < n):
                continue
            color = "#1848cc" if ob.bias == BULLISH else "#b22833"
            rect = mpatches.FancyBboxPatch(
                (idx - 0.4, ob.bar_low),
                n - idx,
                ob.bar_high - ob.bar_low,
                boxstyle="square,pad=0",
                linewidth=1,
                edgecolor=color,
                facecolor=color + "33",
                zorder=2
            )
            ax.add_patch(rect)
            label = "Bull OB" if ob.bias == BULLISH else "Bear OB"
            ax.text(idx, (ob.bar_high + ob.bar_low) / 2,
                    f" {label}", color=color, fontsize=6, va="center", zorder=5)

        # ── 5. Internal Order Blocks ──────────────────────────
        for ob in self.internal_obs:
            idx = ob.bar_index - offset
            if not (0 <= idx < n):
                continue
            color = "#3179f5" if ob.bias == BULLISH else "#f77c80"
            rect = mpatches.FancyBboxPatch(
                (idx - 0.4, ob.bar_low),
                n - idx,
                ob.bar_high - ob.bar_low,
                boxstyle="square,pad=0",
                linewidth=0,
                edgecolor="none",
                facecolor=color + "44",
                zorder=2
            )
            ax.add_patch(rect)

        # ── 6. Fair Value Gaps ────────────────────────────────
        for fvg in self.fvgs:
            left  = fvg.left_idx - offset
            right = fvg.right_idx - offset
            if right < 0 or left >= n:
                continue
            left  = max(left, 0)
            right = min(right + 10, n - 1)
            color = "#00ff68" if fvg.bias == BULLISH else "#ff0008"
            mid   = (fvg.top + fvg.bottom) / 2
            rect  = mpatches.FancyBboxPatch(
                (left, fvg.bottom),
                right - left,
                fvg.top - fvg.bottom,
                boxstyle="square,pad=0",
                linewidth=0.5,
                edgecolor=color,
                facecolor=color + "44",
                zorder=2
            )
            ax.add_patch(rect)
            label = "FVG+" if fvg.bias == BULLISH else "FVG-"
            ax.text(left, mid, f" {label}",
                    color=color, fontsize=5.5, va="center", zorder=5)

        # ── 7. Equal Highs / Lows ─────────────────────────────
        for eq in self.equal_levels:
            i1 = eq.idx1 - offset
            i2 = eq.idx2 - offset
            if i2 < 0 or i1 >= n:
                continue
            i1 = max(i1, 0)
            i2 = min(i2, n - 1)
            color = RED if eq.kind == "EQH" else GREEN
            ax.plot([i1, i2], [eq.price, eq.price],
                    color=color, linewidth=1, linestyle=":",
                    alpha=0.9, zorder=4)
            ax.text((i1 + i2) // 2, eq.price, eq.kind,
                    color=color, fontsize=6,
                    ha="center",
                    va="bottom" if eq.kind == "EQH" else "top",
                    zorder=5)

        # ── 8. Premium / Discount Zones ───────────────────────
        if not np.isnan(self.swing_top) and not np.isnan(self.swing_bottom):
            rng = self.swing_top - self.swing_bottom

            # Premium (top 25 %)
            prem_bot = self.swing_top - 0.25 * rng
            ax.axhspan(prem_bot, self.swing_top,
                       alpha=0.06, color=RED, zorder=1)
            ax.text(n - 1, self.swing_top - 0.01 * rng,
                    "  Premium", color=RED, fontsize=7,
                    ha="right", va="top", zorder=5)

            # Discount (bottom 25 %)
            disc_top = self.swing_bottom + 0.25 * rng
            ax.axhspan(self.swing_bottom, disc_top,
                       alpha=0.06, color=GREEN, zorder=1)
            ax.text(n - 1, self.swing_bottom + 0.01 * rng,
                    "  Discount", color=GREEN, fontsize=7,
                    ha="right", va="bottom", zorder=5)

            # Equilibrium
            eq_top = 0.525 * self.swing_top + 0.475 * self.swing_bottom
            eq_bot = 0.525 * self.swing_bottom + 0.475 * self.swing_top
            ax.axhspan(eq_bot, eq_top,
                       alpha=0.05, color=GRAY, zorder=1)
            ax.text(n - 1, (eq_top + eq_bot) / 2,
                    "  EQ", color=GRAY, fontsize=7,
                    ha="right", va="center", zorder=5)

        # ── 9. Strong / Weak High & Low ───────────────────────
        def _draw_sw_level(price, label, color, ls):
            if np.isnan(price):
                return
            ax.axhline(price, color=color, linewidth=1.2,
                       linestyle=ls, alpha=0.85, zorder=4)
            ax.text(n - 1, price, f"  {label}",
                    color=color, fontsize=7,
                    ha="right", va="bottom", zorder=5)

        _draw_sw_level(self.strong_high, "Strong High", RED,   "-")
        _draw_sw_level(self.weak_high,   "Weak High",   RED,   "--")
        _draw_sw_level(self.strong_low,  "Strong Low",  GREEN, "-")
        _draw_sw_level(self.weak_low,    "Weak Low",    GREEN, "--")

        # ── X-axis labels ──────────────────────────────────────
        date_col = df.columns[0]    # first column is the date / index
        tick_positions = np.linspace(0, n - 1, min(10, n), dtype=int)
        ax.set_xticks(tick_positions)
        try:
            ax.set_xticklabels(
                [str(df[date_col].iloc[i])[:10] for i in tick_positions],
                rotation=30, color="white", fontsize=7
            )
        except Exception:
            ax.set_xticklabels(tick_positions, color="white", fontsize=7)

        ax.yaxis.tick_right()
        ax.yaxis.set_label_position("right")
        ax.tick_params(axis="y", colors="white", labelsize=7)

        # ── Legend ─────────────────────────────────────────────
        legend_items = [
            mpatches.Patch(color=GREEN,   label="BOS Bullish / Swing OB Bull"),
            mpatches.Patch(color=RED,     label="BOS Bearish / Swing OB Bear"),
            mpatches.Patch(color="#3179f5", label="Internal OB Bull"),
            mpatches.Patch(color="#f77c80", label="Internal OB Bear"),
            mpatches.Patch(color="#00ff68", label="FVG Bullish"),
            mpatches.Patch(color="#ff0008", label="FVG Bearish"),
        ]
        ax.legend(handles=legend_items, loc="upper left",
                  facecolor="#1e222d", edgecolor="#2a2e39",
                  labelcolor="white", fontsize=7)

        ax.set_title("Smart Money Concepts (SMC)", color="white",
                     fontsize=13, pad=10)
        ax.set_xlim(-1, n + 1)

        plt.tight_layout()
        plt.savefig("/mnt/user-data/outputs/smc_chart.png", dpi=150,
                    bbox_inches="tight", facecolor="#131722")
        plt.show()
        print("[SMC] Chart saved to smc_chart.png")


# ─────────────────────────────────────────────────────────────
#  QUICK-START  (run directly with yfinance)
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        import yfinance as yf
    except ImportError:
        print("Install yfinance:  pip install yfinance")
        raise

    print("Downloading AAPL data...")
    df = yf.download("AAPL", period="1y", interval="1d", progress=False)

    smc = SMCIndicator(
        df,
        swing_length    = 10,      # bars for swing structure
        internal_length = 3,       # bars for internal structure
        ob_filter       = "atr",   # 'atr' or 'range'
        ob_mitigation   = "highlow",
        eql_threshold   = 0.15,
        max_obs         = 5,
    )

    smc.run()
    smc.plot(last_n_bars=120)
