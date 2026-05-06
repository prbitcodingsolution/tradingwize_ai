"""Step 11 — turn the rule-based findings into a mentor-style explanation.

Hard caps:
  - request timeout: LLM_TIMEOUT_SEC (default 20s) — falls back to deterministic text
    rather than hanging the whole `/analyze` request on a slow OpenRouter response.
  - max_tokens: 300 — keeps generations short and predictable.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .models import CorrectAnalysis, Evaluation

logger = logging.getLogger(__name__)


LLM_TIMEOUT_SEC = float(os.getenv("LLM_TIMEOUT_SEC", "20"))


_SYSTEM_PROMPT = (
    "You are a senior trading mentor reviewing a student's chart analysis. "
    "Be concise, concrete, and constructive. "
    "Three short paragraphs: (1) what the student got wrong and why, "
    "(2) what the correct read of this chart was — focus your analysis on "
    "the time window the student was looking at (`focus_window` in the "
    "input), NOT on the latest candles, (3) one specific habit the student "
    "should practise next time. No fluff, no disclaimers."
)


def explain(
    *,
    score: float,
    evaluation: Evaluation,
    mistakes: List[str],
    correct: Optional[CorrectAnalysis],
    user_summary: Dict[str, Any],
    focus_window: Optional[Tuple[int, int]] = None,
) -> str:
    """Call the OpenRouter-backed LLM via the project's `guarded_llm_call`.
    On timeout or any error, fall back to a deterministic summary so the
    `/analyze` request never blocks on the LLM."""
    try:
        from utils.model_config import guarded_llm_call
    except Exception as e:
        logger.warning("LLM not available, using fallback explanation: %s", e)
        return _fallback(score, mistakes, correct)

    payload = {
        "score": score,
        "evaluation": evaluation.model_dump(),
        "mistakes": mistakes,
        "correct_analysis": correct.model_dump() if correct else None,
        "user_summary": user_summary,
        "focus_window": _focus_window_for_prompt(focus_window),
    }

    try:
        resp = guarded_llm_call(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, default=str)},
            ],
            temperature=0.3,
            max_tokens=300,
            timeout=LLM_TIMEOUT_SEC,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning("LLM call failed/timed out (>%ss), using fallback: %s", LLM_TIMEOUT_SEC, e)
        return _fallback(score, mistakes, correct)


def _focus_window_for_prompt(focus_window: Optional[Tuple[int, int]]) -> Optional[Dict[str, str]]:
    """Render the focus window as ISO datetimes so the LLM can name the time
    period when explaining the correct read (e.g. "in early August 2025…")."""
    if not focus_window:
        return None
    start_t, end_t = focus_window
    return {
        "start": datetime.fromtimestamp(start_t, tz=timezone.utc).isoformat(),
        "end": datetime.fromtimestamp(end_t, tz=timezone.utc).isoformat(),
    }


def _fallback(score: float, mistakes: List[str], correct: Optional[CorrectAnalysis]) -> str:
    parts = [f"Overall score: {score:.1f}%."]
    if mistakes:
        parts.append("Key issues: " + "; ".join(mistakes) + ".")
    if correct:
        parts.append(
            f"Reference read: {correct.trend} bias; ideal Fib range "
            f"{correct.fib_prices[0]:.2f} → {correct.fib_prices[1]:.2f}; "
            f"entry zone {correct.entry_zone.bottom:.2f} – {correct.entry_zone.top:.2f}."
        )
    return " ".join(parts)
