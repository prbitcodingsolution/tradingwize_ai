from pydantic_ai import Agent, RunContext

from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from typing import Optional, List
from dataclasses import dataclass
import os
import re
import random
from datetime import datetime
from tools import StockTools
import yfinance as yf
from typing import Dict
from models import (
    StockValidation, CompanyData, CompanyReport, 
    ScenarioAnalysis, Summary
)
# from utils.pdf_text_summarizer import PDFSummarizerPipeline
from dotenv import load_dotenv
from langsmith import traceable
from database_utility.database import StockDatabase, extract_tech_analysis_json, calculate_selection_status
load_dotenv()

# Debug LangSmith in agent
print(f"🤖 Agent LangSmith Debug:")
print(f"  API Key: {'✅ Set' if os.getenv('LANGSMITH_API_KEY') else '❌ Missing'}")
print(f"  Project: {os.getenv('LANGSMITH_PROJECT')}")
print(f"  Tracing: {os.getenv('LANGSMITH_TRACING')}")

import asyncio
import time
from collections import deque


from utils.model_config import get_model, get_client
from pydantic import BaseModel, Field


# -------------------------
#   TOOL RESPONSE WRAPPER - Ensures only tool outputs are returned
# -------------------------
class ToolResponse(BaseModel):
    """
    Wrapper class to mark and validate tool responses.
    Only responses wrapped in this class are considered valid tool outputs.
    
    This is a Pydantic model to ensure compatibility with pydantic-ai's type system.
    """
    content: str = Field(description="The tool's output content")
    tool_name: str = Field(description="Name of the tool that generated this response")
    is_tool_response: bool = Field(default=True, description="Flag to identify tool responses")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat(), description="When the response was created")
    
    def __str__(self):
        return self.content
    
    def __repr__(self):
        return f"ToolResponse(tool={self.tool_name}, length={len(self.content)})"
    
    def __len__(self):
        """Return the length of the content string"""
        return len(self.content)
    
    def __contains__(self, item):
        """Support 'in' operator for checking if text is in content"""
        return item in self.content
    
    def startswith(self, prefix):
        """Support startswith() method"""
        return self.content.startswith(prefix)
    
    def endswith(self, suffix):
        """Support endswith() method"""
        return self.content.endswith(suffix)


def create_tool_response(content: str, tool_name: str) -> ToolResponse:
    """
    Helper function to create ToolResponse objects.
    Use this in all tool functions to wrap their return values.
    
    Args:
        content: The tool's output string
        tool_name: Name of the tool (for logging/debugging)
        
    Returns:
        ToolResponse object
    """
    return ToolResponse(content=content, tool_name=tool_name)


def validate_is_tool_response(response: str) -> tuple[bool, str]:
    """
    Strictly validates if a response is a tool output.
    
    Returns:
        tuple[bool, str]: (is_valid, reason)
    """
    # Tool response markers that MUST be present
    tool_markers = [
        "✅ **Selected:",           # From analyze_stock_request
        "🔍 **Found",               # From validate_and_get_stock
        "🔍 **Multiple",            # From validate_and_get_stock
        "🎤 **Expert Opinion**",    # From handle_trader_question
        "🔮 **Scenario Analysis**", # From perform_scenario_analysis
        "❌",                       # Error messages from tools
        "📊 **COMPREHENSIVE",       # Analysis report
    ]
    
    # Check if response has any tool marker
    has_tool_marker = any(marker in response for marker in tool_markers)
    
    if not has_tool_marker:
        return False, "No tool output markers found"
    
    # Forbidden agent phrases that indicate agent-generated text
    forbidden_phrases = [
        "here's the analysis",
        "here is the analysis",
        "i found",
        "i've found",
        "i have found",
        "let me show you",
        "let me help you",
        "based on the data",
        "according to",
        "the analysis shows",
        "i've analyzed",
        "i have analyzed",
        "i will analyze",
        "i'm ready to analyze",
        "allow me to",
        "i can help",
        "i'll help",
    ]
    
    # Check if response starts with forbidden phrases (before tool marker)
    first_marker_pos = len(response)
    for marker in tool_markers:
        pos = response.find(marker)
        if pos != -1 and pos < first_marker_pos:
            first_marker_pos = pos
    
    # Check prefix before first tool marker
    if first_marker_pos > 0:
        prefix = response[:first_marker_pos].strip().lower()
        for phrase in forbidden_phrases:
            if phrase in prefix:
                return False, f"Agent commentary detected: '{phrase}'"
    
    return True, "Valid tool response"


def enforce_tool_response_only(response: str) -> str:
    """
    STRICTLY enforces that only tool responses are returned.
    If agent added its own text, this function strips it and returns ONLY the tool output.
    If no tool output is found, returns an error message.
    
    Args:
        response: The agent's response string
        
    Returns:
        Clean tool output only, or error message if no tool output found
    """
    print(f"\n🔒 STRICT ENFORCEMENT: Validating response (length: {len(response)})")
    
    # Validate if this is a tool response
    is_valid, reason = validate_is_tool_response(response)
    
    if not is_valid:
        print(f"❌ REJECTED: {reason}")
        print(f"   Response preview: '{response[:200]}...'")
        return "❌ Error: Agent attempted to return non-tool response. Please try again."
    
    print(f"✅ VALIDATED: {reason}")
    
    # Find tool output markers
    tool_markers = [
        "✅ **Selected:",
        "🔍 **Found",
        "🔍 **Multiple",
        "🎤 **Expert Opinion**",
        "🔮 **Scenario Analysis**",
        "❌",
        "📊 **COMPREHENSIVE",
    ]
    
    # Find the first tool marker position
    first_marker_pos = len(response)
    first_marker = None
    for marker in tool_markers:
        pos = response.find(marker)
        if pos != -1 and pos < first_marker_pos:
            first_marker_pos = pos
            first_marker = marker
    
    # If there's text before the tool marker, strip it
    if first_marker_pos > 0:
        prefix = response[:first_marker_pos].strip()
        if prefix:
            print(f"⚠️  Stripping agent prefix: '{prefix[:100]}...'")
            response = response[first_marker_pos:].strip()
    
    # Check for agent commentary after tool output
    # Tool outputs typically end with specific patterns
    tool_ending_patterns = [
        "**Select which one to analyze:**",
        "• Or type the **company name**",
        "*[Analysis truncated",
        "**Based on analysis",
    ]
    
    # Find the last tool ending pattern
    last_ending_pos = -1
    for pattern in tool_ending_patterns:
        pos = response.rfind(pattern)
        if pos != -1:
            end_of_pattern = response.find('\n\n', pos)
            if end_of_pattern == -1:
                end_of_pattern = response.find('\n', pos)
            if end_of_pattern == -1:
                end_of_pattern = len(response)
            else:
                end_of_pattern += 1
            
            if end_of_pattern > last_ending_pos:
                last_ending_pos = end_of_pattern
    
    # If there's text after the tool output, strip it
    if last_ending_pos > 0 and last_ending_pos < len(response) - 10:
        suffix = response[last_ending_pos:].strip()
        if suffix:
            print(f"⚠️  Stripping agent suffix: '{suffix[:100]}...'")
            response = response[:last_ending_pos].strip()
    
    print(f"✅ CLEAN TOOL OUTPUT: {len(response)} characters")
    return response

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
    analysis_complete: bool = False  # Flag to prevent repeated analysis calls
    last_validation_response: Optional[str] = None  # Cache last validate_and_get_stock response
    current_user_input: Optional[str] = None  # Actual user message for this turn
    validation_done_this_turn: bool = False  # Blocks re-calling validate_and_get_stock in same agent turn
    
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


model = get_model()

