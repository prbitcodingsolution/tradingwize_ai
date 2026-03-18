from model_config import get_model, get_client, perplexity_model
from dataclasses import dataclass
from pydantic_ai import Agent, RunContext
from yfinance import Ticker
from typing import Optional
from models import (
    StockValidation, CompanyData, CompanyReport, 
    ScenarioAnalysis, Summary
)
from tools import StockTools

@dataclass
class TraderAgentDependencies:
    stock_symbol: Optional[str] = None
    stock_name: Optional[str] = None
    company_data: Optional[CompanyData] = None
    report_generated: bool = False

model = get_model()


trader_system_prompt = """
You are financial market expert. Your task is to analyze the stock market and provide insights to the user.

when user greet reply them with a friendly greeting and ask them what they want to know.

When user ask to analyze a stock, first call the validate stock tool for validating the stock name and getting the yfinance ticker symbol.

If there is more than one match, ask the user to be more specific.

If there is no match, ask the user to try again.

If there is only one match or user finalize the stock name from if there are multiple stock found, then call the analyse stock tool to get the stock data and reply with same response you get from the tool.

The response will include the Company Snapshot, Business Overview, SWOT Analysis, Market Data, Financial Data, price performance, compatitor comparision, News and Annoucements, Expert Opinions, shart tank pitch. 

You have send the response as it is.
"""

trader_agent = Agent(
    model=model,
    system_prompt=trader_system_prompt,
    output_type=str,
    deps_type = TraderAgentDependencies
)

@trader_agent.tool
async def validate_stock(ctx: RunContext[TraderAgentDependencies] ,stock_name: str) -> str:
    """
    
    
    """
    validating_agent = Agent(
        model=perplexity_model,
        system_prompt="""You are an expert financial market assistant. Your task is to identify the correct stock "
                "ticker symbol for a given company name or query. \n\n"
                "1. SEARCH: Use your search capabilities to find the company and its ticker symbol. "
                "Prioritize NSE/BSE (Indian markets) if the query implies an Indian company or is ambiguous. "
                "Otherwise check major global exchanges (NASDAQ, NYSE).\n"
                "2. VALIDATE: Ensure the ticker is valid for use with yfinance (e.g., 'RELIANCE.NS', 'AAPL', 'TCS.BO').\n"
                "3. MATCHING:\n"
                "   - If you find a SINGLE clear match, set is_valid=True, provide stock_symbol and stock_name.\n"
                "   - If you find MULTIPLE plausible matches (e.g. 'Tata' -> Tata Motors, Tata Steel, Tata Power), "
                "set is_valid=False and list them in 'variants'. Provide a helpful message listing the options with their symbols.\n"
                "   - If NO match is found, set is_valid=False and explain why in the message.\n"
                "4. OUTPUT: Return the result strictly in the requested JSON format.""",
        output_type=str,
        deps_type = TraderAgentDependencies
    )

    prompt = f"""Find the listed stock name and yfinance ticker symbol for the given stock name.
    If there are mulitple stock name listed based on the given stock name then give their name and ticker symbol and give the response with numbering.
    If there is no match then return "No match found".
    The stock name:- {stock_name}
    """
    validation = await validating_agent.run(prompt)
    return validation.output


