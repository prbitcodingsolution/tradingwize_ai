from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from datetime import datetime


class StockValidation(BaseModel):
    """Model for stock validation response"""
    is_valid: bool
    stock_symbol: Optional[str] = None
    stock_name: Optional[str] = None
    variants: List[Dict[str, str]] = Field(default_factory=list)
    needs_clarification: bool = False
    message: str


class CompanySnapshot(BaseModel):
    """Model for company snapshot information"""
    company_name: Optional[str] = None
    ticker_symbol: Optional[str] = None
    exchange: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    headquarters: Optional[str] = None
    founded_year: Optional[str] = None
    ceo: Optional[str] = None
    employees: Optional[int] = None
    website: Optional[str] = None


class BusinessOverview(BaseModel):
    """Model for business overview"""
    description: Optional[str] = None
    main_products: List[str] = Field(default_factory=list)
    revenue_sources: List[str] = Field(default_factory=list)
    geographic_presence: Optional[str] = None
    growth_segments: List[str] = Field(default_factory=list)


class FinancialData(BaseModel):
    """Model for comprehensive financial metrics"""
    # Income Statement
    revenue: Optional[float] = None
    net_profit: Optional[float] = None
    ebitda: Optional[float] = None
    eps: Optional[float] = None
    dividend_yield: Optional[float] = None
    payout_ratio: Optional[float] = None
    
    # Balance Sheet
    total_assets: Optional[float] = None
    total_liabilities: Optional[float] = None
    debt_to_equity: Optional[float] = None
    cash_balance: Optional[float] = None
    total_debt: Optional[float] = None
    
    # Cash Flow
    operating_cash_flow: Optional[float] = None
    free_cash_flow: Optional[float] = None
    
    # Valuation
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    peg_ratio: Optional[float] = None
    enterprise_value: Optional[float] = None
    ev_ebitda: Optional[float] = None
    
    # Margins
    profit_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    gross_margin: Optional[float] = None


class MarketData(BaseModel):
    """Model for comprehensive market information"""
    current_price: Optional[float] = None
    week_52_high: Optional[float] = None
    week_52_low: Optional[float] = None
    overall_high: Optional[float] = None  # New field for overall high
    overall_low: Optional[float] = None   # New field for overall low
    percentage_change_from_high: Optional[float] = None  # New field for % change from high
    max_drop_after_high: Optional[float] = None  # Maximum drop percentage after reaching overall high
    market_cap: Optional[float] = None
    volume: Optional[int] = None
    avg_volume: Optional[int] = None
    beta: Optional[float] = None
    
    # Holdings
    promoter_holding: Optional[float] = None
    fii_holding: Optional[float] = None
    dii_holding: Optional[float] = None
    
    # Price History
    price_history: Dict[str, float] = Field(default_factory=dict)
    
    # Performance
    day_change: Optional[float] = None
    week_change: Optional[float] = None
    month_change: Optional[float] = None
    month_6_change: Optional[float] = None
    year_change: Optional[float] = None
    year_5_cagr: Optional[float] = None
    
    # Sector
    sector: Optional[str] = None
    sector_performance: Optional[str] = None
    
    # Competitors
    competitors: List[Dict[str, Any]] = Field(default_factory=list)


class SWOTAnalysis(BaseModel):
    """Model for SWOT Analysis"""
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    opportunities: List[str] = Field(default_factory=list)
    threats: List[str] = Field(default_factory=list)


class BankingMetrics(BaseModel):
    """Banking-specific financial metrics.

    Populated only for stocks classified as banks (via
    `utils.sector_helpers.is_banking_sector`). For non-banks this is None on
    CompanyData. All fields optional because screener.in exposes different
    subsets depending on the bank.
    """
    # Profitability
    net_interest_margin: Optional[float] = Field(None, description="NIM % — spread between interest earned and paid")
    return_on_assets: Optional[float] = Field(None, description="ROA % — net profit / total assets")
    return_on_equity: Optional[float] = Field(None, description="ROE % — net profit / shareholder equity")
    cost_to_income: Optional[float] = Field(None, description="Operating costs / operating income %")

    # Asset quality
    gross_npa: Optional[float] = Field(None, description="Gross NPA % — non-performing loans / total loans")
    net_npa: Optional[float] = Field(None, description="Net NPA % — gross NPA minus provisions")
    provision_coverage: Optional[float] = Field(None, description="PCR % — provisions / gross NPAs")

    # Funding & capital
    casa_ratio: Optional[float] = Field(None, description="CASA % — current + savings deposits / total deposits")
    capital_adequacy: Optional[float] = Field(None, description="CAR % — regulatory capital / risk-weighted assets")
    credit_deposit: Optional[float] = Field(None, description="C/D % — advances / deposits")


