from pydantic_ai import Agent, RunContext
from pydantic_ai.models.groq import GroqModel
from typing import Optional, List
from dataclasses import dataclass
import os
import re
import random
from datetime import datetime
from tools import StockTools
from models import (
    StockValidation, CompanyData, CompanyReport, 
    ScenarioAnalysis, Summary
)
from dotenv import load_dotenv
from langsmith import traceable
load_dotenv()

import asyncio
import time
from collections import deque

# -------------------------
#   API KEY ROTATION SYSTEM
# -------------------------
class GroqAPIKeyManager:
    """Manages multiple Groq API keys with automatic rotation and rate limit handling"""
    
    def __init__(self):
        self.api_keys = self._load_api_keys()
        self.current_key_index = 0
        self.key_usage_count = {i: 0 for i in range(len(self.api_keys))}
        self.key_last_used = {i: 0 for i in range(len(self.api_keys))}
        self.key_errors = {i: 0 for i in range(len(self.api_keys))}
        self.key_cooldown = {i: 0 for i in range(len(self.api_keys))}  # Cooldown until timestamp
        
        print(f"🔑 Loaded {len(self.api_keys)} Groq API keys for rotation")
    
    def _load_api_keys(self) -> List[str]:
        """Load all available Groq API keys from environment"""
        keys = []
        for i in range(1, 11):  # Check for GROQ_API_KEY_1 through GROQ_API_KEY_8
            key = os.getenv(f"GROQ_API_KEY_{i}")
            if key and key != "your_groq_api_key_here" and key.strip():
                keys.append(key.strip())
                print(f"✅ Loaded GROQ_API_KEY_{i}")
            else:
                print(f"⚠️ GROQ_API_KEY_{i} not found or empty")
        
        if not keys:
            # Fallback to single key
            fallback_key = os.getenv("GROQ_API_KEY")
            if fallback_key and fallback_key.strip():
                keys.append(fallback_key.strip())
                print("📌 Using fallback GROQ_API_KEY")
        
        if not keys:
            raise ValueError("❌ No valid Groq API keys found! Please check your .env file.")
        
        return keys
    
    def get_current_key(self) -> str:
        """Get the current API key, rotating if needed"""
        now = time.time()
        
        # Check if current key is in cooldown
        if now < self.key_cooldown.get(self.current_key_index, 0):
            print(f"🔄 Key {self.current_key_index + 1} in cooldown, rotating...")
            self._rotate_to_next_available_key()
        
        key = self.api_keys[self.current_key_index]
        self.key_usage_count[self.current_key_index] += 1
        self.key_last_used[self.current_key_index] = now
        
        print(f"🔑 Using API key {self.current_key_index + 1}/{len(self.api_keys)} (used {self.key_usage_count[self.current_key_index]} times)")
        return key
    
    def _rotate_to_next_available_key(self):
        """Rotate to the next available key that's not in cooldown"""
        now = time.time()
        original_index = self.current_key_index
        
        for _ in range(len(self.api_keys)):
            self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
            
            # Check if this key is available (not in cooldown)
            if now >= self.key_cooldown.get(self.current_key_index, 0):
                if self.current_key_index != original_index:
                    print(f"🔄 Rotated from key {original_index + 1} to key {self.current_key_index + 1}")
                return
        
        # If all keys are in cooldown, use the one with shortest remaining cooldown
        min_cooldown_key = min(self.key_cooldown.keys(), 
                              key=lambda k: self.key_cooldown[k])
        self.current_key_index = min_cooldown_key
        print(f"⚠️ All keys in cooldown, using key {self.current_key_index + 1} with shortest cooldown")
    
    def handle_rate_limit_error(self, error_msg: str = ""):
        """Handle rate limit error by putting current key in cooldown and rotating"""
        current_key = self.current_key_index + 1
        self.key_errors[self.current_key_index] += 1
        
        # Calculate cooldown time based on error count for this key
        error_count = self.key_errors[self.current_key_index]
        cooldown_time = min(60 * (2 ** (error_count - 1)), 300)  # Max 5 minutes
        self.key_cooldown[self.current_key_index] = time.time() + cooldown_time
        
        print(f"❌ Rate limit hit on key {current_key} (error #{error_count})")
        print(f"🕒 Key {current_key} in cooldown for {cooldown_time}s")
        
        # Rotate to next available key
        self._rotate_to_next_available_key()
        
        return cooldown_time
    
    def reset_key_errors(self):
        """Reset error count for current key on successful request"""
        if self.key_errors[self.current_key_index] > 0:
            print(f"✅ Key {self.current_key_index + 1} errors cleared")
            self.key_errors[self.current_key_index] = 0
    
    def get_status(self) -> str:
        """Get current status of all keys"""
        now = time.time()
        status_lines = [f"🔑 API Key Status ({len(self.api_keys)} keys):"]
        
        for i, key in enumerate(self.api_keys):
            is_current = "👉" if i == self.current_key_index else "  "
            usage = self.key_usage_count[i]
            errors = self.key_errors[i]
            
            if now < self.key_cooldown.get(i, 0):
                cooldown_remaining = int(self.key_cooldown[i] - now)
                status = f"❄️ Cooldown ({cooldown_remaining}s)"
            else:
                status = "✅ Available"
            
            status_lines.append(f"{is_current} Key {i+1}: {status} | Used: {usage} | Errors: {errors}")
        
        return "\n".join(status_lines)

# Initialize the API key manager
api_key_manager = GroqAPIKeyManager()

# -------------------------
#   ENHANCED RATE LIMITER WITH API KEY ROTATION
# -------------------------
class RateLimiter:
    def __init__(self, max_calls=20, time_window=60):  # Increased since we have 8 keys
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls = deque()
        self.consecutive_errors = 0
        self.last_error_time = 0
    
    async def wait_if_needed(self):
        now = time.time()
        
        # If we had recent errors, add extra delay
        if self.consecutive_errors > 0:
            time_since_error = now - self.last_error_time
            if time_since_error < 30:  # Within 30 seconds of error
                backoff_delay = min(2 ** self.consecutive_errors, 15)  # Max 15 seconds
                print(f"⏳ Rate limit backoff: waiting {backoff_delay}s (error count: {self.consecutive_errors})")
                await asyncio.sleep(backoff_delay)
        
        # Remove old calls outside the time window
        while self.calls and self.calls[0] < now - self.time_window:
            self.calls.popleft()
        
        # If we've hit the limit, wait
        if len(self.calls) >= self.max_calls:
            sleep_time = self.calls[0] + self.time_window - now
            if sleep_time > 0:
                print(f"⏳ Rate limit: waiting {sleep_time:.1f}s before next request")
                await asyncio.sleep(sleep_time + 1)  # Add 1 second buffer
                return await self.wait_if_needed()
        
        self.calls.append(now)
    
    def record_error(self):
        """Record a rate limit error"""
        self.consecutive_errors += 1
        self.last_error_time = time.time()
        print(f"❌ Rate limit error recorded (count: {self.consecutive_errors})")
    
    def reset_errors(self):
        """Reset error count on successful request"""
        if self.consecutive_errors > 0:
            print(f"✅ Rate limit errors cleared")
        self.consecutive_errors = 0

# Global rate limiter: More generous settings with 8 API keys
# With 8 keys, each with 30 RPM = 240 total RPM theoretical max
# We set conservative limit to avoid hitting individual key limits
rate_limiter = RateLimiter(max_calls=20, time_window=60)

