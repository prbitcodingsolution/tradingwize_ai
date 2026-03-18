# -*- coding: utf-8 -*-
#streamlit run app_advanced.py --server.address=0.0.0.0 --server.port=8501
# ngrok config add-authtoken 36bmLDf1FVuILZCpcmXzY6x9TjC_3d1YjRnaX4wD2eFZrwH7f

import streamlit as st
from agent1 import agent, ConversationState, ToolResponse
from datetime import datetime
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from tools import StockTools
from langsmith import traceable
from langsmith.integrations.otel import configure
import re
import os
import time
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart, SystemPromptPart
from agent1 import agent_system_prompt

def fix_response_formatting(response: str) -> str:
    """
    Simple, conservative function to fix only essential formatting issues
    """
    if not response or len(response) < 100:
        return response
    
    print(f"🔧 Starting conservative format fix for {len(response)} char response...")
    
    # Only fix the most critical issues that break markdown rendering
    
    # 1. Fix broken bold headers with spaces
    response = re.sub(r'\*\* ([^*]+?) \*\*', r'**\1**', response)
    
    # 2. Fix financial data that's all crammed on one line with dashes
    # Only if there are multiple dashes in a row indicating list items
    if ' - ' in response and response.count(' - ') > 3:
        # Split financial metrics that are separated by " - " into bullet points
        response = re.sub(r' - ([^-]+?)(?= - |$)', r'\n• \1', response)
    
    # 3. Fix percentage indicators that got separated from their values
    response = re.sub(r'(\d+\.?\d*%)\s*\n\s*([📈📉])', r'\1 \2', response)
    
    # 4. Clean up excessive whitespace
    response = re.sub(r'\n{3,}', '\n\n', response)
    response = re.sub(r'[ \t]+', ' ', response)
    
    # 5. Ensure proper spacing around section headers
    response = re.sub(r'(\*\*[^*]+\*\*)\n([^*\n])', r'\1\n\n\2', response)
    
    print(f"✅ Conservative formatting complete")
    
    return response.strip()


def debug_response_formatting(content: str, stage: str) -> None:
    """
    Debug function to help track formatting issues
    """
    if not content:
        return
    
    print(f"\n🔍 DEBUG - {stage}:")
    print(f"Length: {len(content)}")
    print(f"Lines: {content.count(chr(10)) + 1}")
    
    # Check for the specific issue
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if "Gross Margin:" in line and "STOCK INFORMATION" in line:
            print(f"❌ ISSUE FOUND at line {i}: '{line[:100]}...'")
            return
    
    # Find the relevant lines
    gross_margin_line = None
    stock_info_line = None
    
    for i, line in enumerate(lines):
        if "Gross Margin:" in line:
            gross_margin_line = i
        elif "STOCK INFORMATION" in line:
            stock_info_line = i
    
    if gross_margin_line is not None and stock_info_line is not None:
        lines_apart = stock_info_line - gross_margin_line
        print(f"✅ Sections separated: Gross Margin at line {gross_margin_line}, Stock Info at line {stock_info_line} ({lines_apart} lines apart)")
    elif gross_margin_line is not None:
        print(f"📊 Found Gross Margin at line {gross_margin_line}")
    elif stock_info_line is not None:
        print(f"📈 Found Stock Information at line {stock_info_line}")


def streamlit_markdown_formatter(content: str) -> str:
    """
    Format content specifically for Streamlit markdown rendering - COMPACT VERSION
    
    Args:
        content: The content to format for Streamlit
        
    Returns:
        Streamlit-optimized markdown content with minimal spacing
    """
    if not content:
        return content
    
    print(f"🎨 Applying compact Streamlit formatting to {len(content)} chars...")
    
    import re
    
    # 1. Fix critical section separation issues (keep minimal spacing)
    patterns_to_fix = [
        # Ensure section headers are on their own line
        (r'(- Gross Margin: [0-9.]+%)\s*(📈\s*\*\*STOCK INFORMATION & MARKET DATA\*\*)', r'\1\n\2'),
        (r'(- [^:]+: [^📈\n]+)\s*(📈\s*\*\*STOCK INFORMATION & MARKET DATA\*\*)', r'\1\n\2'),
        (r'([^\n])\s*(📈\s*\*\*STOCK INFORMATION & MARKET DATA\*\*)', r'\1\n\2'),
    ]
    
    for pattern, replacement in patterns_to_fix:
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    
    # 2. Fix other section headers - single newline only
    other_section_headers = [
        r'�\s*\*\*PRICE PERFORMANCE\*\*',
        r'🏆\s*\*\*COMPETITOR COMPARISON\*\*',
        r'🎯\s*\*\*SWOT ANALYSIS\*\*',
        r'📰\s*\*\*NEWS & ANNOUNCEMENTS\*\*',
        r'👨‍💼\s*\*\*EXPERT OPINION\*\*',
        r'🦈\s*\*\*SHARK TANK PITCH\*\*',
        r'🏢\s*\*\*COMPANY SNAPSHOT\*\*',
        r'📋\s*\*\*BUSINESS OVERVIEW\*\*',
        r'�\s*\*\*FINANCIAL METRICS'
    ]
    
    for header_pattern in other_section_headers:
        content = re.sub(f'([^\n])\\s*({header_pattern})', r'\1\n\2', content, flags=re.MULTILINE)
    
    # 3. COMPACT FORMATTING - Remove excessive spacing
    
    # Remove double newlines before bullet points (keep compact)
    content = re.sub(r'\n\n•', '\n•', content)
    content = re.sub(r'\n\n-\s*(?!\d)', '\n- ', content)
    
    # Fix percentage + emoji combinations
    content = re.sub(r'(\d+\.?\d*%)\s*([📈📉])', r'\1 \2', content)
    
    # 4. CLEANUP - Remove excessive newlines
    content = re.sub(r'\n\n\n+', '\n\n', content)  # Max 2 newlines
    
    # 5. Ensure major sections have ONE blank line before them (not two)
    major_sections = [
        '📊 **COMPREHENSIVE STOCK ANALYSIS**',
        '🏢 **COMPANY SNAPSHOT**',
        '📋 **BUSINESS OVERVIEW**',
        '💰 **FINANCIAL METRICS',
        '📈 **STOCK INFORMATION & MARKET DATA**',
        '📊 **PRICE PERFORMANCE**',
        '🏆 **COMPETITOR COMPARISON**',
        '🎯 **SWOT ANALYSIS**',
        '📰 **NEWS & ANNOUNCEMENTS**',
        '👨‍💼 **EXPERT OPINION**',
        '🦈 **SHARK TANK PITCH**'
    ]
    
    for section in major_sections:
        # Single blank line before major sections
        content = re.sub(f'([^\n])({re.escape(section)})', r'\1\n\n\2', content)
        # No extra line after section headers
        content = re.sub(f'({re.escape(section)})\n\n([^\n])', r'\1\n\2', content)
    
    print(f"✅ Compact formatting complete")
    
    return content.strip()
    
    return content.strip()

# Debug LangSmith configuration
print(f"🔍 LangSmith Debug:")
print(f"  API Key: {'✅ Set' if os.getenv('LANGSMITH_API_KEY') else '❌ Missing'}")
print(f"  Project: {os.getenv('LANGSMITH_PROJECT')}")
print(f"  Tracing: {os.getenv('LANGSMITH_TRACING')}")

# Ensure LangSmith environment variables are set
os.environ["LANGSMITH_API_KEY"] = os.getenv("LANGSMITH_API_KEY", "")
os.environ["LANGSMITH_PROJECT"] = os.getenv("LANGSMITH_PROJECT", "trader_agent")
os.environ["LANGSMITH_ENDPOINT"] = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
os.environ["LANGSMITH_TRACING"] = os.getenv("LANGSMITH_TRACING", "true")

configure(project_name=os.getenv("LANGSMITH_PROJECT"))

# Test LangSmith tracing on app startup
@traceable(name="streamlit_app_startup")
def test_langsmith_on_startup():
    """Test function to verify LangSmith is working on app startup"""
    return f"Streamlit app started with LangSmith tracing - Project: {os.getenv('LANGSMITH_PROJECT')}"

# Call the test function
startup_result = test_langsmith_on_startup()
print(f"🚀 {startup_result}")

