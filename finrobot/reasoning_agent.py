# -*- coding: utf-8 -*-
"""
FinRobot — Reasoning Agent (Agent 3 / Synthesis Layer)
Acts as a senior analyst reviewing outputs from the Fundamental and Sentiment agents.
Uses the existing OpenRouter pipeline via utils/model_config.py.
"""

import json
import re
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

from utils.model_config import get_client
from finrobot.fundamental_agent import FundamentalAnalysisResult
from finrobot.sentiment_agent import SentimentAgentResult


class ReasoningResult(BaseModel):
    final_score: float          # 0-100 synthesised overall score
    recommendation: str         # "Strong Buy" / "Buy" / "Hold" / "Sell" / "Strong Sell"
    confidence: str             # "High" / "Medium" / "Low"
    chain_of_thought: str       # Full step-by-step reasoning text (deep, multi-step)
    summary: str                # Executive summary (5-8 sentences)
    contradictions_noted: str   # Fundamental vs sentiment conflict (empty if none)
    time_horizon: str           # "Short-term" / "Medium-term" / "Long-term"
    # Extended narrative sections for a richer deep-analysis output.
    # Optional so older cached reports still deserialise cleanly.
    investment_thesis: Optional[str] = ""
    bull_case: list[str] = []
    bear_case: list[str] = []
    catalysts: list[str] = []
    price_levels: Optional[str] = ""
    risk_management: Optional[str] = ""
    scenario_analysis: Optional[str] = ""
    final_verdict: Optional[str] = ""
    # Explicit risk-reward block — required for 10/10 institutional output.
    upside_pct: Optional[float] = None           # Base-case upside % from current price
    downside_pct: Optional[float] = None         # Bear-case downside % from current price
    risk_reward_ratio: Optional[str] = ""        # e.g. "1.1:1" or "2:1"
    risk_reward_commentary: Optional[str] = ""   # 2-3 sentences explaining the R:R
    # Source attribution — signals transparency and enables verification.
    data_sources: list[str] = []                 # e.g. ["Yahoo Finance — market data/TTM financials", ...]


# ───────────────────── post-processing helpers ─────────────────────

_MONTH_TO_FQ = {
    # Indian fiscal year runs Apr→Mar. FY26 = Apr-2025 → Mar-2026.
    # Q1 Apr-Jun | Q2 Jul-Sep | Q3 Oct-Dec | Q4 Jan-Mar.
    "january":  ("Q4", 0, "Jan–Mar"),
    "jan":      ("Q4", 0, "Jan–Mar"),
    "february": ("Q4", 0, "Jan–Mar"),
    "feb":      ("Q4", 0, "Jan–Mar"),
    "march":    ("Q4", 0, "Jan–Mar"),
    "mar":      ("Q4", 0, "Jan–Mar"),
    "april":    ("Q1", 1, "Apr–Jun"),
    "apr":      ("Q1", 1, "Apr–Jun"),
    "may":      ("Q1", 1, "Apr–Jun"),
    "june":     ("Q1", 1, "Apr–Jun"),
    "jun":      ("Q1", 1, "Apr–Jun"),
    "july":     ("Q2", 1, "Jul–Sep"),
    "jul":      ("Q2", 1, "Jul–Sep"),
    "august":   ("Q2", 1, "Jul–Sep"),
    "aug":      ("Q2", 1, "Jul–Sep"),
    "september":("Q2", 1, "Jul–Sep"),
    "sep":      ("Q2", 1, "Jul–Sep"),
    "sept":     ("Q2", 1, "Jul–Sep"),
    "october":  ("Q3", 1, "Oct–Dec"),
    "oct":      ("Q3", 1, "Oct–Dec"),
    "november": ("Q3", 1, "Oct–Dec"),
    "nov":      ("Q3", 1, "Oct–Dec"),
    "december": ("Q3", 1, "Oct–Dec"),
    "dec":      ("Q3", 1, "Oct–Dec"),
}

