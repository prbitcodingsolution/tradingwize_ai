"""
BigBeluga — Smart Money Concepts (Price Action) indicator
=========================================================
Python port of the Pine Script `BigBeluga - Smart Money Concepts` indicator
(see price_action.md in this folder for the original Pine v5 source).

The indicator produces three families of signals for a price-action / SMC
trading workflow:

  1.  Market-structure events
        • BOS   — break-of-structure (trend continuation)
        • CHoCH — change-of-character  (trend reversal)
        • sweep — wick beyond a structure level that closes back inside
      Each event stores the break bar, the originating pivot bar, the
      broken price level, and the direction (bullish / bearish).

  2.  Volumetric Order Blocks
        At every confirmed BOS / CHoCH we freeze the opposite-side pivot
        as a volumetric OB — an ATR-wide zone that acts as future
        support (bullish break) or resistance (bearish break). The OB
        carries the pivot-bar volume + a candle-direction flag so the
        JSON builder can draw the buy/sell activity split.

  3.  Swing pivots
        Full 5-bar fractal highs/lows used for the mapping polyline /
        bubble overlay.

Parameters
----------
mslen : int         Pivot fractal length   (Pine default = 5)
atr_length : int    ATR window for OB sizing (Pine = 200, we auto-scale
                    for shorter data sets — see FVG-OB indicator for the
                    same rationale)
ob_length : int     Scale factor for OB height; Pine divides atr by
                    `5/len` so larger ob_length → taller zones. Default 5.
obmode : str        'Length' → use atr-based zone height
                    'Full'   → use the full candle range
show_sweep : bool   When False, sweeps are suppressed entirely
ob_last : int       Keep only the most-recent N active OBs per side
"""

from typing import Dict, List, Optional

import numpy as np
import pandas as pd


