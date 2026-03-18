# -*- coding: utf-8 -*-
#streamlit run app_advanced.py --server.address=0.0.0.0 --server.port=8501
# ngrok config add-authtoken 36bmLDf1FVuILZCpcmXzY6x9TjC_3d1YjRnaX4wD2eFZrwH7f

import streamlit as st
import streamlit.components.v1 as components
from agent1 import agent, ConversationState, ToolResponse, agent_system_prompt
from mcp_agent import mcp_agent, MCPConversationState, create_mcp_state, is_mcp_enabled
from datetime import datetime
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from tools import StockTools
from langsmith import traceable
from langsmith.integrations.otel import configure
import re
import os
import time
import json
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
        color: #74e504;
        text-align: center;
        padding: 2rem 0 1rem 0;
        animation: fadeIn 1s ease-in;
    }
    
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(-20px); }
        to { opacity: 1; transform: translateY(0); }
    }
    
    .hero-section {
        background: #74e504;
        padding: 3rem;
        border-radius: 1rem;
        color: white;
        text-align: center;
        margin-bottom: 2rem;
        box-shadow: 0 10px 40px rgba(116, 229, 4, 0.3);
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
    
    /* Custom chat message styling with solid color */
    .user-message-bubble {
        background: #74e504;
        color: white;
        padding: 1rem 1.5rem;
        border-radius: 1.5rem 1.5rem 0.3rem 1.5rem;
        box-shadow: 0 4px 12px rgba(116, 229, 4, 0.3);
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
    
    /* FIXED: Assistant message container with proper overflow handling */
    .assistant-message-container {
        display: flex !important;
        justify-content: flex-start !important;
        align-items: flex-start !important;
        margin: 1rem 0 !important;
        gap: 0.75rem !important;
        width: 100% !important;
    }
    
    .assistant-avatar-fixed {
        width: 40px !important;
        height: 40px !important;
        border-radius: 50% !important;
        background: #d4f4aa !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        font-size: 1.3rem !important;
        flex-shrink: 0 !important;
        color: #2E590E !important;
    }
    
    .assistant-content-box {
        background: white !important;
        color: #1f2937 !important;
        padding: 1rem 1.5rem !important;
        border-radius: 1.5rem 1.5rem 1.5rem 0.3rem !important;
        border: 1px solid #d4f4aa !important;
        box-shadow: 0 2px 8px rgba(116, 229, 4, 0.08) !important;
        max-width: calc(70% - 50px) !important;
        width: auto !important;
        word-wrap: break-word !important;
        overflow-wrap: break-word !important;
        overflow-x: hidden !important;
        overflow-y: visible !important;
        box-sizing: border-box !important;
        hyphens: auto !important;
    }
    
    /* Force all content inside to respect boundaries */
    .assistant-content-box * {
        max-width: 100% !important;
        word-wrap: break-word !important;
        overflow-wrap: break-word !important;
        box-sizing: border-box !important;
        hyphens: auto !important;
    }
    
    /* Handle specific content types */
    .assistant-content-box h1,
    .assistant-content-box h2,
    .assistant-content-box h3,
    .assistant-content-box h4,
    .assistant-content-box h5,
    .assistant-content-box h6 {
        word-break: break-word !important;
        overflow-wrap: break-word !important;
        hyphens: auto !important;
    }
    
    .assistant-content-box p {
        word-break: break-word !important;
        overflow-wrap: break-word !important;
        hyphens: auto !important;
    }
    
    .assistant-content-box ul,
    .assistant-content-box ol {
        word-break: break-word !important;
        overflow-wrap: break-word !important;
    }
    
    .assistant-content-box li {
        word-break: break-word !important;
        overflow-wrap: break-word !important;
        hyphens: auto !important;
    }
    
    /* Handle long words and URLs */
    .assistant-content-box a {
        word-break: break-all !important;
        overflow-wrap: break-word !important;
    }
    
    /* Handle code and pre blocks */
    .assistant-content-box pre,
    .assistant-content-box code {
        white-space: pre-wrap !important;
        word-break: break-all !important;
        overflow-wrap: break-word !important;
        max-width: 100% !important;
        overflow-x: auto !important;
    }
    
    /* Handle tables */
    .assistant-content-box table {
        width: 100% !important;
        table-layout: fixed !important;
        word-wrap: break-word !important;
        border-collapse: collapse !important;
    }
    
    .assistant-content-box td,
    .assistant-content-box th {
        word-wrap: break-word !important;
        overflow-wrap: break-word !important;
        hyphens: auto !important;
        max-width: 0 !important;
        overflow: hidden !important;
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
        background: #74e504;
    }
    
    .assistant-avatar {
        background: #d4f4aa;
        color: #2E590E;
    }
    
    /* Reduce column padding for chat messages */
    div[data-testid="column"] {
        padding: 0.25rem 0.5rem !important;
    }
    
    /* Improve chat input styling with light green theme */
    .stChatInput {
        border-radius: 1.5rem !important;
        border: 2px solid #d4f4aa !important;
        box-shadow: 0 2px 8px rgba(116, 229, 4, 0.05) !important;
        margin-top: 1rem !important;
    }
    
    .stChatInput:focus-within {
        border-color: #74e504 !important;
        box-shadow: 0 0 0 3px rgba(116, 229, 4, 0.1) !important;
    }
    
    .metric-card {
        background: white;
        padding: 1.5rem;
        border-radius: 1rem;
        border-left: 4px solid #74e504;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        transition: transform 0.2s ease;
    }
    
    /* Custom success and info styling with light green theme */
    .stSuccess {
        background-color: #d4f4aa !important;
        border-left: 4px solid #74e504 !important;
        color: #2E590E !important;
    }
    
    .stInfo {
        background-color: #d4f4aa !important;
        border-left: 4px solid #74e504 !important;
        color: #2E590E !important;
    }
    
    /* Light green theme for metric cards */
    .metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(116, 229, 4, 0.15);
    }
    
    /* Hide ALL link icons and external link indicators */
    
    /* Streamlit specific link icon removal */
    .stApp a::after,
    .main a::after,
    [data-testid="stAppViewContainer"] a::after {
        display: none !important;
        content: none !important;
        visibility: hidden !important;
    }
    
    /* Remove external link icons from markdown */
    .stMarkdown a[href^="http"]::after,
    .stMarkdown a[href^="https"]::after {
        display: none !important;
        content: none !important;
    }
    
    /* Hide any pseudo-elements that might contain link icons */
    a::before,
    a::after {
        display: none !important;
        content: none !important;
        visibility: hidden !important;
    }
    
    /* Specific targeting for external link indicators */
    .css-1v0mbdj a::after,
    .css-16huue1 a::after,
    .element-container a::after {
        display: none !important;
    }
    
    /* Light green welcome message styling */
    .welcome-message {
        background-color: #d4f4aa;
        color: #2E590E;
        padding: 1rem 1.5rem;
        border-radius: 0.75rem;
        border-left: 4px solid #74e504;
        margin: 1rem 0;
        font-weight: 500;
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
        background: #74e504 !important;
        color: white !important;
        font-weight: 600 !important;
        padding: 1rem !important;
        border: none !important;
    }
    
    .competitor-table td {
        padding: 0.8rem 1rem !important;
        border-bottom: 1px solid #d4f4aa !important;
        border-left: none !important;
        border-right: none !important;
    }
    
    .competitor-table tr:hover {
        background-color: #d4f4aa !important;
    }
    
    /* Highlight main company row with light green theme */
    .competitor-table tr:has(td:contains("⭐")) {
        background-color: #c4f082 !important;
        font-weight: 600 !important;
    }
    
    .stDataFrame {
        border-radius: 1rem;
        overflow: hidden;
    }
        background: #74e504;
        padding: 2rem;
        border-radius: 1rem;
        color: white;
        text-align: center;
        box-shadow: 0 4px 15px rgba(116, 229, 4, 0.3);
        transition: transform 0.3s;
    }
    
    .metric-card:hover {
        transform: translateY(-5px);
    }
    
    .tool-card {
        background: white;
        padding: 1.5rem;
        border-radius: 0.75rem;
        border-left: 4px solid #74e504;
        margin-bottom: 1rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }
    
    .stButton>button {
        background: #74e504;
        color: white;
        border: none;
        padding: 0.75rem 2rem;
        font-weight: 600;
        border-radius: 0.5rem;
        transition: all 0.3s;
        box-shadow: 0 4px 15px rgba(116, 229, 4, 0.3);
        min-height: 3rem;
    }
    
    .stButton>button:hover {
        background: #65d004;
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(116, 229, 4, 0.4);
    }
    
    /* Make download button same size as regular button */
    .stDownloadButton>button {
        background: #74e504;
        color: white;
        border: none;
        padding: 0.75rem 2rem;
        font-weight: 600;
        border-radius: 0.5rem;
        transition: all 0.3s;
        box-shadow: 0 4px 15px rgba(116, 229, 4, 0.3);
        min-height: 3rem;
    }
    
    .stDownloadButton>button:hover {
        background: #65d004;
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(116, 229, 4, 0.4);
    }
    
    /* Hide AUTO_ADVANCE_HIDDEN button globally */
    button[kind="primary"]:has-text("AUTO_ADVANCE_HIDDEN"),
    button:has-text("AUTO_ADVANCE_HIDDEN"),
    form:has(button:has-text("AUTO_ADVANCE_HIDDEN")),
    div:has(> form > button:has-text("AUTO_ADVANCE_HIDDEN")) {
        display: none !important;
        visibility: hidden !important;
        height: 0 !important;
        width: 0 !important;
        padding: 0 !important;
        margin: 0 !important;
        opacity: 0 !important;
        position: absolute !important;
        left: -9999px !important;
        top: -9999px !important;
    }
