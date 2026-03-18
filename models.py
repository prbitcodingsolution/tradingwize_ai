from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
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
