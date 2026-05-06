"""Step 8 — weighted scoring (Trend 20 / Swings 20 / Fib 25 / Channel 15 / Entry 20)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .models import EvalLabel
from .validators import CheckResult


WEIGHTS = {
    "trend": 0.20,
    "swings": 0.20,
    "fibonacci": 0.25,
    "channel": 0.15,
    "entry": 0.20,
}


@dataclass
class ComponentScore:
    name: str
    score: float
    label: EvalLabel
    weight: float


def trend_score(user_dir: str | None, system_trend: str) -> CheckResult:
    """How well the user's trade direction agrees with the detected trend."""
    if not user_dir:
        return CheckResult(0.5, "missing", ["No trade direction provided to compare against trend"])
    if system_trend == "sideways":
        return CheckResult(0.6, "partially correct", ["Market is ranging — directional bias is risky"])
    expected = "buy" if system_trend == "bullish" else "sell"
    if user_dir == expected:
        return CheckResult(1.0, "correct", [])
    return CheckResult(0.0, "incorrect", [f"Trade direction is opposite to detected {system_trend} trend"])


def swing_score(num_swings: int) -> CheckResult:
    """Health of the underlying market — enough swings to analyze at all?"""
    if num_swings >= 6:
        return CheckResult(1.0, "correct", [])
    if num_swings >= 3:
        return CheckResult(0.7, "partially correct", [])
    return CheckResult(0.3, "weak", ["Too few swings detected — chart may be too noisy or too short"])


def aggregate(
    trend: CheckResult,
    swings: CheckResult,
    fib: CheckResult,
    channel: CheckResult,
    entry: CheckResult,
) -> tuple[float, List[ComponentScore]]:
    components = [
        ComponentScore("trend", trend.score, trend.label, WEIGHTS["trend"]),
        ComponentScore("swings", swings.score, swings.label, WEIGHTS["swings"]),
        ComponentScore("fibonacci", fib.score, fib.label, WEIGHTS["fibonacci"]),
        ComponentScore("channel", channel.score, channel.label, WEIGHTS["channel"]),
        ComponentScore("entry", entry.score, entry.label, WEIGHTS["entry"]),
    ]
    final = sum(c.score * c.weight for c in components) * 100
    return round(final, 1), components
