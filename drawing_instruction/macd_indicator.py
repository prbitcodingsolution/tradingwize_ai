"""
MACD — Moving Average Convergence Divergence
=============================================
Python conversion of TradingView's official Pine Script v6 MACD indicator.

Faithfully replicates:
  • Fast EMA / SMA  (default 12)
  • Slow EMA / SMA  (default 26)
  • MACD line       = Fast MA − Slow MA
  • Signal line     = EMA/SMA of MACD  (default 9)
  • Histogram       = MACD − Signal
  • 4-colour histogram bars (dark/light green & dark/light red)
  • Zero line
  • Alert conditions (histogram zero-cross)
  • Subplot below the candlestick chart

Requirements
------------
    pip install pandas numpy matplotlib yfinance

Standalone usage
----------------
    python macd_indicator.py

Module usage
------------
    from macd_indicator import MACDIndicator
    import yfinance as yf

    df  = yf.download("AAPL", period="6mo", interval="1d")
    mac = MACDIndicator(df)
    mac.run()
    mac.plot()

    # Programmatic access
    data   = mac.get_data()   # DataFrame with macd / signal / hist columns
    alerts = mac.get_alerts() # list of alert dicts
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec
from typing import Optional
import warnings
warnings.filterwarnings("ignore")


# ─────────────────────────────────────────────────────────────
#  COLOURS  (matching Pine Script defaults exactly)
# ─────────────────────────────────────────────────────────────
# Histogram colours — 4 states
HIST_BULL_STRONG = "#26a69a"   # positive & rising   (dark teal)
HIST_BULL_WEAK   = "#b2dfdb"   # positive & falling  (light teal)
HIST_BEAR_WEAK   = "#ffcdd2"   # negative & rising   (light red)
HIST_BEAR_STRONG = "#ff5252"   # negative & falling  (dark red)

MACD_LINE_COLOR   = "#2962ff"  # default blue
SIGNAL_LINE_COLOR = "#ff6d00"  # orange  (exact Pine default)
ZERO_LINE_COLOR   = "#787b8680"

BG_COLOR          = "#131722"
GRID_COLOR        = "#1e222d"


# ─────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────
def _ema(series: pd.Series, length: int) -> pd.Series:
    """Exponential Moving Average — matches Pine's ta.ema()."""
    return series.ewm(span=length, adjust=False).mean()


def _sma(series: pd.Series, length: int) -> pd.Series:
    """Simple Moving Average — matches Pine's ta.sma()."""
    return series.rolling(window=length).mean()


def ma(series: pd.Series, length: int, ma_type: str = "EMA") -> pd.Series:
    """
    Unified MA dispatcher — replicates Pine's ma() function.

    Parameters
    ----------
    series  : pd.Series   price / source series
    length  : int         lookback period
    ma_type : str         'EMA' or 'SMA'
    """
    if ma_type.upper() == "EMA":
        return _ema(series, length)
    elif ma_type.upper() == "SMA":
        return _sma(series, length)
    else:
        raise ValueError(f"Unknown MA type '{ma_type}'. Use 'EMA' or 'SMA'.")


def _hist_color(hist: pd.Series) -> list:
    """
    Replicate Pine's 4-colour histogram logic exactly:

        hist >= 0
            hist > hist[1]  →  #26a69a   (bull strong — rising)
            else            →  #b2dfdb   (bull weak   — falling)
        hist < 0
            hist > hist[1]  →  #ffcdd2   (bear weak   — rising toward 0)
            else            →  #ff5252   (bear strong — falling away from 0)
    """
    colors = []
    vals   = hist.values
    for i in range(len(vals)):
        h     = vals[i]
        h_prv = vals[i - 1] if i > 0 else h   # hist[1] in Pine = previous bar

        if np.isnan(h):
            colors.append(HIST_BULL_STRONG)
            continue

        if h >= 0:
            colors.append(HIST_BULL_STRONG if h > h_prv else HIST_BULL_WEAK)
        else:
            colors.append(HIST_BEAR_WEAK   if h > h_prv else HIST_BEAR_STRONG)

    return colors


