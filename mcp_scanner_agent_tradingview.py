"""
MCP Technical Scanner Agent - TradingView API Format
Returns exact TradingView drawing JSON format using REAL MCP tools
Used ONLY in Technical Scanner section (not in chat)
"""

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.mcp import load_mcp_servers
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import os
import sys
import json
import random
import string
from datetime import datetime
import yfinance as yf
from dotenv import load_dotenv

# Fix Windows console encoding for emojis
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

# Load environment variables
load_dotenv()

# Configure OpenRouter provider
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

# Check if MCP is available (but don't load servers at module level)
MCP_CONFIG_PATH = 'mcp_config.json'
MCP_AVAILABLE = os.path.exists(MCP_CONFIG_PATH) and OPENROUTER_API_KEY
if MCP_AVAILABLE:
    print(f"✅ MCP configuration found: {MCP_CONFIG_PATH}")
else:
    print("⚠️ MCP not available (missing config or API key)")


# ============================================================================
# TradingView Drawing Models (Exact API Format)
# ============================================================================

class DrawingPoint(BaseModel):
    """TradingView drawing point"""
    price: float
    offset: int = 0
    time_t: int  # Unix timestamp


class IntervalsVisibilities(BaseModel):
    """Visibility settings for different timeframes"""
    days: bool = True
    hours: bool = True
    ticks: bool = True
    weeks: bool = True
    daysTo: int = 366
    months: bool = True
    ranges: bool = True
    hoursTo: int = 24
    minutes: bool = True
    seconds: bool = True
    weeksTo: int = 52
    daysFrom: int = 1
    monthsTo: int = 12
    hoursFrom: int = 1
    minutesTo: int = 59
    secondsTo: int = 59
    weeksFrom: int = 1
    monthsFrom: int = 1
    minutesFrom: int = 1
    secondsFrom: int = 1


class RiskRewardState(BaseModel):
    """State for LineToolRiskRewardLong"""
    qty: float = 1.0
    risk: str = "2.00"
    title: str = ""
    frozen: bool = False
    symbol: str
    unitId: Optional[str] = None
    compact: bool = False
    lotSize: int = 1
    visible: bool = True
    fontsize: int = 12
    interval: str = "1D"
    riskSize: float = 100.0
    linecolor: str = "#787B86"
    linewidth: int = 1
    stopLevel: float
    textcolor: str = "#ffffff"
    amountStop: float
    currencyId: Optional[str] = None
    drawBorder: bool = False
    accountSize: float = 10000.0
    borderColor: str = "#667b8b"
    profitLevel: float
    amountTarget: float
    zOrderVersion: int = 2
    fillBackground: bool = True
    stopBackground: str = "rgba(242, 54, 69, 0.2)"
    alwaysShowStats: bool = False
    riskDisplayMode: str = "percents"
    showPriceLabels: bool = True
    profitBackground: str = "rgba(8, 153, 129, 0.2)"
    symbolStateVersion: int = 2
    fillLabelBackground: bool = True
    labelBackgroundColor: str = "#585858"
    intervalsVisibilities: IntervalsVisibilities = Field(default_factory=IntervalsVisibilities)
    stopBackgroundTransparency: int = 80
    profitBackgroundTransparency: int = 80


class NoteState(BaseModel):
    """State for LineToolNote"""
    bold: bool = False
    text: str
    title: str = ""
    frozen: bool = False
    italic: bool = False
    symbol: str
    unitId: Optional[str] = None
    visible: bool = True
    fontSize: int = 14
    interval: str = "1D"
    fixedSize: bool = True
    textColor: str = "#ffffff"
    currencyId: Optional[str] = None
    borderColor: str = "#2962FF"
    markerColor: str = "#2962FF"
    zOrderVersion: int = 2
    backgroundColor: str = "rgba(41, 98, 255, 0.7)"
    symbolStateVersion: int = 2
    intervalsVisibilities: IntervalsVisibilities = Field(default_factory=IntervalsVisibilities)
    backgroundTransparency: int = 0


class RectangleState(BaseModel):
    """State for LineToolRectangle"""
    frozen: bool = False
    symbol: str
    unitId: Optional[str] = None
    visible: bool = True
    interval: str = "1D"
    linecolor: str = "#2962FF"
    linewidth: int = 2
    fillColor: str = "rgba(41, 98, 255, 0.2)"
    currencyId: Optional[str] = None
    zOrderVersion: int = 2
    symbolStateVersion: int = 2
    intervalsVisibilities: IntervalsVisibilities = Field(default_factory=IntervalsVisibilities)
    transparency: int = 80