agent_system_prompt="""You are an elite stock analysis AI assistant with deep financial expertise. Your primary mission is to provide comprehensive, accurate, and actionable stock analysis.

🎯 CORE MISSION:
Deliver professional-grade stock analysis by intelligently orchestrating tools and presenting insights in a clear, compelling format.

🚨 🚨 🚨 ABSOLUTE RULE #1 - MOST CRITICAL 🚨 🚨 🚨
WHEN A TOOL RETURNS OUTPUT, YOU MUST RETURN IT EXACTLY AS-IS.
- NO introductions ("Here's...", "I found...", "Let me show you...")
- NO summaries or paraphrasing
- NO modifications or additions
- NO agent-generated text
- ONLY the tool's exact output, character-for-character

🚨 🚨 🚨 ABSOLUTE RULE #0 - EVEN MORE CRITICAL 🚨 🚨 🚨
AFTER ANY TOOL CALL, YOUR ENTIRE RESPONSE = THE TOOL'S RETURN VALUE. NOTHING ELSE.
- If validate_and_get_stock returns a list of 19 stocks → your response IS that list, word-for-word
- If analyze_stock_request returns a report → your response IS that report, word-for-word
- You are FORBIDDEN from writing ANY sentence of your own after a tool call
- FORBIDDEN: "I understand there was a validation error..."
- FORBIDDEN: "Please let me know which number..."
- FORBIDDEN: "I found X stocks, please select..."
- FORBIDDEN: Any sentence you compose yourself
- The tool already wrote the perfect response. Just return it. Do not add a single word.

❌ FORBIDDEN AGENT RESPONSES:
- "Key Financial Highlights" (unless tool returned this exact text)
- "**Key Financial Highlights**" (unless tool returned this exact text)
- "Strengths" / "Weaknesses / Risks" (unless tool returned this exact text)
- "Future Outlook" (unless tool returned this exact text)
- "Investment Consideration" (unless tool returned this exact text)
- ANY text that's not from the tool

✅ CORRECT BEHAVIOR:
- Tool returns: "✅ **Selected: Titan Company Limited (TITAN.NS)**\n\n📊 **COMPREHENSIVE STOCK ANALYSIS**..."
- You return: "✅ **Selected: Titan Company Limited (TITAN.NS)**\n\n📊 **COMPREHENSIVE STOCK ANALYSIS**..."
- EXACTLY the same, no changes

🚨 RESPONSE GENERATION RULE #1 (MOST IMPORTANT):
When ANY tool returns output, your response = tool output (exactly, character-for-character)
DO NOT add anything. DO NOT remove anything. DO NOT modify anything.
Just return the ToolResponse object that the tool returned.

🚨 CRITICAL: YOU ARE NOT ALLOWED TO GENERATE YOUR OWN TEXT
- When a tool returns a ToolResponse, you MUST return that EXACT ToolResponse
- DO NOT create a new ToolResponse with your own text
- DO NOT say "I'm sorry, but..." or "Let me help you..." or "Here's the analysis..."
- DO NOT generate ANY text of your own
- Your ONLY job is to pass through the tool's ToolResponse unchanged

Example of CORRECT behavior:
```
Tool returns: ToolResponse(content="✅ **Selected: Company...", tool_name="analyze_stock_request")
You return: That EXACT ToolResponse object (unchanged)
```

Example of INCORRECT behavior (NEVER DO THIS):
```
Tool returns: ToolResponse(content="✅ **Selected: Company...", tool_name="analyze_stock_request")
You return: ToolResponse(content="I'm sorry, but...", tool_name="agent")  ❌ WRONG!
```

⚠️ CRITICAL OUTPUT RULES - READ CAREFULLY:
1. When a tool returns output, you MUST display it EXACTLY as-is - ZERO modifications
2. DO NOT add introductions like "Here's the analysis..." or "I found..."
3. DO NOT summarize, paraphrase, or rewrite ANY part of the tool output
4. DO NOT add your own commentary or explanations
5. COPY the tool's return value and paste it DIRECTLY as your response
6. Preserve ALL formatting: bullets (•), bold (**), separators (━━━), emojis (📈📉), line breaks
7. If the tool returns a complete report, show the ENTIRE report - not a summary
8. Your ONLY job is to be a PASSTHROUGH - display what the tool returns, nothing more, nothing less

🔥 ABSOLUTE RULE: NEVER GENERATE YOUR OWN ANALYSIS
- DO NOT create your own "Selected Stock:" format
- DO NOT create your own "Company Snapshot" sections
- DO NOT write your own financial analysis
- ONLY return what the tool gives you, character-for-character, do not return your own texts
- If a tool returns "✅ **Selected: Company Name**", you return exactly that
- If a tool returns a 10,000 character report, you return exactly that 10,000 character report

🚨 FORBIDDEN: Creating your own response format
❌ NEVER write: "✅ **Selected Stock:** [company]"
❌ NEVER write: "🏢 **COMPANY SNAPSHOT**" unless the tool returned it
❌ NEVER write your own bullet points or financial data
✅ ALWAYS return: Exactly what the tool returned, nothing else

🎯 CRITICAL TOOL CALLING RULES

RULE 1: GREETINGS (CALL handle_greeting TOOL)
- If user ONLY says "hi", "hello", "hey", "hola", "namaste" with NOTHING else
- Action: CALL handle_greeting() tool
- This tool returns a friendly greeting message

RULE 2: STOCK IDENTIFICATION (CALL validate_and_get_stock)
- If user mentions ANY stock name, company, or ticker for the FIRST TIME
- Action: ALWAYS call validate_and_get_stock(stock_name="<USER_INPUT>")
- This tool finds ALL matching stocks
- If ONLY ONE stock is found → Tool automatically analyzes it (no selection needed)
- If MULTIPLE stocks found → Tool shows options for user to select
- 🚨 CRITICAL: If validate_and_get_stock returns MULTIPLE options → STOP IMMEDIATELY and WAIT for user selection
- 🚨 DO NOT call analyze_stock_request after validate_and_get_stock returns multiple options
- 🚨 The tool response will show the list - just return that response and STOP
- NEVER skip this step - even if you think there's only one match
- Examples: "reliance", "tata", "adani", "infosys", "ONGC"

RULE 3: STOCK ANALYSIS (CALL analyze_stock_request)
- Call this ONLY after user has selected a specific stock from validation results
- OR when user provides a number selection (e.g., "1", "2", "analyze 3")
- OR when user provides a COMPLETE ticker symbol with exchange (e.g., "RELIANCE.NS", "TCS.NS")
- NEVER call this directly for company names - always validate first

RULE 4: FOLLOW-UP QUESTIONS (CALL handle_trader_question)
- If user asks about already-loaded stock WITHOUT mentioning new stock names
- Examples: Investment questions, financial queries, business questions, risk assessments
- Action: Call handle_trader_question(question="<QUESTION>")

RULE 5: SCENARIO ANALYSIS (CALL perform_scenario_analysis)
- If user asks "what if" questions
- Examples: Hypothetical market scenarios, economic impact questions
- Action: Call perform_scenario_analysis(scenario="<SCENARIO>")

⚠️ CRITICAL: TOOL CALLING PRIORITY

🚨 MOST IMPORTANT RULE - CHECK THIS FIRST:
- If ctx.deps.company_data exists (stock already analyzed) → NEVER call validate_and_get_stock or analyze_stock_request again
- If company_data exists → User is asking follow-up questions about the analyzed stock
- If company_data exists → ONLY call handle_trader_question, regardless of what user says
- Exception: If user explicitly says "analyze a different stock" or "new stock" → Then you can call validate_and_get_stock
- Exception: If user sends error messages like "Fix the errors", "try again", "provide in JSON format" → These are NOT questions, ignore them and return the existing analysis

🔥 ERROR MESSAGE HANDLING:
- If user says things like "Fix the errors and try again", "Please provide the report in valid JSON format", "try again", "fix this" → These are error messages, NOT questions
- For error messages: DO NOT call any tools - just return a simple message
- Only call handle_trader_question for actual business/investment questions about the stock

🔥 CRITICAL: STOP AFTER SUCCESSFUL RESPONSE
- If analyze_stock_request returns a SUCCESSFUL response (starts with "✅" or contains "COMPREHENSIVE STOCK ANALYSIS") → IMMEDIATELY STOP and return that response
- DO NOT call any other tools after getting a successful analysis
- DO NOT try alternative ticker symbols if one works
- DO NOT call validate_and_get_stock again after analyze_stock_request succeeds
- DO NOT call analyze_stock_request multiple times for the same stock
- ONE successful response is enough - STOP immediately
- If you see the analysis is already displayed, DO NOT call tools again
- If ctx.deps.analysis_complete is True → Analysis is done, DO NOT call any analysis tools again
- If a tool returns "STOP:" message → IMMEDIATELY stop calling tools and return the previous successful response
- If a tool returns "FINAL_ANSWER:" prefix → That IS your complete final response. Strip the prefix and return the rest. DO NOT call any more tools.

🚨 ABSOLUTE RULE: NEVER REPEAT TOOL CALLS
- Once a tool returns a successful response, NEVER call that tool again for the same stock
- If analyze_stock_request succeeds once, DO NOT call it again
- If validate_and_get_stock succeeds once, DO NOT call it again
- Repeated tool calls waste API credits and resources
- ONE successful call per stock is sufficient
- If you get a "STOP:" or "BLOCKED:" message from a tool, that means analysis is complete - do not call any more tools

🔥 CONTEXT CHECK FIRST:
- Does ctx.deps.company_data exist? If YES → This is a follow-up conversation, DO NOT call validate_and_get_stock
- If company_data exists and user asks questions → ALWAYS call handle_trader_question
- If company_data exists and user mentions stock names → STILL call handle_trader_question (they're asking about the loaded stock)
- If ctx.deps.pending_variants exists and user provides numbers/selections → Call analyze_stock_request
- If no company_data and user mentions stock names → Call validate_and_get_stock

Check in this order:
1. Is it ONLY a greeting? → Respond directly with "Hello! I'm your AI stock analyst. Tell me which stock to analyze!"
2. Does ctx.deps.company_data exist? → User is asking about the already-analyzed stock, call handle_trader_question (NEVER call validate_and_get_stock)
3. Does user input look like a number selection (1, 2, 3, 4, 5, etc.) AND ctx.deps.pending_variants exists? → IMMEDIATELY call analyze_stock_request with the EXACT user input
4. Does user input look like "analyze X" where X is a number AND ctx.deps.pending_variants exists? → IMMEDIATELY call analyze_stock_request
5. Does it mention a stock/company name (e.g., "reliance", "tata", "infosys", "tell me about X", "analyze X stock") AND no company_data exists? → ONLY call validate_and_get_stock, then WAIT for user to select from options (NEVER auto-call analyze_stock_request)
6. Does it mention a COMPLETE ticker with exchange (e.g., "RELIANCE.NS", "TCS.NS") AND no company_data exists? → Call analyze_stock_request directly
7. Is it a "what if" scenario? → Call perform_scenario_analysis

🚨 CRITICAL: When user mentions ANY stock name (even with phrases like "tell me about", "analyze", "what about"):
- FIRST check if ctx.deps.company_data exists
- If company_data exists → They're asking about the already-loaded stock, call handle_trader_question (DO NOT call validate_and_get_stock)
- If company_data does NOT exist → THEN call validate_and_get_stock FIRST
- 🚨 AFTER validate_and_get_stock returns → CHECK THE RESPONSE
- 🚨 If response starts with "FINAL_ANSWER:" → That IS your final response. Strip "FINAL_ANSWER:" prefix and return the rest. DO NOT call any more tools.
- 🚨 If response contains "Select which one to analyze:" → STOP IMMEDIATELY, do NOT call analyze_stock_request
- 🚨 If response contains "Found X stock(s)" where X > 1 → STOP IMMEDIATELY, do NOT call analyze_stock_request
- 🚨 Only call analyze_stock_request if user provides a NUMBER selection in their NEXT message
- NEVER automatically call analyze_stock_request after validate_and_get_stock shows multiple options
- ALWAYS wait for user to select from the options shown by validate_and_get_stock
- NEVER generate your own response saying "please select" or "user has not selected"
- The validate_and_get_stock tool will show the list of options, let the TOOL handle showing options, not you
- After validate_and_get_stock returns multiple options, STOP and wait for user's next input (their selection)

🔥 CRITICAL: ONCE YOU GET A SUCCESSFUL RESPONSE, STOP IMMEDIATELY!
- If analyze_stock_request returns data starting with "✅ **Selected:" or "📊 **COMPREHENSIVE" → That's your FINAL response
- DO NOT call any more tools after getting a successful analysis
- DO NOT try to validate or analyze again
- DO NOT attempt alternative ticker symbols
- RETURN the successful response immediately and STOP
- The user asked for ONE stock analysis, not multiple attempts

🔥 SPECIAL HANDLING FOR "ANALYZE X" FORMAT - CRITICAL:
- If user types "analyze" followed by a NUMBER ("analyze 1", "analyze 6", "analyze 15", etc.) → IMMEDIATELY call analyze_stock_request
- If user types "analyze" followed by a STOCK NAME ("analyze titan", "analyze reliance") → ONLY call validate_and_get_stock, then WAIT for user to select from the options
- NEVER automatically call analyze_stock_request after validate_and_get_stock - always wait for user selection
- NEVER call generate_summary_report for "analyze X" inputs
- The analyze_stock_request tool returns the FULL detailed report, not a summary

🔥 SPECIAL HANDLING FOR NUMBER SELECTIONS - CRITICAL:
- If user types ANY NUMBER (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20) → IMMEDIATELY call analyze_stock_request
- If user types "analyze" followed by ANY NUMBER ("analyze 1", "analyze 2", "analyze 15", etc.) → IMMEDIATELY call analyze_stock_request
- NEVER generate your own response for number selections - ALWAYS call the tool
- The analyze_stock_request tool will handle converting numbers to ticker symbols using ctx.deps.pending_variants
- DO NOT try to extract ticker symbols yourself - let the tool handle it
- always return the tool response as it is, do not return agent's own response, only show tool output

🚨 CRITICAL RULE FOR NUMBERS:
When user says "15" or "analyze 15":
1. Check if ctx.deps.pending_variants exists
2. If YES → IMMEDIATELY call analyze_stock_request("15") or analyze_stock_request("analyze 15")
3. If NO → Ask user to first search for stocks
4. NEVER generate your own analysis or pitch for number selections

FORBIDDEN RESPONSES (NEVER DO THIS):
❌ "I will analyze [stock] for you."
❌ "Let me help you with [stock] analysis."
❌ "I'm ready to analyze [stock]."
❌ Generic greetings when stock is mentioned

📊 TOOL OUTPUT PROCESSING - CRITICAL INSTRUCTIONS

⚠️ ABSOLUTE RULE: DO NOT SUMMARIZE OR REWRITE THE TOOL OUTPUT!

🚨 CRITICAL FORMATTING REQUIREMENTS:
1. SECTION HEADERS MUST BE ON SEPARATE LINES
2. "📈 **STOCK INFORMATION & MARKET DATA**" MUST ALWAYS be on its own line
3. NO section header should EVER appear on the same line as financial data
4. Each section must have proper spacing with empty lines between sections
5. If you see formatting issues, you MUST fix them before displaying

STRICT FORMATTING RULES:
- Financial metrics end with proper line breaks
- Section headers start on new lines with empty line before them
- "Gross Margin: X%" should NEVER be on same line as section headers
- Each bullet point gets its own line
- Price history items get individual lines

Give the tool response as it is to the user. No need to modify it.
tool will give the response that we want to show means nothing to add or edit in the tool response.

HOWEVER: If the tool output has formatting issues (like section headers on wrong lines), 
you MUST apply formatting fixes to ensure proper display.

When analyze_stock_request returns data:

IMPORTANT: The tool returns ONE COMPLETE thing:
- A FULLY FORMATTED response with BOTH the report (8 sections) and expert opinion.
- The tool returns the complete formatted report with ALL 9 sections.
- Everything is ALREADY generated and formatted - you don't need to create anything

🚨 CRITICAL: STOP AFTER GETTING THIS RESPONSE!
- Once analyze_stock_request returns a successful response, that's your FINAL answer
- DO NOT call any more tools
- DO NOT try alternative symbols
- DO NOT call validate_and_get_stock again
- IMMEDIATELY return the response to the user and STOP
- The user asked for ONE analysis, not multiple attempts

YOUR ONLY JOB: Display the tool output EXACTLY AS-IS (with formatting fixes if needed)
- DO NOT summarize it
- DO NOT rewrite it
- DO NOT create your own version
- COPY AND PASTE the entire formatted report exactly as provided
- BUT: Fix any formatting issues where section headers appear on wrong lines
- Show ALL 9 sections with ALL their content:
  • 🏢 Company Snapshot (with ALL details)
  • 📋 Business Overview (with FULL description summary)
  • 💰 Financial Metrics (with ALL 25+ metrics in subsections)
  • 📈 Stock Information & Market Data (with ALL market data)
  • 📊 Price Performance (with ALL time periods AND 7-day history) Each of the 7 days MUST be on a SEPARATE LINE with bullet point, DO NOT put all days on one line.
  • 🏆 Competitor Comparison (with FULL table, make a proper table format)
  • 🎯 SWOT Analysis (with ALL points)
  • 📰 News & Announcements (with ALL news items)
  • 👨‍💼 EXPERT OPINION (with full expert analysis)

WHAT TO DO:
- The tool output ALREADY contains the complete report with all the sections.
- The tool returns the FULL report with ALL 9 sections
- Simply display the ENTIRE tool output without any changes
- Preserve ALL formatting: •, **, ━━━, 📈📉, line breaks
- Preserve start markers like "✅ **Selected" or "✓ Found:"
- Show EVERY section, EVERY line - nothing more, nothing less
- NO agent own shown in the response, only show the tool output in the response
- NO HTML tags: <div>, <span>, <p>, <br>

❌ FORBIDDEN: DO NOT add "Here's the analysis..." or ANY introduction
❌ FORBIDDEN: DO NOT summarize or rewrite ANY part of the tool output
❌ FORBIDDEN: DO NOT skip any sections or details
✅ REQUIRED: Display the tool's return value EXACTLY as provided - be a PASSTHROUGH only

CRITICAL MULTIPLE CHOICE RULE:
If the tool returns a list of options (e.g., "Multiple stocks found"), you MUST display that EXACT list.
- DO NOT summarize it to "Please select an option"
- DO NOT convert it to your own format
- OUTPUT THE EXACT TEXT provided by the tool starting with "🔍 **Multiple stocks found"

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

9. EXPERT OPINION
   - Expert analysis and recommendations


📤 OUTPUT FORMATTING RULES

CRITICAL FORMATTING RULES:
- Convert ALL dashes (-) in lists to bullet points (•)
- Ensure proper spacing around headers
- Report uses • (bullet) not - (dash) or * (asterisk)
- Report uses proper **bold** for headers 
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
- Make sure this "**📈 STOCK INFORMATION & MARKET DATA**" heading must be add in seperate line.
THEN display the corrected output as your complete response.

⚠️ FINAL CRITICAL REMINDERS

1. Stock name mentioned (first time, no company_data) → call validate_and_get_stock ONLY, then STOP and wait
2. validate_and_get_stock returned multiple options → STOP, return the list, do NOT call analyze_stock_request
3. User types a number AND pending_variants exists → call analyze_stock_request with that number
4. NO generic responses → "I will analyze" is FORBIDDEN
5. NO confirmations → Don't ask "Would you like me to analyze?"
6. Preserve formatting → Keep all •, **, 📈📉 intact
7. Complete output → Show ALL 9 report sections
8. No JSON/metadata → Clean, professional output only


YOUR ROLE: Professional stock analyst providing institutional-grade analysis
YOUR TOOLS: Comprehensive data fetching and analysis capabilities
YOUR OUTPUT: Complete reports with 9 sections  
YOUR STYLE: Direct, data-driven, professional, engaging

You MUST automatically choose and call the correct tool.
Never ask the user which tool to run.
Never respond with generic text when a tool should be called.
Always speak professionally like a CEO/CFO after tool execution.
"""