class CompanyData(BaseModel):
    """Comprehensive company data model"""
    symbol: str
    name: str
    snapshot: CompanySnapshot
    business_overview: BusinessOverview
    financials: FinancialData
    market_data: MarketData
    swot: SWOTAnalysis
    news: List[Dict[str, str]] = Field(default_factory=list)
    announcements: List[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.now)
    finrobot_report: Optional[Any] = Field(default=None, description="FinRobotReport from the three-agent pipeline")
    banking_metrics: Optional[BankingMetrics] = Field(default=None, description="Banking-specific ratios (None for non-banks)")


class CompanyReport(BaseModel):
    """Model for CEO/CFO pitch report"""
    company_name: str
    strengths: List[str]
    growth_story: str
    business_strategy: str
    financial_health: str
    projections: str
    risks: List[str]
    mitigation_plans: List[str]


class ScenarioAnalysis(BaseModel):
    """Model for what-if scenario analysis"""
    scenario: str
    impact_description: str
    financial_impact: Dict[str, str]
    recommendations: List[str]


class Summary(BaseModel):
    """Final summary model"""
    company_name: str
    key_highlights: List[str]
    strengths: List[str]
    weaknesses: List[str]
    future_outlook: str
    recommendation: str


class QuarterlyHolding(BaseModel):
    """FII/DII holding for a single quarter."""
    quarter: str
    fii_pct: float
    dii_pct: float
    promoter_pct: Optional[float] = None
    public_pct: Optional[float] = None


class FIIDIISentiment(BaseModel):
    """Complete FII/DII institutional sentiment analysis for a stock."""
    symbol: str
    company_name: Optional[str] = None

    # Current snapshot
    current_fii_pct: float
    current_dii_pct: float
    current_total_institutional: float

    # Trend data (oldest first)
    quarterly_history: List[QuarterlyHolding] = Field(default_factory=list)

    # Trend direction
    fii_trend: str
    dii_trend: str
    fii_change_1q: Optional[float] = None
    fii_change_4q: Optional[float] = None
    dii_change_1q: Optional[float] = None
    dii_change_4q: Optional[float] = None

    # Scoring
    institutional_sentiment_score: float
    sentiment_label: str

    # Recommendation
    recommendation: str
    recommendation_color: str
    reasoning: List[str] = Field(default_factory=list)

    # Metadata
    data_source: str
    data_freshness: str
    timestamp: datetime


# ── Option Chain & OI Analysis Models ──

class OptionStrike(BaseModel):
    """Single strike row from the option chain table."""
    strike: float
    call_oi: int = 0
    call_chng_oi: int = 0
    put_oi: int = 0
    put_chng_oi: int = 0
    is_max_call_oi: bool = False
    is_max_put_oi: bool = False
    is_atm: bool = False
    call_oi_change_pct: Optional[float] = None
    put_oi_change_pct: Optional[float] = None


class OIShiftSignal(BaseModel):
    """Tracks where OI concentration is shifting."""
    direction: str
    description: str
    strength: str
    score_contribution: int = 0