</style>
""", unsafe_allow_html=True)


if 'deps' not in st.session_state:
    st.session_state.deps = ConversationState()

if 'message_history' not in st.session_state:
    st.session_state.message_history = []  # pydantic-ai manages system prompt internally; history = prior turns only

if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'current_stock' not in st.session_state:
    st.session_state.current_stock = None
if 'company_data' not in st.session_state:
    st.session_state.company_data = None
if 'show_ppt_viewer' not in st.session_state:
    st.session_state.show_ppt_viewer = False
# Bilingual PPT support - store paths for both languages
if 'ppt_path_en' not in st.session_state:
    st.session_state.ppt_path_en = None
if 'ppt_path_hi' not in st.session_state:
    st.session_state.ppt_path_hi = None
if 'pdf_path_en' not in st.session_state:
    st.session_state.pdf_path_en = None
if 'pdf_path_hi' not in st.session_state:
    st.session_state.pdf_path_hi = None
if 'ppt_language' not in st.session_state:
    st.session_state.ppt_language = "english"  # Default to English
# Backward compatibility - keep old keys pointing to English versions
if 'ppt_path' not in st.session_state:
    st.session_state.ppt_path = None
if 'pdf_path' not in st.session_state:
    st.session_state.pdf_path = None



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
        
        # PPT Generator - Right below current analysis
        # Check if sentiment analysis has been completed before allowing PPT generation
        if st.button("📄 Generate Presentation", use_container_width=True, type="primary", key="generate_ppt_current"):
            # Get the stock symbol from deps (more reliable than current_stock name)
            stock_symbol = st.session_state.deps.stock_symbol if hasattr(st.session_state.deps, 'stock_symbol') and st.session_state.deps.stock_symbol else None
            
            if stock_symbol:
                # Check if sentiment analysis has been completed
                try:
                    from database_utility.database import StockDatabase
                    
                    db = StockDatabase()
                    sentiment_missing = False
                    
                    if db.connect():
                        # Get the latest analysis for this stock
                        latest = db.get_latest_analysis(stock_symbol)
                        
                        if latest:
                            # Check if sentiment data exists
                            market_senti = latest.get('market_senti')
                            future_senti = latest.get('future_senti')
                            
                            if not market_senti or not future_senti or market_senti.strip() == '' or future_senti.strip() == '':
                                sentiment_missing = True
                        else:
                            sentiment_missing = True
                        
                        db.disconnect()
                    else:
                        sentiment_missing = True
                    
                    # If sentiment analysis is missing, show warning
                    if sentiment_missing:
                        st.warning("⚠️ Sentiment Analysis Required")
                        st.error("""
                        📊 **Sentiment analysis data is missing!**
                        
                        To generate a complete presentation, you need to:
                        1. Click on **"📈 Current Market Sentiment"** section above
                        2. Wait for the sentiment analysis to complete
                        3. Return here and click **"Generate Presentation"** again
                        
                        This ensures your presentation includes:
                        - Current market sentiment from News, Yahoo Finance, Twitter, and Reddit
                        - Future outlook and growth drivers
                        - Complete market analysis
                        """)
                        st.info("💡 Tip: Sentiment analysis takes 30-60 seconds to complete. Please be patient!")
                    else:
                        # Sentiment data exists, proceed with BILINGUAL PPT generation
                        with st.spinner(f"🚀 Generating bilingual PPT (English + Hindi) for {st.session_state.current_stock}..."):
                            try:
                                from utils.ppt_generator import StockPPTGenerator
                                
                                generator = StockPPTGenerator()
                                result = generator.generate_ppt(stock_symbol)
                                
                                if result:
                                    st.success(f"✅ Bilingual PPT generated successfully!")
                                    
                                    # Store paths in session state (new bilingual structure)
                                    st.session_state.ppt_path_en = result['ppt_path_en']
                                    st.session_state.ppt_path_hi = result['ppt_path_hi']
                                    st.session_state.pdf_path_en = result.get('pdf_path_en')
                                    st.session_state.pdf_path_hi = result.get('pdf_path_hi')
                                    
                                    # Backward compatibility - point to English version
                                    st.session_state.ppt_path = result['ppt_path_en']
                                    st.session_state.pdf_path = result.get('pdf_path_en')
                                    
                                    if not result.get('pdf_path_en') and not result.get('pdf_path_hi'):
                                        st.warning("⚠️ PDF conversion not available on this system")
                                else:
                                    st.error("❌ Failed to generate PPT. Please analyze the stock first to save data to database.")
                                    
                            except Exception as e:
                                st.error(f"❌ Error: {str(e)}")
                                import traceback
                                traceback.print_exc()
                                
                except Exception as e:
                    st.error(f"❌ Error checking sentiment data: {str(e)}")
                    import traceback
                    traceback.print_exc()
            else:
                st.warning("⚠️ Stock symbol not found. Please analyze a stock first.")
        
        # Show language selector and download buttons if PPT was generated
        if hasattr(st.session_state, 'ppt_path_en') and st.session_state.ppt_path_en:
            # Language selector
            st.markdown("---")
            st.subheader("🌐 Language")
            
            selected_language = st.radio(
                "Select presentation language:",
                options=["English", "हिंदी (Hindi)"],
                index=0 if st.session_state.ppt_language == "english" else 1,
                key="language_selector",
                horizontal=True
            )
            
            # Update language in session state
            if selected_language == "English":
                st.session_state.ppt_language = "english"
                current_ppt_path = st.session_state.ppt_path_en
                current_pdf_path = st.session_state.pdf_path_en
            else:
                st.session_state.ppt_language = "hindi"
                current_ppt_path = st.session_state.ppt_path_hi
                current_pdf_path = st.session_state.pdf_path_hi
            
            # Update backward compatibility pointers
            st.session_state.ppt_path = current_ppt_path
            st.session_state.pdf_path = current_pdf_path
            
            col1, col2 = st.columns(2)
            
            # Download PPT button
            with col1:
                try:
                    with open(current_ppt_path, "rb") as file:
                        st.download_button(
                            label=f"⬇️ Download PPT ({selected_language})",
                            data=file,
                            file_name=os.path.basename(current_ppt_path),
                            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                            use_container_width=True,
                            key="download_ppt_current"
                        )
                except Exception as e:
                    st.error(f"Error: {e}")
            
            # Open PPT button (shows PDF viewer)
            with col2:
                # Check if viewer is currently active
                current_view = st.session_state.get("view_selector", "💬 Chat")
                is_viewer_active = current_view == "📖 Presentation Viewer"
                
                if is_viewer_active:
                    button_label = "✅ Viewing"
                    button_type = "secondary"
                else:
                    button_label = "📖 Open PPT"
                    button_type = "primary"
                
                if st.button(button_label, use_container_width=True, type=button_type, key="open_ppt_viewer"):
                    print(f"🔘 Open PPT button clicked - switching to Presentation Viewer")
                    
                    # Generate narration scripts if not already generated
                    ppt_filename = os.path.basename(st.session_state.ppt_path)
                    print(f"🔍 PPT filename: {ppt_filename}")
                    
                    # Extract stock symbol and timestamp from PPT filename
                    # PPT Format: Company_Name_SYMBOL_TIMESTAMP.pptx
                    # JSON Format: SYMBOL_TIMESTAMP.json
                    # Example: Cupid_Limited_CUPID_NS_20260218_183407.pptx → CUPID_NS_20260218_183407.json
                    
                    ppt_name_without_ext = ppt_filename.replace('.pptx', '')
                    parts = ppt_name_without_ext.split('_')
                    
                    # Strategy: The last 3 parts are always: SYMBOL_PART, DATE, TIME
                    # But SYMBOL might have underscore (e.g., CUPID_NS)
                    # So we need to find where the symbol starts
                    
                    json_found = False
                    json_path = None
                    
                    if len(parts) >= 3:
                        # Strategy 1: Try last 4 parts (for symbols with underscore like CUPID_NS)
                        # Example: ['Cupid', 'Limited', 'CUPID', 'NS', '20260218', '183407']
                        # Try: CUPID_NS_20260218_183407
                        if len(parts) >= 4:
                            potential_json_name = '_'.join(parts[-4:]) + '.json'
                            potential_json_path = os.path.join('PPT_json', potential_json_name)
                            print(f"🔍 Strategy 1 - Checking: {potential_json_path}")
                            
                            if os.path.exists(potential_json_path):
                                json_path = potential_json_path
                                json_found = True
                                print(f"✅ Found JSON: {json_path}")
                        
                        # Strategy 2: Try last 3 parts (for simple symbols)
                        if not json_found and len(parts) >= 3:
                            potential_json_name = '_'.join(parts[-3:]) + '.json'
                            potential_json_path = os.path.join('PPT_json', potential_json_name)
                            print(f"🔍 Strategy 2 - Checking: {potential_json_path}")
                            
                            if os.path.exists(potential_json_path):
                                json_path = potential_json_path
                                json_found = True
                                print(f"✅ Found JSON: {json_path}")
                        
                        # Strategy 3: Search by timestamp (most reliable)
                        if not json_found:
                            print(f"🔍 Strategy 3 - Searching by timestamp...")
                            
                            try:
                                import glob
                                json_files = glob.glob('PPT_json/*.json')
                                
                                # Filter out _script.json files
                                json_files = [f for f in json_files if '_script.json' not in f]
                                
                                # Extract timestamp from PPT filename (last 2 parts: DATE_TIME)
                                timestamp_str = '_'.join(parts[-2:])
                                print(f"🔍 Looking for timestamp: {timestamp_str}")
                                
                                for json_file in json_files:
                                    if timestamp_str in json_file:
                                        json_path = json_file
                                        json_found = True
                                        print(f"✅ Found JSON by timestamp: {json_path}")
                                        break
                                
                                # Strategy 4: Use most recent JSON as last resort
                                if not json_found and json_files:
                                    json_path = max(json_files, key=os.path.getmtime)
                                    json_found = True
                                    print(f"⚠️ Using most recent JSON as fallback: {json_path}")
                                    
                            except Exception as e:
                                print(f"❌ Error searching for JSON: {e}")
                    else:
                        print(f"⚠️ Could not parse PPT filename: {ppt_filename}")
                        json_path = None
                        json_found = False
                    
                    if json_found and json_path:
                        # Script JSON will be saved in generated_ai_scripts folder
                        json_basename = os.path.basename(json_path)
                        script_json_filename = json_basename.replace('.json', '_script.json')
                        script_json_path = os.path.join('generated_ai_scripts', script_json_filename)
                        
                        # Check if script JSON already exists
                        if not os.path.exists(script_json_path):
                            print(f"🎤 Generating narration scripts for {json_basename}...")
                            
                            with st.spinner("🎤 Generating professional narration scripts..."):
                                try:
                                    from utils.narration_script_generator import NarrationScriptGenerator
                                    
                                    generator = NarrationScriptGenerator()
                                    output_path = generator.generate_scripts_for_ppt(json_path)
                                    
                                    if output_path:
                                        st.session_state.script_json_path = output_path
                                        print(f"✅ Narration scripts generated: {output_path}")
                                    else:
                                        print(f"⚠️ Failed to generate narration scripts")
                                        st.session_state.script_json_path = None
                                        
                                except Exception as e:
                                    print(f"❌ Error generating narration scripts: {e}")
                                    import traceback
                                    traceback.print_exc()
                                    st.session_state.script_json_path = None
                        else:
                            print(f"✅ Narration scripts already exist: {script_json_path}")
                            st.session_state.script_json_path = script_json_path
                    else:
                        print(f"❌ Could not find matching JSON file for PPT: {ppt_filename}")
                        st.warning("⚠️ Could not find PPT JSON file. Narration scripts will not be available.")
                        st.session_state.script_json_path = None
                    
                    # Switch to Presentation Viewer view
                    st.session_state.view_selector = "📖 Presentation Viewer"
                    st.rerun()
    else:
        st.info("No stock selected")
    
    st.markdown("---")
    
    # View Navigation (NEW - moved from top tabs)
    st.subheader("📑 View")
    
    # Build view options in the desired order
    # Order: Chat → Data Dashboard → Sentiment Analysis → Presentation Viewer → Drawing Generator → Bulk Stock Analyzer → Technical Scanner → System Info
    view_options = [
        "💬 Chat",
        "📊 Data Dashboard",
        "📈 Sentiment Analysis"
    ]
    
    # Add Presentation Viewer if PPT was generated
    if hasattr(st.session_state, 'ppt_path') and st.session_state.ppt_path:
        view_options.append("📖 Presentation Viewer")
    
    # Add Drawing Generator (always available)
    view_options.append("🎨 Drawing Generator")
    
    # Add Bulk Stock Analyzer
    view_options.append("🔍 Bulk Stock Analyzer")
    
    # Add Technical Scanner if MCP is enabled
    use_mcp = os.getenv("USE_MCP", "false").lower() == "true"
    if use_mcp:
        view_options.append("📊 Technical Scanner")
    
    # Add System Info at the end
    view_options.append("🔧 System Info")
    
    view_option = st.radio(
        "Select View",
        view_options,
        label_visibility="collapsed",
        key="view_selector"
    )
    
    st.markdown("---")
    
    # MCP Technical Analysis Scanner (NEW)
    st.subheader("📈 Technical Scanner")
    
    # Check if MCP is enabled
    use_mcp = os.getenv("USE_MCP", "false").lower() == "true"
    
    if use_mcp:
        st.caption("🔧 TradingView MCP Tools Active")
        
        if st.button("🔍 Scan Bollinger Squeeze", use_container_width=True, type="primary", key="scan_bollinger"):
            st.session_state.show_mcp_scanner = True
            st.session_state.view_selector = "📊 Technical Scanner"
            st.rerun()
    else:
        st.caption("⚠️ MCP Disabled")
        st.caption("Set USE_MCP=true in .env to enable technical analysis tools")
    
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
    if len(st.session_state.messages) > 0 or hasattr(st.session_state, 'ppt_path'):
        with st.expander("🔧 Debug Info"):
            try:
                summary = {
                    'ui_messages': len(st.session_state.messages),
                    'agent_memory': len(st.session_state.message_history) if hasattr(st.session_state, 'message_history') else 0,
                    'has_company_data': bool(st.session_state.deps.company_data),
                    'current_stock': st.session_state.deps.stock_symbol,
                    'stock_name': st.session_state.deps.stock_name,
                    'ppt_viewer_open': st.session_state.show_ppt_viewer if hasattr(st.session_state, 'show_ppt_viewer') else False,
                    'has_ppt': bool(st.session_state.ppt_path) if hasattr(st.session_state, 'ppt_path') else False,
                    'has_pdf': bool(st.session_state.pdf_path) if hasattr(st.session_state, 'pdf_path') else False
                }
                st.json(summary)
            except:
                st.caption("Debug info not available")
    
    st.markdown("---")
    
    # Quick Actions
    st.subheader("⚡ Quick Actions")
    if st.button("🔄 New Analysis", use_container_width=True):
        st.session_state.deps = ConversationState()
        st.session_state.message_history = []  # reset; system prompt managed by agent internally
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
st.markdown('<h1 class="main-header">Stock Analysis</h1>', unsafe_allow_html=True)

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
    
    # Show welcome message if no messages yet with light green styling
    if len(st.session_state.messages) == 0:
        st.markdown("""
        <div style="
            background-color: #d4f4aa;
            color: #2E590E;
            padding: 1rem 1.5rem;
            border-radius: 0.75rem;
            border-left: 4px solid #74e504;
            margin: 1rem 0;
            font-weight: 500;
        ">
            👋 Hello! I'm your AI stock analyst. Tell me which stock to analyze!
        </div>
        """, unsafe_allow_html=True)
    
    # Chat messages - using inline HTML for complete control
    for idx, message in enumerate(st.session_state.messages):
        if message["role"] == "user":
            # User message - right aligned with green background
            import html
            # Escape HTML to prevent code from being rendered
            safe_content = html.escape(message["content"])
            
            # Use single-line HTML to avoid whitespace issues
            st.markdown(
                f'<div style="display: flex; justify-content: flex-end; align-items: flex-start; margin: 1rem 0; gap: 0.75rem;">'
                f'<div style="background: #74e504; color: white; padding: 1rem 1.5rem; border-radius: 1.5rem 1.5rem 0.3rem 1.5rem; box-shadow: 0 4px 12px rgba(116, 229, 4, 0.3); max-width: 70%; word-wrap: break-word;">'
                f'{safe_content}'
                f'</div>'
                f'<div style="width: 40px; height: 40px; border-radius: 50%; background: #74e504; display: flex; align-items: center; justify-content: center; font-size: 1.3rem; flex-shrink: 0;">'
                f'👤'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True
            )
        else:
            # Assistant message - left aligned with white background
            # Use proper CSS classes for better overflow handling
            import re
            content = message["content"]
            
            # DEBUG: Log content length
            print(f"🔍 Rendering assistant message: {len(content)} characters, {content.count(chr(10))} lines")
            
            # Convert markdown bold to HTML
            content = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', content)
            
            # Convert markdown italic to HTML
            content = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', content)
            
            # Process line by line with proper word-wrap styling
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
                    html_lines.append(f'<h3 style="margin: 0.8rem 0 0.4rem 0; font-size: 1.1rem; font-weight: 600; line-height: 1.3; word-wrap: break-word; overflow-wrap: break-word; hyphens: auto;">{stripped}</h3>')
                
                # Subsection headers (bold text without emoji, like "Income Statement:")
                elif '<strong>' in stripped and stripped.endswith('</strong>:'):
                    if in_list:
                        html_lines.append('</ul>')
                        in_list = False
                    html_lines.append(f'<p style="margin: 0.5rem 0 0.2rem 0; font-weight: 600; line-height: 1.35; word-wrap: break-word; overflow-wrap: break-word; hyphens: auto;">{stripped}</p>')
                
                # Bullet points
                elif stripped.startswith('• ') or stripped.startswith('- '):
                    if not in_list:
                        html_lines.append('<ul style="margin: 0.2rem 0; padding-left: 1.5rem; list-style-type: disc; word-wrap: break-word; overflow-wrap: break-word;">')
                        in_list = True
                    item_text = stripped[2:]
                    html_lines.append(f'<li style="margin: 0.1rem 0; line-height: 1.35; word-wrap: break-word; overflow-wrap: break-word; hyphens: auto;">{item_text}</li>')
                
                # Regular paragraph
                else:
                    if in_list:
                        html_lines.append('</ul>')
                        in_list = False
                    html_lines.append(f'<p style="margin: 0.2rem 0; line-height: 1.35; word-wrap: break-word; overflow-wrap: break-word; hyphens: auto;">{stripped}</p>')
            
            # Close list if still open
            if in_list:
                html_lines.append('</ul>')
            
            # Join without newlines to avoid Streamlit parsing issues
            html_content = ''.join(html_lines)
            
            # Use CSS classes for proper rendering
            st.markdown(f"""
            <div class="assistant-message-container">
                <div class="assistant-avatar-fixed">🤖</div>
                <div class="assistant-content-box">
                    {html_content}
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # Add download PDF button if this is a stock analysis report
            if len(message["content"]) > 500 and st.session_state.current_stock:
                from utils.pdf_generator import generate_pdf_report
                
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
            st.session_state.message_history = []  # system prompt managed by agent internally
        if 'deps' not in st.session_state:
            st.session_state.deps = ConversationState()
        
        st.session_state.messages.append({"role": "user", "content": user_input})
        
        with st.spinner("🤔 Analyzing..."):
            @traceable(name="pydantic_ai_agent_run")
            async def run_agent_async(user_input, message_history, deps):
                """Async wrapper for agent.run - Fundamental analysis only (no MCP)"""
                try:
                    # Run agent for fundamental stock analysis
                    # Note: MCP tools are only available in Technical Scanner (uses mcp_agent)
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
                max_retries = 1  # Reduced to 1 - if tool generates response, accept it
                
                for attempt in range(max_retries):
                    try:
                        print(f"🔄 Attempt {attempt + 1}/{max_retries}")
                        print(f"🚀 Starting agent.run() for input: {user_input[:50]}...")
                        
                        # Capture session state values
                        message_history = st.session_state.message_history.copy() if hasattr(st.session_state, 'message_history') else []
                        deps = st.session_state.deps if hasattr(st.session_state, 'deps') else ConversationState()
                        
                        # Reset per-turn guards and store current user input
                        deps.current_user_input = user_input.strip()
                        deps.validation_done_this_turn = False  # Allow validate_and_get_stock once per turn
                        
                        # Trim message history to last MAX_HISTORY turns to prevent the LLM
                        # from re-calling tools it already called in previous turns.
                        # We work on a local trimmed copy — session state keeps the full list
                        # so new_messages() can always be appended correctly.
                        MAX_HISTORY = 10  # keep last 10 messages (5 user+assistant pairs)
                        if len(message_history) > MAX_HISTORY:
                            message_history = message_history[-MAX_HISTORY:]
                            print(f"✂️ Trimmed message history to {len(message_history)} messages for this call")
                        
                        # Run the async function directly
                        import asyncio
                        import concurrent.futures
                        import time as time_module
                        
                        start_time = time_module.time()
                        
                        try:
                            # Use ThreadPoolExecutor to run async code with timeout
                            # Reduced timeout to 180 seconds (3 minutes) for faster failure detection
                            with concurrent.futures.ThreadPoolExecutor() as executor:
                                future = executor.submit(
                                    lambda: asyncio.run(run_agent_async(user_input, message_history, deps))
                                )
                                result, error = future.result(timeout=180)  # 3 minute timeout (reduced from 5)
                                
                            elapsed_time = time_module.time() - start_time
                            print(f"✅ Agent.run() completed in {elapsed_time:.2f} seconds")
                            
                        except concurrent.futures.TimeoutError:
                            elapsed_time = time_module.time() - start_time
                            print(f"⏱️ Agent execution exceeded {elapsed_time:.2f} seconds (timeout: 180s / 3 minutes)")
                            
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
                        
                        # Accept the result — actual response is resolved from deps cache later
                        st.session_state.deps = deps

                        # Update message history with new messages from this turn
                        if hasattr(result, 'new_messages'):
                            new_messages = result.new_messages()
                            if new_messages:
                                print(f"📝 Processing {len(new_messages)} new messages from agent")
                                st.session_state.message_history.extend(list(new_messages))
                                print(f"✅ Updated message history: {len(st.session_state.message_history)} total messages")
                            else:
                                # Recovery path — manually record the exchange
                                cached = getattr(deps, 'last_analysis_response', None) or getattr(deps, 'last_validation_response', None) or ""
                                st.session_state.message_history.extend([
                                    ModelRequest(parts=[UserPromptPart(content=user_input)]),
                                    ModelResponse(parts=[TextPart(content=cached)]),
                                ])
                                print(f"📝 Manually appended exchange to history ({len(st.session_state.message_history)} total)")

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
                elif "exceeded maximum retries" in error_msg.lower() or "output validation" in error_msg.lower():
                    # Try to get existing analysis from database
                    print(f"🔄 Validation failed, attempting to retrieve from database...")
                    
                    try:
                        from database_utility.database import StockDatabase
                        
                        db = StockDatabase()
                        if db.connect():
                            # Get the most recent analysis
                            latest = db.get_latest_analysis()
                            
                            if latest and latest.get('formatted_report'):
                                print(f"✅ Retrieved analysis from database: {len(latest['formatted_report'])} chars")
                                response = latest['formatted_report']
                                
                                # Update session state with retrieved data
                                if latest.get('stock_symbol'):
                                    st.session_state.current_stock = latest.get('stock_name', latest.get('stock_symbol'))
                                    
                                    # Create minimal company data for session state
                                    if not st.session_state.deps.company_data:
                                        from models import CompanyData
                                        st.session_state.deps.company_data = CompanyData(
                                            symbol=latest.get('stock_symbol'),
                                            name=latest.get('stock_name', latest.get('stock_symbol')),
                                            current_price=0,  # Will be updated if needed
                                            market_cap=0,
                                            pe_ratio=0,
                                            dividend_yield=0,
                                            revenue=0,
                                            net_income=0,
                                            total_assets=0,
                                            total_debt=0,
                                            free_cash_flow=0,
                                            roe=0,
                                            debt_to_equity=0,
                                            current_ratio=0,
                                            gross_margin=0,
                                            operating_margin=0,
                                            net_margin=0,
                                            revenue_growth=0,
                                            earnings_growth=0,
                                            book_value=0,
                                            price_to_book=0,
                                            enterprise_value=0,
                                            ebitda=0,
                                            ev_to_ebitda=0,
                                            price_to_sales=0,
                                            peg_ratio=0,
                                            beta=0,
                                            fifty_two_week_high=0,
                                            fifty_two_week_low=0,
                                            avg_volume=0,
                                            shares_outstanding=0,
                                            float_shares=0,
                                            insider_ownership=0,
                                            institutional_ownership=0,
                                            short_ratio=0,
                                            analyst_rating="",
                                            target_price=0,
                                            recommendation=""
                                        )
                                        st.session_state.deps.stock_symbol = latest.get('stock_symbol')
                                        st.session_state.deps.stock_name = latest.get('stock_name', latest.get('stock_symbol'))
                                        st.session_state.deps.analysis_complete = True
                                
                            else:
                                print(f"❌ No formatted report found in database")
                                response = """❌ **Analysis Generation Failed**

The system encountered validation issues while generating your analysis.

**What happened:**
• The analysis was processed but couldn't be properly formatted
• This is usually due to API response validation errors

**What you can do:**
• Try your request again with a simpler query
• Ask for specific information about the stock
• Try again in a few minutes

*The system saves partial results, so retrying should be faster.*"""
                            
                            db.disconnect()
                        else:
                            print(f"❌ Could not connect to database")
                            response = """❌ **System Error**

Could not retrieve analysis results.

**What you can do:**
• Try your request again
• Check your internet connection
• Contact support if the issue persists

*The system will automatically retry failed requests.*"""
                            
                    except Exception as db_error:
                        print(f"❌ Database retrieval error: {db_error}")
                        response = """❌ **Analysis Retrieval Failed**

The system generated an analysis but couldn't display it properly.

**What you can do:**
• Try your request again
• The analysis may have been saved and will load faster on retry
• Try asking for specific information about the stock

*This is usually a temporary issue.*"""
                else:
                    response = f"❌ **System Error**\n\n{error_msg}\n\n*Please try your request again.*"
            
            else:
                # Success - resolve the final response.
                # Priority: last_analysis_response > last_validation_response > result.output
                # This ensures we always show the actual tool output, never the LLM's own text.
                _analysis_cache = getattr(st.session_state.deps, 'last_analysis_response', None)
                _validation_cache = getattr(st.session_state.deps, 'last_validation_response', None)

                if _analysis_cache:
                    response = _analysis_cache
                    print(f"📊 Using cached analysis response ({len(response)} chars)")
                elif _validation_cache:
                    response = _validation_cache
                    print(f"📊 Using cached validation response ({len(response)} chars)")
                else:
                    # No cache — fall back to whatever the agent returned
                    if hasattr(result, 'output'):
                        response = result.output
                    elif hasattr(result, 'data'):
                        response = result.data
                    else:
                        response = str(result)
                    print(f"📊 Fallback to result.output: {type(response)}")

                print(f"📄 Raw response preview: {str(response)[:200]}...")

                # Unwrap ToolResponse if present (from FixedResult/CachedResult recovery paths)
                if isinstance(response, ToolResponse):
                    response = response.content

                # Strip FINAL_ANSWER: prefix — tool-level signal, not user-facing
                if isinstance(response, str) and response.startswith("FINAL_ANSWER:\n"):
                    response = response[len("FINAL_ANSWER:\n"):]
                    print(f"✂️ Stripped FINAL_ANSWER prefix, response now {len(response)} chars")

                # Ensure string
                if not isinstance(response, str):
                    response = str(response)

                print(f"✅ Final response: {len(response)} characters")

                # Mark report as generated if we have a substantial response
                if st.session_state.deps.company_data and not st.session_state.deps.report_generated:
                     if len(response) >= 200:
                         # Mark as generated only if we have a substantial response
                         st.session_state.deps.report_generated = True
                     elif len(response) < 200 and not any(err in response for err in ["Invalid selection", "Please choose", "Error", "❌"]):
                         # Short response but not an error - might be a valid short message
                         print(f"⚠️ Short response ({len(response)} chars), but not using fallback")

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

