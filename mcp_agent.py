"""
MCP Technical Scanner Agent
Dedicated agent for TradingView MCP tools (technical analysis)
Separate from the main stock analysis agent
"""

from pydantic_ai import Agent, RunContext
from pydantic import BaseModel, Field
from typing import Optional
from dataclasses import dataclass
import os
from datetime import datetime
from dotenv import load_dotenv
from utils.model_config import get_model

load_dotenv()

# -------------------------
#   TOOL RESPONSE WRAPPER
# -------------------------
class ToolResponse(BaseModel):
    """Wrapper for tool responses"""
    content: str = Field(description="The tool's output content")
    tool_name: str = Field(description="Name of the tool")
    is_tool_response: bool = Field(default=True)
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    
    def __str__(self):
        return self.content
    
    def __repr__(self):
        return f"ToolResponse(tool={self.tool_name}, length={len(self.content)})"
    
    def __len__(self):
        return len(self.content)
    
    def __contains__(self, item):
        return item in self.content


def create_tool_response(content: str, tool_name: str) -> ToolResponse:
    """Helper to create ToolResponse objects"""
    return ToolResponse(content=content, tool_name=tool_name)


# -------------------------
#   MCP CONVERSATION STATE
# -------------------------
@dataclass
class MCPConversationState:
    """State for MCP technical scanner conversations"""
    last_query: Optional[str] = None
    last_tool_used: Optional[str] = None
    last_result: Optional[str] = None
    conversation_history: list = None
    
    def __post_init__(self):
        if self.conversation_history is None:
            self.conversation_history = []


# -------------------------
#   MCP SYSTEM PROMPT
# -------------------------
mcp_system_prompt = """You are a specialized Technical Analysis AI assistant with access to TradingView MCP tools.

🎯 YOUR MISSION:
Provide professional technical analysis using TradingView market scanning tools for:
- Bollinger Band patterns (squeeze, breakouts)
- Candlestick patterns (bullish/bearish signals)
- Market screening (RSI, MACD, volume analysis)
- Technical indicators and chart patterns

🚨 CRITICAL RULES:

1. **TOOL OUTPUT ONLY**: When a tool returns output, return it EXACTLY as-is
   - NO introductions ("Here's...", "I found...")
   - NO summaries or paraphrasing
   - NO modifications
   - ONLY the tool's exact output

2. **STOCKS ONLY**: MCP tools should ONLY scan STOCKS, NOT cryptocurrency
   - Always specify: Exchange (NSE, BSE, NYSE, NASDAQ)
   - Always add: "stocks only, exclude crypto"
   - Focus on Indian stock market (NSE/BSE) by default

3. **TECHNICAL ANALYSIS ONLY**: MCP tools provide:
   - Chart patterns and technical indicators
   - Price action and momentum signals
   - Support/resistance levels
   - Volume analysis
   
   MCP tools DO NOT provide:
   - Buy/sell ratings or recommendations
   - Fundamental analysis (P/E, revenue, earnings)
   - Analyst ratings or price targets
   - Financial metrics or ratios

🔧 AVAILABLE MCP TOOLS:

You have access to TradingView MCP tools for:
- **Bollinger Band Analysis**: Detect squeeze patterns, breakouts
- **Candlestick Patterns**: Identify bullish/bearish formations
- **Market Screening**: Filter stocks by technical criteria
- **Technical Indicators**: RSI, MACD, Moving Averages, Volume

🎯 TOOL CALLING RULES:

**For Bollinger Band queries:**
- "Find Bollinger squeeze" → Use tradingview_bollinger_scan
- "Bollinger breakout stocks" → Use tradingview_bollinger_scan
- Always add: "on NSE exchange (stocks only, exclude crypto)"

**For Candlestick patterns:**
- "Show bullish patterns" → Use tradingview_advanced_candle_pattern
- "Find hammer patterns" → Use tradingview_advanced_candle_pattern
- Always add: "on NSE exchange (stocks only, exclude crypto)"

**For Market Screening:**
- "Find oversold stocks" → Use tradingview_rating_filter
- "Stocks with high RSI" → Use tradingview_rating_filter
- Always add: "on NSE exchange (stocks only, exclude crypto)"

**For General Technical Analysis:**
- Choose the most appropriate MCP tool based on the query
- Always specify exchange and exclude crypto

🚨 RESPONSE FORMAT:

When MCP tool returns data:
1. Return the EXACT tool output
2. DO NOT add your own analysis
3. DO NOT create summaries
4. DO NOT add introductions
5. Let the visualization pipeline handle formatting

Example CORRECT behavior:
```
User: "Find Bollinger squeeze stocks"
Tool returns: [Technical data with 10 stocks]
You return: [EXACT same technical data]
```

Example INCORRECT behavior (NEVER DO THIS):
```
User: "Find Bollinger squeeze stocks"
Tool returns: [Technical data]
You return: "I found 10 stocks with Bollinger squeeze..." ❌ WRONG!
```

🎯 QUERY ENHANCEMENT:

When user asks vague questions, enhance them:
- "Find good stocks" → "Find stocks with Bollinger squeeze on NSE exchange (stocks only, exclude crypto)"
- "Show patterns" → "Show bullish candlestick patterns on NSE exchange (stocks only, exclude crypto)"
- "Scan market" → "Scan NSE market for technical setups (stocks only, exclude crypto)"

🚨 CRITICAL: ALWAYS ADD EXCHANGE AND EXCLUDE CRYPTO

Every MCP tool call MUST include:
- Exchange specification: "on NSE exchange" or "on BSE exchange"
- Crypto exclusion: "(stocks only, exclude crypto)"

Example queries to MCP tools:
- "Find Bollinger squeeze on NSE exchange (stocks only, exclude crypto)"
- "Show hammer patterns on BSE exchange (stocks only, exclude crypto)"
- "Scan for oversold stocks on NSE exchange (stocks only, exclude crypto)"

YOUR ROLE: Technical analysis specialist using TradingView tools
YOUR TOOLS: TradingView MCP technical analysis tools
YOUR OUTPUT: Raw tool output (no modifications)
YOUR STYLE: Direct, data-driven, technical
"""

