"""
Supply and Demand Visible Range Indicator — Python Implementation
=================================================================
Converted from LuxAlgo's Pine Script "Supply and Demand Visible Range".

How it works:
  1. Takes the visible/selected OHLCV bars.
  2. Divides the price range (high→low) into `resolution` equal bins.
  3. Scans from the TOP DOWN  → finds the first bin where cumulative
     volume % exceeds `threshold` → Supply Zone.
  4. Scans from the BOTTOM UP → finds the first bin where cumulative
     volume % exceeds `threshold` → Demand Zone.
  5. Draws colour-filled boxes + average & VWAP lines for each zone,
     plus Equilibrium lines between them.

Requirements:
    pip install pandas numpy matplotlib yfinance

Usage (standalone):
    python supply_demand_indicator.py

Usage (as a module):
    from supply_demand_indicator import SupplyDemandIndicator
    import yfinance as yf

    df = yf.download("RELIANCE.NS", period="6mo", interval="1d")
    sd = SupplyDemandIndicator(df, threshold=10.0, resolution=50)
    sd.run()
    sd.plot()
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyArrowPatch
from dataclasses import dataclass, field
from typing import Optional
import warnings
warnings.filterwarnings("ignore")


# ─────────────────────────────────────────────────────────────
#  COLOURS  (matching LuxAlgo defaults)
# ─────────────────────────────────────────────────────────────
SUPPLY_COLOR  = "#2157f3"   # blue
DEMAND_COLOR  = "#ff5d00"   # orange
EQUI_COLOR    = "#878b94"   # gray
BG_COLOR      = "#131722"   # dark chart background


# ─────────────────────────────────────────────────────────────
#  DATA STRUCTURES
# ─────────────────────────────────────────────────────────────
@dataclass
class Bin:
    """Represents one price bin in the volume profile scan."""
    lvl:       float = 0.0   # current lower/upper boundary of this bin
    prev:      float = 0.0   # previous boundary
    vol_sum:   float = 0.0   # cumulative volume accumulated in this bin
    prev_sum:  float = 0.0   # vol_sum on previous inner iteration
    vwap_num:  float = 0.0   # numerator  for VWAP  (price × vol)
    vwap_den:  float = 0.0   # denominator for VWAP (vol)
    reached:   bool  = False # True once threshold is exceeded


@dataclass
class Zone:
    """A detected Supply or Demand zone."""
    top:        float          # top price of the zone box
    bottom:     float          # bottom price of the zone box
    avg:        float          # simple midpoint
    vwap:       float          # volume-weighted average price of zone
    kind:       str            # 'Supply' or 'Demand'
    left_bar:   int  = 0       # bar index where visible range starts
    right_bar:  int  = 0       # bar index where visible range ends


# ─────────────────────────────────────────────────────────────
#  MAIN CLASS
# ─────────────────────────────────────────────────────────────
class SupplyDemandIndicator:
    """
    Supply and Demand Visible Range indicator.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe.  Columns must include Open, High, Low, Close, Volume.
        Index should be a DatetimeIndex (or will be treated as bar numbers).
    threshold : float
        Volume % threshold to define a zone (default 10 %).
        Lower  → tighter, higher-conviction zones.
        Higher → broader zones that are easier to trigger.
    resolution : int
        Number of price bins to divide the range into (default 50).
    last_n_bars : int
        How many recent bars to treat as the "visible range" (default 200).
        Set to None to use the entire dataframe.
    """

    def __init__(
        self,
        df:           pd.DataFrame,
        threshold:    float = 10.0,
        resolution:   int   = 50,
        last_n_bars:  Optional[int] = 200,
    ):
        # ── normalise columns ───────────────────────────────────
        self.df_full = df.copy()
        self.df_full.columns = [c.capitalize() for c in self.df_full.columns]

        # ── select visible range ────────────────────────────────
        if last_n_bars is not None:
            self.df = self.df_full.tail(last_n_bars).copy()
        else:
            self.df = self.df_full.copy()

        self.df = self.df.reset_index(drop=False)

        self.threshold  = threshold
        self.resolution = resolution

        # ── results ─────────────────────────────────────────────
        self.supply_zone:  Optional[Zone] = None
        self.demand_zone:  Optional[Zone] = None
        self.equi_avg:     Optional[float] = None
        self.equi_vwap:    Optional[float] = None

        # volume profile (bin_price → total_vol) — for visualisation
        self.profile_prices: np.ndarray = np.array([])
        self.profile_vols:   np.ndarray = np.array([])

    # ─────────────────────────────────────────────────────────
    #  VOLUME PROFILE BUILDER
    # ─────────────────────────────────────────────────────────
    def _build_profile(self):
        """
        Build a simple volume-at-price profile over the visible range.

        Pine Script uses actual intrabar tick data; here we approximate
        by distributing each bar's volume uniformly across its High→Low
        range, then binning into `resolution` price levels.

        Returns
        -------
        bin_centers : np.ndarray  shape (resolution,)
        bin_volumes : np.ndarray  shape (resolution,)
        """
        hi    = self.df["High"].values
        lo    = self.df["Low"].values
        vol   = self.df["Volume"].values.astype(float)

        price_max = hi.max()
        price_min = lo.min()
        price_rng = price_max - price_min

        if price_rng == 0:
            raise ValueError("Price range is zero — cannot build profile.")

        # bin edges and centres
        edges   = np.linspace(price_min, price_max, self.resolution + 1)
        centres = 0.5 * (edges[:-1] + edges[1:])
        bin_vol = np.zeros(self.resolution)

        for i in range(len(self.df)):
            bar_hi  = hi[i]
            bar_lo  = lo[i]
            bar_vol = vol[i]
            bar_rng = bar_hi - bar_lo

            if bar_rng == 0:
                # point bar → put all volume in the nearest bin
                idx = np.searchsorted(edges, bar_hi, side="right") - 1
                idx = np.clip(idx, 0, self.resolution - 1)
                bin_vol[idx] += bar_vol
                continue

            # fraction of each bin that overlaps this bar's range
            overlap_top = np.minimum(edges[1:], bar_hi)
            overlap_bot = np.maximum(edges[:-1], bar_lo)
            overlap     = np.maximum(overlap_top - overlap_bot, 0.0)
            fractions   = overlap / bar_rng
            bin_vol    += fractions * bar_vol

        return centres, bin_vol

    # ─────────────────────────────────────────────────────────
    #  ZONE DETECTION  (mirrors Pine's bin-scan logic)
    # ─────────────────────────────────────────────────────────
    def _find_zones(self, centres: np.ndarray, bin_vol: np.ndarray):
        """
        Scan from top→down for Supply and bottom→up for Demand.
        Mirrors the nested loop logic in the Pine script.
        """
        total_vol = bin_vol.sum()
        if total_vol == 0:
            return None, None

        price_max = self.df["High"].values.max()
        price_min = self.df["Low"].values.min()
        bin_width = centres[1] - centres[0] if len(centres) > 1 else 1.0

        # ── Supply: scan TOP → DOWN ────────────────────────────
        supply_zone = None
        cum_vol     = 0.0
        vwap_num    = 0.0
        vwap_den    = 0.0

        for i in range(self.resolution - 1, -1, -1):   # high → low
            cum_vol  += bin_vol[i]
            vwap_num += centres[i] * bin_vol[i]
            vwap_den += bin_vol[i]

            if (cum_vol / total_vol * 100) >= self.threshold:
                zone_top    = price_max
                zone_bottom = centres[i] - bin_width / 2
                zone_avg    = (zone_top + zone_bottom) / 2
                zone_vwap   = vwap_num / vwap_den if vwap_den > 0 else zone_avg

                supply_zone = Zone(
                    top      = zone_top,
                    bottom   = zone_bottom,
                    avg      = zone_avg,
                    vwap     = zone_vwap,
                    kind     = "Supply",
                    left_bar = 0,
                    right_bar= len(self.df) - 1,
                )
                break

        # ── Demand: scan BOTTOM → UP ───────────────────────────
        demand_zone = None
        cum_vol     = 0.0
        vwap_num    = 0.0
        vwap_den    = 0.0

        for i in range(self.resolution):               # low → high
            cum_vol  += bin_vol[i]
            vwap_num += centres[i] * bin_vol[i]
            vwap_den += bin_vol[i]

            if (cum_vol / total_vol * 100) >= self.threshold:
                zone_top    = centres[i] + bin_width / 2
                zone_bottom = price_min
                zone_avg    = (zone_top + zone_bottom) / 2
                zone_vwap   = vwap_num / vwap_den if vwap_den > 0 else zone_avg

                demand_zone = Zone(
                    top      = zone_top,
                    bottom   = zone_bottom,
                    avg      = zone_avg,
                    vwap     = zone_vwap,
                    kind     = "Demand",
                    left_bar = 0,
                    right_bar= len(self.df) - 1,
                )
                break

        return supply_zone, demand_zone

    # ─────────────────────────────────────────────────────────
    #  PUBLIC: RUN
    # ─────────────────────────────────────────────────────────
    def run(self):
        """Detect Supply and Demand zones. Call before plot()."""
        centres, bin_vol = self._build_profile()

        self.profile_prices = centres
        self.profile_vols   = bin_vol

        self.supply_zone, self.demand_zone = self._find_zones(centres, bin_vol)

        # Equilibrium
        if self.supply_zone and self.demand_zone:
            self.equi_avg  = (self.supply_zone.avg  + self.demand_zone.avg)  / 2
            self.equi_vwap = (self.supply_zone.vwap + self.demand_zone.vwap) / 2

        # ── print summary ──────────────────────────────────────
        print(f"\n{'─'*52}")
        print(f"  Supply & Demand — Visible Range Analysis")
        print(f"{'─'*52}")
        print(f"  Visible bars   : {len(self.df)}")
        print(f"  Price range    : {self.df['Low'].min():.4f}  →  {self.df['High'].max():.4f}")
        print(f"  Threshold      : {self.threshold} %")
        print(f"  Resolution     : {self.resolution} bins")
        if self.supply_zone:
            print(f"\n  SUPPLY ZONE")
            print(f"    Top    : {self.supply_zone.top:.4f}")
            print(f"    Bottom : {self.supply_zone.bottom:.4f}")
            print(f"    Avg    : {self.supply_zone.avg:.4f}")
            print(f"    VWAP   : {self.supply_zone.vwap:.4f}")
        if self.demand_zone:
            print(f"\n  DEMAND ZONE")
            print(f"    Top    : {self.demand_zone.top:.4f}")
            print(f"    Bottom : {self.demand_zone.bottom:.4f}")
            print(f"    Avg    : {self.demand_zone.avg:.4f}")
            print(f"    VWAP   : {self.demand_zone.vwap:.4f}")
        if self.equi_avg:
            print(f"\n  EQUILIBRIUM   (avg)  : {self.equi_avg:.4f}")
            print(f"  EQUILIBRIUM   (vwap) : {self.equi_vwap:.4f}")
        print(f"{'─'*52}\n")

    # ─────────────────────────────────────────────────────────
    #  HELPER: hex → rgba tuple
    # ─────────────────────────────────────────────────────────
    @staticmethod
    def _hex_rgba(hex_color: str, alpha: float):
        hex_color = hex_color.lstrip("#")
        r, g, b = (int(hex_color[i:i+2], 16) / 255 for i in (0, 2, 4))
        return (r, g, b, alpha)

    # ─────────────────────────────────────────────────────────
    #  PUBLIC: PLOT
    # ─────────────────────────────────────────────────────────
    def plot(self, figsize=(24, 12), save_path="/mnt/user-data/outputs/supply_demand_chart.png"):
        """
        Plot candlesticks + Supply/Demand zones + volume profile sidebar.

        Parameters
        ----------
        figsize : tuple
        save_path : str or None  — set to None to skip saving.
        """
        df  = self.df
        hi  = df["High"].values
        lo  = df["Low"].values
        op  = df["Open"].values
        cl  = df["Close"].values
        n   = len(df)

        # ── figure layout: main chart + profile sidebar ────────
        fig, (ax, ax_prof) = plt.subplots(
            1, 2,
            figsize=figsize,
            facecolor=BG_COLOR,
            gridspec_kw={"width_ratios": [5, 1], "wspace": 0.01}
        )

        for a in (ax, ax_prof):
            a.set_facecolor(BG_COLOR)
            a.tick_params(colors="white", labelsize=7)
            for spine in a.spines.values():
                spine.set_color("#2a2e39")

        # ── 1. Candlesticks ────────────────────────────────────
        GREEN_C = "#089981"
        RED_C   = "#F23645"

        for i in range(n):
            color = GREEN_C if cl[i] >= op[i] else RED_C
            ax.bar(i, abs(cl[i] - op[i]),
                   bottom=min(cl[i], op[i]),
                   color=color, width=0.6, zorder=3)
            ax.plot([i, i], [lo[i], hi[i]],
                    color=color, linewidth=0.8, zorder=3)

        # ── 2. Supply Zone ────────────────────────────────────
        if self.supply_zone:
            sz = self.supply_zone
            # filled box
            rect = mpatches.FancyBboxPatch(
                (0, sz.bottom),
                n,
                sz.top - sz.bottom,
                boxstyle="square,pad=0",
                linewidth=0,
                facecolor=self._hex_rgba(SUPPLY_COLOR, 0.18),
                zorder=2
            )
            ax.add_patch(rect)

            # volume columns inside the zone (lighter shade per bin)
            self._draw_profile_columns(
                ax, self.profile_prices, self.profile_vols,
                sz.bottom, sz.top, n, SUPPLY_COLOR
            )

            # simple average line (solid)
            ax.axhline(sz.avg,  color=SUPPLY_COLOR,
                       linewidth=1.3, linestyle="-",  zorder=4, alpha=0.95)
            # VWAP line (dashed)
            ax.axhline(sz.vwap, color=SUPPLY_COLOR,
                       linewidth=1.0, linestyle="--", zorder=4, alpha=0.85)

            # labels
            ax.text(n - 1, sz.top,  "  Supply Zone",
                    color=SUPPLY_COLOR, fontsize=8,
                    va="top", ha="right", zorder=5)
            ax.text(n - 1, sz.avg,  "  Avg",
                    color=SUPPLY_COLOR, fontsize=7,
                    va="bottom", ha="right", zorder=5)
            ax.text(n - 1, sz.vwap, "  VWAP",
                    color=SUPPLY_COLOR, fontsize=7,
                    va="top", ha="right", zorder=5, style="italic")

        # ── 3. Demand Zone ────────────────────────────────────
        if self.demand_zone:
            dz = self.demand_zone
            rect = mpatches.FancyBboxPatch(
                (0, dz.bottom),
                n,
                dz.top - dz.bottom,
                boxstyle="square,pad=0",
                linewidth=0,
                facecolor=self._hex_rgba(DEMAND_COLOR, 0.18),
                zorder=2
            )
            ax.add_patch(rect)

            self._draw_profile_columns(
                ax, self.profile_prices, self.profile_vols,
                dz.bottom, dz.top, n, DEMAND_COLOR
            )

            ax.axhline(dz.avg,  color=DEMAND_COLOR,
                       linewidth=1.3, linestyle="-",  zorder=4, alpha=0.95)
            ax.axhline(dz.vwap, color=DEMAND_COLOR,
                       linewidth=1.0, linestyle="--", zorder=4, alpha=0.85)

            ax.text(n - 1, dz.bottom, "  Demand Zone",
                    color=DEMAND_COLOR, fontsize=8,
                    va="bottom", ha="right", zorder=5)
            ax.text(n - 1, dz.avg,    "  Avg",
                    color=DEMAND_COLOR, fontsize=7,
                    va="top", ha="right", zorder=5)
            ax.text(n - 1, dz.vwap,   "  VWAP",
                    color=DEMAND_COLOR, fontsize=7,
                    va="bottom", ha="right", zorder=5, style="italic")

        # ── 4. Equilibrium lines ──────────────────────────────
        if self.equi_avg is not None:
            ax.axhline(self.equi_avg,  color=EQUI_COLOR,
                       linewidth=1.0, linestyle="-",  zorder=4, alpha=0.8)
            ax.axhline(self.equi_vwap, color=EQUI_COLOR,
                       linewidth=0.9, linestyle="--", zorder=4, alpha=0.7)
            ax.text(0, self.equi_avg,
                    "Equilibrium (avg)  ",
                    color=EQUI_COLOR, fontsize=7,
                    va="bottom", ha="left", zorder=5)
            ax.text(0, self.equi_vwap,
                    "Equilibrium (VWAP) ",
                    color=EQUI_COLOR, fontsize=7,
                    va="top", ha="left", zorder=5, style="italic")

        # ── 5. X-axis dates ───────────────────────────────────
        date_col = df.columns[0]
        ticks    = np.linspace(0, n - 1, min(10, n), dtype=int)
        ax.set_xticks(ticks)
        try:
            ax.set_xticklabels(
                [str(df[date_col].iloc[i])[:10] for i in ticks],
                rotation=30, color="white", fontsize=7
            )
        except Exception:
            ax.set_xticklabels(ticks, color="white", fontsize=7)

        ax.yaxis.tick_right()
        ax.yaxis.set_label_position("right")
        ax.set_xlim(-1, n + 2)
        ax.set_title("Supply & Demand — Visible Range", color="white",
                     fontsize=13, pad=10)

        # ── 6. Volume Profile Sidebar ─────────────────────────
        self._draw_sidebar_profile(ax_prof)

        # ── 7. Legend ─────────────────────────────────────────
        legend_items = [
            mpatches.Patch(color=SUPPLY_COLOR, alpha=0.7, label="Supply Zone"),
            mpatches.Patch(color=DEMAND_COLOR, alpha=0.7, label="Demand Zone"),
            mpatches.Patch(color=EQUI_COLOR,   alpha=0.7, label="Equilibrium"),
            plt.Line2D([0], [0], color="white", linewidth=1,
                       linestyle="-",  label="Simple Average"),
            plt.Line2D([0], [0], color="white", linewidth=1,
                       linestyle="--", label="VWAP of Zone"),
        ]
        ax.legend(handles=legend_items, loc="upper left",
                  facecolor="#1e222d", edgecolor="#2a2e39",
                  labelcolor="white", fontsize=7)

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=150,
                        bbox_inches="tight", facecolor=BG_COLOR)
            print(f"[S&D] Chart saved → {save_path}")

        plt.show()

    # ─────────────────────────────────────────────────────────
    #  INTERNAL: draw profile columns inside a zone on main ax
    # ─────────────────────────────────────────────────────────
    def _draw_profile_columns(self, ax, centres, bin_vol,
                               zone_bot, zone_top, n_bars, color):
        """
        Draw horizontal volume bars within a zone (lighter shade).
        Mirrors Pine's inner box.new() calls for each bin.
        """
        if bin_vol.sum() == 0:
            return

        max_vol    = bin_vol.max()
        bin_height = centres[1] - centres[0] if len(centres) > 1 else 1.0

        for price, vol in zip(centres, bin_vol):
            if not (zone_bot <= price <= zone_top):
                continue
            width = (vol / max_vol) * n_bars * 0.4   # scale to 40 % of chart width
            rect  = mpatches.FancyBboxPatch(
                (0, price - bin_height / 2),
                width,
                bin_height,
                boxstyle="square,pad=0",
                linewidth=0,
                facecolor=self._hex_rgba(color, 0.35),
                zorder=2
            )
            ax.add_patch(rect)

    # ─────────────────────────────────────────────────────────
    #  INTERNAL: full volume profile sidebar
    # ─────────────────────────────────────────────────────────
    def _draw_sidebar_profile(self, ax_prof):
        """Draw the full volume-at-price profile in the sidebar."""
        centres = self.profile_prices
        vols    = self.profile_vols
        if len(centres) == 0:
            return

        max_vol    = vols.max() if vols.max() > 0 else 1
        bin_height = centres[1] - centres[0] if len(centres) > 1 else 1.0

        for price, vol in zip(centres, vols):
            # colour by zone membership
            if self.supply_zone and price >= self.supply_zone.bottom:
                color = SUPPLY_COLOR
                alpha = 0.7
            elif self.demand_zone and price <= self.demand_zone.top:
                color = DEMAND_COLOR
                alpha = 0.7
            else:
                color = EQUI_COLOR
                alpha = 0.5

            bar_width = vol / max_vol   # normalised 0–1

            rect = mpatches.FancyBboxPatch(
                (0, price - bin_height / 2),
                bar_width,
                bin_height,
                boxstyle="square,pad=0",
                linewidth=0,
                facecolor=self._hex_rgba(color, alpha),
                zorder=2
            )
            ax_prof.add_patch(rect)

        # zone boundary lines on sidebar
        price_min = centres.min() - bin_height
        price_max = centres.max() + bin_height
        ax_prof.set_ylim(price_min, price_max)
        ax_prof.set_xlim(0, 1.05)
        ax_prof.set_xticks([])
        ax_prof.set_yticks([])
        ax_prof.set_title("Vol\nProfile", color="white", fontsize=7, pad=4)

        if self.supply_zone:
            ax_prof.axhline(self.supply_zone.bottom, color=SUPPLY_COLOR,
                            linewidth=0.8, linestyle="--", alpha=0.8)
        if self.demand_zone:
            ax_prof.axhline(self.demand_zone.top, color=DEMAND_COLOR,
                            linewidth=0.8, linestyle="--", alpha=0.8)

    # ─────────────────────────────────────────────────────────
    #  CONVENIENCE: get zone info as dict
    # ─────────────────────────────────────────────────────────
    def get_zones(self) -> dict:
        """Return detected zones as a plain dict (easy to use in other systems)."""
        return {
            "supply": {
                "top":    self.supply_zone.top    if self.supply_zone else None,
                "bottom": self.supply_zone.bottom if self.supply_zone else None,
                "avg":    self.supply_zone.avg    if self.supply_zone else None,
                "vwap":   self.supply_zone.vwap   if self.supply_zone else None,
            },
            "demand": {
                "top":    self.demand_zone.top    if self.demand_zone else None,
                "bottom": self.demand_zone.bottom if self.demand_zone else None,
                "avg":    self.demand_zone.avg    if self.demand_zone else None,
                "vwap":   self.demand_zone.vwap   if self.demand_zone else None,
            },
            "equilibrium": {
                "avg":  self.equi_avg,
                "vwap": self.equi_vwap,
            }
        }


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

    sd = SupplyDemandIndicator(
        df,
        threshold   = 10.0,   # % of total volume to qualify a zone
        resolution  = 50,     # number of price bins
        last_n_bars = 150,    # treat last 150 bars as "visible range"
    )

    sd.run()
    sd.plot()

    # ── programmatic access ──────────────────────────────────
    zones = sd.get_zones()
    print("Supply zone dict:", zones["supply"])
    print("Demand zone dict:", zones["demand"])
