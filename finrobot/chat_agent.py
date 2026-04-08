# -*- coding: utf-8 -*-
"""
FinRobot Chat Agent — standalone chat interface for the FinRobot pipeline.
Handles user messages, runs the three-agent pipeline, and returns formatted results.
Does NOT depend on agent1.py or pydantic-ai.
"""

import asyncio
import json
import re
from typing import Optional
from utils.model_config import get_client
from utils.finbert_sentiment import FinBERTSentimentAnalyzer
from finrobot.finrobot_orchestrator import run_finrobot_analysis, FinRobotReport


def _normalize_label(label: str) -> str:
    """Strip emojis/symbols and map to a standard sentiment label."""
    clean = re.sub(r'[^\w\s/]', '', label).strip().lower()
    if "strongly bullish" in clean or "strong buy" in clean:
        return "Strongly Positive"
    elif "bullish" in clean or "positive" in clean:
        return "Positive"
    elif "strongly bearish" in clean or "strong sell" in clean:
        return "Strongly Negative"
    elif "bearish" in clean or "negative" in clean:
        return "Negative"
    return "Neutral"


async def run_finrobot_chat(
    user_message: str,
    company_data,
    session_sentiment: dict = None,
    message_history: list = None,
) -> dict:
    """
    Process a user message in the FinRobot chat tab.

    If company_data is available, runs the full three-agent pipeline.
    Otherwise, uses the LLM to respond conversationally.

    Args:
        user_message:     The user's chat input.
        company_data:     models.CompanyData or None.
        session_sentiment: Optional pre-existing sentiment data from the main agent.
        message_history:  List of prior {"role": ..., "content": ...} dicts for context.

    Returns:
        {
            "response": str,
            "report": FinRobotReport | None,
        }
    """
    if not company_data:
        return {
            "response": _no_stock_response(),
            "report": None,
        }

    # Check if user is asking a follow-up question about an existing report
    _lower = user_message.strip().lower()
    _is_analysis_request = any(kw in _lower for kw in [
        "analy", "report", "recommend", "buy", "sell", "hold",
        "deep", "run", "start", "go", "score", "evaluate",
        "what do you think", "should i", "assess", "review",
    ])

    if not _is_analysis_request:
        # Use LLM for general Q&A about the stock in FinRobot context
        return {
            "response": _llm_followup(user_message, company_data, message_history),
            "report": None,
        }

    # --- Run the full pipeline ---
    # 1. Build sentiment data
    #    Strategy: FinBERT on news texts provides individual-level labels.
    #    session_sentiment (from the main pipeline) has a richer multi-source
    #    combined score (Yahoo Finance + news + Twitter + Reddit). We always
    #    prefer the source with the stronger/more confident signal.

    sentiment_data: dict = {
        "score": 50.0, "label": "Neutral", "confidence": 0.0,
        "breakdown": {}, "individual_results": [],
    }

    news_texts = [
        f"{a.get('title', '')} {a.get('content', '')}"
        for a in (company_data.news or [])
        if a.get('title') or a.get('content')
    ][:30]

    # Step A: Run FinBERT to get per-text labels (useful for the sentiment agent prompt)
    finbert_individual: list = []
    finbert_score = 50.0
    if news_texts:
        try:
            finbert = FinBERTSentimentAnalyzer.get_instance()
            fb_raw = finbert.analyze_texts(news_texts)
            finbert_score = fb_raw.get("score", 50.0)
            finbert_individual = fb_raw.get("individual_results", [])
            print(f"FinRobot chat: FinBERT score = {finbert_score:.1f}")
            # Only adopt FinBERT as primary if it shows a meaningful signal (>2pt deviation)
            if abs(finbert_score - 50.0) > 2.0:
                sentiment_data = fb_raw
        except Exception as e:
            print(f"FinRobot chat: FinBERT skipped — {e}")

    # Step B: Use session_sentiment when it has a stronger signal than FinBERT
    #         session_sentiment is a weighted blend: Yahoo(50%) + News(30%) + Twitter/Reddit(20%)
    #         It is always richer than plain FinBERT on generic company_data.news items.
    tavily_news_summary = ""
    if session_sentiment:
        overall_score = float(
            session_sentiment.get("overall_score")
            or 50.0
        )
        overall_label = _normalize_label(
            session_sentiment.get("overall_label") or "Neutral"
        )

        news_sent = session_sentiment.get("news_sentiment", {})
        fb_cached = news_sent.get("finbert_result", {})

        # Merge FinBERT individual results with any cached ones for richer context
        merged_individual = finbert_individual + fb_cached.get("individual_results", [])

        # Prefer session data if it has a meaningfully different (stronger) signal,
        # OR if FinBERT gave a flat 50.0
        if abs(overall_score - 50.0) > abs(finbert_score - 50.0) or abs(finbert_score - 50.0) <= 2.0:
            sentiment_data = {
                "score": overall_score,
                "label": overall_label,
                "confidence": fb_cached.get("confidence") or news_sent.get("confidence") or 0.5,
                "breakdown": fb_cached.get("breakdown") or sentiment_data.get("breakdown") or {},
                "individual_results": merged_individual[:20],
                # Extra multi-source breakdown for the sentiment agent prompt
                "news_score": news_sent.get("sentiment_score"),
                "yahoo_score": session_sentiment.get("yahoo_sentiment", {}).get("sentiment_score"),
                "twitter_score": session_sentiment.get("twitter_sentiment", {}).get("sentiment_score"),
                "reddit_score": session_sentiment.get("reddit_sentiment", {}).get("sentiment_score"),
            }
            print(
                f"FinRobot chat: Using session sentiment (score={overall_score:.1f}, "
                f"label={overall_label})"
            )

        # Pass the LLM-generated unified analysis as tavily_news_summary
        tavily_news_summary = session_sentiment.get("unified_analysis", "") or ""

    # Build raw text dict for the sentiment agent
    raw_texts = {"news": news_texts} if news_texts else None

    # 2. Run orchestrator
    report = await run_finrobot_analysis(
        company_data=company_data,
        sentiment_data=sentiment_data,
        raw_sentiment_texts=raw_texts,
        tavily_news_summary=tavily_news_summary,
    )

    # 3. Cache on company_data
    company_data.finrobot_report = report

    # 4. Format response
    response = _format_report(report, company_data.name, company_data.symbol)

    return {
        "response": response,
        "report": report,
    }


