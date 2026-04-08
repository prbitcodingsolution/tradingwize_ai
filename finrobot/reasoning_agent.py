# -*- coding: utf-8 -*-
"""
FinRobot — Reasoning Agent (Agent 3 / Synthesis Layer)
Acts as a senior analyst reviewing outputs from the Fundamental and Sentiment agents.
Uses the existing OpenRouter pipeline via utils/model_config.py.
"""

import json
from typing import Optional
from pydantic import BaseModel

from utils.model_config import get_client
from finrobot.fundamental_agent import FundamentalAnalysisResult
from finrobot.sentiment_agent import SentimentAgentResult


class ReasoningResult(BaseModel):
    final_score: float          # 0-100 synthesised overall score
    recommendation: str         # "Strong Buy" / "Buy" / "Hold" / "Sell" / "Strong Sell"
    confidence: str             # "High" / "Medium" / "Low"
    chain_of_thought: str       # Full step-by-step reasoning text
    summary: str                # 2-3 sentence executive summary
    contradictions_noted: str   # Fundamental vs sentiment conflict (empty if none)
    time_horizon: str           # "Short-term" / "Medium-term" / "Long-term"


def run_reasoning_agent(
    fundamental_result: Optional[FundamentalAnalysisResult],
    sentiment_result: Optional[SentimentAgentResult],
    company_name: str,
    sector: str,
    tavily_news_summary: str = "",
) -> ReasoningResult:
    """
    Synthesise fundamental and sentiment agent outputs into a final recommendation.

    Degrades gracefully if either input is None.
    """
    client = get_client()

    # Build fundamental block
    if fundamental_result:
        fund_block = f"""Fundamental Agent Results:
  Overall Fundamental Score: {fundamental_result.overall_fundamental_score:.1f}/100
  Valuation Score:           {fundamental_result.valuation_score:.1f}/100
  Financial Health Score:    {fundamental_result.financial_health_score:.1f}/100
  Growth Score:              {fundamental_result.growth_score:.1f}/100
  Key Positives:             {fundamental_result.key_positives}
  Key Risks:                 {fundamental_result.key_risks}
  Reasoning:                 {fundamental_result.reasoning}"""
    else:
        fund_block = "Fundamental Agent: DATA UNAVAILABLE (agent failed)"

    # Build sentiment block
    if sentiment_result:
        sent_block = f"""Sentiment Agent Results:
  Sentiment Score:     {sentiment_result.sentiment_score:.1f}/100
  Sentiment Label:     {sentiment_result.sentiment_label}
  Momentum:            {sentiment_result.sentiment_momentum}
  Theme Summary:       {sentiment_result.theme_summary}
  Key Drivers:         {sentiment_result.key_drivers}
  Anomalies:           {sentiment_result.anomalies_detected}
  Commentary:          {sentiment_result.llm_commentary}"""
    else:
        sent_block = "Sentiment Agent: DATA UNAVAILABLE (agent failed)"

    news_section = f"\nRecent News Summary:\n{tavily_news_summary[:500]}" if tavily_news_summary else ""

    # Pre-compute score strings to avoid f-string format spec issues
    fund_score_str = f"{fundamental_result.overall_fundamental_score:.1f}" if fundamental_result else "N/A"
    sent_score_str = f"{sentiment_result.sentiment_score:.1f}" if sentiment_result else "N/A"

    system_prompt = (
        "You are a Chief Investment Officer reviewing two research reports from junior analysts. "
        "You synthesise conflicting signals, identify the dominant investment thesis, and produce "
        "a clear, actionable recommendation with confidence level. "
        "You cover Indian equities and are aware of sector-specific valuation norms."
    )

    user_prompt = f"""Company: {company_name}
Sector:  {sector or 'N/A'}
{news_section}

{fund_block}

{sent_block}

Perform a step-by-step synthesis:
STEP 1: State the fundamental picture in one sentence.
STEP 2: State the sentiment picture in one sentence.
STEP 3: Identify any contradiction between them (e.g., strong fundamentals but deteriorating sentiment).
STEP 4: Reason about what the combination means for the stock's outlook.
STEP 5: Arrive at a final recommendation and confidence level.

Scores for reference:
  Fundamental Score: {fund_score_str}/100
  Sentiment Score:   {sent_score_str}/100

Final score formula (if both available):
  final_score = (fundamental_score * 0.55) + (sentiment_score * 0.45)
  If only fundamental: final_score = fundamental_score
  If only sentiment:   final_score = sentiment_score

Recommendation mapping:
  final_score >= 70 → Strong Buy
  final_score >= 60 → Buy
  final_score >= 40 → Hold
  final_score >= 30 → Sell
  final_score < 30  → Strong Sell

Return ONLY valid JSON:
{{
  "final_score": <float 0-100>,
  "recommendation": "<Strong Buy|Buy|Hold|Sell|Strong Sell>",
  "confidence": "<High|Medium|Low>",
  "chain_of_thought": "<full step-by-step reasoning as one paragraph>",
  "summary": "<2-3 sentence executive summary>",
  "contradictions_noted": "<description of any conflict, or empty string if none>",
  "time_horizon": "<Short-term|Medium-term|Long-term>"
}}"""

    try:
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.15,
            max_tokens=1200,
        )
        raw = response.choices[0].message.content.strip()
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()
        data = json.loads(raw)
        return ReasoningResult(**data)
    except Exception as e:
        raise RuntimeError(f"ReasoningAgent LLM call failed: {e}") from e
