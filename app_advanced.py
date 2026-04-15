# -*- coding: utf-8 -*-
#streamlit run app_advanced.py --server.address=0.0.0.0 --server.port=8501
# ngrok config add-authtoken 36bmLDf1FVuILZCpcmXzY6x9TjC_3d1YjRnaX4wD2eFZrwH7f

import streamlit as st
import streamlit.components.v1 as components
from agent1 import agent, ConversationState, ToolResponse, agent_system_prompt
from datetime import datetime
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from langsmith import traceable
import re
import os
import time
import json
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart, SystemPromptPart
from utils.option_chain_analyzer import get_option_chain_analysis as fetch_option_chain, _clean_symbol_for_nse

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

# ── LangSmith initialisation (once per process, not per Streamlit rerun) ──
if "langsmith_initialised" not in st.session_state:
    from langsmith.integrations.otel import configure as _ls_configure
    os.environ.setdefault("LANGSMITH_API_KEY", os.getenv("LANGSMITH_API_KEY", ""))
    os.environ.setdefault("LANGSMITH_PROJECT", os.getenv("LANGSMITH_PROJECT", "trader_agent"))
    os.environ.setdefault("LANGSMITH_ENDPOINT", os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"))
    os.environ.setdefault("LANGSMITH_TRACING", os.getenv("LANGSMITH_TRACING", "true"))
    _ls_configure(project_name=os.getenv("LANGSMITH_PROJECT"))
    print(f"🚀 LangSmith configured — project: {os.getenv('LANGSMITH_PROJECT')}")
    st.session_state.langsmith_initialised = True

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

    /* Remove Streamlit default top padding */
    .block-container {
        padding-top: 3rem !important;
    }
    header[data-testid="stHeader"] {
        height: 2.5rem !important;
        min-height: 0 !important;
    }

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
        background: #9EF04D;
        padding: 1.3rem 3rem;
        border-radius: 1rem;
        text-align: center;
        margin-bottom: 2rem;
        box-shadow: 0 10px 40px rgba(116, 229, 4, 0.3);
    }
    
    .hero-title {
        font-size: 2.0rem;
        font-weight: 700;
        margin-bottom: 0.5rem;
        color: #222222;
    }
    
    .hero-subtitle {
        font-size: 1.2rem;
        color: #525252;
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
if 'pending_user_input' not in st.session_state:
    st.session_state.pending_user_input = None
if 'is_processing' not in st.session_state:
    st.session_state.is_processing = False



# Debug: Print current state
print(f"📊 Session state - Messages: {len(st.session_state.messages)}, Stock: {st.session_state.current_stock}")

# Sidebar
with st.sidebar:
    # Always use the dark logo regardless of theme
    import base64

    def img_to_base64(path):
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()

    try:
        dark_b64 = img_to_base64("static/tradingwize-logo-dark.png")
        st.markdown(f"""
        <style>
            .sidebar-logo img {{ max-width: 270px; width: 100%; height: auto; margin-bottom: 0.25rem; border-radius: 8px; mix-blend-mode: screen; }}
        </style>
        <div class="sidebar-logo">
            <img src="data:image/png;base64,{dark_b64}" />
        </div>
        """, unsafe_allow_html=True)
    except Exception as e:
        print(f"Logo load error: {e}")

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
                current_view = st.session_state.get("view_selector", "🏦 Fundamental Analysis")
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
    
    # View Navigation
    st.markdown("""
    <style>
        /* Style the sidebar radio buttons as pill-like nav items */
        div[data-testid="stSidebar"] div[role="radiogroup"] {
            gap: 2px !important;
        }
        div[data-testid="stSidebar"] div[role="radiogroup"] label {
            padding: 6px 10px !important;
            border-radius: 8px !important;
            transition: all 0.2s ease !important;
            font-size: 0.92rem !important;
        }
        div[data-testid="stSidebar"] div[role="radiogroup"] label:hover {
            background-color: rgba(116, 229, 4, 0.1) !important;
        }
        div[data-testid="stSidebar"] div[role="radiogroup"] label[data-checked="true"],
        div[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) {
            background: linear-gradient(135deg, rgba(116, 229, 4, 0.15), rgba(116, 229, 4, 0.05)) !important;
            border-left: 3px solid #74e504 !important;
        }
    </style>
    """, unsafe_allow_html=True)
    st.subheader("🧭 Navigate")

    # Build view options with distinctive emojis
    view_options = [
        "🏦 Fundamental Analysis",
        "📈 Data Dashboard"
    ]

    # Add Presentation Viewer if PPT was generated
    if hasattr(st.session_state, 'ppt_path') and st.session_state.ppt_path:
        view_options.append("📖 Presentation Viewer")

    # Add Drawing Generator (always available)
    view_options.append("🖊️ Drawing Generator")

    # Add Bulk Stock Analyzer
    view_options.append("⚡ Bulk Stock Analyzer")

    # Add System Info at the end
    view_options.append("⚙️ System Info")
    
    view_option = st.radio(
        "Select View",
        view_options,
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

# Main content area - render based on sidebar selection
view_option = st.session_state.get("view_selector", "🏦 Fundamental Analysis")

if view_option == "🏦 Fundamental Analysis":
    # ── Clean CSS: hide the border on st.container(height=...) so chat looks seamless ──
    st.markdown("""
    <style>
        /* Remove the default border/outline Streamlit adds to height-constrained containers */
        div[data-testid="stVerticalBlockBorderWrapper"]:has(> div[style*="overflow"]) {
            border: none !important;
            box-shadow: none !important;
            outline: none !important;
        }
    </style>
    """, unsafe_allow_html=True)

    # Fundamental Analysis - tabs for Chat, Sentiment, and Trade Ideas
    fund_tab1, fund_tab2, fund_tab3, fund_tab4, fund_tab5 = st.tabs(["💬 Chat", "📈 Sentiment Analysis", "📊 Trade Ideas", "🤖 FinRobot Agent", "📊 Option Chain"])

    with fund_tab1:
        # Initial state: show hero + welcome, no fixed-height container
        # After chat starts: use height=650 scrollable container
        has_messages = len(st.session_state.messages) > 0

        if not has_messages:
            # Hero section — only on initial state
            st.markdown("""
            <div class="hero-section">
                <div class="hero-title">AI-Powered Stock Analysis</div>
                <div class="hero-subtitle">
                    Get comprehensive insights with real-time data and expert analysis
                </div>
            </div>
            """, unsafe_allow_html=True)

            st.markdown("""
            <div style="
                background-color: #E1FDC6;
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

        if has_messages:
            # Scrollable chat container — only this area scrolls, tabs stay fixed
            chat_container = st.container(height=650, border=False)
        else:
            # No fixed height at initial state so text input is visible
            chat_container = st.container(border=False)

        with chat_container:
            # Only render messages when they exist (welcome already shown above)
            if not has_messages:
                pass  # welcome already rendered above

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
                        if stripped.startswith(('📊', '🏢', '📋', '💰', '📈', '📊', '🏆', '🎯', '📰', '👨‍💼', '🦈', '✅', '👋', '🤖', '🔍', '🎤', '🔮', '❌', '⏰', '🚀')):
                            if in_list:
                                html_lines.append('</ul>')
                                in_list = False
                            html_lines.append(f'<h3 style="margin: 0.8rem 0 0.4rem 0; font-size: 1.1rem; font-weight: 600; line-height: 1.3; word-wrap: break-word; overflow-wrap: break-word; hyphens: auto;">{stripped}</h3>')

                        # Subsection headers - bold-only lines
                        elif re.match(r'^<strong>[^<]+</strong>:?$', stripped):
                            if in_list:
                                html_lines.append('</ul>')
                                in_list = False
                            html_lines.append(f'<p style="margin: 0.6rem 0 0.2rem 0; font-weight: 700; font-size: 1rem; line-height: 1.35; word-wrap: break-word; overflow-wrap: break-word; hyphens: auto;">{stripped}</p>')

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

            # Auto-scroll: use components.html INSIDE the chat container so
            # the iframe shares the same scrollable parent. The script walks up
            # to find the scrollable ancestor and scrolls it.
            import streamlit.components.v1 as _components
            _last_msg = st.session_state.messages[-1] if st.session_state.messages else None
            _is_long_response = (
                _last_msg
                and _last_msg["role"] == "assistant"
                and len(_last_msg.get("content", "")) > 800
            )
            _scroll_mode = "top_of_last" if _is_long_response else "bottom"
            # Use message count as a cache-buster so the script re-executes on every rerun
            _msg_count = len(st.session_state.messages)
            _components.html(f"""
            <div id="autoscroll-anchor-{_msg_count}"></div>
            <script>
            (function() {{
                var mode = "{_scroll_mode}";
                function doScroll() {{
                    // Walk up from this iframe to find the scrollable container
                    var el = window.frameElement;
                    if (!el) return;
                    var scrollable = null;
                    var node = el.parentElement;
                    while (node) {{
                        if (node.scrollHeight > node.clientHeight + 50) {{
                            var style = window.getComputedStyle(node);
                            var ov = style.overflowY;
                            if (ov === 'auto' || ov === 'scroll') {{
                                scrollable = node;
                                break;
                            }}
                        }}
                        node = node.parentElement;
                    }}
                    if (!scrollable) return;

                    if (mode === "top_of_last") {{
                        // For long responses: find the last assistant message and
                        // scroll so its TOP is at the top of the visible area
                        var msgs = scrollable.querySelectorAll('.assistant-message-container');
                        if (msgs.length > 0) {{
                            var lastMsg = msgs[msgs.length - 1];
                            scrollable.scrollTop = lastMsg.offsetTop - scrollable.offsetTop - 10;
                            return;
                        }}
                    }}
                    // Default: scroll to bottom so latest message is visible
                    scrollable.scrollTop = scrollable.scrollHeight;
                }}
                // Multiple attempts to handle Streamlit's async rendering
                setTimeout(doScroll, 100);
                setTimeout(doScroll, 300);
                setTimeout(doScroll, 600);
            }})();
            </script>
            """, height=0)

        # Chat input - ALWAYS visible at bottom (outside chat_container)
        # User can always type, but sending is silently ignored while agent is busy
        _is_busy = st.session_state.is_processing or st.session_state.pending_user_input is not None
        user_input = st.chat_input(
            "⏳ Please wait, analyzing..." if _is_busy else "💬 Type your message here... (e.g., 'analyze ONGC' or 'tell me about reliance')",
            key="chat_input_main",
        )

        if user_input and not _is_busy:
            # Store user message and rerun so it renders before processing
            st.session_state.messages.append({"role": "user", "content": user_input})
            st.session_state.pending_user_input = user_input
            st.rerun()

        # Process pending input (after rerun so user message is visible)
        if st.session_state.pending_user_input:
            user_input = st.session_state.pending_user_input
            st.session_state.pending_user_input = None
            st.session_state.is_processing = True

            import time as _timer
            _request_start = _timer.time()

            print(f"\n{'='*60}")
            print(f"📝 User input: {user_input}")
            print(f"{'='*60}")

            # Ensure session state is properly initialized
            if 'message_history' not in st.session_state:
                st.session_state.message_history = []  # system prompt managed by agent internally
            if 'deps' not in st.session_state:
                st.session_state.deps = ConversationState()

            with st.spinner("🤔 Analyzing..."):
                @traceable(name="pydantic_ai_agent_run")
                async def run_agent_async(user_input, message_history, deps):
                    """Async wrapper for agent.run"""
                    # Pre-check: handle simple greetings without calling the LLM
                    # This avoids output validation failures with weaker models
                    _greeting_words = {"hi", "hello", "hey", "hola", "namaste", "good morning", "good evening", "good afternoon", "howdy", "greetings", "sup", "yo"}
                    _input_clean = user_input.strip().lower().rstrip("!.,?")
                    _is_simple_greeting = _input_clean in _greeting_words
                    _has_stock_loaded = bool(getattr(deps, 'company_data', None))

                    if _is_simple_greeting and not _has_stock_loaded:
                        print(f"👋 Pre-check: greeting detected, returning directly without LLM call")
                        greeting_response = """Hello! 👋 I'm your AI stock analyst.

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
                        deps.last_validation_response = greeting_response
                        # Return a minimal result-like object
                        class _GreetingResult:
                            output = greeting_response
                            data = greeting_response
                            def new_messages(self): return []
                        return _GreetingResult(), None

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

                            # Clear cached responses from previous turns so follow-up questions
                            # (e.g. handle_trader_question) use result.output instead of stale cache
                            deps.last_analysis_response = None
                            deps.last_validation_response = None

                            # Reset analysis state when user wants to analyze a new/different stock
                            import re as _re_reset
                            _input_stripped = user_input.strip().lower()
                            _is_number_selection = _input_stripped.isdigit() or bool(_re_reset.match(r'^(analyze|select|choose|pick|option)\s*\d+', _input_stripped))
                            _has_pending = bool(getattr(deps, 'pending_variants', None))
                            _is_new_stock_request = bool(_re_reset.search(r'(analy[sz]e|tell me about|check|review|look at|search|find|show)\s+', _input_stripped))

                            if (_is_number_selection and _has_pending) or (_is_new_stock_request and getattr(deps, 'analysis_complete', False)):
                                deps.analysis_complete = False
                                deps.company_data = None
                                deps.stock_symbol = None
                                deps.stock_name = None
                                deps.last_analysis_response = None
                                deps.report_generated = False
                                # Clear message history so the LLM doesn't see the old analysis
                                # and skip tool calls for the new stock
                                message_history = []
                                st.session_state.message_history = []
                                print(f"🔄 Reset analysis state and history for new stock request: '{user_input.strip()}'")
                        
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

                                # FAST RECOVERY: Check if the tool already generated and cached
                                # the response before the timeout. If so, return it immediately
                                # instead of re-running the agent.
                                _cached_analysis = getattr(deps, 'last_analysis_response', None)
                                _cached_validation = getattr(deps, 'last_validation_response', None)

                                if _cached_analysis:
                                    print(f"✅ FAST RECOVERY: Analysis already cached ({len(_cached_analysis)} chars) — returning immediately")
                                    st.session_state.deps = deps
                                    # Manually record the exchange in message history
                                    st.session_state.message_history.extend([
                                        ModelRequest(parts=[UserPromptPart(content=user_input)]),
                                        ModelResponse(parts=[TextPart(content=_cached_analysis)]),
                                    ])
                                    # Create a simple result-like object so downstream code works
                                    class _CachedResult:
                                        output = _cached_analysis
                                        data = _cached_analysis
                                        def new_messages(self): return []
                                    return _CachedResult(), None

                                if _cached_validation:
                                    print(f"✅ FAST RECOVERY: Validation already cached ({len(_cached_validation)} chars) — returning immediately")
                                    st.session_state.deps = deps
                                    st.session_state.message_history.extend([
                                        ModelRequest(parts=[UserPromptPart(content=user_input)]),
                                        ModelResponse(parts=[TextPart(content=_cached_validation)]),
                                    ])
                                    class _CachedResult:
                                        output = _cached_validation
                                        data = _cached_validation
                                        def new_messages(self): return []
                                    return _CachedResult(), None

                                # No cached response available — genuine timeout with no result
                                if attempt < max_retries - 1:
                                    print(f"⚠️ Attempt {attempt + 1} timed out after {elapsed_time:.2f}s, retrying...")
                                    continue
                                else:
                                    return None, f"Request timed out after {elapsed_time:.0f} seconds. Please try again."
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
                        # Check if this is a non-stock query (greeting, casual chat, etc.)
                        # If so, respond directly instead of hitting the database
                        _greeting_words = {"hi", "hello", "hey", "hola", "namaste", "good morning", "good evening", "good afternoon", "howdy", "greetings", "sup", "yo"}
                        _input_lower = user_input.strip().lower().rstrip("!.,?")
                        _is_greeting = _input_lower in _greeting_words or (_input_lower.split()[0] in _greeting_words if _input_lower else False)
                        _has_stock_context = bool(getattr(st.session_state, 'current_stock', None)) or any(
                            kw in _input_lower for kw in [".ns", ".bs", "stock", "share", "analyze", "analysis", "company"]
                        )

                        if not _has_stock_context:
                            if _is_greeting:
                                # Simple greeting — no need to hit the database
                                print(f"👋 Greeting detected, returning friendly response directly")
                                response = """Hello! 👋 I'm your AI stock analyst.

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
                            else:
                                # Non-stock casual message — respond helpfully without DB
                                print(f"💬 Non-stock query detected, returning helpful response")
                                response = """I'm your AI stock analyst! 📊

I can analyze any stock for you. Just tell me a **company name** or **ticker symbol** and I'll provide a comprehensive analysis.

**Examples:**
• "Reliance" or "RELIANCE.NS"
• "Tata Motors" or "TATAMOTORS.NS"
• "Infosys" or "INFY.NS"

What stock would you like to analyze?"""
                        else:
                            # Stock-related query failed — try to retrieve from database
                            print(f"🔄 Validation failed for stock query, attempting to retrieve from database...")
                            try:
                                from database_utility.database import StockDatabase

                                db = StockDatabase()
                                if db.connect():
                                    latest = db.get_latest_analysis()

                                    if latest and latest.get('formatted_report'):
                                        print(f"✅ Retrieved analysis from database: {len(latest['formatted_report'])} chars")
                                        response = latest['formatted_report']

                                        if latest.get('stock_symbol'):
                                            st.session_state.current_stock = latest.get('stock_name', latest.get('stock_symbol'))

                                            if not st.session_state.deps.company_data:
                                                from models import CompanyData
                                                st.session_state.deps.company_data = CompanyData(
                                                    symbol=latest.get('stock_symbol'),
                                                    name=latest.get('stock_name', latest.get('stock_symbol')),
                                                    current_price=0,
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

**What you can do:**
• Try your request again with a simpler query
• Ask for specific information about the stock
• Try again in a few minutes"""

                                    db.disconnect()
                                else:
                                    print(f"❌ Could not connect to database")
                                    response = """❌ **System Error**

Could not retrieve analysis results. Please try your request again."""

                            except Exception as db_error:
                                print(f"❌ Database retrieval error: {db_error}")
                                response = """❌ **Analysis Retrieval Failed**

The system couldn't display the analysis properly. Please try your request again."""
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
                elif isinstance(response, str) and len(response) > 200:
                    # Fallback: extract stock name from response if deps don't have it
                    import re as _re_extract
                    _stock_match = _re_extract.search(r'Stock Analysis\s*[–\-]\s*(.+?)\s*\(', response)
                    if _stock_match:
                        st.session_state.current_stock = _stock_match.group(1).strip()
                        print(f"📊 Extracted stock name from response: {st.session_state.current_stock}")
                if st.session_state.deps.company_data:
                    st.session_state.company_data = st.session_state.deps.company_data
        
            # DISABLED: Final formatting check - format_data_for_report already produces clean output
            # debug_response_formatting(response, "BEFORE SAVING TO SESSION")
        
            # DISABLED: Apply one final formatting pass - causes formatting issues
            # final_response = streamlit_markdown_formatter(response)
            # debug_response_formatting(final_response, "FINAL FORMATTED RESPONSE")
        
            # Use response directly without additional formatting
            st.session_state.messages.append({"role": "assistant", "content": response})
            st.session_state.is_processing = False
            _elapsed = _timer.time() - _request_start
            if _elapsed >= 60:
                _mins = int(_elapsed // 60)
                _secs = _elapsed % 60
                print(f"⏱️ Total response time: {_mins}m {_secs:.1f}s")
            else:
                print(f"⏱️ Total response time: {_elapsed:.1f}s")
            print(f"💾 Message saved to session state")
            st.rerun()


    with fund_tab2:
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
                        subreddit_dist = reddit_data.get('subreddit_distribution')
                        if subreddit_dist and isinstance(subreddit_dist, dict):
                            st.markdown("<br>", unsafe_allow_html=True)
                            with st.expander("📊 Active Subreddits"):
                                subreddit_list = list(subreddit_dist.items())
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
            st.subheader("🔮 Future Outlook & News Analysis")
            st.caption("AI-powered analysis of future expectations from top financial sources")

            # Check if news analysis is already cached
            if 'news_analysis' not in st.session_state or st.session_state.get('news_analysis_stock') != stock_symbol:
                with st.spinner("🔍 Searching for latest news and analyst forecasts..."):
                    from tools import StockTools
                    import concurrent.futures

                    try:
                        # Run with a timeout so the UI doesn't hang forever
                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(
                                StockTools.get_stock_news_analysis,
                                stock_name,
                                5  # max_articles reduced from 10 to 5 for speed
                            )
                            news_result = future.result(timeout=90)  # 90s max

                        st.session_state.news_analysis = news_result
                        st.session_state.news_analysis_stock = stock_symbol
                    except concurrent.futures.TimeoutError:
                        st.warning("⏱️ News analysis timed out. Click Refresh to try again.")
                        news_result = None
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
    
            # ═══════════════════════════════════════════════════════
            # FII/DII INSTITUTIONAL SENTIMENT SECTION
            # ═══════════════════════════════════════════════════════
            st.divider()
            st.subheader("🏦 FII & DII Institutional Sentiment")
            st.caption("Track Foreign & Domestic Institutional buying/selling activity")

            fii_symbol = stock_symbol
            st.info(f"Analyzing institutional sentiment for: **{fii_symbol}**")

            # Cache key for this stock's FII/DII data
            fii_cache_key = f"fii_dii_{fii_symbol}"

            # Auto-run on first load, or re-run on button click
            run_fii = st.button("Fetch FII/DII Data", key="run_fii_dii", type="primary")
            auto_run = fii_cache_key not in st.session_state

            if run_fii or auto_run:
                cached_fii_val = None
                cached_dii_val = None
                if data.market_data:
                    cached_fii_val = data.market_data.fii_holding
                    cached_dii_val = data.market_data.dii_holding
                    # Normalize decimal to percentage
                    if cached_fii_val is not None and cached_fii_val < 1:
                        cached_fii_val = cached_fii_val * 100
                    if cached_dii_val is not None and cached_dii_val < 1:
                        cached_dii_val = cached_dii_val * 100

                with st.spinner("Fetching FII/DII shareholding pattern..."):
                    try:
                        from utils.fii_dii_analyzer import get_fii_dii_sentiment as compute_fii_dii
                        fii_result = compute_fii_dii(
                            symbol=fii_symbol,
                            company_name=stock_name,
                            cached_fii=float(cached_fii_val) if cached_fii_val is not None else None,
                            cached_dii=float(cached_dii_val) if cached_dii_val is not None else None,
                        )
                        st.session_state[fii_cache_key] = fii_result
                    except Exception as e:
                        st.error(f"FII/DII analysis failed: {e}")

            # Display cached result
            fii_result = st.session_state.get(fii_cache_key)

            if fii_result:
                # Recommendation banner
                rec_colors = {
                    "green":   ("#e8f5e9", "#2e7d32"),
                    "#4caf50": ("#f1f8e9", "#33691e"),
                    "gray":    ("#f5f5f5", "#424242"),
                    "orange":  ("#fff3e0", "#e65100"),
                    "red":     ("#ffebee", "#c62828"),
                }
                bg, fg = rec_colors.get(fii_result.recommendation_color, ("#f5f5f5", "#424242"))
                st.markdown(
                    f"<div style='background:{bg}; border-left:5px solid {fg}; "
                    f"padding:14px 18px; border-radius:6px; margin:12px 0;'>"
                    f"<div style='font-size:1.2em; font-weight:700; color:{fg};'>"
                    f"{fii_result.recommendation}</div>"
                    f"<div style='color:{fg}; margin-top:4px;'>"
                    f"Institutional Score: {fii_result.institutional_sentiment_score:.1f}/100 "
                    f"- {fii_result.sentiment_label}</div></div>",
                    unsafe_allow_html=True
                )

                # Metric cards
                m1, m2, m3, m4 = st.columns(4)
                with m1:
                    fii_delta = f"{fii_result.fii_change_1q:+.2f}pp" if fii_result.fii_change_1q is not None else None
                    st.metric("FII Holding", f"{fii_result.current_fii_pct:.2f}%", delta=fii_delta, delta_color="normal")
                with m2:
                    dii_delta = f"{fii_result.dii_change_1q:+.2f}pp" if fii_result.dii_change_1q is not None else None
                    st.metric("DII Holding", f"{fii_result.current_dii_pct:.2f}%", delta=dii_delta, delta_color="normal")
                with m3:
                    st.metric("Total Institutional", f"{fii_result.current_total_institutional:.2f}%")
                with m4:
                    st.metric("Inst. Score", f"{fii_result.institutional_sentiment_score:.1f}/100")

                # Trend labels
                t1, t2 = st.columns(2)
                def _trend_badge(trend):
                    colors = {
                        "Strongly Increasing": ("++", "green"), "Increasing": ("+", "#4caf50"),
                        "Stable": ("=", "gray"), "Decreasing": ("-", "orange"),
                        "Strongly Decreasing": ("--", "red"),
                    }
                    arrow, color = colors.get(trend, ("=", "gray"))
                    return f"<span style='color:{color}; font-weight:600;'>{arrow} {trend}</span>"

                with t1:
                    st.markdown(f"**FII Trend:** {_trend_badge(fii_result.fii_trend)}", unsafe_allow_html=True)
                    if fii_result.fii_change_4q is not None:
                        st.caption(f"4-quarter FII change: {fii_result.fii_change_4q:+.2f}pp")
                with t2:
                    st.markdown(f"**DII Trend:** {_trend_badge(fii_result.dii_trend)}", unsafe_allow_html=True)
                    if fii_result.dii_change_4q is not None:
                        st.caption(f"4-quarter DII change: {fii_result.dii_change_4q:+.2f}pp")

                # Quarterly trend chart
                if len(fii_result.quarterly_history) >= 2:
                    st.subheader("Quarterly Shareholding Trend")
                    quarters = [h.quarter for h in fii_result.quarterly_history]
                    fii_vals = [h.fii_pct for h in fii_result.quarterly_history]
                    dii_vals = [h.dii_pct for h in fii_result.quarterly_history]
                    total_vals = [round(f + d, 2) for f, d in zip(fii_vals, dii_vals)]

                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=quarters, y=fii_vals, mode="lines+markers", name="FII %",
                        line=dict(color="#1976d2", width=2.5), marker=dict(size=7),
                        hovertemplate="Quarter: %{x}<br>FII: %{y:.2f}%<extra></extra>"))
                    fig.add_trace(go.Scatter(x=quarters, y=dii_vals, mode="lines+markers", name="DII %",
                        line=dict(color="#388e3c", width=2.5), marker=dict(size=7),
                        hovertemplate="Quarter: %{x}<br>DII: %{y:.2f}%<extra></extra>"))
                    fig.add_trace(go.Scatter(x=quarters, y=total_vals, mode="lines", name="Total Inst. %",
                        line=dict(color="#f57c00", width=2, dash="dot"),
                        hovertemplate="Quarter: %{x}<br>Total: %{y:.2f}%<extra></extra>"))
                    fig.update_layout(
                        xaxis_title="Quarter", yaxis_title="Holding (%)",
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                        height=320, margin=dict(t=20, b=20, l=10, r=10),
                        hovermode="x unified", plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                    )
                    fig.update_yaxes(gridcolor="rgba(128,128,128,0.15)")
                    st.plotly_chart(fig, use_container_width=True)

                # Analysis reasoning
                st.subheader("Analysis")
                for reason in fii_result.reasoning:
                    st.info(f"  {reason}")

                # Explainer
                with st.expander("What is FII & DII? How to read this?"):
                    st.markdown("""
**FII - Foreign Institutional Investors**: Foreign funds, hedge funds, FPIs investing from abroad.
Rising FII % means foreign money flowing INTO this stock.

**DII - Domestic Institutional Investors**: Indian mutual funds, insurance companies (LIC), pension funds.
Rising DII % means domestic institutions are accumulating.

| Situation | What It Means |
|-----------|--------------|
| FII + DII both up | Strong bullish signal |
| FII up + DII down | Moderate bullish (foreign buying) |
| FII down + DII up | Could be contrarian opportunity |
| FII + DII both down | Bearish signal, avoid |

*FII/DII data updates quarterly. Source: screener.in shareholding pattern.*
                    """)

                st.caption(
                    f"Data source: {fii_result.data_source.replace('_', '.')} | "
                    f"Freshness: {fii_result.data_freshness} | "
                    f"Analyzed: {fii_result.timestamp.strftime('%d %b %Y %H:%M UTC')}"
                )

        else:
            st.info("Analyze a stock to see analytics")

    with fund_tab3:
        # Trade Ideas from TradingView — exact TradingView UI replica

        # Inject CSS that matches TradingView's actual card design
        st.markdown("""
        <style>
            /* ── TradingView Ideas Grid ── */
            .tv-grid {
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 20px;
                margin: 16px 0;
                align-items: start;
            }
            @media (max-width: 900px) {
                .tv-grid { grid-template-columns: repeat(2, 1fr); }
            }
            @media (max-width: 600px) {
                .tv-grid { grid-template-columns: 1fr; }
            }

            /* ── Card ── */
            .tv-card {
                background: #ffffff;
                border-radius: 8px;
                overflow: hidden;
                border: 1px solid #e0e3eb;
                transition: box-shadow 0.2s ease;
                cursor: pointer;
                display: flex;
                flex-direction: column;
            }
            .tv-card:hover {
                box-shadow: 0 2px 12px rgba(0, 0, 0, 0.12);
            }

            /* ── Chart Image — show full image, no crop ── */
            .tv-card-img-wrap {
                width: 100%;
                background: #ffffff;
                border-bottom: 1px solid #f0f3fa;
            }
            .tv-card-img {
                width: 100%;
                height: auto;
                display: block;
            }

            /* ── Card Body ── */
            .tv-card-body {
                padding: 12px 16px;
                flex: 1;
                display: flex;
                flex-direction: column;
                overflow: hidden;
            }

            /* ── Title ── */
            .tv-card-title {
                font-size: 15px;
                font-weight: 700;
                color: #131722;
                line-height: 1.35;
                margin: 0 0 6px 0;
                display: -webkit-box;
                -webkit-line-clamp: 2;
                -webkit-box-orient: vertical;
                overflow: hidden;
                min-height: 40px;
            }

            /* ── Description ── */
            .tv-card-desc {
                font-size: 13px;
                color: #787b86;
                line-height: 1.45;
                display: -webkit-box;
                -webkit-line-clamp: 2;
                -webkit-box-orient: vertical;
                overflow: hidden;
                margin: 0;
                flex: 1;
            }

            /* ── Footer (author + engagement) ── */
            .tv-card-footer {
                display: flex;
                align-items: center;
                justify-content: space-between;
                padding: 10px 16px;
                border-top: 1px solid #f0f3fa;
                font-size: 12px;
                color: #787b86;
                margin-top: auto;
            }
            .tv-card-author {
                display: flex;
                align-items: center;
                gap: 6px;
                color: #787b86;
            }
            .tv-card-author-name {
                font-weight: 500;
                color: #131722;
            }
            .tv-card-date {
                color: #9598a1;
            }
            .tv-card-engagement {
                display: flex;
                align-items: center;
                gap: 14px;
            }
            .tv-card-stat {
                display: flex;
                align-items: center;
                gap: 4px;
                color: #787b86;
            }
            .tv-card-stat svg {
                width: 16px;
                height: 16px;
                fill: #787b86;
            }
        </style>
        """, unsafe_allow_html=True)

        if st.session_state.company_data:
            data = st.session_state.company_data
            stock_symbol = data.symbol
            clean_symbol = stock_symbol.split('.')[0].upper()
            exchange = "NSE" if ".NS" in stock_symbol else "BSE"
            tradingview_url = f"https://www.tradingview.com/symbols/{exchange}-{clean_symbol}/ideas/"

            st.subheader(f"📊 Trade Ideas for {data.name}")
            st.caption(f"Top trading ideas for {clean_symbol}")

            # Check if trade ideas are cached in session
            cache_key = f"trade_ideas_{clean_symbol}"
            if cache_key not in st.session_state or st.session_state.get('trade_ideas_stock') != stock_symbol:
                with st.spinner("🔍 Fetching trade ideas from TradingView..."):
                    try:
                        from utils.tradingview_ideas_scraper import scrape_trade_ideas
                        ideas_result = scrape_trade_ideas(clean_symbol, exchange, 9)

                        st.session_state[cache_key] = ideas_result
                        st.session_state.trade_ideas_stock = stock_symbol
                    except Exception as e:
                        st.error(f"❌ Error fetching trade ideas: {e}")
                        ideas_result = None
            else:
                ideas_result = st.session_state[cache_key]

            if ideas_result and ideas_result.get('ideas'):
                ideas = ideas_result['ideas']
                # st.success(f"Found {len(ideas)} trade ideas from TradingView")

                # SVG icons matching TradingView's UI
                comment_svg = '<svg viewBox="0 0 18 18"><path d="M9 1C4.58 1 1 4.03 1 7.79c0 2.12 1.06 4.02 2.72 5.3L3 16l3.72-1.6C7.78 14.78 8.87 15 9 15c4.42 0 8-3.03 8-6.79S13.42 1 9 1z" fill="none" stroke="#787b86" stroke-width="1.2"/></svg>'
                boost_svg = '<svg viewBox="0 0 18 18"><path d="M9 2l2.09 4.26L16 6.97l-3.5 3.42.83 4.84L9 13.07l-4.33 2.16.83-4.84L2 6.97l4.91-.71L9 2z" fill="none" stroke="#787b86" stroke-width="1.2"/></svg>'

                # Build all cards as one HTML grid block
                cards_html = '<div class="tv-grid">'

                for idea in ideas:
                    title = idea.get('title', 'Untitled')[:90]
                    author = idea.get('author', 'Anonymous')
                    likes = idea.get('likes', '0')
                    time_posted = idea.get('time_posted', '')
                    description = idea.get('description', '')[:200]
                    image_url = idea.get('image_url', '')
                    idea_url = idea.get('idea_url', '#')

                    # Format time to match TradingView (e.g., "Mar 10" or "Nov 29, 2025")
                    display_date = ''
                    if time_posted:
                        if 'T' in time_posted:
                            try:
                                from datetime import datetime as _dt
                                dt = _dt.fromisoformat(time_posted.replace('Z', '+00:00'))
                                display_date = dt.strftime('%b %d')
                            except Exception:
                                display_date = time_posted
                        else:
                            display_date = time_posted

                    # Chart image or placeholder
                    has_image = image_url and 's3.tradingview.com' in image_url
                    if has_image:
                        img_block = f'<img class="tv-card-img" src="{image_url}" alt="{title}" loading="lazy" onerror="this.parentElement.innerHTML=\'<div style=padding:40px;text-align:center;color:#9598a1>Chart unavailable</div>\'">'
                    else:
                        img_block = '<div style="width:100%;aspect-ratio:16/10;background:#f0f3fa;display:flex;align-items:center;justify-content:center;color:#9598a1;font-size:14px;">Chart unavailable</div>'

                    # Escape HTML in user content
                    import html as _html_mod
                    safe_title = _html_mod.escape(title)
                    safe_desc = _html_mod.escape(description)
                    safe_author = _html_mod.escape(author)

                    cards_html += f'''
                    <a href="{idea_url}" target="_blank" style="text-decoration:none;color:inherit;">
                        <div class="tv-card">
                            <div class="tv-card-img-wrap">
                                {img_block}
                            </div>
                            <div class="tv-card-body">
                                <div class="tv-card-title">{safe_title}</div>
                                <div class="tv-card-desc">{safe_desc}</div>
                            </div>
                            <div class="tv-card-footer">
                                <div class="tv-card-author">
                                    <span>by</span>
                                    <span class="tv-card-author-name">{safe_author}</span>
                                    <span class="tv-card-date">{display_date}</span>
                                </div>
                                <div class="tv-card-engagement">
                                    <span class="tv-card-stat">{comment_svg}</span>
                                    <span class="tv-card-stat">{boost_svg} {likes}</span>
                                </div>
                            </div>
                        </div>
                    </a>'''

                cards_html += '</div>'
                st.markdown(cards_html, unsafe_allow_html=True)

                st.markdown("<br>", unsafe_allow_html=True)

                # Footer: View all + Refresh
                foot_col1, foot_col2 = st.columns(2)
                with foot_col1:
                    st.link_button(
                        f"📊 View all ideas for {clean_symbol} on TradingView",
                        tradingview_url,
                        use_container_width=True
                    )
                with foot_col2:
                    if st.button("🔄 Refresh Trade Ideas", key="refresh_trade_ideas", use_container_width=True):
                        if cache_key in st.session_state:
                            del st.session_state[cache_key]
                        if 'trade_ideas_stock' in st.session_state:
                            del st.session_state.trade_ideas_stock
                        try:
                            from utils.tradingview_ideas_scraper import clear_cache
                            clear_cache(clean_symbol, exchange)
                        except Exception:
                            pass
                        st.rerun()

            elif ideas_result and ideas_result.get('error'):
                st.warning(f"⚠️ Unable to fetch trade ideas: {ideas_result['error']}")
                st.link_button(
                    f"📊 View ideas on TradingView directly",
                    tradingview_url,
                    use_container_width=True
                )
            else:
                st.info("No trade ideas found for this stock on TradingView.")
                st.link_button(
                    f"📊 Check TradingView for {clean_symbol}",
                    tradingview_url,
                    use_container_width=True
                )
        else:
            st.info("📊 Analyze a stock to see trade ideas from TradingView")

    with fund_tab4:
        # FinRobot Agent — separate chat for the three-agent deep analysis pipeline
        st.markdown("### FinRobot Deep Analysis Agent")
        st.caption("Three-agent pipeline: Fundamental Agent + Sentiment Agent + Reasoning Agent")

        # Initialize FinRobot chat state
        if 'finrobot_messages' not in st.session_state:
            st.session_state.finrobot_messages = []

        # Check if a stock is loaded
        _fr_company_data = st.session_state.get('deps')
        _fr_company_data = getattr(_fr_company_data, 'company_data', None) if _fr_company_data else None
        _fr_stock_name = getattr(_fr_company_data, 'name', None) if _fr_company_data else None
        _fr_stock_symbol = getattr(_fr_company_data, 'symbol', None) if _fr_company_data else None

        if _fr_stock_name:
            st.markdown(f"**Currently loaded:** {_fr_stock_name} (`{_fr_stock_symbol}`)")
        else:
            st.info("Analyze a stock first in the **Chat** tab, then come back here to run FinRobot deep analysis.")

        # Display existing FinRobot report summary if available
        _fr_report = st.session_state.get(f"finrobot_report_{_fr_stock_symbol}")
        if not _fr_report and _fr_company_data:
            _fr_report = getattr(_fr_company_data, 'finrobot_report', None)
            if _fr_report:
                st.session_state[f"finrobot_report_{_fr_stock_symbol}"] = _fr_report

        if _fr_report and _fr_report.reasoning:
            _r = _fr_report.reasoning
            _rec_color = {"Strong Buy": "#10b981", "Buy": "#34d399", "Hold": "#fbbf24",
                          "Sell": "#f87171", "Strong Sell": "#ef4444"}.get(_r.recommendation, "#94a3b8")
            st.markdown(f"""
            <div style="display:flex; align-items:center; gap:1rem; margin-bottom:1rem;">
                <div style="display:inline-block; background:{_rec_color}22; border:2px solid {_rec_color};
                            border-radius:0.5rem; padding:0.4rem 1rem; font-size:1.1rem;
                            font-weight:700; color:{_rec_color};">
                    {_r.recommendation}
                </div>
                <span style="color:#666;">Confidence: <b>{_r.confidence}</b> &nbsp;|&nbsp;
                Score: <b>{_r.final_score:.1f}/100</b> &nbsp;|&nbsp;
                Horizon: <b>{_r.time_horizon}</b></span>
            </div>
            """, unsafe_allow_html=True)

            # Show scores
            if _fr_report.fundamental:
                _f = _fr_report.fundamental
                _sc1, _sc2, _sc3, _sc4 = st.columns(4)
                _sc1.metric("Overall", f"{_f.overall_fundamental_score:.1f}")
                _sc2.metric("Valuation", f"{_f.valuation_score:.1f}")
                _sc3.metric("Health", f"{_f.financial_health_score:.1f}")
                _sc4.metric("Growth", f"{_f.growth_score:.1f}")

            st.markdown("---")

        # Chat messages display
        for msg in st.session_state.finrobot_messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        # Chat input
        fr_user_input = st.chat_input("Ask FinRobot to analyze (e.g. 'Run deep analysis', 'What's the recommendation?')", key="finrobot_chat_input")

        if fr_user_input:
            # Add user message
            st.session_state.finrobot_messages.append({"role": "user", "content": fr_user_input})
            with st.chat_message("user"):
                st.markdown(fr_user_input)

            # Process with FinRobot
            with st.chat_message("assistant"):
                with st.spinner("FinRobot pipeline running..."):
                    try:
                        import asyncio
                        from finrobot.chat_agent import run_finrobot_chat

                        # Pass existing sentiment data from session as fallback
                        _fr_session_sentiment = st.session_state.get('sentiment_data', {})
                        # Pass full history excluding the just-appended user message
                        _fr_history = st.session_state.finrobot_messages[:-1]

                        result = asyncio.run(run_finrobot_chat(
                            fr_user_input,
                            _fr_company_data,
                            session_sentiment=_fr_session_sentiment,
                            message_history=_fr_history,
                        ))
                        fr_response = result["response"]
                        fr_report = result.get("report")

                        # Cache report
                        if fr_report and _fr_stock_symbol:
                            st.session_state[f"finrobot_report_{_fr_stock_symbol}"] = fr_report
                            if _fr_company_data:
                                _fr_company_data.finrobot_report = fr_report

                    except Exception as e:
                        fr_response = f"FinRobot pipeline error: {e}"

                    st.markdown(fr_response)

            st.session_state.finrobot_messages.append({"role": "assistant", "content": fr_response})
            st.rerun()

    with fund_tab5:
        # ── OPTION CHAIN TAB ──
        st.header("📊 NSE Option Chain — OI Analysis")
        st.caption("Live Open Interest data from NSE India · Supports stocks & indices (F&O eligible only)")

        # ── INPUT SECTION ──
        oc_col1, oc_col2 = st.columns([3, 1.5])

        with oc_col1:
            # Auto-fill: quick-select button > currently loaded stock > empty
            _oc_default_sym = st.session_state.pop("oc_quick_symbol", "")
            if not _oc_default_sym:
                _oc_deps = st.session_state.get("deps")
                _oc_company = getattr(_oc_deps, 'company_data', None) if _oc_deps else None
                if _oc_company and getattr(_oc_company, 'symbol', None):
                    _oc_default_sym = _clean_symbol_for_nse(_oc_company.symbol)

            oc_symbol = st.text_input(
                "Symbol",
                value=_oc_default_sym,
                placeholder="NIFTY, BANKNIFTY, RELIANCE, TCS...",
                key="oc_symbol_input",
                help="Enter NSE symbol. Indices: NIFTY, BANKNIFTY, FINNIFTY. Stocks: RELIANCE, TCS, etc."
            )

        with oc_col2:
            oc_expiry_idx = st.selectbox(
                "Expiry",
                options=[0, 1, 2, 3],
                format_func=lambda x: ["Nearest (Weekly)", "Next Week", "Monthly", "+1 Month"][x],
                key="oc_expiry_idx",
            )

        oc_n_strikes = 40  # Always fetch max strikes

        run_oc = st.button("🔍 Fetch & Analyze Option Chain", type="primary", key="run_option_chain")

        # ── FETCH + CACHE ──
        cache_key = f"option_chain_{oc_symbol}_{oc_expiry_idx}"

        if run_oc and oc_symbol:
            with st.spinner(f"Fetching live option chain from NSE for {oc_symbol}..."):
                try:
                    oc_data = fetch_option_chain(
                        symbol=oc_symbol,
                        expiry_index=oc_expiry_idx,
                        n_strikes=oc_n_strikes,
                    )
                    st.session_state[cache_key] = oc_data
                    st.success(f"✅ Loaded {len(oc_data.strikes)} strikes for {oc_data.symbol} | Expiry: {oc_data.expiry_date}")
                except ValueError as e:
                    st.error(f"❌ {str(e)}")
                    st.info("💡 Make sure the symbol is F&O eligible on NSE. Try NIFTY or BANKNIFTY.")
                    st.stop()
                except ConnectionError as e:
                    st.error(f"🌐 NSE connection failed: {str(e)}")
                    st.info("NSE API can be slow during market hours. Try again in a few seconds.")
                    st.stop()
                except Exception as e:
                    st.error(f"Unexpected error: {str(e)}")
                    st.stop()

        oc_data = st.session_state.get(cache_key)

        if oc_data:
            a = oc_data.analysis

            # ── HEADER INFO ──
            st.markdown(
                f"**{oc_data.symbol}** | Spot: **₹{oc_data.underlying_price:,.2f}** | "
                f"Expiry: **{oc_data.expiry_date}** | "
                f"Data: {oc_data.timestamp.strftime('%H:%M:%S UTC')}"
            )

            # ── RECOMMENDATION BANNER ──
            _oc_rec_styles = {
                "green":   ("#e8f5e9", "#1b5e20"),
                "#4caf50": ("#f1f8e9", "#33691e"),
                "gray":    ("#f5f5f5", "#424242"),
                "orange":  ("#fff3e0", "#bf360c"),
                "red":     ("#ffebee", "#b71c1c"),
            }
            _oc_bg, _oc_fg = _oc_rec_styles.get(a.recommendation_color, ("#f5f5f5", "#424242"))
            st.markdown(
                f"<div style='background:{_oc_bg}; border-left:6px solid {_oc_fg}; "
                f"padding:14px 18px; border-radius:6px; margin:12px 0;'>"
                f"<div style='font-size:1.15em; font-weight:700; color:{_oc_fg};'>"
                f"🎯 {a.recommendation}</div>"
                f"<div style='color:{_oc_fg}; margin-top:4px;'>"
                f"{a.bias_strength} {a.market_bias} · Confidence: {a.confidence}</div>"
                f"</div>",
                unsafe_allow_html=True
            )

            # ── KEY METRICS ROW ──
            m1, m2, m3, m4, m5 = st.columns(5)
            with m1:
                st.metric("🧱 Resistance", f"{a.key_resistance:,.0f}",
                          delta=f"+{((a.key_resistance - a.underlying_price)/a.underlying_price*100):.1f}%")
            with m2:
                st.metric("🛡️ Support", f"{a.key_support:,.0f}",
                          delta=f"{((a.key_support - a.underlying_price)/a.underlying_price*100):.1f}%",
                          delta_color="inverse")
            with m3:
                st.metric("⚙️ Max Pain", f"{a.max_pain_strike:,.0f}")
            with m4:
                _oc_pcr_delta_color = "normal" if a.put_call_ratio >= 1.0 else "inverse"
                st.metric("📊 PCR", f"{a.put_call_ratio:.3f}",
                          delta=a.pcr_label, delta_color=_oc_pcr_delta_color)
            with m5:
                st.metric("📏 Range", f"{a.range_low:,.0f}–{a.range_high:,.0f}")

            # ── INNER TABS: Table | Chart | Analysis ──
            inner_tab1, inner_tab2, inner_tab3 = st.tabs(
                ["📋 OI Table", "📈 OI Chart", "🔍 Full Analysis"]
            )

            with inner_tab1:
                st.subheader("Option Chain — OI Data")

                _oc_table_rows = []
                for s in oc_data.strikes:
                    _oc_row_flag = ""
                    if s.is_atm:
                        _oc_row_flag = "🔵 ATM"
                    elif s.is_max_call_oi:
                        _oc_row_flag = "🧱 Max Call OI"
                    elif s.is_max_put_oi:
                        _oc_row_flag = "🛡️ Max Put OI"

                    def _oc_fmt_oi(v: int) -> str:
                        if v >= 10_000_000: return f"{v/10_000_000:.1f}Cr"
                        if v >= 100_000:    return f"{v/100_000:.1f}L"
                        return f"{v:,}"

                    def _oc_fmt_chng(v: int) -> str:
                        sign = "+" if v > 0 else ""
                        if abs(v) >= 10_000_000: return f"{sign}{v/10_000_000:.1f}Cr"
                        if abs(v) >= 100_000:    return f"{sign}{v/100_000:.1f}L"
                        return f"{sign}{v:,}"

                    _oc_table_rows.append({
                        "Call OI": _oc_fmt_oi(s.call_oi),
                        "Call Chng OI": _oc_fmt_chng(s.call_chng_oi),
                        "⚡": _oc_row_flag,
                        "Strike": f"₹{s.strike:,.0f}",
                        "Put Chng OI": _oc_fmt_chng(s.put_chng_oi),
                        "Put OI": _oc_fmt_oi(s.put_oi),
                    })

                _oc_table_df = pd.DataFrame(_oc_table_rows)

                def _oc_highlight_rows(row):
                    flag = row["⚡"]
                    if "ATM" in flag:
                        return ["background-color: #1565c0; color: #fff; font-weight: bold"] * len(row)
                    elif "Max Call" in flag:
                        return ["background-color: #b71c1c; color: #fff; font-weight: bold"] * len(row)
                    elif "Max Put" in flag:
                        return ["background-color: #1b5e20; color: #fff; font-weight: bold"] * len(row)
                    return [""] * len(row)

                _oc_styled = _oc_table_df.style.apply(_oc_highlight_rows, axis=1)
                st.dataframe(_oc_styled, use_container_width=True, height=500)

                st.caption(
                    "🔵 Blue row = ATM (nearest to current price) | "
                    "🧱 Red row = Max Call OI (resistance) | "
                    "🛡️ Green row = Max Put OI (support)"
                )

            with inner_tab2:
                st.subheader("Open Interest Distribution")

                _oc_strikes_list = [s.strike for s in oc_data.strikes]
                _oc_call_ois = [s.call_oi for s in oc_data.strikes]
                _oc_put_ois = [s.put_oi for s in oc_data.strikes]
                _oc_call_chng = [s.call_chng_oi for s in oc_data.strikes]
                _oc_put_chng = [s.put_chng_oi for s in oc_data.strikes]

                _oc_fig = go.Figure()

                # OI bars (left y-axis)
                _oc_fig.add_trace(go.Bar(
                    x=_oc_strikes_list, y=_oc_call_ois,
                    name="Call OI",
                    marker_color="#ef5350",
                    opacity=0.8,
                    hovertemplate="Strike: %{x:,.0f}<br>Call OI: %{y:,}<extra></extra>"
                ))
                _oc_fig.add_trace(go.Bar(
                    x=_oc_strikes_list, y=_oc_put_ois,
                    name="Put OI",
                    marker_color="#26a69a",
                    opacity=0.8,
                    hovertemplate="Strike: %{x:,.0f}<br>Put OI: %{y:,}<extra></extra>"
                ))

                # Change in OI lines (right y-axis)
                _oc_fig.add_trace(go.Scatter(
                    x=_oc_strikes_list, y=_oc_call_chng,
                    name="Call Chng OI",
                    mode="lines+markers",
                    line=dict(color="#e53935", dash="dot", width=1.5),
                    marker=dict(size=4),
                    yaxis="y2",
                    hovertemplate="Strike: %{x:,.0f}<br>Call Chng: %{y:+,}<extra></extra>"
                ))
                _oc_fig.add_trace(go.Scatter(
                    x=_oc_strikes_list, y=_oc_put_chng,
                    name="Put Chng OI",
                    mode="lines+markers",
                    line=dict(color="#00897b", dash="dot", width=1.5),
                    marker=dict(size=4),
                    yaxis="y2",
                    hovertemplate="Strike: %{x:,.0f}<br>Put Chng: %{y:+,}<extra></extra>"
                ))

                # Vertical lines for key levels
                for _oc_level, _oc_label, _oc_color_line in [
                    (a.underlying_price, f"Spot ₹{a.underlying_price:,.0f}", "#1565c0"),
                    (a.max_call_oi_strike, f"Resistance {a.max_call_oi_strike:,.0f}", "#b71c1c"),
                    (a.max_put_oi_strike, f"Support {a.max_put_oi_strike:,.0f}", "#1b5e20"),
                    (a.max_pain_strike, f"Max Pain {a.max_pain_strike:,.0f}", "#f57f17"),
                ]:
                    _oc_fig.add_vline(
                        x=_oc_level,
                        line_dash="dash",
                        line_color=_oc_color_line,
                        line_width=1.5,
                        annotation_text=_oc_label,
                        annotation_position="top",
                        annotation_font_size=10,
                    )

                _oc_fig.update_layout(
                    barmode="group",
                    xaxis_title="Strike Price",
                    yaxis_title="Open Interest",
                    yaxis2=dict(
                        title="Change in OI",
                        overlaying="y",
                        side="right",
                        showgrid=False,
                    ),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02),
                    height=420,
                    margin=dict(t=40, b=30, l=10, r=10),
                    hovermode="x unified",
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                )
                _oc_fig.update_yaxes(gridcolor="rgba(128,128,128,0.1)")

                st.plotly_chart(_oc_fig, use_container_width=True)

                if len(oc_data.available_expiries) > 1:
                    st.caption(
                        f"Available expiries: {' · '.join(oc_data.available_expiries[:5])}"
                    )

            with inner_tab3:
                st.subheader("OI Signal Analysis & Verdict")

                # -- Signal Score Meter --
                _oc_total_score = getattr(a, 'total_signal_score', 0)
                _oc_has_contradiction = getattr(a, 'has_contradiction', False)

                _oc_score_col1, _oc_score_col2, _oc_score_col3 = st.columns([1, 3, 1])
                with _oc_score_col2:
                    _oc_score_color = "green" if _oc_total_score >= 2 else ("red" if _oc_total_score <= -2 else "gray")
                    st.markdown(
                        f"<div style='text-align:center; font-size:2em; font-weight:700; color:{_oc_score_color};'>"
                        f"{'+'if _oc_total_score > 0 else ''}{_oc_total_score} / 9"
                        f"</div>",
                        unsafe_allow_html=True
                    )
                    _oc_normalized = int(((_oc_total_score + 9) / 18) * 100)
                    _oc_normalized = max(0, min(100, _oc_normalized))
                    st.progress(_oc_normalized, text=f"Signal Score: {'+' if _oc_total_score >= 0 else ''}{_oc_total_score}")

                if _oc_has_contradiction:
                    st.warning(
                        "**Contradicting Signals Detected** — Call OI and Put OI are pointing in "
                        "opposite directions. This means the market is undecided. "
                        "**Do not force a trade.** Wait for signals to converge."
                    )

                st.divider()

                _oc_sc1, _oc_sc2 = st.columns(2)
                with _oc_sc1:
                    st.markdown("#### 📈 Call OI Signal")
                    _oc_dir = a.call_oi_shift.direction
                    _oc_dir_color = {"UP": "green", "DOWN": "red", "SIDEWAYS": "gray"}.get(_oc_dir, "gray")
                    st.markdown(
                        f"<span style='color:{_oc_dir_color}; font-size:1.1em; font-weight:600;'>"
                        f"{'⬆' if _oc_dir=='UP' else ('⬇' if _oc_dir=='DOWN' else '➡')} "
                        f"{_oc_dir} · {a.call_oi_shift.strength} "
                        f"({'+' if getattr(a.call_oi_shift, 'score_contribution', 0) >= 0 else ''}{getattr(a.call_oi_shift, 'score_contribution', 0)})</span>",
                        unsafe_allow_html=True
                    )
                    st.write(a.call_oi_shift.description)

                with _oc_sc2:
                    st.markdown("#### 📉 Put OI Signal")
                    _oc_dir2 = a.put_oi_shift.direction
                    _oc_dir_color2 = {"UP": "green", "DOWN": "red", "SIDEWAYS": "gray"}.get(_oc_dir2, "gray")
                    st.markdown(
                        f"<span style='color:{_oc_dir_color2}; font-size:1.1em; font-weight:600;'>"
                        f"{'⬆' if _oc_dir2=='UP' else ('⬇' if _oc_dir2=='DOWN' else '➡')} "
                        f"{_oc_dir2} · {a.put_oi_shift.strength} "
                        f"({'+' if getattr(a.put_oi_shift, 'score_contribution', 0) >= 0 else ''}{getattr(a.put_oi_shift, 'score_contribution', 0)})</span>",
                        unsafe_allow_html=True
                    )
                    st.write(a.put_oi_shift.description)

                st.divider()

                st.markdown("#### 📋 Complete Signal Breakdown")
                for _oc_point in a.verdict_points:
                    _pt = _oc_point.strip()
                    if not _pt:
                        continue
                    if "TOTAL SIGNAL SCORE" in _pt or "RECOMMENDATION" in _pt:
                        st.markdown(f"**{_pt}**")
                    elif "CONTRADICTION" in _pt:
                        st.error(_pt)
                    elif "(+" in _pt or "bullish" in _pt.lower() or "support" in _pt.lower():
                        st.success(_pt)
                    elif "(-" in _pt or "bearish" in _pt.lower() or "resistance" in _pt.lower():
                        st.warning(_pt)
                    else:
                        st.info(_pt)

                st.divider()

                with st.expander("📖 How to read Option Chain OI"):
                    st.markdown("""
**Open Interest (OI)** = Total number of outstanding option contracts not yet settled.

**Call OI** = Open positions in Call options at that strike.
High Call OI at a strike = that level is a **resistance** (writers expect price to stay below)

**Put OI** = Open positions in Put options at that strike.
High Put OI at a strike = that level is a **support** (writers expect price to stay above)

**Change in OI (Chng OI)**
- Positive = New positions being created (increased activity)
- Negative = Old positions being closed (unwinding)

**OI Shift Tracking**
- PUT OI concentration shifting HIGHER → Supports moving up → Market moving **UP** ⬆
- CALL OI concentration shifting LOWER → Resistance moving down → Market moving **DOWN** ⬇

**Put-Call Ratio (PCR)**
| PCR Value | Interpretation |
|-----------|---------------|
| > 1.5 | Extremely Bullish — heavy put writing |
| 1.2–1.5 | Bullish |
| 0.8–1.2 | Neutral / Range-bound |
| 0.5–0.8 | Bearish |
| < 0.5 | Extremely Bearish |

**Max Pain** = Strike where maximum option buyers lose money at expiry.
Market tends to gravitate toward Max Pain as expiry approaches.

*Note: Option chain data is only available for F&O-eligible stocks and indices on NSE.*
                    """)
        else:
            if not oc_symbol:
                st.info("📊 Enter a symbol above or use Quick Select buttons to fetch option chain data.")

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
            st.session_state.view_selector = "🏦 Fundamental Analysis"
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
                        st.session_state.view_selector = "🏦 Fundamental Analysis"
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
                        st.session_state.view_selector = "🏦 Fundamental Analysis"
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
                st.session_state.view_selector = "🏦 Fundamental Analysis"
                st.rerun()

elif view_option == "📈 Data Dashboard":
    if st.session_state.company_data:
        data = st.session_state.company_data
        st.subheader(f"📊 {data.name} ({data.symbol})")

        # Auto-enrich from yfinance if key dashboard fields are missing (e.g. DB cache hit)
        _needs_enrich = (
            not getattr(data.financials, 'ebitda', None) or
            not getattr(data.financials, 'eps', None) or
            not data.market_data.price_history
        )
        if _needs_enrich and data.symbol and not st.session_state.get(f'_dash_enriched_{data.symbol}'):
            try:
                import yfinance as yf
                _dash_tk = yf.Ticker(data.symbol)
                _dash_info = _dash_tk.info or {}
                _dash_hist = _dash_tk.history(period="1y")

                # Fill missing financials
                if not getattr(data.financials, 'ebitda', None):
                    data.financials.ebitda = _dash_info.get('ebitda')
                if not getattr(data.financials, 'eps', None):
                    data.financials.eps = _dash_info.get('trailingEps')
                if not getattr(data.financials, 'free_cash_flow', None):
                    data.financials.free_cash_flow = _dash_info.get('freeCashflow')

                # Fill price history
                if not data.market_data.price_history and not _dash_hist.empty:
                    data.market_data.price_history = {
                        str(dt.date()): float(row["Close"])
                        for dt, row in _dash_hist.iterrows()
                    }

                # Fill overall high/low from history
                if not _dash_hist.empty:
                    if not getattr(data.market_data, 'overall_high', None):
                        data.market_data.overall_high = float(_dash_hist['High'].max())
                    if not getattr(data.market_data, 'overall_low', None):
                        data.market_data.overall_low = float(_dash_hist['Low'].min())
                    if data.market_data.overall_high and data.market_data.current_price:
                        data.market_data.percentage_change_from_high = round(
                            ((data.market_data.current_price - data.market_data.overall_high) / data.market_data.overall_high) * 100, 2
                        )

                st.session_state[f'_dash_enriched_{data.symbol}'] = True
            except Exception as _e:
                print(f"⚠️ Dashboard enrichment failed: {_e}")

        col1, col2 = st.columns([2, 1])

        # -------- Price Trend (TradingView style) --------
        with col1:
            if data.market_data.price_history:
                st.markdown("#### Chart")

                all_dates = list(data.market_data.price_history.keys())
                all_prices = list(data.market_data.price_history.values())

                # Period selector via session state
                if "pt_period" not in st.session_state:
                    st.session_state.pt_period = "1Y"

                period_map = {"1 day": 1, "5 days": 5, "1 month": 30, "6 months": 180, "Year to date": None, "1 year": 365, "All time": len(all_dates)}

                # Determine days for current selected period
                selected = st.session_state.pt_period
                period_days_map = {"1W": 7, "1M": 30, "3M": 90, "6M": 180, "1Y": 365, "ALL": len(all_dates)}
                days = period_days_map.get(selected, 365)

                dates = all_dates[-days:]
                prices = all_prices[-days:]

                current_price = prices[-1] if prices else 0
                price_change = prices[-1] - prices[0] if len(prices) > 1 else 0
                is_positive = price_change >= 0
                line_color = "#089981" if is_positive else "#F23645"
                fill_color = "rgba(8,153,129,0.12)" if is_positive else "rgba(242,54,69,0.12)"

                fig = go.Figure()

                # Area fill trace
                fig.add_trace(go.Scatter(
                    x=dates,
                    y=prices,
                    mode="lines",
                    fill="tozeroy",
                    fillcolor=fill_color,
                    line=dict(color=line_color, width=1.5, shape="spline"),
                    hovertemplate="₹%{y:,.2f}<br>%{x}<extra></extra>"
                ))

                fig.update_layout(
                    template="plotly_dark",
                    height=380,
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    showlegend=False,
                    margin=dict(l=0, r=50, t=10, b=10),
                    xaxis=dict(
                        showgrid=False,
                        showline=False,
                        zeroline=False,
                        tickfont=dict(color="#787B86", size=11),
                        tickformat="%b '%y" if days > 90 else "%d %b",
                    ),
                    yaxis=dict(
                        showgrid=False,
                        showline=False,
                        zeroline=False,
                        side="right",
                        tickprefix="₹",
                        tickfont=dict(color="#787B86", size=11),
                    ),
                    hoverlabel=dict(bgcolor="#1E222D", font_size=12, font_color="#D1D4DC"),
                    hovermode="x unified",
                )

                # Current price annotation on right edge
                fig.add_annotation(
                    x=dates[-1], y=current_price,
                    text=f"₹{current_price:,.2f}",
                    showarrow=False,
                    xanchor="left", xshift=8,
                    font=dict(color="white", size=12),
                    bgcolor=line_color,
                    borderpad=4,
                )

                # Prev close line
                prev_close = prices[0] if prices else 0
                fig.add_hline(
                    y=prev_close, line_dash="dot",
                    line_color="#787B86", line_width=0.8,
                    annotation_text=f"Prev close  ₹{prev_close:,.2f}",
                    annotation_position="bottom right",
                    annotation_font_color="#787B86",
                    annotation_font_size=10,
                )

                st.plotly_chart(fig, width='stretch')

                # --- Period buttons BELOW chart (TradingView style) ---
                def _set_period(p):
                    st.session_state.pt_period = p

                btn_cols = st.columns(6)
                period_labels = ["1W", "1M", "3M", "6M", "1Y", "ALL"]
                for i, label in enumerate(period_labels):
                    with btn_cols[i]:
                        is_active = st.session_state.pt_period == label
                        st.button(
                            label, key=f"pt_{label}",
                            type="primary" if is_active else "secondary",
                            on_click=_set_period, args=(label,),
                            use_container_width=True,
                        )

                # --- Performance metrics below buttons (TradingView style) ---
                metric_periods = {"1 day": 1, "5 days": 5, "1 month": 30, "6 months": 180, "1 year": 365, "All time": len(all_dates)}
                metric_cols = st.columns(len(metric_periods))
                for idx, (mlabel, mdays) in enumerate(metric_periods.items()):
                    mdays = min(mdays, len(all_prices))
                    if mdays >= 2:
                        start_p = all_prices[-mdays]
                        end_p = all_prices[-1]
                        pct = ((end_p - start_p) / start_p) * 100 if start_p else 0
                        color = "#089981" if pct >= 0 else "#F23645"
                        with metric_cols[idx]:
                            st.markdown(
                                f"<div style='text-align:center;padding:4px 0'>"
                                f"<div style='color:#787B86;font-size:12px'>{mlabel}</div>"
                                f"<div style='color:{color};font-size:14px;font-weight:600'>{pct:+.2f}%</div>"
                                f"</div>",
                                unsafe_allow_html=True,
                            )

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

        # ── CSS for Technical Analysis cards ──
        st.markdown("""
        <style>
        .ta-section-title {
            font-size: 12px; color: #888; letter-spacing: 0.06em;
            text-transform: uppercase; font-weight: 600;
            border-bottom: 0.5px solid #333; padding-bottom: 8px; margin-bottom: 12px; margin-top: 24px;
        }
        .ta-card {
            background: #1a1a1a; border-radius: 8px; padding: 14px 16px;
            height: 100%; min-height: 90px;
        }
        .ta-label { font-size: 11px; color: #888; margin-bottom: 4px; }
        .ta-value { font-size: 20px; font-weight: 500; color: #fff; margin-bottom: 4px; }
        .ta-sub { font-size: 11px; }
        .ta-badge {
            display: inline-block; border-radius: 99px; padding: 2px 8px;
            font-size: 11px; font-weight: 500;
        }
        .ta-badge-green { background: #dcfce7; color: #166534; }
        .ta-badge-red { background: #fee2e2; color: #991b1b; }
        .ta-badge-amber { background: #fef3c7; color: #92400e; }
        .ta-badge-blue { background: #e0f2fe; color: #0c4a6e; }
        .ta-range-track {
            background: #333; border-radius: 99px; height: 4px; width: 100%;
            margin: 8px 0 4px 0; position: relative;
        }
        .ta-range-fill {
            border-radius: 99px; height: 4px; position: absolute; top: 0; left: 0;
        }
        .ta-ma-row {
            display: flex; justify-content: space-between; align-items: center;
            padding: 6px 0; border-bottom: 0.5px solid #2a2a2a;
        }
        .ta-ma-row:last-child { border-bottom: none; }
        .ta-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 6px; }
        </style>
        """, unsafe_allow_html=True)

        # ── Helper values ──
        _is_indian = data.symbol.endswith('.NS') or data.symbol.endswith('.BO')
        _cur = "₹" if _is_indian else "$"
        _divisor = 1e7 if _is_indian else 1e9
        _unit = "Cr" if _is_indian else "B"

        def _fmt_large(val):
            if val is None: return "—"
            if _is_indian:
                return f"{_cur}{val/_divisor:,.2f} {_unit}" if abs(val) >= 1e7 else f"{_cur}{val/1e5:,.2f} L"
            return f"{_cur}{val/_divisor:,.2f} {_unit}"

        def _badge(text, kind="green"):
            return f'<span class="ta-badge ta-badge-{kind}">{text}</span>'

        # ══════════════════════════════════════════════
        # 1. PRICE & VALUATION
        # ══════════════════════════════════════════════
        st.markdown('<div class="ta-section-title">PRICE & VALUATION</div>', unsafe_allow_html=True)

        pv1, pv2, pv3, pv4 = st.columns(4)

        # Current Price
        with pv1:
            cp = data.market_data.current_price
            day_chg = data.market_data.day_change
            chg_color = "#22c55e" if day_chg and day_chg >= 0 else "#ef4444"
            chg_text = f'<div class="ta-sub" style="color:{chg_color}">{day_chg:+.2f}% today</div>' if day_chg is not None else ""
            st.markdown(f'''<div class="ta-card">
                <div class="ta-label">Current Price</div>
                <div class="ta-value">{_cur}{cp:,.2f}</div>{chg_text}
            </div>''' if cp is not None else '<div class="ta-card"><div class="ta-label">Current Price</div><div class="ta-value">—</div></div>', unsafe_allow_html=True)

        # 52W Range
        with pv2:
            w52h = data.market_data.week_52_high
            w52l = data.market_data.week_52_low
            if w52h and w52l and cp:
                range_pct = ((cp - w52l) / (w52h - w52l)) * 100 if w52h != w52l else 50
                range_pct = max(0, min(100, range_pct))
                st.markdown(f'''<div class="ta-card">
                    <div class="ta-label">52W Range</div>
                    <div class="ta-value" style="font-size:16px">{_cur}{w52l:,.0f} – {_cur}{w52h:,.0f}</div>
                    <div class="ta-range-track"><div class="ta-range-fill" style="width:{range_pct}%;background:#2962FF;"></div></div>
                    <div class="ta-sub" style="color:#888">at {range_pct:.0f}% of range</div>
                </div>''', unsafe_allow_html=True)
            else:
                st.markdown('<div class="ta-card"><div class="ta-label">52W Range</div><div class="ta-value">—</div></div>', unsafe_allow_html=True)

        # Market Cap
        with pv3:
            mcap = data.market_data.market_cap
            if mcap:
                if _is_indian:
                    cap_label = "Large Cap" if mcap >= 2e11 else ("Mid Cap" if mcap >= 5e10 else "Small Cap")
                else:
                    cap_label = "Large Cap" if mcap >= 1e10 else ("Mid Cap" if mcap >= 2e9 else "Small Cap")
                st.markdown(f'''<div class="ta-card">
                    <div class="ta-label">Market Cap</div>
                    <div class="ta-value">{_fmt_large(mcap)}</div>
                    <div class="ta-sub" style="color:#888">{cap_label}</div>
                </div>''', unsafe_allow_html=True)
            else:
                st.markdown('<div class="ta-card"><div class="ta-label">Market Cap</div><div class="ta-value">—</div></div>', unsafe_allow_html=True)

        # Avg Volume (10D)
        with pv4:
            avg_vol = data.market_data.avg_volume
            if avg_vol:
                if avg_vol >= 1e7:
                    vol_str = f"{avg_vol/1e7:.2f} Cr"
                elif avg_vol >= 1e5:
                    vol_str = f"{avg_vol/1e5:.2f} L"
                else:
                    vol_str = f"{avg_vol:,.0f}"
                st.markdown(f'''<div class="ta-card">
                    <div class="ta-label">Avg Volume (10D)</div>
                    <div class="ta-value">{vol_str}</div>
                </div>''', unsafe_allow_html=True)
            else:
                st.markdown(f'''<div class="ta-card">
                    <div class="ta-label">Avg Volume (10D)</div>
                    <div class="ta-value">—</div>
                </div>''', unsafe_allow_html=True)

        # ══════════════════════════════════════════════
        # 2. FUNDAMENTALS
        # ══════════════════════════════════════════════
        st.markdown('<div class="ta-section-title">FUNDAMENTALS</div>', unsafe_allow_html=True)

        f1, f2, f3, f4 = st.columns(4)

        # P/E Ratio
        with f1:
            pe = data.financials.pe_ratio
            if pe:
                pe_badge = _badge("Moderate", "amber") if 15 <= pe <= 30 else (_badge("Low", "green") if pe < 15 else _badge("High", "red"))
                st.markdown(f'''<div class="ta-card">
                    <div class="ta-label">P/E Ratio</div>
                    <div class="ta-value">{pe:.2f}</div>{pe_badge}
                </div>''', unsafe_allow_html=True)
            else:
                st.markdown('<div class="ta-card"><div class="ta-label">P/E Ratio</div><div class="ta-value">—</div></div>', unsafe_allow_html=True)

        # EPS (TTM)
        with f2:
            eps = getattr(data.financials, "eps", None)
            st.markdown(f'''<div class="ta-card">
                <div class="ta-label">EPS (TTM)</div>
                <div class="ta-value">{_cur}{eps:,.2f}</div>
                <div class="ta-sub" style="color:#888">Earnings/share</div>
            </div>''' if eps else '<div class="ta-card"><div class="ta-label">EPS (TTM)</div><div class="ta-value">—</div></div>', unsafe_allow_html=True)

        # Profit Margin
        with f3:
            pm = data.financials.profit_margin
            if pm is not None:
                pm_pct = pm * 100
                pm_badge = _badge("Healthy", "green") if pm_pct > 10 else (_badge("Low", "red") if pm_pct < 5 else _badge("Moderate", "amber"))
                st.markdown(f'''<div class="ta-card">
                    <div class="ta-label">Profit Margin</div>
                    <div class="ta-value">{pm_pct:.2f}%</div>{pm_badge}
                </div>''', unsafe_allow_html=True)
            else:
                st.markdown('<div class="ta-card"><div class="ta-label">Profit Margin</div><div class="ta-value">—</div></div>', unsafe_allow_html=True)

        # Debt / Equity
        with f4:
            de = getattr(data.financials, "debt_to_equity", None)
            if de is not None:
                de_badge = _badge("Low", "green") if de < 0.5 else (_badge("Moderate", "amber") if de < 1.5 else _badge("High", "red"))
                st.markdown(f'''<div class="ta-card">
                    <div class="ta-label">Debt / Equity</div>
                    <div class="ta-value">{de:.2f}</div>{de_badge}
                </div>''', unsafe_allow_html=True)
            else:
                st.markdown('<div class="ta-card"><div class="ta-label">Debt / Equity</div><div class="ta-value">—</div></div>', unsafe_allow_html=True)

        # ══════════════════════════════════════════════
        # 3. GROWTH & PROFITABILITY
        # ══════════════════════════════════════════════
        st.markdown('<div class="ta-section-title">GROWTH & PROFITABILITY</div>', unsafe_allow_html=True)

        g1, g2, g3, g4 = st.columns(4)

        # Revenue (TTM)
        with g1:
            rev = data.financials.revenue
            rev_yoy = ""
            st.markdown(f'''<div class="ta-card">
                <div class="ta-label">Revenue (TTM)</div>
                <div class="ta-value">{_fmt_large(rev)}</div>
            </div>''', unsafe_allow_html=True)

        # EBITDA
        with g2:
            ebitda = getattr(data.financials, "ebitda", None)
            ebitda_margin = ""
            if ebitda and rev:
                ebitda_margin = f'<div class="ta-sub" style="color:#888">Margin: ~{(ebitda/rev)*100:.0f}%</div>'
            st.markdown(f'''<div class="ta-card">
                <div class="ta-label">EBITDA</div>
                <div class="ta-value">{_fmt_large(ebitda)}</div>{ebitda_margin}
            </div>''', unsafe_allow_html=True)

        # ROE
        with g3:
            roe = getattr(data.financials, "roe", None)
            if roe is not None:
                roe_pct = roe * 100 if abs(roe) < 1 else roe
                st.markdown(f'''<div class="ta-card">
                    <div class="ta-label">ROE</div>
                    <div class="ta-value">{roe_pct:.1f}%</div>
                </div>''', unsafe_allow_html=True)
            else:
                st.markdown('<div class="ta-card"><div class="ta-label">ROE</div><div class="ta-value">—</div></div>', unsafe_allow_html=True)

        # Dividend Yield
        with g4:
            dy = getattr(data.financials, "dividend_yield", None)
            if dy is not None:
                dy_pct = dy * 100 if abs(dy) < 1 else dy
                st.markdown(f'''<div class="ta-card">
                    <div class="ta-label">Dividend Yield</div>
                    <div class="ta-value">{dy_pct:.2f}%</div>
                </div>''', unsafe_allow_html=True)
            else:
                st.markdown('<div class="ta-card"><div class="ta-label">Dividend Yield</div><div class="ta-value">—</div></div>', unsafe_allow_html=True)

        # ══════════════════════════════════════════════
        # 4. TECHNICAL SIGNALS
        # ══════════════════════════════════════════════
        st.markdown('<div class="ta-section-title">TECHNICAL SIGNALS</div>', unsafe_allow_html=True)

        # Initialize default values for price analysis
        all_dates = []
        all_prices = []
        if data.market_data.price_history:
            all_dates = list(data.market_data.price_history.keys())
            all_prices = list(data.market_data.price_history.values())

        if all_prices and len(all_prices) > 1:
            prices_series = pd.Series(all_prices, index=pd.to_datetime(all_dates))

            sma20 = prices_series.rolling(20).mean()
            sma50 = prices_series.rolling(50).mean()
            sma200 = prices_series.rolling(200).mean()

            returns = prices_series.pct_change().dropna()
            volatility = returns.std() * (252 ** 0.5)

            delta_vals = prices_series.diff()
            up = delta_vals.clip(lower=0)
            down = -delta_vals.clip(upper=0)
            rs = up.rolling(14).mean() / down.rolling(14).mean()
            rsi = 100 - (100 / (1 + rs))

            latest_price = prices_series.iloc[-1]
            latest_sma20 = sma20.dropna().iloc[-1] if not sma20.dropna().empty else None
            latest_sma50 = sma50.dropna().iloc[-1] if not sma50.dropna().empty else None
            latest_sma200 = sma200.dropna().iloc[-1] if not sma200.dropna().empty else None
            latest_rsi = rsi.dropna().iloc[-1] if not rsi.dropna().empty else None

            # MACD
            ema12 = prices_series.ewm(span=12, adjust=False).mean()
            ema26 = prices_series.ewm(span=26, adjust=False).mean()
            macd_line = ema12 - ema26
            macd_signal = macd_line.ewm(span=9, adjust=False).mean()
            latest_macd = macd_line.iloc[-1]
            latest_macd_signal = macd_signal.iloc[-1]
            macd_bullish = latest_macd > latest_macd_signal

            ts1, ts2, ts3 = st.columns(3)

            # Moving Averages card
            with ts1:
                ma_rows = ""
                for ma_label, ma_val in [("MA 20", latest_sma20), ("MA 50", latest_sma50), ("MA 200", latest_sma200)]:
                    if ma_val is not None:
                        above = latest_price > ma_val
                        dot_color = "#22c55e" if above else "#ef4444"
                        signal_text = f'<span style="color:{dot_color}">{"Above" if above else "Below"}</span>'
                        ma_rows += f'''<div class="ta-ma-row">
                            <span><span class="ta-dot" style="background:{dot_color}"></span><span style="color:#ccc">{ma_label}</span></span>
                            <span style="color:#888">{_cur}{ma_val:,.0f} · {signal_text}</span>
                        </div>'''
                st.markdown(f'''<div class="ta-card">
                    <div class="ta-label">Moving Averages</div>{ma_rows}
                </div>''', unsafe_allow_html=True)

            # Momentum card
            with ts2:
                rsi_color = "#22c55e" if latest_rsi and latest_rsi < 70 and latest_rsi > 30 else ("#ef4444" if latest_rsi and latest_rsi >= 70 else "#22c55e")
                rsi_label = "Neutral" if latest_rsi and 30 < latest_rsi < 70 else ("Overbought" if latest_rsi and latest_rsi >= 70 else "Oversold")
                rsi_badge_kind = "amber" if rsi_label == "Neutral" else ("red" if rsi_label == "Overbought" else "green")
                macd_badge = _badge("Bullish", "green") if macd_bullish else _badge("Bearish", "red")
                st.markdown(f'''<div class="ta-card">
                    <div class="ta-label">Momentum</div>
                    <div class="ta-ma-row">
                        <span style="color:#ccc">RSI (14)</span>
                        <span style="color:#fff;font-weight:500">{latest_rsi:.1f} {_badge(rsi_label, rsi_badge_kind)}</span>
                    </div>
                    <div class="ta-ma-row">
                        <span style="color:#ccc">MACD</span>
                        <span>{macd_badge}</span>
                    </div>
                    <div class="ta-ma-row">
                        <span style="color:#ccc">Volatility</span>
                        <span style="color:#fff;font-weight:500">{volatility:.1%}</span>
                    </div>
                </div>''' if latest_rsi else '<div class="ta-card"><div class="ta-label">Momentum</div><div class="ta-value">—</div></div>', unsafe_allow_html=True)

            # Drawdown & Risk card
            with ts3:
                pct_from_ath = data.market_data.percentage_change_from_high
                yr_return = data.market_data.year_change
                beta = data.market_data.beta
                rows_dd = ""
                if pct_from_ath is not None:
                    dd_color = "#ef4444" if pct_from_ath < 0 else "#22c55e"
                    rows_dd += f'<div class="ta-ma-row"><span style="color:#ccc">From ATH</span><span style="color:{dd_color};font-weight:500">{pct_from_ath:+.2f}%</span></div>'
                if yr_return is not None:
                    yr_color = "#22c55e" if yr_return >= 0 else "#ef4444"
                    rows_dd += f'<div class="ta-ma-row"><span style="color:#ccc">1Y Return</span><span style="color:{yr_color};font-weight:500">{yr_return:+.2f}%</span></div>'
                if beta is not None:
                    rows_dd += f'<div class="ta-ma-row"><span style="color:#ccc">Beta</span><span style="color:#fff;font-weight:500">{beta:.2f}</span></div>'
                if not rows_dd:
                    rows_dd = '<div class="ta-value">—</div>'
                st.markdown(f'''<div class="ta-card">
                    <div class="ta-label">Drawdown & Risk</div>{rows_dd}
                </div>''', unsafe_allow_html=True)

            # ── SMA Chart ──
            sma_fig = go.Figure()
            sma_fig.add_trace(go.Scatter(x=prices_series.index, y=prices_series, name="Price", line=dict(color="#2962FF", width=1.5)))
            sma_fig.add_trace(go.Scatter(x=sma20.index, y=sma20, name="SMA 20", line=dict(color="#FF9800", width=1, dash="dot")))
            sma_fig.add_trace(go.Scatter(x=sma50.index, y=sma50, name="SMA 50", line=dict(color="#AB47BC", width=1, dash="dot")))
            sma_fig.add_trace(go.Scatter(x=sma200.index, y=sma200, name="SMA 200", line=dict(color="#26A69A", width=1, dash="dot")))
            sma_fig.update_layout(
                template="plotly_dark", height=350,
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=0, r=50, t=10, b=10),
                xaxis=dict(showgrid=False, showline=False, zeroline=False, tickfont=dict(color="#787B86", size=10)),
                yaxis=dict(showgrid=False, showline=False, zeroline=False, side="right", tickprefix=_cur, tickfont=dict(color="#787B86", size=10)),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(size=11, color="#aaa")),
            )
            st.plotly_chart(sma_fig, width='stretch')

            # ── RSI Chart ──
            if not rsi.dropna().empty:
                rsi_fig = go.Figure()
                rsi_fig.add_trace(go.Scatter(x=rsi.index, y=rsi, name="RSI", line=dict(color="#AB47BC", width=1.5), fill="tozeroy", fillcolor="rgba(171,71,188,0.08)"))
                rsi_fig.add_hline(y=70, line_dash="dash", line_color="#ef4444", line_width=0.8)
                rsi_fig.add_hline(y=30, line_dash="dash", line_color="#22c55e", line_width=0.8)
                rsi_fig.add_hrect(y0=30, y1=70, fillcolor="rgba(255,255,255,0.02)", line_width=0)
                rsi_fig.update_layout(
                    template="plotly_dark", height=180,
                    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=0, r=50, t=10, b=10), showlegend=False,
                    xaxis=dict(showgrid=False, showline=False, zeroline=False, tickfont=dict(color="#787B86", size=10)),
                    yaxis=dict(showgrid=False, showline=False, zeroline=False, side="right", tickfont=dict(color="#787B86", size=10), range=[0, 100]),
                )
                st.plotly_chart(rsi_fig, width='stretch')
        else:
            ts1, ts2, ts3 = st.columns(3)
            with ts1:
                st.markdown('<div class="ta-card"><div class="ta-label">Moving Averages</div><div class="ta-value">—</div></div>', unsafe_allow_html=True)
            with ts2:
                st.markdown('<div class="ta-card"><div class="ta-label">Momentum</div><div class="ta-value">—</div></div>', unsafe_allow_html=True)
            with ts3:
                st.markdown('<div class="ta-card"><div class="ta-label">Drawdown & Risk</div><div class="ta-value">—</div></div>', unsafe_allow_html=True)
            st.info("No price history available for technical analysis")

        # ══════════════════════════════════════════════
        # 5. ANALYST & SENTIMENT
        # ══════════════════════════════════════════════
        st.markdown('<div class="ta-section-title">ANALYST & SENTIMENT</div>', unsafe_allow_html=True)

        an1, an2 = st.columns(2)

        # Selection Status card (reuses max_drop logic)
        with an1:
            max_drop = getattr(data.market_data, 'max_drop_after_high', None)
            if max_drop is not None:
                is_selected = max_drop <= -25
            elif data.market_data.percentage_change_from_high is not None:
                is_selected = data.market_data.percentage_change_from_high <= -25
            else:
                is_selected = None

            if is_selected is not None:
                sel_text = "Selected" if is_selected else "Not Selected"
                sel_color = "#22c55e" if is_selected else "#ef4444"
                sel_icon = "✅" if is_selected else "❌"
                drop_sub = f'<div class="ta-sub" style="color:#888;margin-top:4px">Dropped {abs(max_drop):.1f}% after peak</div>' if max_drop is not None else ""
                st.markdown(f'''<div class="ta-card">
                    <div class="ta-label">Selection Status</div>
                    <div class="ta-value">{sel_icon} {sel_text}</div>{drop_sub}
                </div>''', unsafe_allow_html=True)
            else:
                st.markdown('<div class="ta-card"><div class="ta-label">Selection Status</div><div class="ta-value">—</div></div>', unsafe_allow_html=True)

        # Overall High/Low card
        with an2:
            oh = data.market_data.overall_high
            ol = data.market_data.overall_low
            if oh is not None and ol is not None:
                st.markdown(f'''<div class="ta-card">
                    <div class="ta-label">Overall Price Range</div>
                    <div class="ta-value" style="font-size:16px">{_cur}{ol:,.2f} – {_cur}{oh:,.2f}</div>
                    <div class="ta-sub" style="color:{"#ef4444" if data.market_data.percentage_change_from_high and data.market_data.percentage_change_from_high < 0 else "#22c55e"};margin-top:4px">
                        {data.market_data.percentage_change_from_high:+.2f}% from ATH</div>
                </div>''' if data.market_data.percentage_change_from_high is not None else f'''<div class="ta-card">
                    <div class="ta-label">Overall Price Range</div>
                    <div class="ta-value" style="font-size:16px">{_cur}{ol:,.2f} – {_cur}{oh:,.2f}</div>
                </div>''', unsafe_allow_html=True)
            else:
                st.markdown('<div class="ta-card"><div class="ta-label">Overall Price Range</div><div class="ta-value">—</div></div>', unsafe_allow_html=True)

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


