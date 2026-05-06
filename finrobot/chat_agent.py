# -*- coding: utf-8 -*-
"""
FinRobot Chat Agent — standalone chat interface for the FinRobot pipeline.
Handles user messages, runs the three-agent pipeline, and returns formatted results.
Does NOT depend on agent1.py or pydantic-ai.

Data source policy (per client, to reduce API/Tavily cost)
───────────────────────────────────────────────────────────
The market-sentiment pipeline (news/Yahoo/Twitter/Reddit) is NOT invoked
here. Instead, FinRobot reads three columns from the latest
`stock_analysis` row for the stock:

  • analyzed_response  — full formatted fundamental report (fed to the
                         Fundamental Agent as extra context).
  • fii_dii_analysis   — FII/DII institutional shareholding block
                         (fed to the Reasoning Agent as dedicated
                         institutional-flow context).
  • future_senti       — pre-computed future-outlook block (fed to the
                         Future-Outlook Agent — replaces live sentiment).

All live sentiment code paths are deliberately skipped.
"""

import re
from typing import Optional
from utils.model_config import get_client
from finrobot.finrobot_orchestrator import run_finrobot_analysis, FinRobotReport


# Splits on a "Step N:" / "Step N." / "Step N -" marker at a word boundary so
# the chain-of-thought text (which the LLM emits as one wall of prose) can be
# re-rendered with each step on its own line. Kept lenient on the separator
# (colon / period / dash / en-dash) because prompt outputs vary.
_STEP_SPLIT_RE = re.compile(r"(?=\bStep\s*\d{1,2}\s*[:.\-–])", flags=re.IGNORECASE)


def _format_chain_of_thought(text: str) -> str:
    """
    Reformat a chain-of-thought blob into a list of bolded step-by-step
    lines so the Expert-view reader can scan each step independently
    instead of eyeballing a single paragraph.
    """
    if not text or not text.strip():
        return text
    chunks = [c.strip() for c in _STEP_SPLIT_RE.split(text) if c.strip()]
    # If the split didn't find any "Step N:" markers, keep the original prose
    # verbatim — we don't want to mangle formats the LLM didn't follow.
    if len(chunks) < 2:
        return text
    out_lines: list[str] = []
    for chunk in chunks:
        # Bold the "Step N" header so it stands out at a glance.
        fixed = re.sub(
            r"^(Step\s*\d{1,2})\s*[:.\-–]\s*",
            r"**\1:** ",
            chunk,
            count=1,
            flags=re.IGNORECASE,
        )
        out_lines.append(fixed)
    # Blank line between steps → markdown renders each as its own paragraph.
    return "\n\n".join(out_lines)


# ──────────────────────────────────────────────────────────────────
# DB context loader
# ──────────────────────────────────────────────────────────────────

def _load_db_context(stock_symbol: str) -> dict:
    """Pull the latest analyzed_response + fii_dii_analysis + future_senti
    for a symbol.

    Returns a dict with keys:
        analyzed_response:    str
        fii_dii_analysis:     str
        future_senti:         str
        future_senti_status:  str
    Missing columns fall back to empty strings / "neutral".
    """
    result = {
        "analyzed_response": "",
        "fii_dii_analysis": "",
        "future_senti": "",
        "future_senti_status": "neutral",
    }
    if not stock_symbol:
        return result
    try:
        from database_utility.database import StockDatabase
        db = StockDatabase()
        if not db.connect():
            return result
        try:
            row = db.get_latest_analysis(stock_symbol)
        finally:
            db.disconnect()
        if not row:
            print(f"FinRobot: no stock_analysis row for {stock_symbol}")
            return result
        result["analyzed_response"] = (row.get("analyzed_response") or "").strip()
        result["fii_dii_analysis"] = (row.get("fii_dii_analysis") or "").strip()
        result["future_senti"] = (row.get("future_senti") or "").strip()
        result["future_senti_status"] = (
            (row.get("future_senti_status") or "neutral").strip().lower()
        )
        print(
            f"FinRobot: loaded DB context for {stock_symbol} — "
            f"analyzed_response={len(result['analyzed_response'])} chars, "
            f"fii_dii_analysis={len(result['fii_dii_analysis'])} chars, "
            f"future_senti={len(result['future_senti'])} chars, "
            f"status={result['future_senti_status']}"
        )
    except Exception as e:
        print(f"FinRobot: DB context load failed for {stock_symbol} — {e}")
    return result