elif view_option == "📊 Technical Scanner":
    # Technical Scanner - MCP-driven analysis with TradingView format support
    st.markdown("### 📊 Technical Scanner")
    
    # Check if MCP is enabled
    use_mcp = os.getenv("USE_MCP", "false").lower() == "true"
    
    if not use_mcp:
        st.error("❌ MCP is not enabled")
        st.info("To use technical analysis tools, set USE_MCP=true in your .env file and restart the app")
        
        if st.button("🔙 Back to Chat", use_container_width=True):
            st.session_state.view_selector = "💬 Chat"
            st.rerun()
    else:
        # Create tabs for different scanner modes
        scanner_tab1, scanner_tab2 = st.tabs(["📊 Pattern Scanner", "🎯 TradingView JSON Scanner"])
        
        with scanner_tab1:
            # Original Bollinger Band visualization scanner
            st.markdown("#### Bollinger Band Analysis")
            st.success("✅ TradingView MCP Tools Active")
        
        # Scanner controls
        col1, col2, col3 = st.columns([2, 1, 1])
        
        with col1:
            scan_query = st.text_input(
                "Scanner Query",
                value="Find Indian stocks showing a Bollinger Band squeeze",
                help="Ask the AI to scan for technical patterns"
            )
        
        with col2:
            timeframe = st.selectbox(
                "Timeframe",
                options=['1d', '1h', '15m', '5m', '1wk'],
                index=0,
                help="Chart timeframe"
            )
        
        with col3:
            max_stocks = st.number_input(
                "Max Stocks",
                min_value=1,
                max_value=10,
                value=3,
                help="Maximum stocks to visualize"
            )
        
        # Mode selection
        col_scan, col_demo = st.columns(2)
        
        with col_scan:
            scan_button = st.button("🔍 Scan with MCP", width="stretch", type="primary")
        
        with col_demo:
            demo_button = st.button("🎯 Demo Mode", width="stretch", help="Visualize sample stocks without MCP")
        
        # Scan button
        if scan_button:
            with st.spinner("🤖 AI is scanning the market with TradingView MCP tools..."):
                try:
                    # Import visualization pipeline
                    from utils.mcp_visualization_pipeline import get_visualization_pipeline
                    
                    # Check if user is asking for a specific stock vs market scan
                    query_lower = scan_query.lower()
                    
                    # Detect tool type from query (comprehensive support)
                    is_candlestick_query = 'candle' in query_lower or 'pattern' in query_lower
                    is_bollinger_query = 'bollinger' in query_lower or 'squeeze' in query_lower
                    is_rating_query = 'rating' in query_lower
                    is_rsi_query = 'rsi' in query_lower or 'relative strength' in query_lower or 'oversold' in query_lower or 'overbought' in query_lower
                    is_macd_query = 'macd' in query_lower or 'moving average convergence' in query_lower
                    is_ma_query = ('moving average' in query_lower or 'sma' in query_lower or 'ema' in query_lower or 'golden cross' in query_lower or 'death cross' in query_lower) and not is_macd_query
                    is_volume_query = 'volume' in query_lower and ('high' in query_lower or 'breakout' in query_lower or 'analysis' in query_lower)
                    is_multi_query = 'complete' in query_lower or 'full' in query_lower or 'all indicator' in query_lower or 'comprehensive' in query_lower
                    
                    # Detect if specific stock is mentioned
                    specific_stock_keywords = ['for ', ' for', 'to ', ' to', 'of ', ' of', 'on the ', 'on ']
                    is_specific_stock = any(keyword in query_lower for keyword in specific_stock_keywords)
                    
                    # Common stock names/symbols
                    stock_names = ['tcs', 'reliance', 'infosys', 'infy', 'hdfc', 'icici', 'sbi', 'jio', 'jiofin', 'tata', 'wipro', 'bharti', 'airtel']
                    mentions_stock = any(stock in query_lower for stock in stock_names)
                    
                    # Extract stock symbol if mentioned
                    specific_stock_symbol = None
                    if is_specific_stock and mentions_stock:
                        for stock_name in stock_names:
                            if stock_name in query_lower:
                                # Map common names to symbols
                                symbol_map = {
                                    'tcs': 'TCS.NS',
                                    'reliance': 'RELIANCE.NS',
                                    'infosys': 'INFY.NS',
                                    'infy': 'INFY.NS',
                                    'hdfc': 'HDFCBANK.NS',
                                    'icici': 'ICICIBANK.NS',
                                    'sbi': 'SBIN.NS',
                                    'jio': 'JIOFIN.NS',
                                    'jiofin': 'JIOFIN.NS',
                                    'tata': 'TATAMOTORS.NS',
                                    'wipro': 'WIPRO.NS',
                                    'bharti': 'BHARTIARTL.NS',
                                    'airtel': 'BHARTIARTL.NS'
                                }
                                specific_stock_symbol = symbol_map.get(stock_name)
                                break
                    
                    # Handle specific stock queries
                    if is_specific_stock and mentions_stock:
                        # For candlestick/pattern queries on specific stock, allow it
                        if is_candlestick_query:
                            st.info(f"📊 Analyzing candlestick patterns for {specific_stock_symbol or 'the specified stock'}")
                            
                            # Use pipeline to analyze the specific stock
                            if specific_stock_symbol:
                                # Create visualization for the specific stock
                                pipeline = get_visualization_pipeline()
                                
                                viz_results = {
                                    'stocks': [],
                                    'summary': f"Candlestick Pattern Analysis for {specific_stock_symbol}",
                                    'total_found': 1,
                                    'processed': 0,
                                    'tool_type': 'candlestick'
                                }
                                
                                try:
                                    # Use pipeline's visualize_single_stock with candlestick tool type
                                    chart, error_msg, analysis = pipeline.visualize_single_stock(
                                        specific_stock_symbol,
                                        timeframe=timeframe,
                                        tool_type='candlestick'
                                    )
                                    
                                    if not error_msg and chart:
                                        stock_result = {
                                            'symbol': specific_stock_symbol,
                                            'original_symbol': specific_stock_symbol,
                                            'display_name': specific_stock_symbol,
                                            'data': analysis.get('data'),
                                            'chart': chart,
                                            'pattern': analysis.get('pattern', 'Multiple Patterns Detected'),
                                            'explanation': analysis.get('explanation', f'Candlestick pattern analysis for {specific_stock_symbol}'),
                                            'timeframe': timeframe,
                                            'signal_strength': 'medium',
                                            'mcp_description': f'Pattern analysis for {specific_stock_symbol}',
                                            'is_current': False,
                                            'tool_type': 'candlestick'
                                        }
                                        viz_results['stocks'].append(stock_result)
                                        viz_results['processed'] = 1
                                        viz_results['summary'] = f"""📊 Candlestick Pattern Analysis:
   • Stock: {specific_stock_symbol}
   • Timeframe: {timeframe}
   • Analysis: Candlestick patterns detected
   • Note: Direct analysis (MCP not used for single stock)"""
                                        
                                        st.session_state.mcp_viz_results = viz_results
                                        st.session_state.mcp_demo_mode = True
                                        st.rerun()
                                    else:
                                        st.error(f"❌ Could not fetch data for {specific_stock_symbol}")
                                        st.info("💡 Try using the stock symbol with .NS suffix (e.g., TCS.NS)")
                                        st.stop()
                                        
                                except Exception as e:
                                    st.error(f"❌ Error analyzing {specific_stock_symbol}: {str(e)}")
                                    st.stop()
                            else:
                                st.error("❌ Could not identify the stock symbol")
                                st.info("💡 Try using the full symbol (e.g., TCS.NS)")
                                st.stop()
                        
                        else:
                            # For non-candlestick queries on specific stock, redirect to Chat
                            st.warning("⚠️ Technical Scanner is for market-wide scanning")
                            st.info("""
                            💡 **You're asking for analysis of a specific stock, but Technical Scanner is designed for market-wide scans.**
                            
                            **For analyzing a specific stock:**
                            1. Go to **Chat** view (sidebar)
                            2. Ask: "Analyze TCS" or "Analyze TCS.NS"
                            3. Get complete technical + fundamental analysis
                            
                            **For market-wide scanning:**
                            Use Technical Scanner with queries like:
                            - "Find Indian stocks with Bollinger squeeze on NSE"
                            - "Show stocks with bullish candlestick patterns on NSE"
                            - "Scan NSE for breakout stocks"
                            
                            **For candlestick patterns on specific stock:**
                            - "Show candlestick patterns on TCS stock"
                            - "What patterns are on Reliance stock"
                            
                            **Or try Demo Mode** to see how market scanning works.
                            """)
                            
                            # Offer demo mode
                            if st.button("🎯 Try Demo Mode", width="stretch", key="demo_specific_stock"):
                                st.session_state.force_demo_mode = True
                                st.rerun()
                            
                            # Stop here - don't call MCP
                            st.stop()
                    
                    # Enhance query to ensure stocks-only (not crypto)
                    # Add Technical Scanner context to prevent stock validation tools
                    enhanced_query = f"[TECHNICAL SCANNER MODE - Use TradingView MCP tools only, do NOT call validate_and_get_stock or analyze_stock_request] {scan_query}"
                    
                    # Add stock-specific constraints if not already present
                    query_lower = scan_query.lower()
                    
                    # If query doesn't specify exchange or market, add NSE constraint
                    if "nse" not in query_lower and "bse" not in query_lower and "exchange" not in query_lower:
                        if "indian" in query_lower or "india" in query_lower:
                            enhanced_query = f"{enhanced_query} on NSE exchange (stocks only, exclude crypto)"
                        else:
                            enhanced_query = f"{enhanced_query} on NSE exchange in Indian stock market (stocks only, exclude crypto)"
                    else:
                        # Exchange mentioned, just add crypto exclusion
                        enhanced_query = f"{enhanced_query} (stocks only, exclude crypto and cryptocurrency)"
                    
                    print(f"📊 Original query: {scan_query}")
                    print(f"📊 Enhanced query: {enhanced_query}")
                    
                    # Run agent with MCP query
                    import asyncio
                    
                    async def run_mcp_scan():
                        try:
                            # Use MCP agent instead of main agent
                            # Create MCP conversation state
                            mcp_state = create_mcp_state()
                            
                            # Run MCP agent with TradingView tools
                            result = await mcp_agent.run(
                                enhanced_query,  # Use enhanced query
                                deps=mcp_state
                            )
                            return result, None
                        except asyncio.TimeoutError:
                            return None, "timeout_error"
                        except Exception as e:
                            error_msg = str(e)
                            # Check if it's a TaskGroup error (asyncio)
                            if "TaskGroup" in error_msg or "sub-exception" in error_msg:
                                return None, "taskgroup_error"
                            # Check if it's an OpenAI API validation error
                            if "validation errors for ChatCompletion" in error_msg or "tool_calls" in error_msg:
                                return None, "openai_api_error"
                            # Check if it's an output validation error
                            if "output validation" in error_msg.lower() or "exceeded maximum retries" in error_msg.lower():
                                return None, "validation_error"
                            # Check if it's an MCP tool error
                            if "Tool" in error_msg and ("exceeded max retries" in error_msg or "MCP tool call failed" in error_msg):
                                return None, "mcp_tool_error"
                            return None, error_msg
                    
                    # Execute scan with proper event loop handling and timeout
                    try:
                        # Try to get existing event loop
                        loop = asyncio.get_event_loop()
                        if loop.is_closed():
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                    except RuntimeError:
                        # No event loop in current thread
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                    
                    # Run the scan with 60 second timeout
                    try:
                        result, error = loop.run_until_complete(
                            asyncio.wait_for(run_mcp_scan(), timeout=100.0)
                        )
                    except asyncio.TimeoutError:
                        result, error = None, "timeout_error"
                    
                    if error == "timeout_error":
                        # MCP call timed out
                        st.error("⏱️ MCP Request Timed Out")
                        st.info("""
                        💡 **The TradingView MCP tool took too long to respond (>60 seconds).**
                        
                        This usually happens when:
                        - The MCP server is slow or overloaded
                        - The query is too complex or broad
                        - Network connectivity issues
                        
                        **What you can do:**
                        
                        1. **Try a simpler query:**
                           - Instead of: "Show stocks with bullish candlestick patterns on NSE"
                           - Try: "Find Indian stocks with Bollinger squeeze on NSE"
                        
                        2. **Use Demo Mode:**
                           - Click the button below to see sample analysis
                           - Demo Mode works without MCP
                        
                        3. **Try again later:**
                           - MCP server might be temporarily slow
                        
                        **✅ Queries that usually work faster:**
                        - "Find Indian stocks with Bollinger squeeze on NSE"
                        - "Scan NSE for breakout stocks"
                        """)
                        
                        # Offer demo mode
                        if st.button("🎯 Try Demo Mode", width="stretch", key="demo_after_timeout"):
                            st.session_state.force_demo_mode = True
                            st.rerun()
                    
                    elif error == "taskgroup_error":
                        # TaskGroup error - MCP server issue
                        st.error("⚠️ MCP Server Error")
                        st.info("""
                        💡 **The TradingView MCP server encountered an internal error.**
                        
                        This usually happens when:
                        - The MCP tool doesn't support the requested analysis
                        - The MCP server is having connectivity issues
                        - The query format is not recognized by MCP
                        
                        **What you can do:**
                        
                        1. **Try a simpler query:**
                           - Instead of: "add supply demand indicators to JIO stock"
                           - Try: "Find Indian stocks with Bollinger squeeze on NSE"
                        
                        2. **Use Demo Mode:**
                           - Click the button below to see working examples
                        
                        3. **Note:** Supply/demand indicators may not be available in current MCP version
                        
                        **✅ Queries that work:**
                        - "Find Indian stocks with Bollinger squeeze on NSE"
                        - "Show stocks with bullish candlestick patterns on NSE"
                        - "Scan NSE for breakout stocks"
                        """)
                        
                        # Offer demo mode
                        if st.button("🎯 Try Demo Mode", width="stretch", key="demo_after_taskgroup_error"):
                            st.session_state.force_demo_mode = True
                            st.rerun()
                    
                    elif error == "openai_api_error":
                        # OpenAI API returned invalid tool call format
                        st.error("⚠️ AI model returned an invalid response")
                        st.info("""
                        💡 **This is a temporary AI model issue.** The model tried to call a tool but didn't provide valid arguments.
                        
                        **What you can do:**
                        
                        1. **Try a more specific query:**
                           - Instead of: "Find stocks"
                           - Try: "Find Indian stocks with Bollinger squeeze on NSE"
                        
                        2. **Use Demo Mode:**
                           - Click the button below to see sample technical analysis
                        
                        3. **Try again:**
                           - Sometimes the model works on retry
                        
                        **✅ Recommended queries:**
                        - "Find Indian stocks with Bollinger squeeze on NSE"
                        - "Show stocks with bullish candlestick patterns on NSE"
                        - "Scan NSE for breakout stocks"
                        """)
                        
                        # Offer demo mode
                        if st.button("🎯 Try Demo Mode", width="stretch", key="demo_after_api_error"):
                            st.session_state.force_demo_mode = True
                            st.rerun()
                    
                    elif error == "validation_error":
                        # Output validation failed - agent couldn't format response correctly
                        st.warning("⚠️ Query not supported by TradingView MCP tools")
                        st.info("""
                        💡 **TradingView MCP tools provide technical analysis only**, not buy/sell ratings.
                        
                        **✅ Supported queries (Technical Patterns):**
                        - "Find Indian stocks with Bollinger squeeze on NSE"
                        - "Show stocks with bullish candlestick patterns"
                        - "Scan for breakout stocks on NSE"
                        - "Find stocks with tight Bollinger Bands"
                        - "Detect hammer candlestick patterns"
                        
                        **❌ Not supported (Fundamental Analysis):**
                        - "Show stocks with strong buy rating" ← Your query
                        - "Find stocks with high P/E ratio"
                        - "Show analyst recommendations"
                        
                        **💡 For buy ratings and fundamental analysis:**
                        - Go to **Chat** view
                        - Ask: "Analyze [stock name]" for complete fundamental analysis
                        - Or use **Demo Mode** below to see technical pattern examples
                        """)
                        
                        # Offer demo mode
                        if st.button("🎯 Try Demo Mode Instead", width="stretch", key="demo_after_validation_error"):
                            st.session_state.force_demo_mode = True
                            st.rerun()
                    
                    elif error == "mcp_tool_error":
                        # MCP tool failed - use fallback with intelligent stock selection
                        st.warning("⚠️ TradingView MCP tool is currently unavailable")
                        
                        # Detect tool type from query
                        query_lower = scan_query.lower()
                        if 'candle' in query_lower or 'pattern' in query_lower:
                            demo_tool_type = 'candlestick'
                        elif 'rating' in query_lower:
                            demo_tool_type = 'rating'
                        else:
                            demo_tool_type = 'bollinger'
                        
                        # Priority 1: Use current analyzed stock if available
                        current_stock_symbol = None
                        if hasattr(st.session_state.deps, 'stock_symbol') and st.session_state.deps.stock_symbol:
                            current_stock_symbol = st.session_state.deps.stock_symbol
                        
                        # Priority 2: Check if user wants multiple stocks
                        wants_multiple = any(keyword in query_lower for keyword in [
                            'all indian', 'multiple', 'several', 'top stocks', 'best stocks',
                            'demo', 'sample', 'example', 'stocks'  # plural
                        ])
                        
                        # Determine stocks to visualize
                        if current_stock_symbol and not wants_multiple:
                            # Use only current stock
                            demo_stocks = [current_stock_symbol]
                            st.info(f"💡 Visualizing current stock: {st.session_state.current_stock} ({current_stock_symbol})")
                        else:
                            # Use demo stocks
                            demo_stocks = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS"]
                            
                            # If current stock exists, add it to the beginning
                            if current_stock_symbol and current_stock_symbol not in demo_stocks:
                                demo_stocks = [current_stock_symbol] + demo_stocks[:max_stocks-1]
                                st.info(f"💡 Visualizing {len(demo_stocks[:max_stocks])} stocks (including current: {st.session_state.current_stock})")
                            else:
                                st.info(f"💡 Visualizing {len(demo_stocks[:max_stocks])} sample Indian stocks")
                        
                        # Create a mock MCP response based on tool type
                        if demo_tool_type == 'candlestick':
                            mcp_response = f"""
                            Candlestick patterns detected:
                            {chr(10).join([f'- {symbol}: Pattern analysis' for symbol in demo_stocks[:max_stocks]])}
                            """
                        else:
                            mcp_response = f"""
                            Found {len(demo_stocks[:max_stocks])} stocks for analysis:
                            {chr(10).join([f'- {symbol}: Analyzing Bollinger Band patterns' for symbol in demo_stocks[:max_stocks]])}
                            """
                        
                        st.session_state.mcp_scan_response = mcp_response
                        st.session_state.mcp_scan_timeframe = timeframe
                        st.session_state.mcp_scan_max_stocks = min(max_stocks, len(demo_stocks))
                        st.session_state.mcp_demo_mode = True
                        
                        # Process with demo stocks using appropriate tool type
                        pipeline = get_visualization_pipeline()
                        
                        # Manually create results for demo stocks
                        viz_results = {
                            'stocks': [],
                            'summary': f"Demo Mode: Visualizing {len(demo_stocks)} Indian stocks",
                            'total_found': len(demo_stocks),
                            'processed': 0,
                            'tool_type': demo_tool_type
                        }
                        
                        for symbol in demo_stocks[:max_stocks]:
                            try:
                                if demo_tool_type == 'candlestick':
                                    # Candlestick pattern visualization
                                    from utils.data_fetcher import get_data_fetcher
                                    
                                    fetcher = get_data_fetcher()
                                    df, error_msg = fetcher.fetch_ohlc(symbol, timeframe)
                                    
                                    if df is not None:
                                        # Create candlestick pattern chart
                                        chart = pipeline.visualizer.create_candlestick_with_patterns(
                                            df,
                                            symbol,
                                            pattern_name="Bullish Pattern",
                                            title=f"{symbol} - Candlestick Patterns",
                                            show_volume=True
                                        )
                                        
                                        # Get stock name
                                        stock_name = symbol
                                        if symbol == current_stock_symbol and st.session_state.current_stock:
                                            stock_name = f"{st.session_state.current_stock} ({symbol})"
                                        
                                        stock_result = {
                                            'symbol': symbol,
                                            'original_symbol': symbol,
                                            'display_name': stock_name,
                                            'data': df,
                                            'chart': chart,
                                            'pattern': 'Bullish Pattern',
                                            'explanation': f'Candlestick pattern analysis for {stock_name}',
                                            'timeframe': timeframe,
                                            'signal_strength': 'medium',
                                            'mcp_description': f'Pattern analysis for {stock_name}',
                                            'is_current': symbol == current_stock_symbol,
                                            'tool_type': 'candlestick'
                                        }
                                        viz_results['stocks'].append(stock_result)
                                        viz_results['processed'] += 1
                                else:
                                    # Bollinger Band analysis (default)
                                    chart, error_msg, analysis = pipeline.visualize_single_stock(
                                        symbol,
                                        timeframe=timeframe,
                                        tool_type='bollinger'
                                    )
                                    
                                    if not error_msg and chart:
                                        # Get data
                                        from utils.data_fetcher import get_data_fetcher
                                        from utils.indicators import add_bollinger_bands
                                        
                                        fetcher = get_data_fetcher()
                                        df, _ = fetcher.fetch_ohlc(symbol, timeframe)
                                        if df is not None:
                                            df = add_bollinger_bands(df)
                                        
                                        # Get stock name
                                        stock_name = symbol
                                        if symbol == current_stock_symbol and st.session_state.current_stock:
                                            stock_name = f"{st.session_state.current_stock} ({symbol})"
                                        
                                        stock_result = {
                                            'symbol': symbol,
                                            'original_symbol': symbol,
                                            'display_name': stock_name,
                                            'data': df if df is not None else analysis.get('data'),
                                            'chart': chart,
                                            'squeeze_detected': analysis.get('squeeze_detected', False),
                                            'squeeze_percentile': analysis.get('squeeze_percentile', 0),
                                            'explanation': analysis.get('explanation', ''),
                                            'timeframe': timeframe,
                                            'signal_strength': 'strong' if analysis.get('squeeze_detected', False) else 'medium',
                                            'mcp_description': f'Analysis for {stock_name}',
                                            'is_current': symbol == current_stock_symbol,
                                            'tool_type': 'bollinger'
                                        }
                                        viz_results['stocks'].append(stock_result)
                                        viz_results['processed'] += 1
                            except Exception as e:
                                print(f"Error processing {symbol}: {e}")
                                continue
                        
                        # Update summary based on tool type
                        if demo_tool_type == 'candlestick':
                            if current_stock_symbol and not wants_multiple:
                                viz_results['summary'] = f"""📊 Current Stock Pattern Analysis:
   • Stock: {st.session_state.current_stock} ({current_stock_symbol})
   • Analysis: Candlestick patterns
   • Timeframe: {timeframe}
   • Note: MCP unavailable - using direct analysis"""
                            else:
                                viz_results['summary'] = f"""📊 Candlestick Pattern Analysis:
   • Stocks analyzed: {viz_results['processed']}
   • Timeframe: {timeframe}
   • Note: MCP unavailable - using direct analysis"""
                                if current_stock_symbol:
                                    viz_results['summary'] += f"\n   • Current stock included: {st.session_state.current_stock}"
                        else:
                            squeeze_count = sum(1 for s in viz_results['stocks'] if s.get('squeeze_detected', False))
                            
                            if current_stock_symbol and not wants_multiple:
                                viz_results['summary'] = f"""📊 Current Stock Analysis:
   • Stock: {st.session_state.current_stock} ({current_stock_symbol})
   • Bollinger squeeze: {'🔥 YES' if squeeze_count > 0 else '❌ NO'}
   • Timeframe: {timeframe}
   • Note: MCP unavailable - using direct analysis"""
                            else:
                                viz_results['summary'] = f"""📊 Technical Analysis:
   • Stocks analyzed: {viz_results['processed']}
   • Bollinger squeeze detected: {squeeze_count}/{viz_results['processed']}
   • Timeframe: {timeframe}
   • Note: MCP unavailable - using direct analysis"""
                                if current_stock_symbol:
                                    viz_results['summary'] += f"\n   • Current stock included: {st.session_state.current_stock}"
                        
                        st.session_state.mcp_viz_results = viz_results
                        st.rerun()
                        
                    elif error:
                        st.error(f"❌ Error during scan: {error}")
                        st.info("💡 Try using demo mode or check MCP configuration")
                    else:
                        # Success - process MCP response
                        # Handle ToolResponse object
                        if hasattr(result, 'output'):
                            output = result.output
                            # If output is ToolResponse, extract content
                            if hasattr(output, 'content'):
                                mcp_response = output.content
                            elif isinstance(output, str):
                                mcp_response = output
                            else:
                                mcp_response = str(output)
                        else:
                            mcp_response = str(result)
                        
                        print(f"📊 MCP Response type: {type(mcp_response)}")
                        print(f"📊 MCP Response preview: {mcp_response[:200] if isinstance(mcp_response, str) else 'Not a string'}")
                        
                        # Store MCP response
                        st.session_state.mcp_scan_response = mcp_response
                        st.session_state.mcp_scan_timeframe = timeframe
                        st.session_state.mcp_scan_max_stocks = max_stocks
                        st.session_state.mcp_demo_mode = False
                        
                        # Process and visualize
                        pipeline = get_visualization_pipeline()
                        
                        # Auto-detect tool type from query (comprehensive support)
                        query_lower = scan_query.lower()
                        if 'candle' in query_lower or 'pattern' in query_lower:
                            tool_type = 'candlestick'
                        elif 'rsi' in query_lower or 'relative strength' in query_lower or 'oversold' in query_lower or 'overbought' in query_lower:
                            tool_type = 'rsi'
                        elif 'macd' in query_lower or 'moving average convergence' in query_lower:
                            tool_type = 'macd'
                        elif ('moving average' in query_lower or 'sma' in query_lower or 'ema' in query_lower or 'golden cross' in query_lower or 'death cross' in query_lower) and 'macd' not in query_lower:
                            tool_type = 'moving_average'
                        elif 'volume' in query_lower and ('high' in query_lower or 'breakout' in query_lower or 'analysis' in query_lower):
                            tool_type = 'volume'
                        elif 'complete' in query_lower or 'full' in query_lower or 'all indicator' in query_lower or 'comprehensive' in query_lower:
                            tool_type = 'multi'
                        elif 'rating' in query_lower:
                            tool_type = 'rating'
                        else:
                            tool_type = 'unknown'  # Will auto-detect from response
                        
                        viz_results = pipeline.process_mcp_response(
                            mcp_response,
                            timeframe=timeframe,
                            max_stocks=max_stocks,
                            tool_type=tool_type
                        )
                        
                        # Check if MCP returned empty response
                        if viz_results.get('empty_response', False):
                            # MCP returned no stocks - show helpful message
                            st.warning("⚠️ No stocks found matching your criteria")
                            
                            if viz_results.get('is_empty_array', False):
                                # MCP explicitly returned empty array []
                                st.info("""
                                💡 **The TradingView MCP tool found no stocks matching your query.**
                                
                                This can happen when:
                                - The criteria are too specific (no stocks match)
                                - You're asking for analysis of a specific stock (MCP is for market-wide scanning)
                                - The query format isn't recognized by MCP
                                
                                **What you can do:**
                                
                                1. **For specific stock analysis:**
                                   - Go to **Chat** view (sidebar)
                                   - Ask: "Analyze [stock name]" for complete analysis
                                
                                2. **For market-wide scanning, try broader queries:**
                                   - "Find Indian stocks with Bollinger squeeze on NSE"
                                   - "Show stocks with bullish patterns on NSE"
                                   - "Scan NSE for breakout stocks"
                                
                                3. **Try Demo Mode:**
                                   - See how market scanning works with sample stocks
                                """)
                            else:
                                # Parse failure or unclear response
                                st.info("""
                                💡 **Could not parse the MCP response.**
                                
                                **Try these working queries:**
                                - "Find Indian stocks with Bollinger squeeze on NSE"
                                - "Show stocks with bullish candlestick patterns on NSE"
                                - "Scan NSE for breakout stocks"
                                
                                **Or use Demo Mode** to see sample technical analysis.
                                """)
                            
                            # Offer demo mode
                            if st.button("🎯 Try Demo Mode", width="stretch", key="demo_after_empty_response"):
                                st.session_state.force_demo_mode = True
                                st.rerun()
                            
                            # Stop here
                            st.stop()
                        
                        # Check if all stocks were crypto (skipped)
                        if viz_results.get('processed', 0) == 0 and viz_results.get('skipped_crypto'):
                            # All stocks were crypto - auto switch to demo mode
                            st.warning("⚠️ All stocks returned were cryptocurrency (not supported)")
                            st.info(f"""
                            💡 **MCP returned only crypto symbols:**
                            {', '.join(viz_results['skipped_crypto'][:5])}
                            
                            **Switching to Demo Mode with Indian stocks...**
                            
                            **💡 Tip:** For Indian stocks, use queries like:
                            - "Find Indian stocks with Bollinger squeeze on NSE"
                            - "Show NSE stocks with bullish patterns"
                            - "Scan NSE exchange for breakout stocks"
                            """)
                            
                            # Auto-switch to demo mode
                            st.session_state.force_demo_mode = True
                            st.rerun()
                        
                        # Store results and rerun to display
                        st.session_state.mcp_viz_results = viz_results
                        st.rerun()
                    
                except Exception as e:
                    st.error(f"❌ Error during scan: {str(e)}")
                    st.code(str(e))
                    
                    # Offer demo mode
                    if st.button("🎯 Try Demo Mode", width="stretch"):
                        st.session_state.force_demo_mode = True
                        st.rerun()
        
        # Demo mode button handler
        if demo_button or st.session_state.get('force_demo_mode', False):
            if 'force_demo_mode' in st.session_state:
                del st.session_state.force_demo_mode
            
            with st.spinner("🎯 Loading visualization..."):
                try:
                    from utils.mcp_visualization_pipeline import get_visualization_pipeline
                    
                    # Detect tool type from query (comprehensive support)
                    query_lower = scan_query.lower()
                    if 'candle' in query_lower or 'pattern' in query_lower:
                        demo_tool_type = 'candlestick'
                    elif 'rsi' in query_lower or 'relative strength' in query_lower or 'oversold' in query_lower or 'overbought' in query_lower:
                        demo_tool_type = 'rsi'
                    elif 'macd' in query_lower or 'moving average convergence' in query_lower:
                        demo_tool_type = 'macd'
                    elif ('moving average' in query_lower or 'sma' in query_lower or 'ema' in query_lower or 'golden cross' in query_lower or 'death cross' in query_lower) and 'macd' not in query_lower:
                        demo_tool_type = 'moving_average'
                    elif 'volume' in query_lower and ('high' in query_lower or 'breakout' in query_lower or 'analysis' in query_lower):
                        demo_tool_type = 'volume'
                    elif 'complete' in query_lower or 'full' in query_lower or 'all indicator' in query_lower or 'comprehensive' in query_lower:
                        demo_tool_type = 'multi'
                    elif 'rating' in query_lower:
                        demo_tool_type = 'rating'
                    else:
                        demo_tool_type = 'bollinger'
                    
                    # Priority 1: Use current analyzed stock if available
                    current_stock_symbol = None
                    if hasattr(st.session_state.deps, 'stock_symbol') and st.session_state.deps.stock_symbol:
                        current_stock_symbol = st.session_state.deps.stock_symbol
                        st.info(f"📊 Visualizing current stock: {st.session_state.current_stock} ({current_stock_symbol})")
                    
                    # Priority 2: Check if user wants "all Indian stocks" or demo stocks
                    wants_multiple = any(keyword in query_lower for keyword in [
                        'all indian', 'multiple', 'several', 'top stocks', 'best stocks',
                        'demo', 'sample', 'example'
                    ])
                    
                    # Determine stocks to visualize
                    if current_stock_symbol and not wants_multiple:
                        # Use only current stock
                        stocks_to_visualize = [current_stock_symbol]
                        mode_message = f"Analyzing current stock: {st.session_state.current_stock}"
                    else:
                        # Use demo stocks (multiple stocks requested or no current stock)
                        demo_stocks = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS"]
                        
                        # If current stock exists, add it to the beginning of the list
                        if current_stock_symbol and current_stock_symbol not in demo_stocks:
                            stocks_to_visualize = [current_stock_symbol] + demo_stocks[:max_stocks-1]
                        else:
                            stocks_to_visualize = demo_stocks[:max_stocks]
                        
                        mode_message = f"Analyzing {len(stocks_to_visualize)} stocks"
                        if current_stock_symbol:
                            mode_message += f" (including current: {st.session_state.current_stock})"
                    
                    st.info(f"💡 {mode_message}")
                    
                    # Create a mock MCP response based on tool type
                    if demo_tool_type == 'candlestick':
                        mcp_response = f"""
                        Candlestick patterns detected:
                        {chr(10).join([f'- {symbol}: Pattern analysis' for symbol in stocks_to_visualize])}
                        """
                    elif demo_tool_type == 'rsi':
                        mcp_response = f"""
                        RSI Analysis:
                        {chr(10).join([f'- {symbol}: RSI indicator analysis' for symbol in stocks_to_visualize])}
                        """
                    elif demo_tool_type == 'macd':
                        mcp_response = f"""
                        MACD Analysis:
                        {chr(10).join([f'- {symbol}: MACD indicator analysis' for symbol in stocks_to_visualize])}
                        """
                    elif demo_tool_type == 'moving_average':
                        mcp_response = f"""
                        Moving Average Analysis:
                        {chr(10).join([f'- {symbol}: MA analysis' for symbol in stocks_to_visualize])}
                        """
                    elif demo_tool_type == 'volume':
                        mcp_response = f"""
                        Volume Analysis:
                        {chr(10).join([f'- {symbol}: Volume analysis' for symbol in stocks_to_visualize])}
                        """
                    elif demo_tool_type == 'multi':
                        mcp_response = f"""
                        Complete Technical Analysis:
                        {chr(10).join([f'- {symbol}: Multi-indicator analysis' for symbol in stocks_to_visualize])}
                        """
                    else:
                        mcp_response = f"""
                        Technical Analysis:
                        {chr(10).join([f'- {symbol}: Bollinger Band analysis' for symbol in stocks_to_visualize])}
                        """
                    
                    st.session_state.mcp_scan_response = mcp_response
                    st.session_state.mcp_scan_timeframe = timeframe
                    st.session_state.mcp_scan_max_stocks = len(stocks_to_visualize)
                    st.session_state.mcp_demo_mode = True
                    
                    # Process with selected stocks
                    pipeline = get_visualization_pipeline()
                    
                    # Manually create results
                    viz_results = {
                        'stocks': [],
                        'summary': mode_message,
                        'total_found': len(stocks_to_visualize),
                        'processed': 0,
                        'tool_type': demo_tool_type
                    }
                    
                    for symbol in stocks_to_visualize:
                        try:
                            if demo_tool_type == 'candlestick':
                                # Candlestick pattern visualization
                                from utils.data_fetcher import get_data_fetcher
                                
                                fetcher = get_data_fetcher()
                                df, error_msg = fetcher.fetch_ohlc(symbol, timeframe)
                                
                                if df is not None:
                                    # Create candlestick pattern chart
                                    chart = pipeline.visualizer.create_candlestick_with_patterns(
                                        df,
                                        symbol,
                                        pattern_name="Bullish Pattern",
                                        title=f"{symbol} - Candlestick Patterns",
                                        show_volume=True
                                    )
                                    
                                    # Get stock name
                                    stock_name = symbol
                                    if symbol == current_stock_symbol and st.session_state.current_stock:
                                        stock_name = f"{st.session_state.current_stock} ({symbol})"
                                    
                                    stock_result = {
                                        'symbol': symbol,
                                        'original_symbol': symbol,
                                        'display_name': stock_name,
                                        'data': df,
                                        'chart': chart,
                                        'pattern': 'Bullish Pattern',
                                        'explanation': f'Candlestick pattern analysis for {stock_name}',
                                        'timeframe': timeframe,
                                        'signal_strength': 'medium',
                                        'mcp_description': f'Pattern analysis for {stock_name}',
                                        'is_current': symbol == current_stock_symbol,
                                        'tool_type': 'candlestick'
                                    }
                                    viz_results['stocks'].append(stock_result)
                                    viz_results['processed'] += 1
                            else:
                                # Use pipeline for other tool types (RSI, MACD, MA, Volume, Multi, Bollinger)
                                chart, error, analysis = pipeline.visualize_single_stock(
                                    symbol,
                                    timeframe=timeframe,
                                    tool_type=demo_tool_type
                                )
                                
                                if not error and chart:
                                    # Get data from analysis
                                    from utils.data_fetcher import get_data_fetcher
                                    
                                    fetcher = get_data_fetcher()
                                    df, _ = fetcher.fetch_ohlc(symbol, timeframe)
                                    
                                    # Get stock name
                                    stock_name = symbol
                                    if symbol == current_stock_symbol and st.session_state.current_stock:
                                        stock_name = f"{st.session_state.current_stock} ({symbol})"
                                    
                                    # Build result based on tool type
                                    stock_result = {
                                        'symbol': symbol,
                                        'original_symbol': symbol,
                                        'display_name': stock_name,
                                        'data': df,
                                        'chart': chart,
                                        'timeframe': timeframe,
                                        'mcp_description': f'{demo_tool_type.title()} analysis for {stock_name}',
                                        'is_current': symbol == current_stock_symbol,
                                        'tool_type': demo_tool_type
                                    }
                                    
                                    # Add tool-specific fields
                                    if demo_tool_type == 'bollinger':
                                        stock_result['squeeze_detected'] = analysis.get('squeeze_detected', False)
                                        stock_result['squeeze_percentile'] = analysis.get('squeeze_percentile', 0)
                                        stock_result['explanation'] = analysis.get('explanation', '')
                                        stock_result['signal_strength'] = 'strong' if analysis.get('squeeze_detected', False) else 'medium'
                                    elif demo_tool_type == 'rsi':
                                        stock_result['rsi_value'] = analysis.get('rsi_value')
                                        stock_result['explanation'] = analysis.get('explanation', '')
                                        stock_result['signal_strength'] = 'strong' if (analysis.get('rsi_value') and (analysis.get('rsi_value') < 30 or analysis.get('rsi_value') > 70)) else 'medium'
                                    elif demo_tool_type == 'macd':
                                        stock_result['macd_signal'] = analysis.get('macd_signal', 'Neutral')
                                        stock_result['explanation'] = analysis.get('explanation', '')
                                        stock_result['signal_strength'] = 'strong' if analysis.get('macd_signal') in ['Bullish', 'Bearish'] else 'medium'
                                    else:
                                        stock_result['explanation'] = analysis.get('explanation', '')
                                        stock_result['signal_strength'] = 'medium'
                                    
                                    viz_results['stocks'].append(stock_result)
                                    viz_results['processed'] += 1
                        except Exception as e:
                            st.warning(f"⚠️ Could not load {symbol}: {str(e)}")
                            continue
                    
                    # Update summary based on tool type
                    if demo_tool_type == 'candlestick':
                        if current_stock_symbol and not wants_multiple:
                            viz_results['summary'] = f"""📊 Current Stock Pattern Analysis:
   • Stock: {st.session_state.current_stock} ({current_stock_symbol})
   • Analysis: Candlestick patterns
   • Timeframe: {timeframe}"""
                        else:
                            viz_results['summary'] = f"""📊 Candlestick Pattern Analysis:
   • Stocks analyzed: {viz_results['processed']}
   • Timeframe: {timeframe}"""
                            if current_stock_symbol:
                                viz_results['summary'] += f"\n   • Current stock included: {st.session_state.current_stock}"
                    
                    elif demo_tool_type == 'rsi':
                        oversold_count = sum(1 for s in viz_results['stocks'] if s.get('rsi_value') and s.get('rsi_value') < 30)
                        overbought_count = sum(1 for s in viz_results['stocks'] if s.get('rsi_value') and s.get('rsi_value') > 70)
                        
                        if current_stock_symbol and not wants_multiple:
                            viz_results['summary'] = f"""📊 Current Stock RSI Analysis:
   • Stock: {st.session_state.current_stock} ({current_stock_symbol})
   • Analysis: RSI indicator
   • Timeframe: {timeframe}"""
                        else:
                            viz_results['summary'] = f"""📊 RSI Analysis:
   • Stocks analyzed: {viz_results['processed']}
   • Oversold (RSI < 30): {oversold_count}
   • Overbought (RSI > 70): {overbought_count}
   • Timeframe: {timeframe}"""
                            if current_stock_symbol:
                                viz_results['summary'] += f"\n   • Current stock included: {st.session_state.current_stock}"
                    
                    elif demo_tool_type == 'macd':
                        bullish_count = sum(1 for s in viz_results['stocks'] if s.get('macd_signal') == 'Bullish')
                        bearish_count = sum(1 for s in viz_results['stocks'] if s.get('macd_signal') == 'Bearish')
                        
                        if current_stock_symbol and not wants_multiple:
                            viz_results['summary'] = f"""📊 Current Stock MACD Analysis:
   • Stock: {st.session_state.current_stock} ({current_stock_symbol})
   • Analysis: MACD indicator
   • Timeframe: {timeframe}"""
                        else:
                            viz_results['summary'] = f"""📊 MACD Analysis:
   • Stocks analyzed: {viz_results['processed']}
   • Bullish signals: {bullish_count}
   • Bearish signals: {bearish_count}
   • Timeframe: {timeframe}"""
                            if current_stock_symbol:
                                viz_results['summary'] += f"\n   • Current stock included: {st.session_state.current_stock}"
                    
                    elif demo_tool_type in ['moving_average', 'ma']:
                        if current_stock_symbol and not wants_multiple:
                            viz_results['summary'] = f"""📊 Current Stock Moving Average Analysis:
   • Stock: {st.session_state.current_stock} ({current_stock_symbol})
   • Analysis: SMA 20, 50, 200
   • Timeframe: {timeframe}"""
                        else:
                            viz_results['summary'] = f"""📊 Moving Average Analysis:
   • Stocks analyzed: {viz_results['processed']}
   • Indicators: SMA 20, 50, 200
   • Timeframe: {timeframe}"""
                            if current_stock_symbol:
                                viz_results['summary'] += f"\n   • Current stock included: {st.session_state.current_stock}"
                    
                    elif demo_tool_type == 'volume':
                        if current_stock_symbol and not wants_multiple:
                            viz_results['summary'] = f"""📊 Current Stock Volume Analysis:
   • Stock: {st.session_state.current_stock} ({current_stock_symbol})
   • Analysis: Volume patterns
   • Timeframe: {timeframe}"""
                        else:
                            viz_results['summary'] = f"""📊 Volume Analysis:
   • Stocks analyzed: {viz_results['processed']}
   • Analysis: Volume patterns and trends
   • Timeframe: {timeframe}"""
                            if current_stock_symbol:
                                viz_results['summary'] += f"\n   • Current stock included: {st.session_state.current_stock}"
                    
                    elif demo_tool_type == 'multi':
                        if current_stock_symbol and not wants_multiple:
                            viz_results['summary'] = f"""📊 Current Stock Complete Analysis:
   • Stock: {st.session_state.current_stock} ({current_stock_symbol})
   • Analysis: All indicators (Bollinger, RSI, MACD, Volume)
   • Timeframe: {timeframe}"""
                        else:
                            viz_results['summary'] = f"""📊 Complete Technical Analysis:
   • Stocks analyzed: {viz_results['processed']}
   • Indicators: Bollinger, RSI, MACD, Volume
   • Timeframe: {timeframe}"""
                            if current_stock_symbol:
                                viz_results['summary'] += f"\n   • Current stock included: {st.session_state.current_stock}"
                    
                    else:
                        # Bollinger (default)
                        squeeze_count = sum(1 for s in viz_results['stocks'] if s.get('squeeze_detected', False))
                        
                        if current_stock_symbol and not wants_multiple:
                            viz_results['summary'] = f"""📊 Current Stock Analysis:
   • Stock: {st.session_state.current_stock} ({current_stock_symbol})
   • Bollinger squeeze: {'🔥 YES' if squeeze_count > 0 else '❌ NO'}
   • Timeframe: {timeframe}"""
                        else:
                            viz_results['summary'] = f"""📊 Technical Analysis:
   • Stocks analyzed: {viz_results['processed']}
   • Bollinger squeeze detected: {squeeze_count}/{viz_results['processed']}
   • Timeframe: {timeframe}"""
                            if current_stock_symbol:
                                viz_results['summary'] += f"\n   • Current stock included: {st.session_state.current_stock}"
                    
                    st.session_state.mcp_viz_results = viz_results
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"❌ Error in visualization: {str(e)}")
                    import traceback
                    st.code(traceback.format_exc())
        
        # Display results if available
        if hasattr(st.session_state, 'mcp_viz_results') and st.session_state.mcp_viz_results:
            results = st.session_state.mcp_viz_results
            tool_type = results.get('tool_type', 'bollinger')
            
            st.markdown("---")
            
            # Demo mode indicator
            if st.session_state.get('mcp_demo_mode', False):
                st.info("🎯 **Demo Mode Active** - Visualizing sample stocks without TradingView MCP")
            
            # Summary
            st.markdown("### 📊 Scan Results")
            st.info(results['summary'])
            
            # Display each stock
            if results['stocks']:
                for idx, stock_result in enumerate(results['stocks'], 1):
                    # Highlight current stock
                    is_current = stock_result.get('is_current', False)
                    display_name = stock_result.get('display_name', stock_result['symbol'])
                    
                    if is_current:
                        st.markdown(f"### {idx}. ⭐ {display_name} (Current Stock)")
                    else:
                        st.markdown(f"### {idx}. {display_name}")
                    
                    # Stock info - different metrics based on tool type
                    if tool_type == 'candlestick':
                        # Candlestick pattern metrics
                        col1, col2, col3 = st.columns(3)
                        
                        with col1:
                            st.metric("Timeframe", stock_result['timeframe'])
                        
                        with col2:
                            pattern = stock_result.get('pattern', 'Pattern Detected')
                            st.metric("Pattern", pattern)
                        
                        with col3:
                            signal_color = {
                                'strong': '🟢',
                                'medium': '🟡',
                                'weak': '🔴'
                            }.get(stock_result['signal_strength'], '⚪')
                            st.metric("Signal", f"{signal_color} {stock_result['signal_strength'].title()}")
                    
                    elif tool_type == 'rsi':
                        # RSI metrics
                        col1, col2, col3 = st.columns(3)
                        
                        with col1:
                            st.metric("Timeframe", stock_result['timeframe'])
                        
                        with col2:
                            rsi_value = stock_result.get('rsi_value')
                            if rsi_value:
                                rsi_status = "🔴 Overbought" if rsi_value > 70 else "🟢 Oversold" if rsi_value < 30 else "🟡 Neutral"
                                st.metric("RSI", f"{rsi_value:.2f}")
                            else:
                                st.metric("RSI", "N/A")
                        
                        with col3:
                            signal_color = {
                                'strong': '🟢',
                                'medium': '🟡',
                                'weak': '🔴'
                            }.get(stock_result['signal_strength'], '⚪')
                            st.metric("Signal", f"{signal_color} {stock_result['signal_strength'].title()}")
                    
                    elif tool_type == 'macd':
                        # MACD metrics
                        col1, col2, col3 = st.columns(3)
                        
                        with col1:
                            st.metric("Timeframe", stock_result['timeframe'])
                        
                        with col2:
                            macd_signal = stock_result.get('macd_signal', 'Neutral')
                            signal_emoji = "🟢" if macd_signal == 'Bullish' else "🔴" if macd_signal == 'Bearish' else "🟡"
                            st.metric("MACD Signal", f"{signal_emoji} {macd_signal}")
                        
                        with col3:
                            signal_color = {
                                'strong': '🟢',
                                'medium': '🟡',
                                'weak': '🔴'
                            }.get(stock_result['signal_strength'], '⚪')
                            st.metric("Strength", f"{signal_color} {stock_result['signal_strength'].title()}")
                    
                    elif tool_type in ['moving_average', 'ma']:
                        # Moving Average metrics
                        col1, col2, col3 = st.columns(3)
                        
                        with col1:
                            st.metric("Timeframe", stock_result['timeframe'])
                        
                        with col2:
                            st.metric("Indicators", "SMA 20, 50, 200")
                        
                        with col3:
                            signal_color = {
                                'strong': '🟢',
                                'medium': '🟡',
                                'weak': '🔴'
                            }.get(stock_result['signal_strength'], '⚪')
                            st.metric("Signal", f"{signal_color} {stock_result['signal_strength'].title()}")
                    
                    elif tool_type == 'volume':
                        # Volume metrics
                        col1, col2, col3 = st.columns(3)
                        
                        with col1:
                            st.metric("Timeframe", stock_result['timeframe'])
                        
                        with col2:
                            st.metric("Analysis", "Volume Patterns")
                        
                        with col3:
                            signal_color = {
                                'strong': '🟢',
                                'medium': '🟡',
                                'weak': '🔴'
                            }.get(stock_result['signal_strength'], '⚪')
                            st.metric("Signal", f"{signal_color} {stock_result['signal_strength'].title()}")
                    
                    elif tool_type == 'multi':
                        # Multi-indicator metrics
                        col1, col2, col3 = st.columns(3)
                        
                        with col1:
                            st.metric("Timeframe", stock_result['timeframe'])
                        
                        with col2:
                            st.metric("Analysis", "All Indicators")
                        
                        with col3:
                            signal_color = {
                                'strong': '🟢',
                                'medium': '🟡',
                                'weak': '🔴'
                            }.get(stock_result['signal_strength'], '⚪')
                            st.metric("Signal", f"{signal_color} {stock_result['signal_strength'].title()}")
                    
                    else:
                        # Bollinger Band metrics (default)
                        col1, col2, col3, col4 = st.columns(4)
                        
                        with col1:
                            st.metric("Timeframe", stock_result['timeframe'])
                        
                        with col2:
                            squeeze_status = "🔥 YES" if stock_result.get('squeeze_detected', False) else "❌ NO"
                            st.metric("Squeeze", squeeze_status)
                        
                        with col3:
                            st.metric("Percentile", f"{stock_result.get('squeeze_percentile', 0):.1f}%")
                        
                        with col4:
                            signal_color = {
                                'strong': '🟢',
                                'medium': '🟡',
                                'weak': '🔴'
                            }.get(stock_result['signal_strength'], '⚪')
                            st.metric("Signal", f"{signal_color} {stock_result['signal_strength'].title()}")
                    
                    # Explanation
                    with st.expander("📝 Analysis", expanded=True):
                        st.write(stock_result['explanation'])
                        if stock_result['mcp_description']:
                            st.caption(f"MCP: {stock_result['mcp_description']}")
                    
                    # Chart
                    if stock_result['chart']:
                        st.plotly_chart(
                            stock_result['chart'], 
                            width="stretch",
                            key=f"mcp_chart_{stock_result['symbol']}_{idx}"
                        )
                    
                    # Data preview - different columns based on tool type
                    with st.expander("📊 Data Preview"):
                        if stock_result['data'] is not None:
                            df_preview = stock_result['data']
                            
                            # Base columns (always present)
                            base_cols = ['datetime', 'open', 'high', 'low', 'close', 'volume']
                            
                            # Add tool-specific columns if they exist
                            if tool_type == 'candlestick' or tool_type == 'pattern':
                                # Show basic OHLCV for candlestick patterns
                                preview_cols = base_cols
                            elif tool_type == 'rsi':
                                # Show RSI data
                                preview_cols = base_cols + (['rsi'] if 'rsi' in df_preview.columns else [])
                            elif tool_type == 'macd':
                                # Show MACD data
                                macd_cols = [col for col in ['macd', 'macd_signal', 'macd_histogram'] if col in df_preview.columns]
                                preview_cols = base_cols + macd_cols
                            elif tool_type in ['moving_average', 'ma']:
                                # Show MA data
                                ma_cols = [col for col in ['sma_20', 'sma_50', 'sma_200'] if col in df_preview.columns]
                                preview_cols = base_cols + ma_cols
                            elif tool_type == 'volume':
                                # Show volume data (already in base)
                                preview_cols = base_cols
                            elif tool_type == 'multi' or tool_type == 'complete':
                                # Show all available indicators
                                indicator_cols = [col for col in ['rsi', 'macd', 'bb_upper', 'bb_middle', 'bb_lower'] if col in df_preview.columns]
                                preview_cols = base_cols + indicator_cols[:3]  # Limit to avoid too wide table
                            else:
                                # Bollinger Band data (default)
                                bb_cols = [col for col in ['bb_upper', 'bb_middle', 'bb_lower', 'bb_width'] if col in df_preview.columns]
                                preview_cols = base_cols + bb_cols
                            
                            # Display only columns that exist
                            available_cols = [col for col in preview_cols if col in df_preview.columns]
                            
                            if available_cols:
                                st.dataframe(
                                    df_preview[available_cols].tail(10),
                                    width="stretch"
                                )
                            else:
                                st.warning("No data available for preview")
                    
                    st.markdown("---")
                
                # Action buttons
                col1, col2 = st.columns(2)
                
                with col1:
                    if st.button("🔄 New Scan", width="stretch"):
                        # Clear results
                        if hasattr(st.session_state, 'mcp_viz_results'):
                            del st.session_state.mcp_viz_results
                        if hasattr(st.session_state, 'mcp_scan_response'):
                            del st.session_state.mcp_scan_response
                        st.rerun()
                
                with col2:
                    if st.button("🔙 Back to Chat", width="stretch"):
                        st.session_state.view_selector = "💬 Chat"
                        st.rerun()
            else:
                st.warning("No stocks found matching the criteria")
                
                if st.button("🔄 Try Again", width="stretch"):
                    if hasattr(st.session_state, 'mcp_viz_results'):
                        del st.session_state.mcp_viz_results
                    st.rerun()
        else:
            # Instructions
            st.markdown("---")
            st.markdown("### 🎯 How to Use")
            st.markdown("""
            1. **Enter a query** - Ask the AI to scan for technical patterns
            2. **Select timeframe** - Choose chart timeframe (1d, 1h, 15m, etc.)
            3. **Set max stocks** - Limit number of results to visualize
            4. **Click Scan Market** - AI will use TradingView MCP tools to find opportunities
            5. **View results** - Interactive charts with Bollinger Bands overlay
            
            **Example Queries:**
            
            **Bollinger Band Analysis:**
            - "Find Indian stocks showing a Bollinger Band squeeze"
            - "Show stocks with breakout potential on NSE"
            
            **Candlestick Patterns:**
            - "Scan for bullish candlestick patterns in Nifty 50"
            - "Find stocks with hammer pattern on NSE"
            - "Show candlestick patterns on TCS stock"
            
            **RSI Analysis:**
            - "Find oversold stocks with RSI below 30"
            - "Show overbought stocks on NSE"
            - "Scan for RSI divergence on Indian stocks"
            
            **MACD Analysis:**
            - "Find stocks with bullish MACD crossover"
            - "Show MACD signals on NSE stocks"
            - "Scan for MACD divergence"
            
            **Moving Averages:**
            - "Find stocks above 200-day moving average"
            - "Show golden cross stocks on NSE"
            - "Scan for death cross patterns"
            
            **Volume Analysis:**
            - "Find stocks with high volume breakout"
            - "Show volume surge stocks on NSE"
            - "Scan for volume anomalies"
            
            **Complete Analysis:**
            - "Complete technical analysis for TCS"
            - "Full indicator scan on NSE stocks"
            - "Comprehensive analysis of Indian stocks"
            """)
            
            st.markdown("---")
            st.markdown("### 📚 About Bollinger Bands")
            st.markdown("""
            **Bollinger Bands** are a technical analysis tool that consists of:
            - **Middle Band**: 20-period Simple Moving Average (SMA)
            - **Upper Band**: Middle Band + (2 × Standard Deviation)
            - **Lower Band**: Middle Band - (2 × Standard Deviation)
            
            **Bollinger Squeeze** occurs when:
            - Band width is at its lowest level in recent history
            - Indicates low volatility and potential for significant breakout
            - Often precedes major price movements
            
            **How to Trade:**
            1. Wait for squeeze to form (bands narrow)
            2. Watch for breakout direction (above upper or below lower band)
            3. Enter trade in breakout direction
            4. Set stop loss on opposite band
            """)
        
        with scanner_tab2:
            # NEW: TradingView JSON Scanner - Returns exact TradingView API format
            st.markdown("#### TradingView Drawing JSON Scanner")
            st.success("✅ MCP Scanner Agent (TradingView Format)")
            
            # Import TradingView scanner integration
            try:
                from utils.mcp_scanner_integration_tradingview import (
                    run_scanner_tradingview_sync,
                    get_tradingview_drawing_endpoint
                )
                TRADINGVIEW_SCANNER_AVAILABLE = True
            except ImportError:
                TRADINGVIEW_SCANNER_AVAILABLE = False
            
            if not TRADINGVIEW_SCANNER_AVAILABLE:
                st.error("❌ TradingView Scanner not available")
                st.info("Install dependencies: `pip install -r requirements_mcp_scanner.txt`")
            else:
                # Scanner Configuration
                st.markdown("##### 🔧 Scanner Configuration")
                
                col1, col2, col3 = st.columns([3, 1, 1])
                
                with col1:
                    tv_scan_query = st.text_input(
                        "Scanner Query",
                        value="Find stocks with Bollinger Band squeeze",
                        help="Describe the technical pattern you're looking for",
                        key="tv_scan_query"
                    )
                
                with col2:
                    tv_timeframe = st.selectbox(
                        "Timeframe",
                        options=['1m', '5m', '15m', '1h', '4h', '1D', '1W'],
                        index=5,
                        key="tv_timeframe"
                    )
                
                with col3:
                    tv_max_stocks = st.number_input(
                        "Max Stocks",
                        min_value=1,
                        max_value=10,
                        value=3,
                        key="tv_max_stocks"
                    )
                
                # Stock Selection
                st.markdown("##### 📈 Select Stocks to Scan")
                
                # Predefined lists
                indian_stocks = ["TCS.NS", "RELIANCE.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS"]
                us_stocks = ["AAPL", "MSFT", "GOOGL", "TSLA", "NVDA", "AMZN", "META"]
                
                tab_indian, tab_us, tab_custom = st.tabs(["🇮🇳 Indian Stocks", "🇺🇸 US Stocks", "✏️ Custom"])
                
                with tab_indian:
                    selected_indian = st.multiselect(
                        "Select Indian Stocks",
                        options=indian_stocks,
                        default=indian_stocks[:3],
                        key="tv_indian_stocks"
                    )
                
                with tab_us:
                    selected_us = st.multiselect(
                        "Select US Stocks",
                        options=us_stocks,
                        default=[],
                        key="tv_us_stocks"
                    )
                
                with tab_custom:
                    custom_symbols = st.text_area(
                        "Enter custom symbols (one per line)",
                        value="",
                        height=100,
                        key="tv_custom_symbols"
                    )
                    selected_custom = [s.strip() for s in custom_symbols.split('\n') if s.strip()]
                
                # Combine all selected symbols
                all_tv_symbols = selected_indian + selected_us + selected_custom
                
                if not all_tv_symbols:
                    st.warning("⚠️ Please select at least one stock to scan")
                else:
                    st.info(f"📊 Ready to scan {len(all_tv_symbols)} symbols: {', '.join(all_tv_symbols[:5])}{'...' if len(all_tv_symbols) > 5 else ''}")
                    
                    # Scan Button
                    col_scan, col_api = st.columns([1, 1])
                    
                    with col_scan:
                        tv_scan_button = st.button(
                            "🔍 Scan with MCP Agent (TradingView Format)",
                            type="primary",
                            use_container_width=True,
                            key="tv_scan_button"
                        )
                    
                    with col_api:
                        if st.button("🌐 View API Docs", use_container_width=True, key="tv_api_docs"):
                            st.session_state.show_tv_api_docs = not st.session_state.get('show_tv_api_docs', False)
                    
                    # API Documentation
                    if st.session_state.get('show_tv_api_docs', False):
                        with st.expander("📚 API Documentation", expanded=True):
                            st.markdown("""
                            ### Available Endpoints
                            
                            ```bash
                            # Get TradingView drawings for a symbol
                            GET http://localhost:5000/api/drawings/tradingview?symbol=AAPL
                            
                            # Get all latest drawings
                            GET http://localhost:5000/api/drawings/tradingview/latest
                            
                            # Trigger a new scan
                            POST http://localhost:5000/api/scan/tradingview
                            Body: {"query": "...", "symbols": [...], "timeframe": "1D"}
                            
                            # Health check
                            GET http://localhost:5000/api/health
                            
                            # Get drawing types
                            GET http://localhost:5000/api/drawing-types/tradingview
                            
                            # Get example JSON
                            GET http://localhost:5000/api/example/tradingview
                            ```
                            
                            ### Start API Server
                            ```bash
                            python api_drawings_endpoint_tradingview.py
                            ```
                            
                            ### TradingView Drawing Format
                            The scanner returns exact TradingView API format:
                            ```json
                            {
                              "id": "6VgiHl",
                              "type": "LineToolRiskRewardLong",
                              "state": {...},
                              "points": [...],
                              "zorder": -5000,
                              "linkKey": "6KXuHgdFCwnO",
                              "version": 2,
                              "ownerSource": "_seriesId",
                              "userEditEnabled": false,
                              "isSelectionEnabled": true
                            }
                            ```
                            """)
                    
                    # Run Scanner
                    if tv_scan_button:
                        with st.spinner("🤖 MCP Agent analyzing technical patterns (TradingView format)..."):
                            try:
                                # Run scanner
                                result = run_scanner_tradingview_sync(
                                    query=tv_scan_query,
                                    symbols=all_tv_symbols,
                                    timeframe=tv_timeframe,
                                    max_results=tv_max_stocks
                                )
                                
                                if result.get("success"):
                                    # Success metrics
                                    col_metric1, col_metric2, col_metric3 = st.columns(3)
                                    
                                    with col_metric1:
                                        st.metric(
                                            "Symbols Scanned",
                                            result.get("total_scanned", 0)
                                        )
                                    
                                    with col_metric2:
                                        st.metric(
                                            "Setups Found",
                                            result.get("total_results", 0)
                                        )
                                    
                                    with col_metric3:
                                        success_rate = (result.get("total_results", 0) / result.get("total_scanned", 1)) * 100
                                        st.metric(
                                            "Success Rate",
                                            f"{success_rate:.0f}%"
                                        )
                                    
                                    st.success(f"✅ Scan complete! Found {result['total_results']} technical setups")
                                    
                                    # Display Results
                                    st.markdown("#### 📊 Scan Results (TradingView Format)")
                                    
                                    for idx, scan_result in enumerate(result["results"], 1):
                                        if scan_result.get("success"):
                                            symbol = scan_result["symbol"]
                                            drawings = scan_result.get("drawings", [])
                                            metadata = scan_result.get("metadata", {})
                                            num_drawings = len(drawings)
                                            
                                            with st.expander(
                                                f"📈 {idx}. {symbol} - {num_drawings} TradingView drawings",
                                                expanded=(idx == 1)
                                            ):
                                                # Tabs for different views
                                                tab_viz, tab_json, tab_api, tab_download = st.tabs([
                                                    "📊 Visualization",
                                                    "📄 JSON",
                                                    "🌐 API",
                                                    "📥 Download"
                                                ])
                                                
                                                with tab_viz:
                                                    st.markdown("##### Drawing Instructions")
                                                    
                                                    for drawing in drawings:
                                                        draw_type = drawing.type if hasattr(drawing, 'type') else drawing.get("type", "unknown")
                                                        draw_id = drawing.id if hasattr(drawing, 'id') else drawing.get("id", "")
                                                        num_points = len(drawing.points if hasattr(drawing, 'points') else drawing.get("points", []))
                                                        
                                                        st.markdown(f"- **{draw_type}** (ID: `{draw_id}`, {num_points} points)")
                                                    
                                                    st.markdown("##### Metadata")
                                                    st.json(metadata)
                                                
                                                with tab_json:
                                                    # Convert drawings to dict if needed
                                                    drawings_dict = []
                                                    for d in drawings:
                                                        if hasattr(d, 'model_dump'):
                                                            drawings_dict.append(d.model_dump())
                                                        elif isinstance(d, dict):
                                                            drawings_dict.append(d)
                                                        else:
                                                            drawings_dict.append(str(d))
                                                    
                                                    st.json(drawings_dict)
                                                
                                                with tab_api:
                                                    st.markdown("##### API Endpoint")
                                                    st.code(
                                                        f"GET http://localhost:5000/api/drawings/tradingview?symbol={symbol}",
                                                        language="bash"
                                                    )
                                                    
                                                    st.markdown("##### cURL Command")
                                                    st.code(
                                                        f"curl http://localhost:5000/api/drawings/tradingview?symbol={symbol}",
                                                        language="bash"
                                                    )
                                                    
                                                    st.markdown("##### Next.js Integration")
                                                    st.code(f"""
const response = await fetch('http://localhost:5000/api/drawings/tradingview?symbol={symbol}');
const drawings = await response.json();

// Apply drawings to TradingView chart
drawings.forEach(drawing => {{
  chart.createShape(drawing.points, {{
    shape: drawing.type,
    overrides: drawing.state
  }});
}});
                                                    """, language="typescript")
                                                
                                                with tab_download:
                                                    # Download JSON
                                                    drawings_dict = []
                                                    for d in drawings:
                                                        if hasattr(d, 'model_dump'):
                                                            drawings_dict.append(d.model_dump())
                                                        elif isinstance(d, dict):
                                                            drawings_dict.append(d)
                                                    
                                                    json_str = json.dumps(drawings_dict, indent=2)
                                                    st.download_button(
                                                        label="📥 Download TradingView JSON",
                                                        data=json_str,
                                                        file_name=f"{symbol}_tradingview_drawings_{tv_timeframe}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                                                        mime="application/json",
                                                        key=f"download_tv_{symbol}_{idx}"
                                                    )
                                                    
                                                    st.markdown("##### File Info")
                                                    st.markdown(f"- **Symbol**: {symbol}")
                                                    st.markdown(f"- **Timeframe**: {tv_timeframe}")
                                                    st.markdown(f"- **Drawings**: {num_drawings}")
                                                    st.markdown(f"- **Size**: {len(json_str)} bytes")
                                                    st.markdown(f"- **Format**: TradingView API")
                                        
                                        else:
                                            # Failed scan
                                            symbol = scan_result.get("symbol", "Unknown")
                                            error = scan_result.get("error", "Unknown error")
                                            
                                            with st.expander(f"❌ {idx}. {symbol} - Failed"):
                                                st.error(f"Error: {error}")
                                
                                else:
                                    st.error(f"❌ Scanner failed: {result.get('error', 'Unknown error')}")
                            
                            except Exception as e:
                                st.error(f"❌ Error running TradingView scanner: {str(e)}")
                                st.exception(e)
                
                # Footer
                st.markdown("---")
                st.markdown("""
                <div style="text-align: center; color: #666; font-size: 0.9rem;">
                    <p>🤖 Powered by MCP Scanner Agent | 📊 TradingView Drawing Instructions</p>
                    <p>Returns exact TradingView API format for Next.js integration</p>
                    <p>Start API server: <code>python api_drawings_endpoint_tradingview.py</code></p>
                </div>
                """, unsafe_allow_html=True)