# ─────────────────────────────────────────────────────────────
#  MAIN CLASS
# ─────────────────────────────────────────────────────────────
class MACDIndicator:
    """
    MACD — Moving Average Convergence Divergence.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe.  Must contain a 'Close' column.
    source : str
        Which price column to use (default 'Close').
    fast_len : int
        Fast MA period (default 12).
    slow_len : int
        Slow MA period (default 26).
    sig_len : int
        Signal MA period (default 9).
    osc_type : str
        MA type for MACD calculation: 'EMA' or 'SMA' (default 'EMA').
    sig_type : str
        MA type for signal line: 'EMA' or 'SMA' (default 'EMA').
    last_n_bars : int or None
        Limit chart display to last N bars (default 200).
    """

    def __init__(
        self,
        df:          pd.DataFrame,
        source:      str  = "Close",
        fast_len:    int  = 12,
        slow_len:    int  = 26,
        sig_len:     int  = 9,
        osc_type:    str  = "EMA",
        sig_type:    str  = "EMA",
        last_n_bars: Optional[int] = 200,
    ):
        # ── normalise columns ──────────────────────────────────
        self.df = df.copy()
        self.df.columns = [c.capitalize() for c in self.df.columns]
        self.df = self.df.reset_index(drop=False)

        self.source      = source.capitalize()
        self.fast_len    = fast_len
        self.slow_len    = slow_len
        self.sig_len     = sig_len
        self.osc_type    = osc_type.upper()
        self.sig_type    = sig_type.upper()
        self.last_n_bars = last_n_bars

        # ── result columns (added to self.df after run()) ──────
        self._ran = False

    # ─────────────────────────────────────────────────────────
    #  CORE CALCULATION
    # ─────────────────────────────────────────────────────────
    def run(self):
        """Calculate MACD, signal, histogram and alert conditions."""
        src = self.df[self.source]

        # ── MACD ──────────────────────────────────────────────
        fast_ma          = ma(src, self.fast_len, self.osc_type)
        slow_ma          = ma(src, self.slow_len, self.osc_type)
        self.df["macd"]  = fast_ma - slow_ma

        # ── Signal ────────────────────────────────────────────
        self.df["signal"] = ma(self.df["macd"], self.sig_len, self.sig_type)

        # ── Histogram ─────────────────────────────────────────
        self.df["hist"]   = self.df["macd"] - self.df["signal"]

        # ── Histogram colours ─────────────────────────────────
        self.df["hist_color"] = _hist_color(self.df["hist"])

        # ── Alert conditions ──────────────────────────────────
        h     = self.df["hist"]
        h_prv = h.shift(1)

        # "Rising to falling"  — histogram was ≥0 then went <0
        self.df["alert_r2f"] = (h_prv >= 0) & (h < 0)
        # "Falling to rising"  — histogram was ≤0 then went >0
        self.df["alert_f2r"] = (h_prv <= 0) & (h > 0)

        self._ran = True

        # ── print summary ──────────────────────────────────────
        latest = self.df.dropna(subset=["macd"]).iloc[-1]
        r2f    = int(self.df["alert_r2f"].sum())
        f2r    = int(self.df["alert_f2r"].sum())

        print(f"\n{'─'*52}")
        print(f"  MACD  ({self.osc_type} {self.fast_len}/{self.slow_len} | "
              f"Signal {self.sig_type} {self.sig_len})")
        print(f"{'─'*52}")
        print(f"  Latest MACD      : {latest['macd']:.4f}")
        print(f"  Latest Signal    : {latest['signal']:.4f}")
        print(f"  Latest Histogram : {latest['hist']:.4f}")
        trend = "Bullish ▲" if latest["hist"] >= 0 else "Bearish ▼"
        mom   = "Rising  ↑" if latest["hist"] > self.df["hist"].iloc[-2] else "Falling ↓"
        print(f"  Trend            : {trend}")
        print(f"  Momentum         : {mom}")
        print(f"  Rising→Falling alerts : {r2f}")
        print(f"  Falling→Rising alerts : {f2r}")
        print(f"{'─'*52}\n")

    # ─────────────────────────────────────────────────────────
    #  PUBLIC: get_data
    # ─────────────────────────────────────────────────────────
    def get_data(self) -> pd.DataFrame:
        """
        Return a DataFrame with all calculated columns.
        Columns: macd, signal, hist, hist_color, alert_r2f, alert_f2r
        """
        if not self._ran:
            raise RuntimeError("Call .run() first.")
        cols = [self.df.columns[0], self.source,
                "macd", "signal", "hist",
                "hist_color", "alert_r2f", "alert_f2r"]
        return self.df[[c for c in cols if c in self.df.columns]].copy()

    # ─────────────────────────────────────────────────────────
    #  PUBLIC: get_alerts
    # ─────────────────────────────────────────────────────────
    def get_alerts(self) -> list:
        """
        Return list of dicts for every alert event.
        Each dict: { date, bar_index, type, macd, signal, hist }
        """
        if not self._ran:
            raise RuntimeError("Call .run() first.")

        date_col = self.df.columns[0]
        alerts   = []

        for idx, row in self.df.iterrows():
            if row.get("alert_r2f", False):
                alerts.append({
                    "date":      str(row[date_col])[:10],
                    "bar_index": idx,
                    "type":      "Rising→Falling",
                    "macd":      round(row["macd"],   4),
                    "signal":    round(row["signal"], 4),
                    "hist":      round(row["hist"],   4),
                })
            if row.get("alert_f2r", False):
                alerts.append({
                    "date":      str(row[date_col])[:10],
                    "bar_index": idx,
                    "type":      "Falling→Rising",
                    "macd":      round(row["macd"],   4),
                    "signal":    round(row["signal"], 4),
                    "hist":      round(row["hist"],   4),
                })

        return sorted(alerts, key=lambda x: x["bar_index"])

    # ─────────────────────────────────────────────────────────
    #  HELPER: hex → rgba
    # ─────────────────────────────────────────────────────────
    @staticmethod
    def _hex_rgba(hex_str: str, alpha: float) -> tuple:
        h = hex_str.lstrip("#")[:6]
        r, g, b = (int(h[i:i+2], 16) / 255 for i in (0, 2, 4))
        return (r, g, b, alpha)

    # ─────────────────────────────────────────────────────────
    #  PUBLIC: plot
    # ─────────────────────────────────────────────────────────
    def plot(
        self,
        figsize   = (24, 14),
        save_path = "/mnt/user-data/outputs/macd_chart.png"
    ):
        """
        Plot candlestick chart (top) + MACD panel (bottom).

        Layout mirrors TradingView:
          • Top panel    — candlestick price chart
          • Bottom panel — histogram bars, MACD line, signal line, zero line
          • Alert markers on MACD panel
        """
        if not self._ran:
            raise RuntimeError("Call .run() first.")

        # ── select display window ──────────────────────────────
        df = self.df.copy()
        if self.last_n_bars:
            df = df.tail(self.last_n_bars).copy()
        df = df.reset_index(drop=True)
        n  = len(df)

        hi  = df["High"].values   if "High"  in df.columns else np.zeros(n)
        lo  = df["Low"].values    if "Low"   in df.columns else np.zeros(n)
        op  = df["Open"].values   if "Open"  in df.columns else np.zeros(n)
        cl  = df["Close"].values  if "Close" in df.columns else np.zeros(n)

        macd_v   = df["macd"].values
        sig_v    = df["signal"].values
        hist_v   = df["hist"].values
        h_colors = df["hist_color"].tolist()

        # ── figure ─────────────────────────────────────────────
        fig = plt.figure(figsize=figsize, facecolor=BG_COLOR)
        gs  = GridSpec(
            3, 1, figure=fig,
            hspace=0.06,
            height_ratios=[2.8, 0.08, 1.2]   # price : spacer : macd
        )

        ax_price = fig.add_subplot(gs[0])
        ax_macd  = fig.add_subplot(gs[2], sharex=ax_price)

        for ax in (ax_price, ax_macd):
            ax.set_facecolor(BG_COLOR)
            ax.tick_params(colors="white", labelsize=7)
            ax.grid(color=GRID_COLOR, linewidth=0.4, linestyle="-")
            for spine in ax.spines.values():
                spine.set_color("#2a2e39")

        plt.setp(ax_price.get_xticklabels(), visible=False)

        # ── 1. Candlesticks ────────────────────────────────────
        GREEN_C = "#089981"
        RED_C   = "#f23645"

        for i in range(n):
            c = GREEN_C if cl[i] >= op[i] else RED_C
            ax_price.bar(
                i, abs(cl[i] - op[i]),
                bottom=min(cl[i], op[i]),
                color=c, width=0.6, zorder=3
            )
            ax_price.plot(
                [i, i], [lo[i], hi[i]],
                color=c, linewidth=0.8, zorder=3
            )

        ax_price.set_xlim(-1, n + 1)
        ax_price.yaxis.tick_right()
        ax_price.yaxis.set_label_position("right")
        ax_price.set_title(
            f"MACD  ({self.osc_type} {self.fast_len}/{self.slow_len} | "
            f"Signal {self.sig_type} {self.sig_len})",
            color="white", fontsize=12, pad=8
        )

        # ── 2. MACD panel ──────────────────────────────────────

        # Zero line
        ax_macd.axhline(0, color=ZERO_LINE_COLOR,
                        linewidth=0.9, linestyle="-", zorder=2)

        # Histogram bars
        for i in range(n):
            if np.isnan(hist_v[i]):
                continue
            ax_macd.bar(
                i, hist_v[i],
                color=h_colors[i],
                width=0.6, zorder=3
            )

        # MACD line
        x_valid = np.where(~np.isnan(macd_v))[0]
        if len(x_valid):
            ax_macd.plot(
                x_valid, macd_v[x_valid],
                color=MACD_LINE_COLOR,
                linewidth=1.3, zorder=4,
                label=f"MACD ({self.fast_len},{self.slow_len})"
            )

        # Signal line
        s_valid = np.where(~np.isnan(sig_v))[0]
        if len(s_valid):
            ax_macd.plot(
                s_valid, sig_v[s_valid],
                color=SIGNAL_LINE_COLOR,
                linewidth=1.1, zorder=4,
                label=f"Signal ({self.sig_len})"
            )

        # ── 3. Alert markers ───────────────────────────────────
        r2f_mask = df["alert_r2f"].values
        f2r_mask = df["alert_f2r"].values

        for i in range(n):
            if r2f_mask[i]:
                ax_macd.axvline(
                    i, color=RED_C,
                    linewidth=0.8, linestyle=":", alpha=0.7, zorder=2
                )
                ax_macd.annotate(
                    "R→F",
                    xy=(i, hist_v[i] if not np.isnan(hist_v[i]) else 0),
                    xytext=(0, -14), textcoords="offset points",
                    color=RED_C, fontsize=5.5,
                    ha="center", zorder=6
                )

            if f2r_mask[i]:
                ax_macd.axvline(
                    i, color=GREEN_C,
                    linewidth=0.8, linestyle=":", alpha=0.7, zorder=2
                )
                ax_macd.annotate(
                    "F→R",
                    xy=(i, hist_v[i] if not np.isnan(hist_v[i]) else 0),
                    xytext=(0, 6), textcoords="offset points",
                    color=GREEN_C, fontsize=5.5,
                    ha="center", zorder=6
                )

        ax_macd.yaxis.tick_right()
        ax_macd.yaxis.set_label_position("right")
        ax_macd.set_ylabel("MACD", color="white", fontsize=8)

        # ── 4. X-axis dates ────────────────────────────────────
        date_col = df.columns[0]
        ticks    = np.linspace(0, n - 1, min(12, n), dtype=int)
        ax_macd.set_xticks(ticks)
        try:
            ax_macd.set_xticklabels(
                [str(df[date_col].iloc[i])[:10] for i in ticks],
                rotation=30, color="white", fontsize=7
            )
        except Exception:
            ax_macd.set_xticklabels(ticks, color="white", fontsize=7)

        # ── 5. Legend on MACD panel ────────────────────────────
        legend_items = [
            mpatches.Patch(color=HIST_BULL_STRONG, label="Hist: Bull Strong"),
            mpatches.Patch(color=HIST_BULL_WEAK,   label="Hist: Bull Weak"),
            mpatches.Patch(color=HIST_BEAR_WEAK,   label="Hist: Bear Weak"),
            mpatches.Patch(color=HIST_BEAR_STRONG, label="Hist: Bear Strong"),
            plt.Line2D([0],[0], color=MACD_LINE_COLOR,
                       linewidth=1.3, label=f"MACD ({self.fast_len},{self.slow_len})"),
            plt.Line2D([0],[0], color=SIGNAL_LINE_COLOR,
                       linewidth=1.1, label=f"Signal ({self.sig_len})"),
            plt.Line2D([0],[0], color=GREEN_C, linewidth=0.8,
                       linestyle=":", label="F→R Alert"),
            plt.Line2D([0],[0], color=RED_C,   linewidth=0.8,
                       linestyle=":", label="R→F Alert"),
        ]
        ax_macd.legend(
            handles=legend_items,
            loc="upper left",
            facecolor="#1e222d",
            edgecolor="#2a2e39",
            labelcolor="white",
            fontsize=6.5,
            ncol=4
        )

        plt.tight_layout()
        if save_path:
            plt.savefig(
                save_path, dpi=150,
                bbox_inches="tight", facecolor=BG_COLOR
            )
            print(f"[MACD] Chart saved → {save_path}")

        plt.show()


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

    mac = MACDIndicator(
        df,
        fast_len    = 12,     # fast EMA period
        slow_len    = 26,     # slow EMA period
        sig_len     = 9,      # signal EMA period
        osc_type    = "EMA",  # 'EMA' or 'SMA' for MACD calculation
        sig_type    = "EMA",  # 'EMA' or 'SMA' for signal line
        last_n_bars = 150,    # visible window on chart
    )

    mac.run()
    mac.plot()

    # ── programmatic access ──────────────────────────────────
    data   = mac.get_data()
    alerts = mac.get_alerts()

    print(f"Last 5 rows:\n{data[['macd','signal','hist']].tail()}\n")
    print(f"Last 5 alerts:")
    for a in alerts[-5:]:
        print(f"  {a['date']}  {a['type']:18s}  hist={a['hist']}")