def generate_shark_tank_pitch(company_data: CompanyData) -> str:
    """
    Generate a Shark Tank pitch with safe None value handling
    
    Args:
        company_data: CompanyData object
    
    Returns:
        Formatted Shark Tank pitch string
    """
    # Safely get values with defaults
    company_name = company_data.name if company_data.name else "this company"
    symbol = company_data.symbol if company_data.symbol else "N/A"
    sector = company_data.market_data.sector if company_data.market_data.sector else "market"
    
    # Determine currency and formatters
    is_indian = company_data.symbol.endswith('.NS') or company_data.symbol.endswith('.BO')
    currency_symbol = '₹' if is_indian else '$'
    
    # Safely format market cap
    market_cap_str = "N/A"
    if company_data.market_data.market_cap:
        if is_indian:
             market_cap_str = f"₹{company_data.market_data.market_cap/1e7:.2f} Cr"
        else:
             market_cap_str = f"${company_data.market_data.market_cap/1e9:.2f} B"
    
    # Safely format revenue
    revenue_str = "N/A"
    if company_data.financials.revenue:
        if is_indian:
             revenue_str = f"₹{company_data.financials.revenue/1e7:.2f} Cr"
        else:
             revenue_str = f"${company_data.financials.revenue/1e9:.2f} B"
    
    # Safely format net profit
    net_profit_str = "N/A"
    if company_data.financials.net_profit:
         if is_indian:
             net_profit_str = f"₹{company_data.financials.net_profit/1e7:.2f} Cr"
         else:
             net_profit_str = f"${company_data.financials.net_profit/1e9:.2f} B"
    
    # Safely format free cash flow
    fcf_str = "N/A"
    if company_data.financials.free_cash_flow:
        if is_indian:
             fcf_str = f"₹{company_data.financials.free_cash_flow/1e7:.2f} Cr"
        else:
             fcf_str = f"${company_data.financials.free_cash_flow/1e9:.2f} B"
    
    # Safely format current price
    price_str = "N/A"
    if company_data.market_data.current_price:
        price_str = f"{currency_symbol}{company_data.market_data.current_price:.2f}"
    
    return f"""🦈 **SHARK TANK PITCH**

Hello Sharks! I'm here today representing {company_name}, and I'm excited to share why we represent an incredible investment opportunity in the {sector} sector.

Let me tell you our story. We're a major player trading under {symbol}, and we've built something truly special with a market capitalization of {market_cap_str}. What makes us unique is our position in the {sector} industry, where we've established ourselves as a reliable and innovative force.

Our business model is solid and proven. We generate revenue through multiple streams, serving both domestic and international markets. We focus on delivering exceptional value to our customers while maintaining operational excellence. The numbers speak for themselves - we're generating {revenue_str} in revenue and converting that into {net_profit_str} in net profit.

But here's what really excites me, Sharks - our cash generation capability. We're producing {fcf_str} in free cash flow, giving us tremendous flexibility to invest in growth, return capital to shareholders, or strengthen our balance sheet.

Looking at our competitive position, we operate in a dynamic market where differentiation is key. Our strengths lie in our established market presence, strong financial fundamentals, and proven track record of execution. While we face challenges like market volatility and competitive pressures, we see significant opportunities for growth through strategic initiatives and market expansion.

From a financial perspective, our current trading price of {price_str} represents what I believe is excellent value for investors. We've demonstrated resilience through various market conditions while maintaining our strategic focus on long-term value creation.

Our investment thesis is compelling: we're a profitable company with strong cash generation, operating in a sector with long-term growth potential. We have the financial flexibility to invest in growth opportunities while maintaining a strong balance sheet. Our management team has a proven track record of creating shareholder value through disciplined capital allocation and operational excellence.

Of course, like any investment, there are risks to consider. Market volatility, regulatory changes, and competitive dynamics all present challenges. However, our diversified business model, strong financial position, and experienced management team position us well to navigate these challenges and capitalize on opportunities.

Looking ahead, our growth strategy focuses on expanding our market presence, investing in innovation, and optimizing our operations for maximum efficiency. We're committed to delivering sustainable returns to our shareholders while building long-term value for all stakeholders.

So, Sharks, are you ready to invest in {company_name}? We offer a compelling combination of financial strength, market position, and growth potential. I'm ready to answer any questions you have about our operations, strategy, or financial outlook. What do you say?"""


@trader_agent.tool
async def analyse_stock(ctx: RunContext[TraderAgentDependencies], stock_symbol: str) -> str:
    """
    Analyses the stock by fetching comprehensive data, generating a report, and a Shark Tank pitch.
    """
    # 1. Fetch comprehensive real-time company data
    company_data = StockTools.get_realtime_data(stock_symbol)
    
    # 2. Format the data into a comprehensive report
    # This includes: Company Snapshot, Business Overview, Financial Metrics, Market Data, 
    # Price Performance, Competitor Comparison, SWOT Analysis, News & Announcements,
    # and Expert Opinion (which uses an LLM to generate analysis).
    report = StockTools.format_data_for_report(company_data)
    
    # 3. Generate the Shark Tank pitch
    pitch = generate_shark_tank_pitch(company_data)
    
    # 4. Combine report and pitch
    full_response = report + "\n\n" + pitch
    
    # Store data in context if needed (optional, depending on future use)
    ctx.deps.company_data = company_data
    ctx.deps.report_generated = True
    
    return full_response