# -------------------------
#   Conversation State
# -------------------------
@dataclass
class ConversationState:
    stock_symbol: Optional[str] = None
    stock_name: Optional[str] = None
    company_data: Optional[CompanyData] = None
    report_generated: bool = False
    conversation_history: list = None
    pending_variants: Optional[list] = None  # Store variants when user needs to choose
    last_user_message: Optional[str] = None  # Track last user input
    last_assistant_message: Optional[str] = None  # Track last assistant response
    conversation_context: Optional[dict] = None  # Rich context tracking
    
    def __post_init__(self):
        if self.conversation_history is None:
            self.conversation_history = []
        if self.conversation_context is None:
            self.conversation_context = {
                'recent_actions': [],  # Last 5 actions
                'user_intent': None,   # What user is trying to do
                'session_start': datetime.now().isoformat(),
                'total_interactions': 0
            }
    
    def add_interaction(self, user_input: str, action_type: str, result_summary: str):
        """Add interaction to conversation context with rich tracking"""
        interaction = {
            'timestamp': datetime.now().isoformat(),
            'user_input': user_input,
            'action_type': action_type,  # 'new_search', 'selection', 'question', etc.
            'result_summary': result_summary,
            'interaction_id': self.conversation_context['total_interactions'] + 1
        }
        
        # Update recent actions (keep last 5)
        self.conversation_context['recent_actions'].append(interaction)
        if len(self.conversation_context['recent_actions']) > 5:
            self.conversation_context['recent_actions'].pop(0)
        
        # Update counters
        self.conversation_context['total_interactions'] += 1
        
        # Update last messages
        self.last_user_message = user_input
        
        # Add to conversation history (keep last 10 for context)
        self.conversation_history.append(interaction)
        if len(self.conversation_history) > 10:
            self.conversation_history.pop(0)
    
    def get_recent_context(self, last_n: int = 3) -> dict:
        """Get recent conversation context for decision making"""
        return {
            'recent_actions': self.conversation_context['recent_actions'][-last_n:],
            'has_pending_variants': bool(self.pending_variants),
            'current_stock': self.stock_symbol,
            'last_user_input': self.last_user_message,
            'session_interactions': self.conversation_context['total_interactions']
        }
        if self.conversation_context is None:
            self.conversation_context = {
                'recent_actions': [],  # Last 5 actions
                'user_intent': None,   # What user is trying to do
                'session_start': datetime.now().isoformat(),
                'total_interactions': 0
            }


# -------------------------
#   DYNAMIC GROQ MODEL WITH API KEY ROTATION
# -------------------------
class DynamicGroqModel:
    """Wrapper for GroqModel that handles API key rotation"""
    
    def __init__(self, model_name="openai/gpt-oss-120b"):
        self.model_name = model_name
        self._current_model = None
        self._current_key = None
    
    def _get_model(self):
        """Get current model instance, creating new one if key changed"""
        current_key = api_key_manager.get_current_key()
        
        if self._current_model is None or self._current_key != current_key:
            print(f"🔄 Creating new GroqModel instance with rotated key")
            # Set environment variable for Groq API key
            import os
            os.environ['GROQ_API_KEY'] = current_key
            
            # Create GroqModel - it reads from GROQ_API_KEY environment variable
            self._current_model = GroqModel(self.model_name)
            self._current_key = current_key
        
        return self._current_model
    
    def __getattr__(self, name):
        """Delegate all attributes to the current model instance"""
        model = self._get_model()
        return getattr(model, name)
    
    def __str__(self):
        """String representation"""
        return f"DynamicGroqModel({self.model_name})"
    
    def __repr__(self):
        """String representation"""
        return f"DynamicGroqModel(model_name='{self.model_name}')"

# Create dynamic model that rotates API keys
# Set initial API key before creating model
initial_key = api_key_manager.get_current_key()
os.environ['GROQ_API_KEY'] = initial_key
model = GroqModel("openai/gpt-oss-120b")

# -------------------------
#   AGENT CREATION WITH API KEY ROTATION

    # Ensure we have the current API key in environment
current_key = api_key_manager.get_current_key()
os.environ['GROQ_API_KEY'] = current_key

# Create model with current key - using supported model
model = GroqModel("openai/gpt-oss-120b")

