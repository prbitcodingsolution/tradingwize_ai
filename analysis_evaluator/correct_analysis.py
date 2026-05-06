"""Step 10 — assemble the system's reference 'correct analysis'."""

from __future__ import annotations

from typing import List, Optional

from .market_structure import Trend
from .models import CorrectAnalysis, EntryZone
from .optimal_zone import OptimalRange, golden_pocket


def build_correct_analysis(trend: Trend, optimal: Optional[OptimalRange]) -> Optional[CorrectAnalysis]:
    if optimal is None:
        return None

    gp_top, gp_bottom = golden_pocket(optimal)

    # In a downtrend, "ideal" entries are short retracements UP into the move,
    # so the entry zone should be on the upper side. The golden_pocket already
    # works on price ordering — we just clamp top/bottom for clarity.
    return CorrectAnalysis(
        trend=trend,
        fib_range=optimal.fib_range,
        fib_prices=optimal.fib_prices,
        key_levels=[0.5, 0.618],
        entry_zone=EntryZone(top=gp_top, bottom=gp_bottom),
    )
