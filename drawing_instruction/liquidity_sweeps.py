"""
Liquidity Sweeps Indicator — Python Implementation
===================================================
Converted from LuxAlgo's Pine Script "Liquidity Sweeps [LuxAlgo]".

Concept:
  Liquidity pools sit above swing highs and below swing lows
  (where traders place stop-loss orders). Institutional "smart money"
  sweeps these levels to grab that liquidity before reversing direction.

Three detection modes
---------------------
  'wicks'      — wick pierces pivot level but candle CLOSES back beyond it
                 (classic sweep: high > pivot but close < pivot for bearish)
  'outbreaks'  — candle CLOSES beyond pivot (breaks out), then later
                 a candle closes back on the other side (retest/mitigation)
  'both'       — detect both wicks AND outbreaks

What gets drawn
---------------
  • Dotted line  at the swept pivot level
  • Dot marker   at the candle's opposite extreme
  • Coloured box from the sweep bar extending rightward until broken
  • Box is "broken" when price closes beyond it in the opposite direction

Requirements:
    pip install pandas numpy matplotlib yfinance

Usage (standalone):
    python liquidity_sweeps.py

Usage (as module):
    from liquidity_sweeps import LiquiditySweeps
    import yfinance as yf
    df = yf.download("AAPL", period="6mo", interval="1d")
    ls = LiquiditySweeps(df, swing_len=5, mode='wicks')
    ls.run()
    ls.plot()
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from dataclasses import dataclass, field
from typing import Optional, List
import warnings
warnings.filterwarnings("ignore")


# ─────────────────────────────────────────────────────────────
#  COLOURS
# ─────────────────────────────────────────────────────────────
BULL_COLOR      = "#089981"    # green  — bullish sweep (low swept)
BEAR_COLOR      = "#f23645"    # red    — bearish sweep (high swept)
BULL_BOX_COLOR  = "#08998141"  # translucent green box
BEAR_BOX_COLOR  = "#f2364541"  # translucent red box
BULL_LINE_COLOR = "#08998180"  # semi-transparent green line
BEAR_LINE_COLOR = "#f2364580"  # semi-transparent red line
BG_COLOR        = "#131722"


# ─────────────────────────────────────────────────────────────
#  DATA STRUCTURES
# ─────────────────────────────────────────────────────────────
@dataclass
class Pivot:
    """A detected swing pivot point."""
    price:     float          # pivot price level
    bar_index: int            # bar where the pivot formed (confirmed)
    is_high:   bool           # True = pivot high, False = pivot low
    broken:    bool = False   # price closed beyond the pivot
    mitigated: bool = False   # pivot is no longer active
    taken:     bool = False   # swept after a breakout
    wicked:    bool = False   # already registered a wick sweep


@dataclass
class SweepEvent:
    """A detected liquidity sweep."""
    pivot_price:  float   # price level that was swept
    sweep_bar:    int     # bar index of the sweep candle
    dot_price:    float   # opposite extreme (low for bear sweep, high for bull)
    direction:    int     # +1 = bullish (low swept → up), -1 = bearish (high swept → down)
    kind:         str     # 'wick' or 'outbreak'
    box_top:      float   = 0.0
    box_bottom:   float   = 0.0
    box_left:     int     = 0
    box_right:    int     = 0    # updated each bar while extending
    broken:       bool    = False


# ─────────────────────────────────────────────────────────────
#  MAIN CLASS
# ─────────────────────────────────────────────────────────────
class LiquiditySweeps:
    """
    Liquidity Sweeps indicator.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe. Columns: Open, High, Low, Close, Volume.
    swing_len : int
        Pivot lookback length (bars on each side). Default 5.
    mode : str
        Detection mode:
          'wicks'     — only wick sweeps
          'outbreaks' — only breakout + retest
          'both'      — wicks AND outbreaks
    max_bars : int
        Max bars to extend a sweep box rightward. Default 300.
    last_n_bars : int or None
        Limit chart display to last N bars. Default 200.
    """

    def __init__(
        self,
        df:           pd.DataFrame,
        swing_len:    int  = 5,
        mode:         str  = 'wicks',
        max_bars:     int  = 300,
        last_n_bars:  Optional[int] = 200,
    ):
        self.df_full    = df.copy()
        self.df_full.columns = [c.capitalize() for c in self.df_full.columns]
        self.df_full    = self.df_full.reset_index(drop=False)

        self.swing_len  = swing_len
        self.mode       = mode.lower()
        self.max_bars   = max_bars
        self.last_n_bars = last_n_bars

        # ── results ─────────────────────────────────────────
        self.sweeps:     List[SweepEvent] = []
        self.pivots_h:   List[Pivot]      = []   # active pivot highs
        self.pivots_l:   List[Pivot]      = []   # active pivot lows

    # ─────────────────────────────────────────────────────────
    #  PIVOT DETECTION
    # ─────────────────────────────────────────────────────────
    def _find_pivots(self):
        """
        Detect pivot highs and lows.
        A pivot high at bar i: high[i] is the highest in window
                               [i - swing_len, i + swing_len].
        Confirmed `swing_len` bars AFTER the pivot bar (same as Pine).
        Returns list of Pivot objects sorted by confirmation bar.
        """
        hi   = self.df_full["High"].values
        lo   = self.df_full["Low"].values
        n    = len(hi)
        L    = self.swing_len

        pivot_highs: List[Pivot] = []
        pivot_lows:  List[Pivot] = []

        for i in range(L, n - L):
            window_h = hi[i - L: i + L + 1]
            window_l = lo[i - L: i + L + 1]

            if hi[i] == window_h.max() and np.sum(window_h == hi[i]) == 1:
                # confirmed at bar  i + L
                pivot_highs.append(Pivot(
                    price     = hi[i],
                    bar_index = i,          # actual pivot bar
                    is_high   = True,
                ))

            if lo[i] == window_l.min() and np.sum(window_l == lo[i]) == 1:
                pivot_lows.append(Pivot(
                    price     = lo[i],
                    bar_index = i,
                    is_high   = False,
                ))

        return pivot_highs, pivot_lows

    # ─────────────────────────────────────────────────────────
    #  SWEEP DETECTION  (mirrors Pine's bar-by-bar loop)
    # ─────────────────────────────────────────────────────────
    def _detect_sweeps(self, pivot_highs: List[Pivot], pivot_lows: List[Pivot]):
        """
        Walk every bar and test active pivots for sweep conditions.
        Exactly mirrors the Pine Script execution logic.
        """
        hi    = self.df_full["High"].values
        lo    = self.df_full["Low"].values
        cl    = self.df_full["Close"].values
        n     = len(cl)
        L     = self.swing_len

        only_wicks     = (self.mode == 'wicks')
        only_outbreaks = (self.mode == 'outbreaks')

        # index pivot events by their confirmation bar (pivot_bar + L)
        ph_by_confirm: dict[int, List[Pivot]] = {}
        pl_by_confirm: dict[int, List[Pivot]] = {}

        for p in pivot_highs:
            cb = p.bar_index + L
            ph_by_confirm.setdefault(cb, []).append(p)

        for p in pivot_lows:
            cb = p.bar_index + L
            pl_by_confirm.setdefault(cb, []).append(p)

        active_highs: List[Pivot] = []
        active_lows:  List[Pivot] = []
        sweeps:       List[SweepEvent] = []

        for i in range(n):

            # ── add newly confirmed pivots ─────────────────────
            for p in ph_by_confirm.get(i, []):
                active_highs.append(p)
            for p in pl_by_confirm.get(i, []):
                active_lows.append(p)

            # ── scan active pivot HIGHS ────────────────────────
            to_remove_h = []
            for get in active_highs:
                if get.mitigated or get.taken:
                    to_remove_h.append(get)
                    continue

                if not get.broken:
                    # ── WICK sweep of pivot high ─────────────
                    # high pierces pivot but close is below → bearish wick
                    if (not only_outbreaks and
                            not get.wicked and
                            hi[i] > get.price and
                            cl[i] < get.price):

                        box_top    = hi[i]
                        box_bottom = get.price
                        sw = SweepEvent(
                            pivot_price = get.price,
                            sweep_bar   = i,
                            dot_price   = lo[i],      # dot at low of sweep candle
                            direction   = -1,          # bearish — high swept
                            kind        = 'wick',
                            box_top     = box_top,
                            box_bottom  = box_bottom,
                            box_left    = i,
                            box_right   = i,
                        )
                        sweeps.append(sw)
                        get.wicked = True

                    # close above → outbreak (not wick mode)
                    if cl[i] > get.price:
                        if only_wicks:
                            get.mitigated = True
                        else:
                            get.broken = True

                else:  # pivot high already broken (outbreak mode)
                    # retest: close back below pivot → taken (bullish retest)
                    if (not only_wicks and
                            lo[i] < get.price and
                            cl[i] > get.price):

                        box_top    = get.price
                        box_bottom = lo[i]
                        sw = SweepEvent(
                            pivot_price = get.price,
                            sweep_bar   = i,
                            dot_price   = hi[i],      # dot at high of candle
                            direction   = +1,          # bullish retest after bearish break
                            kind        = 'outbreak',
                            box_top     = box_top,
                            box_bottom  = box_bottom,
                            box_left    = i,
                            box_right   = i,
                        )
                        sweeps.append(sw)
                        get.taken = True

                    if cl[i] < get.price:
                        get.mitigated = True

                # expire old pivots (> 2000 bars or done)
                if (i - get.bar_index > 2000 or
                        get.mitigated or get.taken):
                    to_remove_h.append(get)

            for g in to_remove_h:
                if g in active_highs:
                    active_highs.remove(g)

            # ── scan active pivot LOWS ─────────────────────────
            to_remove_l = []
            for get in active_lows:
                if get.mitigated or get.taken:
                    to_remove_l.append(get)
                    continue

                if not get.broken:
                    # ── WICK sweep of pivot low ───────────────
                    # low pierces pivot but close above → bullish wick
                    if (not only_outbreaks and
                            not get.wicked and
                            lo[i] < get.price and
                            cl[i] > get.price):

                        box_top    = get.price
                        box_bottom = lo[i]
                        sw = SweepEvent(
                            pivot_price = get.price,
                            sweep_bar   = i,
                            dot_price   = hi[i],      # dot at high
                            direction   = +1,          # bullish — low swept → up
                            kind        = 'wick',
                            box_top     = box_top,
                            box_bottom  = box_bottom,
                            box_left    = i,
                            box_right   = i,
                        )
                        sweeps.append(sw)
                        get.wicked = True

                    # close below → outbreak
                    if cl[i] < get.price:
                        if only_wicks:
                            get.mitigated = True
                        else:
                            get.broken = True

                else:  # pivot low already broken
                    # retest: close back above pivot → taken (bearish retest)
                    if (not only_wicks and
                            hi[i] > get.price and
                            cl[i] < get.price):

                        box_top    = hi[i]
                        box_bottom = get.price
                        sw = SweepEvent(
                            pivot_price = get.price,
                            sweep_bar   = i,
                            dot_price   = lo[i],
                            direction   = -1,
                            kind        = 'outbreak',
                            box_top     = box_top,
                            box_bottom  = box_bottom,
                            box_left    = i,
                            box_right   = i,
                        )
                        sweeps.append(sw)
                        get.taken = True

                    if cl[i] > get.price:
                        get.mitigated = True

                if (i - get.bar_index > 2000 or
                        get.mitigated or get.taken):
                    to_remove_l.append(get)

            for g in to_remove_l:
                if g in active_lows:
                    active_lows.remove(g)

        # ── extend box right edges ─────────────────────────────
        for sw in sweeps:
            for i in range(sw.sweep_bar + 1, n):
                if i - sw.sweep_bar > self.max_bars:
                    break
                if sw.broken:
                    break
                sw.box_right = i
                # box broken when price closes beyond it
                if sw.direction == +1 and cl[i] < sw.box_bottom:
                    sw.broken = True
                if sw.direction == -1 and cl[i] > sw.box_top:
                    sw.broken = True

        return sweeps

    # ─────────────────────────────────────────────────────────
    #  PUBLIC: RUN
    # ─────────────────────────────────────────────────────────
    def run(self):
        """Detect all liquidity sweeps. Call before plot()."""
        pivot_highs, pivot_lows = self._find_pivots()
        self.sweeps = self._detect_sweeps(pivot_highs, pivot_lows)
        self.pivots_h = pivot_highs
        self.pivots_l = pivot_lows

        bull = sum(1 for s in self.sweeps if s.direction == +1)
        bear = sum(1 for s in self.sweeps if s.direction == -1)
        wick = sum(1 for s in self.sweeps if s.kind == 'wick')
        outb = sum(1 for s in self.sweeps if s.kind == 'outbreak')

        print(f"\n{'─'*52}")
        print(f"  Liquidity Sweeps Analysis")
        print(f"{'─'*52}")
        print(f"  Total bars     : {len(self.df_full)}")
        print(f"  Swing length   : {self.swing_len}")
        print(f"  Mode           : {self.mode}")
        print(f"  Total sweeps   : {len(self.sweeps)}")
        print(f"    Bullish      : {bull}  (low swept → up)")
        print(f"    Bearish      : {bear}  (high swept → down)")
        print(f"    Wick sweeps  : {wick}")
        print(f"    Outbreaks    : {outb}")
        print(f"{'─'*52}\n")

    # ─────────────────────────────────────────────────────────
    #  HELPER: hex with alpha → rgba
    # ─────────────────────────────────────────────────────────
    @staticmethod
    def _hex_rgba(hex_str: str, alpha: float) -> tuple:
        h = hex_str.lstrip("#")[:6]
        r, g, b = (int(h[i:i+2], 16) / 255 for i in (0, 2, 4))
        return (r, g, b, alpha)

    # ─────────────────────────────────────────────────────────
    #  PUBLIC: PLOT
    # ─────────────────────────────────────────────────────────
    def plot(
        self,
        figsize=(24, 11),
        save_path="/mnt/user-data/outputs/liquidity_sweeps_chart.png"
    ):
        """
        Plot candlestick chart with all detected liquidity sweeps.

        Parameters
        ----------
        figsize   : tuple
        save_path : str or None
        """
        # ── select display window ──────────────────────────────
        df_plot  = self.df_full
        if self.last_n_bars:
            df_plot = df_plot.tail(self.last_n_bars).copy()
        df_plot  = df_plot.reset_index(drop=True)

        # bar offset between full df and plot window
        offset   = len(self.df_full) - len(df_plot)

        hi   = df_plot["High"].values
        lo   = df_plot["Low"].values
        op   = df_plot["Open"].values
        cl   = df_plot["Close"].values
        n    = len(df_plot)

        fig, ax = plt.subplots(figsize=figsize, facecolor=BG_COLOR)
        ax.set_facecolor(BG_COLOR)
        ax.tick_params(colors="white", labelsize=7)
        for spine in ax.spines.values():
            spine.set_color("#2a2e39")

        # ── 1. Candlesticks ────────────────────────────────────
        GREEN_C = "#089981"
        RED_C   = "#f23645"
        for i in range(n):
            c = GREEN_C if cl[i] >= op[i] else RED_C
            ax.bar(i, abs(cl[i] - op[i]),
                   bottom=min(cl[i], op[i]),
                   color=c, width=0.6, zorder=3)
            ax.plot([i, i], [lo[i], hi[i]],
                    color=c, linewidth=0.8, zorder=3)

        # ── 2. Pivot highs / lows (small triangles) ────────────
        for p in self.pivots_h:
            idx = p.bar_index - offset
            if 0 <= idx < n:
                ax.plot(idx, self.df_full["High"].values[p.bar_index],
                        marker="v", color=BEAR_LINE_COLOR,
                        markersize=5, zorder=4, alpha=0.6)

        for p in self.pivots_l:
            idx = p.bar_index - offset
            if 0 <= idx < n:
                ax.plot(idx, self.df_full["Low"].values[p.bar_index],
                        marker="^", color=BULL_LINE_COLOR,
                        markersize=5, zorder=4, alpha=0.6)

        # ── 3. Sweep boxes + lines ─────────────────────────────
        for sw in self.sweeps:
            left  = sw.box_left  - offset
            right = sw.box_right - offset

            if right < 0 or left >= n:
                continue

            left  = max(left, 0)
            right = min(right, n - 1)

            is_bull   = sw.direction == +1
            box_color = BULL_BOX_COLOR if is_bull else BEAR_BOX_COLOR
            ln_color  = BULL_COLOR     if is_bull else BEAR_COLOR
            ln_color2 = BULL_LINE_COLOR if is_bull else BEAR_LINE_COLOR

            box_h = sw.box_top - sw.box_bottom
            if box_h <= 0:
                continue

            # filled box
            rgba = self._hex_rgba(
                BULL_COLOR if is_bull else BEAR_COLOR, 0.12
            )
            rect = mpatches.FancyBboxPatch(
                (left - 0.4, sw.box_bottom),
                right - left + 0.8,
                box_h,
                boxstyle="square,pad=0",
                linewidth=0,
                facecolor=rgba,
                zorder=2
            )
            ax.add_patch(rect)

            # pivot level line (dotted for wick, dashed for outbreak)
            ls = ":" if sw.kind == "wick" else "--"
            ax.hlines(
                sw.pivot_price,
                xmin=left, xmax=right,
                colors=ln_color2,
                linewidth=1.2, linestyle=ls, zorder=4
            )

            # dot at opposite extreme of sweep candle
            sweep_plot_idx = sw.sweep_bar - offset
            if 0 <= sweep_plot_idx < n:
                ax.scatter(
                    sweep_plot_idx, sw.dot_price,
                    color=ln_color, s=20, zorder=6,
                    marker="o"
                )

                # small dotted line at dot level
                ax.hlines(
                    sw.dot_price,
                    xmin=sweep_plot_idx,
                    xmax=min(sweep_plot_idx + 3, n - 1),
                    colors=ln_color,
                    linewidth=1.0, linestyle=":", zorder=4
                )

            # label
            mid_bar = (left + right) // 2
            label   = ("Bull Sweep ↑" if is_bull else "Bear Sweep ↓")
            sub     = f"({sw.kind})"
            va      = "top" if is_bull else "bottom"
            y_off   = sw.box_bottom if is_bull else sw.box_top
            ax.text(
                mid_bar, y_off, f" {label}\n {sub}",
                color=ln_color, fontsize=6,
                va=va, ha="center", zorder=5
            )

            # broken marker
            if sw.broken:
                ax.text(
                    right, sw.pivot_price, " ✗",
                    color="white", fontsize=7,
                    va="center", zorder=5, alpha=0.7
                )

        # ── 4. X-axis ──────────────────────────────────────────
        date_col = df_plot.columns[0]
        ticks    = np.linspace(0, n - 1, min(10, n), dtype=int)
        ax.set_xticks(ticks)
        try:
            ax.set_xticklabels(
                [str(df_plot[date_col].iloc[i])[:10] for i in ticks],
                rotation=30, color="white", fontsize=7
            )
        except Exception:
            ax.set_xticklabels(ticks, color="white", fontsize=7)

        ax.yaxis.tick_right()
        ax.yaxis.set_label_position("right")
        ax.set_xlim(-1, n + 2)
        ax.set_title("Liquidity Sweeps", color="white", fontsize=13, pad=10)

        # ── 5. Legend ──────────────────────────────────────────
        legend_items = [
            mpatches.Patch(color=BULL_COLOR, alpha=0.7,
                           label="Bullish Sweep (Low swept → reversal up)"),
            mpatches.Patch(color=BEAR_COLOR, alpha=0.7,
                           label="Bearish Sweep (High swept → reversal down)"),
            plt.Line2D([0],[0], color="white", linewidth=1,
                       linestyle=":", label="Wick Sweep line"),
            plt.Line2D([0],[0], color="white", linewidth=1,
                       linestyle="--", label="Outbreak Retest line"),
            plt.Line2D([0],[0], marker="o", color="white",
                       linewidth=0, markersize=5,
                       label="Sweep dot (opposite extreme)"),
        ]
        ax.legend(
            handles=legend_items,
            loc="upper left",
            facecolor="#1e222d",
            edgecolor="#2a2e39",
            labelcolor="white",
            fontsize=7
        )

        plt.tight_layout()
        if save_path:
            plt.savefig(save_path, dpi=150,
                        bbox_inches="tight", facecolor=BG_COLOR)
            print(f"[LS] Chart saved → {save_path}")

        plt.show()

    # ─────────────────────────────────────────────────────────
    #  CONVENIENCE: get sweeps as list of dicts
    # ─────────────────────────────────────────────────────────
    def get_sweeps(self) -> list:
        """
        Return all detected sweeps as plain dicts.
        Useful for integrating into trading systems / alert engines.
        """
        result = []
        date_col = self.df_full.columns[0]
        dates    = self.df_full[date_col].values

        for sw in self.sweeps:
            result.append({
                "date":        str(dates[sw.sweep_bar])[:10],
                "bar_index":   sw.sweep_bar,
                "pivot_price": round(sw.pivot_price, 4),
                "direction":   "bullish" if sw.direction == +1 else "bearish",
                "kind":        sw.kind,
                "box_top":     round(sw.box_top,    4),
                "box_bottom":  round(sw.box_bottom, 4),
                "broken":      sw.broken,
            })
        return result


# ─────────────────────────────────────────────────────────────
#  QUICK-START
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        import yfinance as yf
    except ImportError:
        print("Install yfinance:  pip install yfinance")
        raise

    print("Downloading AAPL data …")
    df = yf.download("AAPL", period="1y", interval="1d", progress=False)

    ls = LiquiditySweeps(
        df,
        swing_len   = 5,          # pivot lookback (bars each side)
        mode        = 'wicks',    # 'wicks' | 'outbreaks' | 'both'
        max_bars    = 300,        # max bars to extend a sweep box
        last_n_bars = 150,        # visible window for the chart
    )

    ls.run()
    ls.plot()

    # ── programmatic access ──────────────────────────────────
    sweeps = ls.get_sweeps()
    print(f"\nLast 5 sweeps detected:")
    for s in sweeps[-5:]:
        print(f"  {s['date']}  {s['direction']:8s}  {s['kind']:9s}"
              f"  pivot={s['pivot_price']}  broken={s['broken']}")
