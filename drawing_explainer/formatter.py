"""Render the structured analysis into a markdown string the frontend can drop
straight into a markdown renderer (e.g. react-markdown).

We expose two entry points:

    format_question(q)         — markdown for ONE question card
    format_session(result)     — markdown for the WHOLE session report
                                  (session summary + every question)

Both are defensive: any missing field is silently skipped rather than raising,
so a partial / parse-recovered LLM response still renders something useful.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# ───────────────────────── small helpers ─────────────────────────

def _g(d: Optional[Dict[str, Any]], *path: str, default: Any = None) -> Any:
    """Safe nested-dict access: `_g(d, 'a', 'b')` → `d['a']['b']` or default."""
    cur: Any = d or {}
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def _bullets(items: Any) -> List[str]:
    """Turn an arbitrary list into stripped, non-empty markdown bullet lines."""
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        if isinstance(it, str) and it.strip():
            out.append(f"- {it.strip()}")
    return out


def _fmt_price(v: Any) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):g}"
    except (TypeError, ValueError):
        return str(v)


# ───────────────────────── per-question ──────────────────────────

def format_question(q: Dict[str, Any]) -> str:
    """Render one question's analysis as markdown."""
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

    pair = q.get("pair", "")
    tf = q.get("timeframe", "")
    qno = q.get("question_no", "?")
    parts.append(f"## 📈 Question {qno}: {pair} · {tf}")

    # Higher-timeframe bias + liquidity-sweep status — anchors every other
    # piece of feedback. Render only when the LLM populated them.
    context_bits: List[str] = []
    htf = q.get("htf_bias")
    if isinstance(htf, str) and htf.strip():
        context_bits.append(f"**HTF bias**: {htf.strip()}")
    sweep = q.get("liquidity_swept_before_entry")
    if isinstance(sweep, dict) and sweep.get("status"):
        context_bits.append(f"**Liquidity swept before entry**: {sweep['status']}")
    elif isinstance(sweep, str) and sweep.strip():
        context_bits.append(f"**Liquidity swept before entry**: {sweep.strip()}")
    if context_bits:
        parts.append(" · ".join(context_bits))
    if isinstance(sweep, dict) and sweep.get("note"):
        parts.append(f"> {sweep['note']}")

    score = q.get("score") or {}
    if score:
        parts.append(
            f"**Score** — Overall **{score.get('overall', '?')}/10**  ·  "
            f"Pattern {score.get('pattern_recognition', '?')}/10  ·  "
            f"Execution {score.get('execution', '?')}/10  ·  "
            f"Risk Mgmt {score.get('risk_management', '?')}/10  ·  "
            f"Drawing Accuracy {score.get('drawing_accuracy', '?')}/10"
        )

    # Confluence breakdown — five-axis quality of the setup, framework-agnostic.
    cs = q.get("confluence_score") or {}
    if isinstance(cs, dict) and cs:
        parts.append(
            f"\n**🧩 Confluence** — Structure {cs.get('structure', '?')}/10  ·  "
            f"Liquidity {cs.get('liquidity', '?')}/10  ·  "
            f"Risk {cs.get('risk', '?')}/10  ·  "
            f"Entry Timing {cs.get('entry_timing', '?')}/10  ·  "
            f"Confirmation {cs.get('confirmation', '?')}/10"
        )

    # Drawing accuracy: ground-truth check against the actual candles.
    da = q.get("drawing_accuracy") or {}
    if da:
        anchored = da.get("well_anchored")
        total = da.get("total_drawings")
        breakdown = ""
        if anchored is not None and total is not None:
            breakdown = f" · {anchored}/{total} drawings well-anchored"
        parts.append(
            f"\n**🎯 Drawing accuracy**: {da.get('score', '?')}/10{breakdown}"
        )
        if da.get("explanation"):
            parts.append(f"> {da['explanation']}")

    # ── pattern analysis ──
    pa = q.get("pattern_analysis") or {}
    if pa:
        parts.append("\n### 🎯 Pattern Analysis")
        parts.append(
            f"- **Identified pattern**: {pa.get('identified_pattern', '—')}  "
            f"(confidence: *{pa.get('pattern_confidence', '—')}*)"
        )
        parts.append(f"- **Trend direction**: {pa.get('trend_direction', '—')}")
        tools = pa.get("drawing_tools_used") or []
        if tools:
            parts.append(f"- **Drawing tools used**: {', '.join(str(t) for t in tools)}")

        markers = pa.get("entry_exit_markers") or {}
        if any(markers.get(k) is not None for k in ("entry", "stop_loss", "take_profit")):
            parts.append(
                f"- **Levels** — Entry: `{_fmt_price(markers.get('entry'))}`  ·  "
                f"SL: `{_fmt_price(markers.get('stop_loss'))}`  ·  "
                f"TP: `{_fmt_price(markers.get('take_profit'))}`"
            )

        levels = pa.get("key_levels") or []
        if isinstance(levels, list) and levels:
            parts.append("- **Key levels**:")
            for lv in levels:
                if isinstance(lv, dict):
                    role = lv.get("role", "level")
                    price = _fmt_price(lv.get("price"))
                    label = lv.get("label", "")
                    parts.append(f"  - *{role}* · `{price}` — {label}")

        if pa.get("summary"):
            parts.append(f"\n> {pa['summary']}")

    # ── potential higher-probability setup ──
    bs = q.get("best_setup") or {}
    if bs:
        title = bs.get("title") or "One possible execution model"
        parts.append(f"\n### ✨ Potential Higher-Probability Setup — {title}")
        if bs.get("description"):
            parts.append(f"**One possible execution model:** {bs['description']}")
        if bs.get("rationale"):
            parts.append(f"\n**Why it can fit the current structure:** {bs['rationale']}")

    # ── mistakes ──
    mistakes = q.get("mistakes") or []
    if isinstance(mistakes, list) and mistakes:
        parts.append("\n### ❌ Mistakes")
        for i, m in enumerate(mistakes, 1):
            if not isinstance(m, dict):
                continue
            mtype = m.get("type", "mistake").replace("_", " ").title()
            parts.append(f"\n**{i}. {mtype}**")
            if m.get("what"):
                parts.append(f"- *What:* {m['what']}")
            if m.get("why_wrong"):
                parts.append(f"- *Why it's wrong:* {m['why_wrong']}")
            if m.get("correct_approach"):
                parts.append(f"- *Correct approach:* {m['correct_approach']}")

    # ── personalized coaching ──
    ps = q.get("personalized_strategy") or {}
    if ps:
        parts.append("\n### 🎓 Personalized Coaching")
        if ps.get("feedback"):
            parts.append(f"**Feedback:** {ps['feedback']}")
        if ps.get("correct_approach"):
            parts.append(f"\n**Correct approach next time:** {ps['correct_approach']}")
        if ps.get("concept_lesson"):
            parts.append(f"\n**Concept lesson:** {ps['concept_lesson']}")

        steps = ps.get("actionable_steps") or []
        if isinstance(steps, list) and steps:
            parts.append("\n**Action steps:**")
            for i, s in enumerate(steps, 1):
                if isinstance(s, str) and s.strip():
                    # Strip a "1." or "1)" prefix if the model already numbered.
                    text = s.strip().lstrip("0123456789.)-: \t")
                    parts.append(f"{i}. {text}")

        if ps.get("encouragement"):
            parts.append(f"\n> 💪 {ps['encouragement']}")

    if q.get("_truncated"):
        parts.append(
            "\n*⚠️ Note: this response was truncated — some fields may be incomplete.*"
        )

    return "\n".join(parts).strip()