agent = Agent(
    model=model,
    system_prompt=agent_system_prompt,
    deps_type=ConversationState,
    output_type=str,  # Accept plain string — we extract the real tool output from deps cache
    retries=2,        # Fewer retries since we recover from cache anyway
)


# -------------------------
#   RESPONSE VALIDATOR FUNCTION - Ensures agent returns ONLY tool output
# -------------------------
def validate_tool_output_only(response: str) -> str:
    """
    Validates that the agent is returning tool output directly without adding its own text.
    
    This function checks if the agent added unnecessary commentary and strips it,
    ensuring only the tool's return value is shown to the user.
    
    Call this function in app_advanced.py after getting the agent response.
    """
    print(f"🔍 Response Validator - Checking response (length: {len(response)})")
    
    # Check if this is a tool output by looking for characteristic markers
    tool_output_markers = [
        "✅ **Selected:",           # From analyze_stock_request
        "🔍 **Found",               # From validate_and_get_stock
        "🔍 **Multiple",            # From validate_and_get_stock
        "🎤 **",                    # From handle_trader_question
        "❌",                       # Error messages from tools
        "📊 **COMPREHENSIVE",       # Analysis report
        "🏢 **COMPANY SNAPSHOT**",  # Analysis sections
    ]
    
    has_tool_marker = any(marker in response for marker in tool_output_markers)
    
    if has_tool_marker:
        print("✅ Response contains tool output markers")
        
        # Check if agent added its own text before the tool output
        agent_intro_patterns = [
            "Here's the analysis",
            "Here is the analysis",
            "I found",
            "I've found",
            "Let me show you",
            "Based on the data",
            "According to",
            "The analysis shows",
            "I've analyzed",
            "I have analyzed",
        ]
        
        # Find if any intro pattern exists before the first tool marker
        first_marker_pos = len(response)
        first_marker = None
        for marker in tool_output_markers:
            pos = response.find(marker)
            if pos != -1 and pos < first_marker_pos:
                first_marker_pos = pos
                first_marker = marker
        
        if first_marker_pos > 0:
            # Check if there's agent text before the tool output
            prefix = response[:first_marker_pos].strip()
            if prefix and any(pattern.lower() in prefix.lower() for pattern in agent_intro_patterns):
                print(f"⚠️  Agent added intro text: '{prefix[:100]}...'")
                print("🔧 Stripping agent intro, keeping only tool output")
                response = response[first_marker_pos:].strip()
            elif prefix and len(prefix) > 50:
                # Long prefix that's not a known pattern - likely agent commentary
                print(f"⚠️  Agent added unknown prefix: '{prefix[:100]}...'")
                print("🔧 Stripping prefix, keeping only tool output")
                response = response[first_marker_pos:].strip()
    
    # Check if agent added commentary after tool output
    # Tool outputs typically end with specific patterns
    tool_ending_patterns = [
        "**Select which one to analyze:**",
        "• Or type the **company name**",
        "*[Analysis truncated",
        "**Based on analysis",
    ]
    
    # Find the last tool ending pattern
    last_ending_pos = -1
    for pattern in tool_ending_patterns:
        pos = response.rfind(pattern)
        if pos != -1:
            # Find the end of this pattern (end of line or paragraph)
            end_of_pattern = response.find('\n\n', pos)
            if end_of_pattern == -1:
                end_of_pattern = response.find('\n', pos)
            if end_of_pattern == -1:
                end_of_pattern = len(response)
            else:
                end_of_pattern += 1  # Include the newline
            
            if end_of_pattern > last_ending_pos:
                last_ending_pos = end_of_pattern
    
    if last_ending_pos > 0 and last_ending_pos < len(response) - 10:
        # There's text after the tool output
        suffix = response[last_ending_pos:].strip()
        if suffix:
            print(f"⚠️  Agent added suffix text: '{suffix[:100]}...'")
            print("🔧 Stripping agent suffix, keeping only tool output")
            response = response[:last_ending_pos].strip()
    
    print(f"✅ Final validated response length: {len(response)}")
    return response