elif view_option == "⚡ Bulk Stock Analyzer":
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

elif view_option == "🖊️ Drawing Generator":
    # Drawing Generator — calls api_chat_drawing.py  POST /api/v1/drawing/chat/
    import requests as _req
    from datetime import timedelta as _td

    st.markdown("### 🎨 Auto Drawing Generator")
    st.markdown("Generate TradingView drawing instructions from price data analysis")
    st.markdown("---")

    # ── Row 1: Symbol / Timeframe / Period / Market ──────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        symbol_input = st.text_input(
            "Stock Symbol", value="AAPL",
            help="e.g. AAPL, RELIANCE, TCS  (exchange suffix added automatically)"
        )
    with col2:
        timeframe = st.selectbox(
            "Timeframe",
            options=["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1wk", "1mo"],
            index=6,
            help="Chart timeframe"
        )
    with col3:
        period = st.selectbox(
            "Period",
            options=["1mo", "3mo", "6mo", "1y", "2y", "5y"],
            index=3,
            help="How far back to pull price data"
        )
    with col4:
        market = st.selectbox(
            "Market",
            options=["stock", "nasdaq", "nyse", "forex", "crypto"],
            index=0,
            help="stock = NSE India  |  nasdaq/nyse = US stocks  |  forex/crypto = global"
        )

    # ── Row 2: API server URL ─────────────────────────────────────────────────
    api_url = st.text_input(
        "Drawing API URL",
        value="http://localhost:8000",
        help="Base URL of the api_chat_drawing.py server  (POST /api/v1/drawing/chat/)"
    )

    st.markdown("---")
    # ── What to generate ─────────────────────────────────────────────────────
    st.markdown("#### 📋 Select Analysis Tasks")
    st.info(
        "🤖 **AI-Powered Detection**: your selections are converted into a natural-language "
        "message and sent to the Chat Drawing API. The LLM understands context and generates "
        "only the requested drawing types."
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        task_zones    = st.checkbox("Supply/Demand Zones",  value=True)
        task_patterns = st.checkbox("Candlestick Patterns", value=True)
        task_smc      = st.checkbox("SMC (BOS/CHoCH/OB)",  value=False)
    with col2:
        task_fvg      = st.checkbox("Fair Value Gaps (FVG)", value=False)
        task_rsi      = st.checkbox("RSI Signals",           value=True)
        task_bollinger= st.checkbox("Bollinger Bands",       value=False)
    with col3:
        task_macd     = st.checkbox("MACD Crossovers",       value=True)
        task_levels   = st.checkbox("Key Support/Resistance",value=True)

    # Optional custom message (overrides auto-generated one)
    custom_msg = st.text_area(
        "Custom message (optional — overrides checkboxes)",
        placeholder='e.g. "mark supply zones and show RSI overbought levels"',
        height=68,
        help="Leave blank to auto-build from the checkboxes above."
    )

    st.markdown("---")

    # ── Generate button ───────────────────────────────────────────────────────
    if st.button("🚀 Generate Drawings (AI-Powered)", type="primary", use_container_width=True):

        # Build message from checkboxes (unless user typed a custom one)
        if custom_msg.strip():
            final_message = custom_msg.strip()
        else:
            _task_labels = {
                "supply and demand zones":       task_zones,
                "candlestick patterns":          task_patterns,
                "SMC (BOS, CHoCH, order blocks)":task_smc,
                "fair value gaps":               task_fvg,
                "RSI signals":                   task_rsi,
                "Bollinger Bands":               task_bollinger,
                "MACD crossovers":               task_macd,
                "key support and resistance levels": task_levels,
            }
            selected_labels = [lbl for lbl, chk in _task_labels.items() if chk]
            if not selected_labels:
                st.error("❌ Please select at least one analysis task or enter a custom message.")
                st.stop()
            if len(selected_labels) == 1:
                final_message = f"Show me {selected_labels[0]}"
            else:
                final_message = "Show me " + ", ".join(selected_labels[:-1]) + " and " + selected_labels[-1]

        # Compute start / end dates from period
        _period_days = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1825}
        _end_dt   = datetime.now()
        _start_dt = _end_dt - _td(days=_period_days.get(period, 365))
        start_date_str = _start_dt.strftime("%d-%m-%Y")
        end_date_str   = _end_dt.strftime("%d-%m-%Y")

        payload = {
            "message":    final_message,
            "symbol":     symbol_input.strip().upper(),
            "start_date": start_date_str,
            "end_date":   end_date_str,
            "market":     market,
            "timeframe":  timeframe,
        }

        st.markdown(f"**Request →** `{final_message}` | `{symbol_input}` | `{start_date_str}` → `{end_date_str}`")

        with st.spinner(f"🤖 Calling Drawing API for {symbol_input}…"):
            try:
                endpoint = f"{api_url.rstrip('/')}/api/v1/drawing/chat/"
                resp = _req.post(endpoint, json=payload, timeout=180)

                if resp.status_code == 200:
                    result = resp.json()
                    if not result.get("success"):
                        st.error(f"❌ API error: {result.get('message', 'Unknown error')}")
                    else:
                        st.success(
                            f"✅ Generated **{result['total_drawings']}** drawings  "
                            f"| Resolved symbol: `{result.get('resolved_symbol', symbol_input)}`"
                        )
                        st.session_state.drawing_result = result

                        # Intent info
                        intent = result.get("parsed_intent", {})
                        if intent:
                            st.caption(
                                f"🧠 AI understood: *{intent.get('user_wants', '')}*  "
                                f"| Confidence: {intent.get('confidence', 0):.0%}  "
                                f"| Types: {', '.join(result.get('drawing_types_generated', []))}"
                            )

                        # Statistics
                        st.markdown("#### 📊 Generation Statistics")
                        counts = {"zones": 0, "patterns": 0, "indicators": 0, "levels": 0}
                        _pattern_kw = [
                            "engulfing", "doji", "hammer", "star", "shooting",
                            "hanging", "soldiers", "crows", "piercing", "cloud",
                            "harami", "tweezer", "dragonfly", "gravestone"
                        ]
                        for drawing in result["drawings"]:
                            dtype = drawing.get("type", "")
                            if dtype == "LineToolRectangle":
                                counts["zones"] += 1
                            elif dtype == "LineToolHorzLine":
                                counts["levels"] += 1
                            elif dtype == "LineToolNote":
                                text = drawing.get("state", {}).get("text", "").lower()
                                if any(kw in text for kw in _pattern_kw):
                                    counts["patterns"] += 1
                                else:
                                    counts["indicators"] += 1
                            else:
                                counts["indicators"] += 1

                        mc1, mc2, mc3, mc4, mc5 = st.columns(5)
                        mc1.metric("Total", result["total_drawings"])
                        mc2.metric("Zones", counts["zones"])
                        mc3.metric("Patterns", counts["patterns"])
                        mc4.metric("Indicators", counts["indicators"])
                        mc5.metric("Key Levels", counts["levels"])

                elif resp.status_code == 401:
                    err = resp.json().get("detail", {})
                    st.error("❌ API Authentication Error — token expired.")
                    st.info(
                        f"**Fix:** {err.get('fix_instructions', {}).get('step_3', 'Update API_BEARER_TOKEN in .env')}"
                    )
                elif resp.status_code == 422:
                    st.error(f"❌ Validation error: {resp.json()}")
                else:
                    st.error(f"❌ API returned HTTP {resp.status_code}: {resp.text[:300]}")

            except _req.exceptions.ConnectionError:
                st.error(
                    f"❌ Cannot connect to Drawing API at `{api_url}`.  \n"
                    "Make sure **api_chat_drawing.py** is running:  \n"
                    "`python api_chat_drawing.py`"
                )
            except _req.exceptions.Timeout:
                st.error("❌ Request timed out (180 s). The analysis may be taking too long — try a shorter period.")
            except Exception as e:
                st.error(f"❌ Unexpected error: {e}")
                import traceback
                st.code(traceback.format_exc())

    # ── Display Results ───────────────────────────────────────────────────────
    if hasattr(st.session_state, "drawing_result") and st.session_state.drawing_result:
        result = st.session_state.drawing_result

        st.markdown("---")
        st.markdown("#### 📄 Generated JSON")

        tab1, tab2, tab3 = st.tabs(["📊 Summary", "📝 JSON Output", "💾 Download"])

        with tab1:
            st.markdown("##### Drawing Instructions Summary")
            for idx, drawing in enumerate(result["drawings"][:10], 1):
                with st.expander(f"{idx}. {drawing['type']} — {drawing.get('state', {}).get('text', 'N/A')}"):
                    st.json(drawing)
            if len(result["drawings"]) > 10:
                st.info(f"Showing first 10 of {len(result['drawings'])} drawings. Download JSON to see all.")

        with tab2:
            col1, col2 = st.columns([5, 1])
            with col1:
                st.markdown("##### 📝 Complete JSON Output")
            with col2:
                json_str_for_copy = json.dumps(result, indent=2)
                copy_button_html = f"""
                <div style="text-align: right;">
                    <button onclick="copyToClipboard()" style="
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        color: white; border: none; padding: 0.5rem 1rem;
                        font-weight: 600; border-radius: 0.5rem; cursor: pointer;
                        box-shadow: 0 2px 8px rgba(102,126,234,0.3); font-size: 14px;">
                        📋 Copy JSON
                    </button>
                    <div id="copyStatus" style="margin-top:5px;font-size:12px;color:#10b981;display:none;">
                        ✅ Copied!
                    </div>
                </div>
                <script>
                const jsonData = {json.dumps(json_str_for_copy)};
                function copyToClipboard() {{
                    if (navigator.clipboard && navigator.clipboard.writeText) {{
                        navigator.clipboard.writeText(jsonData).then(showCopyStatus, fallbackCopy);
                    }} else {{ fallbackCopy(); }}
                }}
                function fallbackCopy() {{
                    const t = document.createElement('textarea');
                    t.value = jsonData; t.style.position='fixed'; t.style.opacity='0';
                    document.body.appendChild(t); t.select();
                    try {{ document.execCommand('copy'); showCopyStatus(); }} catch(e) {{}}
                    document.body.removeChild(t);
                }}
                function showCopyStatus() {{
                    const s = document.getElementById('copyStatus');
                    s.style.display='block';
                    setTimeout(()=>{{ s.style.display='none'; }}, 2000);
                }}
                </script>"""
                components.html(copy_button_html, height=80)
            st.markdown("---")
            st.json(result)

        with tab3:
            _sym = result.get("symbol", symbol_input)
            _tf  = result.get("timeframe", timeframe)
            json_str = json.dumps(result, indent=2)
            st.download_button(
                label="💾 Download JSON",
                data=json_str,
                file_name=f"drawings_{_sym}_{_tf}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json",
                use_container_width=True,
            )
            st.markdown("---")
            st.markdown("##### 📖 How to Use")
            st.info("""
            **Using the Generated JSON:**

            1. **Download the JSON** file using the button above
            2. **Import into TradingView** — compatible with TradingView's drawing format
            3. **Use with Trading Bots** that accept drawing instructions
            4. **Integrate with your own tools** via the JSON format

            **JSON Structure (TradingView Compatible):**
            - `symbol` / `resolved_symbol`: Stock symbol analyzed
            - `total_drawings`: Number of drawing instructions
            - `drawing_types_generated`: Which analysis types were included
            - `parsed_intent`: LLM's understanding of your request + confidence
            - `drawings`: Array of drawing objects with:
              - `type`: Drawing tool type (LineToolRectangle, LineToolNote, etc.)
              - `state`: Visual properties (colors, text, style)
              - `points`: Price and timestamp coordinates
            """)

elif view_option == "⚙️ System Info":
    # System Info
    st.subheader("🔧 System Information")
    st.info("**Pydantic AI Agent**: Using Google Gemini with 4-key rotation")
    st.info("**Tools**: Stock validation, Q&A, scenario analysis, summaries")
    st.info("**Data Sources**: Yahoo Finance + Tavily web search (screener.in only)")

# Footer
st.markdown("""
<div style="text-align: center; color: #94a3b8; padding: 0.25rem 0; margin: 0; font-size: 0.8rem; border-top: 1px solid #333;">
    <strong>Stock Analysis</strong> | AI-Powered Investment Insights
</div>
""", unsafe_allow_html=True)
