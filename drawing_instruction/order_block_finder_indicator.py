"""
wugamlo — Order Block Finder  (Python port)
===========================================
Python port of the `Order Block Finder` Pine Script by © wugamlo
(see order_block.md in this folder for the original Pine v4 source).

The indicator identifies institutional order blocks defined as:

  • Bullish OB — the LAST down candle before a sequence of `periods`
    (default 5) consecutive up candles, provided the % move from the
    OB candle's close to the last candle in the sequence meets the
    `threshold`. Zone = Open→Low (body) or High→Low (`usewicks=True`).

  • Bearish OB — the LAST up candle before a sequence of `periods`
    consecutive down candles under the same % filter. Zone = High→Open
    (body) or High→Low (`usewicks=True`).

Each detected OB carries its high, low, avg (mid-line), volume, and an
`invalidated_at` flag (first bar where close closes through the OB —
below Low for bullish, above High for bearish). Per-side caps (`max_obs`)
keep the rendered output manageable.

Parameters (Pine defaults)
--------------------------
periods : int          Required sequential candles  (Pine default = 5)
threshold : float      Min. % move to validate the OB (Pine default = 0.0)
usewicks : bool        Use the full candle range for the OB zone
max_obs : int          Cap active OBs rendered per side (sanity default 6)
show_broken : bool     Keep invalidated OBs in the output (faded)

Module usage
------------
    from order_block_finder_indicator import OrderBlockFinderIndicator

    ob = OrderBlockFinderIndicator(df, periods=5, threshold=0.3)
    ob.run()
    data = ob.get_data()
"""

from typing import Dict, List

import numpy as np
import pandas as pd