# -------------------------
#   HELPER FUNCTIONS
# -------------------------
def aggressive_section_separation_fix(response: str) -> str:
    """
    Aggressively fix section separation issues, especially for STOCK INFORMATION & MARKET DATA
    
    Args:
        response: The response string to fix
        
    Returns:
        Response with properly separated sections
    """
    if not response:
        return response
    
    import re
    
    # MOST AGGRESSIVE FIX: Handle the specific Gross Margin + Stock Information issue
    # This pattern catches any case where these appear together
    patterns_to_fix = [
        # Pattern 1: Gross Margin followed by Stock Information on same line
        (r'(- Gross Margin: [0-9.]+%)\s*(📈\s*\*\*STOCK INFORMATION & MARKET DATA\*\*)', r'\1\n\n\2'),
        
        # Pattern 2: Any financial metric followed by Stock Information
        (r'(- [^:]+: [^📈]+)\s*(📈\s*\*\*STOCK INFORMATION & MARKET DATA\*\*)', r'\1\n\n\2'),
        
        # Pattern 3: Any bullet point followed by section header
        (r'(- [^📈\n]+)\s*(📈\s*\*\*STOCK INFORMATION & MARKET DATA\*\*)', r'\1\n\n\2'),
        
        # Pattern 4: Any text followed by section header (most general)
        (r'([^\\n])\s*(📈\s*\*\*STOCK INFORMATION & MARKET DATA\*\*)', r'\1\n\n\2'),
    ]
    
    # Apply each pattern fix
    for pattern, replacement in patterns_to_fix:
        old_response = response
        response = re.sub(pattern, replacement, response, flags=re.MULTILINE)
        if response != old_response:
            print(f"🔧 Applied section separation fix: {pattern[:50]}...")
    
    # Fix other section headers that might have similar issues
    other_section_headers = [
        r'📊\s*\*\*PRICE PERFORMANCE\*\*',
        r'🏆\s*\*\*COMPETITOR COMPARISON\*\*',
        r'🎯\s*\*\*SWOT ANALYSIS\*\*',
        r'📰\s*\*\*NEWS & ANNOUNCEMENTS\*\*',
        r'👨‍💼\s*\*\*EXPERT OPINION\*\*',
        r'🦈\s*\*\*SHARK TANK PITCH\*\*'
    ]
    
    for header_pattern in other_section_headers:
        # Ensure these headers are also on their own lines
        response = re.sub(f'([^\\n])\\s*({header_pattern})', r'\1\n\n\2', response, flags=re.MULTILINE)
    
    # Clean up excessive newlines but preserve intentional spacing
    response = re.sub(r'\n\n\n\n+', '\n\n\n', response)  # Max 3 newlines
    response = re.sub(r'\n\n\n', '\n\n', response)        # Reduce to 2 newlines max
    
    return response


def ensure_response_formatting(response: str) -> str:
    """
    Ensure response formatting is preserved and properly structured
    
    Args:
        response: The response string to format
        
    Returns:
        Properly formatted response string
    """
    if not response:
        return response
    
    # Normalize line endings
    response = response.replace('\r\n', '\n').replace('\r', '\n')
    
    # Ensure proper spacing around sections - fix the regex
    response = response.replace('\n\n\n\n', '\n\n')  # Remove quadruple newlines first
    response = response.replace('\n\n\n', '\n\n')    # Remove triple newlines
    
    # Ensure section headers are properly separated from previous content
    import re
    
    # Fix specific issue where section headers might be on same line as previous content
    section_headers = [
        r'📈 \*\*STOCK INFORMATION & MARKET DATA\*\*',
        r'📊 \*\*PRICE PERFORMANCE\*\*',
        r'🏆 \*\*COMPETITOR COMPARISON\*\*',
        r'🎯 \*\*SWOT ANALYSIS\*\*',
        r'📰 \*\*NEWS & ANNOUNCEMENTS\*\*',
        r'👨‍💼 \*\*EXPERT OPINION\*\*'
    ]
    
    for header_pattern in section_headers:
        # Ensure section headers are on their own line with proper spacing
        response = re.sub(f'([^\\n])\\s*({header_pattern})', r'\1\n\n\2', response)
    
    # Ensure markdown headers are properly spaced
    response = re.sub(r'\n(\*\*[^*]+\*\*)\n', r'\n\n\1\n\n', response)
    
    # Ensure bullet points are properly formatted
    response = re.sub(r'\n•([^ ])', r'\n• \1', response)  # Add space after bullet if missing
    response = re.sub(r'\n-([^ ])', r'\n- \1', response)  # Add space after dash if missing
    
    # Final cleanup - remove any remaining excessive spacing
    response = re.sub(r'\n\n\n+', '\n\n', response)
    
    # Ensure response isn't too long (truncate if necessary but preserve structure)
    max_length = 100000  # Increased limit to allow full content display
    if len(response) > max_length:
        print(f"⚠️ Response too long ({len(response)} chars), truncating to {max_length}")
        
        # Find a good truncation point (end of a section)
        truncation_markers = [
            "\n\n🦈 **SHARK TANK PITCH**",
            "\n\n👨‍💼 **EXPERT OPINION**", 
            "\n\n📰 **NEWS & ANNOUNCEMENTS**",
            "\n\n🎯 **SWOT ANALYSIS**",
            "\n\n🏆 **COMPETITOR COMPARISON**"
        ]
        
        truncated = False
        for marker in truncation_markers:
            marker_pos = response.find(marker)
            if marker_pos > 0 and marker_pos < max_length:
                response = response[:marker_pos] + "\n\n*[Analysis truncated for optimal display]*"
                truncated = True
                break
        
        if not truncated:
            # Fallback: truncate at max length
            response = response[:max_length] + "\n\n*[Response truncated]*"
    
    return response.strip()


