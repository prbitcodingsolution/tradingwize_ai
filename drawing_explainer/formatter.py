"""Render the per-question card produced by `explain_question` into the
mentor-style markdown layout the frontend expects.

Card schema (top-level keys on the question dict):

    overall_score, market_analysis, mentor_note,
    student_review: { did_well, mistake, improve }

Plus the always-present chart context: question_no, pair, timeframe.

Two entry points:

    format_question(q)         — markdown for ONE card
    format_session(result)     — header + every card stacked
"""

from __future__ import annotations

from typing import Any, Dict, List

# Use the shared schema so the section list lives in ONE place; if a future
# change adds/renames a card field we update only `llm_explainer._SECTION_KEYS`
# / `_STUDENT_REVIEW_KEYS` and both the prompt's empty-card defaults and this
# renderer follow.
from .llm_explainer import _SECTION_KEYS, _STUDENT_REVIEW_KEYS


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
    """Render one trade as the mentor-style card."""
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

    market_analysis = next((label for key, label in _SECTION_KEYS if key == "market_analysis"), "Market Analysis")
    mentor_note_label = next((label for key, label in _SECTION_KEYS if key == "mentor_note"), "Mentor Note")

    parts.append(f"\n**{market_analysis}**\n{_section_text(q.get('market_analysis'))}")

    sr = q.get("student_review") if isinstance(q.get("student_review"), dict) else {}
    parts.append("\n**Student Review 👨‍🎓**")
    for key, label in _STUDENT_REVIEW_KEYS:
        parts.append(f"- **{label}:** {_section_text(sr.get(key))}")

    parts.append(f"\n**{mentor_note_label}**\n{_section_text(q.get('mentor_note'))}")

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