async def run_finrobot_chat(
    user_message: str,
    company_data,
    session_sentiment: dict = None,  # kept for signature compat; ignored
    message_history: list = None,
) -> dict:
    """
    Process a user message in the FinRobot chat tab.

    Args:
        user_message:      The user's chat input.
        company_data:      models.CompanyData or None.
        session_sentiment: IGNORED — retained for backward-compatible call
                           sites. The market-sentiment pipeline is no longer
                           invoked (cost-reduction). Future outlook is
                           sourced from the DB instead.
        message_history:   List of prior {"role": ..., "content": ...} dicts.

    Returns:
        {"response": str, "report": FinRobotReport | None}
    """
    if not company_data:
        return {
            "response": _no_stock_response(),
            "report": None,
        }

    _lower = user_message.strip().lower()
    _is_analysis_request = any(kw in _lower for kw in [
        "analy", "report", "recommend", "buy", "sell", "hold",
        "deep", "run", "start", "go", "score", "evaluate",
        "what do you think", "should i", "assess", "review",
    ])

    if not _is_analysis_request:
        return {
            "response": _llm_followup(user_message, company_data, message_history),
            "report": None,
        }

    # --- Load DB-backed context (no live sentiment APIs) ---
    db_ctx = _load_db_context(company_data.symbol)
    analyzed_response = db_ctx["analyzed_response"]
    fii_dii_analysis = db_ctx["fii_dii_analysis"]
    future_senti = db_ctx["future_senti"]
    future_senti_status = db_ctx["future_senti_status"]

    # --- Run orchestrator on DB-sourced context ---
    report = await run_finrobot_analysis(
        company_data=company_data,
        analyzed_response=analyzed_response,
        fii_dii_analysis=fii_dii_analysis,
        future_senti=future_senti,
        future_senti_status=future_senti_status,
        # Explicit symbol → timing summary buckets under the right stock
        # even if `company_data.symbol` is slightly different (casing etc.).
        timing_symbol=(company_data.symbol or "").strip().upper() or None,
    )

    # Cache the report on the CompanyData object for downstream consumers.
    company_data.finrobot_report = report

    response = _format_report(report, company_data.name, company_data.symbol)

    # Also build the beginner-friendly "Plain English View" from the
    # same report object. The expert report remains the default; the UI
    # toggles between the two. We build both eagerly so switching views
    # is instant — the work is <10ms on the already-populated report.
    try:
        from finrobot.plain_english_formatter import format_plain_english_report
        response_plain = format_plain_english_report(
            report, company_data, company_data.symbol, company_data.name
        )
    except Exception as e:
        print(f"FinRobot: plain-english formatter failed — {e}")
        response_plain = ""

    return {
        "response": response,             # Expert View (unchanged)
        "response_plain": response_plain, # Plain English View (new)
        "report": report,
    }


def _no_stock_response() -> str:
    return (
        "No stock has been analyzed yet. Please search a stock on the "
        "**Data Dashboard** tab first, then come back here to run the "
        "FinRobot deep analysis pipeline."
    )


def _llm_followup(user_message: str, company_data, message_history: list = None) -> str:
    """Use LLM to answer a follow-up question in context of the stock."""
    client = get_client()

    context = (
        f"Company: {company_data.name} ({company_data.symbol})\n"
        f"Sector: {getattr(company_data.snapshot, 'sector', 'N/A')}\n"
        f"Price: {getattr(company_data.market_data, 'current_price', 'N/A')}\n"
        f"P/E: {getattr(company_data.financials, 'pe_ratio', 'N/A')}\n"
        f"Market Cap: {getattr(company_data.market_data, 'market_cap', 'N/A')}\n"
    )

    report = getattr(company_data, 'finrobot_report', None)
    if report and report.reasoning:
        context += (
            f"\nFinRobot Analysis:\n"
            f"  Recommendation: {report.reasoning.recommendation}\n"
            f"  Score: {report.reasoning.final_score:.1f}/100\n"
            f"  Summary: {report.reasoning.summary}\n"
        )

    MAX_HISTORY = 10
    prior = (message_history or [])[-MAX_HISTORY:]
    if prior and prior[-1].get("role") == "user" and prior[-1].get("content") == user_message:
        prior = prior[:-1]

    messages = [
        {"role": "system", "content": (
            "You are FinRobot, an AI investment analyst. Answer the user's question "
            "about the stock using the context provided. Be concise and data-driven. "
            "If the user hasn't run the deep analysis yet, suggest they do so.\n\n"
            f"Stock context:\n{context}"
        )},
        *prior,
        {"role": "user", "content": user_message},
    ]

    try:
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=messages,
            temperature=0.2,
            max_tokens=800,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Error processing your question: {e}"


# ──────────────────────────────────────────────────────────────────
# Markdown report formatter
# ──────────────────────────────────────────────────────────────────

def _bullets(items: Optional[list]) -> str:
    """Render a list as markdown bullets; empty string if no items."""
    if not items:
        return ""
    return "\n".join(f"- {item}" for item in items)


