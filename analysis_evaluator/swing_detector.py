"""Window-based swing-high / swing-low detection (Step 2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal

from .models import Candle


@dataclass
class Swing:
    kind: Literal["HIGH", "LOW"]
    index: int
    price: float
    time: int


def detect_swings(candles: List[Candle], window: int = 5) -> List[Swing]:
    """A point is a swing high (resp. low) iff it is the strict max (resp. min) over
    the `window` candles before AND after it (inclusive of itself)."""
    n = len(candles)
    if n < 2 * window + 1:
        return []

    swings: List[Swing] = []
    for i in range(window, n - window):
        c = candles[i]
        is_high = all(candles[j].high <= c.high for j in range(i - window, i + window + 1) if j != i) and \
                  any(candles[j].high < c.high for j in range(i - window, i + window + 1) if j != i)
        is_low = all(candles[j].low >= c.low for j in range(i - window, i + window + 1) if j != i) and \
                 any(candles[j].low > c.low for j in range(i - window, i + window + 1) if j != i)

        if is_high:
            swings.append(Swing("HIGH", i, c.high, c.time))
        if is_low:
            swings.append(Swing("LOW", i, c.low, c.time))

    swings.sort(key=lambda s: s.index)
    return _alternate(swings)


def _alternate(swings: List[Swing]) -> List[Swing]:
    """Collapse runs of same-kind swings into the most extreme one — clean alternation."""
    out: List[Swing] = []
    for s in swings:
        if not out:
            out.append(s)
            continue
        prev = out[-1]
        if prev.kind == s.kind:
            # Same kind in a row → keep the more extreme one
            if (s.kind == "HIGH" and s.price > prev.price) or (s.kind == "LOW" and s.price < prev.price):
                out[-1] = s
        else:
            out.append(s)
    return out