agent = Agent(
    model=model,
    system_prompt="""You are an elite stock analysis AI assistant with deep financial expertise. Your primary mission is to provide comprehensive, accurate, and actionable stock analysis.

🎯 CORE MISSION:
Deliver professional-grade stock analysis by intelligently orchestrating tools and presenting insights in a clear, compelling format.

🚨 RESPONSE GENERATION RULE #1 (MOST IMPORTANT):
When ANY tool returns output, your response = tool output (exactly, character-for-character)
DO NOT add anything. DO NOT remove anything. DO NOT modify anything.
Just display the tool's return value as your complete response.

⚠️ CRITICAL OUTPUT RULES - READ CAREFULLY:
1. When a tool returns output, you MUST display it EXACTLY as-is - ZERO modifications
2. DO NOT add introductions like "Here's the analysis..." or "I found..."
3. DO NOT summarize, paraphrase, or rewrite ANY part of the tool output
4. DO NOT add your own commentary or explanations
5. COPY the tool's return value and paste it DIRECTLY as your response
6. Preserve ALL formatting: bullets (•), bold (**), separators (━━━), emojis (📈📉), line breaks
7. If the tool returns a complete report, show the ENTIRE report - not a summary
8. Your ONLY job is to be a PASSTHROUGH - display what the tool returns, nothing more, nothing less

🎯 CRITICAL TOOL CALLING RULES
 
RULE 1: GREETINGS (NO TOOL)
- If user ONLY says "hi", "hello", "hey" with NOTHING else
- Respond: "Hello! I'm your AI stock analyst. Tell me which stock to analyze!"

RULE 2: STOCK ANALYSIS (CALL analyze_stock_request)
- If user mentions ANY stock name, company, ticker, or makes a selection
- Examples: Stock symbols, company names, "analyze [company]", "tell me about [stock]", selection numbers
- Action: IMMEDIATELY call analyze_stock_request(user_input="<FULL_USER_INPUT>")
- This smart tool will automatically decide whether it's a new search or selection
- DO NOT respond with text - CALL THE TOOL FIRST

RULE 3: FOLLOW-UP QUESTIONS (CALL handle_trader_question)
- If user asks about already-loaded stock WITHOUT mentioning new stock names
- Examples: Investment questions, financial queries, business questions, risk assessments
- Action: Call handle_trader_question(question="<QUESTION>")

RULE 4: SCENARIO ANALYSIS (CALL perform_scenario_analysis)
- If user asks "what if" questions
- Examples: Hypothetical market scenarios, economic impact questions
- Action: Call perform_scenario_analysis(scenario="<SCENARIO>")

RULE 5: SUMMARY (CALL generate_summary_report)
- If user asks for summary
- Examples: "give me a summary", "summarize", "key takeaways"
- Action: Call generate_summary_report()

⚠️ CRITICAL: TOOL CALLING PRIORITY

🔥 CONTEXT CHECK FIRST:
- Does ctx.deps.company_data exist? If YES → This is a follow-up conversation
- If company_data exists and user asks questions → ALWAYS call handle_trader_question
- If no company_data and user mentions stock names → Call analyze_stock_request

Check in this order:
1. Is it ONLY a greeting? → Respond directly
2. Does it mention a stock/company/selection? → Call analyze_stock_request
3. Is it a question about loaded stock? → Call handle_trader_question
4. Is it a "what if" scenario? → Call perform_scenario_analysis
5. Is it a summary request? → Call generate_summary_report

🚨 NEVER ASK "WHICH STOCK" IF COMPANY DATA EXISTS!

FORBIDDEN RESPONSES (NEVER DO THIS):
❌ "I will analyze [stock] for you."
❌ "Let me help you with [stock] analysis."
❌ "I'm ready to analyze [stock]."
❌ Generic greetings when stock is mentioned

📊 TOOL OUTPUT PROCESSING - CRITICAL INSTRUCTIONS

⚠️ ABSOLUTE RULE: DO NOT SUMMARIZE OR REWRITE THE TOOL OUTPUT!

When analyze_stock_request returns data:

IMPORTANT: The tool returns ONE COMPLETE thing:
- A FULLY FORMATTED response with BOTH the report (8 sections) AND the Shark Tank pitch
- Everything is ALREADY generated and formatted - you don't need to create anything

YOUR ONLY JOB: Display the tool output EXACTLY AS-IS
- DO NOT summarize it
- DO NOT rewrite it
- DO NOT create your own version
- COPY AND PASTE the entire formatted report exactly as provided
- Show ALL 8 sections with ALL their content:
  • 🏢 Company Snapshot (with ALL details)
  • 📋 Business Overview (with FULL description summary)
  • 💰 Financial Metrics (with ALL 25+ metrics in subsections)
  • 📈 Stock Information & Market Data (with ALL market data)
  • 📊 Price Performance (with ALL time periods AND 7-day history) Each of the 7 days MUST be on a SEPARATE LINE with bullet point, DO NOT put all days on one line.
  • 🏆 Competitor Comparison (with FULL table, make a proper table format)
  • 🎯 SWOT Analysis (with ALL points)
  • 📰 News & Announcements (with ALL news items)

WHAT TO DO:
- The tool output ALREADY contains the complete report AND the Shark Tank pitch
- Simply display the ENTIRE tool output without any changes
- Preserve ALL formatting: •, **, ━━━, 📈📉, line breaks
- Show EVERY section, EVERY line - nothing more, nothing less
- NO HTML tags: <div>, <span>, <p>, <br>

❌ FORBIDDEN: DO NOT add "Here's the analysis..." or ANY introduction
❌ FORBIDDEN: DO NOT summarize or rewrite ANY part of the tool output
❌ FORBIDDEN: DO NOT skip any sections or details
❌ FORBIDDEN: DO NOT generate your own Shark Tank pitch (it's already in the output!)
✅ REQUIRED: Display the tool's return value EXACTLY as provided - be a PASSTHROUGH only

📋 COMPREHENSIVE REPORT STRUCTURE (8 Sections)

The tool returns a report with these sections - present them AS-IS:

1. 🏢 COMPANY SNAPSHOT
   - Company Name, Ticker Symbol, Exchange
   - Sector, Industry, Headquarters
   - CEO, Employees, Website

2. 📋 BUSINESS OVERVIEW
   - Business description
   - Products and services
   - Geographic presence

3. 💰 FINANCIAL METRICS (25+ metrics)
   - Income Statement: Revenue, Net Profit, EBITDA, EPS
   - Balance Sheet: Total Assets, Total Liabilities, Total Debt, Cash Balance, Debt-to-Equity Ratio
   - Cash Flow: Operating CF, Free CF, CapEx
   - Valuation: PE Ratio, PB Ratio, Market Cap, Enterprise Value, EV/EBITDA
   - Margins: Profit Margin, Operating Margin, Gross Margin

4. 📈 STOCK INFORMATION & MARKET DATA
   - Current Price, 52-Week High, 52-Week Low, Market Capitalization
   - Volume, Average Volume, Beta, Dividend Yield, Institutional Holdings

5. 📊 PRICE PERFORMANCE
   - 1 Day, 1 Week, 1 Month, 6 Month, 1 Year, 5 Year CAGR
   - With % changes and 📈📉 indicators
   - Last 7 days price history (each day on separate line)

6. 🏆 COMPETITOR COMPARISON
   - Table format with metrics across competitors

7. 🎯 SWOT ANALYSIS
   - Strengths, Weaknesses, Opportunities, Threats

8. 📰 NEWS & ANNOUNCEMENTS
   - Recent news and announcements

🦈 SHARK TANK PITCH STRUCTURE (14 Points)

After showing the report, generate a Shark Tank pitch with these 14 points:

1. FOUNDER-STYLE INTRODUCTION
   - "Hello Sharks! I am the CEO of [Company]..."
   - Explain the sector and opportunity

2. COMPANY SNAPSHOT
   - Overview of ticker, market cap, industry position

3. BUSINESS OVERVIEW
   - What the company does, revenue streams, market presence

4. FINANCIAL PERFORMANCE
   - Present the numbers conversationally
   - Revenue, profit, margins, cash flow, PE ratio, debt

5. STOCK INFORMATION & MARKET DATA
   - Current price, market cap, trading volume, liquidity

6. PRICE PERFORMANCE
   - Historical performance, resilience, market recognition

7. COMPETITOR LANDSCAPE
   - Who you compete with and what sets you apart

8. SWOT ANALYSIS
   - Strengths, Weaknesses, Opportunities, Threats - be transparent

9. INVESTMENT RATIONALE
   - Why should investors buy? Key value propositions

10. KEY RISKS
    - Honest assessment of risks

11. FUTURE GROWTH PLAN
    - Strategic roadmap, innovation plans

12. SUMMARY FOR SHARKS
    - Bring it all together - conversational wrap-up
    - End with: "So, Sharks, are you ready to invest?"

13. VOICE PITCH SCRIPT (Optional)
    - Brief voice-friendly version

14. Q&A MODE - READY FOR QUESTIONS
    - "Sharks, I'm now ready to answer any questions..."

📤 OUTPUT FORMATTING RULES

CRITICAL FORMATTING RULES:
- Report uses • (bullet) not - (dash) or * (asterisk)
- Report uses **bold** for headers
- DO NOT convert • to - or *
- DO NOT add extra ** around already formatted text
- Preserve ALL separator lines (━━━)
- Keep emoji indicators (📈📉) intact
- Maintain table formatting in competitor section
- Present report section AS-IS without modification
- NO HTML tags ever: <div>, <span>, <p>, <br>
- NEVER return JSON structures like {"tool_name": {"return_value": ...}}
- NEVER add metadata or wrapper text
- Do not use *, Use • (bullet)

⚠️ FINAL CRITICAL REMINDERS

1. Stock name mentioned → IMMEDIATELY call analyze_stock_request
2. NO generic responses → "I will analyze" is FORBIDDEN
3. NO confirmations → Don't ask "Would you like me to analyze?"
4. CALL TOOLS FIRST → Then present results
5. Preserve formatting → Keep all •, **, 📈📉 intact
6. Complete output → Show ALL 8 report sections + 14-point pitch
7. No JSON/metadata → Clean, professional output only
8. No points and titles into the shark tank pitch response(14-point pitch)

YOUR ROLE: Professional stock analyst providing institutional-grade analysis
YOUR TOOLS: Comprehensive data fetching and analysis capabilities
YOUR OUTPUT: Complete reports with 8 sections + Shark Tank pitches
YOUR STYLE: Direct, data-driven, professional, engaging

You MUST automatically choose and call the correct tool.
Never ask the user which tool to run.
Never respond with generic text when a tool should be called.
Always speak professionally like a CEO/CFO after tool execution.
""",
        deps_type=ConversationState,
        retries=3,
    )


# -------------------------
#   HELPER FUNCTIONS
# -------------------------
def generate_shark_tank_pitch(company_data) -> str:
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
    
    # Safely format market cap
    market_cap_str = "N/A"
    if company_data.market_data.market_cap:
        market_cap_str = f"₹{company_data.market_data.market_cap/1e7:.2f} Cr"
    
    # Safely format revenue
    revenue_str = "N/A"
    if company_data.financials.revenue:
        revenue_str = f"₹{company_data.financials.revenue/1e7:.2f} Cr"
    
    # Safely format net profit
    net_profit_str = "N/A"
    if company_data.financials.net_profit:
        net_profit_str = f"₹{company_data.financials.net_profit/1e7:.2f} Cr"
    
    # Safely format free cash flow
    fcf_str = "N/A"
    if company_data.financials.free_cash_flow:
        fcf_str = f"₹{company_data.financials.free_cash_flow/1e7:.2f} Cr"
    
    # Safely format current price
    price_str = "N/A"
    if company_data.market_data.current_price:
        price_str = f"₹{company_data.market_data.current_price:.2f}"
    
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


