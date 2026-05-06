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


def _build_peer_cap_ranking(company_data) -> str:
    """
    Pre-compute a verified peer market-cap ranking block so the LLM can
    cite directional comparisons (larger/smaller/dwarfs) against arithmetic
    that has already been checked in Python. Returns a plain-text block
    suitable for dropping into the fundamental prompt.
    """
    try:
        main_cap = company_data.market_data.market_cap
        main_name = company_data.name
        main_sym = company_data.symbol
        peers = []
        for comp in (company_data.market_data.competitors or []):
            cap = comp.get("market_cap")
            if not isinstance(cap, (int, float)) or cap <= 0:
                continue
            peers.append({
                "name": comp.get("name") or comp.get("symbol") or "Unknown",
                "symbol": comp.get("symbol") or "N/A",
                "market_cap": float(cap),
                "is_main": bool(comp.get("is_main_company")),
            })

        if isinstance(main_cap, (int, float)) and main_cap > 0 and not any(p["is_main"] for p in peers):
            peers.append({
                "name": main_name,
                "symbol": main_sym,
                "market_cap": float(main_cap),
                "is_main": True,
            })

        if not peers:
            return ""

        peers.sort(key=lambda p: p["market_cap"], reverse=True)

        def _fmt_cap(v: float) -> str:
            if v >= 1_000_000_000_000:
                return f"₹{v/1_000_000_000_000:.2f}T"
            if v >= 1_000_000_000:
                return f"₹{v/1_000_000_000:.2f}B"
            if v >= 1_000_000:
                return f"₹{v/1_000_000:.2f}M"
            return f"₹{v:,.0f}"

        lines = ["--- Verified Peer Market-Cap Ranking (arithmetic checked in Python) ---"]
        for i, p in enumerate(peers, 1):
            tag = "  ← SUBJECT" if p["is_main"] else ""
            lines.append(f"  {i}. {p['name']} ({p['symbol']}): {_fmt_cap(p['market_cap'])}{tag}")

        main_row = next((p for p in peers if p["is_main"]), None)
        if main_row:
            larger = [p for p in peers if p["market_cap"] > main_row["market_cap"]]
            smaller = [p for p in peers if p["market_cap"] < main_row["market_cap"]]
            lines.append("")
            lines.append("  VERIFIED DIRECTIONAL FACTS (use these verbatim for directional claims):")
            if larger:
                names = ", ".join(f"{p['symbol']} ({_fmt_cap(p['market_cap'])})" for p in larger)
                lines.append(f"    • Peers LARGER than {main_row['symbol']} by market cap: {names}")
            if smaller:
                names = ", ".join(f"{p['symbol']} ({_fmt_cap(p['market_cap'])})" for p in smaller)
                lines.append(f"    • Peers SMALLER than {main_row['symbol']} by market cap: {names}")
            if not larger and not smaller:
                lines.append(f"    • {main_row['symbol']} has no peers with comparable market-cap data.")
            lines.append(
                "    • If a peer has a LARGER market cap, do NOT write that the subject 'dwarfs' "
                "it. Reframe using asset-base / branch-network / deposit-base scale instead."
            )

        return "\n".join(lines) + "\n"
    except Exception:
        return ""


class FundamentalAnalysisResult(BaseModel):
    valuation_score: float         # 0-100
    financial_health_score: float  # 0-100
    growth_score: float            # 0-100
    overall_fundamental_score: float  # weighted average
    reasoning: str
    key_positives: list[str]
    key_risks: list[str]
    # Extended narrative sections for richer deep-analysis output.
    # Kept optional so older cached reports still deserialise cleanly.
    valuation_commentary: Optional[str] = ""
    financial_health_commentary: Optional[str] = ""
    growth_commentary: Optional[str] = ""
    peer_comparison: Optional[str] = ""
    moat_assessment: Optional[str] = ""
    capital_allocation: Optional[str] = ""