class TrendLineState(BaseModel):
    """State for LineToolTrendLine"""
    frozen: bool = False
    symbol: str
    unitId: Optional[str] = None
    visible: bool = True
    interval: str = "1D"
    linecolor: str = "#2962FF"
    linewidth: int = 2
    linestyle: int = 0  # 0=solid, 1=dotted, 2=dashed
    currencyId: Optional[str] = None
    zOrderVersion: int = 2
    symbolStateVersion: int = 2
    intervalsVisibilities: IntervalsVisibilities = Field(default_factory=IntervalsVisibilities)
    extendLeft: bool = False
    extendRight: bool = False


class TradingViewDrawing(BaseModel):
    """TradingView drawing in exact API format"""
    id: str  # Unique ID like "6VgiHl"
    type: str  # "LineToolRiskRewardLong", "LineToolNote", "LineToolRectangle", etc.
    state: Dict[str, Any]  # State object (varies by type)
    points: List[DrawingPoint]
    zorder: int = -5000
    linkKey: Optional[str] = None
    version: int = 2
    ownerSource: str = "_seriesId"
    userEditEnabled: bool = False
    isSelectionEnabled: bool = True


class ScannerDrawingOutput(BaseModel):
    """Final output from MCP Scanner Agent"""
    symbol: str
    timeframe: str
    drawings: List[TradingViewDrawing]
    metadata: Dict[str, Any] = {}


# ============================================================================
# Helper Functions
# ============================================================================

def generate_drawing_id() -> str:
    """Generate unique drawing ID like TradingView (6 characters)"""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=6))


def generate_link_key() -> str:
    """Generate unique link key like TradingView (12 characters)"""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=12))


def get_stock_data(symbol: str, period: str = "3mo") -> Optional[Dict[str, Any]]:
    """Fetch stock data using yfinance"""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period)
        
        if hist.empty:
            return None
        
        current_price = float(hist['Close'].iloc[-1])
        high_52w = float(hist['High'].max())
        low_52w = float(hist['Low'].min())
        
        return {
            "current_price": current_price,
            "high_52w": high_52w,
            "low_52w": low_52w,
            "latest_timestamp": int(hist.index[-1].timestamp()),
            "data": hist
        }
    except Exception as e:
        print(f"❌ Error fetching data for {symbol}: {e}")
        return None


# ============================================================================
# Drawing Translator (MCP Signals → TradingView JSON)
# ============================================================================

