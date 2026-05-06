"""Trend classification from swing sequence — HH/HL → bullish, LH/LL → bearish (Step 3)."""

from __future__ import annotations

from typing import List, Literal

from .swing_detector import Swing


Trend = Literal["bullish", "bearish", "sideways"]


def classify_trend(swings: List[Swing], lookback: int = 6) -> Trend:
    """Look at the last `lookback` swings and count HH/HL vs LH/LL signals."""
    if len(swings) < 4:
        return "sideways"

    recent = swings[-lookback:]
    highs = [s for s in recent if s.kind == "HIGH"]
    lows = [s for s in recent if s.kind == "LOW"]
    if len(highs) < 2 or len(lows) < 2:
        return "sideways"

    bull = 0
    bear = 0
    for a, b in zip(highs, highs[1:]):
        if b.price > a.price:
            bull += 1
        elif b.price < a.price:
            bear += 1
    for a, b in zip(lows, lows[1:]):
        if b.price > a.price:
            bull += 1
        elif b.price < a.price:
            bear += 1

    if bull >= bear + 2:
        return "bullish"
    if bear >= bull + 2:
        return "bearish"
    return "sideways"
