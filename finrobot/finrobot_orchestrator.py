# -*- coding: utf-8 -*-
"""
FinRobot Orchestrator — entry point for the full three-agent pipeline.

Execution order:
  1. Fundamental Agent  → FundamentalAnalysisResult
  2. Sentiment Agent    → SentimentAgentResult
  3. Reasoning Agent    → ReasoningResult

Each agent failure is isolated: the result field is set to None, the agent
name is added to agents_failed, and the pipeline continues.
"""

import asyncio
import traceback
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

from finrobot.fundamental_agent import FundamentalAnalysisResult, run_fundamental_agent
from finrobot.sentiment_agent import SentimentAgentResult, run_sentiment_agent
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
    sentiment_data: dict,
    raw_sentiment_texts: Optional[dict] = None,
    tavily_news_summary: str = "",
) -> FinRobotReport:
    """
    Run the full FinRobot three-agent pipeline.

    Args:
        company_data:         models.CompanyData — already populated.
        sentiment_data:       Output from FinBERTSentimentAnalyzer or the main sentiment dict.
        raw_sentiment_texts:  Optional dict keyed by source with raw text lists.
        tavily_news_summary:  Summary string from stock_news_analyzer.

    Returns:
        FinRobotReport with results from all agents that succeeded.
    """
    agents_completed: list[str] = []
    agents_failed: list[str] = []
    fundamental_result: Optional[FundamentalAnalysisResult] = None
    sentiment_result: Optional[SentimentAgentResult] = None
    reasoning_result: Optional[ReasoningResult] = None

    # --- Agent 1: Fundamental ---
    try:
        print("FinRobot: Running Fundamental Agent...")
        fundamental_result = await asyncio.get_event_loop().run_in_executor(
            None, run_fundamental_agent, company_data
        )
        agents_completed.append("fundamental")
        print(f"FinRobot: Fundamental score = {fundamental_result.overall_fundamental_score:.1f}")
    except Exception as e:
        agents_failed.append(f"fundamental: {e}")
        traceback.print_exc()
        print(f"FinRobot: Fundamental Agent failed — {e}")

    # --- Agent 2: Sentiment ---
    try:
        print("FinRobot: Running Sentiment Agent...")
        news_articles = company_data.news if hasattr(company_data, "news") else []
        sentiment_result = await asyncio.get_event_loop().run_in_executor(
            None,
            run_sentiment_agent,
            sentiment_data,
            news_articles,
            raw_sentiment_texts,
        )
        agents_completed.append("sentiment")
        print(f"FinRobot: Sentiment score = {sentiment_result.sentiment_score:.1f}")
    except Exception as e:
        agents_failed.append(f"sentiment: {e}")
        traceback.print_exc()
        print(f"FinRobot: Sentiment Agent failed — {e}")

    # --- Agent 3: Reasoning (synthesis) ---
    try:
        print("FinRobot: Running Reasoning Agent...")
        sector = (company_data.snapshot.sector or "") if hasattr(company_data, "snapshot") else ""
        reasoning_result = await asyncio.get_event_loop().run_in_executor(
            None,
            run_reasoning_agent,
            fundamental_result,
            sentiment_result,
            company_data.name,
            sector,
            tavily_news_summary,
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