# Matches "October 2026", "Oct-2026", "Oct 2026", "Oct/2026"
_MONTH_YEAR_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|"
    r"October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept?|"
    r"Oct|Nov|Dec)[\s\-/]+(20\d{2})\b",
    re.IGNORECASE,
)


def _month_year_to_fiscal(month_name: str, year: int) -> str:
    """
    Convert a specific (month, calendar-year) to Indian-fiscal-quarter form.
    e.g. ('October', 2026) → 'Q3 FY27 (Oct–Dec 2026)'
         ('February', 2027) → 'Q4 FY27 (Jan–Mar 2027)'
    """
    key = month_name.strip().lower()
    if key not in _MONTH_TO_FQ:
        return f"{month_name} {year}"
    q, fy_offset, window = _MONTH_TO_FQ[key]
    fy = (year + fy_offset) % 100
    return f"{q} FY{fy:02d} ({window} {year})"


def _normalize_catalyst_dates(catalysts: list[str], today: Optional[datetime] = None) -> list[str]:
    """
    Post-process catalyst strings:
      • If a single calendar month appears paired with a year that is 12+
        months out from today, rewrite it as 'Q# FYxx (Mon–Mon YYYY)'.
      • If the year is within the next 12 months, leave it alone (month-level
        precision is acceptable for near-term events).
    """
    today = today or datetime.now()
    out: list[str] = []
    for raw in catalysts:
        if not isinstance(raw, str):
            out.append(raw)
            continue
        def _replace(m: re.Match) -> str:
            month, year_s = m.group(1), m.group(2)
            year = int(year_s)
            months_out = (year - today.year) * 12 + (1 - today.month)  # rough: month 1 of `year`
            if months_out < 12:
                return m.group(0)  # keep near-term specificity
            return _month_year_to_fiscal(month, year)
        out.append(_MONTH_YEAR_RE.sub(_replace, raw))
    return out