def _no_stock_response() -> str:
    return (
        "No stock has been analyzed yet. Please analyze a stock first in the "
        "**Chat** tab (e.g. type \"Reliance\" or \"TCS\"), then come back here "
        "to run the FinRobot deep analysis pipeline."
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

    # Include finrobot report summary if available
    report = getattr(company_data, 'finrobot_report', None)
    if report and report.reasoning:
        context += (
            f"\nFinRobot Analysis:\n"
            f"  Recommendation: {report.reasoning.recommendation}\n"
            f"  Score: {report.reasoning.final_score:.1f}/100\n"
            f"  Summary: {report.reasoning.summary}\n"
        )

    # Build messages list: system → prior history (last 10 turns) → current user message
    MAX_HISTORY = 10
    prior = (message_history or [])[-MAX_HISTORY:]
    # Strip the last user message from history if it duplicates the current input
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


def _format_report(report: FinRobotReport, name: str, symbol: str) -> str:
    """Format a FinRobotReport into markdown for the chat display."""
    parts = [f"## FinRobot Deep Analysis — {name} ({symbol})\n"]

    if report.reasoning:
        r = report.reasoning
        parts.append(f"**Recommendation: {r.recommendation}** | Confidence: {r.confidence} | Score: {r.final_score:.1f}/100")
        parts.append(f"**Time Horizon:** {r.time_horizon}\n")
        parts.append(f"**Executive Summary:**\n{r.summary}\n")
        parts.append(f"**Chain of Thought:**\n{r.chain_of_thought}\n")
        if r.contradictions_noted:
            parts.append(f"**Contradictions Noted:** {r.contradictions_noted}\n")

    if report.fundamental:
        f = report.fundamental
        parts.append(
            f"---\n**Fundamental Scores:** Valuation={f.valuation_score:.1f} | "
            f"Financial Health={f.financial_health_score:.1f} | Growth={f.growth_score:.1f} | "
            f"Overall={f.overall_fundamental_score:.1f}\n"
        )
        parts.append("**Key Positives:** " + ", ".join(f.key_positives[:5]))
        parts.append("**Key Risks:** " + ", ".join(f.key_risks[:5]) + "\n")

    if report.sentiment:
        s = report.sentiment
        parts.append(
            f"---\n**Sentiment:** {s.sentiment_score:.1f}/100 ({s.sentiment_label}) | "
            f"Momentum: {s.sentiment_momentum}\n"
        )
        parts.append(f"**Theme:** {s.theme_summary}")
        if s.key_drivers:
            parts.append("**Key Drivers:**\n" + "\n".join(f"- {d}" for d in s.key_drivers))
        if s.anomalies_detected:
            parts.append("**Anomalies:** " + "; ".join(s.anomalies_detected))

    if report.agents_failed:
        parts.append(f"\n_Agents with errors: {', '.join(report.agents_failed)}_")

    parts.append(f"\n_Agents completed: {', '.join(report.agents_completed)}_")

    return "\n".join(parts)