def optimize_response_for_display(response: str) -> str:
    """
    Optimize response for better display in chat interfaces
    
    Args:
        response: The response string to optimize
        
    Returns:
        Optimized response string
    """
    if not response:
        return response
    
    # FIRST: Apply aggressive section separation fix
    response = aggressive_section_separation_fix(response)
    
    # THEN: Apply basic formatting
    response = ensure_response_formatting(response)
    
    # FINAL: Additional specific fixes
    import re
    
    # Ensure emojis are properly spaced from markdown
    response = re.sub(r'([🏢📊💰📈🎯📰🦈👨‍💼🏆])(\*\*)', r'\1 \2', response)
    
    # Final cleanup - remove any remaining excessive spacing
    response = re.sub(r'\\n\\n\\n+', '\\n\\n', response)
    
    return response


# -------------------------
#   AGENT TOOLS
# -------------------------
@agent.tool
@traceable(name="analyze_stock_request")
def analyze_stock_request(ctx: RunContext[ConversationState], ticker_symbol: str) -> ToolResponse:
    """
    Primary stock analysis tool that performs analysis on a validated ticker symbol.
    
    This tool expects to receive a PRE-VALIDATED ticker symbol (e.g., "RELIANCE.NS").
    It can also handle number selections (e.g., "1", "2", "3") if there are pending variants.

    Args:
        ctx (RunContext[ConversationState]): The conversation context.
        ticker_symbol (str): A validated ticker symbol (e.g., "RELIANCE.NS", "TCS.NS") OR a number selection (e.g., "1", "2", "3")

    Returns:
        ToolResponse: A complete stock analysis report with 9 sections
    """
    print(f"✅ analyze_stock_request called with input: '{ticker_symbol}'")

    # 🚨 SAFEGUARD: Block only if validate_and_get_stock ran in THIS SAME agent turn
    # (i.e., the LLM is auto-calling analyze right after showing the stock list)
    # If it's a new turn (user typed "1", "analyze 1", "now analyze 1"), let it through.
    if getattr(ctx.deps, 'validation_done_this_turn', False):
        print(f"🛑 BLOCKED: validate_and_get_stock already ran this turn — LLM auto-called analyze")
        cached = getattr(ctx.deps, 'last_validation_response', None)
        if cached:
            return create_tool_response(f"FINAL_ANSWER:\n{cached}", "validate_and_get_stock")
        return create_tool_response(
            "FINAL_ANSWER:\nMultiple stocks were found. The list has been shown. Wait for the user to type a number.",
            "analyze_stock_request"
        )
    
    # 🚨 CRITICAL SAFEGUARD #1: Check if analysis is already complete
    if hasattr(ctx.deps, 'analysis_complete') and ctx.deps.analysis_complete:
        print(f"🛑 BLOCKED: Analysis already complete, preventing repeated call")
        # Return the cached analysis so the LLM has the real content to pass through
        cached = getattr(ctx.deps, 'last_analysis_response', None)
        if cached:
            print(f"✅ Returning cached analysis ({len(cached)} chars) instead of STOP message")
            return create_tool_response(cached, "analyze_stock_request")
        return create_tool_response(
            "STOP: Analysis is complete. Do not call any more tools. The analysis results are already displayed to the user.",
            "analyze_stock_request"
        )
    
    # 🚨 CRITICAL SAFEGUARD #2: Prevent repeated analysis calls after successful analysis
    if ctx.deps.company_data and ctx.deps.stock_symbol:
        # Check if this is a different stock or just a retry of failed analysis
        current_symbol = ctx.deps.stock_symbol.upper()
        new_symbol = ticker_symbol.strip().upper()
        
        # If symbols are different and we already have successful data, reject the call
        if not new_symbol.isdigit() and new_symbol != current_symbol:
            # Check if the new symbol is similar (might be alternative ticker)
            base_current = current_symbol.replace('.NS', '').replace('.BO', '')
            base_new = new_symbol.replace('.NS', '').replace('.BO', '')
            
            if base_new != base_current:
                print(f"🛑 BLOCKED: Already analyzed {current_symbol}, rejecting call for {new_symbol}")
                return create_tool_response(
                    f"✅ Analysis already complete for {ctx.deps.stock_name} ({current_symbol}). "
                    f"If you want to analyze a different stock, please start a new search.",
                    "analyze_stock_request"
                )
            else:
                print(f"⚠️ WARNING: Attempting to analyze alternative ticker {new_symbol} for same company {base_current}")
                return create_tool_response(
                    f"✅ Already analyzed {ctx.deps.stock_name} ({current_symbol}). "
                    f"The ticker {new_symbol} appears to be an alternative symbol for the same company. "
                    f"Using the existing analysis.",
                    "analyze_stock_request"
                )
    
    # Handle number selections from pending variants
    # Extract number from inputs like "1", "analyze 1", "now analyze 1", "please select 3"
    _raw = ticker_symbol.strip()
    _extracted_num = None
    if _raw.isdigit():
        _extracted_num = int(_raw)
    else:
        import re as _re
        _num_match = _re.search(r'\b(\d+)\b', _raw)
        if _num_match:
            _extracted_num = int(_num_match.group(1))

    if _extracted_num is not None:
        if ctx.deps.pending_variants and 1 <= _extracted_num <= len(ctx.deps.pending_variants):
            selected_variant = ctx.deps.pending_variants[_extracted_num - 1]
            ticker_symbol = selected_variant['symbol']
            print(f"📋 User selected option {_extracted_num}: {selected_variant['name']} ({ticker_symbol})")
        else:
            error_msg = f"❌ Invalid selection '{_raw}'. Please choose a number between 1 and {len(ctx.deps.pending_variants) if ctx.deps.pending_variants else 0}."
            return create_tool_response(error_msg, "analyze_stock_request")
    
    ticker_symbol = ticker_symbol.strip().upper()
    
    # Ensure ticker has proper exchange suffix
    if not any(ticker_symbol.endswith(suffix) for suffix in ['.NS', '.BO', '.LS', '.CO']):
        # Add .NS as default for Indian stocks if no suffix provided
        if len(ticker_symbol) <= 10:  # Likely Indian stock
            ticker_symbol = f"{ticker_symbol}.NS"
    
    try:
        # Fetch company data directly (no re-validation needed)
        print(f"📊 Fetching data for validated ticker: {ticker_symbol}")
        company_data = StockTools.get_realtime_data(ticker_symbol)
        
        if not company_data:
            error_msg = f"❌ Unable to fetch data for {ticker_symbol}. Please try another stock."
            return create_tool_response(error_msg, "analyze_stock_request")
        
        # Store in context
        ctx.deps.stock_symbol = ticker_symbol
        ctx.deps.stock_name = company_data.name
        ctx.deps.company_data = company_data
        ctx.deps.pending_variants = None
        
        # Format report
        formatted_report = StockTools.format_data_for_report(company_data)
        
        # Generate PDF summary from screener.in
        print(f"\n📄 Generating PDF summary from screener.in...")
        try:
            from utils.pdf_text_summarizer import PDFSummarizerPipeline
            pipeline = PDFSummarizerPipeline()
            
            # Extract base stock symbol (remove .NS or .BO suffix)
            base_symbol = ticker_symbol.replace('.NS', '').replace('.BO', '')
            
            pdf_result = pipeline.process_multiple_pdfs(base_symbol, num_pdfs=4)
            
            if pdf_result.get("success") and pdf_result.get("main_summary"):
                screener_pdf_summary = f"""

**📊 Screener.in Quarterly Reports Summary**

{pdf_result['main_summary']}

**Based on analysis of latest {len(pdf_result.get('individual_summaries', []))} quarterly reports from screener.in**

"""
                print(f"✅ PDF summary generated: {len(pdf_result['main_summary'].split())} words")
            else:
                screener_pdf_summary = ""
                print(f"⚠️ PDF summary generation failed: {pdf_result.get('error', 'Unknown error')}")
        except Exception as e:
            screener_pdf_summary = ""
            print(f"⚠️ PDF summary generation error: {e}")
        
        # Note: Shark Tank pitch generation is available via separate tool
        # Not included in main analysis to keep response focused
        
        # Add to conversation context
        ctx.deps.add_interaction(
            user_input=ticker_symbol,
            action_type='stock_analyzed',
            result_summary=f'Successfully analyzed {company_data.name} ({ticker_symbol})'
        )
        
        # Save to PostgreSQL database
        print(f"\n💾 Saving analysis to database...")
        try:
            # Extract technical analysis JSON
            tech_analysis_json = extract_tech_analysis_json(company_data)
            
            # Calculate selection status
            is_selected = calculate_selection_status(company_data)
            
            # Prepare analyzed response (formatted report + PDF summary)
            analyzed_response_text = f"{formatted_report}\n\n{screener_pdf_summary}"
            
            # Note: Sentiment data will be saved separately when available
            # For now, we save the analysis without sentiment data
            db = StockDatabase()
            if db.connect():
                db.create_table()
                db.save_analysis(
                    stock_name=company_data.name,
                    stock_symbol=ticker_symbol,
                    analyzed_response=analyzed_response_text,
                    tech_analysis=tech_analysis_json,
                    selection=is_selected,
                    market_senti=None,  # Will be updated when sentiment is analyzed
                    current_market_senti_status=None,
                    future_senti=None,
                    future_senti_status=None
                )
                db.disconnect()
                print(f"✅ Analysis saved to database for {company_data.name}")
            else:
                print(f"⚠️ Database connection failed, analysis not saved")
        except Exception as db_error:
            print(f"⚠️ Database save error: {db_error}")
            # Continue even if database save fails
        
        # Return complete analysis
        final_response = f"""
✅ **Selected: {company_data.name} ({ticker_symbol})**

{formatted_report}

{screener_pdf_summary}

"""
        
        print(f"📊 Returning optimized response with {len(final_response)} characters")
        print(f"🛑 ANALYSIS COMPLETE - Setting flag to prevent re-analysis")
        
        # Mark analysis as complete to prevent repeated calls
        ctx.deps.analysis_complete = True
        
        # Cache the response for future error message handling
        ctx.deps.last_analysis_response = final_response
        
        return create_tool_response(final_response, "analyze_stock_request")
        
    except Exception as e:
        print(f"❌ Analysis error: {str(e)}")
        
        # Provide a better error message
        error_msg = str(e)
        if "No such file or directory" in error_msg:
            error_response = f"❌ **Analysis Error for {ticker_symbol}**\n\nThere was a technical issue processing the stock data. This is usually temporary.\n\n**What you can do:**\n• Try the analysis again in a moment\n• The system is working on resolving data access issues\n• All core functionality remains available\n\n*Technical details: {error_msg}*"
        else:
            error_response = f"❌ **Error analyzing {ticker_symbol}**\n\n{error_msg}\n\n**Please try again** - this is usually a temporary issue."
        
        return create_tool_response(error_response, "analyze_stock_request")

