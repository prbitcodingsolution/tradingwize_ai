"""
Fair Value Gap (FVG) Order Blocks — BigBeluga Pine port
=======================================================
Python port of the Pine Script `FVG Order Blocks [BigBeluga]` indicator.
(see fvg.md in this folder for the original Pine v5 source).

For every 3-candle imbalance that passes the % filter we emit:

  • a *gap box* — the tight rectangle describing the actual imbalance
    (the area price skipped), spanning from bar_index-1 to bar_index+5;
  • an *order-block* — an ATR-wide zone sitting directly below the
    bullish gap (or above the bearish gap) that extends forward to the
    right edge of the chart; it is the consumable support/resistance.

Invalidation rules mirror the Pine script:
  • A bullish block is *broken* when a later bar's `high` drops below
    the block's bottom — the block is dropped (or faded).
  • A bearish block is *broken* when a later bar's `low` rises above
    the block's top.
  • Overlap: when a newer block is fully contained inside an older
    block's range, the older one is discarded to avoid stacking.

Parameters:
    filter_pct = 0.5   (minimum gap % of price — Pine default)
    box_amount = 6     (keep the most-recent N blocks per side — Pine default)
    atr_length = 50    (ATR warmup for OB-zone sizing; Pine hardcodes 200
                       but that requires ~200 bars of warmup before *any*
                       detection fires — on the typical 300-bar daily window
                       the pipeline sends us, that leaves only ~100 bars of
                       valid detection, often producing just 0–1 blocks.
                       50 is a pragmatic default that preserves zone shape
                       while giving reliable coverage on shorter windows.
                       Set atr_length=200 if you have 400+ bars of history
                       and want the Pine-exact visual.)

Module usage
------------
    from fvg_order_blocks_indicator import FVGOrderBlocksIndicator

    fvg = FVGOrderBlocksIndicator(df, filter_pct=0.5, box_amount=6)
    fvg.run()

    data = fvg.get_data()   # dict consumed by json_builder
"""

from typing import Dict, List, Optional

import numpy as np
import pandas as pd