# -------------------------
#   AGENT TOOLS
# -------------------------
@agent.tool
@traceable(name="analyze_stock_request")
def analyze_stock_request(ctx: RunContext[ConversationState], stock_name: str) -> str:
    """
    Primary stock analysis dispatcher that routes user requests to either a new stock search or a selection from variants.

    Args:
        ctx (RunContext[ConversationState]): The conversation context.
        stock_name (str): The raw input from the user, which can be a company name, a stock symbol (e.g., RELIANCE.NS), or a selection choice (number or name).

    Returns:
        str: A formatted string containing either:
            - A list of stock variants if multiple matches are found (for disambiguation).
            - A complete stock analysis report and Shark Tank pitch if a single valid stock is identified.
            - An error message if the stock cannot be found or data validation fails.
    """
    print(f"🔧 analyze_stock_request called with: '{user_input}'")
    print(f"🔧 Company data exists: {bool(ctx.deps.company_data)}")
    if ctx.deps.company_data:
        print(f"🔧 Current stock: {ctx.deps.company_data.name} ({ctx.deps.company_data.symbol})")
        print(f"⚠️ WARNING: analyze_stock_request called but company data already exists!")
        print(f"⚠️ This might be a follow-up question that should use handle_trader_question instead!")
    
    user_input = user_input.strip()
    
    # Check if user is asking for a specific stock symbol (e.g., "RELIANCE.NS", "analyze RELIANCE.NS")
    import re
    specific_symbol_match = re.search(r'\b([A-Z]{2,15}\.(NS|BO))\b', user_input.upper())
    
    if specific_symbol_match:
        # User asked for a specific symbol - bypass multiple options and go directly
        symbol = specific_symbol_match.group(1)
        print(f"🎯 Direct symbol request detected: {symbol}")
        
        # Extract company name from symbol for validation
        base_symbol = symbol.replace('.NS', '').replace('.BO', '')
        validation = StockTools.validate_stock(base_symbol)
        
        # Check if the requested symbol is in the variants
        if validation.variants:
            matching_variant = None
            for variant in validation.variants:
                if variant['symbol'].upper() == symbol.upper():
                    matching_variant = variant
                    break
            
            if matching_variant:
                # Found the exact symbol - use it directly
                ctx.deps.stock_symbol = matching_variant['symbol']
                ctx.deps.stock_name = matching_variant['name']
                ctx.deps.pending_variants = None
                
                try:
                    company_data = StockTools.get_realtime_data(matching_variant['symbol'])
                    ctx.deps.company_data = company_data
                    formatted_report = StockTools.format_data_for_report(company_data)
                    
                    # Add to conversation context
                    ctx.deps.add_interaction(
                        user_input=user_input,
                        action_type='direct_symbol_analysis',
                        result_summary=f'Directly analyzed {symbol}'
                    )
                    
                    shark_tank_pitch = generate_shark_tank_pitch(company_data)
                    
                    return f"""✅ **Selected: {matching_variant['name']} ({matching_variant['symbol']})**

{formatted_report}

{shark_tank_pitch}"""
                    
                except Exception as e:
                    return f"✅ Selected: {matching_variant['name']} ({matching_variant['symbol']})\n\n❌ Error fetching detailed data: {str(e)}"
    
    # Get enhanced conversation context
    context = ctx.deps.get_recent_context(last_n=3)
    
    # Check if we have pending variants
    has_pending_variants = context['has_pending_variants']
    
    # Check recent actions for multiple options shown
    recent_multiple_options = any(
        action.get('action_type') == 'multiple_options_shown' 
        for action in context['recent_actions']
    )
    
    # Enhanced selection detection
    is_selection = False
    selection_confidence = 0
    
    # Check for number selection (1, 2, 3, etc.)
    if user_input.isdigit():
        is_selection = True
        selection_confidence = 0.9
    
    # Check for specific stock symbol patterns (SYMBOL.NS, SYMBOL.BO)
    elif re.match(r'^[A-Z]+\.(NS|BO)$', user_input.upper()):
        is_selection = True
        selection_confidence = 0.8
    
    # Check for selection phrases with specific symbols
    elif any(phrase in user_input.lower() for phrase in ['i want', 'analyze', 'select', 'choose']) and \
            re.search(r'[A-Z]+\.(NS|BO)', user_input.upper()):
        is_selection = True
        selection_confidence = 0.7
    
    # Check if the input matches any pending variant symbols or names
    elif has_pending_variants:
        for variant in ctx.deps.pending_variants:
            if (user_input.upper() in variant['symbol'].upper() or 
                user_input.upper() in variant['name'].upper() or
                variant['symbol'].upper() in user_input.upper()):
                is_selection = True
                selection_confidence = 0.6
                break
    
    # Decision logic with confidence scoring
    if (has_pending_variants or recent_multiple_options) and is_selection and selection_confidence > 0.5:
        # This is a selection from previous options
        result = select_stock_variant(ctx, user_input)
        
        # Add to conversation context
        ctx.deps.add_interaction(
            user_input=user_input,
            action_type='stock_selection',
            result_summary=f'Selected stock variant: {user_input}'
        )
        
        return result
    else:
        # This is a new stock search
        # Extract stock name from user input
        stock_name = user_input
        # Clean up common phrases more intelligently
        # Remove articles and common words that don't help with stock identification
        cleanup_phrases = [
            'analyze', 'tell me about', 'stock', 'share', 'company', 
            'the', 'a', 'an', 'about', 'information on', 'details of',
            'data for', 'report on', 'analysis of'
        ]
        
        for phrase in cleanup_phrases:
            stock_name = re.sub(rf'\b{phrase}\b', '', stock_name, flags=re.IGNORECASE).strip()
        
        # Remove extra whitespace
        stock_name = ' '.join(stock_name.split())
        
        # If the cleaned name is empty or too short, use original input
        if len(stock_name.strip()) < 2:
            stock_name = user_input
        
        result = validate_and_get_stock(ctx, stock_name)
        
        # Add to conversation context
        ctx.deps.add_interaction(
            user_input=user_input,
            action_type='new_stock_search',
            result_summary=f'Searched for stock: {stock_name}'
        )
        
        return result