class OrderBlockFinderIndicator:
    def __init__(
        self,
        df: pd.DataFrame,
        periods: int = 5,
        threshold: float = 0.0,
        usewicks: bool = False,
        max_obs: int = 6,
        show_broken: bool = False,
    ):
        self.df = df.copy()
        self._normalize_columns()
        self.periods = int(periods)
        self.threshold = float(threshold)
        self.usewicks = bool(usewicks)
        self.max_obs = int(max_obs)
        self.show_broken = bool(show_broken)

        if self.periods < 1:
            raise ValueError("periods must be >= 1")
        if self.threshold < 0:
            raise ValueError("threshold must be >= 0")

        self.bull_obs: List[Dict] = []
        self.bear_obs: List[Dict] = []

        self._ran = False

    # ------------------------------------------------------------------
    def _normalize_columns(self) -> None:
        # yfinance.download() returns a MultiIndex (e.g. ('Open', 'AAPL')) —
        # flatten to the OHLCV level so the rest of the pipeline can use
        # plain string columns.
        if isinstance(self.df.columns, pd.MultiIndex):
            ohlcv = {"open", "high", "low", "close", "volume"}
            for level in range(self.df.columns.nlevels):
                values = [str(v).lower() for v in self.df.columns.get_level_values(level)]
                if any(v in ohlcv for v in values):
                    self.df.columns = self.df.columns.get_level_values(level)
                    break

        col_map = {}
        for c in self.df.columns:
            name = str(c)
            if name.lower() in ("open", "high", "low", "close", "volume"):
                col_map[c] = name.capitalize()
        if col_map:
            self.df = self.df.rename(columns=col_map)

        for required in ("Open", "High", "Low", "Close"):
            if required not in self.df.columns:
                raise ValueError(
                    f"OrderBlockFinderIndicator: missing required column '{required}'. "
                    f"Got columns: {list(self.df.columns)}"
                )
        if "Volume" not in self.df.columns:
            self.df["Volume"] = 0.0

    # ------------------------------------------------------------------
    def run(self) -> None:
        n = len(self.df)
        ob_period = self.periods + 1
        # Pine needs only `ob_period + 1` bars to evaluate the formula at
        # the first eligible bar (where `close[ob_period]` and `close[1]`
        # both exist). The previous `+ 2` margin silently dropped one
        # detection on small datasets.
        if n < ob_period + 1:
            self._ran = True
            return

        high = self.df["High"].astype(float).values
        low = self.df["Low"].astype(float).values
        close = self.df["Close"].astype(float).values
        open_ = self.df["Open"].astype(float).values
        volume = self.df["Volume"].astype(float).values

        # Precompute candle direction flags
        is_red = close < open_
        is_green = close > open_

        # Scan bar-by-bar — at bar `i` the candidate OB candle is at `i - ob_period`
        for i in range(ob_period, n):
            ob_bar = i - ob_period
            if ob_bar < 0:
                continue

            # Absolute move from OB close → close of the last sequential bar (i-1)
            ob_close = close[ob_bar]
            last_seq_close = close[i - 1]
            if ob_close == 0:
                continue
            abs_move_pct = abs(ob_close - last_seq_close) / ob_close * 100.0
            rel_move = abs_move_pct >= self.threshold

            # ---- Bullish OB: red OB candle + `periods` green candles ----
            if is_red[ob_bar] and rel_move:
                seq_ok = True
                for j in range(1, self.periods + 1):
                    k = i - j
                    if not is_green[k]:
                        seq_ok = False
                        break
                if seq_ok:
                    ob_high = float(high[ob_bar]) if self.usewicks else float(open_[ob_bar])
                    ob_low = float(low[ob_bar])
                    self.bull_obs.append(
                        {
                            "direction": "bullish",
                            "bar_index": int(ob_bar),
                            "detect_bar": int(i),      # bar where the sequence was confirmed
                            "high": ob_high,
                            "low": ob_low,
                            "avg": (ob_high + ob_low) / 2.0,
                            "volume": float(volume[ob_bar]),
                            "move_pct": float(abs_move_pct),
                            "invalidated_at": None,
                        }
                    )

            # ---- Bearish OB: green OB candle + `periods` red candles ----
            if is_green[ob_bar] and rel_move:
                seq_ok = True
                for j in range(1, self.periods + 1):
                    k = i - j
                    if not is_red[k]:
                        seq_ok = False
                        break
                if seq_ok:
                    ob_high = float(high[ob_bar])
                    ob_low = float(low[ob_bar]) if self.usewicks else float(open_[ob_bar])
                    self.bear_obs.append(
                        {
                            "direction": "bearish",
                            "bar_index": int(ob_bar),
                            "detect_bar": int(i),
                            "high": ob_high,
                            "low": ob_low,
                            "avg": (ob_high + ob_low) / 2.0,
                            "volume": float(volume[ob_bar]),
                            "move_pct": float(abs_move_pct),
                            "invalidated_at": None,
                        }
                    )

        # Invalidation — price closes through the OB bound in the wrong direction.
        self._mark_invalidations(close, n)

        # Cap: pick the per-side render budget — un-invalidated OBs first.
        self._apply_cap()

        self._ran = True

    # ------------------------------------------------------------------
    def _mark_invalidations(self, close: np.ndarray, n: int) -> None:
        for ob in self.bull_obs:
            for i in range(ob["detect_bar"] + 1, n):
                if close[i] < ob["low"]:
                    ob["invalidated_at"] = int(i)
                    break
        for ob in self.bear_obs:
            for i in range(ob["detect_bar"] + 1, n):
                if close[i] > ob["high"]:
                    ob["invalidated_at"] = int(i)
                    break

    # ------------------------------------------------------------------
    def _apply_cap(self) -> None:
        """Choose which OBs the renderer should display. Pine doesn't
        cap or hide anything, but a chart of dozens of historical OBs is
        unreadable, so we surface the most useful subset.

        Strategy: fill the `max_obs` budget per side with the most-recent
        un-invalidated OBs first (those are actionable levels), then fall
        back to the most-recent mitigated OBs for any remaining slots
        (they still show institutional history). Without this, a stretch
        where the latest OBs all got broken would silently hide every
        active level — which looked like the indicator was "missing" OBs.
        """
        for side in (self.bull_obs, self.bear_obs):
            for ob in side:
                ob["render_active"] = False

            if self.max_obs <= 0:
                for ob in side:
                    ob["render_active"] = True
                continue

            budget = self.max_obs
            # Newest first — within each group, pick the most recent.
            active_recent = [ob for ob in reversed(side) if ob.get("invalidated_at") is None]
            broken_recent = [ob for ob in reversed(side) if ob.get("invalidated_at") is not None]

            for ob in active_recent[:budget]:
                ob["render_active"] = True
                budget -= 1
            for ob in broken_recent[:budget]:
                ob["render_active"] = True

    # ------------------------------------------------------------------
    def get_data(self) -> Dict:
        if not self._ran:
            raise RuntimeError("Call .run() first.")
        return {
            "bull_obs": self.bull_obs,
            "bear_obs": self.bear_obs,
            "df_index": self.df.index,
            "params": {
                "periods": self.periods,
                "threshold": self.threshold,
                "usewicks": self.usewicks,
                "max_obs": self.max_obs,
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

    ob = OrderBlockFinderIndicator(df, periods=5, threshold=0.3)
    ob.run()

    print(f"\nBullish OBs: {len(ob.bull_obs)}  "
          f"(active={sum(1 for o in ob.bull_obs if o['render_active'])})")
    print(f"Bearish OBs: {len(ob.bear_obs)}  "
          f"(active={sum(1 for o in ob.bear_obs if o['render_active'])})")
    for o in (ob.bull_obs + ob.bear_obs)[-6:]:
        print(
            f"  [{o['direction']:>7}] bar={o['bar_index']:>4}  "
            f"zone=[{o['low']:.2f}, {o['high']:.2f}]  "
            f"move={o['move_pct']:.2f}%  inv={o.get('invalidated_at')}"
        )