class FVGOrderBlocksIndicator:
    """BigBeluga FVG Order Blocks — faithful Python port.

    Parameters
    ----------
    df : pd.DataFrame
        OHLC dataframe. Must contain Open / High / Low / Close columns
        (any capitalisation). A DatetimeIndex is expected when the result
        is fed into the JSON builders.
    filter_pct : float
        Minimum gap % of price (Pine default = 0.5).
    box_amount : int
        Keep the most-recent N blocks per side (Pine default = 6).
    atr_length : int
        ATR period used to size the order-block zone. Pine hardcodes 200
        but we default to 50 so detection still fires on ~300-bar windows.
        Set to 200 if you have 400+ bars and want the Pine-exact visual.
    lookback : int
        Pine caps detection to the most recent N bars (Pine default = 2000).
    show_broken : bool
        When True we retain invalidated blocks (rendered faded by the
        builder). Default False matches Pine's `show_broken=false`.
    """

    def __init__(
        self,
        df: pd.DataFrame,
        filter_pct: float = 0.5,
        box_amount: int = 6,
        atr_length: int = 50,
        lookback: int = 2000,
        show_broken: bool = False,
    ):
        self.df = df.copy()
        self._normalize_columns()

        self.filter_pct = float(filter_pct)
        self.box_amount = int(box_amount)
        self.atr_length = int(atr_length)
        self.lookback = int(lookback)
        self.show_broken = bool(show_broken)

        self.bull_blocks: List[Dict] = []
        self.bear_blocks: List[Dict] = []

        self._ran = False

    # ------------------------------------------------------------------
    def _normalize_columns(self) -> None:
        col_map = {}
        for c in self.df.columns:
            if isinstance(c, str) and c.lower() in ("open", "high", "low", "close", "volume"):
                col_map[c] = c.capitalize()
        if col_map:
            self.df = self.df.rename(columns=col_map)

    @staticmethod
    def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, length: int) -> np.ndarray:
        """RMA-based ATR matching Pine's `ta.atr()`."""
        n = len(close)
        if n == 0:
            return np.array([])
        prev_close = np.roll(close, 1)
        prev_close[0] = close[0]
        tr = np.maximum.reduce(
            [high - low, np.abs(high - prev_close), np.abs(low - prev_close)]
        )
        # Wilder / RMA smoothing: alpha = 1/length
        atr = np.full(n, np.nan)
        if n < length:
            return atr
        # Seed with simple mean of the first `length` TR values
        seed = np.nanmean(tr[:length])
        atr[length - 1] = seed
        alpha = 1.0 / length
        for i in range(length, n):
            atr[i] = (1 - alpha) * atr[i - 1] + alpha * tr[i]
        return atr

    # ------------------------------------------------------------------
    def run(self) -> None:
        """Populate bull_blocks / bear_blocks with every detected FVG."""
        n = len(self.df)
        if n < max(self.atr_length, 3):
            self._ran = True
            return

        high = self.df["High"].astype(float).values
        low = self.df["Low"].astype(float).values
        close = self.df["Close"].astype(float).values

        atr = self._atr(high, low, close, self.atr_length)

        scan_start = max(self.atr_length, 2)
        scan_start = max(scan_start, n - self.lookback)

        # First pass — detect every 3-candle imbalance that passes the filter
        for i in range(scan_start, n):
            h2 = high[i - 2]
            l2 = low[i - 2]
            h1 = high[i - 1]
            l1 = low[i - 1]
            h0 = high[i]
            l0 = low[i]
            a = atr[i]

            if np.isnan(a):
                continue

            # ── Bullish FVG: low[i] > high[i-2], middle bar extends above ──
            if h2 < l0 and h2 < h1 and l2 < l0:
                gap_pct = (l0 - h2) / l0 * 100.0 if l0 != 0 else 0.0
                if gap_pct > self.filter_pct:
                    self.bull_blocks.append(
                        {
                            "direction": "bullish",
                            "bar_index": i,           # current bar
                            "gap_left_idx": i - 1,    # Pine: bar_index - 1
                            "gap_right_idx": i + 5,   # Pine: bar_index + 5
                            # Gap rectangle (the imbalance itself)
                            "gap_top": float(l0),
                            "gap_bottom": float(h2),
                            # Order-block zone (ATR-wide, sits under the gap top)
                            "ob_top": float(h2),
                            "ob_bottom": float(h2 - a),
                            "gap_pct": float(gap_pct),
                            "atr": float(a),
                            "invalidated_at": None,
                        }
                    )

            # ── Bearish FVG: high[i] < low[i-2], middle bar extends below ─
            if l2 > h0 and l2 > l1 and h2 > h0:
                gap_pct = (l2 - h0) / l2 * 100.0 if l2 != 0 else 0.0
                if gap_pct > self.filter_pct:
                    self.bear_blocks.append(
                        {
                            "direction": "bearish",
                            "bar_index": i,
                            "gap_left_idx": i - 1,
                            "gap_right_idx": i + 5,
                            # Gap rectangle (the imbalance itself)
                            "gap_top": float(l2),
                            "gap_bottom": float(h0),
                            # Order-block zone above the gap bottom
                            "ob_top": float(l2 + a),
                            "ob_bottom": float(l2),
                            "gap_pct": float(gap_pct),
                            "atr": float(a),
                            "invalidated_at": None,
                        }
                    )

        # Invalidation is computed on every detected block so the builder
        # can choose how to style stale blocks.
        self._mark_invalidations(high, low, n)

        # Pine keeps the small grey "gap" labels for every detected FVG
        # (they're transient `box.new` calls that are never deleted), but
        # the colored "order block" zones live in `boxes1/2` which are
        # subject to overlap suppression and the `box_amount` cap.
        #
        # We replicate that by flagging each block with:
        #   render_gap = True   (always — matches Pine's historical record)
        #   render_ob  = True only for blocks that survive the Pine rules
        for b in self.bull_blocks + self.bear_blocks:
            b["render_gap"] = True
            b["render_ob"] = True

        # 1) Overlap suppression — only on the OB subset
        self._drop_overlaps_in_place(self.bull_blocks, attr="render_ob")
        self._drop_overlaps_in_place(self.bear_blocks, attr="render_ob")

        # 2) Broken OBs fall out of the active OB list (unless show_broken)
        if not self.show_broken:
            for b in self.bull_blocks + self.bear_blocks:
                if b.get("invalidated_at") is not None:
                    b["render_ob"] = False

        # 3) Cap active OB count per side — Pine: `box.delete(boxes1.shift())`
        if self.box_amount > 0:
            self._cap_active_obs(self.bull_blocks, self.box_amount)
            self._cap_active_obs(self.bear_blocks, self.box_amount)

        self._ran = True

    # ------------------------------------------------------------------
    def _mark_invalidations(self, high: np.ndarray, low: np.ndarray, n: int) -> None:
        """Pine rules:
           * Bullish OB broken when `high < box.bottom` on a later bar.
           * Bearish OB broken when `low  > box.top`    on a later bar.
        We tag the first bar where that happens so the builder can decide
        whether to fade, truncate, or drop the drawing.
        """
        for blk in self.bull_blocks:
            ob_bottom = blk["ob_bottom"]
            for i in range(blk["bar_index"] + 1, n):
                if high[i] < ob_bottom:
                    blk["invalidated_at"] = i
                    break

        for blk in self.bear_blocks:
            ob_top = blk["ob_top"]
            for i in range(blk["bar_index"] + 1, n):
                if low[i] > ob_top:
                    blk["invalidated_at"] = i
                    break

    # ------------------------------------------------------------------
    @staticmethod
    def _drop_overlaps_in_place(blocks: List[Dict], attr: str = "render_ob") -> None:
        """Pine suppresses older blocks when a newer block's top is contained
        inside the older block's range. We replicate that by flagging older
        overlapped blocks with `attr = False` (instead of deleting them),
        so gap labels are preserved but the OB rectangles are suppressed.
        """
        if len(blocks) <= 1:
            return

        for newer_idx in range(len(blocks) - 1, 0, -1):
            newer = blocks[newer_idx]
            if not newer.get(attr, True):
                continue
            new_top = newer["ob_top"]
            for older_idx in range(newer_idx - 1, -1, -1):
                older = blocks[older_idx]
                if not older.get(attr, True):
                    continue
                if new_top < older["ob_top"] and new_top > older["ob_bottom"]:
                    older[attr] = False

    @staticmethod
    def _cap_active_obs(blocks: List[Dict], max_active: int) -> None:
        """Keep only the most-recent `max_active` blocks as active OBs;
        older ones retain their gap box but lose their colored zone —
        mirrors Pine's `box.delete(boxes1.shift())` on array overflow.
        """
        active_indices = [i for i, b in enumerate(blocks) if b.get("render_ob")]
        if len(active_indices) <= max_active:
            return
        # Keep the last `max_active` active ones, suppress the rest
        to_suppress = active_indices[:-max_active]
        for i in to_suppress:
            blocks[i]["render_ob"] = False

    # ------------------------------------------------------------------
    def get_data(self) -> Dict:
        """Return the full indicator payload for the JSON builder."""
        if not self._ran:
            raise RuntimeError("Call .run() first.")
        return {
            "bull_blocks": self.bull_blocks,
            "bear_blocks": self.bear_blocks,
            "df_index": self.df.index,
            "params": {
                "filter_pct": self.filter_pct,
                "box_amount": self.box_amount,
                "atr_length": self.atr_length,
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

    fvg = FVGOrderBlocksIndicator(df, filter_pct=0.5, box_amount=6)
    fvg.run()

    print(f"\nBullish FVG blocks : {len(fvg.bull_blocks)}")
    print(f"Bearish FVG blocks : {len(fvg.bear_blocks)}")
    for b in (fvg.bull_blocks + fvg.bear_blocks)[-10:]:
        print(
            f"  [{b['direction']:>7}] bar={b['bar_index']:>4}  "
            f"gap={b['gap_pct']:.2f}%  "
            f"OB=[{b['ob_bottom']:.2f}, {b['ob_top']:.2f}]  "
            f"inv={b.get('invalidated_at')}"
        )
