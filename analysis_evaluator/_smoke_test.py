"""Smoke test against the sample LMS payload in `drawing_instruction/find.py`.

We don't have the live candle API in this environment, so we synthesize ~120
1-hour candles around the trade window (entry @ 2948 → SL 2916 → TP 2972).
Run: `python -m analysis_evaluator._smoke_test`
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

# Make the repo root importable so `utils.model_config` resolves.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis_evaluator.drawing_parser import parse_drawings
from analysis_evaluator.evaluator import evaluate
from analysis_evaluator.models import Candle


def _load_sample() -> dict:
    """Wrap the JSON object in `find.py` so we can reuse it as a payload."""
    text = Path("drawing_instruction/find.py").read_text(encoding="utf-8")
    return json.loads(text)


def _synthetic_candles(start_t: int = 1738_368_000, n: int = 200, base: float = 2700.0) -> list[Candle]:
    """Sine-wave-ish candles so the swing detector has real swings to find."""
    out: list[Candle] = []
    for i in range(n):
        # Two overlapping sine waves → realistic-looking swings
        trend = base + i * 1.2  # steady uptrend so we get HH/HL → bullish
        wave = 60 * math.sin(i / 7.0) + 20 * math.cos(i / 3.0)
        mid = trend + wave
        op = mid - 2
        cl = mid + 2 * math.sin(i / 5.0)
        hi = max(op, cl) + abs(math.sin(i / 4.0)) * 8
        lo = min(op, cl) - abs(math.cos(i / 4.0)) * 8
        out.append(Candle(time=start_t + i * 3600, open=op, high=hi, low=lo, close=cl, volume=1_000.0))
    return out


def main() -> None:
    sample = _load_sample()
    candles = _synthetic_candles()
    analysis = parse_drawings(sample, candles)

    # Disable LLM call for this offline smoke test — fallback explanation is enough
    os.environ.setdefault("OPENROUTER_API_KEY", "")
    response = evaluate(candles, analysis)

    print(json.dumps(response.model_dump(), indent=2, default=str))
    print("\n--- summary ---")
    print(f"score: {response.score}")
    print(f"trend (detected): {response.debug.get('detected_trend')}")
    print(f"swing_count: {response.debug.get('swing_count')}")
    print(f"optimal_range: {response.debug.get('optimal_range')}")


if __name__ == "__main__":
    main()