# ───────────────────────── session-level ─────────────────────────

def format_session(result: Dict[str, Any]) -> str:
    """Render the whole report (session summary + every question) as markdown."""
    if not isinstance(result, dict):
        return ""

    parts: List[str] = ["# 📊 Trading Session Analysis"]

    sess = result.get("session") or {}
    if sess:
        meta_bits = []
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

    summary = result.get("session_summary") or {}
    if summary.get("_error"):
        parts.append(f"\n> ⚠️ Session summary failed: {summary['_error']}")
    elif summary:
        score = summary.get("session_score") or {}
        if score:
            parts.append(
                f"\n**Session score** — Overall **{score.get('overall', '?')}/10**  ·  "
                f"Pattern {score.get('pattern_recognition', '?')}/10  ·  "
                f"Execution {score.get('execution', '?')}/10  ·  "
                f"Risk Mgmt {score.get('risk_management', '?')}/10  ·  "
                f"Drawing Accuracy {score.get('drawing_accuracy', '?')}/10"
            )

        if summary.get("headline"):
            parts.append(f"\n> {summary['headline']}")

        strengths = _bullets(summary.get("strengths"))
        if strengths:
            parts.append("\n### ✅ Strengths")
            parts.extend(strengths)

        weaknesses = _bullets(summary.get("weaknesses"))
        if weaknesses:
            parts.append("\n### ⚠️ Weaknesses")
            parts.extend(weaknesses)

        recurring = summary.get("recurring_mistakes") or []
        if isinstance(recurring, list) and recurring:
            parts.append("\n### 🔁 Recurring Mistakes")
            for i, rm in enumerate(recurring, 1):
                if not isinstance(rm, dict):
                    continue
                pattern = rm.get("pattern", "")
                freq = rm.get("frequency", "")
                fix = rm.get("fix", "")
                line = f"{i}. **{pattern}**"
                if freq:
                    line += f" *({freq})*"
                parts.append(line)
                if fix:
                    parts.append(f"   - *Fix:* {fix}")

        best = summary.get("best_question") or {}
        worst = summary.get("worst_question") or {}
        if best or worst:
            parts.append("\n### 🏆 Best & Worst")
            if best:
                parts.append(
                    f"- **Best — Q{best.get('question_no', '?')}**: {best.get('reason', '')}"
                )
            if worst:
                parts.append(
                    f"- **Worst — Q{worst.get('question_no', '?')}**: {worst.get('reason', '')}"
                )

        plan = summary.get("study_plan") or []
        if isinstance(plan, list) and plan:
            parts.append("\n### 📚 Study Plan")
            for i, item in enumerate(plan, 1):
                if isinstance(item, dict):
                    drill = item.get("drill", "")
                    why = item.get("why", "")
                    how_long = item.get("how_long", "")
                    line = f"{i}. **{drill}**"
                    suffix_bits = []
                    if how_long:
                        suffix_bits.append(f"*{how_long}*")
                    if why:
                        suffix_bits.append(why)
                    if suffix_bits:
                        line += " — " + " · ".join(suffix_bits)
                    parts.append(line)
                elif isinstance(item, str):
                    parts.append(f"{i}. {item}")

        if summary.get("closing_note"):
            parts.append(f"\n### 💬 Closing Note\n\n> {summary['closing_note']}")

    questions = result.get("questions") or []
    if isinstance(questions, list) and questions:
        parts.append("\n---\n")
        for q in questions:
            md = format_question(q)
            if md:
                parts.append(md)
                parts.append("")  # blank line between questions

    return "\n".join(parts).rstrip() + "\n"