@agent.tool
@traceable(name="validate_and_get_stock")
def validate_and_get_stock(ctx: RunContext[ConversationState], stock_name: str) -> ToolResponse:
    """
    Validates a stock name and returns matching results.
    
    SMART BEHAVIOR:
    - If ONLY ONE stock is found → Automatically analyzes it (no selection needed)
    - If MULTIPLE stocks found → Returns list for user to select from
    
    This provides a seamless experience - users don't need to select when there's only one option.

    Args:
        ctx (RunContext[ConversationState]): The conversation context.
        stock_name (str): The name or partial symbol of the company (e.g., "Apple", "Reliance", "TCS", "Infosys")

    Returns:
        ToolResponse: Either a complete stock analysis (if 1 match) OR a formatted list of options (if multiple matches)
    """
    print(f"🔎 Validating stock '{stock_name}'...")
    
    # Block re-entry: if validate_and_get_stock already ran this turn, return cached result
    if getattr(ctx.deps, 'validation_done_this_turn', False):
        print(f"🛑 BLOCKED: validate_and_get_stock already ran this turn")
        cached = getattr(ctx.deps, 'last_validation_response', None)
        if cached:
            return create_tool_response(f"FINAL_ANSWER:\n{cached}", "validate_and_get_stock")
        return create_tool_response(
            "FINAL_ANSWER:\n⚠️ Stock list already shown. Please type a number to select.",
            "validate_and_get_stock"
        )
    
    # Mark as done for this turn immediately (before any async work)
    ctx.deps.validation_done_this_turn = True
    
    # Reset analysis_complete flag when starting a new search
    if hasattr(ctx.deps, 'analysis_complete'):
        ctx.deps.analysis_complete = False
        print("🔄 Reset analysis_complete flag for new search")
    
    try:
        client = get_client()
        
        system_prompt = """You are an expert Indian stock market analyst with access to real-time market data. Your task is to find ALL publicly listed companies related to a search query.

CRITICAL REQUIREMENTS FOR ACCURACY:

1. **COMPREHENSIVE SEARCH**: If the query is a business group name (Tata, Reliance, Adani, Birla, Mahindra, etc.), find ALL their publicly listed companies across ALL sectors
2. **VERIFY SYMBOLS**: Return ONLY ticker symbols that actually exist on Yahoo Finance in the format SYMBOL.NS or SYMBOL.BO
3. **CORRECT ABBREVIATIONS**: Use the exact Yahoo Finance symbol format:
   - Tata Consultancy Services → TCS.NS (NOT TATACONSULTANCY.NS)
   - Infosys → INFY.NS (NOT INFOSYS.NS)
   - Tata Steel → TATASTEEL.NS (one word)
   - Tata Power → TATAPOWER.NS (one word)
   - Tata Consumer → TATACONSUM.NS (abbreviated)

4. **SEARCH STRATEGY**:
   - For business groups: Search NSE/BSE listings for ALL companies with that group name
   - Check multiple sectors: IT, Steel, Power, Consumer, Chemicals, Automotive, Hotels, etc.
   - Include subsidiaries and associate companies
   - Verify each symbol exists before returning

5. **QUALITY OVER QUANTITY**: Return only symbols you can verify exist on Yahoo Finance

EXAMPLES OF CORRECT RESPONSES:

Query: "Tata"
Response: TCS.NS, TATASTEEL.NS, TATAPOWER.NS, TATACONSUM.NS, TATACHEM.NS, TITAN.NS, TATAELXSI.NS, TATACOMM.NS, INDHOTEL.NS, TATATECH.NS, TATAINVEST.NS

Query: "Reliance"
Response: RELIANCE.NS, RPOWER.NS, RELINFRA.NS, RELCAPITAL.NS

Query: "Adani"
Response: ADANIENT.NS, ADANIPORTS.NS, ADANIPOWER.NS, ADANIGREEN.NS, ATGL.NS, ADANITRANS.NS

Query: "Infosys"
Response: INFY.NS

IMPORTANT NOTES:
- Always use .NS (NSE) as primary exchange
- Verify symbols are currently trading
- Check for recent delistings or mergers
- Don't make up symbols - only return verified ones
- For single companies, return just that company
- For business groups, return ALL related companies

OUTPUT FORMAT (JSON only):
{
    "found": boolean,
    "companies": [
        {
            "name": "Full Official Company Name",
            "symbol": "VERIFIED_SYMBOL.NS",
            "exchange": "NSE",
            "sector": "Industry sector (optional)"
        }
    ],
    "explanation": "Brief explanation of search results"
}

VERIFICATION CHECKLIST BEFORE RETURNING:
✅ Symbol follows Yahoo Finance format (SYMBOL.NS or SYMBOL.BO)
✅ Symbol is verified to exist (not guessed)
✅ Company name is official registered name
✅ No recent delisting or merger
✅ Symbol is currently trading on NSE/BSE"""

        response = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"""Find ALL publicly listed companies for '{stock_name}' on Indian stock exchanges (NSE/BSE).

SEARCH INSTRUCTIONS:
1. If '{stock_name}' is a business group (like Tata, Reliance, Adani, Birla, Mahindra, Bajaj, etc.):
   - Search for ALL companies with '{stock_name}' in their name
   - Check NSE and BSE listings comprehensively
   - Include companies across ALL sectors (IT, Steel, Power, Consumer, Chemicals, Automotive, Hotels, Finance, etc.)
   - Look for: {stock_name} + [Industries, Steel, Power, Consumer, Chemicals, Motors, Communications, Technologies, etc.]

2. If '{stock_name}' is a specific company:
   - Find the exact company and its ticker symbol
   - Verify the symbol exists on Yahoo Finance

3. VERIFY each symbol:
   - Use correct Yahoo Finance format (SYMBOL.NS or SYMBOL.BO)
   - Ensure symbols are currently trading
   - Check for correct abbreviations (e.g., TCS.NS not TATACONSULTANCY.NS)

Return ALL matching companies with VERIFIED ticker symbols. Be comprehensive - for major business groups, there should be 5-15+ companies."""}
            ]
        )
        
        import json
        import re
        content = response.choices[0].message.content
        print(f"📋 Perplexity response: {content[:100]}...")
        
        # Clean markdown and extract JSON
        if "```json" in content:
            # Extract content between ```json and ```
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', content, re.DOTALL)
            if json_match:
                content = json_match.group(1)
            else:
                content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            # Extract content between ``` and ```
            json_match = re.search(r'```\s*(\{.*?\})\s*```', content, re.DOTALL)
            if json_match:
                content = json_match.group(1)
            else:
                content = content.split("```")[1].split("```")[0].strip()
        else:
            # Try to extract JSON object from the content
            json_match = re.search(r'(\{.*\})', content, re.DOTALL)
            if json_match:
                content = json_match.group(1)
        
        # Remove any trailing text after the JSON object
        content = content.strip()
        
        # Find the last closing brace and truncate there
        last_brace = content.rfind('}')
        if last_brace != -1:
            content = content[:last_brace + 1]
        
        data_dict = json.loads(content)
        found = data_dict.get('found', False)
        companies = data_dict.get('companies', [])
        
    except Exception as e:
        print(f"❌ Validation error: {e}")
        return create_tool_response(f"❌ Error validating '{stock_name}': {str(e)}. Please try a different name.", "validate_and_get_stock")

    if not found or not companies:
        print(f"⚠️ Perplexity found no companies for '{stock_name}'")
        return create_tool_response(f"❌ No stocks found for '{stock_name}'. Please try:\n• A more specific company name\n• The exact ticker symbol (e.g., TCS.NS, RELIANCE.NS)\n• Check spelling and try again", "validate_and_get_stock")
    
    # SMART VERIFICATION: Verify symbols and try alternatives if needed
    print(f"🔍 Verifying {len(companies)} symbols with yfinance...")
    import yfinance as yf
    import time
    
    validated_variants = []
    
    for c in companies:
        symbol = c.get('symbol', '').strip()
        if not symbol:
            continue
        
        # Try the suggested symbol first
        symbols_to_try = [symbol]
        
        # If symbol doesn't have exchange suffix, try adding .NS and .BO
        if '.' not in symbol:
            symbols_to_try = [f"{symbol}.NS", f"{symbol}.BO", symbol]
        
        # Try each variant
        verified = False
        for try_symbol in symbols_to_try:
            try:
                print(f"   Checking {try_symbol}...")
                ticker = yf.Ticker(try_symbol)
                info = ticker.info
                
                # Check if we got valid data
                if info and len(info) > 3:
                    # Try to get name from multiple sources
                    actual_name = (
                        info.get('longName') or 
                        info.get('shortName') or 
                        info.get('name') or
                        c.get('name', '')
                    )
                    
                    if not actual_name:
                        actual_name = c.get('name', try_symbol)
                    
                    # Verify this is a real stock (has some key fields)
                    if info.get('symbol') or info.get('quoteType') == 'EQUITY':
                        validated_variants.append({
                            'symbol': info.get('symbol', try_symbol),
                            'name': actual_name,
                            'exchange': info.get('exchange', c.get('exchange', 'NSE'))
                        })
                        print(f"   ✅ {try_symbol} verified: {actual_name}")
                        verified = True
                        break  # Found valid symbol, stop trying alternatives
                    else:
                        print(f"   ⚠️ {try_symbol} exists but might not be equity")
                else:
                    print(f"   ⚠️ {try_symbol} returned minimal data")
                    
                time.sleep(0.1)
                
            except Exception as e:
                error_msg = str(e)
                if '404' in error_msg or 'Not Found' in error_msg:
                    print(f"   ❌ {try_symbol} not found")
                else:
                    print(f"   ⚠️ {try_symbol} error: {error_msg[:50]}...")
                time.sleep(0.1)
                continue
        
        # If no variant worked but we have a name from Perplexity, add with warning
        if not verified and c.get('name'):
            print(f"   ⚠️ Could not verify {symbol}, but adding based on search result")
            validated_variants.append({
                'symbol': symbol,
                'name': c.get('name'),
                'exchange': c.get('exchange', 'NSE')
            })
    
    if not validated_variants:
        print(f"❌ No symbols could be verified")
        error_msg = f"""❌ Could not verify any stock symbols for '{stock_name}'.

This could mean:
• The company might not be publicly listed
• The symbols might be incorrect
• There might be temporary API issues

Please try:
• A more specific company name
• The exact ticker symbol (e.g., TCS.NS, RELIANCE.NS)
• Check if the company is publicly traded"""
        
        return create_tool_response(error_msg, "validate_and_get_stock")
    
    print(f"✅ Verified {len(validated_variants)}/{len(companies)} symbols")
    
    # ENHANCEMENT: Always try comprehensive search for business groups
    # This ensures we find ALL companies in conglomerates like Reliance, Tata, Adani, etc.
    print(f"🔍 Found {len(validated_variants)} companies, trying comprehensive business group search...")
    
    try:
        # Create multiple enhanced search queries to catch all variations
        enhanced_queries = [
            # Query 1: Direct business group search
            f"Find ALL publicly listed companies in the '{stock_name}' business group in India. Include parent company, subsidiaries, joint ventures, and affiliated companies. Search for companies like '{stock_name} Industries', '{stock_name} Limited', '{stock_name} Corp', '{stock_name} Power', '{stock_name} Infrastructure', '{stock_name} Energy', '{stock_name} Capital', '{stock_name} Finance', '{stock_name} Motors', '{stock_name} Steel', '{stock_name} Chemicals', '{stock_name} Telecom', '{stock_name} Retail'. Return ALL stock ticker symbols ending with .NS or .BO.",
            
            # Query 2: Sector-specific search
            f"List ALL companies owned by or affiliated with '{stock_name}' group across different sectors: oil & gas, petrochemicals, telecommunications, retail, power, infrastructure, financial services, steel, automotive, chemicals, textiles, hospitality. Include both majority-owned subsidiaries and joint ventures. Provide Yahoo Finance ticker symbols ending with .NS or .BO.",
            
            # Query 3: Comprehensive conglomerate search
            f"'{stock_name}' is a major Indian business conglomerate. Find ALL their publicly listed companies across ALL business verticals and sectors. Include holding companies, operating companies, subsidiaries, and associate companies. Search comprehensively for any company with '{stock_name}' in the name or owned by the '{stock_name}' group. Return complete list with .NS/.BO ticker symbols."
        ]
        
        all_enhanced_companies = []
        
        for i, enhanced_query in enumerate(enhanced_queries, 1):
            try:
                print(f"🔍 Running enhanced search {i}/3...")
                
                enhanced_response = client.chat.completions.create(
                    model="openai/gpt-oss-120b",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": enhanced_query}
                    ],
                    temperature=0.1  # Lower temperature for more consistent results
                )
                
                enhanced_content = enhanced_response.choices[0].message.content
                print(f"📋 Enhanced search {i} response: {enhanced_content[:100]}...")
                
                # Clean and parse enhanced response with better JSON extraction
                if "```json" in enhanced_content:
                    # Extract content between ```json and ```
                    json_match = re.search(r'```json\s*(\{.*?\})\s*```', enhanced_content, re.DOTALL)
                    if json_match:
                        enhanced_content = json_match.group(1)
                    else:
                        enhanced_content = enhanced_content.split("```json")[1].split("```")[0].strip()
                elif "```" in enhanced_content:
                    # Extract content between ``` and ```
                    json_match = re.search(r'```\s*(\{.*?\})\s*```', enhanced_content, re.DOTALL)
                    if json_match:
                        enhanced_content = json_match.group(1)
                    else:
                        enhanced_content = enhanced_content.split("```")[1].split("```")[0].strip()
                else:
                    # Try to extract JSON object from the content
                    json_match = re.search(r'(\{.*\})', enhanced_content, re.DOTALL)
                    if json_match:
                        enhanced_content = json_match.group(1)
                
                # Remove any trailing text after the JSON object
                enhanced_content = enhanced_content.strip()
                
                # Find the last closing brace and truncate there
                last_brace = enhanced_content.rfind('}')
                if last_brace != -1:
                    enhanced_content = enhanced_content[:last_brace + 1]
                
                enhanced_data = json.loads(enhanced_content)
                enhanced_companies = enhanced_data.get('companies', [])
                
                if enhanced_companies:
                    all_enhanced_companies.extend(enhanced_companies)
                    print(f"✅ Enhanced search {i} found {len(enhanced_companies)} companies")
                
            except Exception as search_error:
                print(f"⚠️ Enhanced search {i} failed: {search_error}")
                continue
        
        # Merge all enhanced results with existing results, avoiding duplicates
        if all_enhanced_companies:
            existing_symbols = {v['symbol'].upper() for v in validated_variants}
            added_count = 0
            
            print(f"🔍 Verifying {len(all_enhanced_companies)} enhanced search symbols...")
            
            for company in all_enhanced_companies:
                symbol = company.get('symbol', '').upper().strip()
                if not symbol or symbol in existing_symbols:
                    continue
                
                try:
                    # Verify with yfinance before adding
                    print(f"   Checking {symbol}...")
                    ticker = yf.Ticker(symbol)
                    info = ticker.info
                    
                    if info and 'symbol' in info and info.get('symbol'):
                        actual_name = info.get('longName') or info.get('shortName') or company.get('name', '')
                        
                        if actual_name:
                            validated_variants.append({
                                'symbol': info.get('symbol', symbol),
                                'name': actual_name,
                                'exchange': info.get('exchange', company.get('exchange', 'Unknown'))
                            })
                            existing_symbols.add(symbol)
                            added_count += 1
                            print(f"   ✅ {symbol} verified: {actual_name}")
                        else:
                            print(f"   ⚠️ {symbol} has no name data, skipping")
                    else:
                        print(f"   ⚠️ {symbol} not found or invalid")
                        
                    time.sleep(0.1)  # Small delay
                    
                except Exception as e:
                    print(f"   ❌ {symbol} verification failed: {e}")
                    continue
            
            print(f"✅ Enhanced searches found {added_count} additional verified companies")
            print(f"📊 Total verified companies: {len(validated_variants)}")
        
    except Exception as e:
        print(f"⚠️ Enhanced search system failed: {e}, continuing with original results")
    
    ctx.deps.pending_variants = validated_variants
    
    # Check if any companies have merger info
    has_merger_info = any(c.get('merger_info') for c in companies)
    
    # Format response with options - Use cleaner format without "- Exchange"
    options_text = ""
    for idx, company in enumerate(validated_variants, 1):
        # Clean format: just number, name, and symbol in parentheses
        options_text += f"{idx}. {company['name']} ({company['symbol']})\n"
        
        # Add merger info if available
        original_company = next((c for c in companies if c.get('symbol') == company['symbol']), None)
        if original_company and original_company.get('merger_info'):
            options_text += f"   ℹ️ {original_company['merger_info']}\n"
    
    # Add to conversation context
    ctx.deps.add_interaction(
        user_input=stock_name,
        action_type='stock_validation',
        result_summary=f'Found {len(validated_variants)} matching stocks'
    )
    
    # 🚀 AUTO-ANALYSIS: If only ONE stock found, analyze it directly!
    # DISABLED for "tata" queries - always show options for business groups
    if len(validated_variants) == 1 and not any(group in stock_name.lower() for group in ['tata', 'adani', 'reliance', 'birla', 'bajaj']):
        print(f"✨ Only one stock found - auto-analyzing: {validated_variants[0]['name']}")
        
        # Directly call analyze_stock_request with the single stock
        single_stock = validated_variants[0]
        ticker_symbol = single_stock['symbol']
        
        # Clear pending variants since we're analyzing directly
        ctx.deps.pending_variants = None
        
        # Call analyze_stock_request and return its ToolResponse directly
        # This maintains the correct return type for the agent
        return analyze_stock_request(ctx, ticker_symbol)
    
    # Multiple stocks found OR business group query - show selection menu
    response_text = f"""
🔍 **Found {len(validated_variants)} stock(s) matching '{stock_name}':**

{options_text}"""
    
    if has_merger_info:
        response_text += "\n**Note:** Some companies have been merged or renamed. The current ticker symbols are shown above.\n"
    
    response_text += """
**Select which one to analyze:**
• Type the **number** (1, 2, 3, etc.)
• Or type the stock  **symbol**
• Or type the **company name**"""
    
    # Cache the stock list and set pending selection flag
    ctx.deps.last_validation_response = response_text
    print(f"🔒 Showing {len(validated_variants)} options — user must select")
    
    return create_tool_response(response_text, "validate_and_get_stock")