elif view_option == "📖 Presentation Viewer":
    # Presentation Viewer - Dedicated page for viewing generated presentations
    st.markdown("### 📖 Presentation Viewer")
    
    # Check if PPT was generated (check new bilingual structure first, then fall back to old)
    has_ppt = (hasattr(st.session_state, 'ppt_path_en') and st.session_state.ppt_path_en) or \
              (hasattr(st.session_state, 'ppt_path') and st.session_state.ppt_path)
    
    if not has_ppt:
        st.warning("⚠️ No presentation available")
        st.info("💡 Generate a presentation first by analyzing a stock and clicking 'Generate Presentation' in the sidebar")
        
        if st.button("🔙 Back to Chat", use_container_width=True):
            st.session_state.view_selector = "💬 Chat"
            st.rerun()
    else:
        # Language selector at the top (if bilingual PPTs are available)
        if hasattr(st.session_state, 'ppt_path_en') and st.session_state.ppt_path_en:
            col_lang, col_info = st.columns([1, 2])
            
            with col_lang:
                selected_language = st.radio(
                    "🌐 Language:",
                    options=["English", "हिंदी"],
                    index=0 if st.session_state.ppt_language == "english" else 1,
                    key="viewer_language_selector",
                    horizontal=True
                )
                
                # Update language in session state
                if selected_language == "English":
                    st.session_state.ppt_language = "english"
                    st.session_state.ppt_path = st.session_state.ppt_path_en
                    st.session_state.pdf_path = st.session_state.pdf_path_en
                else:
                    st.session_state.ppt_language = "hindi"
                    st.session_state.ppt_path = st.session_state.ppt_path_hi
                    st.session_state.pdf_path = st.session_state.pdf_path_hi
        
        # Show presentation info (compact, at top)
        ppt_filename = os.path.basename(st.session_state.ppt_path)
        
        # ========== SLIDE STATE MANAGEMENT ==========
        # Initialize slide state
        if "current_slide" not in st.session_state:
            st.session_state.current_slide = 1
        if "total_slides" not in st.session_state:
            st.session_state.total_slides = 12  # Default, will be updated from JSON
        if "auto_play" not in st.session_state:
            st.session_state.auto_play = True  # Default to True for automatic experience
        
        # Check for query parameter to advance slide (triggered by video end)
        query_params = st.query_params
        if "advance_slide" in query_params:
            try:
                target_slide = int(query_params["advance_slide"])
                if 1 <= target_slide <= st.session_state.total_slides:
                    st.session_state.current_slide = target_slide
                    print(f"🎬 Auto-advanced to slide {target_slide}")
                # Clear the query parameter
                st.query_params.clear()
                st.rerun()
            except:
                pass
        
        # Get total slides from script JSON if available
        if hasattr(st.session_state, 'script_json_path') and st.session_state.script_json_path and os.path.exists(st.session_state.script_json_path):
            try:
                import json
                with open(st.session_state.script_json_path, 'r', encoding='utf-8') as f:
                    script_data = json.load(f)
                slides = script_data.get('slide_structure', {}).get('slides', [])
                st.session_state.total_slides = len(slides)
            except:
                pass
        
        # ========== SLIDE-VIDEO MAPPING (BILINGUAL) ==========
        # Determine video folder based on selected language
        if st.session_state.ppt_language == "hindi":
            video_folder = "video_hindi"
            print(f"🎬 Using Hindi video folder: {video_folder}")
        else:  # english
            video_folder = "video_eng"
            print(f"🎬 Using English video folder: {video_folder}")
        
        # Map slides to videos in the appropriate language folder
        slide_videos = {}
        for i in range(1, st.session_state.total_slides + 1):
            # Use absolute path for reliability
            video_path = os.path.abspath(f"{video_folder}/202602 ({i}).mp4")
            slide_videos[i] = video_path
            
            # Debug: Check if video exists
            if os.path.exists(video_path):
                print(f"   ✅ Slide {i}: {video_path}")
            else:
                print(f"   ⚠️ Slide {i}: Video not found at {video_path}")
        
        # Top controls bar
        col_info, col_controls, col_restart = st.columns([2, 1, 1])
        
        with col_info:
            # Show language indicator
            lang_emoji = "🇬🇧" if st.session_state.ppt_language == "english" else "🇮🇳"
            lang_text = "English" if st.session_state.ppt_language == "english" else "हिंदी"
            st.success(f"📁 {ppt_filename} | {lang_emoji} {lang_text} | Slide {st.session_state.current_slide}/{st.session_state.total_slides}")
        
        with col_controls:
            st.session_state.auto_play = st.checkbox(
                "🎬 Automatic Mode", 
                value=st.session_state.auto_play, 
                help="Videos play automatically and advance to next slide when finished - Full hands-free experience!"
            )
        
        with col_restart:
            if st.button("🔄 Restart from Slide 1", use_container_width=True):
                st.session_state.current_slide = 1
                # Clear all slide timers
                if "slide_start_time" in st.session_state:
                    st.session_state.slide_start_time = {}
                st.rerun()
        
        # Check if PDF is available for viewing
        if hasattr(st.session_state, 'pdf_path') and st.session_state.pdf_path and os.path.exists(st.session_state.pdf_path):
            try:
                import base64
                
                print(f"📄 Loading PDF: {st.session_state.pdf_path}")
                
                # Read PDF file
                with open(st.session_state.pdf_path, "rb") as pdf_file:
                    pdf_bytes = pdf_file.read()
                
                print(f"✅ PDF loaded: {len(pdf_bytes)} bytes")
                
                # Check if PDF is too large for base64 embedding (>10MB)
                pdf_size_mb = len(pdf_bytes) / (1024 * 1024)
                print(f"📊 PDF size: {pdf_size_mb:.2f} MB")
                
                if pdf_size_mb > 10:
                    st.warning(f"⚠️ PDF is large ({pdf_size_mb:.1f} MB). Loading may take a moment...")
                
                # Encode to base64
                base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
                
                print(f"✅ PDF encoded to base64: {len(base64_pdf)} characters")
                
                # ========== NAVIGATION CONTROLS ==========
                col_prev, col_replay, col_next = st.columns([1, 1, 1])
                
                with col_prev:
                    if st.button("⬅️ Previous", use_container_width=True, disabled=(st.session_state.current_slide <= 1)):
                        st.session_state.current_slide = max(1, st.session_state.current_slide - 1)
                        # Clear the timer for the new slide so it restarts
                        if "slide_start_time" in st.session_state and st.session_state.current_slide in st.session_state.slide_start_time:
                            del st.session_state.slide_start_time[st.session_state.current_slide]
                        st.rerun()
                
                with col_replay:
                    if st.button("🔄 Replay", use_container_width=True):
                        # Clear the timer to restart current slide
                        if "slide_start_time" in st.session_state and st.session_state.current_slide in st.session_state.slide_start_time:
                            del st.session_state.slide_start_time[st.session_state.current_slide]
                        st.rerun()
                
                with col_next:
                    if st.button("➡️ Next", use_container_width=True, disabled=(st.session_state.current_slide >= st.session_state.total_slides)):
                        st.session_state.current_slide = min(st.session_state.total_slides, st.session_state.current_slide + 1)
                        # Clear the timer for the new slide so it restarts
                        if "slide_start_time" in st.session_state and st.session_state.current_slide in st.session_state.slide_start_time:
                            del st.session_state.slide_start_time[st.session_state.current_slide]
                        st.rerun()
                
                st.markdown("---")
                
                # TWO-COLUMN LAYOUT: PDF Viewer (left) + Synchronized Video Panel (right)
                col_pdf, col_video = st.columns([3, 1])
                
                with col_pdf:
                    # Display PDF with specific page (synchronized with current slide)
                    current_page = st.session_state.current_slide
                    
                    # Add timestamp to force iframe reload when page changes
                    import time
                    pdf_timestamp = int(time.time() * 1000)
                    
                    # Create a custom PDF viewer using PDF.js with embedded base64
                    # This avoids Chrome's blocking of data: URIs in iframes
                    pdf_viewer_html = f'''
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <meta charset="utf-8">
                        <meta name="viewport" content="width=device-width, initial-scale=1">
                        <title>PDF Viewer</title>
                        <style>
                            body {{
                                margin: 0;
                                padding: 0;
                                overflow: hidden;
                                background: #525659;
                            }}
                            #pdf-container {{
                                width: 100%;
                                height: 100vh;
                                display: flex;
                                flex-direction: column;
                                align-items: center;
                                justify-content: flex-start;
                                overflow-y: auto;
                                padding: 20px 0;
                            }}
                            canvas {{
                                border: 1px solid #ccc;
                                box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                                background: white;
                                margin-bottom: 20px;
                            }}
                            .loading {{
                                color: white;
                                font-family: Arial, sans-serif;
                                padding: 20px;
                                text-align: center;
                            }}
                        </style>
                    </head>
                    <body>
                        <div id="pdf-container">
                            <div class="loading">Loading PDF page {current_page}...</div>
                        </div>
                        
                        <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
                        <script>
                            // Set worker source
                            pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
                            
                            // Base64 PDF data
                            const pdfData = atob('{base64_pdf}');
                            const pdfArray = new Uint8Array(pdfData.length);
                            for (let i = 0; i < pdfData.length; i++) {{
                                pdfArray[i] = pdfData.charCodeAt(i);
                            }}
                            
                            // Load and render PDF
                            const loadingTask = pdfjsLib.getDocument({{data: pdfArray}});
                            loadingTask.promise.then(function(pdf) {{
                                console.log('PDF loaded, pages:', pdf.numPages);
                                
                                // Render the specific page
                                const pageNumber = {current_page};
                                pdf.getPage(pageNumber).then(function(page) {{
                                    console.log('Page loaded:', pageNumber);
                                    
                                    const scale = 1.5;
                                    const viewport = page.getViewport({{scale: scale}});
                                    
                                    const canvas = document.createElement('canvas');
                                    const context = canvas.getContext('2d');
                                    canvas.height = viewport.height;
                                    canvas.width = viewport.width;
                                    
                                    const container = document.getElementById('pdf-container');
                                    container.innerHTML = '';
                                    container.appendChild(canvas);
                                    
                                    const renderContext = {{
                                        canvasContext: context,
                                        viewport: viewport
                                    }};
                                    
                                    page.render(renderContext).promise.then(function() {{
                                        console.log('Page rendered successfully');
                                    }});
                                }});
                            }}, function(reason) {{
                                console.error('Error loading PDF:', reason);
                                document.getElementById('pdf-container').innerHTML = 
                                    '<div class="loading" style="color: #ff6b6b;">Error loading PDF: ' + reason + '</div>';
                            }});
                        </script>
                    </body>
                    </html>
                    '''
                    
                    # Use components.html to render the custom PDF viewer
                    components.html(pdf_viewer_html, height=920, scrolling=True)
                    print(f"✅ PDF viewer rendered - Page {current_page} (timestamp: {pdf_timestamp})")
                    
                    # Add download button as fallback
                    st.download_button(
                        label="📥 Download PDF",
                        data=pdf_bytes,
                        file_name=f"presentation_slide_{current_page}.pdf",
                        mime="application/pdf",
                        help="Download the PDF if it's not displaying correctly"
                    )
                
                with col_video:
                    # ========== SYNCHRONIZED VIDEO PANEL ==========
                    current_video_path = slide_videos.get(st.session_state.current_slide)
                    
                    if current_video_path and os.path.exists(current_video_path):
                        # Encode video to base64 for embedding
                        with open(current_video_path, "rb") as video_file:
                            video_bytes = video_file.read()
                        base64_video = base64.b64encode(video_bytes).decode('utf-8')
                        
                        # Generate unique key for video to force reload on slide change
                        video_timestamp = int(time.time() * 1000)
                        video_key = f"video_slide_{st.session_state.current_slide}_{video_timestamp}"
                        
                        # Build video HTML with onended event
                        autoplay_attr = "autoplay" if st.session_state.auto_play else ""
                        
                        # Create JavaScript that will submit a form when video ends
                        next_slide = st.session_state.current_slide + 1
                        can_advance = next_slide <= st.session_state.total_slides
                        
                        video_html = f'''
                        <div style="position: sticky; top: 80px; margin-top: 0.5rem;">
                            <div style="background: white; padding: 1rem; border-radius: 0.75rem; box-shadow: 0 4px 12px rgba(0,0,0,0.15);">
                                <h4 style="margin: 0 0 0.75rem 0; color: #1f2937; font-size: 1rem; font-weight: 600;">
                                    🎤 Slide {st.session_state.current_slide} of {st.session_state.total_slides}
                                </h4>
                                <video 
                                    id="{video_key}" 
                                    width="100%" 
                                    controls 
                                    {autoplay_attr}
                                    style="border-radius: 0.5rem; box-shadow: 0 2px 8px rgba(0,0,0,0.2);"
                                    onended="handleVideoEnd()">
                                    <source src="data:video/mp4;base64,{base64_video}" type="video/mp4">
                                    Your browser does not support the video tag.
                                </video>
                                <p style="margin: 0.5rem 0 0 0; font-size: 0.75rem; color: #6b7280; text-align: center;">
                                    Slide {st.session_state.current_slide}: Professional Analysis
                                </p>
                            </div>
                        </div>
                        
                        <script>
                        function handleVideoEnd() {{
                            const autoPlay = {str(st.session_state.auto_play).lower()};
                            const canAdvance = {str(can_advance).lower()};
                            
                            if (autoPlay && canAdvance) {{
                                console.log("Video ended, attempting to advance to next slide");
                                
                                // Try to find and click the hidden advance button
                                try {{
                                    // Look for the button in parent document
                                    const buttons = window.parent.document.querySelectorAll('button');
                                    for (let btn of buttons) {{
                                        if (btn.textContent.includes('AUTO_ADVANCE_HIDDEN')) {{
                                            console.log("Found advance button, clicking...");
                                            btn.click();
                                            return;
                                        }}
                                    }}
                                    console.log("Advance button not found");
                                }} catch(e) {{
                                    console.error("Error clicking button:", e);
                                }}
                            }}
                        }}
                        </script>
                        '''
                        
                        # Use components.html WITHOUT auto-refresh
                        components.html(video_html, height=450, scrolling=False)
                        print(f"✅ Synchronized video rendered - Slide {st.session_state.current_slide}")
                        
                        # Hidden button that JavaScript will click when video ends
                        if st.session_state.auto_play and st.session_state.current_slide < st.session_state.total_slides:
                            # Use a form to make the button more accessible to JavaScript
                            with st.form(key=f"advance_form_{st.session_state.current_slide}", clear_on_submit=True):
                                submitted = st.form_submit_button(
                                    "AUTO_ADVANCE_HIDDEN", 
                                    use_container_width=False,
                                    type="primary"
                                )
                                if submitted:
                                    st.session_state.current_slide += 1
                                    # Clear the timer for the new slide
                                    if "slide_start_time" in st.session_state and st.session_state.current_slide in st.session_state.slide_start_time:
                                        del st.session_state.slide_start_time[st.session_state.current_slide]
                                    print(f"🎬 Auto-advancing to slide {st.session_state.current_slide}")
                                    st.rerun()
                            
                            # Hide the button with CSS
                            st.markdown("""
                            <style>
                            /* Hide the AUTO_ADVANCE_HIDDEN button */
                            button[kind="primary"]:has-text("AUTO_ADVANCE_HIDDEN"),
                            button:has-text("AUTO_ADVANCE_HIDDEN"),
                            form:has(button:has-text("AUTO_ADVANCE_HIDDEN")) {
                                display: none !important;
                                visibility: hidden !important;
                                height: 0 !important;
                                width: 0 !important;
                                padding: 0 !important;
                                margin: 0 !important;
                                opacity: 0 !important;
                                position: absolute !important;
                                left: -9999px !important;
                            }
                            </style>
                            """, unsafe_allow_html=True)
                        
                        # Show status
                        if st.session_state.auto_play:
                            if st.session_state.current_slide < st.session_state.total_slides:
                                st.info("Automatic mode: Next slide will start when video ends")
                            else:
                                st.success("🎉 Final slide - Presentation complete!")
                    else:
                        # Placeholder if video doesn't exist for this slide
                        placeholder_html = f'''
                        <div style="position: sticky; top: 80px; margin-top: 0.5rem;">
                            <div style="background: white; padding: 1.5rem; border-radius: 0.75rem; box-shadow: 0 4px 12px rgba(0,0,0,0.15); text-align: center;">
                                <div style="font-size: 3rem; margin-bottom: 0.5rem;">🎤</div>
                                <h4 style="margin: 0 0 0.5rem 0; color: #1f2937; font-size: 1rem; font-weight: 600;">
                                    Slide {st.session_state.current_slide} Video
                                </h4>
                                <p style="margin: 0; font-size: 0.875rem; color: #6b7280;">
                                    Video not available
                                </p>
                                <p style="margin: 0.5rem 0 0 0; font-size: 0.75rem; color: #9ca3af;">
                                    Expected at:<br/>
                                    <code style="background: #f3f4f6; padding: 0.25rem 0.5rem; border-radius: 0.25rem; font-size: 0.7rem;">{current_video_path}</code>
                                </p>
                            </div>
                        </div>
                        '''
                        
                        st.markdown(placeholder_html, unsafe_allow_html=True)
                        print(f"⚠️ Video file not found for slide {st.session_state.current_slide}")
                
                # Action buttons BELOW the two-column layout
                st.markdown("---")
                st.markdown("#### 📥 Download Options")
                
                col1, col2, col3 = st.columns([2, 2, 1])
                
                with col1:
                    # Download PPT button (respects language selection)
                    try:
                        lang_label = "English" if st.session_state.ppt_language == "english" else "हिंदी"
                        with open(st.session_state.ppt_path, "rb") as file:
                            st.download_button(
                                label=f"⬇️ Download PPT ({lang_label})",
                                data=file,
                                file_name=ppt_filename,
                                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                                use_container_width=True,
                                key="download_ppt_viewer"
                            )
                    except Exception as e:
                        st.error(f"Error: {e}")
                
                with col2:
                    # Download PDF button
                    try:
                        with open(st.session_state.pdf_path, "rb") as file:
                            st.download_button(
                                label="⬇️ Download PDF",
                                data=file,
                                file_name=os.path.basename(st.session_state.pdf_path),
                                mime="application/pdf",
                                use_container_width=True,
                                key="download_pdf_viewer"
                            )
                    except Exception as e:
                        st.error(f"Error: {e}")
                
                with col3:
                    # Back button
                    if st.button("🔙 Back", use_container_width=True):
                        st.session_state.view_selector = "💬 Chat"
                        st.rerun()
                
                # Display Narration Scripts below download buttons
                if hasattr(st.session_state, 'script_json_path') and st.session_state.script_json_path and os.path.exists(st.session_state.script_json_path):
                    st.markdown("---")
                    st.markdown("### 🎤 Professional Narration Scripts")
                    st.info("💡 These scripts are ready for voice-over generation (Voicemaker, ElevenLabs) and AI avatar videos (gaga.art, D-ID)")
                    
                    try:
                        import json
                        
                        # Load script JSON
                        with open(st.session_state.script_json_path, 'r', encoding='utf-8') as f:
                            script_data = json.load(f)
                        
                        slides = script_data.get('slide_structure', {}).get('slides', [])
                        metadata = script_data.get('metadata', {})
                        
                        # Show statistics
                        total_words = sum(slide.get('script_word_count', 0) for slide in slides)
                        total_duration = sum(slide.get('script_duration_seconds', 0) for slide in slides)
                        
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("📊 Total Slides", len(slides))
                        with col2:
                            st.metric("📝 Total Words", total_words)
                        with col3:
                            st.metric("⏱️ Total Duration", f"{total_duration/60:.1f} min")
                        
                        st.markdown("---")
                        
                        # Display each slide's script
                        for i, slide in enumerate(slides, 1):
                            with st.expander(f"🎬 Slide {i}: {slide.get('title', 'Untitled')}", expanded=(i==1)):
                                # Slide info
                                col1, col2, col3 = st.columns(3)
                                with col1:
                                    st.caption(f"**Type:** {slide.get('type', 'N/A').title()}")
                                with col2:
                                    st.caption(f"**Words:** {slide.get('script_word_count', 0)}")
                                with col3:
                                    st.caption(f"**Duration:** {slide.get('script_duration_seconds', 0):.1f}s")
                                
                                # Script text
                                script_text = slide.get('script', 'No script available')
                                st.markdown("**Narration Script:**")
                                st.markdown(f"> {script_text}")
                                
                                # Show original content for reference
                                with st.expander("📋 Original Slide Content"):
                                    if slide.get('type') == 'bullets':
                                        st.markdown("**Bullet Points:**")
                                        for bullet in slide.get('content', []):
                                            st.markdown(f"- {bullet}")
                                    elif slide.get('type') == 'paragraph':
                                        st.markdown("**Paragraph:**")
                                        st.markdown(slide.get('paragraph', 'N/A'))
                                    elif slide.get('type') == 'mixed':
                                        st.markdown("**Bullet Points:**")
                                        for bullet in slide.get('content', []):
                                            st.markdown(f"- {bullet}")
                                        st.markdown("**Paragraph:**")
                                        st.markdown(slide.get('paragraph', 'N/A'))
                        
                        # Download script JSON button
                        st.markdown("---")
                        st.markdown("#### 📥 Download Narration Scripts")
                        
                        with open(st.session_state.script_json_path, 'r', encoding='utf-8') as f:
                            script_json_content = f.read()
                        
                        st.download_button(
                            label="⬇️ Download Scripts JSON",
                            data=script_json_content,
                            file_name=os.path.basename(st.session_state.script_json_path),
                            mime="application/json",
                            use_container_width=True,
                            key="download_scripts_json"
                        )
                        
                    except Exception as e:
                        st.error(f"❌ Error loading narration scripts: {e}")
                        print(f"❌ Error loading scripts: {e}")
                        import traceback
                        traceback.print_exc()
                else:
                    st.markdown("---")
                    st.info("💡 Narration scripts will be generated automatically when you open the presentation")
                    
            except Exception as e:
                print(f"❌ Error displaying PDF: {e}")
                import traceback
                traceback.print_exc()
                
                st.error(f"❌ Error displaying PDF: {str(e)}")
                st.warning("⚠️ PDF viewer encountered an issue. This could be due to:")
                st.markdown("""
                - Browser compatibility (try Chrome, Firefox, or Edge)
                - PDF file size or format
                - Browser security settings blocking embedded PDFs
                """)
                st.info("💡 You can still download the PDF and PPT files using the buttons below")
                
                # Show download buttons even if PDF viewer fails
                st.markdown("---")
                st.markdown("#### 📥 Download Options")
                col1, col2, col3 = st.columns([2, 2, 1])
                
                with col1:
                    try:
                        if hasattr(st.session_state, 'ppt_path') and st.session_state.ppt_path and os.path.exists(st.session_state.ppt_path):
                            with open(st.session_state.ppt_path, "rb") as file:
                                st.download_button(
                                    label="⬇️ Download PPT",
                                    data=file,
                                    file_name=os.path.basename(st.session_state.ppt_path),
                                    mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                                    use_container_width=True,
                                    key="download_ppt_error"
                                )
                    except Exception as download_error:
                        st.error(f"Error accessing PPT: {download_error}")
                
                with col2:
                    try:
                        if hasattr(st.session_state, 'pdf_path') and st.session_state.pdf_path and os.path.exists(st.session_state.pdf_path):
                            with open(st.session_state.pdf_path, "rb") as file:
                                st.download_button(
                                    label="⬇️ Download PDF",
                                    data=file,
                                    file_name=os.path.basename(st.session_state.pdf_path),
                                    mime="application/pdf",
                                    use_container_width=True,
                                    key="download_pdf_error"
                                )
                    except Exception as download_error:
                        st.error(f"Error accessing PDF: {download_error}")
                
                with col3:
                    if st.button("🔙 Back", use_container_width=True, key="back_error"):
                        st.session_state.view_selector = "💬 Chat"
                        st.rerun()
        
        else:
            # PDF not available
            st.warning("⚠️ PDF file not found")
            st.info("Please generate a presentation first using the 'Generate PPT' button in the Chat view")
            
            # Show debug info
            with st.expander("🔍 Debug Info"):
                st.code(f"PPT Path: {st.session_state.ppt_path if hasattr(st.session_state, 'ppt_path') else 'Not set'}")
                st.code(f"PDF Path: {st.session_state.pdf_path if hasattr(st.session_state, 'pdf_path') else 'Not set'}")
                if hasattr(st.session_state, 'pdf_path') and st.session_state.pdf_path:
                    st.code(f"PDF Exists: {os.path.exists(st.session_state.pdf_path)}")
                
                st.markdown("**How to enable PDF preview:**")
                st.markdown("- **Windows:** Install Microsoft PowerPoint + `pip install comtypes`")
                st.markdown("- **Linux:** Install LibreOffice: `sudo apt-get install libreoffice`")
            
            if st.button("🔙 Back to Chat"):
                st.session_state.view_selector = "💬 Chat"
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


