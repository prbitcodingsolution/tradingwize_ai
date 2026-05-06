"""
LuxAlgo — Liquidity Swings  (Python port)
==========================================
Python port of the Pine Script `Liquidity Swings [LuxAlgo]` indicator
(see liquididty.md in this folder for the original Pine v5 source).

For every `length`-bar fractal swing high / low the indicator tracks:

  • a *liquidity level* — the pivot price (solid line that turns dashed
    once price closes through it, signalling the liquidity has been
    swept);
  • a *liquidity zone* — the wick-to-body (or full) range at the pivot;
  • the number of subsequent bars that *overlap* that zone and the
    volume accumulated during those touches — i.e. how much trading
    interest has stacked up at that level.

A wide accumulation rectangle alongside each zone makes the stacking
visually obvious — the wider the block, the more liquidity has rested
at that level waiting to be taken.

Parameters (Pine defaults)
--------------------------
length : int              Pivot lookback left = right = length (Pine = 14)
eq_tolerance : float      Equal-H/L cluster tolerance as % of pivot price
                          (Pine = 0.2). A pivot is marked `is_cluster=True`
                          when any of the 10 bars immediately preceding it
                          has a high/low within this % of the pivot price
                          — equal highs/lows indicate stacked stop orders
                          and therefore higher-conviction liquidity levels.
area : str                'Wick Extremity' (body of the pivot candle) or
                          'Full Range' (entire candle range)
filter_by : str           'Count' or 'Volume' — what the threshold filters on
filter_value : float      Minimum count/volume for a zone to count as
                          "passed" (Pine default 0 = everything passes)
max_zones : int           Cap active zones rendered per side

Module usage
------------
    from liquidity_swings_indicator import LiquiditySwingsIndicator

    liq = LiquiditySwingsIndicator(df, length=14, area='Wick Extremity')
    liq.run()
    data = liq.get_data()
"""

from typing import Dict, List

import numpy as np
import pandas as pd