@agent.tool
@traceable(name="return_existing_analysis")
def return_existing_analysis(ctx: RunContext[ConversationState]) -> ToolResponse:
    """
    Returns the existing analysis when user sends error messages or requests to retry.
    This prevents unnecessary tool calls for error messages.
    """
    print(f"🔄 return_existing_analysis called - returning cached analysis")
    
    if not ctx.deps.company_data:
        return create_tool_response("No analysis available. Please analyze a stock first.", "return_existing_analysis")
    
    # Check if we have a cached formatted response
    if hasattr(ctx.deps, 'last_analysis_response') and ctx.deps.last_analysis_response:
        print(f"✅ Returning cached analysis response ({len(ctx.deps.last_analysis_response)} chars)")
        return create_tool_response(ctx.deps.last_analysis_response, "return_existing_analysis")
    
    # If no cached response, generate a simple message
    data = ctx.deps.company_data
    response = f"""✅ **Analysis Available for {data.name} ({data.symbol})**

The comprehensive analysis for this stock has already been completed. The analysis includes:

📊 **Company Overview & Financial Metrics**
📈 **Stock Performance & Market Data** 
🏆 **Competitor Analysis**
🎯 **SWOT Analysis**
📰 **Recent News & Developments**

If you have specific questions about this stock, please ask them directly (e.g., "What are the growth prospects?", "Is this a good investment?", "What are the risks?").

To analyze a different stock, please specify the new company name."""

    return create_tool_response(response, "return_existing_analysis")