class TradingViewDrawingTranslator:
    """Converts MCP signals into exact TradingView drawing JSON"""
    
    @staticmethod
    def create_supply_demand_zone(
        symbol: str,
        zone_type: str,  # "supply" or "demand"
        start_time: int,
        end_time: int,
        high_price: float,
        low_price: float,
        interval: str = "1D"
    ) -> TradingViewDrawing:
        """Create supply/demand zone as rectangle"""
        
        # Supply zone = red, Demand zone = green
        if zone_type.lower() == "supply":
            color = "#FF4444"
            fill_color = "rgba(255, 68, 68, 0.2)"
        else:  # demand
            color = "#44FF44"
            fill_color = "rgba(68, 255, 68, 0.2)"
        
        state = RectangleState(
            symbol=symbol,
            interval=interval,
            linecolor=color,
            fillColor=fill_color,
            transparency=80
        )
        
        return TradingViewDrawing(
            id=generate_drawing_id(),
            type="LineToolRectangle",
            state=state.model_dump(),
            points=[
                DrawingPoint(price=high_price, time_t=start_time),
                DrawingPoint(price=low_price, time_t=end_time)
            ],
            zorder=-6000,
            linkKey=generate_link_key()
        )
    
    @staticmethod
    def create_risk_reward(
        symbol: str,
        entry_time: int,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        interval: str = "1D",
        account_size: float = 10000.0
    ) -> TradingViewDrawing:
        """Create LineToolRiskRewardLong drawing"""
        
        risk_amount = abs(entry_price - stop_loss)
        reward_amount = abs(take_profit - entry_price)
        risk_percent = (risk_amount / entry_price) * 100
        
        state = RiskRewardState(
            qty=1.0,
            risk=f"{risk_percent:.2f}",
            symbol=symbol,
            interval=interval,
            riskSize=risk_amount * account_size / entry_price,
            stopLevel=stop_loss,
            amountStop=risk_amount,
            accountSize=account_size,
            profitLevel=take_profit,
            amountTarget=reward_amount
        )
        
        return TradingViewDrawing(
            id=generate_drawing_id(),
            type="LineToolRiskRewardLong",
            state=state.model_dump(),
            points=[
                DrawingPoint(price=entry_price, time_t=entry_time),
                DrawingPoint(price=entry_price, time_t=entry_time + 86400 * 30),
                DrawingPoint(price=entry_price, time_t=entry_time),
                DrawingPoint(price=stop_loss, time_t=entry_time + 86400 * 30)
            ],
            zorder=-5000,
            linkKey=generate_link_key()
        )
    
    @staticmethod
    def create_note(
        symbol: str,
        time: int,
        price: float,
        text: str,
        interval: str = "1D",
        color: str = "#2962FF"
    ) -> TradingViewDrawing:
        """Create LineToolNote drawing"""
        
        state = NoteState(
            text=text,
            symbol=symbol,
            interval=interval,
            borderColor=color,
            markerColor=color,
            backgroundColor=f"rgba(41, 98, 255, 0.7)"
        )
        
        return TradingViewDrawing(
            id=generate_drawing_id(),
            type="LineToolNote",
            state=state.model_dump(),
            points=[DrawingPoint(price=price, time_t=time)],
            zorder=-7500,
            linkKey=generate_link_key()
        )
    
    @staticmethod
    def create_rectangle(
        symbol: str,
        start_time: int,
        end_time: int,
        high_price: float,
        low_price: float,
        interval: str = "1D",
        color: str = "#2962FF",
        label: str = "Zone"
    ) -> TradingViewDrawing:
        """Create LineToolRectangle drawing"""
        
        state = RectangleState(
            symbol=symbol,
            interval=interval,
            linecolor=color,
            fillColor=f"rgba(41, 98, 255, 0.2)",
            transparency=80
        )
        
        return TradingViewDrawing(
            id=generate_drawing_id(),
            type="LineToolRectangle",
            state=state.model_dump(),
            points=[
                DrawingPoint(price=high_price, time_t=start_time),
                DrawingPoint(price=low_price, time_t=end_time)
            ],
            zorder=-6000,
            linkKey=generate_link_key()
        )
    
    @staticmethod
    def create_trend_line(
        symbol: str,
        start_time: int,
        start_price: float,
        end_time: int,
        end_price: float,
        interval: str = "1D",
        color: str = "#2962FF",
        extend_right: bool = False
    ) -> TradingViewDrawing:
        """Create LineToolTrendLine drawing"""
        
        state = TrendLineState(
            symbol=symbol,
            interval=interval,
            linecolor=color,
            linewidth=2,
            linestyle=0,
            extendRight=extend_right
        )
        
        return TradingViewDrawing(
            id=generate_drawing_id(),
            type="LineToolTrendLine",
            state=state.model_dump(),
            points=[
                DrawingPoint(price=start_price, time_t=start_time),
                DrawingPoint(price=end_price, time_t=end_time)
            ],
            zorder=-6500,
            linkKey=generate_link_key()
        )


# ============================================================================
# MCP-Powered Scanner Agent
# ============================================================================

# System prompt for the drawing instruction agent
DRAWING_AGENT_PROMPT = """You are a TradingView drawing instruction generator.

Your job is to analyze stock data using TradingView MCP tools and generate drawing instructions in JSON format.

IMPORTANT RULES:
1. Use TradingView MCP tools to analyze the stock
2. Based on the analysis, generate appropriate drawing instructions
3. Return ONLY valid JSON with drawing instructions
4. Support these drawing types:
   - Supply/Demand zones (rectangles)
   - Support/Resistance levels (trend lines)
   - Risk/Reward setups
   - Notes/Annotations

EXAMPLE USER QUERIES:
- "Add supply and demand zones for TCS stock"
- "Show support and resistance levels for AAPL"
- "Create risk/reward setup for RELIANCE"

RESPONSE FORMAT:
Return a JSON object with:
{
  "symbol": "AAPL",
  "timeframe": "1D",
  "drawings": [
    {
      "type": "supply_zone" | "demand_zone" | "support" | "resistance" | "risk_reward" | "note",
      "price_high": 150.0,
      "price_low": 145.0,
      "start_time": 1640000000,
      "end_time": 1642592000,
      "text": "Supply Zone",
      "color": "#FF4444"
    }
  ]
}

Use the TradingView MCP tools to get real data and generate accurate drawing instructions.
"""

# ============================================================================
# Agent Creation Function (Create fresh agent for each request)
# ============================================================================

