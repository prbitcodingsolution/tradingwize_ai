"""
Market Structure Break & Order Block Indicator
==============================================
Python port of the Pine Script `MSB-OB` indicator by EmreKb
(see market_structure.md in this folder for the original Pine v5 source).

The indicator identifies:
  * ZigZag swing pivots driven by a rolling-window highest/lowest break.
  * Market Structure Breaks (MSB) — bullish / bearish structure shifts
    confirmed with a fib_factor buffer against the opposing leg.
  * Order Blocks (Bu-OB / Be-OB) — last opposite-colour candle inside the
    impulse leg that produced the break.
  * Breaker / Mitigation Blocks (Bu-BB / Bu-MB / Be-BB / Be-MB) — last
    opposite-colour candle inside the prior leg; labelled BB when the new
    pivot extends beyond the previous extreme, MB otherwise.

The class exposes plain-dict events (no matplotlib / box objects) so they
can be consumed by the existing drawing_instruction JSON builder pipeline.

Module usage
------------
    from market_structure_indicator import MarketStructureIndicator

    msi = MarketStructureIndicator(df, zigzag_len=9, fib_factor=0.33)
    msi.run()

    data = msi.get_data()    # dict with events + pivots + df_index
"""

from typing import List, Dict, Optional

import numpy as np
import pandas as pd