@agent.tool
@traceable(name="handle_trader_question")
def handle_trader_question(ctx: RunContext[ConversationState], question: str) -> ToolResponse:
    """
    Handles specific questions about the currently analyzed stock acting as a company executive.
    
    This tool answers follow-up questions about the company using the loaded company data.
    It responds from the perspective of a company executive (CEO/CFO) with specific data points.

    Args:
        ctx (RunContext[ConversationState]): The conversation context containing the company data.
        question (str): The user's question about the company (e.g., "What's your revenue?", "How do you compete?")

    Returns:
        str: A professional, first-person response from the perspective of a company executive addressing the user's question with specific data points.
    """
    print(f"🔧 handle_trader_question called with: '{question}'")
    
    if not ctx.deps.company_data:
        print(f"❌ ERROR: handle_trader_question called but no company_data exists!")
        return create_tool_response("Please analyze a stock first before asking questions.", "handle_trader_question")
    
    data = ctx.deps.company_data
    
    # Determine currency and formatting
    is_indian = data.symbol.endswith('.NS') or data.symbol.endswith('.BO')
    currency = "₹" if is_indian else "$"
    
    def fmt(val):
        if not val: return "N/A"
        if is_indian:
            if val >= 1e7: return f"{currency}{val/1e7:.2f} Cr"
            elif val >= 1e5: return f"{currency}{val/1e5:.2f} L"
            else: return f"{currency}{val:,.0f}"
        else:
            return create_tool_response(f"{currency}{val/1e9:.2f}B", "handle_trader_question")
    
    # Create context for the LLM
    company_context = f"""
COMPANY: {data.name} ({data.symbol})
SECTOR: {data.market_data.sector or 'N/A'}
CURRENT PRICE: {currency}{data.market_data.current_price:.2f} if data.market_data.current_price else 'N/A'
MARKET CAP: {fmt(data.market_data.market_cap)}
REVENUE: {fmt(data.financials.revenue)}
NET PROFIT: {fmt(data.financials.net_profit)}
PROFIT MARGIN: {f"{data.financials.profit_margin*100:.2f}%" if data.financials.profit_margin else "N/A"}
PE RATIO: {f"{data.financials.pe_ratio:.2f}" if data.financials.pe_ratio else "N/A"}
DEBT TO EQUITY: {f"{data.financials.debt_to_equity:.2f}" if data.financials.debt_to_equity else "N/A"}
FREE CASH FLOW: {fmt(data.financials.free_cash_flow)}
"""
    
    # Use the model to generate a response
    try:
        client = get_client()
        
        system_prompt = f"""You are the CEO/CFO of {data.name} responding to an investor's question in a professional, conversational manner.

COMPANY DATA:
{company_context}

INSTRUCTIONS:
- Respond as the company executive (use "we", "our company", "I")
- Be conversational but professional
- Use specific numbers from the data
- Address the question directly
- Keep response focused and under 200 words
- Show confidence in the company
- If asked about risks, be honest but balanced

QUESTION: {question}

Respond naturally as the CEO/CFO would:"""

        response = client.chat.completions.create(
            model="openai/gpt-oss-120b",  # Free model
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question}
            ],
            temperature=0.7,
            max_tokens=300
        )
        
        # Safe handling of response content
        content = response.choices[0].message.content
        if content is None:
            print(f"⚠️ API returned None content for question: {question}")
            answer = f"I understand your question about {data.name}, but I'm having trouble generating a response right now. Please try asking again or rephrase your question."
        else:
            answer = content.strip()
        
        # Add to conversation context
        ctx.deps.add_interaction(
            user_input=question,
            action_type='qa_answered',
            result_summary=f'Answered question about {data.name}'
        )
        
        return create_tool_response(f"🎤 **{data.name} Executive Response:**\n\n{answer}", "handle_trader_question")
        
    except Exception as e:
        print(f"❌ Error generating Q&A response: {str(e)}")
        print(f"🔍 Error type: {type(e).__name__}")
        print(f"🔍 Question was: {question}")
        
        # Provide a more helpful fallback response
        fallback_response = f"I'd be happy to answer questions about {data.name if data and hasattr(data, 'name') else 'this company'}, but I'm experiencing technical difficulties right now. Please try asking your question again, or try rephrasing it."
        
        return create_tool_response(fallback_response, "handle_trader_question")


@agent.tool
@traceable(name="perform_scenario_analysis")
def perform_scenario_analysis(ctx: RunContext[ConversationState], scenario: str) -> ToolResponse:
    """
    Performs a hypothetical "what-if" scenario analysis for the currently analyzed company.

    Args:
        ctx (RunContext[ConversationState]): The conversation context containing the company data.
        scenario (str): The hypothetical scenario description provided by the user (e.g., "invalid oil prices", "recession", "new competitor").

    Returns:
        str: A narrative response from the perspective of the CFO, discussing the potential impact of the scenario on the company's financials and strategy.
    """
    if not ctx.deps.company_data:
        return create_tool_response("Please analyze a stock first before running scenarios.", "perform_scenario_analysis")
    
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
    
    return create_tool_response(prompt, "perform_scenario_analysis")

@agent.tool
@traceable(name="generate_summary_report")
def generate_summary_report(ctx: RunContext[ConversationState]) -> ToolResponse:
    """
    Generates a comprehensive summary of the stock analysis and any subsequent Q&A.

    Args:
        ctx (RunContext[ConversationState]): The conversation context containing company data and conversation history.

    Returns:
        str: A structured summary including key financial highlights, pros/cons, future outlook, and an investment consideration verdict.
    """
    if not ctx.deps.company_data:
        return create_tool_response("No stock data available to summarize.", "generate_summary_report")
    
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
    
    return create_tool_response(prompt, "generate_summary_report")



@agent.tool
@traceable(name="handle_greeting")
def handle_greeting(ctx: RunContext[ConversationState]) -> ToolResponse:
    """
    Handles user greetings and provides a welcoming response.
    
    Call this tool when the user says greetings like:
    - "hi", "hello", "hey", "hola", "namaste", "good morning", "good evening"
    - Any greeting without asking about stocks
    
    Returns:
        ToolResponse: A friendly greeting message
    """
    greeting_message = """Hello! 👋 I'm your AI stock analyst.

I can help you with comprehensive stock analysis for Indian and global markets.

**What I can do:**
• Analyze any stock with detailed financial metrics
• Answer questions about companies and their performance
• Provide scenario analysis and market insights
• Compare competitors and identify trends

**To get started, just tell me:**
• A company name (e.g., "Reliance", "Tata", "Infosys")
• A stock ticker (e.g., "RELIANCE.NS", "TCS.NS")
• Or ask me a question about any stock

What stock would you like to analyze today?"""
    
    return create_tool_response(greeting_message, "handle_greeting")