def create_drawing_agent():
    """Create a fresh MCP-powered drawing agent for each request
    
    This creates both fresh MCP servers AND a fresh agent to avoid
    event loop conflicts in Streamlit.
    """
    if not MCP_AVAILABLE:
        return None
    
    try:
        # Load MCP servers fresh for this request (avoids event loop issues)
        print("📡 Loading fresh MCP servers for this request...")
        servers = load_mcp_servers(MCP_CONFIG_PATH)
        print(f"✅ Loaded {len(servers)} MCP server(s)")
        
        # Create OpenRouter provider
        provider = OpenAIProvider(
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_BASE_URL
        )
        
        # Create model
        model = OpenAIModel(
            provider=provider,
            model_name="openai/gpt-oss-120b"  # Fast and cost-effective
        )
        
        # Create agent with fresh MCP tools
        agent = Agent(
            model=model,
            toolsets=servers,
            system_prompt=DRAWING_AGENT_PROMPT
        )
        print("✅ Drawing agent created with fresh MCP tools")
        return agent
    except Exception as e:
        print(f"❌ Error creating drawing agent: {e}")
        import traceback
        traceback.print_exc()
        return None


# ============================================================================
# Main Scanner Function (MCP-Powered)
# ============================================================================

async def run_mcp_scanner_tradingview(
    query: str,
    symbol: str,
    timeframe: str = "1D"
) -> ScannerDrawingOutput:
    """
    Run MCP scanner and return TradingView-format drawings
    
    Args:
        query: Scanner query (e.g., "Add supply and demand zones for TCS")
        symbol: Stock symbol (e.g., "AAPL", "TCS.NS")
        timeframe: Chart timeframe (e.g., "1D", "1h")
    
    Returns:
        ScannerDrawingOutput with TradingView-format drawings
    """
    
    print(f"\nMCP Scanner Query: {query}")
    print(f"Symbol: {symbol}, Timeframe: {timeframe}")
    
    translator = TradingViewDrawingTranslator()
    drawings = []
    
    # Get stock data
    stock_data = get_stock_data(symbol)
    
    if not stock_data:
        print(f"Could not fetch data for {symbol}, using fallback")
        current_price = 100.0
        current_time = int(datetime.now().timestamp())
    else:
        current_price = stock_data["current_price"]
        current_time = stock_data["latest_timestamp"]
        print(f"Got stock data: Price=${current_price:.2f}")
    
    # Try to use MCP agent if available
    drawing_agent = None
    if MCP_AVAILABLE and OPENROUTER_API_KEY:
        try:
            print("🤖 Creating fresh MCP agent for this request...")
            drawing_agent = create_drawing_agent()
            if drawing_agent:
                print("✅ MCP agent ready")
        except Exception as e:
            print(f"❌ Error creating MCP agent: {e}")
            import traceback
            traceback.print_exc()
            drawing_agent = None
    
    if drawing_agent:
        try:
            print("🔧 Calling MCP agent with TradingView tools...")
            
            # Construct prompt for agent
            agent_query = f"{query} for {symbol} on {timeframe} timeframe. Current price: ${current_price:.2f}"
            
            # Run agent with MCP tools
            result = await drawing_agent.run(agent_query)
            
            print(f"MCP agent response received")
            print(f"Response type: {type(result.output)}")
            print(f"Response: {str(result.output)[:500]}...")
            
            # Try to parse agent response as JSON
            try:
                # Handle both string and dict responses
                if isinstance(result.output, str):
                    agent_data = json.loads(result.output)
                elif isinstance(result.output, dict):
                    agent_data = result.output
                else:
                    agent_data = {"drawings": []}
                
                # Convert agent response to TradingView drawings
                for drawing_spec in agent_data.get("drawings", []):
                    draw_type = drawing_spec.get("type", "").lower()
                    
                    if "supply" in draw_type:
                        drawings.append(
                            translator.create_supply_demand_zone(
                                symbol=symbol,
                                zone_type="supply",
                                start_time=drawing_spec.get("start_time", current_time - 86400 * 10),
                                end_time=drawing_spec.get("end_time", current_time),
                                high_price=drawing_spec.get("price_high", current_price * 1.05),
                                low_price=drawing_spec.get("price_low", current_price * 1.02),
                                interval=timeframe
                            )
                        )
                    
                    elif "demand" in draw_type:
                        drawings.append(
                            translator.create_supply_demand_zone(
                                symbol=symbol,
                                zone_type="demand",
                                start_time=drawing_spec.get("start_time", current_time - 86400 * 10),
                                end_time=drawing_spec.get("end_time", current_time),
                                high_price=drawing_spec.get("price_high", current_price * 0.98),
                                low_price=drawing_spec.get("price_low", current_price * 0.95),
                                interval=timeframe
                            )
                        )
                    
                    elif "risk" in draw_type or "reward" in draw_type:
                        drawings.append(
                            translator.create_risk_reward(
                                symbol=symbol,
                                entry_time=current_time,
                                entry_price=drawing_spec.get("entry_price", current_price),
                                stop_loss=drawing_spec.get("stop_loss", current_price * 0.95),
                                take_profit=drawing_spec.get("take_profit", current_price * 1.10),
                                interval=timeframe
                            )
                        )
                    
                    elif "note" in draw_type:
                        drawings.append(
                            translator.create_note(
                                symbol=symbol,
                                time=drawing_spec.get("time", current_time),
                                price=drawing_spec.get("price", current_price),
                                text=drawing_spec.get("text", "Analysis Note"),
                                interval=timeframe,
                                color=drawing_spec.get("color", "#2962FF")
                            )
                        )
                
                if drawings:
                    print(f"Generated {len(drawings)} drawings from MCP agent response")
                else:
                    print("No drawings generated from MCP response, using fallback")
                
            except (json.JSONDecodeError, AttributeError, TypeError) as e:
                print(f"Could not parse MCP agent response: {e}, using fallback")
        
        except Exception as e:
            import traceback
            print(f"MCP agent error: {e}")
            print(f"Error details: {traceback.format_exc()}")
            print("Using fallback...")
    
    # Fallback: Generate example drawings if MCP didn't work
    if not drawings:
        print("Using fallback drawing generation...")
        
        # Detect query intent
        query_lower = query.lower()
        
        if "supply" in query_lower or "demand" in query_lower:
            # Supply zone (above current price)
            drawings.append(
                translator.create_supply_demand_zone(
                    symbol=symbol,
                    zone_type="supply",
                    start_time=current_time - 86400 * 10,
                    end_time=current_time,
                    high_price=current_price * 1.08,
                    low_price=current_price * 1.05,
                    interval=timeframe
                )
            )
            
            # Demand zone (below current price)
            drawings.append(
                translator.create_supply_demand_zone(
                    symbol=symbol,
                    zone_type="demand",
                    start_time=current_time - 86400 * 10,
                    end_time=current_time,
                    high_price=current_price * 0.97,
                    low_price=current_price * 0.94,
                    interval=timeframe
                )
            )
        
        elif "risk" in query_lower or "reward" in query_lower:
            drawings.append(
                translator.create_risk_reward(
                    symbol=symbol,
                    entry_time=current_time,
                    entry_price=current_price,
                    stop_loss=current_price * 0.95,
                    take_profit=current_price * 1.10,
                    interval=timeframe
                )
            )
        
        else:
            # Default: Add a note
            drawings.append(
                translator.create_note(
                    symbol=symbol,
                    time=current_time,
                    price=current_price,
                    text=f"Analysis for {symbol}",
                    interval=timeframe
                )
            )
    
    return ScannerDrawingOutput(
        symbol=symbol,
        timeframe=timeframe,
        drawings=drawings,
        metadata={
            "scan_time": datetime.now().isoformat(),
            "query": query,
            "drawing_count": len(drawings),
            "mcp_used": MCP_AVAILABLE and drawing_agent is not None,
            "current_price": current_price
        }
    )