@agent.tool
@traceable(name="select_stock_variant")
def select_stock_variant(ctx: RunContext[ConversationState], selection: str) -> str:
    """
    Processes the user's selection from a list of previously presented stock variants.

    Args:
        ctx (RunContext[ConversationState]): The conversation context.
        selection (str): The user's selection, which can be a number (corresponding to the list option), a stock symbol, or a company name.

    Returns:
        str: A formatted string containing the complete stock analysis report and Shark Tank pitch for the selected stock, or an error message if the selection is invalid.
    """
    # Check if we have stored variants from previous validation
    if not hasattr(ctx.deps, 'pending_variants') or not getattr(ctx.deps, 'pending_variants', None):
        return "❌ No stock variants available for selection. Please search for a stock first."
    
    variants = ctx.deps.pending_variants
    selection = selection.strip()
    
    # Try to parse selection as number (1, 2, 3, etc.)
    try:
        choice_num = int(selection)
        if 1 <= choice_num <= len(variants):
            selected_variant = variants[choice_num - 1]
            
            # Store the selected stock
            ctx.deps.stock_symbol = selected_variant['symbol']
            ctx.deps.stock_name = selected_variant['name']
            
            # Clear pending variants
            ctx.deps.pending_variants = None
            
            # Now get the full stock data
            try:
                company_data = StockTools.get_realtime_data(selected_variant['symbol'])
                ctx.deps.company_data = company_data
                
                # Generate the formatted report
                formatted_report = StockTools.format_data_for_report(company_data)
                
                shark_tank_pitch = generate_shark_tank_pitch(company_data)
                
                return f"""✅ **Selected: {selected_variant['name']} ({selected_variant['symbol']})**

{formatted_report}

{shark_tank_pitch}"""
                
            except Exception as e:
                import traceback
                print(f"\n❌ ERROR in select_stock_variant (numeric selection):")
                print(f"Error: {e}")
                print("Full traceback:")
                traceback.print_exc()
                return f"✅ Selected: {selected_variant['name']} ({selected_variant['symbol']})\n\n❌ Error fetching detailed data: {str(e)}"
        else:
            return f"❌ Invalid selection. Please choose a number between 1 and {len(variants)}."
            
    except ValueError:
        # Try to match by symbol or name
        selection_upper = selection.upper()
        
        # First, check for exact symbol match
        exact_match = None
        partial_matches = []
        
        for i, variant in enumerate(variants):
            if variant['symbol'].upper() == selection_upper:
                exact_match = variant
                break
            elif (selection_upper in variant['symbol'].upper() or 
                    selection_upper in variant['name'].upper()):
                partial_matches.append(variant)
        
        # If we found an exact symbol match, use it
        if exact_match:
            selected_variant = exact_match
        # If no exact match but user provided a specific symbol (contains .NS or .BO)
        elif ('.' in selection_upper and (selection_upper.endswith('.NS') or selection_upper.endswith('.BO'))):
            # User asked for a specific symbol that's not in our variants
            # This might happen if they're asking for a different stock after seeing limited options
            # Try to validate this symbol directly
            direct_validation = StockTools.validate_stock(selection.replace('.NS', '').replace('.BO', ''))
            
            if direct_validation.is_valid and direct_validation.stock_symbol.upper() == selection_upper:
                # The symbol exists, use it directly
                ctx.deps.stock_symbol = direct_validation.stock_symbol
                ctx.deps.stock_name = direct_validation.stock_name
                ctx.deps.pending_variants = None
                
                try:
                    company_data = StockTools.get_realtime_data(direct_validation.stock_symbol)
                    ctx.deps.company_data = company_data
                    formatted_report = StockTools.format_data_for_report(company_data)
                    
                    shark_tank_pitch = generate_shark_tank_pitch(company_data)
                    
                    return f"""✅ **Selected: {direct_validation.stock_name} ({direct_validation.stock_symbol})**

{formatted_report}

{shark_tank_pitch}"""
                    
                except Exception as e:
                    import traceback
                    print(f"\n❌ ERROR in select_stock_variant (direct validation):")
                    print(f"Error: {e}")
                    print("Full traceback:")
                    traceback.print_exc()
                    return f"✅ Selected: {direct_validation.stock_name} ({direct_validation.stock_symbol})\n\n❌ Error fetching detailed data: {str(e)}"
            else:
                return f"❌ Stock symbol '{selection}' not found. Please choose from the available options or search for a different stock."
        
        # If we have partial matches, use the first one
        elif partial_matches:
            selected_variant = partial_matches[0]
        else:
            return f"❌ Selection '{selection}' not found. Please choose from the available options by number (1, 2, 3...) or by exact symbol."
        
        # Process the selected variant
        if 'selected_variant' in locals():
            # Store the selected stock
            ctx.deps.stock_symbol = selected_variant['symbol']
            ctx.deps.stock_name = selected_variant['name']
            
            # Clear pending variants
            ctx.deps.pending_variants = None
            
            # Get full stock data and generate report
            try:
                company_data = StockTools.get_realtime_data(selected_variant['symbol'])
                ctx.deps.company_data = company_data
                formatted_report = StockTools.format_data_for_report(company_data)
                
                shark_tank_pitch = generate_shark_tank_pitch(company_data)
                
                return f"""✅ **Selected: {selected_variant['name']} ({selected_variant['symbol']})**

{formatted_report}

{shark_tank_pitch}"""
                
            except Exception as e:
                    import traceback
                    print(f"\n❌ ERROR in select_stock_variant (partial match):")
                    print(f"Error: {e}")
                    print("Full traceback:")
                    traceback.print_exc()
                    return f"✅ Selected: {selected_variant['name']} ({selected_variant['symbol']})\n\n❌ Error fetching detailed data: {str(e)}"
                    import traceback
                    print(f"\n❌ ERROR in select_stock_variant (fallback):")
                    print(f"Error: {e}")
                    print("Full traceback:")
                    traceback.print_exc()
                    return f"✅ Selected: {variant['name']} ({variant['symbol']})\n\n❌ Error fetching detailed data: {str(e)}"
        
        return f"❌ Selection '{selection}' not found. Please choose from the available options by number (1, 2, 3...) or by symbol."

@agent.tool
@traceable(name="validate_and_get_stock")
def validate_and_get_stock(ctx: RunContext[ConversationState], stock_name: str) -> str:
    """
    Validates a stock name or symbol and retrieves its data.

    This tool searches for the given stock. If multiple matching stocks are found, it returns a list of options for the user to choose from.
    If a single valid stock is found, it fetches the full financial data and generates a report.

    Args:
        ctx (RunContext[ConversationState]): The conversation context.
        stock_name (str): The name or ticker symbol of the company or stock to validate (e.g., "Apple", "AAPL", "Reliance Industries").

    Returns:
        str:
            - If multiple matches: A formatted message listing the variants and asking the user to select one.
            - If single match: A complete stock analysis report including company snapshot, financials, and a Shark Tank pitch.
            - If no match: An error message indicating the stock could not be found.
    """
    validation = StockTools.validate_stock(stock_name)
    
    if validation.needs_clarification:
        # Multiple stocks found - store variants and show options
        ctx.deps.pending_variants = validation.variants
        
        # Add to enhanced conversation context
        ctx.deps.add_interaction(
            user_input=stock_name,
            action_type='multiple_options_shown',
            result_summary=f'Found {len(validation.variants)} stock variants for {stock_name}'
        )
        
        variants_text = "\n".join([
            f"{i+1}. **{v['name']}** ({v['symbol']}) - Exchange: {v.get('exchange', 'Unknown')}" 
            for i, v in enumerate(validation.variants)
        ])
        
        return f"""🔍 **Multiple stocks found matching '{stock_name}':**

{variants_text}

Please specify which one you'd like to analyze:
• Type the **number** (1, 2, 3, etc.)
• Or type the stock name with **symbol** 
• Or type part of the **company name**

I'll analyze the stock you choose and provide a complete report with Shark Tank pitch!"""
    
    if validation.is_valid:
        # Single stock found - set state
        ctx.deps.stock_symbol = validation.stock_symbol
        ctx.deps.stock_name = validation.stock_name
        
        # Fetch data and generate pitch directly (no signals, no chaining)
        try:
            print(f"📊 Fetching data for {ctx.deps.stock_symbol}...")
            
            # Fetch real-time data
            company_data = StockTools.get_realtime_data(ctx.deps.stock_symbol)
            ctx.deps.company_data = company_data
            
            print(f"✅ Data fetched successfully for {ctx.deps.stock_name}")
            
            # Get the full formatted report
            formatted_report = StockTools.format_data_for_report(company_data)
            
            # Generate Shark Tank pitch
            shark_tank_pitch = generate_shark_tank_pitch(company_data)
            
            # Create a response that includes both the full report and comprehensive pitch
            combined_output = f"""✓ Found: {validation.stock_name} ({validation.stock_symbol})

{formatted_report}

{shark_tank_pitch}"""
            
            ctx.deps.report_generated = True
            
            print(f"📝 Returning combined output ({len(combined_output)} chars)")
            
            return combined_output
            
        except Exception as e:
            import traceback
            error_msg = str(e)
            print(f"\n❌ ERROR in validate_and_get_stock:")
            print(f"Error: {error_msg}")
            print("Full traceback:")
            traceback.print_exc()
            
            # Provide more helpful error message
            if "404" in error_msg or "not found" in error_msg.lower():
                return f"❌ Could not fetch data for {validation.stock_name} ({validation.stock_symbol}).\n\nThe stock symbol appears to be valid, but I'm having trouble retrieving the financial data. This could be due to:\n• Temporary data provider issues\n• The stock might be delisted or suspended\n• Try using a different exchange suffix (e.g., .NS instead of .BO for Indian stocks)\n\nPlease try again in a moment or try a different stock."
            else:
                return f"❌ Error gathering data for {validation.stock_name} ({validation.stock_symbol}):\n\n{error_msg}\n\nPlease try again or ask about a different stock."
    
    return validation.message

@agent.tool
def debug_conversation_state(ctx: RunContext[ConversationState]) -> str:
    """Debug tool to check conversation state"""
    print(f"🔧 DEBUG: Conversation state check")
    print(f"🔧 Stock symbol: {ctx.deps.stock_symbol}")
    print(f"🔧 Stock name: {ctx.deps.stock_name}")
    print(f"🔧 Company data exists: {bool(ctx.deps.company_data)}")
    print(f"🔧 Conversation history length: {len(ctx.deps.conversation_history)}")
    
    if ctx.deps.company_data:
        return f"✅ Context exists: {ctx.deps.company_data.name} ({ctx.deps.company_data.symbol})"
    else:
        return "❌ No context found"