def run_reasoning_agent(
    fundamental_result: Optional[FundamentalAnalysisResult],
    sentiment_result: Optional[SentimentAgentResult],
    company_name: str,
    sector: str,
    tavily_news_summary: str = "",
    fii_dii_analysis_text: str = "",
) -> ReasoningResult:
    """
    Synthesise fundamental and sentiment agent outputs into a final recommendation.

    Degrades gracefully if either input is None.

    Args:
        fii_dii_analysis_text: Formatted FII/DII institutional-flow block
                               (from the stock_analysis.fii_dii_analysis
                               column). Surfaced as a dedicated section in
                               the prompt so the reasoning memo explicitly
                               factors smart-money accumulation/distribution
                               into its thesis.
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
  Reasoning:                 {fundamental_result.reasoning}
  Valuation Commentary:      {getattr(fundamental_result, 'valuation_commentary', '') or 'N/A'}
  Financial Health Commentary:{getattr(fundamental_result, 'financial_health_commentary', '') or 'N/A'}
  Growth Commentary:         {getattr(fundamental_result, 'growth_commentary', '') or 'N/A'}
  Peer Comparison:           {getattr(fundamental_result, 'peer_comparison', '') or 'N/A'}
  Moat Assessment:           {getattr(fundamental_result, 'moat_assessment', '') or 'N/A'}
  Capital Allocation:        {getattr(fundamental_result, 'capital_allocation', '') or 'N/A'}"""
    else:
        fund_block = "Fundamental Agent: DATA UNAVAILABLE (agent failed)"

    # Build sentiment block
    if sentiment_result:
        sent_block = f"""Future-Outlook Agent Results:
  Sentiment Score:       {sentiment_result.sentiment_score:.1f}/100
  Sentiment Label:       {sentiment_result.sentiment_label}
  Momentum:              {sentiment_result.sentiment_momentum}
  Theme Summary:         {sentiment_result.theme_summary}
  Key Drivers:           {sentiment_result.key_drivers}
  Anomalies:             {sentiment_result.anomalies_detected}
  Commentary:            {sentiment_result.llm_commentary}
  Analyst View:          {getattr(sentiment_result, 'analyst_view', '') or 'N/A'}
  Performance Highlights:{getattr(sentiment_result, 'performance_highlights', '') or 'N/A'}
  Growth Drivers Detail: {getattr(sentiment_result, 'growth_drivers_detail', []) or 'N/A'}
  Risk Factors Detail:   {getattr(sentiment_result, 'risk_factors_detail', []) or 'N/A'}
  Target/Upside:         {getattr(sentiment_result, 'target_price_snapshot', '') or 'N/A'}"""
    else:
        sent_block = "Future-Outlook Agent: DATA UNAVAILABLE (agent failed)"

    news_section = (
        f"\nFuture-Outlook Research Block (from DB):\n{tavily_news_summary[:2000]}"
        if tavily_news_summary else ""
    )

    fii_dii_section = (
        f"\nFII/DII Institutional Flow Block (from DB):\n{fii_dii_analysis_text.strip()[:3000]}"
        if fii_dii_analysis_text else ""
    )

    # Pre-compute score strings to avoid f-string format spec issues
    fund_score_str = f"{fundamental_result.overall_fundamental_score:.1f}" if fundamental_result else "N/A"
    sent_score_str = f"{sentiment_result.sentiment_score:.1f}" if sentiment_result else "N/A"

    system_prompt = (
        "You are a Chief Investment Officer writing an institutional-grade "
        "investment memo for a committee vote. You synthesise conflicting "
        "signals, identify the dominant investment thesis, and produce a "
        "clear, actionable recommendation with confidence level. You cover "
        "Indian equities (NSE/BSE) and are aware of sector-specific "
        "valuation norms. Your memo must be deep and specific — committee "
        "members reject shallow one-paragraph write-ups. Quote numbers, "
        "reason through trade-offs, and show your work.\n\n"
        "Institutional style rules (NON-NEGOTIABLE — a memo that violates "
        "any of these is rejected):\n"
        "1. Catalyst timing: use FISCAL QUARTERS for anything more than "
        "   one quarter out. Format: 'Q3 FY26 Earnings (Expected Oct–Dec "
        "   2026)'. Do NOT name a specific month for events 12+ months "
        "   away — the false precision ('Oct-2026') will be marked down "
        "   by the committee. A calendar-month window on the Indian "
        "   fiscal-year system is acceptable; a single calendar month is "
        "   not.\n"
        "2. Fiscal-year tags: every revenue / profit / EBITDA figure "
        "   must be tagged with its period (TTM / FY25 / FY26E). The "
        "   fundamental data block is labelled TTM — carry that tag. If "
        "   you also quote an FY-annual figure from the prior analyst "
        "   report, tag it 'FYxx annual'. Never quote the same metric "
        "   with two different numbers in the same memo unless each "
        "   carries a distinct fiscal tag.\n"
        "3. Directional comparisons ('larger than', 'dwarfs', 'trails') "
        "   between two numeric values must be arithmetically verified "
        "   before being written. If A < B, do not write that A dwarfs B. "
        "   When a peer outranks the subject on market cap, reframe the "
        "   subject's advantage using asset base, branch network, "
        "   deposit base, or distribution reach instead.\n"
        "3a. INDIAN NUMBERING (critical): 1 Trillion INR = 1 Lakh Crore "
        "    = 100,000 Crore. A market cap of 1,010,060 Cr is ₹10.10 "
        "    Trillion, NOT ₹1.01 Trillion. If the upstream fundamental "
        "    memo gives you a pre-formatted trillion value (e.g. "
        "    '₹10.10 T (₹10,10,060 Cr)'), quote it verbatim — do not "
        "    recompute. Never divide a crore value by 1,000,000 to get "
        "    trillions; the correct divisor is 100,000.\n"
        "4. Risk/Reward: you MUST compute and state an explicit Risk-to-"
        "   Reward ratio using the Base-case upside and Bear-case "
        "   downside. Format the ratio as 'X:1' (e.g. '1.1:1', '2:1'). "
        "   Never ship scenario analysis without the ratio.\n"
        "5. Source attribution: every memo MUST end with a compact "
        "   data_sources list naming the specific data providers used "
        "   (e.g. 'Yahoo Finance — TTM financials & market data', "
        "   'screener.in — FY-annual income statement', 'NSE — shareholding "
        "   pattern', 'TradingView — price action'). Generic names "
        "   without a stated role are not acceptable.\n"
        "6. Naming consistency: introduce the subject ONCE as 'Full Name "
        "   (TICKER)' and thereafter use the ticker only. Do not "
        "   alternate between full name and ticker across sections."
    )

    canonical_ticker = getattr(fundamental_result, "__dict__", {})
    canonical_ticker = ""
    # Best-effort ticker extraction — the reasoning agent doesn't take
    # company_data directly, so fall back to trailing '(TICKER)' in name.
    _m = re.search(r"\(([A-Z0-9\.\-]{1,20})\)\s*$", company_name or "")
    if _m:
        canonical_ticker = _m.group(1)

    user_prompt = f"""Company:          {company_name}
Canonical Ticker: {canonical_ticker or '(derive from Company; use consistently after first mention)'}
Sector:  {sector or 'N/A'}
{news_section}
{fii_dii_section}

{fund_block}

{sent_block}

Produce a DEEP, INSTITUTIONAL-GRADE synthesis grounded in THREE data sources: the Fundamental Agent output, the Future-Outlook Agent output, AND the FII/DII Institutional Flow block. Do not be concise — expand every section, and explicitly reference FII/DII holdings/trends when they support or contradict the fundamental or sentiment view.

chain_of_thought: Walk through the following 11 steps as one long paragraph (or clearly-delimited steps). EACH step must be 2–4 sentences, cite numbers, and lead into the next.
  Step 1: Summarise the fundamental picture — valuation, balance-sheet, growth scores with the specific multiples behind them.
  Step 2: Summarise the future-outlook / sentiment picture — dominant themes, momentum, analyst view.
  Step 3: Summarise the FII/DII institutional-flow picture — current FII%, DII%, 1Q/4Q deltas, and the institutional score/recommendation from the block above. Call out whether foreign vs domestic money is aligned or diverging.
  Step 4: Explicitly identify any contradictions (e.g. cheap valuation but deteriorating outlook; strong growth but stretched multiples; fundamentals positive but FIIs exiting).
  Step 5: Reason about sector-specific context — what's typical for this sector's multiples, cycle position, regulatory backdrop.
  Step 6: Weigh the balance-sheet evidence — is leverage a helper or a drag here?
  Step 7: Weigh growth evidence — is growth durable or at risk of mean-reversion?
  Step 8: Weigh the catalyst slate — what could re-rate the stock up or down in the next 6–18 months? Include institutional-flow catalysts (e.g. FII re-accumulation, DII distribution).
  Step 9: Stress-test the thesis — what breaks the call? What data would change your mind?
  Step 10: Assign confidence and time horizon.
  Step 11: State the final recommendation and explain how the blended score maps to it.

summary: 5–8 sentences — the executive committee-brief version, citing the final score and the two strongest drivers plus the two biggest risks.

investment_thesis: 4–6 sentences — the ONE-THESIS statement. What is the core reason to own (or avoid) this stock?

bull_case: 5–8 bullet points — each a specific upside driver with numbers.
bear_case: 5–8 bullet points — each a specific downside risk with numbers.
catalysts: 4–7 upcoming catalysts (earnings, policy, launches, re-rating triggers, macro events). Tag each with approximate timing using FISCAL QUARTERS for events more than one quarter away — e.g. "Q3 FY26 Earnings (Expected Oct–Dec 2026)", "RBI policy review (Q1 FY27)". Never pin a single calendar month to an event 12+ months out.
price_levels: 2–4 sentences on entry zones, support/resistance, target price range (use numbers from the data), and implied upside/downside.
risk_management: 3–5 sentences on position sizing, stop-loss logic, and what to monitor.
scenario_analysis: 3–5 sentences covering Bull / Base / Bear outcomes with approximate target prices or outcome ranges. Express Bull/Base/Bear as explicit +/− % moves from the current price.
upside_pct: numeric Base-case upside expressed as a percentage from current price (e.g. 8.0 for +8%). Must be consistent with scenario_analysis.
downside_pct: numeric Bear-case downside expressed as a percentage from current price (always a POSITIVE number representing the magnitude of the drop, e.g. 7.0 for a 7% drawdown).
risk_reward_ratio: the explicit ratio of Base-case upside to Bear-case downside, formatted 'X:1'. Compute as round(upside_pct / downside_pct, 1) and render as e.g. '1.1:1' or '2:1'. If you prefer to anchor on the Bull case instead, state that explicitly in the commentary.
risk_reward_commentary: 2–3 sentences — one line stating the ratio in words ("Based on Base Case upside of ~8% and Bear Case downside of ~7%, the Risk-Reward Ratio is approximately 1.1:1"), one line on whether that ratio is attractive vs. sector norms, and one line on what would flip the skew.
data_sources: list of 3–7 strings, each naming a specific data provider AND its role — e.g. "Yahoo Finance — TTM financial statements & market data", "screener.in — FY-annual income statement & shareholding pattern", "NSE — option chain & FII/DII flows", "TradingView — technical levels & price action", "SimplyWall.st — peer valuation snapshot". Never submit a memo without this list populated.
final_verdict: 2–3 sentences — the crisp, quotable one-liner a PM could paste into a memo.
contradictions_noted: detailed paragraph (3–5 sentences) describing any fundamental-vs-sentiment conflict and how you resolved it.

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

Return ONLY valid JSON (no markdown fences, no trailing commas):
{{
  "final_score": <float 0-100>,
  "recommendation": "<Strong Buy|Buy|Hold|Sell|Strong Sell>",
  "confidence": "<High|Medium|Low>",
  "chain_of_thought": "<10-step deep reasoning>",
  "summary": "<5-8 sentence executive summary>",
  "contradictions_noted": "<3-5 sentences>",
  "time_horizon": "<Short-term|Medium-term|Long-term>",
  "investment_thesis": "<4-6 sentences>",
  "bull_case": ["<point with numbers>", ...],
  "bear_case": ["<point with numbers>", ...],
  "catalysts": ["<catalyst with timing>", ...],
  "price_levels": "<2-4 sentences>",
  "risk_management": "<3-5 sentences>",
  "scenario_analysis": "<3-5 sentences Bull/Base/Bear>",
  "upside_pct": <float — Base-case upside %>,
  "downside_pct": <float — Bear-case downside % as a positive magnitude>,
  "risk_reward_ratio": "<e.g. '1.1:1'>",
  "risk_reward_commentary": "<2-3 sentences>",
  "data_sources": ["<Provider — role>", ...],
  "final_verdict": "<2-3 sentence one-liner>"
}}"""

    try:
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.18,
            max_tokens=5000,
        )
        raw = response.choices[0].message.content.strip()
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()
        data = json.loads(raw)

        # ── Post-processing guardrails ───────────────────────────────
        # 1. Rewrite any single calendar-month-plus-year that is 12+ months
        #    out into fiscal-quarter form. The LLM is instructed to avoid
        #    this, but we harden the output against drift.
        if isinstance(data.get("catalysts"), list):
            data["catalysts"] = _normalize_catalyst_dates(data["catalysts"])

        # 2. Backfill the risk-reward ratio if the LLM omitted it but
        #    provided both upside_pct and downside_pct. Keeps the field
        #    populated even on partial outputs.
        up = data.get("upside_pct")
        down = data.get("downside_pct")
        rr = data.get("risk_reward_ratio")
        if (not rr or not str(rr).strip()) and isinstance(up, (int, float)) and isinstance(down, (int, float)) and down > 0:
            data["risk_reward_ratio"] = f"{round(up / down, 1)}:1"

        return ReasoningResult(**data)
    except Exception as e:
        raise RuntimeError(f"ReasoningAgent LLM call failed: {e}") from e