class MarketStructureIndicator:
    """Port of the `MSB-OB` Pine Script indicator.

    Parameters
    ----------
    df : pd.DataFrame
        OHLC dataframe. Must contain Open / High / Low / Close columns
        (any capitalisation). A DatetimeIndex is expected when the result
        is fed into the JSON builders.
    zigzag_len : int
        Rolling window for pivot detection (Pine default = 9).
    fib_factor : float
        Fibonacci buffer used to confirm a break (Pine default = 0.33).
    """

    def __init__(
        self,
        df: pd.DataFrame,
        zigzag_len: int = 9,
        fib_factor: float = 0.33,
    ):
        self.df = df.copy()
        self._normalize_columns()

        self.zigzag_len = int(zigzag_len)
        self.fib_factor = float(fib_factor)

        self.high_pivots: List[Dict] = []
        self.low_pivots: List[Dict] = []
        self.zigzag_lines: List[Dict] = []
        self.msb_events: List[Dict] = []

        self._ran = False

    # ------------------------------------------------------------------
    #  Helpers
    # ------------------------------------------------------------------
    def _normalize_columns(self) -> None:
        col_map = {}
        for c in self.df.columns:
            if isinstance(c, str) and c.lower() in ("open", "high", "low", "close", "volume"):
                col_map[c] = c.capitalize()
        if col_map:
            self.df = self.df.rename(columns=col_map)

    @staticmethod
    def _find_last_bearish(open_: np.ndarray, close: np.ndarray, start: int, end: int) -> Optional[int]:
        lo, hi = sorted([max(0, start), max(0, end)])
        hi = min(hi, len(open_) - 1)
        last = None
        for i in range(lo, hi + 1):
            if open_[i] > close[i]:
                last = i
        return last

    @staticmethod
    def _find_last_bullish(open_: np.ndarray, close: np.ndarray, start: int, end: int) -> Optional[int]:
        lo, hi = sorted([max(0, start), max(0, end)])
        hi = min(hi, len(open_) - 1)
        last = None
        for i in range(lo, hi + 1):
            if open_[i] < close[i]:
                last = i
        return last

    # ------------------------------------------------------------------
    #  Core
    # ------------------------------------------------------------------
    def run(self) -> None:
        """Populate pivots / zigzag lines / MSB events."""
        n = len(self.df)
        if n < self.zigzag_len + 5:
            self._ran = True
            return

        high = self.df["High"].astype(float).values
        low = self.df["Low"].astype(float).values
        open_ = self.df["Open"].astype(float).values
        close = self.df["Close"].astype(float).values

        self._compute_pivots(high, low, n)
        self._detect_msb(open_, close, high, low)
        self._mark_invalidations(close, n)

        self._ran = True

    # ------------------------------------------------------------------
    def _mark_invalidations(self, close: np.ndarray, n: int) -> None:
        """Pine deletes a Bu-OB/BB when `close < bottom` (bullish side) and a
        Be-OB/BB when `close > top` (bearish side). We replicate that by
        tagging each event's boxes with an `invalidated_at` bar index so
        the JSON builder can choose to skip stale structures."""
        if n == 0:
            return

        for ev in self.msb_events:
            start_bar = ev.get("bar_index", 0)
            direction = ev.get("direction", "bullish")

            for key in ("ob", "bb"):
                box = ev.get(key)
                if not box:
                    continue
                box.setdefault("invalidated_at", None)
                top = float(box.get("high", 0))
                bot = float(box.get("low", 0))
                # Scan bars strictly after the MSB was confirmed
                scan_start = max(start_bar + 1, int(box.get("start_idx", 0)) + 1)
                for i in range(scan_start, n):
                    c = close[i]
                    if direction == "bullish" and c < bot:
                        box["invalidated_at"] = i
                        break
                    if direction == "bearish" and c > top:
                        box["invalidated_at"] = i
                        break

    # ------------------------------------------------------------------
    def _compute_pivots(self, high: np.ndarray, low: np.ndarray, n: int) -> None:
        """Replicate the Pine zigzag — rolling `ta.highest` / `ta.lowest`
        plus a trend state machine that pushes pivots on each flip."""
        rolling_high = pd.Series(high).rolling(self.zigzag_len).max().values
        rolling_low = pd.Series(low).rolling(self.zigzag_len).min().values

        valid_hi = ~np.isnan(rolling_high)
        valid_lo = ~np.isnan(rolling_low)

        to_up = np.where(valid_hi, high >= rolling_high, False)
        to_down = np.where(valid_lo, low <= rolling_low, False)

        trend = 1
        last_to_up = -1
        last_to_down = -1

        for i in range(n):
            # 1-bar lag on to_up / to_down (Pine uses `to_up[1]`)
            if i > 0 and to_up[i - 1]:
                last_to_up = i - 1
            if i > 0 and to_down[i - 1]:
                last_to_down = i - 1

            new_trend = trend
            if trend == 1 and to_down[i]:
                new_trend = -1
            elif trend == -1 and to_up[i]:
                new_trend = 1

            if new_trend != trend:
                if new_trend == 1:
                    start = last_to_up if last_to_up >= 0 else max(i - self.zigzag_len, 0)
                    window = low[start : i + 1]
                    if window.size:
                        price = float(np.min(window))
                        idx = start + int(np.argmin(window))
                        self.low_pivots.append({"bar_index": idx, "price": price})
                else:
                    start = last_to_down if last_to_down >= 0 else max(i - self.zigzag_len, 0)
                    window = high[start : i + 1]
                    if window.size:
                        price = float(np.max(window))
                        idx = start + int(np.argmax(window))
                        self.high_pivots.append({"bar_index": idx, "price": price})

                # Zigzag line between the two most recent pivots
                if self.high_pivots and self.low_pivots:
                    h = self.high_pivots[-1]
                    l = self.low_pivots[-1]
                    if new_trend == 1:
                        self.zigzag_lines.append(
                            {
                                "start_idx": h["bar_index"], "start_price": h["price"],
                                "end_idx": l["bar_index"], "end_price": l["price"],
                                "direction": "down",
                            }
                        )
                    else:
                        self.zigzag_lines.append(
                            {
                                "start_idx": l["bar_index"], "start_price": l["price"],
                                "end_idx": h["bar_index"], "end_price": h["price"],
                                "direction": "up",
                            }
                        )

            trend = new_trend

    # ------------------------------------------------------------------
    def _detect_msb(
        self,
        open_: np.ndarray,
        close: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
    ) -> None:
        """Interleave high/low pivots chronologically and fire an MSB
        event whenever the fib-factor buffered break condition flips the
        market state."""
        ordered = [
            {**p, "type": "H"} for p in self.high_pivots
        ] + [
            {**p, "type": "L"} for p in self.low_pivots
        ]
        ordered.sort(key=lambda x: x["bar_index"])

        market = 1
        last_flip_l0 = None
        last_flip_h0 = None

        for k, piv in enumerate(ordered):
            highs = [p for p in ordered[: k + 1] if p["type"] == "H"]
            lows = [p for p in ordered[: k + 1] if p["type"] == "L"]

            if len(highs) < 2 or len(lows) < 2:
                continue

            h0, h1 = highs[-1], highs[-2]
            l0, l1 = lows[-1], lows[-2]

            # Pine: skip re-evaluation if neither anchor changed since last flip
            if last_flip_l0 == l0["price"] or last_flip_h0 == h0["price"]:
                continue

            new_market = market
            if (
                market == 1
                and l0["price"] < l1["price"]
                and l0["price"] < l1["price"] - abs(h0["price"] - l1["price"]) * self.fib_factor
            ):
                new_market = -1
            elif (
                market == -1
                and h0["price"] > h1["price"]
                and h0["price"] > h1["price"] + abs(h1["price"] - l0["price"]) * self.fib_factor
            ):
                new_market = 1

            if new_market == market:
                continue

            event_bar = piv["bar_index"]

            if new_market == 1:
                # Bullish MSB — horizontal at h1 from h1i → h0i
                msb = {
                    "start_idx": h1["bar_index"], "start_price": h1["price"],
                    "end_idx": h0["bar_index"], "end_price": h1["price"],
                }
                label_idx = (h1["bar_index"] + l0["bar_index"]) // 2

                ob_idx = self._find_last_bearish(
                    open_, close, h1["bar_index"], max(l0["bar_index"] - self.zigzag_len, h1["bar_index"])
                )
                if ob_idx is None:
                    ob_idx = h1["bar_index"]

                bb_idx = self._find_last_bearish(
                    open_, close, max(l1["bar_index"] - self.zigzag_len, 0), h1["bar_index"]
                )
                if bb_idx is None:
                    bb_idx = max(l1["bar_index"] - self.zigzag_len, 0)

                bb_tag = "Bu-BB" if l0["price"] < l1["price"] else "Bu-MB"

                self.msb_events.append(
                    {
                        "direction": "bullish",
                        "bar_index": event_bar,
                        "msb": msb,
                        "label_idx": label_idx,
                        "label_price": h1["price"],
                        "ob": {
                            "start_idx": ob_idx,
                            "high": float(high[ob_idx]),
                            "low": float(low[ob_idx]),
                            "tag": "Bu-OB",
                        },
                        "bb": {
                            "start_idx": bb_idx,
                            "high": float(high[bb_idx]),
                            "low": float(low[bb_idx]),
                            "tag": bb_tag,
                        },
                        "h0": h0, "h1": h1, "l0": l0, "l1": l1,
                    }
                )
            else:
                # Bearish MSB — horizontal at l1 from l1i → l0i
                msb = {
                    "start_idx": l1["bar_index"], "start_price": l1["price"],
                    "end_idx": l0["bar_index"], "end_price": l1["price"],
                }
                label_idx = (l1["bar_index"] + h0["bar_index"]) // 2

                ob_idx = self._find_last_bullish(
                    open_, close, l1["bar_index"], max(h0["bar_index"] - self.zigzag_len, l1["bar_index"])
                )
                if ob_idx is None:
                    ob_idx = l1["bar_index"]

                bb_idx = self._find_last_bullish(
                    open_, close, max(h1["bar_index"] - self.zigzag_len, 0), l1["bar_index"]
                )
                if bb_idx is None:
                    bb_idx = max(h1["bar_index"] - self.zigzag_len, 0)

                bb_tag = "Be-BB" if h0["price"] > h1["price"] else "Be-MB"

                self.msb_events.append(
                    {
                        "direction": "bearish",
                        "bar_index": event_bar,
                        "msb": msb,
                        "label_idx": label_idx,
                        "label_price": l1["price"],
                        "ob": {
                            "start_idx": ob_idx,
                            "high": float(high[ob_idx]),
                            "low": float(low[ob_idx]),
                            "tag": "Be-OB",
                        },
                        "bb": {
                            "start_idx": bb_idx,
                            "high": float(high[bb_idx]),
                            "low": float(low[bb_idx]),
                            "tag": bb_tag,
                        },
                        "h0": h0, "h1": h1, "l0": l0, "l1": l1,
                    }
                )

            market = new_market
            last_flip_l0 = l0["price"]
            last_flip_h0 = h0["price"]

    # ------------------------------------------------------------------
    #  Public accessors
    # ------------------------------------------------------------------
    def get_data(self) -> Dict:
        """Return the full indicator payload for the JSON builder."""
        if not self._ran:
            raise RuntimeError("Call .run() first.")
        return {
            "events": self.msb_events,
            "high_pivots": self.high_pivots,
            "low_pivots": self.low_pivots,
            "zigzag_lines": self.zigzag_lines,
            "df_index": self.df.index,
            "params": {"zigzag_len": self.zigzag_len, "fib_factor": self.fib_factor},
        }

    def get_events(self) -> List[Dict]:
        if not self._ran:
            raise RuntimeError("Call .run() first.")
        return self.msb_events


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
    df = yf.download("AAPL", period="1y", interval="1d", progress=False)

    msi = MarketStructureIndicator(df, zigzag_len=9, fib_factor=0.33)
    msi.run()

    print(f"\nPivots detected:  highs={len(msi.high_pivots)}  lows={len(msi.low_pivots)}")
    print(f"MSB events:        {len(msi.msb_events)}")
    for e in msi.msb_events[-5:]:
        print(
            f"  [{e['direction']:>7}] bar={e['bar_index']:>4}  "
            f"OB={e['ob']['tag']} @ {e['ob']['start_idx']}  "
            f"BB={e['bb']['tag']} @ {e['bb']['start_idx']}"
        )