@agent.tool
@traceable(name="handle_trader_question")
def handle_trader_question(ctx: RunContext[ConversationState], question: str) -> str:
    """
    Handles specific questions about the currently analyzed stock acting as a company executive.

    This tool should only be used AFTER a stock has been successfully analyzed and loaded into the context.

    Args:
        ctx (RunContext[ConversationState]): The conversation context containing the company data.
        question (str): The user's specific question regarding the company's financials, strategy, risks, or performance.

    Returns:
        str: A professional, first-person response from the perspective of a company executive (e.g., CFO/CEO) addressing the user's question with specific data points.
    """
    print(f"🔧 handle_trader_question called with: '{question}'")
    print(f"🔧 Company data exists: {bool(ctx.deps.company_data)}")
    if ctx.deps.company_data:
        print(f"🔧 Current stock: {ctx.deps.company_data.name} ({ctx.deps.company_data.symbol})")
    else:
        print(f"🔧 No company data - this should not happen for follow-up questions!")
    
    if not ctx.deps.company_data:
        print(f"❌ ERROR: handle_trader_question called but no company_data exists!")
        return "Please analyze a stock first before asking questions."
    
    data = ctx.deps.company_data

    # Format numbers properly with dynamic currency detection
    def format_financial_number(value, data_currency_symbol=""):
        if not value:
            return "N/A"
        
        # Detect currency from company data or use generic formatting
        if hasattr(data, 'market_data') and hasattr(data.market_data, 'currency'):
            currency = data.market_data.currency
        else:
            # Default to appropriate currency based on exchange or region
            currency = "₹" if any(x in str(data.symbol) for x in ['.NS', '.BO']) else "$"
        
        # Format in appropriate scale (Crores for INR, Billions for USD)
        if currency == "₹":
            return f"₹{value/1e7:.2f} Cr"
        else:
            return f"${value/1e9:.2f}B"
    
    revenue_str = format_financial_number(data.financials.revenue)
    profit_str = format_financial_number(data.financials.net_profit)
    debt_str = format_financial_number(data.financials.total_debt)
    cashflow_str = format_financial_number(data.financials.free_cash_flow)
    margin_str = f"{data.financials.profit_margin*100:.2f}%" if data.financials.profit_margin else "N/A"
    
    # Generate conversational response based on the question type
    question_lower = question.lower()
    
    # Risk-related questions
    if any(word in question_lower for word in ['risk', 'risks', 'danger', 'concern', 'worry', 'problem']):
        return f"""I'm glad you asked about the risks—understanding them is essential before you commit any capital.

Let me be transparent about the key risk areas for {data.name}. First, we operate in the {getattr(data.market_data, 'sector', 'market')} sector, which naturally comes with its own set of challenges. Market volatility affects our stock price, and economic cycles can impact our revenue streams.

From a financial perspective, we're managing a debt load of {debt_str}, which gives us a debt-to-equity ratio that we monitor closely. While this provides us leverage for growth, it also means we need to maintain strong cash flows to service our obligations. Our current profit margin of {margin_str} shows we're generating solid returns, but margin compression is always a risk if costs rise or competition intensifies.

Operationally, we face regulatory changes that could affect our business model, and we're exposed to supply chain disruptions that could impact our operations. Competition in our space is fierce, and we need to continuously innovate to maintain our market position.

However, I want to emphasize that we're actively managing these risks. We maintain strong liquidity buffers, diversify our revenue streams, and have experienced management teams in place. Our free cash flow of {cashflow_str} gives us flexibility to weather short-term challenges while investing in long-term growth.

The key is balancing these risks against our growth potential and the strength of our market position. We believe our risk management strategies position us well for sustainable long-term performance."""

    # Investment rationale questions
    elif any(word in question_lower for word in ['invest', 'buy', 'purchase', 'why', 'reason', 'rationale']):
        return f"""That's an excellent question, and I appreciate your interest in {data.name}.

Here's why I believe we represent a compelling investment opportunity. We're generating {revenue_str} in annual revenue with a healthy profit margin of {margin_str}, which demonstrates our ability to convert sales into bottom-line results. Our net profit of {profit_str} shows we're not just growing the top line—we're building sustainable profitability.

What really excites me about our investment thesis is our cash generation capability. We're producing {cashflow_str} in free cash flow, which gives us tremendous flexibility. This isn't just paper profits—it's real cash we can use to invest in growth, return to shareholders, or strengthen our balance sheet.

Our position in the {getattr(data.market_data, 'sector', 'market')} sector gives us exposure to long-term growth trends, and we've built competitive advantages that are difficult to replicate. We have strong market share, established customer relationships, and operational expertise that took years to develop.

From a valuation perspective, I believe our current metrics reflect solid fundamentals while still offering upside potential. We're not just asking you to bet on a story—we're showing you a business that's already generating strong returns and has clear pathways for continued growth.

The management team has a proven track record of capital allocation and strategic execution. We've navigated various market cycles and consistently delivered value to our shareholders through disciplined operations and smart investments.

Looking ahead, we see multiple growth drivers that can expand our market opportunity while maintaining our competitive moat. We're committed to delivering sustainable returns while building long-term value for all stakeholders."""

    # Financial performance questions
    elif any(word in question_lower for word in ['revenue', 'profit', 'financial', 'performance', 'earnings', 'money']):
        return f"""I'm pleased to discuss our financial performance—it's one of our key strengths.

We're currently generating {revenue_str} in annual revenue, which reflects our strong market position and customer demand for our products and services. This revenue translates into {profit_str} in net profit, giving us a profit margin of {margin_str}. This shows we're not just focused on growth—we're building a sustainable, profitable business.

Our cash generation is particularly strong, with {cashflow_str} in free cash flow. This is real money we can deploy strategically, whether that's investing in growth opportunities, returning capital to shareholders, or strengthening our financial position.

We maintain a disciplined approach to capital allocation. Our debt level of {debt_str} is manageable and gives us leverage for growth while maintaining financial flexibility. We monitor our debt-to-equity ratios closely and ensure we have adequate liquidity to meet our obligations and fund our operations.

What I'm most proud of is the consistency of our performance. We've built a business model that generates predictable cash flows while maintaining the flexibility to capitalize on growth opportunities. Our margins demonstrate operational efficiency, and our revenue growth shows we're gaining market share in our sector.

Looking at our sector positioning in {getattr(data.market_data, 'sector', 'the market')}, we're well-positioned to benefit from industry trends while maintaining our competitive advantages. Our financial metrics compare favorably to peers, and we continue to invest in capabilities that will drive future performance.

The key is that these aren't just numbers on a spreadsheet—they represent real operational excellence and strategic execution that creates value for our stakeholders."""

    # Competition questions
    elif any(word in question_lower for word in ['compet', 'rival', 'market', 'advantage', 'different']):
        return f"""Great question about our competitive position—it's something we think about every day.

We operate in a dynamic {getattr(data.market_data, 'sector', 'market')} sector where differentiation is crucial. What sets {data.name} apart is our combination of scale, operational efficiency, and strategic positioning. Our revenue of {revenue_str} and profit margin of {margin_str} demonstrate that we're not just competing on price—we're delivering real value that customers are willing to pay for.

Our competitive advantages are built on several pillars. First, we have operational scale that gives us cost advantages and negotiating power with suppliers. Second, we've invested heavily in capabilities and infrastructure that are difficult for competitors to replicate quickly. Third, we have established customer relationships and brand recognition that create switching costs.

From a financial perspective, our free cash flow of {cashflow_str} gives us resources to invest in innovation, expand our market presence, and respond to competitive threats. While our competitors may have similar products or services, few can match our combination of financial strength and operational execution.

We don't take our market position for granted. Competition keeps us sharp and drives continuous improvement. We monitor competitive dynamics closely and adjust our strategies accordingly. Whether that's investing in new technologies, expanding into adjacent markets, or improving our cost structure, we're always looking for ways to strengthen our competitive moat.

The key is that competition isn't just about defending market share—it's about creating value for customers in ways that competitors can't easily match. Our profit margins and cash generation show we're succeeding in that effort, but we know we need to keep innovating to maintain our edge.

Looking ahead, we see opportunities to further differentiate ourselves through strategic investments and operational improvements that will strengthen our competitive position for the long term."""

    # Growth and strategy questions
    elif any(word in question_lower for word in ['growth', 'future', 'strategy', 'plan', 'expand']):
        return f"""I'm excited to talk about our growth strategy—it's where we see the most opportunity for {data.name}.

Our current financial foundation gives us a strong platform for growth. With {revenue_str} in revenue and {cashflow_str} in free cash flow, we have both the market presence and financial resources to execute on our expansion plans.

Our growth strategy focuses on several key areas. First, we're expanding our market presence in existing segments where we have proven capabilities. Our profit margin of {margin_str} shows we can grow profitably, not just for the sake of size. Second, we're investing in innovation and new product development to capture emerging opportunities in our sector.

We're also looking at strategic partnerships and potential acquisitions that can accelerate our growth while leveraging our operational expertise. Our strong balance sheet and cash generation give us flexibility to pursue these opportunities when they align with our strategic objectives.

From a geographic perspective, we see opportunities to expand our footprint in markets where our capabilities and business model can create value. We're taking a disciplined approach—focusing on markets where we can achieve sustainable competitive advantages rather than just chasing revenue growth.

Technology and operational efficiency are also key growth drivers. We're investing in capabilities that will improve our cost structure, enhance customer experience, and create new revenue opportunities. These investments are already showing results in our operational metrics.

The beauty of our growth strategy is that it's not dependent on any single initiative. We have multiple pathways to expand our business while maintaining the financial discipline that has made us successful. Our debt level of {debt_str} is manageable, giving us financial flexibility to fund growth while maintaining a strong balance sheet.

Looking ahead, we're confident in our ability to deliver sustainable growth that creates value for all stakeholders while strengthening our market position."""

    # General/other questions - provide a balanced response
    else:
        return f"""Thank you for that question about {data.name}.

Let me give you a comprehensive view of our company. We're a well-established player in the {getattr(data.market_data, 'sector', 'market')} sector, generating {revenue_str} in annual revenue with a solid profit margin of {margin_str}. This translates to {profit_str} in net profit, demonstrating our ability to convert sales into sustainable earnings.

Our financial position is strong, with {cashflow_str} in free cash flow that gives us significant strategic flexibility. We maintain a manageable debt level of {debt_str}, which provides leverage for growth while keeping our financial risk at appropriate levels.

What I'm most proud of is how we've built a business that balances growth with profitability. We're not just chasing revenue—we're building sustainable competitive advantages that create long-term value. Our market position allows us to generate consistent cash flows while investing in future opportunities.

We operate with a clear strategic focus: delivering value to our customers, maintaining operational excellence, and generating strong returns for our shareholders. Our management team has extensive experience in this sector and a proven track record of navigating various market conditions.

Looking ahead, we see multiple opportunities to expand our business while maintaining the financial discipline that has made us successful. Whether that's through organic growth, strategic partnerships, or operational improvements, we have clear pathways to enhance our market position.

The key is that we're not just managing for the short term—we're building a business that can deliver sustainable performance across different market cycles. Our financial metrics demonstrate this capability, and our strategic investments position us well for continued success.

I'm confident in our ability to continue creating value for all stakeholders while maintaining our strong market position and financial performance."""