def run_fundamental_agent(
    company_data,
    analyzed_response_text: str = "",
    fii_dii_analysis_text: str = "",
) -> FundamentalAnalysisResult:
    """
    Analyse CompanyData and return a FundamentalAnalysisResult.

    Args:
        company_data:            models.CompanyData — already populated.
        analyzed_response_text:  The saved `analyzed_response` column from
                                 the stock_analysis DB row. This is the full
                                 formatted fundamental report produced by
                                 the main agent pipeline. When provided,
                                 the LLM uses it as an additional context
                                 source so the output is grounded in the
                                 same numbers the rest of the app shows.
        fii_dii_analysis_text:   The saved `fii_dii_analysis` column — a
                                 formatted FII/DII institutional-flow
                                 block (holdings, quarterly trend, score,
                                 recommendation). Folded into the prompt
                                 so the fundamental commentary reflects
                                 foreign/domestic institutional sentiment.
    """
    client = get_client()

    fin = company_data.financials
    mkt = company_data.market_data
    swot = company_data.swot
    snap = company_data.snapshot

    # All income-statement and per-share figures in CompanyData are sourced
    # from yfinance, which returns trailing-twelve-month values. Label them
    # explicitly (TTM) so the LLM can carry that tag into any number it
    # quotes downstream and never conflate them with FY-annual figures that
    # may appear in the prior analyst report.
    peer_cap_ranking_block = _build_peer_cap_ranking(company_data)

    # Pre-format large INR figures to the trillion scale. Passing raw INR
    # integers (e.g. 10_100_603_355_136) to the LLM is what produced the
    # 'SBI ₹1.011T vs HDFC ₹1.212T' (10× underestimate) bug: the model
    # silently did a crore→trillion conversion with the wrong divisor.
    # Emitting '₹10.10 T (₹10,10,060 Cr)' directly removes the conversion
    # step from the LLM's hands.
    def _fmt_inr_scaled(v):
        if not isinstance(v, (int, float)):
            return v
        av = abs(v)
        if av >= 1e12:
            return f"₹{v/1e12:.2f} T (₹{v/1e7:,.0f} Cr)"
        if av >= 1e7:
            return f"₹{v/1e7:.2f} Cr"
        if av >= 1e5:
            return f"₹{v/1e5:.2f} L"
        return f"₹{v:,.0f}"

    market_cap_display = _fmt_inr_scaled(mkt.market_cap)
    revenue_display = _fmt_inr_scaled(fin.revenue)
    net_profit_display = _fmt_inr_scaled(fin.net_profit)
    ebitda_display = _fmt_inr_scaled(fin.ebitda)
    ev_display = _fmt_inr_scaled(fin.enterprise_value)
    total_debt_display = _fmt_inr_scaled(fin.total_debt)
    cash_display = _fmt_inr_scaled(fin.cash_balance)
    total_assets_display = _fmt_inr_scaled(fin.total_assets)
    total_liab_display = _fmt_inr_scaled(fin.total_liabilities)
    op_cf_display = _fmt_inr_scaled(fin.operating_cash_flow)
    fcf_display = _fmt_inr_scaled(fin.free_cash_flow)

    data_block = f"""
Company:          {company_data.name}
Canonical Ticker: {company_data.symbol}   ← use this ticker consistently after the first mention
Sector: {snap.sector or 'N/A'}  |  Industry: {snap.industry or 'N/A'}

--- Valuation (TTM unless noted) ---
P/E Ratio:          {fin.pe_ratio}
P/B Ratio:          {fin.pb_ratio}
PEG Ratio:          {fin.peg_ratio}
EV/EBITDA:          {fin.ev_ebitda}
Enterprise Value:   {ev_display}

--- Income (TTM — trailing twelve months from yfinance) ---
Revenue (TTM):       {revenue_display}
Net Profit (TTM):    {net_profit_display}
EBITDA (TTM):        {ebitda_display}
EPS (TTM):           {fin.eps}
Gross Margin:        {fin.gross_margin}
Operating Margin:    {fin.operating_margin}
Profit Margin:       {fin.profit_margin}

--- Balance Sheet (latest reported) ---
Debt-to-Equity:     {fin.debt_to_equity}
Total Debt:         {total_debt_display}
Cash Balance:       {cash_display}
Total Assets:       {total_assets_display}
Total Liabilities:  {total_liab_display}

--- Cash Flow (TTM) ---
Operating CF:       {op_cf_display}
Free CF:            {fcf_display}

--- Dividends ---
Dividend Yield:     {fin.dividend_yield}
Payout Ratio:       {fin.payout_ratio}

--- Market ---
Current Price:      {mkt.current_price}
52-Week High:       {mkt.week_52_high}
52-Week Low:        {mkt.week_52_low}
Market Cap:         {market_cap_display}   ← USE THIS TRILLION VALUE AS-IS. Do NOT re-convert crores to trillions yourself; 1 Trillion INR = 1 Lakh Crore (100,000 Cr).
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

{peer_cap_ranking_block}"""

    # Fold in the pre-computed analyst report from the DB so the LLM has
    # the same qualitative context the main app already produced.
    reference_block = ""
    if analyzed_response_text:
        _clip = analyzed_response_text.strip()[:8000]
        reference_block = (
            "\n--- Prior Analyst Report (formatted stock_analysis.analyzed_response) ---\n"
            f"{_clip}\n"
        )

    # Fold in the FII/DII institutional-flow block. Helps the model gauge
    # whether smart money is accumulating or distributing, which directly
    # informs financial-health and moat commentary.
    fii_dii_block = ""
    if fii_dii_analysis_text:
        _clip_fii = fii_dii_analysis_text.strip()[:4000]
        fii_dii_block = (
            "\n--- FII/DII Institutional Flow (stock_analysis.fii_dii_analysis) ---\n"
            f"{_clip_fii}\n"
        )

    system_prompt = (
        "You are a senior buy-side fundamental analyst with 20 years of "
        "experience covering Indian equities (NSE/BSE). Reason step-by-step, "
        "be quantitatively precise, and ground every claim in the numbers "
        "in the data block. Produce a comprehensive institutional-grade "
        "fundamental report — think Goldman/Morgan Stanley equity research "
        "note depth, not a one-paragraph summary.\n\n"
        "Quantitative hygiene rules (NON-NEGOTIABLE — institutional readers "
        "fail a report that violates these):\n"
        "1. Every revenue / profit / EBITDA figure MUST be tagged with its "
        "   fiscal-year context in parentheses. The structured data block "
        "   below is explicitly labelled TTM — carry that 'TTM' tag into "
        "   every number you quote from it. If you also cite a figure from "
        "   the prior analyst report (which may be an FY-annual number), "
        "   tag it 'FYxx' (e.g. 'FY25 annual'). Example: 'Revenue ₹3.43T "
        "   (TTM)' vs. 'Revenue ₹3.70T (FY25 annual)'. NEVER quote the same "
        "   metric with two different numbers without distinct fiscal tags "
        "   — an unlabelled double-quote is the single fastest way to get "
        "   the memo rejected.\n"
        "2. Before writing ANY directional comparison between two numbers "
        "   ('X dwarfs Y', 'larger than', 'exceeds', 'trails'), use the "
        "   VERIFIED DIRECTIONAL FACTS block injected into the data (if "
        "   present) as the source of truth. Do NOT invent a direction "
        "   that contradicts that block. If A = 1.011T and B = 1.212T, "
        "   then B > A — do NOT write that A dwarfs B. When the verified "
        "   block lists a peer as LARGER, reframe the subject's advantage "
        "   in terms of asset-base / branch-network / deposit-base scale.\n"
        "3. Prefer describing scale advantages (branch network, deposit "
        "   base, asset base, distribution reach) over market-cap "
        "   comparisons when a peer has a larger market cap — market cap "
        "   is not the only scale metric.\n"
        "3a. INDIAN NUMBERING (critical — this is the single most common "
        "    LLM error in this codebase): 1 Trillion INR = 1 Lakh Crore = "
        "    100,000 Crore. NOT 1,000,000 Crore. If the data block shows "
        "    a pre-formatted value like '₹10.10 T (₹10,10,060 Cr)', QUOTE "
        "    THAT TRILLION VALUE AS-IS. Never recompute it. A market cap "
        "    of 1,010,060 Cr is ₹10.10 Trillion, NOT ₹1.01 Trillion — "
        "    misreading this produced the infamous 'SBI ₹1.011T dwarfs "
        "    HDFC ₹1.212T' inversion. When in doubt, keep the crore "
        "    number and skip the trillion conversion.\n"
        "4. Naming consistency: introduce the subject ONCE using full "
        "   company name + ticker (e.g. 'State Bank of India (SBI)'), "
        "   then use the CANONICAL TICKER given in the data block for "
        "   every subsequent reference. Do not alternate between the full "
        "   name and the ticker in later sections — pick the ticker and "
        "   stick with it."
    )

    user_prompt = f"""Produce a deep fundamental report for {company_data.name}. Use ALL of the structured data, the prior analyst report, and the FII/DII institutional-flow block below; cite specific numbers from them.

{data_block}
{reference_block}
{fii_dii_block}

Score each dimension from 0 (worst) to 100 (best):
1. valuation_score — P/E, P/B, PEG, EV/EBITDA vs sector peers. Is the stock cheap, fair, or expensive?
2. financial_health_score — Debt/equity, interest coverage, cash position, quality of cash flow, working-capital strength.
3. growth_score — Revenue trajectory, EPS CAGR, margin direction, reinvestment runway.

Compute:
  overall_fundamental_score = (valuation_score * 0.35) + (financial_health_score * 0.35) + (growth_score * 0.30)

Your output MUST be rich and detailed — NOT a one-paragraph summary. Provide:
- reasoning: 8–12 sentences of chain-of-thought. Reference at least 6 specific numbers (P/E, D/E, margins, growth rates, etc.). Explain the scoring logic, not just the verdict.
- key_positives: 6–10 specific bullish points. Each must include a number or concrete fact (e.g. "Operating margin expanded from 14.2% to 17.8% YoY"). No generic platitudes.
- key_risks: 6–10 specific risk factors. Each must include a number or concrete fact.
- valuation_commentary: 3–5 sentences deep-diving the valuation case — multiples vs peers, implied growth, margin-of-safety.
- financial_health_commentary: 3–5 sentences on balance-sheet quality, leverage trajectory, cash conversion, liquidity.
- growth_commentary: 3–5 sentences on revenue/EPS/margin direction, segment mix, capex intensity.
- peer_comparison: 3–5 sentences comparing the company against 2–4 named peers on valuation and profitability. If peers are unknown, say so and explain what sector cohort you are benchmarking against. When quoting peer market caps side-by-side, verify the directional claim (larger/smaller/dwarfs) against the raw numbers before writing it.
- moat_assessment: 3–4 sentences on the competitive moat — brand, scale, regulation, network effects, cost advantage — and whether it is widening, stable, or eroding. If a peer outranks this company on market cap, emphasise asset-base, deposit-base, or distribution-network scale instead of claiming market-cap leadership.
- capital_allocation: 3–4 sentences on how management deploys capital — dividends, buybacks, capex, M&A — and whether the track record is shareholder-friendly.

Return ONLY valid JSON matching this schema exactly (no markdown fences, no trailing commas):
{{
  "valuation_score": <float 0-100>,
  "financial_health_score": <float 0-100>,
  "growth_score": <float 0-100>,
  "overall_fundamental_score": <float 0-100>,
  "reasoning": "<8-12 sentences>",
  "key_positives": ["<point with numbers>", ...],
  "key_risks": ["<risk with numbers>", ...],
  "valuation_commentary": "<3-5 sentences>",
  "financial_health_commentary": "<3-5 sentences>",
  "growth_commentary": "<3-5 sentences>",
  "peer_comparison": "<3-5 sentences>",
  "moat_assessment": "<3-4 sentences>",
  "capital_allocation": "<3-4 sentences>"
}}"""

    try:
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=4000,
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
