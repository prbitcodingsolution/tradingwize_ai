"""
Supply and Demand Zones — BigBeluga Pine port
=============================================
Python port of the Pine Script `Supply and Demand Zones [BigBeluga]`
indicator (see supply_demand.md in this folder for the original Pine v6
source).

The indicator identifies institutional supply / demand pockets:

  * Supply Zone — fired when 3 consecutive bear candles print after a
    high-volume bar. We walk back up to 5 bars to find the last bullish
    candle (the "base" — last accumulation before distribution) and draw
    an ATR-tall box from `low[i]` upward by ATR.
  * Demand Zone — mirrored: 3 consecutive bull candles after a high-volume
    bar; the last bearish candle inside the look-back becomes the base
    and the box is drawn ATR-tall, dropping down from `high[i]`.

For each zone we accumulate the impulse-leg volume into a `delta` value:
positive volume on bars that match the zone direction, negative on
opposite candles. The label at render time shows `delta | share %` —
share is computed against the running total of bull+bear delta so the
visualisation matches the Pine `dash` panel.

Invalidation rules mirror the Pine script:
  * Supply box is broken when a later bar's `close > box.top` — dropped.
  * Demand box is broken when a later bar's `close < box.bottom` — dropped.
  * Mitigation: any bar whose wick crosses the opposite side of the box
    (high > bottom AND low < bottom for supply / low < top AND high > top
    for demand) flags the box as "mitigated" — drawn with a dashed border.
  * Overlap suppression: if a newer box's top sits inside an older box's
    range (older.bottom < newer.top < older.top), the older box is dropped.
  * Cap: keep at most `max_boxes` per side (Pine default = 5); older
    boxes fall off as new ones arrive.

Module usage
------------
    from supply_demand_zones_indicator import SupplyDemandZonesIndicator

    sdz = SupplyDemandZonesIndicator(df, atr_length=200, vol_window=1000,
                                     cooldown=15, max_boxes=5)
    sdz.run()

    data = sdz.get_data()    # dict consumed by the JSON builder
"""

from typing import Dict, List, Optional

import numpy as np
import pandas as pd