class OIAnalysis(BaseModel):
    """Complete OI-based market analysis output."""
    symbol: str
    expiry_date: str
    underlying_price: float
    max_call_oi_strike: float
    max_put_oi_strike: float
    max_pain_strike: float
    put_call_ratio: float
    pcr_label: str
    call_oi_shift: OIShiftSignal
    put_oi_shift: OIShiftSignal
    key_support: float
    key_resistance: float
    range_low: float
    range_high: float
    market_bias: str
    bias_strength: str
    recommendation: str
    recommendation_color: str
    verdict_points: List[str]
    confidence: str
    total_signal_score: int = 0
    has_contradiction: bool = False
    pcr_score: int = 0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class OptionChainData(BaseModel):
    """Complete option chain fetch result — raw data + analysis."""
    symbol: str
    expiry_date: str
    underlying_price: float
    available_expiries: List[str]
    strikes: List[OptionStrike]
    analysis: OIAnalysis
    data_source: str = "nse_api"
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ─────────────────────────────────────────────────────────
# Enhanced fundamental analysis (see utils/fundamental_analyzer.py)
# ─────────────────────────────────────────────────────────
#
# Every sub-section returns its own model wrapped in a `SectionResult` so the
# renderer can degrade gracefully when a source is unavailable (Tavily down,
# screener.in blocking, etc.) without breaking the whole card.


class SectionStatus(BaseModel):
    """Common per-section status block — every fundamental sub-analysis
    carries one of these so the UI can show 'data not available' or a
    confidence badge instead of an empty/blank section."""
    available: bool = False
    confidence: str = "low"  # "high" | "medium" | "low"
    notes: str = ""
    sources: List[str] = Field(default_factory=list)


class FinancialTrendPoint(BaseModel):
    """One year (or quarter) of headline P&L / balance-sheet metrics."""
    period: str  # e.g. "FY21" or "Mar 2024"
    revenue: Optional[float] = None
    ebitda: Optional[float] = None
    pat: Optional[float] = None  # profit after tax
    eps: Optional[float] = None
    debt: Optional[float] = None
    roe: Optional[float] = None
    roce: Optional[float] = None
    operating_margin: Optional[float] = None


class CorporateAction(BaseModel):
    period: str
    action_type: str  # dividend / split / buyback / bonus
    detail: str


class ShareholdingSnapshot(BaseModel):
    quarter: str
    promoter: Optional[float] = None
    fii: Optional[float] = None
    dii: Optional[float] = None
    public: Optional[float] = None
    government: Optional[float] = None


class FinancialTrend(BaseModel):
    """5-year financial trend block (item 1 in the client brief)."""
    status: SectionStatus = Field(default_factory=SectionStatus)
    yearly: List[FinancialTrendPoint] = Field(default_factory=list)
    quarterly: List[FinancialTrendPoint] = Field(default_factory=list)
    shareholding: List[ShareholdingSnapshot] = Field(default_factory=list)
    corporate_actions: List[CorporateAction] = Field(default_factory=list)


class DirectorProfile(BaseModel):
    """One person on the board / promoter group (item 2)."""
    name: str
    designation: Optional[str] = None
    since_year: Optional[str] = None  # year (or "since YYYY") they took the current role
    din: Optional[str] = None
    background: Optional[str] = None
    other_directorships: List[str] = Field(default_factory=list)
    source_links: List[str] = Field(default_factory=list)


class DirectorBlock(BaseModel):
    status: SectionStatus = Field(default_factory=SectionStatus)
    directors: List[DirectorProfile] = Field(default_factory=list)


class PoliticalConnection(BaseModel):
    """Item 3 — best-effort flag, NOT authoritative."""
    subject: str  # director name or "company"
    finding: str
    category: Optional[str] = None
    # category: one of "government_ownership", "political_appointment",
    # "donation", "affiliation", "controversy", "regulatory", "contracts",
    # or "other" — drives badge color + grouping in the renderer.
    confidence: str = "low"  # high|medium|low
    source_links: List[str] = Field(default_factory=list)


class PoliticalBlock(BaseModel):
    status: SectionStatus = Field(default_factory=SectionStatus)
    connections: List[PoliticalConnection] = Field(default_factory=list)


class NewsHeadline(BaseModel):
    """Item 4 — headline + LLM-tagged sentiment / category."""
    title: str
    publisher: str = ""
    link: str = ""
    summary: str = ""
    published: Optional[str] = None
    sentiment: str = "neutral"  # positive / negative / neutral
    category: Optional[str] = None  # earnings / regulatory / governance / management / macro / other