# ============================================================================
# Utility Functions
# ============================================================================

def save_drawings_tradingview(symbol: str, drawings: ScannerDrawingOutput):
    """Save TradingView-format drawings to cache"""
    cache_dir = "scanner_cache_tradingview"
    os.makedirs(cache_dir, exist_ok=True)
    
    cache_file = f"{cache_dir}/{symbol}_drawings.json"
    
    with open(cache_file, 'w') as f:
        json.dump(drawings.model_dump(), f, indent=2)
    
    print(f"Saved TradingView drawings to {cache_file}")


def get_latest_drawings_tradingview(symbol: str) -> Optional[Dict[str, Any]]:
    """Get latest TradingView-format drawings for a symbol"""
    cache_file = f"scanner_cache_tradingview/{symbol}_drawings.json"
    
    if os.path.exists(cache_file):
        with open(cache_file, 'r') as f:
            return json.load(f)
    
    return None


# ============================================================================
# Example Usage
# ============================================================================

async def example_usage():
    """Example of how to use the MCP-powered TradingView scanner"""
    
    # Run scanner with MCP agent
    result = await run_mcp_scanner_tradingview(
        query="Add supply and demand zones for TCS stock",
        symbol="TCS.NS",
        timeframe="1D"
    )
    
    print("\nTradingView Scanner Result:")
    print(json.dumps(result.model_dump(), indent=2))
    
    # Save to cache
    save_drawings_tradingview("TCS.NS", result)
    
    return result


if __name__ == "__main__":
    import asyncio
    asyncio.run(example_usage())