elif view_option == "📈 Sentiment Analysis":
    # Analytics - Sentiment Analysis
    if st.session_state.company_data:
        data = st.session_state.company_data
        stock_name = data.name
        stock_symbol = data.symbol
        
        # ===== FIRST: Current Market Sentiment Section =====
        st.subheader("📈 Current Market Sentiment")
        st.caption("Real-time sentiment from News, Yahoo Finance, Twitter/X, and Reddit")
        
        # Check if sentiment analysis is already cached
        if 'sentiment_data' not in st.session_state or st.session_state.get('sentiment_stock') != stock_symbol:
            with st.spinner("🔍 Analyzing market sentiment from multiple sources (News, Yahoo Finance, Reddit, Twitter)..."):
                from utils.sentiment_analyzer_adanos import analyze_stock_sentiment
                
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
            
            # Determine number of columns based on available data
            has_twitter = 'twitter_sentiment' in sentiment_data
            has_reddit = 'reddit_sentiment' in sentiment_data
            
            if has_twitter and has_reddit:
                col1, col2, col3, col4, col5 = st.columns([2, 1, 1, 1, 1])
            elif has_twitter or has_reddit:
                col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
            else:
                col1, col2, col3 = st.columns([2, 1, 1])
            
            with col1:
                # Sentiment gauge
                score = sentiment_data['overall_score']
                label = sentiment_data['overall_label']
                color = sentiment_data['color']
                
                # Build sources text based on available data
                sources = ["News", "Yahoo Finance"]
                if 'twitter_sentiment' in sentiment_data:
                    sources.append("Twitter/X")
                if 'reddit_sentiment' in sentiment_data:
                    sources.append("Reddit")
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
            
            # Twitter column (if available)
            if has_twitter and has_reddit:
                with col4:
                    twitter_score = sentiment_data['twitter_sentiment']['sentiment_score']
                    twitter_label = sentiment_data['twitter_sentiment']['sentiment_label']
                    st.metric("🐦 Twitter/X", f"{twitter_score}/100", twitter_label)
            elif has_twitter:
                with col4:
                    twitter_score = sentiment_data['twitter_sentiment']['sentiment_score']
                    twitter_label = sentiment_data['twitter_sentiment']['sentiment_label']
                    st.metric("🐦 Twitter/X", f"{twitter_score}/100", twitter_label)
            
            # Reddit column (if available)
            if has_twitter and has_reddit:
                with col5:
                    reddit_score = sentiment_data['reddit_sentiment']['sentiment_score']
                    reddit_label = sentiment_data['reddit_sentiment']['sentiment_label']
                    st.metric("🔴 Reddit", f"{reddit_score}/100", reddit_label)
            elif has_reddit:
                with col4:
                    reddit_score = sentiment_data['reddit_sentiment']['sentiment_score']
                    reddit_label = sentiment_data['reddit_sentiment']['sentiment_label']
                    st.metric("🔴 Reddit", f"{reddit_score}/100", reddit_label)
            
            # Twitter/X and Reddit Sentiment - Side by side in two columns
            st.markdown("---")
            
            # Create two main columns for Twitter and Reddit
            social_col1, social_col2 = st.columns(2)
            
            # LEFT COLUMN: Twitter/X Sentiment
            with social_col1:
                if 'twitter_sentiment' in sentiment_data:
                    st.markdown("### 🐦 Twitter/X Sentiment")
                    
                    twitter_data = sentiment_data['twitter_sentiment']
                    
                    # Twitter sentiment score
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
                    
                    # Show source information as caption below score
                    source = twitter_data.get('source', 'unknown')
                    if source == 'rapidapi_twitter':
                        tweet_count = twitter_data.get('tweet_count', 0)
                        st.caption(f"📊 Based on {tweet_count} recent tweets")
                    elif source == 'news_based_twitter':
                        st.caption(f"📰 Based on news articles")
                    else:
                        st.caption("📊 Twitter sentiment data")
                    
                    # Fixed spacing before sentiment breakdown
                    st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)
                    
                    # Sentiment breakdown in 3 columns
                    tw_col1, tw_col2, tw_col3 = st.columns(3)
                    
                    with tw_col1:
                        positive_pct = twitter_data.get('positive_percentage', 0)
                        st.metric("👍 Positive", f"{positive_pct}%")
                    
                    with tw_col2:
                        negative_pct = twitter_data.get('negative_percentage', 0)
                        st.metric("👎 Negative", f"{negative_pct}%")
                    
                    with tw_col3:
                        neutral_pct = twitter_data.get('neutral_percentage', 0)
                        st.metric("😐 Neutral", f"{neutral_pct}%")
                    
                    # Show top engaging tweets if available
                    if twitter_data.get('top_tweets'):
                        st.markdown("<br>", unsafe_allow_html=True)
                        with st.expander("🔥 Top Engaging Tweets"):
                            for i, tweet in enumerate(twitter_data['top_tweets'][:5], 1):
                                sentiment_emoji = "✅" if tweet.get('sentiment_label') == 'Positive' else "⚠️" if tweet.get('sentiment_label') == 'Negative' else "➖"
                                tweet_text = tweet.get('text', 'N/A')
                                st.markdown(f"{sentiment_emoji} **Tweet {i}:** {tweet_text[:200]}...")
                                st.caption(f"❤️ {tweet.get('favorites', 0)} | 🔄 {tweet.get('retweets', 0)} | 💬 {tweet.get('replies', 0)}")
                                if i < 5:
                                    st.markdown("---")
                else:
                    st.markdown("### 🐦 Twitter/X Sentiment")
                    st.info("No Twitter data available")
            
            # RIGHT COLUMN: Reddit Sentiment
            with social_col2:
                if 'reddit_sentiment' in sentiment_data:
                    st.markdown("### 🔴 Reddit Sentiment")
                    
                    reddit_data = sentiment_data['reddit_sentiment']
                    
                    # Reddit sentiment score
                    reddit_score = reddit_data.get('sentiment_score', 0)
                    reddit_label = reddit_data.get('sentiment_label', 'N/A')
                    
                    # Color based on sentiment
                    if reddit_score >= 60:
                        reddit_color = "#10b981"
                    elif reddit_score >= 40:
                        reddit_color = "#fbbf24"
                    else:
                        reddit_color = "#ef4444"
                    
                    st.markdown(f"""
                    <div style="background: linear-gradient(135deg, {reddit_color}22 0%, {reddit_color}44 100%); 
                                padding: 1.5rem; border-radius: 0.75rem; border-left: 4px solid {reddit_color};">
                        <div style="font-size: 2rem; font-weight: bold; color: {reddit_color};">{reddit_score}/100</div>
                        <div style="font-size: 1rem; font-weight: 600; margin-top: 0.5rem;">{reddit_label}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Show source information as caption below score
                    total_posts = reddit_data.get('total_posts', 0)
                    total_items = reddit_data.get('total_items_analyzed', 0)
                    st.caption(f"📊 Based on {total_posts} posts & {total_items} items")
                    
                    # Fixed spacing before sentiment breakdown (same as Twitter)
                    st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)
                    
                    # Sentiment breakdown in 3 columns
                    rd_col1, rd_col2, rd_col3 = st.columns(3)
                    
                    with rd_col1:
                        positive_pct = reddit_data.get('positive_percentage', 0)
                        st.metric("👍 Positive", f"{positive_pct}%")
                    
                    with rd_col2:
                        negative_pct = reddit_data.get('negative_percentage', 0)
                        st.metric("👎 Negative", f"{negative_pct}%")
                    
                    with rd_col3:
                        neutral_pct = reddit_data.get('neutral_percentage', 0)
                        st.metric("😐 Neutral", f"{neutral_pct}%")
                    
                    # Show subreddit distribution in expander (like top posts)
                    if reddit_data.get('subreddit_distribution'):
                        st.markdown("<br>", unsafe_allow_html=True)
                        with st.expander("📊 Active Subreddits"):
                            subreddit_list = list(reddit_data['subreddit_distribution'].items())
                            # Display in rows of 2
                            for i in range(0, len(subreddit_list), 2):
                                sub_cols = st.columns(2)
                                for j, (subreddit, count) in enumerate(subreddit_list[i:i+2]):
                                    with sub_cols[j]:
                                        st.metric(f"r/{subreddit}", f"{count} posts")
                    
                    # Show top Reddit posts if available
                    if reddit_data.get('top_posts'):
                        with st.expander("🔥 Top Reddit Posts"):
                            for i, post in enumerate(reddit_data['top_posts'][:5], 1):
                                st.markdown(f"**{i}. {post['title']}**")
                                st.caption(f"r/{post['subreddit']} | ⬆️ {post['score']} | 💬 {post['num_comments']} comments")
                                # Only show link if URL is available
                                if post.get('url'):
                                    st.markdown(f"[View on Reddit]({post['url']})")
                                if i < 5:
                                    st.markdown("---")
                    
                    # Show Reddit insights in expander
                    if reddit_data.get('key_insights'):
                        with st.expander("💡 Key Insights"):
                            for insight in reddit_data['key_insights']:
                                st.markdown(f"• {insight}")
                else:
                    st.markdown("### 🔴 Reddit Sentiment")
                    st.info("No Reddit data available")
            
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
            
            # Refresh button
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
                from database_utility.database import StockDatabase
                
                # ===== BUILD COMPLETE MARKET SENTIMENT TEXT =====
                market_senti_text = f"""📈 Current Market Sentiment Analysis for {stock_name}

🎯 Overall Market Sentiment
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Overall Score: {sentiment_data['overall_score']}/100
Sentiment: {sentiment_data['overall_label']}
Based on: News, Yahoo Finance, Twitter/X

📊 Sentiment Breakdown
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📰 News Sentiment: {sentiment_data['news_sentiment']['sentiment_score']}/100 ({sentiment_data['news_sentiment']['sentiment_label']})
📊 Yahoo Finance: {sentiment_data['yahoo_sentiment']['sentiment_score']}/100 ({sentiment_data['yahoo_sentiment']['analyst_rating']})
"""
                
                # Add Twitter sentiment if available
                if 'twitter_sentiment' in sentiment_data:
                    twitter_data = sentiment_data['twitter_sentiment']
                    market_senti_text += f"🐦 Twitter/X: {twitter_data['sentiment_score']}/100 ({twitter_data['sentiment_label']})\n"
                    market_senti_text += f"   - Positive: {twitter_data.get('positive_percentage', 0)}%\n"
                    market_senti_text += f"   - Negative: {twitter_data.get('negative_percentage', 0)}%\n"
                    market_senti_text += f"   - Neutral: {twitter_data.get('neutral_percentage', 0)}%\n"
                    if twitter_data.get('tweet_count'):
                        market_senti_text += f"   - Based on {twitter_data['tweet_count']} tweets\n"
                
                market_senti_text += "\n📈 Positive Factors\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                
                positive_points = sentiment_data['news_sentiment'].get('positive_points', [])
                if positive_points and positive_points != ['Insufficient data']:
                    for point in positive_points:
                        market_senti_text += f"✅ {point}\n"
                else:
                    market_senti_text += "No significant positive factors identified\n"
                
                market_senti_text += "\n📉 Negative Factors\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                
                negative_points = sentiment_data['news_sentiment'].get('negative_points', [])
                if negative_points and negative_points != ['Insufficient data']:
                    for point in negative_points:
                        market_senti_text += f"⚠️ {point}\n"
                else:
                    market_senti_text += "No significant negative factors identified\n"
                
                market_senti_text += "\n💭 Market Mood & Analysis\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                market_senti_text += sentiment_data['final_analysis']
                
                # Determine market sentiment status
                market_senti_status = sentiment_data['overall_label'].lower()
                
                # ===== BUILD COMPLETE FUTURE SENTIMENT TEXT =====
                future_senti_text = f"""🔮 Future Outlook & News Analysis for {stock_name}

{news_result.get('analysis', 'No analysis available')}
"""
                
                # Add Tavily summary if available
                if news_result.get('tavily_summary'):
                    future_senti_text += f"\n\n🌐 Web Search Summary\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    future_senti_text += news_result['tavily_summary']
                
                # Add source articles
                articles = news_result.get('articles', [])
                if articles:
                    future_senti_text += f"\n\n📚 Source Articles ({len(articles)} articles)\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    
                    # Group by source
                    source_counts = {}
                    for article in articles:
                        source = article.get('source', 'Unknown')
                        source_counts[source] = source_counts.get(source, 0) + 1
                    
                    future_senti_text += "Sources:\n"
                    for source, count in source_counts.items():
                        future_senti_text += f"  • {source}: {count} articles\n"
                    
                    future_senti_text += "\nTop Articles:\n"
                    for i, article in enumerate(articles[:5], 1):
                        future_senti_text += f"\n{i}. {article.get('title', 'Untitled')}\n"
                        future_senti_text += f"   Source: {article.get('source', 'Unknown')}\n"
                        future_senti_text += f"   {article.get('snippet', 'No preview available')}\n"
                
                # Determine future sentiment status from analysis text
                future_senti_status = "neutral"
                if future_senti_text:
                    text_lower = future_senti_text.lower()
                    positive_keywords = ['positive', 'bullish', 'growth', 'strong', 'optimistic', 'upside', 'buy', 'outperform']
                    negative_keywords = ['negative', 'bearish', 'decline', 'weak', 'pessimistic', 'downside', 'sell', 'underperform']
                    
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
                        print(f"✅ Complete sentiment data updated in database for {stock_name}")
                        print(f"   - Market sentiment: {len(market_senti_text)} characters")
                        print(f"   - Future sentiment: {len(future_senti_text)} characters")
                    
                    db.disconnect()
            except Exception as db_error:
                print(f"⚠️ Database sentiment update error: {db_error}")
                import traceback
                traceback.print_exc()
                # Continue even if database update fails
    
    else:
        st.info("📈 Analyze a stock to see analytics")

elif view_option == "🔍 Bulk Stock Analyzer":
    # Bulk Stock Analyzer - Full-featured version matching bulk_stock_dashboard.py
    st.markdown("### 🔍 Bulk Stock Analyzer")
    st.markdown("Find stocks that have fallen ≥25% from their 52-week high")
    
    # Import required modules
    from utils.bulk_stock_selector import BulkStockSelector, SAMPLE_INDIAN_STOCKS
    import yfinance as yf
    import json
    
    # Initialize session state for bulk analyzer
    if 'bulk_results' not in st.session_state:
        st.session_state.bulk_results = None
    if 'bulk_processing' not in st.session_state:
        st.session_state.bulk_processing = False
    if 'bulk_stock_list' not in st.session_state:
        st.session_state.bulk_stock_list = SAMPLE_INDIAN_STOCKS
    
    # Helper function for stock price charts
    def load_stock_price_chart(symbol: str):
        """Load and display price chart for a stock"""
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="1y")
            
            if hist.empty:
                st.warning(f"No data available for {symbol}")
                return
            
            # Create line chart
            fig = go.Figure()
            
            fig.add_trace(go.Scatter(
                x=hist.index,
                y=hist['Close'],
                mode='lines',
                name='Close Price',
                line=dict(color='#667eea', width=2),
                fill='tozeroy',
                fillcolor='rgba(102, 126, 234, 0.1)'
            ))
            
            # Add high line
            overall_high = hist['High'].max()
            fig.add_hline(
                y=overall_high,
                line_dash="dash",
                line_color="red",
                annotation_text=f"52W High: ₹{overall_high:.2f}",
                annotation_position="right"
            )
            
            # Add 25% drop line
            drop_25_price = overall_high * 0.75
            fig.add_hline(
                y=drop_25_price,
                line_dash="dash",
                line_color="orange",
                annotation_text=f"25% Drop: ₹{drop_25_price:.2f}",
                annotation_position="right"
            )
            
            fig.update_layout(
                title=f"{symbol} - 1 Year Price History",
                xaxis_title="Date",
                yaxis_title="Price (₹)",
                hovermode='x unified',
                height=400,
                showlegend=True
            )
            
            st.plotly_chart(fig, width='stretch')
            
        except Exception as e:
            st.error(f"Error loading chart: {e}")
    
    # Configuration section
    with st.expander("⚙️ Configuration", expanded=True):
        col1, col2 = st.columns([2, 1])
        
        with col1:
            input_method = st.radio(
                "Input Method",
                ["Use Sample List", "Upload File", "Manual Entry"],
                help="Choose how to provide stock symbols",
                horizontal=True
            )
        
        with col2:
            max_workers = st.slider("Concurrent Workers", 5, 20, 10, help="Number of parallel processes")
            timeout = st.slider("Timeout (seconds)", 5, 30, 15)
        
        if input_method == "Use Sample List":
            st.info(f"📋 Using {len(SAMPLE_INDIAN_STOCKS)} sample Indian stocks")
            st.session_state.bulk_stock_list = SAMPLE_INDIAN_STOCKS
            
        elif input_method == "Upload File":
            uploaded_file = st.file_uploader(
                "Upload CSV/TXT file (company names or ticker symbols)",
                type=['csv', 'txt'],
                help="File can contain company names (e.g., 'Reliance Industries') or ticker symbols (e.g., 'RELIANCE.NS')"
            )
            if uploaded_file:
                content = uploaded_file.read().decode('utf-8')
                lines = [line.strip() for line in content.split('\n') if line.strip()]
                
                # Check if lines are company names or ticker symbols
                ticker_symbols = [line for line in lines if line.endswith('.NS') or line.endswith('.BO')]
                company_names = [line for line in lines if not (line.endswith('.NS') or line.endswith('.BO'))]
                
                if company_names:
                    st.info(f"📋 Detected {len(company_names)} company names and {len(ticker_symbols)} ticker symbols")
                    
                    if st.button("🔍 Resolve Company Names to Ticker Symbols", key="bulk_resolve_btn"):
                        with st.spinner(f"Resolving {len(company_names)} company names..."):
                            from utils.stock_symbol_resolver import StockSymbolResolver
                            
                            resolver = StockSymbolResolver()
                            resolve_results = resolver.resolve_list(company_names)
                            
                            all_symbols = ticker_symbols + resolve_results['resolved_symbols']
                            st.session_state.bulk_stock_list = all_symbols
                            
                            st.success(f"✅ Resolved {resolve_results['resolved']}/{resolve_results['total']} company names")
                            st.metric("Success Rate", f"{resolve_results['success_rate']:.1f}%")
                            
                            col1, col2 = st.columns(2)
                            with col1:
                                st.metric("Total Symbols", len(all_symbols))
                            with col2:
                                st.metric("Failed", resolve_results['failed'])
                            
                            if resolve_results['failed_names']:
                                with st.expander(f"❌ Failed to resolve {len(resolve_results['failed_names'])} names"):
                                    for name in resolve_results['failed_names']:
                                        st.write(f"- {name}")
                else:
                    st.session_state.bulk_stock_list = ticker_symbols
                    st.success(f"✅ Loaded {len(ticker_symbols)} ticker symbols")
        
        else:  # Manual Entry
            manual_input = st.text_area(
                "Enter stock symbols (one per line)",
                value="\n".join(SAMPLE_INDIAN_STOCKS[:10]),
                height=150,
                help="Enter ticker symbols like RELIANCE.NS, TCS.NS"
            )
            if manual_input:
                stocks = [line.strip() for line in manual_input.split('\n') if line.strip()]
                st.session_state.bulk_stock_list = stocks
                
                invalid_symbols = [s for s in stocks if not (s.endswith('.NS') or s.endswith('.BO'))]
                if invalid_symbols:
                    st.warning(f"⚠️ {len(invalid_symbols)} symbols may be invalid (should end with .NS or .BO)")
    
    # Process button
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        if st.button("🚀 Process Stocks", type="primary", use_container_width=True):
            st.session_state.bulk_processing = True
            st.rerun()
    
    with col2:
        if st.session_state.bulk_results and st.button("🔄 Clear Results", use_container_width=True):
            st.session_state.bulk_results = None
            st.rerun()
    
    # Processing
    if st.session_state.bulk_processing:
        st.session_state.bulk_processing = False
        
        with st.spinner(f"Processing {len(st.session_state.bulk_stock_list)} stocks..."):
            processor = BulkStockSelector(max_workers=max_workers, timeout=timeout)
            results = processor.process_bulk_stocks(st.session_state.bulk_stock_list)
            st.session_state.bulk_results = results
        
        st.success("✅ Processing complete!")
        st.rerun()
    
    # Display results
    if st.session_state.bulk_results:
        results = st.session_state.bulk_results
        
        st.markdown("---")
        st.markdown("## 📈 Summary")
        
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("Total Stocks", results['total_stocks_processed'])
        with col2:
            st.metric("Successful", results['successful_count'])
        with col3:
            st.metric("Errors", results['error_count'])
        with col4:
            st.metric("Selected", results['selected_count'], 
                     delta=f"{(results['selected_count']/results['successful_count']*100):.1f}%" if results['successful_count'] > 0 else "0%")
        with col5:
            st.metric("Processing Time", f"{results['processing_time_seconds']}s")
        
        st.markdown("---")
        
        # Tabs for different views
        tab1, tab2, tab3, tab4 = st.tabs(["🎯 Selected Stocks", "📊 All Results", "📈 Visualizations", "💾 Export"])
        
        with tab1:
            st.markdown("### Selected Stocks (≥25% drop from high)")
            
            if results['selected_stocks']:
                # Create DataFrame
                df_selected = pd.DataFrame(results['selected_stocks'])
                
                # Display count
                st.info(f"Found {len(df_selected)} stocks that have fallen ≥25% from their 52-week high")
                
                # Sort by percent change
                df_selected = df_selected.sort_values('percent_change_from_high')
                
                # Display table
                st.dataframe(
                    df_selected[[
                        'stock_symbol', 'stock_name', 'current_price', 
                        'overall_high', 'percent_change_from_high'
                    ]].style.format({
                        'current_price': '₹{:.2f}',
                        'overall_high': '₹{:.2f}',
                        'percent_change_from_high': '{:.2f}%'
                    }),
                    width='stretch',
                    height=400
                )
                
                # Show detailed cards
                st.markdown("#### Detailed View")
                for idx, stock in df_selected.iterrows():
                    with st.expander(f"📊 {stock['stock_symbol']} - {stock['stock_name']}"):
                        col1, col2, col3 = st.columns(3)
                        
                        with col1:
                            st.metric("Current Price", f"₹{stock['current_price']:.2f}")
                            st.metric("52W High", f"₹{stock['overall_high']:.2f}")
                        
                        with col2:
                            st.metric("52W Low", f"₹{stock['overall_low']:.2f}")
                            st.metric("% from High", f"{stock['percent_change_from_high']:.2f}%")
                        
                        with col3:
                            potential_gain = ((stock['overall_high'] - stock['current_price']) / stock['current_price']) * 100
                            st.metric("Potential Gain to High", f"{potential_gain:.2f}%")
                            st.caption(f"Last Updated: {stock['last_updated']}")
                        
                        # Load price chart
                        if st.checkbox(f"Show Chart for {stock['stock_symbol']}", key=f"chart_selected_{idx}_{stock['stock_symbol']}"):
                            load_stock_price_chart(stock['stock_symbol'])
            else:
                st.warning("⚠️ No stocks met the selection criteria (≥25% drop from high)")
        
        with tab2:
            st.markdown("### All Processed Stocks")
            
            # Create DataFrame
            df_all = pd.DataFrame(results['all_results'])
            
            # Filter options
            col1, col2 = st.columns(2)
            with col1:
                show_errors = st.checkbox("Show errors", value=False)
            with col2:
                sort_by = st.selectbox("Sort by", 
                                       ['percent_change_from_high', 'current_price', 'stock_symbol'])
            
            # Filter and sort
            if not show_errors:
                df_display = df_all[df_all['error'].isna()]
            else:
                df_display = df_all
            
            df_display = df_display.sort_values(sort_by)
            
            # Display table with color coding
            def color_selection(val):
                """Color code the selection column"""
                if val:
                    return 'background-color: #d4edda; color: #155724'  # Green
                else:
                    return 'background-color: #f8d7da; color: #721c24'  # Red
            
            st.dataframe(
                df_display[[
                    'stock_symbol', 'stock_name', 'current_price', 
                    'overall_high', 'percent_change_from_high', 'selection'
                ]].style.format({
                    'current_price': '₹{:.2f}',
                    'overall_high': '₹{:.2f}',
                    'percent_change_from_high': '{:.2f}%'
                }).map(color_selection, subset=['selection']),
                width='stretch',
                height=500
            )
        
        with tab3:
            st.markdown("### Visualizations")
            
            # Create DataFrame for successful stocks
            df_viz = pd.DataFrame([r for r in results['all_results'] if not r.get('error')])
            
            if not df_viz.empty:
                col1, col2 = st.columns(2)
                
                with col1:
                    # Distribution of % change
                    fig1 = px.histogram(
                        df_viz,
                        x='percent_change_from_high',
                        nbins=30,
                        title='Distribution of % Change from High',
                        labels={'percent_change_from_high': '% Change from High'},
                        color_discrete_sequence=['#667eea']
                    )
                    fig1.add_vline(x=-25, line_dash="dash", line_color="red", 
                                  annotation_text="Selection Threshold (-25%)")
                    st.plotly_chart(fig1, width='stretch')
                
                with col2:
                    # Selection pie chart
                    selection_counts = df_viz['selection'].value_counts()
                    
                    # Handle case where all stocks have same selection status
                    if len(selection_counts) == 1:
                        if selection_counts.index[0]:
                            names = ['Selected']
                            colors = ['#10b981']
                        else:
                            names = ['Not Selected']
                            colors = ['#ef4444']
                        
                        fig2 = px.pie(
                            values=selection_counts.values,
                            names=names,
                            title='Selection Status',
                            color_discrete_sequence=colors
                        )
                    else:
                        names = ['Not Selected' if not idx else 'Selected' for idx in selection_counts.index]
                        fig2 = px.pie(
                            values=selection_counts.values,
                            names=names,
                            title='Selection Status',
                            color_discrete_sequence=['#ef4444', '#10b981']
                        )
                    
                    st.plotly_chart(fig2, width='stretch')
                
                # Top 10 biggest drops
                st.markdown("#### Top 10 Biggest Drops")
                top_drops = df_viz.nsmallest(10, 'percent_change_from_high')
                
                fig3 = px.bar(
                    top_drops,
                    x='stock_symbol',
                    y='percent_change_from_high',
                    title='Top 10 Stocks with Biggest Drops',
                    labels={'percent_change_from_high': '% Change from High', 'stock_symbol': 'Stock'},
                    color='percent_change_from_high',
                    color_continuous_scale='RdYlGn_r'
                )
                fig3.add_hline(y=-25, line_dash="dash", line_color="red")
                st.plotly_chart(fig3, width='stretch')
                
                # Scatter plot: Current Price vs % Change
                fig4 = px.scatter(
                    df_viz,
                    x='current_price',
                    y='percent_change_from_high',
                    color='selection',
                    hover_data=['stock_symbol', 'stock_name'],
                    title='Current Price vs % Change from High',
                    labels={
                        'current_price': 'Current Price (₹)',
                        'percent_change_from_high': '% Change from High'
                    },
                    color_discrete_map={True: '#10b981', False: '#ef4444'}
                )
                fig4.add_hline(y=-25, line_dash="dash", line_color="red")
                st.plotly_chart(fig4, width='stretch')
        
        with tab4:
            st.markdown("### Export Results")
            
            col1, col2 = st.columns(2)
            
            with col1:
                # Export selected stocks as CSV
                if results['selected_stocks']:
                    df_selected = pd.DataFrame(results['selected_stocks'])
                    csv_selected = df_selected.to_csv(index=False)
                    
                    st.download_button(
                        label="📥 Download Selected Stocks (CSV)",
                        data=csv_selected,
                        file_name=f"selected_stocks_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv",
                        width='stretch'
                    )
            
            with col2:
                # Export all results as JSON
                json_data = json.dumps(results, indent=2)
                
                st.download_button(
                    label="📥 Download All Results (JSON)",
                    data=json_data,
                    file_name=f"stock_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                    mime="application/json",
                    width='stretch'
                )
            
            # Display JSON preview
            with st.expander("Preview JSON Data"):
                st.json(results)
    
    else:
        # Welcome screen
        st.info("👆 Configure settings above and click 'Process Stocks' to analyze")
        
        st.markdown("""
        ### How it works:
        
        1. **Select Stock List**: Choose from sample list, upload file, or enter manually
        2. **Configure Settings**: Set concurrent workers and timeout
        3. **Process**: Click 'Process Stocks' to analyze all stocks
        4. **Review Results**: View selected stocks, visualizations, and export data
        
        ### Selection Criteria:
        
        A stock is **SELECTED** if:
        - It has fallen **25% or more** from its 52-week high
        - Formula: `(Current Price - 52W High) / 52W High × 100 ≤ -25%`
        
        ### Features:
        
        - ✅ Concurrent processing for fast results
        - ✅ Automatic retry on failures
        - ✅ Detailed visualizations
        - ✅ Export to CSV/JSON
        - ✅ Individual stock charts
        """)

elif view_option == "🎨 Drawing Generator":
    # Drawing Generator - Auto-generate TradingView drawing instructions
    st.markdown("### 🎨 Auto Drawing Generator")
    st.markdown("Generate TradingView drawing instructions from price data analysis")
    
    st.markdown("---")
    
    # Configuration Section
    col1, col2, col3 = st.columns(3)
    
    with col1:
        symbol_input = st.text_input(
            "Stock Symbol",
            value="AAPL",
            help="Enter stock symbol (e.g., AAPL, RELIANCE.NS, TCS.NS)"
        )
    
    with col2:
        timeframe = st.selectbox(
            "Timeframe",
            options=["1m", "5m", "15m", "1h", "1d", "1wk", "1mo"],
            index=4,  # Default to 1d
            help="Chart timeframe"
        )
    
    with col3:
        period = st.selectbox(
            "Period",
            options=["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y"],
            index=5,  # Default to 1y
            help="Data period to analyze"
        )
    
    # Task Selection
    st.markdown("#### 📋 Select Analysis Tasks")
    
    # Info about LLM-powered detection
    st.info("""
    🤖 **AI-Powered Detection**: This tool uses advanced LLM (Large Language Model) analysis to detect patterns, 
    zones, and indicators with high accuracy. The AI understands market context and provides confidence scores 
    for each detection.
    """)
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        task_zones = st.checkbox("Supply/Demand Zones", value=True)
        task_patterns = st.checkbox("Candlestick Patterns", value=True)
    
    with col2:
        task_bollinger = st.checkbox("Bollinger Bands", value=False)
        task_rsi = st.checkbox("RSI Signals", value=True)
    
    with col3:
        task_macd = st.checkbox("MACD Crossovers", value=True)
        task_levels = st.checkbox("Key Levels", value=True)
    
    # Generate Button
    st.markdown("---")
    
    if st.button("🚀 Generate Drawings (AI-Powered)", type="primary", use_container_width=True):
        # Collect selected tasks
        tasks = []
        if task_zones:
            tasks.append("zones")
        if task_patterns:
            tasks.append("patterns")
        if task_bollinger:
            tasks.append("bollinger")
        if task_rsi:
            tasks.append("rsi")
        if task_macd:
            tasks.append("macd")
        if task_levels:
            tasks.append("levels")
        
        if not tasks:
            st.error("❌ Please select at least one analysis task")
        else:
            with st.spinner(f"🤖 Analyzing {symbol_input} with AI (LLM-powered detection)..."):
                try:
                    # Use LLM-powered detection instead of logic-based
                    from drawing_instruction.llm_drawing_generator import generate_drawings_with_llm
                    
                    # API configuration for external data source
                    api_config = {
                        'base_url': 'http://192.168.0.126:8000',
                        'from_date': '2025-01-01',
                        'to_date': '2026-03-03',
                        'market': 'stocks'
                    }
                    
                    result = generate_drawings_with_llm(
                        symbol=symbol_input,
                        timeframe=timeframe,
                        use_api=True,
                        api_config=api_config
                    )
                    
                    if result.get('error'):
                        st.error(f"❌ Error: {result['error']}")
                    else:
                        st.success(f"✅ Successfully generated {result['total_drawings']} drawing instructions!")
                        
                        # Store result in session state
                        st.session_state.drawing_result = result
                        
                        # Display Statistics
                        st.markdown("#### 📊 Generation Statistics")
                        
                        # Count different types
                        counts = {
                            'zones': 0,
                            'patterns': 0,
                            'indicators': 0,
                            'levels': 0
                        }
                        
                        for drawing in result['drawings']:
                            dtype = drawing.get('type', '')
                            
                            if dtype == 'LineToolRectangle':
                                counts['zones'] += 1
                            elif dtype == 'LineToolNote':
                                # Check if it's a pattern by looking at the text
                                text = drawing.get('state', {}).get('text', '')
                                pattern_keywords = [
                                    'engulfing', 'doji', 'hammer', 'star', 'shooting',
                                    'hanging', 'soldiers', 'crows', 'piercing', 'cloud',
                                    'harami', 'tweezer', 'dragonfly', 'gravestone'
                                ]
                                
                                if any(pattern in text.lower() for pattern in pattern_keywords):
                                    counts['patterns'] += 1
                                else:
                                    counts['indicators'] += 1
                            elif dtype == 'LineToolHorzLine':
                                counts['levels'] += 1
                            elif dtype == 'LineToolTrendLine':
                                counts['indicators'] += 1
                            else:
                                counts['indicators'] += 1
                        
                        col1, col2, col3, col4, col5 = st.columns(5)
                        
                        with col1:
                            st.metric("Total Drawings", result['total_drawings'])
                        with col2:
                            st.metric("Zones", counts['zones'])
                        with col3:
                            st.metric("Patterns", counts['patterns'])
                        with col4:
                            st.metric("Indicators", counts['indicators'])
                        with col5:
                            st.metric("Key Levels", counts['levels'])
                
                except Exception as e:
                    st.error(f"❌ Error: {str(e)}")
                    import traceback
                    st.code(traceback.format_exc())
    
    # Display Results if available
    if hasattr(st.session_state, 'drawing_result') and st.session_state.drawing_result:
        result = st.session_state.drawing_result
        
        st.markdown("---")
        st.markdown("#### 📄 Generated JSON")
        
        # Tabs for different views
        tab1, tab2, tab3 = st.tabs(["📊 Summary", "📝 JSON Output", "💾 Download"])
        
        with tab1:
            st.markdown("##### Drawing Instructions Summary")
            
            for idx, drawing in enumerate(result['drawings'][:10], 1):  # Show first 10
                with st.expander(f"{idx}. {drawing['type']} - {drawing.get('state', {}).get('text', 'N/A')}"):
                    st.json(drawing)
            
            if len(result['drawings']) > 10:
                st.info(f"Showing first 10 of {len(result['drawings'])} drawings. Download JSON to see all.")
        
        with tab2:
            # Create columns for header and copy button
            col1, col2 = st.columns([5, 1])
            
            with col1:
                st.markdown("##### 📝 Complete JSON Output")
            
            with col2:
                # Prepare JSON string
                json_str_for_copy = json.dumps(result, indent=2)
                
                # Copy button with custom HTML/JS for reliable clipboard access
                copy_button_html = f"""
                <div style="text-align: right;">
                    <button onclick="copyToClipboard()" style="
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        color: white;
                        border: none;
                        padding: 0.5rem 1rem;
                        font-weight: 600;
                        border-radius: 0.5rem;
                        cursor: pointer;
                        box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3);
                        font-size: 14px;
                    ">
                        📋 Copy JSON
                    </button>
                    <div id="copyStatus" style="
                        margin-top: 5px;
                        font-size: 12px;
                        color: #10b981;
                        display: none;
                    ">
                        ✅ Copied!
                    </div>
                </div>
                
                <script>
                const jsonData = {json.dumps(json_str_for_copy)};
                
                function copyToClipboard() {{
                    // Try modern clipboard API first
                    if (navigator.clipboard && navigator.clipboard.writeText) {{
                        navigator.clipboard.writeText(jsonData).then(function() {{
                            showCopyStatus();
                        }}, function(err) {{
                            // Fallback to textarea method
                            fallbackCopy();
                        }});
                    }} else {{
                        // Fallback for older browsers
                        fallbackCopy();
                    }}
                }}
                
                function fallbackCopy() {{
                    const textarea = document.createElement('textarea');
                    textarea.value = jsonData;
                    textarea.style.position = 'fixed';
                    textarea.style.opacity = '0';
                    document.body.appendChild(textarea);
                    textarea.select();
                    
                    try {{
                        document.execCommand('copy');
                        showCopyStatus();
                    }} catch (err) {{
                        console.error('Fallback copy failed:', err);
                        alert('Copy failed. Please copy manually from the JSON display below.');
                    }}
                    
                    document.body.removeChild(textarea);
                }}
                
                function showCopyStatus() {{
                    const status = document.getElementById('copyStatus');
                    status.style.display = 'block';
                    setTimeout(function() {{
                        status.style.display = 'none';
                    }}, 2000);
                }}
                </script>
                """
                
                components.html(copy_button_html, height=80)
            
            st.markdown("---")
            
            # Display JSON
            st.json(result)
        
        with tab3:
            # Download JSON
            json_str = json.dumps(result, indent=2)
            st.download_button(
                label="💾 Download JSON",
                data=json_str,
                file_name=f"drawings_{result['symbol']}_{timeframe}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json",
                use_container_width=True
            )
            
            st.markdown("---")
            st.markdown("##### 📖 How to Use")
            st.info("""
            **Using the Generated JSON:**
            
            1. **Download the JSON** file using the button above
            2. **Import into TradingView** - Compatible with TradingView's drawing format
            3. **Use with Trading Bots** that accept drawing instructions
            4. **Integrate with your own tools** via the JSON format
            
            **JSON Structure (TradingView Compatible):**
            - `symbol`: Stock symbol analyzed
            - `total_drawings`: Number of drawing instructions
            - `drawings`: Array of drawing objects with:
              - `id`: Unique 6-character identifier
              - `type`: Drawing tool type (LineToolRectangle, LineToolNote, etc.)
              - `state`: Visual properties (colors, text, style, intervals)
              - `points`: Price and timestamp coordinates with offset
              - `zorder`: Layer ordering
              - `linkKey`: Unique link identifier
              - `ownerSource`: Source identifier
            """)

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