class PriceActionSMCIndicator:
    def __init__(
        self,
        df: pd.DataFrame,
        mslen: int = 5,
        atr_length: int = 200,
        ob_length: int = 5,
        obmode: str = "Length",
        show_sweep: bool = True,
        ob_last: int = 5,
        mitigation: str = "Close",   # 'Close' | 'Wick' | 'Avg'
    ):
        self.df = df.copy()
        self._normalize_columns()
        self.mslen = int(mslen)
        self.atr_length = int(atr_length)
        self.ob_length = int(ob_length)
        self.obmode = obmode
        self.show_sweep = bool(show_sweep)
        self.ob_last = int(ob_last)
        self.mitigation = mitigation

        # Auto-reduce atr_length for short datasets (same trick used by the
        # FVG-OB indicator — Pine's 200-bar ATR requires 200 bars of warmup
        # which leaves nothing on a typical 300-bar window).
        n = len(self.df)
        if n and self.atr_length > max(20, n - 30):
            self.atr_length = max(20, n - 30)

        self.events: List[Dict] = []
        self.order_blocks: List[Dict] = []
        self.pivot_highs: List[Dict] = []
        self.pivot_lows: List[Dict] = []

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

    @staticmethod
    def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, length: int) -> np.ndarray:
        """RMA-based ATR (Wilder) matching Pine's `ta.atr()`."""
        n = len(close)
        if n == 0 or length <= 0:
            return np.full(n, np.nan)
        prev_close = np.roll(close, 1)
        prev_close[0] = close[0]
        tr = np.maximum.reduce(
            [high - low, np.abs(high - prev_close), np.abs(low - prev_close)]
        )
        atr = np.full(n, np.nan)
        if n < length:
            return atr
        atr[length - 1] = float(np.nanmean(tr[:length]))
        alpha = 1.0 / length
        for i in range(length, n):
            atr[i] = (1 - alpha) * atr[i - 1] + alpha * tr[i]
        return atr

    # ------------------------------------------------------------------
    def _compute_fractals(self, series: np.ndarray, kind: str) -> np.ndarray:
        """5-bar (or `mslen`-bar) fractal pivots — Pine's `ta.pivothigh` /
        `ta.pivotlow`. The pivot is *confirmed* `mslen` bars later.
        """
        n = len(series)
        flags = np.zeros(n, dtype=bool)
        L = self.mslen
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
    def run(self) -> None:
        """Populate events, order_blocks, pivot lists."""
        n = len(self.df)
        if n < 2 * self.mslen + 3:
            self._ran = True
            return

        high = self.df["High"].astype(float).values
        low = self.df["Low"].astype(float).values
        close = self.df["Close"].astype(float).values
        open_ = self.df["Open"].astype(float).values
        volume = self.df["Volume"].astype(float).values

        ph_flags = self._compute_fractals(high, "high")
        pl_flags = self._compute_fractals(low, "low")
        atr = self._atr(high, low, close, self.atr_length)

        self.pivot_highs = [
            {"bar_index": int(i), "price": float(high[i])} for i in range(n) if ph_flags[i]
        ]
        self.pivot_lows = [
            {"bar_index": int(i), "price": float(low[i])} for i in range(n) if pl_flags[i]
        ]

        # Active watch-levels: pivots that haven't yet been broken
        watch_highs: List[tuple] = []  # [(pivot_bar, price)]
        watch_lows: List[tuple] = []

        trend = 0   # 0 = neutral, 1 = bullish, -1 = bearish

        for i in range(n):
            # 1) Confirm pivots whose fractal-right side has just filled in.
            #    A pivot at bar `i - mslen` becomes confirmed at bar `i`.
            pivot_bar = i - self.mslen
            if pivot_bar >= self.mslen:
                if ph_flags[pivot_bar]:
                    watch_highs.append((int(pivot_bar), float(high[pivot_bar])))
                if pl_flags[pivot_bar]:
                    watch_lows.append((int(pivot_bar), float(low[pivot_bar])))

            c = close[i]
            h = high[i]
            l = low[i]

            # 2) Bullish break — close above the most-recent un-broken pivot high
            broken_high = None
            if watch_highs:
                for idx, price in reversed(watch_highs):
                    if c > price:
                        broken_high = (idx, price)
                        break

            if broken_high is not None:
                event_type = "BOS" if trend == 1 else "CHoCH"
                self.events.append(
                    {
                        "type": event_type,
                        "direction": "bullish",
                        "bar_index": int(i),
                        "origin_bar": int(broken_high[0]),
                        "price": float(broken_high[1]),
                    }
                )
                trend = 1
                # Consume every watched high at or below the broken level
                watch_highs = [(idx, p) for (idx, p) in watch_highs if p > broken_high[1]]

                # Create bullish OB at the most-recent unbroken pivot low
                self._add_ob(
                    direction="bullish",
                    pivot_lows=watch_lows,
                    pivot_bar_limit=i,
                    event_bar=i,
                    event_type=event_type,
                    atr_val=atr[i] if not np.isnan(atr[i]) else None,
                    high=high, low=low, close=close, open_=open_, volume=volume,
                )

            # 3) Bearish break — close below the most-recent un-broken pivot low
            broken_low = None
            if watch_lows:
                for idx, price in reversed(watch_lows):
                    if c < price:
                        broken_low = (idx, price)
                        break

            if broken_low is not None:
                event_type = "BOS" if trend == -1 else "CHoCH"
                self.events.append(
                    {
                        "type": event_type,
                        "direction": "bearish",
                        "bar_index": int(i),
                        "origin_bar": int(broken_low[0]),
                        "price": float(broken_low[1]),
                    }
                )
                trend = -1
                watch_lows = [(idx, p) for (idx, p) in watch_lows if p < broken_low[1]]

                self._add_ob(
                    direction="bearish",
                    pivot_highs=watch_highs,
                    pivot_bar_limit=i,
                    event_bar=i,
                    event_type=event_type,
                    atr_val=atr[i] if not np.isnan(atr[i]) else None,
                    high=high, low=low, close=close, open_=open_, volume=volume,
                )

            # 4) Sweep detection — wick through without close confirmation
            if self.show_sweep:
                if broken_high is None and watch_highs:
                    for idx, price in reversed(watch_highs):
                        if h > price and c <= price:
                            self.events.append(
                                {
                                    "type": "sweep",
                                    "direction": "bullish",
                                    "bar_index": int(i),
                                    "origin_bar": int(idx),
                                    "price": float(price),
                                }
                            )
                            break
                if broken_low is None and watch_lows:
                    for idx, price in reversed(watch_lows):
                        if l < price and c >= price:
                            self.events.append(
                                {
                                    "type": "sweep",
                                    "direction": "bearish",
                                    "bar_index": int(i),
                                    "origin_bar": int(idx),
                                    "price": float(price),
                                }
                            )
                            break

        self._mark_ob_invalidations(high, low, close, open_, n)
        self._cap_active_obs()
        self._ran = True

    # ------------------------------------------------------------------
    def _add_ob(
        self,
        *,
        direction: str,
        event_bar: int,
        event_type: str,
        atr_val: Optional[float],
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        open_: np.ndarray,
        volume: np.ndarray,
        pivot_lows: List[tuple] = None,
        pivot_highs: List[tuple] = None,
        pivot_bar_limit: int = 0,
    ) -> None:
        """Freeze the opposite-side pivot as a volumetric OB.

        Pine semantics:
            bullish break  → OB at the most-recent pivot low
                             top = low[idx] + atr (or high[idx] if 'Full')
                             btm = low[idx]
            bearish break  → OB at the most-recent pivot high
                             top = high[idx]
                             btm = high[idx] - atr (or low[idx] if 'Full')
        """
        if direction == "bullish":
            candidates = [(idx, p) for (idx, p) in (pivot_lows or []) if idx < pivot_bar_limit]
            if not candidates:
                return
            pl_idx, pl_price = candidates[-1]
            bottom = float(pl_price)
            if self.obmode == "Length" and atr_val is not None:
                zone = atr_val / max(1.0, 5.0 / self.ob_length)
                top = bottom + zone
                # Clip to actual candle high so we don't project above real price
                if top > high[pl_idx]:
                    top = float(high[pl_idx])
            else:
                top = float(high[pl_idx])
        else:
            candidates = [(idx, p) for (idx, p) in (pivot_highs or []) if idx < pivot_bar_limit]
            if not candidates:
                return
            ph_idx, ph_price = candidates[-1]
            top = float(ph_price)
            if self.obmode == "Length" and atr_val is not None:
                zone = atr_val / max(1.0, 5.0 / self.ob_length)
                bottom = top - zone
                if bottom < low[ph_idx]:
                    bottom = float(low[ph_idx])
            else:
                bottom = float(low[ph_idx])
            pl_idx = ph_idx  # reuse for candle metadata

        candle_dir = 1 if close[pl_idx] > open_[pl_idx] else -1

        self.order_blocks.append(
            {
                "direction": direction,
                "bar_index": int(pl_idx),
                "top": float(top),
                "bottom": float(bottom),
                "avg": float((top + bottom) / 2.0),
                "volume": float(volume[pl_idx]) if pl_idx < len(volume) else 0.0,
                "candle_dir": int(candle_dir),
                "event_bar": int(event_bar),
                "event_type": event_type,
                "invalidated_at": None,
                "render_active": True,   # set False later by _cap_active_obs
            }
        )

    # ------------------------------------------------------------------
    def _mark_ob_invalidations(
        self,
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        open_: np.ndarray,
        n: int,
    ) -> None:
        """Pine's `mitigated()` — using the configured mitigation method,
        flag the first bar where price has invalidated each OB.
        """
        for ob in self.order_blocks:
            btm = ob["bottom"]
            top = ob["top"]
            avg = ob["avg"]
            start = ob["event_bar"] + 1
            for i in range(start, n):
                if ob["direction"] == "bullish":
                    if self.mitigation == "Close" and min(close[i], open_[i]) < btm:
                        ob["invalidated_at"] = int(i); break
                    if self.mitigation == "Wick" and low[i] < btm:
                        ob["invalidated_at"] = int(i); break
                    if self.mitigation == "Avg" and low[i] < avg:
                        ob["invalidated_at"] = int(i); break
                else:
                    if self.mitigation == "Close" and max(close[i], open_[i]) > top:
                        ob["invalidated_at"] = int(i); break
                    if self.mitigation == "Wick" and high[i] > top:
                        ob["invalidated_at"] = int(i); break
                    if self.mitigation == "Avg" and high[i] > avg:
                        ob["invalidated_at"] = int(i); break

    # ------------------------------------------------------------------
    def _cap_active_obs(self) -> None:
        """Keep only the most-recent `ob_last` un-invalidated OBs per side
        marked as active (render_active=True). Older / broken ones stay in
        the list with render_active=False for historical context.
        """
        bulls = [ob for ob in self.order_blocks if ob["direction"] == "bullish"]
        bears = [ob for ob in self.order_blocks if ob["direction"] == "bearish"]
        for side in (bulls, bears):
            active = [ob for ob in side if ob.get("invalidated_at") is None]
            if len(active) <= self.ob_last:
                continue
            # Mark only the last `ob_last` as active; the rest are shown faded
            for ob in active[:-self.ob_last]:
                ob["render_active"] = False

    # ------------------------------------------------------------------
    def get_data(self) -> Dict:
        if not self._ran:
            raise RuntimeError("Call .run() first.")
        return {
            "events": self.events,
            "order_blocks": self.order_blocks,
            "pivot_highs": self.pivot_highs,
            "pivot_lows": self.pivot_lows,
            "df_index": self.df.index,
            "params": {
                "mslen": self.mslen,
                "atr_length": self.atr_length,
                "ob_length": self.ob_length,
                "obmode": self.obmode,
                "ob_last": self.ob_last,
            },
        }


# ---------------------------------------------------------------------
#  CLI test
# ---------------------------------------------------------------------
if __name__ == "__main__":
    try:
        import yfinance as yf
    except ImportError:
        print("Install yfinance:  pip install yfinance")
        raise

    print("Downloading AAPL data …")
    df = yf.download("AAPL", period="2y", interval="1d", progress=False)

    smc = PriceActionSMCIndicator(df, mslen=5, atr_length=200, ob_length=5)
    smc.run()

    print(f"\nPivots  highs={len(smc.pivot_highs)}  lows={len(smc.pivot_lows)}")
    print(f"Events  total={len(smc.events)}")
    for e in smc.events[-6:]:
        print(f"  [{e['direction']:>7}] {e['type']:>5}  "
              f"bar={e['bar_index']:>4}  price={e['price']:.2f}")
    print(f"Order blocks  total={len(smc.order_blocks)}  "
          f"active={sum(1 for ob in smc.order_blocks if ob['render_active'] and ob['invalidated_at'] is None)}")