@agent.tool
@traceable(name="perform_scenario_analysis")
def perform_scenario_analysis(ctx: RunContext[ConversationState], scenario: str) -> str:
    """
    Performs a hypothetical "what-if" scenario analysis for the currently analyzed company.

    Args:
        ctx (RunContext[ConversationState]): The conversation context containing the company data.
        scenario (str): The hypothetical scenario description provided by the user (e.g., "invalid oil prices", "recession", "new competitor").

    Returns:
        str: A narrative response from the perspective of the CFO, discussing the potential impact of the scenario on the company's financials and strategy.
    """
    if not ctx.deps.company_data:
        return "Please analyze a stock first before running scenarios."
    
    data = ctx.deps.company_data
    
    prompt = f"""You are the CFO of {data.name} responding to a Shark's "what-if" question in a Shark Tank setting.

SHARK'S SCENARIO QUESTION: {scenario}

COMPANY DATA:
- Revenue: {f"${data.financials.revenue/1e9:.2f}B" if data.financials.revenue else "N/A"}
- Net Profit: {f"${data.financials.net_profit/1e9:.2f}B" if data.financials.net_profit else "N/A"}
- Profit Margin: {f"{data.financials.profit_margin*100:.2f}%" if data.financials.profit_margin else "N/A"}
- EBITDA: {f"${data.financials.ebitda/1e9:.2f}B" if data.financials.ebitda else "N/A"}
- Free Cash Flow: {f"${data.financials.free_cash_flow/1e9:.2f}B" if data.financials.free_cash_flow else "N/A"}
- Debt: {f"${data.financials.total_debt/1e9:.2f}B" if data.financials.total_debt else "N/A"}
- Market Cap: {f"${data.market_data.market_cap/1e9:.2f}B" if data.market_data.market_cap else "N/A"}

Respond naturally as a CFO would discuss a scenario with Sharks - conversational, analytical, confident.

RESPONSE STYLE:
- Start naturally: "That's a great scenario to explore", "Let me walk you through what would happen", "Interesting question"
- Speak conversationally about the impact
- Discuss how it would affect revenue, profit, cash flow naturally in sentences
- Explain your strategy to handle it conversationally
- Show confidence in your ability to manage the situation
- NO numbered lists or bullet points
- NO formal sections like "1. Impact Assessment, 2. Quantitative Projections"
- Write as flowing paragraphs like natural speech

Generate your response now as the CFO speaking naturally:
"""
    
    return prompt

@agent.tool
@traceable(name="generate_summary_report")
def generate_summary_report(ctx: RunContext[ConversationState]) -> str:
    """
    Generates a comprehensive summary of the stock analysis and any subsequent Q&A.

    Args:
        ctx (RunContext[ConversationState]): The conversation context containing company data and conversation history.

    Returns:
        str: A structured summary including key financial highlights, pros/cons, future outlook, and an investment consideration verdict.
    """
    if not ctx.deps.company_data:
        return "No stock data available to summarize."
    
    data = ctx.deps.company_data
    
    # Handle conversation_history properly (it contains dicts, not strings)
    history_items = []
    if ctx.deps.conversation_history:
        for item in ctx.deps.conversation_history[-5:]:
            if isinstance(item, dict):
                # Extract meaningful text from the interaction dict
                user_input = item.get('user_input', '')
                result_summary = item.get('result_summary', '')
                if user_input and result_summary:
                    history_items.append(f"User: {user_input} | Result: {result_summary}")
                elif user_input:
                    history_items.append(f"User: {user_input}")
                elif result_summary:
                    history_items.append(f"Result: {result_summary}")
            elif isinstance(item, str):
                history_items.append(item)
            else:
                history_items.append(str(item))
    
    history = "\n".join(history_items) if history_items else "No Q&A history"
    
    prompt = f"""Create a concise investment summary for {data.name}:

COMPANY DATA:
{StockTools.format_data_for_report(data)}

CONVERSATION CONTEXT:
{history}

Provide:
1. Key Financial Highlights (3-4 bullet points)
2. Strengths (2-3 points)
3. Weaknesses/Risks (2-3 points)
4. Future Outlook (1 paragraph)
5. Investment Consideration (neutral, data-driven perspective)

Be concise, factual, and actionable."""
    
    return prompt