# Page configuration
st.set_page_config(
    page_title="Stock Analysis 🦈",
    page_icon="🦈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Advanced CSS with animations
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
    
    * {
        font-family: 'Inter', sans-serif;
    }
    
    .main-header {
        font-size: 3.5rem;
        font-weight: 700;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        text-align: center;
        padding: 2rem 0 1rem 0;
        animation: fadeIn 1s ease-in;
    }
    
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(-20px); }
        to { opacity: 1; transform: translateY(0); }
    }
    
    .hero-section {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 3rem;
        border-radius: 1rem;
        color: white;
        text-align: center;
        margin-bottom: 2rem;
        box-shadow: 0 10px 40px rgba(102, 126, 234, 0.3);
    }
    
    .hero-title {
        font-size: 2.5rem;
        font-weight: 700;
        margin-bottom: 1rem;
    }
    
    .hero-subtitle {
        font-size: 1.2rem;
        opacity: 0.9;
    }
    
    /* Custom chat message styling with column layout */
    .user-message-bubble {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 1rem 1.5rem;
        border-radius: 1.5rem 1.5rem 0.3rem 1.5rem;
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
        word-wrap: break-word;
        margin: 0.5rem 0;
    }
    
    .user-message-bubble p,
    .user-message-bubble h1,
    .user-message-bubble h2,
    .user-message-bubble h3,
    .user-message-bubble strong {
        color: white !important;
        margin: 0.5rem 0;
    }
    
    /* Style the assistant message wrapper */
    .assistant-msg-wrapper {
        background: white;
        color: #1f2937;
        padding: 1rem 1.5rem;
        border-radius: 1.5rem 1.5rem 1.5rem 0.3rem;
        border: 1px solid #e5e7eb;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
        margin: 0.5rem 0;
        display: block;
    }
    
    /* Ensure markdown content inside wrapper inherits styling */
    .assistant-msg-wrapper p,
    .assistant-msg-wrapper h1,
    .assistant-msg-wrapper h2,
    .assistant-msg-wrapper h3,
    .assistant-msg-wrapper ul,
    .assistant-msg-wrapper ol {
        color: #1f2937 !important;
    }
    
    /* COMPACT LINE SPACING - Reduce spacing in assistant messages */
    div[data-testid="column"] p {
        margin-top: 0 !important;
        margin-bottom: 0.2rem !important;
        line-height: 1.35 !important;
        text-indent: 0 !important;
        padding-left: 0 !important;
    }
    
    /* First paragraph should have no top margin */
    div[data-testid="column"] p:first-child {
        margin-top: 0 !important;
        padding-top: 0 !important;
    }
    
    div[data-testid="column"] ul,
    div[data-testid="column"] ol {
        margin-top: 0.2rem !important;
        margin-bottom: 0.2rem !important;
        padding-left: 1.5rem !important;
    }
    
    div[data-testid="column"] li {
        margin-top: 0 !important;
        margin-bottom: 0.1rem !important;
        line-height: 1.35 !important;
        padding-top: 0 !important;
        padding-bottom: 0 !important;
    }
    
    div[data-testid="column"] h1,
    div[data-testid="column"] h2,
    div[data-testid="column"] h3 {
        margin-top: 0.6rem !important;
        margin-bottom: 0.3rem !important;
        line-height: 1.25 !important;
        padding-top: 0 !important;
    }
    
    /* First heading should have no top margin */
    div[data-testid="column"] h1:first-child,
    div[data-testid="column"] h2:first-child,
    div[data-testid="column"] h3:first-child {
        margin-top: 0 !important;
    }
    
    /* Reduce spacing between paragraphs */
    div[data-testid="column"] .stMarkdown {
        line-height: 1.35 !important;
        margin-top: 0 !important;
        padding-top: 0 !important;
    }
    
    /* First markdown element should have no top spacing */
    div[data-testid="column"] .stMarkdown:first-child {
        margin-top: 0 !important;
        padding-top: 0 !important;
    }
    
    /* Compact bullet points and numbered lists */
    div[data-testid="column"] ul li,
    div[data-testid="column"] ol li {
        padding-top: 0 !important;
        padding-bottom: 0 !important;
        margin-top: 0 !important;
        margin-bottom: 0.1rem !important;
    }
    
    /* Remove any text indentation */
    div[data-testid="column"] * {
        text-indent: 0 !important;
    }
    
    /* Remove top padding from the column container itself */
    div[data-testid="column"] > div {
        padding-top: 0 !important;
        margin-top: 0 !important;
    }
    
    /* Ensure the styled message container has no top padding */
    div[data-testid="column"] > div[style*="background: white"] {
        padding-top: 1rem !important;
    }
    
    .message-avatar {
        width: 40px;
        height: 40px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.3rem;
        flex-shrink: 0;
        margin: 0.5rem auto;
    }
    
    .user-avatar {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    }
    
    .assistant-avatar {
        background: #f3f4f6;
    }
    
    /* Reduce column padding for chat messages */
    div[data-testid="column"] {
        padding: 0.25rem 0.5rem !important;
    }
    
    /* Improve chat input styling */
    .stChatInput {
        border-radius: 1.5rem !important;
        border: 2px solid #e2e8f0 !important;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05) !important;
        margin-top: 1rem !important;
    }
    
    .stChatInput:focus-within {
        border-color: #667eea !important;
        box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1) !important;
    }
    
    .metric-card {
        background: white;
        padding: 1.5rem;
        border-radius: 1rem;
        border-left: 4px solid #667eea;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        transition: transform 0.2s ease;
    }
    
    .metric-card:hover {
        transform: translateY(-2px);
    }
    
    /* Custom styling for competitor comparison table */
    .competitor-table {
        background: white;
        border-radius: 1rem;
        overflow: hidden;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        margin: 1rem 0;
    }
    
    .competitor-table .dataframe {
        border: none !important;
    }
    
    .competitor-table th {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
        color: white !important;
        font-weight: 600 !important;
        padding: 1rem !important;
        border: none !important;
    }
    
    .competitor-table td {
        padding: 0.8rem 1rem !important;
        border-bottom: 1px solid #e2e8f0 !important;
        border-left: none !important;
        border-right: none !important;
    }
    
    .competitor-table tr:hover {
        background-color: #f8fafc !important;
    }
    
    /* Highlight main company row */
    .competitor-table tr:has(td:contains("⭐")) {
        background-color: #fef3c7 !important;
        font-weight: 600 !important;
    }
    
    .stDataFrame {
        border-radius: 1rem;
        overflow: hidden;
    }
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 1rem;
        color: white;
        text-align: center;
        box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
        transition: transform 0.3s;
    }
    
    .metric-card:hover {
        transform: translateY(-5px);
    }
    
    .tool-card {
        background: white;
        padding: 1.5rem;
        border-radius: 0.75rem;
        border-left: 4px solid #667eea;
        margin-bottom: 1rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }
    
    .stButton>button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        padding: 0.75rem 2rem;
        font-weight: 600;
        border-radius: 0.5rem;
        transition: all 0.3s;
        box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
    }
    
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);
    }