class SupplyDemandZonesIndicator:
    """Faithful Python port of `Supply and Demand Zones [BigBeluga]`.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe. Must contain Open / High / Low / Close / Volume
        columns (any capitalisation). A DatetimeIndex is expected when the
        result is fed into the JSON builders.
    atr_length : int
        ATR lookback for box height (Pine: `ta.atr(200) * 2` — we keep the
        same default but allow override on shorter histories).
    atr_mult : float
        Multiplier on ATR to size the box (Pine default = 2.0).
    vol_window : int
        Rolling window for the volume average that gates new detections
        (Pine default = 1000).
    look_back : int
        How many bars back from a 3-bar impulse to scan for the base
        candle of opposite colour (Pine default = 5 → range 0..5 inclusive).
    cooldown : int
        Bars to skip after a detection before another zone of the same
        side may fire (Pine default = 15).
    max_boxes : int
        Keep at most N most-recent active zones per side (Pine default = 5).
    """

    def __init__(
        self,
        df: pd.DataFrame,
        atr_length: int = 200,
        atr_mult: float = 2.0,
        vol_window: int = 1000,
        look_back: int = 5,
        cooldown: int = 15,
        max_boxes: int = 5,
    ):
        self.df = df.copy()
        self._normalize_columns()

        self.atr_length = int(atr_length)
        self.atr_mult = float(atr_mult)
        self.vol_window = int(vol_window)
        self.look_back = int(look_back)
        self.cooldown = int(cooldown)
        self.max_boxes = int(max_boxes)

        self.supply_zones: List[Dict] = []
        self.demand_zones: List[Dict] = []

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
            # Fall back to a constant series so the indicator still runs;
            # delta values will be meaningless but zone geometry is intact.
            self.df["Volume"] = 1.0

    # ------------------------------------------------------------------
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
        atr = np.full(n, np.nan)
        if n < length:
            return atr
        seed = float(np.nanmean(tr[:length]))
        atr[length - 1] = seed
        alpha = 1.0 / length
        for i in range(length, n):
            atr[i] = (1 - alpha) * atr[i - 1] + alpha * tr[i]
        return atr

    # ------------------------------------------------------------------
    def run(self) -> None:
        """Populate supply_zones / demand_zones with every detected zone."""
        n = len(self.df)
        # We need enough bars for ATR + at least one impulse window.
        if n < max(self.atr_length, self.look_back + 4):
            self._ran = True
            return

        open_ = self.df["Open"].astype(float).values
        high = self.df["High"].astype(float).values
        low = self.df["Low"].astype(float).values
        close = self.df["Close"].astype(float).values
        volume = self.df["Volume"].astype(float).values

        atr = self._atr(high, low, close, self.atr_length) * self.atr_mult

        # Rolling mean of volume over `vol_window` bars (Pine: `vol.avg()`
        # with a max-size 1000 array).
        vol_avg = pd.Series(volume).rolling(self.vol_window, min_periods=1).mean().values

        bear = close < open_
        bull = close > open_

        count_bear = 0
        count_bull = 0

        # Pine evaluates from bar 5 forward (needs 3-back history + look_back).
        scan_start = max(self.atr_length, self.look_back + 3)

        for i in range(scan_start, n):
            a = atr[i]
            if np.isnan(a):
                if count_bear >= 1:
                    count_bear += 1
                if count_bull >= 1:
                    count_bull += 1
                if count_bear >= self.cooldown:
                    count_bear = 0
                if count_bull >= self.cooldown:
                    count_bull = 0
                continue

            # Pine: `extra_vol = volume > vol.avg()` evaluated each bar; the
            # detection rule references `extra_vol[1]` (volume of the bar
            # before the impulse trigger).
            extra_vol_prev = volume[i - 1] > vol_avg[i - 1]

            # ── Supply detection ───────────────────────────────────────
            # Pine: 3 consecutive bear candles + extra_vol on bar -1 + cooldown 0
            if (
                bear[i] and bear[i - 1] and bear[i - 2]
                and extra_vol_prev
                and count_bear == 0
            ):
                delta = 0.0
                base_offset: Optional[int] = None
                # Walk back 0..look_back (inclusive) — first bull candle = base
                for off in range(0, self.look_back + 1):
                    j = i - off
                    if j < 0:
                        break
                    if bull[j]:
                        base_offset = off
                        break
                    # Accumulate impulse delta — bear contributes negative,
                    # bull contributes positive (Pine ternary).
                    delta += -volume[j] if bear[j] else volume[j]

                if base_offset is not None:
                    base_idx = i - base_offset
                    box_top = float(low[base_idx] + a)
                    box_bottom = float(low[base_idx])
                    self.supply_zones.append(
                        {
                            "direction": "supply",
                            "bar_index": i,             # confirmation bar
                            "base_idx": base_idx,       # left edge of the box
                            "top": box_top,
                            "bottom": box_bottom,
                            "delta": float(delta),
                            "atr": float(a),
                            "invalidated_at": None,
                            "mitigated_at": None,
                        }
                    )
                    count_bear = 1

            # ── Demand detection ──────────────────────────────────────
            if (
                bull[i] and bull[i - 1] and bull[i - 2]
                and extra_vol_prev
                and count_bull == 0
            ):
                delta = 0.0
                base_offset = None
                for off in range(0, self.look_back + 1):
                    j = i - off
                    if j < 0:
                        break
                    if bear[j]:
                        base_offset = off
                        break
                    delta += volume[j] if bull[j] else -volume[j]

                if base_offset is not None:
                    base_idx = i - base_offset
                    box_top = float(high[base_idx])
                    box_bottom = float(high[base_idx] - a)
                    self.demand_zones.append(
                        {
                            "direction": "demand",
                            "bar_index": i,
                            "base_idx": base_idx,
                            "top": box_top,
                            "bottom": box_bottom,
                            "delta": float(delta),
                            "atr": float(a),
                            "invalidated_at": None,
                            "mitigated_at": None,
                        }
                    )
                    count_bull = 1

            # ── Cooldown advance / reset (Pine: count += 1 each bar) ──
            if count_bear >= 1:
                count_bear += 1
            if count_bull >= 1:
                count_bull += 1
            if count_bear >= self.cooldown:
                count_bear = 0
            if count_bull >= self.cooldown:
                count_bull = 0

        # Post-processing — mirror Pine's per-bar maintenance loops.
        self._mark_invalidations(close, high, low, n)
        self._drop_overlaps_in_place(self.supply_zones, side="supply")
        self._drop_overlaps_in_place(self.demand_zones, side="demand")
        self._compute_share_pct()
        self._cap_active_zones(self.supply_zones, self.max_boxes)
        self._cap_active_zones(self.demand_zones, self.max_boxes)

        self._ran = True

    # ------------------------------------------------------------------
    def _mark_invalidations(
        self,
        close: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        n: int,
    ) -> None:
        """Tag the first bar where each box is broken (closed beyond) or
        merely mitigated (wick crossed). Pine deletes broken boxes; we
        retain the geometry but flag them so the JSON builder can fade
        or drop them as needed."""
        for z in self.supply_zones:
            top = z["top"]
            bottom = z["bottom"]
            for i in range(z["bar_index"] + 1, n):
                if z["mitigated_at"] is None and high[i] > bottom and low[i] < bottom:
                    z["mitigated_at"] = i
                if close[i] > top:
                    z["invalidated_at"] = i
                    break

        for z in self.demand_zones:
            top = z["top"]
            bottom = z["bottom"]
            for i in range(z["bar_index"] + 1, n):
                if z["mitigated_at"] is None and low[i] < top and high[i] > top:
                    z["mitigated_at"] = i
                if close[i] < bottom:
                    z["invalidated_at"] = i
                    break

    # ------------------------------------------------------------------
    @staticmethod
    def _drop_overlaps_in_place(zones: List[Dict], side: str) -> None:
        """Pine: when an older box has another box's top sitting inside its
        range (older.bottom < other.top < older.top), the older box is
        deleted. We mark it `render = False` rather than dropping the entry,
        so the post-cap accounting still works."""
        if len(zones) <= 1:
            return
        for older_idx in range(len(zones)):
            older = zones[older_idx]
            if older.get("render") is False:
                continue
            for newer_idx in range(len(zones)):
                if newer_idx == older_idx:
                    continue
                newer = zones[newer_idx]
                if newer.get("render") is False:
                    continue
                top1 = newer["top"]
                if older["bottom"] < top1 < older["top"]:
                    older["render"] = False
                    break
        for z in zones:
            z.setdefault("render", True)

    # ------------------------------------------------------------------
    def _compute_share_pct(self) -> None:
        """Each zone label shows |delta| / total * 100% — total is the sum
        of |delta| across both sides (Pine: `BullDelta.sum() + BearDelta.sum()`
        in absolute terms)."""
        total = (
            sum(abs(z["delta"]) for z in self.supply_zones)
            + sum(abs(z["delta"]) for z in self.demand_zones)
        )
        for z in self.supply_zones + self.demand_zones:
            if total > 0:
                z["share_pct"] = abs(z["delta"]) / total * 100.0
            else:
                z["share_pct"] = 0.0

    # ------------------------------------------------------------------
    @staticmethod
    def _cap_active_zones(zones: List[Dict], max_active: int) -> None:
        """Pine drops the oldest active box when the array exceeds
        `box_amount` (default 5). We flag overflow boxes with
        `render = False` instead of removing them, so the dataset stays
        stable for downstream consumers."""
        active = [z for z in zones if z.get("render", True) and z.get("invalidated_at") is None]
        if len(active) <= max_active:
            return
        # Keep the last `max_active` active ones; suppress older.
        to_suppress = active[:-max_active]
        for z in to_suppress:
            z["render"] = False

    # ------------------------------------------------------------------
    def get_data(self) -> Dict:
        """Return the full indicator payload for the JSON builder."""
        if not self._ran:
            raise RuntimeError("Call .run() first.")
        # Aggregate totals for the dashboard / metadata
        total_supply_delta = sum(z["delta"] for z in self.supply_zones)
        total_demand_delta = sum(z["delta"] for z in self.demand_zones)
        return {
            "supply_zones": self.supply_zones,
            "demand_zones": self.demand_zones,
            "df_index": self.df.index,
            "totals": {
                "supply_delta": float(total_supply_delta),
                "demand_delta": float(total_demand_delta),
            },
            "params": {
                "atr_length": self.atr_length,
                "atr_mult": self.atr_mult,
                "vol_window": self.vol_window,
                "look_back": self.look_back,
                "cooldown": self.cooldown,
                "max_boxes": self.max_boxes,
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

    print("Downloading RELIANCE.NS data …")
    df = yf.download("RELIANCE.NS", period="2y", interval="1d", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    sdz = SupplyDemandZonesIndicator(
        df, atr_length=200, atr_mult=2.0, vol_window=1000,
        look_back=5, cooldown=15, max_boxes=5,
    )
    sdz.run()

    print(f"\nSupply zones detected : {len(sdz.supply_zones)}")
    print(f"Demand zones detected : {len(sdz.demand_zones)}")
    for z in (sdz.supply_zones + sdz.demand_zones)[-10:]:
        print(
            f"  [{z['direction']:>6}] bar={z['bar_index']:>4} base={z['base_idx']:>4}  "
            f"box=[{z['bottom']:.2f}, {z['top']:.2f}]  "
            f"delta={z['delta']:>14.0f}  share={z.get('share_pct', 0):.1f}%  "
            f"inv={z.get('invalidated_at')}  mit={z.get('mitigated_at')}"
        )
