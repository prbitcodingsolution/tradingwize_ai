# -*- coding: utf-8 -*-
"""
FinRobot Orchestrator — entry point for the full three-agent pipeline.

Execution order:
  1. Fundamental Agent  → FundamentalAnalysisResult
     (uses live CompanyData + the persisted `analyzed_response` DB text)
  2. Future-Outlook Agent → SentimentAgentResult
     (uses the persisted `future_senti` DB text; no live API calls)
  3. Reasoning Agent    → ReasoningResult

Each agent failure is isolated: the result field is set to None, the agent
name is added to agents_failed, and the pipeline continues.

Cost note
─────────
The client removed the Sentiment Analysis tab and asked us to stop all
live news / Yahoo / Twitter / Reddit / Tavily sentiment processing to
reduce API spend. This pipeline therefore sources sentiment from the
pre-computed `future_senti` DB column only. The legacy
`run_sentiment_agent` function is retained in `sentiment_agent.py` for
potential re-use but is NOT called here.
"""

import asyncio
import traceback
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

from finrobot.fundamental_agent import FundamentalAnalysisResult, run_fundamental_agent
from finrobot.sentiment_agent import SentimentAgentResult, run_future_outlook_agent
from finrobot.reasoning_agent import ReasoningResult, run_reasoning_agent


class FinRobotReport(BaseModel):
    fundamental: Optional[FundamentalAnalysisResult] = None
    sentiment: Optional[SentimentAgentResult] = None
    reasoning: Optional[ReasoningResult] = None
    generated_at: datetime
    symbol: str
    agents_completed: list[str]
    agents_failed: list[str]


async def run_finrobot_analysis(
    company_data,
    analyzed_response: str = "",
    fii_dii_analysis: str = "",
    future_senti: str = "",
    future_senti_status: str = "neutral",
    *,
    timing_symbol: Optional[str] = None,
) -> FinRobotReport:
    """
    Run the full FinRobot three-agent pipeline using DB-sourced context.

    Args:
        company_data:         models.CompanyData — already populated.
        analyzed_response:    The `analyzed_response` column from stock_analysis
                              (full formatted fundamental report from the main
                              agent). Fed to the Fundamental Agent as extra
                              context.
        fii_dii_analysis:     The `fii_dii_analysis` column from stock_analysis
                              (FII/DII institutional-shareholding block).
                              Fed to both the Fundamental and Reasoning Agents
                              so institutional flow factors into the memo.
        future_senti:         The `future_senti` column from stock_analysis
                              (compact future-outlook summary). Fed to the
                              Future-Outlook Agent instead of live sentiment.
        future_senti_status:  "bullish" / "bearish" / "neutral" — used to
                              derive a starting sentiment score.

    Returns:
        FinRobotReport with results from all agents that succeeded.
    """
    agents_completed: list[str] = []
    agents_failed: list[str] = []
    fundamental_result: Optional[FundamentalAnalysisResult] = None
    sentiment_result: Optional[SentimentAgentResult] = None
    reasoning_result: Optional[ReasoningResult] = None

    # ── Phase-4 timing: FinRobot (orchestrator + per-agent sub-phases) ──
    # If the caller didn't pass an explicit `timing_symbol`, fall back to
    # whatever is on `company_data.symbol` so timings still get bucketed
    # under the right stock in the summary.
    from utils.timing import phase_timer as _phase_timer
    _sym = (timing_symbol
            or (getattr(company_data, "symbol", None) if company_data else None)
            or None)
    if isinstance(_sym, str):
        _sym = _sym.strip().upper() or None

    with _phase_timer("FinRobot Orchestrator", symbol=_sym):
        # --- Agent 1: Fundamental ---
        try:
            print("FinRobot: Running Fundamental Agent...")
            with _phase_timer("FinRobot Orchestrator » Fundamental Agent", symbol=_sym):
                fundamental_result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    run_fundamental_agent,
                    company_data,
                    analyzed_response,
                    fii_dii_analysis,
                )
            agents_completed.append("fundamental")
            print(f"FinRobot: Fundamental score = {fundamental_result.overall_fundamental_score:.1f}")
        except Exception as e:
            agents_failed.append(f"fundamental: {e}")
            traceback.print_exc()
            print(f"FinRobot: Fundamental Agent failed — {e}")

        # --- Agent 2: Future-Outlook (replaces legacy market-sentiment agent) ---
        try:
            print("FinRobot: Running Future-Outlook Agent...")
            company_name = getattr(company_data, "name", "") or ""
            with _phase_timer("FinRobot Orchestrator » Future-Outlook Agent", symbol=_sym):
                sentiment_result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    run_future_outlook_agent,
                    future_senti,
                    future_senti_status,
                    company_name,
                )
            agents_completed.append("future_outlook")
            print(f"FinRobot: Future-outlook score = {sentiment_result.sentiment_score:.1f}")
        except Exception as e:
            agents_failed.append(f"future_outlook: {e}")
            traceback.print_exc()
            print(f"FinRobot: Future-Outlook Agent failed — {e}")

        # --- Agent 3: Reasoning (synthesis) ---
        try:
            print("FinRobot: Running Reasoning Agent...")
            sector = (company_data.snapshot.sector or "") if hasattr(company_data, "snapshot") else ""
            with _phase_timer("FinRobot Orchestrator » Reasoning Agent", symbol=_sym):
                reasoning_result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    run_reasoning_agent,
                    fundamental_result,
                    sentiment_result,
                    company_data.name,
                    sector,
                    future_senti,
                    fii_dii_analysis,
                )
            agents_completed.append("reasoning")
            print(f"FinRobot: Recommendation = {reasoning_result.recommendation} (score={reasoning_result.final_score:.1f})")
        except Exception as e:
            agents_failed.append(f"reasoning: {e}")
            traceback.print_exc()
            print(f"FinRobot: Reasoning Agent failed — {e}")

    return FinRobotReport(
        fundamental=fundamental_result,
        sentiment=sentiment_result,
        reasoning=reasoning_result,
        generated_at=datetime.now(),
        symbol=company_data.symbol,
        agents_completed=agents_completed,
        agents_failed=agents_failed,
    )