def _format_report(report: FinRobotReport, name: str, symbol: str) -> str:
    """Format a FinRobotReport into a rich, multi-section markdown document."""
    parts: list[str] = [f"## FinRobot Deep Analysis — {name} ({symbol})\n"]

    r = report.reasoning
    if r:
        parts.append(
            f"**Recommendation: {r.recommendation}** &nbsp;|&nbsp; "
            f"Confidence: {r.confidence} &nbsp;|&nbsp; "
            f"Score: {r.final_score:.1f}/100 &nbsp;|&nbsp; "
            f"Time Horizon: {r.time_horizon}\n"
        )
        if getattr(r, "final_verdict", ""):
            parts.append(f"> **Verdict:** {r.final_verdict}\n")

        parts.append("### Executive Summary")
        parts.append(r.summary + "\n")

        if getattr(r, "investment_thesis", ""):
            parts.append("### Investment Thesis")
            parts.append(r.investment_thesis + "\n")

        parts.append("### Chain of Thought")
        parts.append(_format_chain_of_thought(r.chain_of_thought) + "\n")

        if getattr(r, "bull_case", None):
            parts.append("### Bull Case")
            parts.append(_bullets(r.bull_case) + "\n")

        if getattr(r, "bear_case", None):
            parts.append("### Bear Case")
            parts.append(_bullets(r.bear_case) + "\n")

        if getattr(r, "catalysts", None):
            parts.append("### Upcoming Catalysts")
            parts.append(_bullets(r.catalysts) + "\n")

        if getattr(r, "scenario_analysis", ""):
            parts.append("### Scenario Analysis (Bull / Base / Bear)")
            parts.append(r.scenario_analysis + "\n")

        if getattr(r, "price_levels", ""):
            parts.append("### Price Levels & Target")
            parts.append(r.price_levels + "\n")

        if getattr(r, "risk_management", ""):
            parts.append("### Risk Management")
            parts.append(r.risk_management + "\n")

        if r.contradictions_noted:
            parts.append("### Contradictions Noted")
            parts.append(r.contradictions_noted + "\n")

    f = report.fundamental
    if f:
        parts.append("---")
        parts.append("### Fundamental Analysis")
        parts.append(
            f"**Scores:** Valuation={f.valuation_score:.1f} &nbsp;|&nbsp; "
            f"Financial Health={f.financial_health_score:.1f} &nbsp;|&nbsp; "
            f"Growth={f.growth_score:.1f} &nbsp;|&nbsp; "
            f"**Overall={f.overall_fundamental_score:.1f}**\n"
        )
        if f.reasoning:
            parts.append("**Reasoning:** " + f.reasoning + "\n")

        if getattr(f, "valuation_commentary", ""):
            parts.append("**Valuation Commentary:** " + f.valuation_commentary + "\n")
        if getattr(f, "financial_health_commentary", ""):
            parts.append("**Financial Health:** " + f.financial_health_commentary + "\n")
        if getattr(f, "growth_commentary", ""):
            parts.append("**Growth:** " + f.growth_commentary + "\n")
        if getattr(f, "peer_comparison", ""):
            parts.append("**Peer Comparison:** " + f.peer_comparison + "\n")
        if getattr(f, "moat_assessment", ""):
            parts.append("**Moat Assessment:** " + f.moat_assessment + "\n")
        if getattr(f, "capital_allocation", ""):
            parts.append("**Capital Allocation:** " + f.capital_allocation + "\n")

        if f.key_positives:
            parts.append("**Key Positives:**")
            parts.append(_bullets(f.key_positives) + "\n")
        if f.key_risks:
            parts.append("**Key Risks:**")
            parts.append(_bullets(f.key_risks) + "\n")

    s = report.sentiment
    if s:
        parts.append("---")
        parts.append("### Future Outlook (from DB)")
        parts.append(
            f"**Score:** {s.sentiment_score:.1f}/100 ({s.sentiment_label}) &nbsp;|&nbsp; "
            f"**Momentum:** {s.sentiment_momentum}\n"
        )
        if s.theme_summary:
            parts.append("**Theme:** " + s.theme_summary + "\n")
        if s.llm_commentary:
            parts.append("**Commentary:** " + s.llm_commentary + "\n")
        if getattr(s, "analyst_view", ""):
            parts.append("**Analyst View:** " + s.analyst_view + "\n")
        if getattr(s, "performance_highlights", ""):
            parts.append("**Performance Highlights:** " + s.performance_highlights + "\n")
        if s.key_drivers:
            parts.append("**Key Drivers:**")
            parts.append(_bullets(s.key_drivers) + "\n")
        if getattr(s, "growth_drivers_detail", None):
            parts.append("**Growth Drivers (Detail):**")
            parts.append(_bullets(s.growth_drivers_detail) + "\n")
        if getattr(s, "risk_factors_detail", None):
            parts.append("**Risk Factors (Detail):**")
            parts.append(_bullets(s.risk_factors_detail) + "\n")
        if getattr(s, "target_price_snapshot", ""):
            parts.append(f"**Target/Upside:** {s.target_price_snapshot}\n")
        if s.anomalies_detected:
            parts.append("**Anomalies:** " + "; ".join(s.anomalies_detected))

    if report.agents_failed:
        parts.append(f"\n_Agents with errors: {', '.join(report.agents_failed)}_")

    parts.append(f"\n_Agents completed: {', '.join(report.agents_completed)}_")

    return "\n".join(parts)