</style>
""", unsafe_allow_html=True)


if 'deps' not in st.session_state:
    st.session_state.deps = ConversationState()

if 'message_history' not in st.session_state:
    st.session_state.message_history = [ModelRequest(parts=[SystemPromptPart(content=agent_system_prompt)])]

if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'current_stock' not in st.session_state:
    st.session_state.current_stock = None
if 'company_data' not in st.session_state:
    st.session_state.company_data = None



# Debug: Print current state
print(f"📊 Session state - Messages: {len(st.session_state.messages)}, Stock: {st.session_state.current_stock}")

# Sidebar
with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/000000/shark.png", width=80)
    st.title("Stock Analysis")
    st.markdown("---")
    
    # Current Analysis
    st.subheader("📊 Current Analysis")
    if st.session_state.current_stock:
        st.success(f"**{st.session_state.current_stock}**")
    else:
        st.info("No stock selected")
    
    st.markdown("---")
    
    # View Navigation (NEW - moved from top tabs)
    st.subheader("📑 View")
    view_option = st.radio(
        "Select View",
        ["💬 Chat", "📊 Data Dashboard", "📈 Analytics", "🔧 System Info"],
        label_visibility="collapsed",
        key="view_selector"
    )
    
    st.markdown("---")
    
    # Session Stats
    st.subheader("📈 Session Statistics")
    col1, col2 = st.columns(2)
    col1.metric("Messages", len(st.session_state.messages))
    col2.metric("Exchanges", len(st.session_state.messages)//2)
    
    # Message History Status
    if hasattr(st.session_state, 'message_history'):
        st.metric("Agent Memory", f"{len(st.session_state.message_history)} msgs", help="Number of messages in agent's conversation memory")
    
    # Message History Debug (only show if there are messages)
    if len(st.session_state.messages) > 0:
        with st.expander("🔧 Debug Info"):
            try:
                summary = {
                    'ui_messages': len(st.session_state.messages),
                    'agent_memory': len(st.session_state.message_history) if hasattr(st.session_state, 'message_history') else 0,
                    'has_company_data': bool(st.session_state.deps.company_data),
                    'current_stock': st.session_state.deps.stock_symbol,
                    'stock_name': st.session_state.deps.stock_name
                }
                st.json(summary)
            except:
                st.caption("Debug info not available")
    
    st.markdown("---")
    
    # Quick Actions
    st.subheader("⚡ Quick Actions")
    if st.button("🔄 New Analysis", width='stretch'):
        st.session_state.deps = ConversationState()
        st.session_state.message_history = [ModelRequest(parts=[SystemPromptPart(content=agent_system_prompt)])]
        st.session_state.messages = []
        st.session_state.current_stock = None
        st.session_state.company_data = None
        st.rerun()
    
    st.markdown("---")
    
    # Tools
    st.subheader("🔧 AI Tools")
    tools = [
        ("🔍", "Stock Validation & Fetch", "Web-powered symbol search (Tavily) and web insights (yfinance + Tavily)"),
        ("💬", "Q&A Handler", "Answers your questions"),
        ("🔮", "Scenario Analysis", "What-if projections/questionner"),
        ("📋", "Summary Report", "Investment insights")
    ]
    
    for icon, name, desc in tools:
        with st.expander(f"{icon} {name}"):
            st.caption(desc)

# Main content
st.markdown('<h1 class="main-header">🦈 Stock Analysis</h1>', unsafe_allow_html=True)

# Simplified hero section - only show if no messages
if len(st.session_state.messages) == 0:
    st.markdown("""
    <div class="hero-section">
        <div class="hero-title">AI-Powered Stock Analysis</div>
        <div class="hero-subtitle">
            Get comprehensive insights with real-time data and expert analysis
        </div>
    </div>
    """, unsafe_allow_html=True)

# Main content area - render based on sidebar selection
view_option = st.session_state.get("view_selector", "💬 Chat")

if view_option == "💬 Chat":
    # Chat interface - cleaner header
    st.markdown("### 💬 Chat")
    
    # Show welcome message if no messages yet
    if len(st.session_state.messages) == 0:
        st.info("👋 Hello! I'm your AI stock analyst. Tell me which stock to analyze!")
    
    # Chat messages - using inline HTML for complete control
    for idx, message in enumerate(st.session_state.messages):
        if message["role"] == "user":
            # User message - right aligned with purple gradient
            st.markdown(f"""
            <div style="display: flex; justify-content: flex-end; align-items: flex-start; margin: 1rem 0; gap: 0.75rem;">
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                            color: white; 
                            padding: 1rem 1.5rem; 
                            border-radius: 1.5rem 1.5rem 0.3rem 1.5rem; 
                            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3); 
                            max-width: 70%;
                            word-wrap: break-word;">
                    {message["content"]}
                </div>
                <div style="width: 40px; 
                            height: 40px; 
                            border-radius: 50%; 
                            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                            display: flex; 
                            align-items: center; 
                            justify-content: center; 
                            font-size: 1.3rem;
                            flex-shrink: 0;">
                    👤
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            # Assistant message - left aligned with white background
            # Convert markdown to HTML for proper rendering
            import re
            content = message["content"]
            
            # DEBUG: Log content length
            print(f"🔍 Rendering assistant message: {len(content)} characters, {content.count(chr(10))} lines")
            
            # Convert markdown bold to HTML
            content = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', content)
            
            # Convert markdown italic to HTML
            content = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', content)
            
            # Process line by line
            lines = content.split('\n')
            html_lines = []
            in_list = False
            
            for i, line in enumerate(lines):
                stripped = line.strip()
                
                # Empty line - close list if open, add spacing
                if not stripped:
                    if in_list:
                        html_lines.append('</ul>')
                        in_list = False
                    # Only add spacing between sections, not excessive breaks
                    if i > 0 and i < len(lines) - 1:
                        html_lines.append('<div style="height: 0.5rem;"></div>')
                    continue
                
                # Section headers (with emojis and bold)
                if stripped.startswith(('📊', '🏢', '📋', '💰', '📈', '📊', '🏆', '🎯', '📰', '👨‍💼', '🦈', '✅')):
                    if in_list:
                        html_lines.append('</ul>')
                        in_list = False
                    html_lines.append(f'<h3 style="margin: 0.8rem 0 0.4rem 0; font-size: 1.1rem; font-weight: 600; line-height: 1.3;">{stripped}</h3>')
                
                # Subsection headers (bold text without emoji, like "Income Statement:")
                elif '<strong>' in stripped and stripped.endswith('</strong>:'):
                    if in_list:
                        html_lines.append('</ul>')
                        in_list = False
                    html_lines.append(f'<p style="margin: 0.5rem 0 0.2rem 0; font-weight: 600; line-height: 1.35;">{stripped}</p>')
                
                # Bullet points
                elif stripped.startswith('• ') or stripped.startswith('- '):
                    if not in_list:
                        html_lines.append('<ul style="margin: 0.2rem 0; padding-left: 1.5rem; list-style-type: disc;">')
                        in_list = True
                    item_text = stripped[2:]
                    html_lines.append(f'<li style="margin: 0.1rem 0; line-height: 1.35;">{item_text}</li>')
                
                # Regular paragraph
                else:
                    if in_list:
                        html_lines.append('</ul>')
                        in_list = False
                    html_lines.append(f'<p style="margin: 0.2rem 0; line-height: 1.35;">{stripped}</p>')
            
            # Close list if still open
            if in_list:
                html_lines.append('</ul>')
            
            html_content = '\n'.join(html_lines)
            
            # DEBUG: Log HTML content length
            print(f"🔍 HTML conversion: {len(html_content)} characters, {len(html_lines)} HTML elements")
            print(f"🔍 First 200 chars: {html_content[:200]}")
            print(f"🔍 Last 200 chars: {html_content[-200:]}")
            
            # Render using flex layout (same as user message) for consistent spacing
            st.markdown(f"""
            <div style="display: flex; justify-content: flex-start; align-items: flex-start; margin: 1rem 0; gap: 0.75rem;">
                <div style="width: 40px; 
                            height: 40px; 
                            border-radius: 50%; 
                            background: #f3f4f6; 
                            display: flex; 
                            align-items: center; 
                            justify-content: center; 
                            font-size: 1.3rem;
                            flex-shrink: 0;">
                    🤖
                </div>
                <div style="background: white; 
                            color: #1f2937; 
                            padding: 1rem 1.5rem; 
                            border-radius: 1.5rem 1.5rem 1.5rem 0.3rem; 
                            border: 1px solid #e5e7eb; 
                            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
                            max-width: 70%;
                            word-wrap: break-word;">
                    {html_content}
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # Add download PDF button if this is a stock analysis report
            if len(message["content"]) > 500 and st.session_state.current_stock:
                from pdf_generator import generate_pdf_report
                
                # Generate PDF
                pdf_buffer = generate_pdf_report(
                    message["content"], 
                    st.session_state.current_stock
                )
                
                # Use the enumerate index directly - it's unique per render
                # Add role to make it even more unique (in case of re-ordering)
                unique_key = f"download_{message['role']}_{idx}"
                
                # Create download button with unique key
                st.download_button(
                    label="📥 Download PDF Report",
                    data=pdf_buffer,
                    file_name=f"{st.session_state.current_stock}_Analysis_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                    mime="application/pdf",
                    key=unique_key,
                    help="Download this analysis as a formatted PDF report"
                )
    
    # Chat input - ALWAYS visible at bottom
    user_input = st.chat_input("💬 Type your message here... (e.g., 'analyze ONGC' or 'tell me about reliance')", key="chat_input_main")
    
    if user_input:
        print(f"\n{'='*60}")
        print(f"📝 User input: {user_input}")
        print(f"{'='*60}")
        
        # Ensure session state is properly initialized
        if 'message_history' not in st.session_state:
            st.session_state.message_history = [ModelRequest(parts=[SystemPromptPart(content=agent_system_prompt)])]
        if 'deps' not in st.session_state:
            st.session_state.deps = ConversationState()
        
        st.session_state.messages.append({"role": "user", "content": user_input})
        
        with st.spinner("🤔 Analyzing..."):
            @traceable(name="pydantic_ai_agent_run")
            async def run_agent_async(user_input, message_history, deps):
                """Simple async wrapper for agent.run with error handling"""
                try:
                    result = await agent.run(
                        user_input, 
                        message_history=message_history, 
                        deps=deps
                    )
                    
                    return result, None
                except Exception as e:
                    error_msg = str(e)
                    print(f"❌ Agent.run() failed: {error_msg}")
                    
                    # Check for specific API validation errors
                    if "validation errors for ChatCompletion" in error_msg:
                        return None, "API response validation error. This is usually temporary - please try again."
                    elif "Invalid response from openai" in error_msg:
                        return None, "Invalid API response received. Please try again in a moment."
                    elif "timeout" in error_msg.lower():
                        return None, "Request timed out. Please try again."
                    else:
                        return None, f"Error: {error_msg}"
            
            def run_agent_sync(user_input):
                """Simplified synchronous wrapper with fallback and retry"""
                max_retries = 3
                
                for attempt in range(max_retries):
                    try:
                        print(f"🔄 Attempt {attempt + 1}/{max_retries}")
                        print(f"🚀 Starting agent.run() for input: {user_input[:50]}...")
                        
                        # Capture session state values
                        message_history = st.session_state.message_history.copy() if hasattr(st.session_state, 'message_history') else []
                        deps = st.session_state.deps if hasattr(st.session_state, 'deps') else ConversationState()
                        
                        # Run the async function directly
                        import asyncio
                        import concurrent.futures
                        import time as time_module
                        
                        start_time = time_module.time()
                        
                        try:
                            # Use ThreadPoolExecutor to run async code with timeout
                            # Increased timeout to 900 seconds (15 minutes) to handle complex analysis with PDF processing
                            with concurrent.futures.ThreadPoolExecutor() as executor:
                                future = executor.submit(
                                    lambda: asyncio.run(run_agent_async(user_input, message_history, deps))
                                )
                                result, error = future.result(timeout=900)  # 15 minute timeout
                                
                            elapsed_time = time_module.time() - start_time
                            print(f"✅ Agent.run() completed in {elapsed_time:.2f} seconds")
                            
                        except concurrent.futures.TimeoutError:
                            elapsed_time = time_module.time() - start_time
                            print(f"⏱️ Agent execution exceeded {elapsed_time:.2f} seconds (timeout: 900s / 15 minutes)")
                            
                            if attempt < max_retries - 1:
                                print(f"⚠️ Attempt {attempt + 1} timed out after {elapsed_time:.2f}s, retrying...")
                                continue
                            else:
                                print("⚠️ All attempts timed out, trying fallback approach...")
                                # Fallback: Try a simpler approach
                                try:
                                    loop = asyncio.new_event_loop()
                                    asyncio.set_event_loop(loop)
                                    try:
                                        result, error = loop.run_until_complete(run_agent_async(user_input, message_history, deps))
                                    finally:
                                        loop.close()
                                        asyncio.set_event_loop(None)
                                except Exception as fallback_error:
                                    return None, f"All methods failed. Last error: {str(fallback_error)}"
                        except Exception as e:
                            elapsed_time = time_module.time() - start_time
                            print(f"❌ Agent execution failed after {elapsed_time:.2f} seconds: {str(e)}")
                            
                            if attempt < max_retries - 1:
                                print(f"⚠️ Attempt {attempt + 1} failed: {str(e)}, retrying...")
                                continue
                            else:
                                return None, f"Execution error after {max_retries} attempts: {str(e)}"
                        
                        # Check if we got an error from the agent
                        if error:
                            print(f"⚠️ Agent returned error: {error}")
                            if "validation error" in error.lower() or "invalid response" in error.lower():
                                if attempt < max_retries - 1:
                                    print(f"⚠️ API validation error on attempt {attempt + 1}, retrying...")
                                    time.sleep(2)  # Brief delay before retry
                                    continue
                            return None, error
                        
                        # Check if result is valid before accepting it
                        if result and hasattr(result, 'output'):
                            output_text = result.output if hasattr(result, 'output') else str(result)
                            
                            # Validate that we got a meaningful response
                            if len(output_text) > 500:  # Substantial response
                                print(f"✅ Valid response received ({len(output_text)} characters)")
                            elif "Invalid selection" in output_text or "Please choose" in output_text:
                                # This is an error message, not a valid analysis
                                print(f"⚠️ Agent returned error message instead of analysis: {output_text[:100]}")
                                if attempt < max_retries - 1:
                                    print(f"⚠️ Retrying with fresh context...")
                                    continue
                                else:
                                    return None, "Failed to get valid analysis after multiple attempts"
                        
                        # Success! Update session state and return
                        st.session_state.deps = deps
                        
                        # Process and update message history
                        if hasattr(result, 'new_messages'):
                            new_messages = result.new_messages()
                            if new_messages:
                                print(f"📝 Processing {len(new_messages)} new messages from agent")
                                
                                # Filter messages to only keep text parts (remove tool calls/returns)
                                new_filtered_messages = []
                                for msg in new_messages:
                                    if isinstance(msg, ModelRequest):
                                        # Keep only UserPromptPart
                                        parts = [p for p in msg.parts if isinstance(p, UserPromptPart)]
                                        if parts:
                                            new_filtered_messages.append(ModelRequest(parts=parts))
                                    elif isinstance(msg, ModelResponse):
                                        # Keep only TextPart
                                        parts = [p for p in msg.parts if isinstance(p, TextPart)]
                                        if parts:
                                            new_filtered_messages.append(ModelResponse(parts=parts))
                                
                                # Update session state message history
                                st.session_state.message_history.extend(new_filtered_messages)
                                print(f"✅ Updated message history: {len(st.session_state.message_history)} total messages")
                        
                        return result, None
                        
                    except Exception as e:
                        if attempt < max_retries - 1:
                            print(f"⚠️ Attempt {attempt + 1} failed with exception: {str(e)}, retrying...")
                            time.sleep(2)  # Brief delay before retry
                            continue
                        else:
                            return None, f"Failed after {max_retries} attempts: {str(e)}"
                
                return None, f"All {max_retries} attempts failed"

            print("� Calling agent.run()...")
            print(f"📋 Current message history length: {len(st.session_state.message_history)}")
            
            result, error_msg = run_agent_sync(user_input)
            
            if error_msg:
                # Error Handling
                print(f"❌ Error in agent.run(): {error_msg}")
                
                # Provide user-friendly error messages
                if "validation error" in error_msg.lower():
                    response = """❌ **Temporary API Issue**

The AI service returned an invalid response. This is usually temporary and resolves quickly.

**What you can do:**
• Try your request again in a few seconds
• The system has automatic retry logic built-in
• If the issue persists, try rephrasing your question

*This is a known issue with the OpenRouter API that occurs occasionally.*"""
                elif "timed out" in error_msg.lower():
                    response = """⏰ **Request Timed Out**

Your request took longer than expected to process.

**What you can do:**
• Try your request again - it may work faster the second time
• For complex analysis, try asking for specific information first
• Check your internet connection

*The system will automatically retry failed requests.*"""
                else:
                    response = f"❌ **System Error**\n\n{error_msg}\n\n*Please try your request again.*"
            
            else:
                # Success - Process Response
                print(f"🔍 Agent result type: {type(result)}")
                print(f"🔍 Agent result attributes: {dir(result)}")
                
                if hasattr(result, 'data'):
                    response = result.data
                    print(f"📊 Using result.data: {type(response)}")
                elif hasattr(result, 'output'):
                    response = result.output
                    print(f"📊 Using result.output: {type(response)}")
                else:
                    response = str(result)
                    print(f"📊 Using str(result): {type(response)}")
                
                print(f"📄 Raw response preview: {str(response)[:200]}...")
                
                # VALIDATION: Check if agent is following tool output rules
                if isinstance(response, str):
                    # Check for signs that agent is generating its own response instead of using tool output
                    if "Selected Stock:" in response and "Selected:" not in response:
                        print("⚠️  WARNING: Agent appears to be generating its own response format instead of using tool output")
                        print("🔧 This suggests the agent is not following the system prompt correctly")
                    
                # CRITICAL: Extract content from ToolResponse object FIRST
                if isinstance(response, ToolResponse):
                    response = response.content
                    print(f"✅ Extracted ToolResponse content: {len(response)} characters")
                elif isinstance(response, dict):
                    response = "I encountered an issue with the response format. Please try again."
                else:
                    # Convert to string if needed
                    response = str(response)
                
                    # Check for proper tool output format
                    if response.startswith("✅ **Selected:") and "COMPREHENSIVE STOCK ANALYSIS" in response:
                        print("✅ Response appears to be proper tool output format")
                    elif len(response) > 1000 and any(section in response for section in ["COMPANY SNAPSHOT", "FINANCIAL METRICS", "STOCK INFORMATION"]):
                        print("✅ Response contains expected analysis sections")
                    else:
                        print("⚠️  Response format may not be complete tool output")
                
                # Fallback for short responses - but NOT for error messages
                if st.session_state.deps.company_data and not st.session_state.deps.report_generated:
                     # Only use fallback if response is short AND not an error message
                     if len(response) < 200 and not any(err in response for err in ["Invalid selection", "Please choose", "Error", "❌"]):
                         print("⚠️ Response too short, using fallback pitch")
                         response = StockTools._generate_static_pitch(st.session_state.deps.company_data)
                     elif len(response) >= 200:
                         # Mark as generated only if we have a substantial response
                         st.session_state.deps.report_generated = True

                # DISABLED: Apply comprehensive formatting fixes - format_data_for_report already handles this
                # response = fix_response_formatting(response)
                
                if 'tool_outputs' in response:
                    markers = ['🔍 **Multiple', '🏢 COMPANY', '📊 COMPREHENSIVE', 'Here is', '🤖 AI', '✓ Found:', '✅ **Selected', '✅']
                    for marker in markers:
                        if marker in response:
                            response = response[response.index(marker):]
                            break
                            
                if response.startswith('{') or response.startswith('tool_outputs'):
                    match = re.search(r'[🔍🏢📊🤖✓🦈📋💰📈🏆🎯📰✅]', response)
                    if match:
                        response = response[match.start():]
                
                # DISABLED: Final formatting pass - not needed, causes issues
                # response = fix_response_formatting(response)

            # Update Session State from Deps
            if st.session_state.deps.stock_name:
                st.session_state.current_stock = st.session_state.deps.stock_name
            if st.session_state.deps.company_data:
                st.session_state.company_data = st.session_state.deps.company_data
        
        # DISABLED: Final formatting check - format_data_for_report already produces clean output
        # debug_response_formatting(response, "BEFORE SAVING TO SESSION")
        
        # DISABLED: Apply one final formatting pass - causes formatting issues
        # final_response = streamlit_markdown_formatter(response)
        # debug_response_formatting(final_response, "FINAL FORMATTED RESPONSE")
        
        # Use response directly without additional formatting
        st.session_state.messages.append({"role": "assistant", "content": response})
        print(f"💾 Message saved to session state")
        st.rerun()

elif view_option == "📊 Data Dashboard":
    if st.session_state.company_data:
        data = st.session_state.company_data
        st.subheader(f"📊 {data.name} ({data.symbol})")
        col1, col2 = st.columns(2)

        # -------- Price Trend --------
        with col1:
            if data.market_data.price_history:
                st.subheader("📈 Price Trend")

                p1, p2, p3, p4, p5, p6 = st.columns(6)
                with p1: period_1w = st.button("1W", key="pt_1w")
                with p2: period_1m = st.button("1M", key="pt_1m")
                with p3: period_3m = st.button("3M", key="pt_3m")
                with p4: period_6m = st.button("6M", key="pt_6m")
                with p5: period_1y = st.button("1Y", key="pt_1y", type="primary")
                with p6: period_all = st.button("ALL", key="pt_all")

                if period_1w:
                    days = 7
                elif period_1m:
                    days = 30
                elif period_3m:
                    days = 90
                elif period_6m:
                    days = 180
                else:
                    days = 365

                all_dates = list(data.market_data.price_history.keys())
                all_prices = list(data.market_data.price_history.values())

                dates = all_dates[-days:]
                prices = all_prices[-days:]

                price_change = prices[-1] - prices[0] if len(prices) > 1 else 0
                is_positive = price_change >= 0

                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=dates,
                    y=prices,
                    mode="lines",
                    fill="tozeroy",
                    line=dict(
                        color="#10b981" if is_positive else "#ef4444",
                        width=2.5,
                        shape="spline"
                    )
                ))

                fig.update_layout(
                    template="plotly_white",
                    height=380,
                    yaxis=dict(tickprefix="₹"),
                    showlegend=False,
                    margin=dict(l=40, r=20, t=30, b=40)
                )

                st.plotly_chart(fig, width='stretch')

        with col2:
            st.subheader("💰 Financial Breakdown")
            if data.financials.revenue and data.financials.net_profit:
                # Determine currency and unit based on market
                is_indian = data.symbol.endswith('.NS') or data.symbol.endswith('.BO')
                divisor = 1e7 if is_indian else 1e9
                unit_label = "Cr" if is_indian else "Billion"
                currency_sym = "₹" if is_indian else "$"
                
                # Safely handle None values
                revenue_val = (data.financials.revenue or 0) / divisor
                net_profit_val = (data.financials.net_profit or 0) / divisor
                free_cash_flow_val = (data.financials.free_cash_flow or 0) / divisor
                
                fin_fig = go.Figure(data=[
                    go.Bar(
                        x=["Revenue", "Net Profit", "Free Cash Flow"],
                        y=[revenue_val, net_profit_val, free_cash_flow_val]
                    )
                ])
                fin_fig.update_layout(
                    template="plotly_white",
                    height=380,
                    yaxis_title=f"Amount ({currency_sym} {unit_label})"
                )
                st.plotly_chart(fin_fig, width='stretch')

        st.markdown("---")
        st.subheader("🔬 Technical Analysis")

        m1, m2, m3, m4 = st.columns(4)
        with m1:
            if data.market_data.current_price is not None:
                st.metric("Current Price", f"₹{data.market_data.current_price:.2f}")
            else:
                st.metric("Current Price", "N/A")
        with m2:
            if data.financials.pe_ratio:
                st.metric("PE Ratio", f"{data.financials.pe_ratio:.2f}")
            else:
                st.metric("PE Ratio", "N/A")
        with m3:
            if data.financials.profit_margin:
                st.metric("Profit Margin", f"{data.financials.profit_margin*100:.2f}%")
            else:
                st.metric("Profit Margin", "N/A")
        with m4:
            if data.market_data.market_cap:
                val = data.market_data.market_cap
                is_indian = data.symbol.endswith('.NS') or data.symbol.endswith('.BO')
                if is_indian:
                    fmt_val = f"₹{val/1e7:.2f} Cr" if val >= 1e7 else f"₹{val/1e5:.2f} L"
                else:
                    fmt_val = f"${val/1e9:.2f} B"
                st.metric("Market Cap", fmt_val)
            else:
                st.metric("Market Cap", "N/A")

        m5, m6, m7, m8 = st.columns(4)
        with m5:
            if getattr(data.financials, "ebitda", None):
                val = data.financials.ebitda
                is_indian = data.symbol.endswith('.NS') or data.symbol.endswith('.BO')
                if is_indian:
                    fmt_val = f"₹{val/1e7:.2f} Cr" if val >= 1e7 else f"₹{val/1e5:.2f} L"
                else:
                    fmt_val = f"${val/1e9:.2f} B"
                st.metric("EBITDA", fmt_val)
            else:
                st.metric("EBITDA", "N/A")
        with m6:
            if getattr(data.financials, "eps", None):
                st.metric("EPS", f"{data.financials.eps:.2f}")
            else:
                st.metric("EPS", "N/A")
        with m7:
            if getattr(data.financials, "debt_to_equity", None):
                st.metric("Debt / Equity", f"{data.financials.debt_to_equity:.2f}")
            else:
                st.metric("Debt / Equity", "N/A")
        with m8:
            # Display Max Drop After High
            max_drop = getattr(data.market_data, 'max_drop_after_high', None)
            if max_drop is not None:
                st.metric("Max Drop After High", f"{max_drop:.2f}%")
            else:
                st.metric("Max Drop After High", "N/A")

        # New row for Overall High, Overall Low, Percentage Change, and Selection Status
        m9, m10, m11, m12 = st.columns(4)
        with m9:
            if data.market_data.overall_high is not None:
                st.metric("Overall High", f"₹{data.market_data.overall_high:.2f}")
            else:
                st.metric("Overall High", "N/A")
        with m10:
            if data.market_data.overall_low is not None:
                st.metric("Overall Low", f"₹{data.market_data.overall_low:.2f}")
            else:
                st.metric("Overall Low", "N/A")
        with m11:
            if data.market_data.percentage_change_from_high is not None:
                delta_color = "inverse" if data.market_data.percentage_change_from_high < 0 else "normal"
                st.metric("% Change from High", f"{data.market_data.percentage_change_from_high:.2f}%", 
                         delta=f"{data.market_data.percentage_change_from_high:.2f}%")
            else:
                st.metric("% Change from High", "N/A")
        with m12:
            # Display selection status based on maximum drop after high
            # Use getattr for backward compatibility with old data
            max_drop = getattr(data.market_data, 'max_drop_after_high', None)
            
            if max_drop is not None:
                is_selected = max_drop <= -25
                status_text = "✅ Selected" if is_selected else "❌ Not Selected"
                st.metric("Selection Status", status_text)
                
                # Show explanation in small text
                if is_selected:
                    st.caption(f"Dropped {abs(max_drop):.1f}% after peak")
            elif data.market_data.percentage_change_from_high is not None:
                # Fallback to current price comparison
                is_selected = data.market_data.percentage_change_from_high <= -25
                status_text = "✅ Selected" if is_selected else "❌ Not Selected"
                st.metric("Selection Status", status_text)
            else:
                st.metric("Selection Status", "N/A")

        # Initialize default values for price analysis
        all_dates = []
        all_prices = []
        
        # Get price history if available
        if data.market_data.price_history:
            all_dates = list(data.market_data.price_history.keys())
            all_prices = list(data.market_data.price_history.values())

        # Only perform technical analysis if we have price data
        if all_prices and len(all_prices) > 1:
            prices_series = pd.Series(
                all_prices, index=pd.to_datetime(all_dates)
            )

            sma20 = prices_series.rolling(20).mean()
            sma50 = prices_series.rolling(50).mean()
            sma200 = prices_series.rolling(200).mean()

            returns = prices_series.pct_change().dropna()
            volatility = returns.std() * (252 ** 0.5)

            delta = prices_series.diff()
            up = delta.clip(lower=0)
            down = -delta.clip(upper=0)
            rs = up.rolling(14).mean() / down.rolling(14).mean()
            rsi = 100 - (100 / (1 + rs))

            latest_price = prices_series.iloc[-1]
            latest_sma50 = sma50.dropna().iloc[-1] if not sma50.dropna().empty else None
            trend = "Bullish" if latest_sma50 and latest_price > latest_sma50 else "Bearish"

            st.markdown("**Technical Summary**")
            st.write(f"- Trend: {trend}")
            st.write(f"- Annualized Volatility: {volatility:.2%}")

            sma_fig = go.Figure()
            sma_fig.add_trace(go.Scatter(x=prices_series.index, y=prices_series, name="Price"))
            sma_fig.add_trace(go.Scatter(x=sma20.index, y=sma20, name="SMA 20"))
            sma_fig.add_trace(go.Scatter(x=sma50.index, y=sma50, name="SMA 50"))
            sma_fig.add_trace(go.Scatter(x=sma200.index, y=sma200, name="SMA 200"))

            sma_fig.update_layout(
                title="Price with Simple Moving Averages",
                template="plotly_white",
                height=350
            )
            st.plotly_chart(sma_fig, width='stretch')

            # -------- RSI Chart --------
            if not rsi.dropna().empty:
                rsi_fig = go.Figure()
                rsi_fig.add_trace(go.Scatter(x=rsi.index, y=rsi, name="RSI"))
                rsi_fig.add_hline(y=70, line_dash="dash", line_color="red")
                rsi_fig.add_hline(y=30, line_dash="dash", line_color="green")
                rsi_fig.update_layout(
                    title="RSI (14)",
                    template="plotly_white",
                    height=220
                )
                st.plotly_chart(rsi_fig, width='stretch')
        else:
            st.info("📊 No price history available for technical analysis")

        # =========================
        # =========================
        # Competitors (with detailed table)
        # =========================
        if data.market_data.competitors:
            st.markdown("---")
            st.subheader("🏢 Competitors")
            st.markdown("*Real-time financial data*")
            
            # Create competitor comparison table (METRIC-BASED FORMAT)
            import pandas as pd
            
            # Prepare data for metric-based table (metrics as rows, companies as columns)
            companies = []
            company_data = {}
            
            for competitor in data.market_data.competitors:
                if isinstance(competitor, dict):
                    name = competitor.get('name', 'Unknown')
                    symbol = competitor.get('symbol', 'N/A')
                    market_cap = competitor.get('market_cap', 'N/A')
                    pe_ratio = competitor.get('pe_ratio', 'N/A')
                    profit_margin = competitor.get('profit_margin', 'N/A')
                    revenue = competitor.get('revenue', 'N/A')
                    is_main = competitor.get('is_main_company', False)
                    
                    # Create company column header with star for main company
                    if is_main:
                        # Shorten company name for main company and add star
                        short_name = name.split()[0] if ' ' in name else name
                        company_header = f"{short_name} ⭐"
                    else:
                        # Shorten company names for better display
                        short_name = name.split()[0] if ' ' in name else name
                        company_header = short_name
                    
                    companies.append(company_header)
                    
                    # Format values
                    # Market Cap
                    if isinstance(market_cap, (int, float)) and market_cap != 'N/A':
                        if market_cap >= 1e7:  # 1 Crore
                            mcap_formatted = f"₹{market_cap/1e7:.2f} Cr"
                        else:
                            mcap_formatted = f"₹{market_cap/1e5:.2f} L"
                    else:
                        mcap_formatted = 'N/A'
                    
                    # PE Ratio
                    pe_formatted = f"{pe_ratio:.2f}" if isinstance(pe_ratio, (int, float)) else 'N/A'
                    
                    # Profit Margin
                    if isinstance(profit_margin, (int, float)) and profit_margin != 'N/A':
                        pm_formatted = f"{profit_margin * 100:.2f}%"
                    else:
                        pm_formatted = 'N/A'
                    
                    # Revenue
                    if isinstance(revenue, (int, float)) and revenue != 'N/A':
                        if revenue >= 1e7:  # 1 Crore
                            revenue_formatted = f"₹{revenue/1e7:.2f} Cr"
                        else:
                            revenue_formatted = f"₹{revenue/1e5:.2f} L"
                    else:
                        revenue_formatted = 'N/A'
                    
                    # Store formatted data
                    company_data[company_header] = {
                        'Symbol': symbol,
                        'Market Cap': mcap_formatted,
                        'PE Ratio': pe_formatted,
                        'Profit Margin': pm_formatted,
                        'Revenue': revenue_formatted
                    }
            
            # Create metric-based table data
            if companies and company_data:
                # Define metrics to display
                metrics = ['Symbol', 'Market Cap', 'Revenue', 'PE Ratio', 'Profit Margin']
                
                # Build table data with metrics as rows
                table_data = {}
                table_data['Metric'] = metrics
                
                for company in companies:
                    table_data[company] = [
                        company_data[company].get('Symbol', 'N/A'),
                        company_data[company].get('Market Cap', 'N/A'),
                        company_data[company].get('Revenue', 'N/A'),
                        company_data[company].get('PE Ratio', 'N/A'),
                        company_data[company].get('Profit Margin', 'N/A')
                    ]
                
                # Create DataFrame
                df = pd.DataFrame(table_data)
                
                # Add custom container for styling
                st.markdown('<div class="competitor-table">', unsafe_allow_html=True)
                
                # Display the table with custom styling
                st.dataframe(
                    df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Metric": st.column_config.TextColumn(
                            "Metric",
                            width="medium",
                        ),
                        **{company: st.column_config.TextColumn(
                            company,
                            width="medium",
                        ) for company in companies}
                    }
                )
                
                st.markdown('</div>', unsafe_allow_html=True)
                
                # Add legend
                st.caption("⭐ = Your selected company | Data from real-time sources")
    else:
        st.info("📊 Analyze a stock to see the data dashboard")


elif view_option == "📈 Analytics":
    # Analytics - Sentiment Analysis
    if st.session_state.company_data:
        data = st.session_state.company_data
        stock_name = data.name
        stock_symbol = data.symbol
        
        # ===== FIRST: Current Market Sentiment Section =====
        st.subheader("📈 Current Market Sentiment")
        st.caption("Real-time sentiment from News, Yahoo Finance, and Twitter/X")
        
        # Check if sentiment analysis is already cached
        if 'sentiment_data' not in st.session_state or st.session_state.get('sentiment_stock') != stock_symbol:
            with st.spinner("🔍 Analyzing market sentiment from multiple sources (News, Yahoo Finance, Reddit, Twitter)..."):
                from sentiment_analyzer_adanos import analyze_stock_sentiment
                
                try:
                    # Extract base ticker for Adanos API (remove .NS, .BO, etc.)
                    ticker = stock_symbol.split('.')[0]
                    sentiment_data = analyze_stock_sentiment(stock_name, stock_symbol, ticker)
                    st.session_state.sentiment_data = sentiment_data
                    st.session_state.sentiment_stock = stock_symbol
                except Exception as e:
                    st.error(f"❌ Error analyzing sentiment: {e}")
                    sentiment_data = None
        else:
            sentiment_data = st.session_state.sentiment_data
        
        if sentiment_data:
            # Overall Sentiment Score
            st.markdown("### 🎯 Overall Market Sentiment")
            
            col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
            
            with col1:
                # Sentiment gauge
                score = sentiment_data['overall_score']
                label = sentiment_data['overall_label']
                color = sentiment_data['color']
                
                # Build sources text based on available data
                sources = ["News", "Yahoo Finance"]
                if 'twitter_sentiment' in sentiment_data:
                    sources.append("Twitter/X")
                sources_text = ", ".join(sources)
                
                st.markdown(f"""
                <div style="background: linear-gradient(135deg, {color}22 0%, {color}44 100%); 
                            padding: 2rem; border-radius: 1rem; border-left: 5px solid {color};">
                    <div style="font-size: 3rem; font-weight: bold; color: {color};">{score}/100</div>
                    <div style="font-size: 1.5rem; font-weight: 600; margin-top: 0.5rem;">{label}</div>
                    <div style="margin-top: 1rem; color: #666;">
                        Based on {sources_text}
                    </div>
                </div>
                """, unsafe_allow_html=True)
            
            with col2:
                news_score = sentiment_data['news_sentiment']['sentiment_score']
                news_label = sentiment_data['news_sentiment']['sentiment_label']
                st.metric("📰 News Sentiment", f"{news_score}/100", news_label)
            
            with col3:
                yahoo_score = sentiment_data['yahoo_sentiment']['sentiment_score']
                yahoo_rating = sentiment_data['yahoo_sentiment']['analyst_rating']
                st.metric("📊 Yahoo Finance", f"{yahoo_score}/100", yahoo_rating)
            
            with col4:
                # Add Twitter/X sentiment metric if available
                if 'twitter_sentiment' in sentiment_data:
                    twitter_score = sentiment_data['twitter_sentiment']['sentiment_score']
                    twitter_label = sentiment_data['twitter_sentiment']['sentiment_label']
                    st.metric("🐦 Twitter/X", f"{twitter_score}/100", twitter_label)
                else:
                    st.metric("🐦 Twitter/X", "N/A", "No data")
            
            # Twitter/X Sentiment - Display directly below Overall Market Sentiment
            if 'twitter_sentiment' in sentiment_data:
                st.markdown("---")
                st.markdown("### 🐦 Twitter/X Sentiment")
                
                twitter_data = sentiment_data['twitter_sentiment']
                
                # Show source information
                source = twitter_data.get('source', 'unknown')
                if source == 'rapidapi_twitter':
                    tweet_count = twitter_data.get('tweet_count', 0)
                    st.info(f"📊 Based on {tweet_count} recent tweets from Twitter/X via RapidAPI")
                elif source == 'news_based_twitter':
                    st.warning(f"📰 Based on news articles (Twitter data not available)")
                
                # Twitter sentiment score and breakdown
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    twitter_score = twitter_data.get('sentiment_score', 0)
                    twitter_label = twitter_data.get('sentiment_label', 'N/A')
                    
                    # Color based on sentiment
                    if twitter_score >= 60:
                        twitter_color = "#10b981"
                    elif twitter_score >= 40:
                        twitter_color = "#fbbf24"
                    else:
                        twitter_color = "#ef4444"
                    
                    st.markdown(f"""
                    <div style="background: linear-gradient(135deg, {twitter_color}22 0%, {twitter_color}44 100%); 
                                padding: 1.5rem; border-radius: 0.75rem; border-left: 4px solid {twitter_color};">
                        <div style="font-size: 2rem; font-weight: bold; color: {twitter_color};">{twitter_score}/100</div>
                        <div style="font-size: 1rem; font-weight: 600; margin-top: 0.5rem;">{twitter_label}</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col2:
                    positive_pct = twitter_data.get('positive_percentage', 0)
                    st.metric("👍 Positive", f"{positive_pct}%")
                
                with col3:
                    negative_pct = twitter_data.get('negative_percentage', 0)
                    st.metric("👎 Negative", f"{negative_pct}%")
                
                with col4:
                    neutral_pct = twitter_data.get('neutral_percentage', 0)
                    st.metric("😐 Neutral", f"{neutral_pct}%")
                
                # Show top engaging tweets if available
                if twitter_data.get('top_tweets'):
                    with st.expander("🔥 Top Engaging Tweets"):
                        for i, tweet in enumerate(twitter_data['top_tweets'][:5], 1):
                            sentiment_emoji = "✅" if tweet.get('sentiment_label') == 'Positive' else "⚠️" if tweet.get('sentiment_label') == 'Negative' else "➖"
                            tweet_text = tweet.get('text', 'N/A')
                            engagement = tweet.get('favorites', 0) + tweet.get('retweets', 0)
                            st.markdown(f"{sentiment_emoji} **Tweet {i}:** {tweet_text[:200]}...")
                            st.caption(f"❤️ {tweet.get('favorites', 0)} | 🔄 {tweet.get('retweets', 0)} | 💬 {tweet.get('replies', 0)}")
                            if i < 5:
                                st.markdown("---")
            
            st.markdown("---")
            
            # Sentiment Breakdown
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("### 📈 Positive Factors")
                positive_points = sentiment_data['news_sentiment'].get('positive_points', [])
                if positive_points and positive_points != ['Insufficient data']:
                    for point in positive_points:
                        st.markdown(f"✅ {point}")
                else:
                    st.info("No significant positive factors identified")
            
            with col2:
                st.markdown("### 📉 Negative Factors")
                negative_points = sentiment_data['news_sentiment'].get('negative_points', [])
                if negative_points and negative_points != ['Insufficient data']:
                    for point in negative_points:
                        st.markdown(f"⚠️ {point}")
                else:
                    st.info("No significant negative factors identified")
            
            st.markdown("---")
            
            # Market Mood Summary
            st.markdown("### 💭 Market Mood & Analysis")
            st.markdown(sentiment_data['final_analysis'])
            
            st.markdown("---")
            
            # Yahoo Finance Insights
            st.markdown("### 📊 Yahoo Finance Insights")
            
            yahoo_data = sentiment_data['yahoo_sentiment']
            
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                buy_count = yahoo_data.get('buy_recommendations', 0)
                st.metric("👍 Buy", buy_count)
            
            with col2:
                hold_count = yahoo_data.get('hold_recommendations', 0)
                st.metric("✋ Hold", hold_count)
            
            with col3:
                sell_count = yahoo_data.get('sell_recommendations', 0)
                st.metric("👎 Sell", sell_count)
            
            with col4:
                price_target = yahoo_data.get('average_price_target')
                if price_target:
                    st.metric("🎯 Avg Target", f"₹{price_target:.2f}")
                else:
                    st.metric("🎯 Avg Target", "N/A")
            
            # Yahoo Insights
            yahoo_insights = yahoo_data.get('key_insights', [])
            if yahoo_insights and yahoo_insights != ['Insufficient data from Yahoo Finance']:
                st.markdown("**Key Insights:**")
                for insight in yahoo_insights:
                    st.markdown(f"• {insight}")
            
            st.markdown("---")
            
            # News Sources Breakdown
            st.markdown("### 📰 News Sources Analysis")
            
            news_articles = sentiment_data['news_sentiment'].get('news_articles', [])
            
            if news_articles:
                # Group by source
                source_counts = {}
                for article in news_articles:
                    source = article['source']
                    source_counts[source] = source_counts.get(source, 0) + 1
                
                # Display source breakdown
                cols = st.columns(min(len(source_counts), 4))
                for idx, (source, count) in enumerate(source_counts.items()):
                    with cols[idx % len(cols)]:
                        st.metric(source.replace('.com', '').title(), count)
                
                st.markdown("---")
                
                # Show recent news articles
                st.markdown("**Recent News Articles:**")
                for article in news_articles[:5]:
                    with st.expander(f"📄 {article['title'][:80]}..."):
                        st.markdown(f"**Source:** {article['source']}")
                        st.markdown(f"**Content:** {article['content'][:300]}...")
                        if article.get('url'):
                            st.markdown(f"[Read full article →]({article['url']})")
            else:
                st.info("No news articles found for sentiment analysis")
            
            # Refresh button
            st.markdown("---")
            if st.button("🔄 Refresh Sentiment Analysis"):
                if 'sentiment_data' in st.session_state:
                    del st.session_state.sentiment_data
                if 'sentiment_stock' in st.session_state:
                    del st.session_state.sentiment_stock
                st.rerun()
        
        else:
            st.error("Unable to perform sentiment analysis. Please try again.")
        
        # ===== SECOND: Future Outlook & News Analysis Section =====
        st.markdown("---")
        st.markdown("---")
        st.subheader("🔮 Future Outlook & News Analysis")
        st.caption("AI-powered analysis of future expectations from top financial sources")
        
        # Check if news analysis is already cached
        if 'news_analysis' not in st.session_state or st.session_state.get('news_analysis_stock') != stock_symbol:
            with st.spinner("🔍 Searching for latest news and analyst forecasts from top financial sources..."):
                from tools import StockTools
                
                try:
                    news_result = StockTools.get_stock_news_analysis(stock_name, max_articles=10)
                    st.session_state.news_analysis = news_result
                    st.session_state.news_analysis_stock = stock_symbol
                except Exception as e:
                    st.error(f"❌ Error fetching news analysis: {e}")
                    news_result = None
        else:
            news_result = st.session_state.news_analysis
        
        if news_result and not news_result.get('error'):
            # Display the full LLM analysis
            st.markdown("### 📝 Detailed Analysis")
            analysis_text = news_result.get('analysis', 'No analysis available')
            st.markdown(analysis_text)
            
            st.markdown("---")
            
            # Display Tavily Summary
            if news_result.get('tavily_summary'):
                st.markdown("### 🌐 Web Search Summary")
                st.info(news_result['tavily_summary'])
                st.markdown("---")
            
            # Display Source Articles
            st.markdown("### 📚 Source Articles")
            articles = news_result.get('articles', [])
            
            if articles:
                # Show article count by source
                source_counts = {}
                for article in articles:
                    source = article.get('source', 'Unknown')
                    source_counts[source] = source_counts.get(source, 0) + 1
                
                st.markdown("**Sources:**")
                cols = st.columns(min(len(source_counts), 5))
                for idx, (source, count) in enumerate(source_counts.items()):
                    with cols[idx % len(cols)]:
                        st.metric(source, count)
                
                st.markdown("---")
                
                # Display articles
                for i, article in enumerate(articles, 1):
                    with st.expander(f"📄 {i}. {article.get('title', 'Untitled')[:80]}..."):
                        st.markdown(f"**Source:** {article.get('source', 'Unknown')}")
                        st.markdown(f"**Snippet:** {article.get('snippet', 'No preview available')}")
                        if article.get('url'):
                            st.markdown(f"[🔗 Read full article]({article['url']})")
            
            # Refresh button for news analysis
            st.markdown("---")
            if st.button("🔄 Refresh News Analysis", key="refresh_news"):
                if 'news_analysis' in st.session_state:
                    del st.session_state.news_analysis
                if 'news_analysis_stock' in st.session_state:
                    del st.session_state.news_analysis_stock
                st.rerun()
        
        elif news_result and news_result.get('error'):
            st.warning(f"⚠️ {news_result['error']}")
        
        # ===== Update Database with Sentiment Data =====
        # After both sentiment analyses are complete, update the database
        if sentiment_data and news_result and not news_result.get('error'):
            try:
                from database import StockDatabase
                
                # Extract market sentiment text and status
                market_senti_text = ""
                market_senti_status = "neutral"
                
                if 'overall_sentiment' in sentiment_data:
                    overall = sentiment_data['overall_sentiment']
                    market_senti_text = f"Overall Score: {overall.get('score', 'N/A')}\n"
                    market_senti_text += f"Label: {overall.get('label', 'N/A')}\n"
                    market_senti_status = overall.get('label', 'neutral').lower()
                
                # Add individual source sentiments
                for source in ['news', 'yahoo', 'twitter']:
                    if f'{source}_sentiment' in sentiment_data:
                        source_data = sentiment_data[f'{source}_sentiment']
                        market_senti_text += f"\n{source.title()}: {source_data.get('label', 'N/A')} ({source_data.get('score', 'N/A')})"
                
                # Extract future sentiment text and status
                future_senti_text = news_result.get('analysis', '')
                
                # Determine future sentiment status from analysis text
                future_senti_status = "neutral"
                if future_senti_text:
                    text_lower = future_senti_text.lower()
                    positive_keywords = ['positive', 'bullish', 'growth', 'strong', 'optimistic', 'upside']
                    negative_keywords = ['negative', 'bearish', 'decline', 'weak', 'pessimistic', 'downside']
                    
                    positive_count = sum(1 for keyword in positive_keywords if keyword in text_lower)
                    negative_count = sum(1 for keyword in negative_keywords if keyword in text_lower)
                    
                    if positive_count > negative_count:
                        future_senti_status = "positive"
                    elif negative_count > positive_count:
                        future_senti_status = "negative"
                
                # Update database
                db = StockDatabase()
                if db.connect():
                    # Get the latest analysis for this stock
                    latest = db.get_latest_analysis(stock_symbol)
                    
                    if latest:
                        # Update the existing record with sentiment data
                        update_query = """
                        UPDATE stock_analysis
                        SET market_senti = %s,
                            current_market_senti_status = %s,
                            future_senti = %s,
                            future_senti_status = %s
                        WHERE id = %s
                        """
                        db.cursor.execute(update_query, (
                            market_senti_text,
                            market_senti_status,
                            future_senti_text,
                            future_senti_status,
                            latest['id']
                        ))
                        db.conn.commit()
                        print(f"✅ Sentiment data updated in database for {stock_name}")
                    
                    db.disconnect()
            except Exception as db_error:
                print(f"⚠️ Database sentiment update error: {db_error}")
                # Continue even if database update fails
    
    else:
        st.info("📈 Analyze a stock to see analytics")

elif view_option == "🔧 System Info":
    # System Info
    st.subheader("🔧 System Information")
    st.info("**Pydantic AI Agent**: Using Google Gemini with 4-key rotation")
    st.info("**Tools**: Stock validation, Q&A, scenario analysis, summaries")
    st.info("**Data Sources**: Yahoo Finance + Tavily web search (screener.in only)")

# Footer
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #94a3b8; padding: 1rem; font-size: 0.85rem;">
    <strong>Stock Analysis</strong> | AI-Powered Investment Insights
</div>
""", unsafe_allow_html=True)
