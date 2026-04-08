# -*- coding: utf-8 -*-
"""
FinRobot — Fundamental Agent (Agent 1)
Analyses CompanyData financials and produces a structured fundamental score.
Uses the existing OpenRouter pipeline via utils/model_config.py.
"""

import json
from typing import Optional
from pydantic import BaseModel

from utils.model_config import get_client


class FundamentalAnalysisResult(BaseModel):
    valuation_score: float         # 0-100
    financial_health_score: float  # 0-100
    growth_score: float            # 0-100
    overall_fundamental_score: float  # weighted average
    reasoning: str
    key_positives: list[str]
    key_risks: list[str]


def run_fundamental_agent(company_data) -> FundamentalAnalysisResult:
    """
    Analyse CompanyData and return a FundamentalAnalysisResult.

    Args:
        company_data: models.CompanyData — already populated, not fetched here.
    """
    client = get_client()

    fin = company_data.financials
    mkt = company_data.market_data
    swot = company_data.swot
    snap = company_data.snapshot

    data_block = f"""
Company: {company_data.name} ({company_data.symbol})
Sector: {snap.sector or 'N/A'}  |  Industry: {snap.industry or 'N/A'}

--- Valuation ---
P/E Ratio:          {fin.pe_ratio}
P/B Ratio:          {fin.pb_ratio}
PEG Ratio:          {fin.peg_ratio}
EV/EBITDA:          {fin.ev_ebitda}
Enterprise Value:   {fin.enterprise_value}

--- Income ---
Revenue:            {fin.revenue}
Net Profit:         {fin.net_profit}
EBITDA:             {fin.ebitda}
EPS:                {fin.eps}
Gross Margin:       {fin.gross_margin}
Operating Margin:   {fin.operating_margin}
Profit Margin:      {fin.profit_margin}

--- Balance Sheet ---
Debt-to-Equity:     {fin.debt_to_equity}
Total Debt:         {fin.total_debt}
Cash Balance:       {fin.cash_balance}
Total Assets:       {fin.total_assets}
Total Liabilities:  {fin.total_liabilities}

--- Cash Flow ---
Operating CF:       {fin.operating_cash_flow}
Free CF:            {fin.free_cash_flow}

--- Dividends ---
Dividend Yield:     {fin.dividend_yield}
Payout Ratio:       {fin.payout_ratio}

--- Market ---
Current Price:      {mkt.current_price}
52-Week High:       {mkt.week_52_high}
52-Week Low:        {mkt.week_52_low}
Market Cap:         {mkt.market_cap}
Beta:               {mkt.beta}
Promoter Holding:   {mkt.promoter_holding}%
FII Holding:        {mkt.fii_holding}%
DII Holding:        {mkt.dii_holding}%

--- SWOT ---
Strengths:     {swot.strengths}
Weaknesses:    {swot.weaknesses}
Opportunities: {swot.opportunities}
Threats:       {swot.threats}

--- Peers ---
{mkt.competitors[:5] if mkt.competitors else 'N/A'}
"""

    system_prompt = (
        "You are a senior buy-side fundamental analyst with 20 years of experience "
        "covering Indian equities. Reason step-by-step and be quantitatively precise."
    )

    user_prompt = f"""Analyse the following financial data for {company_data.name} and produce a structured fundamental report.

{data_block}

Score each dimension from 0 (worst) to 100 (best):
1. valuation_score — Is the stock cheap, fair, or expensive vs its sector peers?
2. financial_health_score — Debt levels, cash flow quality, balance-sheet strength.
3. growth_score — Revenue consistency, EPS trend, margin expansion or contraction.

Compute:
  overall_fundamental_score = (valuation_score * 0.35) + (financial_health_score * 0.35) + (growth_score * 0.30)

Also provide:
- reasoning: 3–5 sentences chain-of-thought explaining how you arrived at the scores.
- key_positives: list of 3–5 bullish fundamental points (specific, not generic).
- key_risks: list of 3–5 fundamental risk factors (specific, not generic).

Return ONLY valid JSON matching this schema exactly:
{{
  "valuation_score": <float 0-100>,
  "financial_health_score": <float 0-100>,
  "growth_score": <float 0-100>,
  "overall_fundamental_score": <float 0-100>,
  "reasoning": "<text>",
  "key_positives": ["<point>", ...],
  "key_risks": ["<risk>", ...]
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
        return FundamentalAnalysisResult(**data)
    except Exception as e:
        raise RuntimeError(f"FundamentalAgent LLM call failed: {e}") from e
