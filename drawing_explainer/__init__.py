"""Drawing Explainer

Reads the user's TradingView drawing JSON from the LMS
(`/api/v1/learning/result-screenshot-view/` for a chapter,
`/api/v1/learning/single-result/` for one trade), compacts it, and asks
`openai/gpt-oss-120b` (via OpenRouter) to:

  - Verdict each drawing as correct / partial / incorrect with a reason.
  - Suggest one concrete improvement per problematic drawing.
  - Rank each question (0-10) and the whole session (0-10).
  - Produce a focused study plan.

Public entry points:

    from drawing_explainer import (
        explain_from_session,
        explain_from_api,
        explain_from_single_answer,
    )

    explain_from_session(session_json)
    explain_from_api(date="23-04-2026", chapter_id="726", bearer_token="...")
    explain_from_single_answer(answer_id=546, bearer_token="...")
"""

from .explainer import (
    explain_from_api,
    explain_from_session,
    explain_from_single_answer,
)

__all__ = [
    "explain_from_api",
    "explain_from_session",
    "explain_from_single_answer",
]