class NewsBlock(BaseModel):
    status: SectionStatus = Field(default_factory=SectionStatus)
    items: List[NewsHeadline] = Field(default_factory=list)
    positive: int = 0
    negative: int = 0
    neutral: int = 0


class LegalCase(BaseModel):
    """Item 5 — SEBI order / SFIO / court / defaulter flag. Best-effort."""
    subject: str  # company or director name
    case_type: str  # SEBI / SFIO / court / wilful_defaulter / other
    summary: str
    published: Optional[str] = None
    confidence: str = "low"
    source_links: List[str] = Field(default_factory=list)


class LegalBlock(BaseModel):
    status: SectionStatus = Field(default_factory=SectionStatus)
    cases: List[LegalCase] = Field(default_factory=list)


class PromoterInvestment(BaseModel):
    """Item 6 — a company the promoter / director has invested in."""
    investor_name: str  # director / promoter
    company_name: str
    stake_percent: Optional[float] = None
    listed: bool = False
    ticker: Optional[str] = None
    investment_value: Optional[str] = None
    source_links: List[str] = Field(default_factory=list)


class PortfolioPerformance(BaseModel):
    """Item 7 — performance of a portfolio company (only when listed)."""
    company_name: str
    ticker: Optional[str] = None
    last_price: Optional[float] = None
    return_1y_pct: Optional[float] = None
    return_3y_pct: Optional[float] = None
    revenue_trend: Optional[str] = None  # "growing" / "flat" / "declining"
    note: Optional[str] = None


class InvestmentsBlock(BaseModel):
    """Combined item 6 + 7."""
    status: SectionStatus = Field(default_factory=SectionStatus)
    investments: List[PromoterInvestment] = Field(default_factory=list)
    performance: List[PortfolioPerformance] = Field(default_factory=list)


class PledgePoint(BaseModel):
    """Item 8 — one quarter's pledge snapshot."""
    quarter: str
    percent_pledged: Optional[float] = None
    lender: Optional[str] = None


class PledgeEvent(BaseModel):
    """Item 8 — one SAST/PIT pledge filing from NSE.

    Sourced from `/api/corporates-pit` so the values are authoritative
    exchange disclosures, not text-extracted estimates. Empty for stocks
    with no recent SAST filings (most clean large-caps).
    """
    acquirer: str
    transaction_type: str  # "Pledge" / "Sell" / etc.
    mode: str  # "Pledge Creation" / "Pledge Release" / "Pledge Invocation"
    shares: Optional[int] = None
    value: Optional[int] = None  # rupees
    before_pct: Optional[float] = None
    after_pct: Optional[float] = None
    date: Optional[str] = None  # event date
    intimation_date: Optional[str] = None  # filing date
    category: Optional[str] = None  # promoter / employee / etc.
    xbrl_url: Optional[str] = None


class PledgeBlock(BaseModel):
    status: SectionStatus = Field(default_factory=SectionStatus)
    current_percent: Optional[float] = None
    risk_level: str = "unknown"  # low / medium / high / critical / unknown
    trend: List[PledgePoint] = Field(default_factory=list)
    events: List[PledgeEvent] = Field(default_factory=list)  # NSE SAST/PIT history


class FundamentalAnalysis(BaseModel):
    """Top-level aggregator returned by
    `utils.fundamental_analyzer.analyze_fundamentals`."""
    symbol: str
    stock_name: Optional[str] = None
    analysis_version: str = "v1"
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    cached: bool = False  # True when returned from the DB cache rather than freshly fetched
    financials: FinancialTrend = Field(default_factory=FinancialTrend)
    directors: DirectorBlock = Field(default_factory=DirectorBlock)
    political: PoliticalBlock = Field(default_factory=PoliticalBlock)
    news: NewsBlock = Field(default_factory=NewsBlock)
    legal: LegalBlock = Field(default_factory=LegalBlock)
    investments: InvestmentsBlock = Field(default_factory=InvestmentsBlock)
    pledge: PledgeBlock = Field(default_factory=PledgeBlock)
    overall_notes: List[str] = Field(default_factory=list)