class LiquiditySwingsIndicator:
    def __init__(
        self,
        df: pd.DataFrame,
        length: int = 14,
        eq_tolerance: float = 0.2,
        area: str = "Wick Extremity",
        filter_by: str = "Count",
        filter_value: float = 0.0,
        max_zones: int = 10,
        eq_lookback: int = 10,
    ):
        self.df = df.copy()
        self._normalize_columns()
        self.length = int(length)
        self.eq_tolerance = float(eq_tolerance)
        self.area = area
        self.filter_by = filter_by
        self.filter_value = float(filter_value)
        self.max_zones = int(max_zones)
        self.eq_lookback = int(eq_lookback)

        self.high_zones: List[Dict] = []
        self.low_zones: List[Dict] = []

        self._ran = False

    # ------------------------------------------------------------------
    def _normalize_columns(self) -> None:
        col_map = {}
        for c in self.df.columns:
            if isinstance(c, str) and c.lower() in ("open", "high", "low", "close", "volume"):
                col_map[c] = c.capitalize()
        if col_map:
            self.df = self.df.rename(columns=col_map)
        if "Volume" not in self.df.columns:
            self.df["Volume"] = 0.0

    # ------------------------------------------------------------------
    def _compute_fractals(self, series: np.ndarray, kind: str) -> np.ndarray:
        """`length`-bar pivot highs / lows — matches Pine's
        `ta.pivothigh(length, length)` / `ta.pivotlow(length, length)`.
        A pivot at bar `i` is confirmed at bar `i + length`.
        """
        n = len(series)
        flags = np.zeros(n, dtype=bool)
        L = self.length
        if n < 2 * L + 1:
            return flags
        for i in range(L, n - L):
            left = series[i - L:i]
            right = series[i + 1:i + L + 1]
            if kind == "high":
                if series[i] > left.max() and series[i] > right.max():
                    flags[i] = True
            else:
                if series[i] < left.min() and series[i] < right.min():
                    flags[i] = True
        return flags

    # ------------------------------------------------------------------
    def _is_equal_level(
        self,
        series: np.ndarray,
        pivot_bar: int,
        pivot_price: float,
    ) -> bool:
        """Port of Pine's `is_equal_high` / `is_equal_low`:

            for i = 1 to 10
                prev = series[pivot_bar - i]
                if |prev - pivot_price| / pivot_price * 100 <= eq_tolerance
                    found = True

        i.e. scan the `eq_lookback` bars immediately *before* the pivot and
        mark it as a cluster if any of them sit within `eq_tolerance` %
        of the pivot's price.
        """
        if pivot_price == 0:
            return False
        start = max(0, pivot_bar - self.eq_lookback)
        end = pivot_bar  # exclusive — bars strictly before the pivot
        if end <= start:
            return False
        window = series[start:end]
        diffs_pct = np.abs(window - pivot_price) / abs(pivot_price) * 100.0
        return bool(np.any(diffs_pct <= self.eq_tolerance))

    # ------------------------------------------------------------------
    def run(self) -> None:
        n = len(self.df)
        if n < 2 * self.length + 3:
            self._ran = True
            return

        high = self.df["High"].astype(float).values
        low = self.df["Low"].astype(float).values
        close = self.df["Close"].astype(float).values
        open_ = self.df["Open"].astype(float).values
        volume = self.df["Volume"].astype(float).values

        ph_flags = self._compute_fractals(high, "high")
        pl_flags = self._compute_fractals(low, "low")

        # Active zones — one per side, tracked in real-time as we walk bars.
        active_ph = None
        active_pl = None

        for i in range(n):
            # A pivot at `pivot_bar` becomes confirmed at bar `pivot_bar + length`.
            pivot_bar = i - self.length
            if pivot_bar >= 0:
                if ph_flags[pivot_bar]:
                    if active_ph is not None:
                        self.high_zones.append(active_ph)
                    top = float(high[pivot_bar])
                    if self.area == "Wick Extremity":
                        btm = float(max(close[pivot_bar], open_[pivot_bar]))
                    else:  # Full Range
                        btm = float(low[pivot_bar])
                    active_ph = {
                        "direction": "high",
                        "pivot_bar": int(pivot_bar),
                        "confirm_bar": int(i),
                        "pivot_price": top,
                        "zone_top": top,
                        "zone_bottom": btm,
                        "count": 0,
                        "volume": 0.0,
                        "crossed_at": None,
                        # FIX 4: flag equal-highs clusters (stacked stop orders)
                        "is_cluster": self._is_equal_level(high, pivot_bar, top),
                    }

                if pl_flags[pivot_bar]:
                    if active_pl is not None:
                        self.low_zones.append(active_pl)
                    btm = float(low[pivot_bar])
                    if self.area == "Wick Extremity":
                        top = float(min(close[pivot_bar], open_[pivot_bar]))
                    else:
                        top = float(high[pivot_bar])
                    active_pl = {
                        "direction": "low",
                        "pivot_bar": int(pivot_bar),
                        "confirm_bar": int(i),
                        "pivot_price": btm,
                        "zone_top": top,
                        "zone_bottom": btm,
                        "count": 0,
                        "volume": 0.0,
                        "crossed_at": None,
                        # FIX 4: flag equal-lows clusters (stacked stop orders)
                        "is_cluster": self._is_equal_level(low, pivot_bar, btm),
                    }

            # Update active high zone — Pine: count bars where
            #   low < zone_top and high > zone_btm  (bar overlaps the zone)
            # Pivot level is "crossed" when close > pivot_price.
            if active_ph is not None:
                if low[i] < active_ph["zone_top"] and high[i] > active_ph["zone_bottom"]:
                    active_ph["count"] += 1
                    active_ph["volume"] += float(volume[i])
                if active_ph["crossed_at"] is None and close[i] > active_ph["pivot_price"]:
                    active_ph["crossed_at"] = int(i)

            # Update active low zone — mirror: crossed when close < pivot_price
            if active_pl is not None:
                if low[i] < active_pl["zone_top"] and high[i] > active_pl["zone_bottom"]:
                    active_pl["count"] += 1
                    active_pl["volume"] += float(volume[i])
                if active_pl["crossed_at"] is None and close[i] < active_pl["pivot_price"]:
                    active_pl["crossed_at"] = int(i)

        # Flush the active zones
        if active_ph is not None:
            self.high_zones.append(active_ph)
        if active_pl is not None:
            self.low_zones.append(active_pl)

        # Apply filter + cap
        self._apply_filter_and_cap()

        self._ran = True

    # ------------------------------------------------------------------
    def _apply_filter_and_cap(self) -> None:
        """Flag each zone with `passed_filter` (Pine's threshold check)
        and `render_active` (most-recent N per side)."""
        for side in (self.high_zones, self.low_zones):
            for z in side:
                target = z["count"] if self.filter_by == "Count" else z["volume"]
                z["passed_filter"] = target > self.filter_value

            if self.max_zones > 0 and len(side) > self.max_zones:
                for z in side[:-self.max_zones]:
                    z["render_active"] = False
                for z in side[-self.max_zones:]:
                    z["render_active"] = True
            else:
                for z in side:
                    z["render_active"] = True

    # ------------------------------------------------------------------
    def get_data(self) -> Dict:
        if not self._ran:
            raise RuntimeError("Call .run() first.")
        return {
            "high_zones": self.high_zones,
            "low_zones": self.low_zones,
            "df_index": self.df.index,
            "params": {
                "length": self.length,
                "area": self.area,
                "filter_by": self.filter_by,
                "filter_value": self.filter_value,
            },
        }


# ---------------------------------------------------------------------
if __name__ == "__main__":
    try:
        import yfinance as yf
    except ImportError:
        print("Install yfinance:  pip install yfinance")
        raise

    print("Downloading AAPL data …")
    df = yf.download("AAPL", period="1y", interval="1d", progress=False)

    liq = LiquiditySwingsIndicator(df, length=14)
    liq.run()

    print(f"\nHigh liquidity swings: {len(liq.high_zones)}  "
          f"(swept={sum(1 for z in liq.high_zones if z['crossed_at'] is not None)})")
    print(f"Low  liquidity swings: {len(liq.low_zones)}  "
          f"(swept={sum(1 for z in liq.low_zones if z['crossed_at'] is not None)})")
    for z in (liq.high_zones + liq.low_zones)[-6:]:
        state = "swept" if z["crossed_at"] is not None else "live"
        print(
            f"  [{z['direction']:>4}] bar={z['pivot_bar']:>4}  price={z['pivot_price']:.2f}  "
            f"count={z['count']:>3}  vol={z['volume']:.0f}  ({state})"
        )
