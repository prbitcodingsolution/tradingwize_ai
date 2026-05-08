"""Render the per-question card produced by `explain_question` into the
7-section markdown layout the frontend expects.

Card schema (top-level keys on the question dict):

    overall_score, strengths, mistake, market_did, better_approach,
    psychology_note, key_lesson, next_focus

Plus the always-present chart context: question_no, pair, timeframe.

Two entry points:

    format_question(q)         — markdown for ONE card
    format_session(result)     — header + every card stacked

The verbose multi-section format (session_summary, pattern_analysis,
mistakes[], drawing_accuracy, etc.) was removed — see
`ai_explanation_format_task.md` for the deprecation list.
"""

from __future__ import annotations

from typing import Any, Dict, List

# Use the shared schema so the section list lives in ONE place; if a future
# change adds/renames a card field we update only `llm_explainer._SECTION_KEYS`
# and both the prompt's empty-card defaults and this renderer follow.
from .llm_explainer import _SECTION_KEYS


def _fmt_score(raw: Any) -> str:
    """Score formatter — always one decimal so the UI gets `7.0/10` not `7/10`."""
    if raw is None or raw == "":
        return "?"
    try:
        return f"{float(raw):.1f}"
    except (TypeError, ValueError):
        return str(raw)


def _section_text(value: Any) -> str:
    """Coerce a card field to a clean single-line string. The schema asks the
    LLM for plain text but a stray bullet / list can sneak in — flatten
    whatever we got into a single paragraph so the card layout stays clean."""
    if value is None:
        return "—"
    if isinstance(value, list):
        bits = [str(v).strip() for v in value if isinstance(v, (str, int, float)) and str(v).strip()]
        return " ".join(bits) or "—"
    s = str(value).strip()
    return s or "—"


# ───────────────────────── per-question card ─────────────────────

def format_question(q: Dict[str, Any]) -> str:
    """Render one trade as the 7-section card."""
    if not isinstance(q, dict):
        return ""

    if q.get("_error"):
        return (
            f"## ⚠️ Question {q.get('question_no', '?')} — analysis failed\n\n"
            f"> {q.get('_error_summary') or q.get('_error')}\n"
        )
    if q.get("_parse_error"):
        return (
            f"## ⚠️ Question {q.get('question_no', '?')} — output unparseable\n\n"
            f"> The model's response could not be parsed as JSON. "
            f"Try increasing `DRAWING_EXPLAINER_MAX_TOKENS_Q`.\n"
        )

    parts: List[str] = []

    pair = q.get("pair") or ""
    tf = q.get("timeframe") or ""
    qno = q.get("question_no", "?")
    parts.append(f"## 📈 Question {qno}: {pair} · {tf}".rstrip(" ·"))

    parts.append(f"\n**Overall Score:** {_fmt_score(q.get('overall_score'))}/10")

    for key, label in _SECTION_KEYS:
        parts.append(f"\n**{label}** {_section_text(q.get(key))}")

    if q.get("_truncated"):
        parts.append(
            "\n*⚠️ Note: this response was truncated — some fields may be incomplete.*"
        )

    return "\n".join(parts).strip()


# ───────────────────────── session-level ─────────────────────────

def format_session(result: Dict[str, Any]) -> str:
    """Render the whole session — metadata header + every question card.

    The verbose session-level coaching summary (strengths/weaknesses/
    recurring-mistakes/study-plan/closing-note) was deprecated in favour of
    the per-question card; we no longer emit any of those blocks here.
    """
    if not isinstance(result, dict):
        return ""

    parts: List[str] = ["# 📊 Trading Session Analysis"]

    sess = result.get("session") or {}
    meta_bits: List[str] = []
    if sess.get("submit_date"):
        meta_bits.append(f"**Date**: {sess['submit_date']}")
    if sess.get("win") is not None and sess.get("loss") is not None:
        meta_bits.append(f"**W/L**: {sess['win']} / {sess['loss']}")
    if sess.get("win_loss_ratio"):
        meta_bits.append(f"**Win-rate**: {sess['win_loss_ratio']}")
    if sess.get("total_points") is not None:
        meta_bits.append(f"**Points**: {sess['total_points']}")
    if sess.get("total_questions") is not None:
        meta_bits.append(f"**Questions**: {sess['total_questions']}")
    if meta_bits:
        parts.append(" · ".join(meta_bits))

    questions = result.get("questions") or []
    if isinstance(questions, list) and questions:
        parts.append("\n---\n")
        for q in questions:
            md = format_question(q)
            if md:
                parts.append(md)
                parts.append("")  # blank line between cards

    return "\n".join(parts).rstrip() + "\n"