# -------------------------
#   LOAD MCP SERVERS
# -------------------------
print("🔧 Loading MCP servers for Technical Scanner...")

USE_MCP = os.getenv("USE_MCP", "false").lower() == "true"

if USE_MCP:
    try:
        from pydantic_ai.mcp import load_mcp_servers
        
        # Load MCP servers from config file
        mcp_servers = load_mcp_servers("mcp_config.json")
        print(f"✅ MCP servers loaded: {len(mcp_servers)} server(s)")
        
        # Display loaded servers
        for server in mcp_servers:
            print(f"   • {server.id}: TradingView technical analysis tools")
            
    except FileNotFoundError:
        print(f"⚠️  mcp_config.json not found - MCP agent will not work")
        mcp_servers = []
    except Exception as e:
        print(f"⚠️  Failed to load MCP servers: {e}")
        mcp_servers = []
else:
    print("ℹ️  MCP disabled (set USE_MCP=true in .env to enable)")
    print("   Technical Scanner requires MCP to be enabled")
    mcp_servers = []

# -------------------------
#   INITIALIZE MCP AGENT
# -------------------------
model = get_model()

mcp_agent = Agent(
    model=model,
    system_prompt=mcp_system_prompt,
    deps_type=MCPConversationState,
    output_type=ToolResponse,
    mcp_servers=mcp_servers,  # TradingView MCP tools
    retries=3,
)

print(f"✅ MCP Technical Scanner Agent initialized with {len(mcp_servers)} MCP server(s)" if mcp_servers else "⚠️  MCP Agent initialized without MCP servers (disabled)")


# -------------------------
#   HELPER FUNCTIONS
# -------------------------
def is_mcp_enabled() -> bool:
    """Check if MCP is enabled and servers are loaded"""
    return USE_MCP and len(mcp_servers) > 0


def get_mcp_agent():
    """Get the MCP agent instance"""
    return mcp_agent


def create_mcp_state() -> MCPConversationState:
    """Create a new MCP conversation state"""
    return MCPConversationState()


# -------------------------
#   MAIN FUNCTION FOR TESTING
# -------------------------
async def test_mcp_agent():
    """Test the MCP agent with a sample query"""
    if not is_mcp_enabled():
        print("❌ MCP is not enabled. Set USE_MCP=true in .env")
        return
    
    print("\n🧪 Testing MCP Agent...")
    print("=" * 60)
    
    # Test query
    query = "Find stocks with Bollinger squeeze on NSE exchange (stocks only, exclude crypto)"
    
    print(f"Query: {query}")
    print("=" * 60)
    
    try:
        # Create state
        state = create_mcp_state()
        
        # Run agent
        result = await mcp_agent.run(query, deps=state)
        
        print(f"\n📊 MCP Agent Response:")
        print("=" * 60)
        print(result.output)
        print("=" * 60)
        
        print("\n✅ MCP Agent test complete!")
        
    except Exception as e:
        print(f"❌ Error testing MCP agent: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_mcp_agent())