class StockAnalysisOrchestrator:
    """Main orchestrator for the stock analysis chatbot with proper message history"""
    
    def __init__(self):
        self.state = ConversationState()
        self.agent = orchestrator_agent
        self._current_key_index = api_key_manager.current_key_index
        self.message_history = []  # Store PydanticAI message history
    
    def _ensure_agent_has_current_key(self):
        """Recreate agent if API key has rotated"""
        if self._current_key_index != api_key_manager.current_key_index:
            print(f"🔄 Recreating agent with rotated API key")
            self.agent = create_orchestrator_agent()
            self._current_key_index = api_key_manager.current_key_index
    
    async def chat(self, user_message: str) -> str:
        """
        Main chat interface with proper PydanticAI message history
        """
        # Debug: Print current state
        print(f"🔧 Chat called with: '{user_message}'")
        print(f"🔧 Current stock: {self.state.stock_symbol}")
        print(f"🔧 Company data exists: {bool(self.state.company_data)}")
        print(f"🔧 Message history length: {len(self.message_history)}")
        
        # Ensure agent has current API key
        self._ensure_agent_has_current_key()
        
        # Apply rate limiting before making API call
        await rate_limiter.wait_if_needed()

        # Run the agent with the user message and message history
        try:
            if self.message_history:
                # Use message history for follow-up conversations
                print(f"🔧 Using message history with {len(self.message_history)} previous messages")
                result = await self.agent.run(user_message, message_history=self.message_history, deps=self.state)
            else:
                # First message in conversation
                print(f"🔧 Starting new conversation")
                result = await self.agent.run(user_message, deps=self.state)
            
            # Success - reset error counters
            rate_limiter.reset_errors()
            api_key_manager.reset_key_errors()
            
            # Update message history with new messages from this interaction
            self.message_history = result.new_messages()
            print(f"🔧 Updated message history: {len(self.message_history)} total messages")
            
        except Exception as e:
            error_msg = str(e)
            
            # Handle 429 rate limit errors with API key rotation
            if "429" in error_msg or "quota" in error_msg.lower() or "resource_exhausted" in error_msg.lower():
                rate_limiter.record_error()
                cooldown_time = api_key_manager.handle_rate_limit_error(error_msg)
                
                # Get status of all keys
                key_status = api_key_manager.get_status()
                
                return f"""❌ API Rate Limit Exceeded - Auto-Rotating Keys

🔄 **Automatic Key Rotation Active**
- Hit rate limit on current key
- Rotated to next available key
- Key cooldown: {cooldown_time}s

{key_status}

💡 **What's Happening:**
- Free tier: 30 requests/minute per key
- System automatically rotates between {len(api_key_manager.api_keys)} keys
- Failed key is in cooldown, using next available key

🚀 **Try Again:** The system has already switched to a fresh key - you can try your request again immediately!

⚙️ Rate limit: {rate_limiter.max_calls} requests per {rate_limiter.time_window} seconds across all keys"""
            
            # Handle 503 overload errors
            elif "503" in error_msg or "overloaded" in error_msg.lower():
                rate_limiter.record_error()
                # Try rotating key for overload errors too
                api_key_manager.handle_rate_limit_error("503 overload")
                return f"""❌ Model Overloaded - Rotated to Different Key

The AI model was overloaded. I've rotated to a different API key.

{api_key_manager.get_status()}

🚀 **Try Again:** You can retry your request immediately with the new key."""
            
            # Other errors
            else:
                return f"❌ Error: {error_msg}"

        # Extract the agent's final text response
        print(f"Result type: {type(result)}")
        
        # Get the clean response from result.data (this is the agent's final output)
        if hasattr(result, 'data'):
            response = result.data
            print(f"Response from result.data: {type(response)}, length: {len(str(response))}")
        elif hasattr(result, 'output'):
            response = result.output
            print(f"Response from result.output: {type(response)}, length: {len(str(response))}")
        else:
            # Fallback if neither exists
            response = str(result)
            print(f"Fallback response: {type(response)}, length: {len(str(response))}")
        
        # CRITICAL FIX: If response is a dict (structured data), it means the agent
        # returned structured output instead of text. This shouldn't happen.
        if isinstance(response, dict):
            print(f"❌ ERROR: Response is dict, not string!")
            print(f"Dict keys: {list(response.keys())[:5]}")
            # The agent is misconfigured or returning wrong format
            # Return an error message
            response = "I encountered an issue with the response format. The system returned structured data instead of formatted text. Please try again."
        
        # Only use fallback if response is VERY short (likely an error)
        if self.state.company_data and not self.state.report_generated:
            response_length = len(response)
            
            # Only fallback if response is extremely short (< 200 chars = likely error)
            if response_length < 200:
                print(f"⚠️ Response too short ({response_length} chars), using fallback")
                response = StockTools._generate_static_pitch(self.state.company_data)
            else:
                print(f"✅ LLM generated response ({response_length} chars)")
            
            # Mark that we've shown the report
            self.state.report_generated = True
        
        # Clean up the response
        import re
        response = re.sub(r'</?div[^>]*>', '', response)  # Remove <div> and </div>
        response = re.sub(r'<[^>]+>', '', response)  # Remove any other HTML tags
        
        # Remove markdown code blocks (```json, ```python, etc.)
        response = re.sub(r'```[a-z]*\n', '', response)  # Remove opening code blocks
        response = re.sub(r'```', '', response)  # Remove closing code blocks
        
        # CRITICAL: Remove any JSON-like structures that start with tool_outputs
        # This is the main issue - the agent is including raw tool output
        if 'tool_outputs' in response:
            # Find the end of the JSON structure (look for the closing brace)
            # Then find where the actual formatted content starts
            markers = [
                '🔍 **Multiple stocks found',  # For multiple stock options
                '🏢 COMPANY SNAPSHOT',
                '📊 COMPREHENSIVE STOCK ANALYSIS', 
                'Here is the stock analysis',
                '🤖 AI Analyst',
                '✓ Found:'
            ]
            for marker in markers:
                if marker in response:
                    # Extract everything from the marker onwards
                    response = response[response.index(marker):]
                    break
        
        # Also check for raw JSON at the start
        if response.startswith('{') or response.startswith('tool_outputs'):
            # Find the first emoji or formatted marker
            import re
            match = re.search(r'[🔍🏢📊🤖✓🦈📋💰📈🏆🎯📰]', response)
            if match:
                response = response[match.start():]
        
        response = response.strip()

        return response
    
    def reset(self):
        """Reset conversation state and message history"""
        self.state = ConversationState()
        self.message_history = []  # Clear PydanticAI message history
        print("🔄 Conversation state and message history reset")
    
    def get_api_key_status(self):
        """Get current status of all API keys"""
        return api_key_manager.get_status()
    
    def force_rotate_key(self):
        """Manually rotate to next API key"""
        old_key = api_key_manager.current_key_index + 1
        api_key_manager._rotate_to_next_available_key()
        new_key = api_key_manager.current_key_index + 1
        return f"🔄 Manually rotated from key {old_key} to key {new_key}"
    
    def get_conversation_summary(self):
        """Get a summary of the current conversation"""
        return {
            'message_count': len(self.message_history),
            'has_company_data': bool(self.state.company_data),
            'current_stock': self.state.stock_symbol,
            'stock_name': self.state.stock_name
        }
        response = re.sub(r'```', '', response)  # Remove closing code blocks
        
        # # Remove tool output markers if present
        # response = re.sub(r'\*\*Tool:\*\*.*?\n', '', response)
        # response = re.sub(r'\*\*Input:\*\*.*?\n', '', response)
        # response = re.sub(r'\*\*Output:\*\*.*?\n', '', response)
        
        # CRITICAL: Remove any JSON-like structures that start with tool_outputs
        # This is the main issue - the agent is including raw tool output
        if 'tool_outputs' in response:
            # Find the end of the JSON structure (look for the closing brace)
            # Then find where the actual formatted content starts
            markers = [
                '🔍 **Multiple stocks found',  # For multiple stock options
                '🏢 COMPANY SNAPSHOT',
                '📊 COMPREHENSIVE STOCK ANALYSIS', 
                'Here is the stock analysis',
                '🤖 AI Analyst',
                '✓ Found:'
            ]
            for marker in markers:
                if marker in response:
                    # Extract everything from the marker onwards
                    response = response[response.index(marker):]
                    break
        
        # Also check for raw JSON at the start
        if response.startswith('{') or response.startswith('tool_outputs'):
            # Find the first emoji or formatted marker
            import re
            match = re.search(r'[🔍🏢📊🤖✓🦈📋💰📈🏆🎯📰]', response)
            if match:
                response = response[match.start():]
        
        response = response.strip()

        return response
    
    def reset(self):
        """Reset conversation state"""
        self.state = ConversationState()
    
    def get_api_key_status(self):
        """Get current status of all API keys"""
        return api_key_manager.get_status()
    
    def force_rotate_key(self):
        """Manually rotate to next API key"""
        old_key = api_key_manager.current_key_index + 1
        api_key_manager._rotate_to_next_available_key()
        new_key = api_key_manager.current_key_index + 1
        return f"🔄 Manually rotated from key {old_key} to key {new_key}"
