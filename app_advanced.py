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
from utils.sector_helpers import (
    is_banking_sector,
    is_financial_sector,
    sector_inapplicability_note,
)

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

# Load Boxicons (https://boxicons.com) for professional UI icons
st.markdown("""
<link href='https://unpkg.com/boxicons@2.1.4/css/boxicons.min.css' rel='stylesheet'>
<style>
    /* Boxicon sizing + vertical alignment for use inside headings */
    .bx-h { font-size: 1.1em; vertical-align: -2px; margin-right: 0.45rem; color: #74e504; }
    h1 .bx, h2 .bx, h3 .bx, h4 .bx, h5 .bx { vertical-align: -2px; margin-right: 0.45rem; color: #74e504; }
    .bx-accent { color: #74e504; }
    .bx-danger { color: #e53935; }
    .bx-warn { color: #f59e0b; }
</style>
""", unsafe_allow_html=True)


def _company_logo_html(website: str | None, symbol: str, size: int = 36) -> str:
    """Return an <img> of the company logo (Clearbit), with a Boxicon fallback.

    Clearbit's Logo API (https://logo.clearbit.com/{domain}) is free for
    public use and returns a square PNG. If the image fails to load (unknown
    or blocked domain) the onerror handler hides it and reveals a sibling
    Boxicon so the heading still looks reasonable.
    """
    import re as _re
    _fallback = (
        f"<i class='bx bx-bar-chart-alt-2' "
        f"style='color:#74e504;font-size:{size}px;display:none;'></i>"
    )
    if not website:
        return (
            f"<i class='bx bx-bar-chart-alt-2' "
            f"style='color:#74e504;font-size:{size}px;'></i>"
        )
    _m = _re.search(r'https?://(?:www\.)?([^/\s]+)', website.strip())
    _domain = _m.group(1) if _m else website.strip().lstrip('www.')
    _img = (
        f"<img src='https://logo.clearbit.com/{_domain}' alt='{symbol}' "
        f"style='width:{size}px;height:{size}px;border-radius:6px;"
        f"background:#fff;padding:2px;object-fit:contain;' "
        f"onerror=\"this.style.display='none';"
        f"this.nextElementSibling.style.display='inline-block';\" />"
    )
    return f"{_img}{_fallback}"


def bx_header(text: str, icon: str, level: int = 3, color: str = "#74e504") -> None:
    """Render a Streamlit-styled heading prefixed with a Boxicon.

    Args:
        text:  heading text.
        icon:  Boxicon class, e.g. "bx-bar-chart-alt-2" or "bxs-bank".
        level: 1..5 -> <h1>..<h5> (matches st.header / st.subheader / ###).
        color: icon color.
    """
    tag = f"h{max(1, min(5, level))}"
    st.markdown(
        f"<{tag} style='margin:0 0 0.5rem 0;'>"
        f"<i class='bx {icon}' style='color:{color};margin-right:0.45rem;vertical-align:-2px;'></i>"
        f"{text}</{tag}>",
        unsafe_allow_html=True,
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
    
    /* (AUTO_ADVANCE_HIDDEN button CSS removed — video autoplay panel
       was taken out of the Presentation Viewer per client request.) */
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
    bx_header("Current Analysis", "bx-bar-chart-alt-2")
    if st.session_state.current_stock:
        st.success(f"**{st.session_state.current_stock}**")
        
        # PPT Generator - Right below current analysis
        # Check if sentiment analysis has been completed before allowing PPT generation
        if st.button("📄 Generate Presentation", use_container_width=True, type="primary", key="generate_ppt_current"):
            # Get the stock symbol from deps (more reliable than current_stock name)
            stock_symbol = st.session_state.deps.stock_symbol if hasattr(st.session_state.deps, 'stock_symbol') and st.session_state.deps.stock_symbol else None

            if stock_symbol:
                # Gate check — the PPT now builds from three DB columns:
                #   • analyzed_response   (fundamentals, always NOT NULL)
                #   • future_senti        (future-outlook block — populated on every main analysis)
                #   • finrobot_response   (FinRobot deep-analysis memo — populated when
                #                          the user clicks "Run Deep Analysis")
                # The legacy market_senti requirement was removed because the
                # client disabled the Sentiment Analysis pipeline. We still
                # verify the row exists so we fail fast with a clear message.
                try:
                    from database_utility.database import StockDatabase

                    db = StockDatabase()
                    _analysis_row = None
                    if db.connect():
                        _analysis_row = db.get_latest_analysis(stock_symbol)
                        db.disconnect()

                    if not _analysis_row or not _analysis_row.get('analyzed_response'):
                        st.warning("⚠️ Main Analysis Required")
                        st.error(
                            "**No fundamental analysis found for this stock yet.**\n\n"
                            "Run the main search on the Data Dashboard first so the "
                            "`analyzed_response` and `future_senti` rows exist, then "
                            "click **Generate Presentation** again."
                        )
                    else:
                        # Heads-up hints (non-blocking) about the richer content
                        # sources — the PPT still generates without them, just
                        # with less depth in the relevant slides.
                        _hint_msgs: list[str] = []
                        if not (_analysis_row.get('future_senti') or "").strip():
                            _hint_msgs.append(
                                "Future outlook block is empty — the Future Outlook slide will be lighter. "
                                "Run the main analysis again to populate it."
                            )
                        if not (_analysis_row.get('finrobot_response') or "").strip():
                            _hint_msgs.append(
                                "TradingWize deep analysis not saved yet — click **🚀 Run Deep Analysis** "
                                "on the Deep Analysis → TradingWize Agent tab for a richer Recommendation slide."
                            )
                        for _m in _hint_msgs:
                            st.info(_m)

                        with st.spinner(f"🚀 Generating bilingual PPT (English + Hindi) for {st.session_state.current_stock}..."):
                            try:
                                from utils.ppt_generator import StockPPTGenerator
                                # ── Phase-5 timing: PPT Generation ──
                                from utils.timing import (
                                    phase_timer as _phase_timer,
                                    print_summary as _timing_summary,
                                )

                                _ppt_timing_sym = str(stock_symbol).strip().upper()
                                generator = StockPPTGenerator()
                                with _phase_timer("PPT Generation", symbol=_ppt_timing_sym):
                                    result = generator.generate_ppt(stock_symbol)

                                # PPT is the final phase in the usual pipeline,
                                # so emit the per-phase breakdown + grand total
                                # for this symbol once generation finishes.
                                try:
                                    _timing_summary(symbol=_ppt_timing_sym)
                                except Exception as _t_err:
                                    print(f"⚠️ Timing summary failed: {_t_err}")

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
                    st.error(f"❌ Error checking analysis data: {str(e)}")
                    import traceback
                    traceback.print_exc()
            else:
                st.warning("⚠️ Stock symbol not found. Please analyze a stock first.")
        
        # Show language selector and download buttons if PPT was generated
        if hasattr(st.session_state, 'ppt_path_en') and st.session_state.ppt_path_en:
            # Language selector
            st.markdown("---")
            bx_header("Language", "bx-globe")
            
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
                current_view = st.session_state.get("view_selector", "🔬 Deep Analysis")
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
    bx_header("Navigate", "bx-compass")

    # Build view options with distinctive emojis
    # Data Dashboard is the primary landing view — search is embedded on the dashboard.
    view_options = [
        "📈 Data Dashboard",
        "🔬 Deep Analysis",
        "📅 5-Year Analysis",
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
    bx_header("Session Statistics", "bx-line-chart")
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
    bx_header("Quick Actions", "bx-bolt-circle")
    if st.button("🔄 New Analysis", use_container_width=True):
        st.session_state.deps = ConversationState()
        st.session_state.message_history = []  # reset; system prompt managed by agent internally
        st.session_state.messages = []
        st.session_state.current_stock = None
        st.session_state.company_data = None
        st.rerun()
    
# Main content area - render based on sidebar selection
view_option = st.session_state.get("view_selector", "📈 Data Dashboard")

if view_option == "🔬 Deep Analysis":
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

    # Fundamental Analysis - tabs for Trade Ideas and FinRobot.
    # The "💬 Chat", "📈 Sentiment Analysis", and "📊 Option Chain" tabs are
    # preserved in-code behind disable flags so git history stays clean and
    # they can be restored by flipping the corresponding flag.
    fund_tab3, fund_tab4 = st.tabs(["📊 Trade Ideas", "🤖 TradingWize Agent"])
    fund_tab1 = None  # placeholder so the disabled chat block still parses
    fund_tab2 = None  # placeholder so the disabled sentiment block still parses
    fund_tab5 = None  # placeholder so the disabled option chain block still parses
    _CHAT_TAB_DISABLED = True
    _SENTIMENT_TAB_DISABLED = True
    _OPTION_CHAIN_TAB_DISABLED = True

    if not _CHAT_TAB_DISABLED:
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


    if not _SENTIMENT_TAB_DISABLED:
     with fund_tab2:
        # Analytics - Sentiment Analysis
        if st.session_state.company_data:
            data = st.session_state.company_data
            stock_name = data.name
            stock_symbol = data.symbol
        
            # ===== FIRST: Current Market Sentiment Section =====
            bx_header("Current Market Sentiment", "bx-line-chart")
            st.caption("Real-time sentiment from News, Yahoo Finance, Twitter/X, and Reddit")
        
            # Check if sentiment analysis is already cached.
            # Sentiment is normally kicked off in the background from the
            # Data Dashboard as soon as the stock loads, so by the time the
            # user clicks into this tab the result is usually cached. If the
            # background task is still running, show a live-refreshing
            # progress banner. Only fall back to inline analysis if nothing
            # was ever started (e.g. user opened Fundamental Analysis first
            # without visiting the Dashboard).
            from utils.background_tasks import bg_status
            _sent_cached = (
                "sentiment_data" in st.session_state
                and st.session_state.get("sentiment_stock") == stock_symbol
                and st.session_state.sentiment_data is not None
            )
            _sent_bg_status = bg_status("sentiment", stock_symbol)

            if _sent_cached:
                sentiment_data = st.session_state.sentiment_data
            elif _sent_bg_status == "running":
                # Background thread is still working. Poll every 3s until done.
                from streamlit_autorefresh import st_autorefresh
                st_autorefresh(interval=3000, key=f"_sent_poll_{stock_symbol}")
                st.info(
                    "🔄 **Market sentiment analysis is running in the background.**  \n"
                    "It started automatically when you loaded the stock on the Data "
                    "Dashboard. This page will refresh itself every 3 seconds until "
                    "the result is ready (usually 30-90 seconds total)."
                )
                sentiment_data = None
            elif _sent_bg_status == "error":
                _err = st.session_state.get(f"_bg_sentiment_error_{stock_symbol}", "unknown error")
                st.error(f"❌ Background sentiment analysis failed: {_err}")
                if st.button("🔄 Retry sentiment analysis", key="retry_sentiment_from_error"):
                    from utils.background_tasks import reset_bg_status_for_symbol
                    reset_bg_status_for_symbol(stock_symbol)
                    st.rerun()
                sentiment_data = None
            else:
                # Legacy inline path: bg task was never started (e.g. user
                # opened Fundamental Analysis directly without visiting the
                # Dashboard first). Run inline like before — and persist the
                # result to the stock_analysis.market_senti column so the DB
                # row doesn't stay NULL. The background path already does
                # this via persist_market_sentiment; we call the same helper
                # here so both paths end up writing the same rows.
                with st.spinner("🔍 Analyzing market sentiment from multiple sources (News, Yahoo Finance, Reddit, Twitter)..."):
                    from utils.sentiment_analyzer_adanos import analyze_stock_sentiment
                    from utils.background_tasks import persist_market_sentiment
                    try:
                        ticker = stock_symbol.split('.')[0]
                        sentiment_data = analyze_stock_sentiment(stock_name, stock_symbol, ticker)
                        st.session_state.sentiment_data = sentiment_data
                        st.session_state.sentiment_stock = stock_symbol
                        # Persist to DB (best-effort; failures are logged but
                        # never block the UI).
                        persist_market_sentiment(stock_symbol, stock_name, sentiment_data)
                    except Exception as e:
                        st.error(f"❌ Error analyzing sentiment: {e}")
                        sentiment_data = None
        
            if sentiment_data:
                # Backfill DB once per (session, symbol). This catches the
                # case where sentiment was produced before this save-on-inline
                # change shipped, or where the bg thread's DB write failed
                # silently. persist_market_sentiment is idempotent — it will
                # overwrite with the same value if called twice, no harm done.
                _ms_flag = f"_market_senti_persisted_{stock_symbol}"
                if not st.session_state.get(_ms_flag):
                    try:
                        from utils.background_tasks import persist_market_sentiment
                        persist_market_sentiment(stock_symbol, stock_name, sentiment_data)
                        st.session_state[_ms_flag] = True
                    except Exception as _ms_e:
                        print(f"⚠️ market_senti backfill failed for {stock_symbol}: {_ms_e}")

                # Overall Sentiment Score
                bx_header("Overall Market Sentiment", "bx-target-lock", level=3)
            
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
            
                def _bx_metric_label(icon: str, text: str, color: str = "#74e504") -> None:
                    """Render a Boxicon + text label above a collapsed-label st.metric."""
                    st.markdown(
                        f"<div style='font-size:0.85rem;color:#808495;font-weight:500;margin-bottom:-8px;'>"
                        f"<i class='bx {icon}' style='color:{color};margin-right:5px;vertical-align:-2px;'></i>{text}"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

                def _bx_details(title: str, icon: str, icon_color: str, inner_html: str) -> None:
                    """Render a <details>/<summary> disclosure with a Boxicon in the header."""
                    st.markdown(
                        f"""
                        <details style='background:#1a1a1a;border:1px solid #2a2a2a;
                                        border-radius:6px;margin:6px 0 10px 0;'>
                          <summary style='cursor:pointer;padding:10px 14px;font-weight:500;
                                          font-size:14px;color:#e5e7eb;list-style:none;'>
                            <i class='bx {icon}' style='color:{icon_color};margin-right:8px;
                                                        vertical-align:-2px;font-size:1.05em;'></i>{title}
                          </summary>
                          <div style='padding:6px 14px 12px 14px;'>{inner_html}</div>
                        </details>
                        """,
                        unsafe_allow_html=True,
                    )

                with col2:
                    news_score = sentiment_data['news_sentiment']['sentiment_score']
                    news_label = sentiment_data['news_sentiment']['sentiment_label']
                    _bx_metric_label("bxs-news", "News Sentiment")
                    st.metric("News Sentiment", f"{news_score}/100", news_label, label_visibility="collapsed")

                with col3:
                    yahoo_score = sentiment_data['yahoo_sentiment']['sentiment_score']
                    yahoo_rating = sentiment_data['yahoo_sentiment']['analyst_rating']
                    _bx_metric_label("bx-line-chart", "Yahoo Finance", color="#7E1FFF")
                    st.metric("Yahoo Finance", f"{yahoo_score}/100", yahoo_rating, label_visibility="collapsed")

                # Twitter column (if available)
                if has_twitter and has_reddit:
                    with col4:
                        twitter_score = sentiment_data['twitter_sentiment']['sentiment_score']
                        twitter_label = sentiment_data['twitter_sentiment']['sentiment_label']
                        _bx_metric_label("bxl-twitter", "Twitter/X", color="#1DA1F2")
                        st.metric("Twitter/X", f"{twitter_score}/100", twitter_label, label_visibility="collapsed")
                elif has_twitter:
                    with col4:
                        twitter_score = sentiment_data['twitter_sentiment']['sentiment_score']
                        twitter_label = sentiment_data['twitter_sentiment']['sentiment_label']
                        _bx_metric_label("bxl-twitter", "Twitter/X", color="#1DA1F2")
                        st.metric("Twitter/X", f"{twitter_score}/100", twitter_label, label_visibility="collapsed")

                # Reddit column (if available)
                if has_twitter and has_reddit:
                    with col5:
                        reddit_score = sentiment_data['reddit_sentiment']['sentiment_score']
                        reddit_label = sentiment_data['reddit_sentiment']['sentiment_label']
                        _bx_metric_label("bxl-reddit", "Reddit", color="#FF4500")
                        st.metric("Reddit", f"{reddit_score}/100", reddit_label, label_visibility="collapsed")
                elif has_reddit:
                    with col4:
                        reddit_score = sentiment_data['reddit_sentiment']['sentiment_score']
                        reddit_label = sentiment_data['reddit_sentiment']['sentiment_label']
                        _bx_metric_label("bxl-reddit", "Reddit", color="#FF4500")
                        st.metric("Reddit", f"{reddit_score}/100", reddit_label, label_visibility="collapsed")
            
                # Twitter/X and Reddit Sentiment - Side by side in two columns
                st.markdown("---")

                # Create two main columns for Twitter and Reddit
                social_col1, social_col2 = st.columns(2)
            
                # LEFT COLUMN: Twitter/X Sentiment
                with social_col1:
                    if 'twitter_sentiment' in sentiment_data:
                        bx_header("Twitter/X Sentiment", "bxl-twitter", level=3, color="#1DA1F2")
                    
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
                        _cap_style = "color:#808495;font-size:0.875rem;margin:0.25rem 0;"
                        if source == 'rapidapi_twitter':
                            tweet_count = twitter_data.get('tweet_count', 0)
                            st.markdown(f"<div style='{_cap_style}'><i class='bx bx-stats' style='vertical-align:-2px;margin-right:5px;'></i>Based on {tweet_count} recent tweets</div>", unsafe_allow_html=True)
                        elif source == 'news_based_twitter':
                            st.markdown(f"<div style='{_cap_style}'><i class='bx bxs-news' style='vertical-align:-2px;margin-right:5px;'></i>Based on news articles</div>", unsafe_allow_html=True)
                        else:
                            st.markdown(f"<div style='{_cap_style}'><i class='bx bx-bar-chart-alt-2' style='vertical-align:-2px;margin-right:5px;'></i>Twitter sentiment data</div>", unsafe_allow_html=True)
                    
                        # Fixed spacing before sentiment breakdown
                        st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)
                    
                        # Sentiment breakdown in 3 columns
                        tw_col1, tw_col2, tw_col3 = st.columns(3)
                    
                        with tw_col1:
                            positive_pct = twitter_data.get('positive_percentage', 0)
                            _bx_metric_label("bxs-like", "Positive", color="#16a34a")
                            st.metric("Positive", f"{positive_pct}%", label_visibility="collapsed")

                        with tw_col2:
                            negative_pct = twitter_data.get('negative_percentage', 0)
                            _bx_metric_label("bxs-dislike", "Negative", color="#e53935")
                            st.metric("Negative", f"{negative_pct}%", label_visibility="collapsed")

                        with tw_col3:
                            neutral_pct = twitter_data.get('neutral_percentage', 0)
                            _bx_metric_label("bxs-meh", "Neutral", color="#9ca3af")
                            st.metric("Neutral", f"{neutral_pct}%", label_visibility="collapsed")
                    
                        # Show top engaging tweets if available
                        if twitter_data.get('top_tweets'):
                            st.markdown("<br>", unsafe_allow_html=True)
                            import html as _html_tw
                            _tweets = twitter_data['top_tweets'][:5]
                            _tweet_blocks = []
                            for i, tweet in enumerate(_tweets, 1):
                                _tw_label = tweet.get('sentiment_label')
                                if _tw_label == 'Positive':
                                    _sicon = "<i class='bx bxs-check-circle' style='color:#16a34a;margin-right:6px;vertical-align:-2px;'></i>"
                                elif _tw_label == 'Negative':
                                    _sicon = "<i class='bx bxs-error' style='color:#e53935;margin-right:6px;vertical-align:-2px;'></i>"
                                else:
                                    _sicon = "<i class='bx bx-minus-circle' style='color:#9ca3af;margin-right:6px;vertical-align:-2px;'></i>"
                                _safe_text = _html_tw.escape((tweet.get('text') or 'N/A')[:200]) + "..."
                                _block = (
                                    f"<div style='padding:6px 0;'>"
                                    f"<div style='color:#e5e7eb;'>{_sicon}<strong>Tweet {i}:</strong> {_safe_text}</div>"
                                    f"<div style='color:#9ca3af;font-size:12px;margin-top:4px;'>"
                                    f"<i class='bx bxs-heart' style='color:#ef4444;margin-right:4px;vertical-align:-2px;'></i>{tweet.get('favorites', 0)}"
                                    f"&nbsp;&nbsp;|&nbsp;&nbsp;"
                                    f"<i class='bx bx-repost' style='color:#10b981;margin-right:4px;vertical-align:-2px;'></i>{tweet.get('retweets', 0)}"
                                    f"&nbsp;&nbsp;|&nbsp;&nbsp;"
                                    f"<i class='bx bxs-message-rounded' style='color:#6366f1;margin-right:4px;vertical-align:-2px;'></i>{tweet.get('replies', 0)}"
                                    f"</div></div>"
                                )
                                if i < len(_tweets):
                                    _block += "<hr style='border:0;border-top:1px solid #2a2a2a;margin:8px 0;'>"
                                _tweet_blocks.append(_block)
                            _bx_details("Top Engaging Tweets", "bx-fire", "#f97316", "".join(_tweet_blocks))
                    else:
                        bx_header("Twitter/X Sentiment", "bxl-twitter", level=3, color="#1DA1F2")
                        st.info("No Twitter data available")
            
                # RIGHT COLUMN: Reddit Sentiment
                with social_col2:
                    if 'reddit_sentiment' in sentiment_data:
                        bx_header("Reddit Sentiment", "bxl-reddit", level=3, color="#FF4500")
                    
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
                        st.markdown(f"<div style='color:#808495;font-size:0.875rem;margin:0.25rem 0;'><i class='bx bx-stats' style='vertical-align:-2px;margin-right:5px;'></i>Based on {total_posts} posts & {total_items} items</div>", unsafe_allow_html=True)

                        # If Reddit data is unavailable, surface the reason
                        # directly under the score so users understand why
                        # (e.g. RapidAPI monthly quota exhausted, transient
                        # rate-limit, or credentials missing) instead of just
                        # seeing a "50/100 Unavailable" pill with no context.
                        if reddit_data.get('status') == 'unavailable':
                            _reason = (
                                reddit_data.get('unavailable_reason')
                                or reddit_data.get('market_mood')
                                or 'Reddit data temporarily unavailable'
                            )
                            if 'quota' in _reason.lower():
                                st.warning(f"⚠️ **Reddit API quota exhausted.** {_reason}")
                            elif 'rate limit' in _reason.lower():
                                st.info(f"⏱️ {_reason}")
                            elif 'credentials' in _reason.lower():
                                st.error(f"🔑 {_reason}")
                            else:
                                st.info(f"ℹ️ {_reason}")
                    
                        # Fixed spacing before sentiment breakdown (same as Twitter)
                        st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)
                    
                        # Sentiment breakdown in 3 columns
                        rd_col1, rd_col2, rd_col3 = st.columns(3)
                    
                        with rd_col1:
                            positive_pct = reddit_data.get('positive_percentage', 0)
                            _bx_metric_label("bxs-like", "Positive", color="#16a34a")
                            st.metric("Positive", f"{positive_pct}%", label_visibility="collapsed")

                        with rd_col2:
                            negative_pct = reddit_data.get('negative_percentage', 0)
                            _bx_metric_label("bxs-dislike", "Negative", color="#e53935")
                            st.metric("Negative", f"{negative_pct}%", label_visibility="collapsed")

                        with rd_col3:
                            neutral_pct = reddit_data.get('neutral_percentage', 0)
                            _bx_metric_label("bxs-meh", "Neutral", color="#9ca3af")
                            st.metric("Neutral", f"{neutral_pct}%", label_visibility="collapsed")
                    
                        # Show subreddit distribution in expander (like top posts)
                        subreddit_dist = reddit_data.get('subreddit_distribution')
                        if subreddit_dist and isinstance(subreddit_dist, dict):
                            st.markdown("<br>", unsafe_allow_html=True)
                            _sub_cells = []
                            for _sub, _cnt in subreddit_dist.items():
                                _sub_cells.append(
                                    f"<div style='background:#111827;border:1px solid #2a2a2a;"
                                    f"border-radius:6px;padding:10px 12px;'>"
                                    f"<div style='color:#9ca3af;font-size:12px;font-weight:500;'>"
                                    f"<i class='bx bxl-reddit' style='color:#FF4500;margin-right:4px;vertical-align:-2px;'></i>"
                                    f"r/{_sub}</div>"
                                    f"<div style='color:#fff;font-size:18px;font-weight:700;margin-top:2px;'>"
                                    f"{_cnt} posts</div></div>"
                                )
                            _grid = (
                                "<div style='display:grid;grid-template-columns:1fr 1fr;"
                                "gap:8px;'>" + "".join(_sub_cells) + "</div>"
                            )
                            _bx_details("Active Subreddits", "bx-list-ul", "#3b82f6", _grid)
                    
                        # Show top Reddit posts if available
                        if reddit_data.get('top_posts'):
                            import html as _html_rd
                            _posts = reddit_data['top_posts'][:5]
                            _post_blocks = []
                            for i, post in enumerate(_posts, 1):
                                _safe_title = _html_rd.escape(post.get('title', ''))
                                _url = post.get('url', '')
                                _link_html = (
                                    f"<a href='{_html_rd.escape(_url)}' target='_blank' "
                                    f"style='color:#74e504;font-size:12px;text-decoration:none;'>"
                                    f"<i class='bx bx-link-external' style='vertical-align:-2px;"
                                    f"margin-right:3px;'></i>View on Reddit</a>"
                                ) if _url else ""
                                _block = (
                                    f"<div style='padding:6px 0;'>"
                                    f"<div style='color:#e5e7eb;font-weight:600;'>{i}. {_safe_title}</div>"
                                    f"<div style='color:#9ca3af;font-size:12px;margin-top:4px;'>"
                                    f"<i class='bx bxl-reddit' style='color:#FF4500;margin-right:4px;vertical-align:-2px;'></i>"
                                    f"r/{_html_rd.escape(post.get('subreddit', ''))}"
                                    f"&nbsp;&nbsp;|&nbsp;&nbsp;"
                                    f"<i class='bx bxs-upvote' style='color:#ff7a45;margin-right:4px;vertical-align:-2px;'></i>{post.get('score', 0)}"
                                    f"&nbsp;&nbsp;|&nbsp;&nbsp;"
                                    f"<i class='bx bxs-message-rounded' style='color:#6366f1;margin-right:4px;vertical-align:-2px;'></i>{post.get('num_comments', 0)} comments"
                                    f"{'&nbsp;&nbsp;|&nbsp;&nbsp;' + _link_html if _link_html else ''}"
                                    f"</div></div>"
                                )
                                if i < len(_posts):
                                    _block += "<hr style='border:0;border-top:1px solid #2a2a2a;margin:8px 0;'>"
                                _post_blocks.append(_block)
                            _bx_details("Top Reddit Posts", "bx-fire", "#f97316", "".join(_post_blocks))
                    
                        # Show Reddit insights in expander
                        if reddit_data.get('key_insights'):
                            import html as _html_ki
                            _insight_items = "".join(
                                f"<li style='color:#e5e7eb;margin:4px 0;'>"
                                f"<i class='bx bxs-bulb' style='color:#eab308;margin-right:6px;vertical-align:-2px;'></i>"
                                f"{_html_ki.escape(str(_ins))}</li>"
                                for _ins in reddit_data['key_insights']
                            )
                            _insights_html = (
                                f"<ul style='list-style:none;padding-left:0;margin:0;'>"
                                f"{_insight_items}</ul>"
                            )
                            _bx_details("Key Insights", "bxs-bulb", "#eab308", _insights_html)
                    else:
                        bx_header("Reddit Sentiment", "bxl-reddit", level=3, color="#FF4500")
                        st.info("No Reddit data available")
            
                st.markdown("---")
            
                # Sentiment Breakdown
                col1, col2 = st.columns(2)
            
                with col1:
                    bx_header("Positive Factors", "bx-trending-up", level=3, color="#16a34a")
                    positive_points = sentiment_data['news_sentiment'].get('positive_points', [])
                    if positive_points and positive_points != ['Insufficient data']:
                        for point in positive_points:
                            st.markdown(
                                f"<div style='margin:4px 0;'><i class='bx bxs-check-circle' style='color:#16a34a;margin-right:8px;vertical-align:-2px;'></i>{point}</div>",
                                unsafe_allow_html=True,
                            )
                    else:
                        st.info("No significant positive factors identified")

                with col2:
                    bx_header("Negative Factors", "bx-trending-down", level=3, color="#e53935")
                    negative_points = sentiment_data['news_sentiment'].get('negative_points', [])
                    if negative_points and negative_points != ['Insufficient data']:
                        for point in negative_points:
                            st.markdown(
                                f"<div style='margin:4px 0;'><i class='bx bxs-error' style='color:#e53935;margin-right:8px;vertical-align:-2px;'></i>{point}</div>",
                                unsafe_allow_html=True,
                            )
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
                    # Also clear the bg task status so the next render
                    # re-runs the analysis (either via bg or inline).
                    from utils.background_tasks import reset_bg_status_for_symbol
                    reset_bg_status_for_symbol(stock_symbol)
                    st.rerun()
        
            # Note: the legacy "🔮 Future Outlook & News Analysis" section and
            # its companion DB-update block used to live here. They were removed
            # because the Future Outlook is now rendered on the Data Dashboard
            # (below the Expert Opinion card), and duplicating it here caused
            # a cascade of repeated Tavily+LLM calls every 3 seconds whenever
            # the background-sentiment autorefresh fired. The false "Unable
            # to perform sentiment analysis" error that showed up alongside
            # the "running in background" banner was removed for the same
            # reason — the bg-status branches above already surface loading
            # and error states correctly, so a catch-all else here was
            # redundant noise.

            # ═══════════════════════════════════════════════════════
            # FII/DII INSTITUTIONAL SENTIMENT SECTION
            # ═══════════════════════════════════════════════════════
            st.divider()
            bx_header("FII & DII Institutional Sentiment", "bxs-bank")
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
                        from utils.fii_dii_analyzer import (
                            get_fii_dii_sentiment as compute_fii_dii,
                            persist_fii_dii_analysis,
                        )
                        # ── Phase-2 timing: FII/DII Analysis ──
                        from utils.timing import phase_timer as _phase_timer
                        with _phase_timer("FII/DII Analysis", symbol=str(fii_symbol).strip().upper()):
                            fii_result = compute_fii_dii(
                                symbol=fii_symbol,
                                company_name=stock_name,
                                cached_fii=float(cached_fii_val) if cached_fii_val is not None else None,
                                cached_dii=float(cached_dii_val) if cached_dii_val is not None else None,
                            )
                            st.session_state[fii_cache_key] = fii_result
                            # Persist to DB so FinRobot can read it back as context
                            persist_fii_dii_analysis(fii_symbol, fii_result)
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

            bx_header(f"Trade Ideas for {data.name}", "bx-bulb")
            st.caption(f"Top trading ideas from TradingView for {clean_symbol}")

            # Check if trade ideas are cached in session.
            # Trade ideas are kicked off in the background from the Data
            # Dashboard — same pattern as sentiment. If the bg task is still
            # running, show a live-refreshing progress banner; if cached,
            # use it immediately; otherwise fall back to inline scraping.
            cache_key = f"trade_ideas_{clean_symbol}"
            from utils.background_tasks import bg_status as _bg_status_ti
            _ti_cached = (
                cache_key in st.session_state
                and st.session_state.get("trade_ideas_stock") == stock_symbol
                and st.session_state[cache_key] is not None
            )
            _ti_bg_status = _bg_status_ti("trade_ideas", stock_symbol)

            if _ti_cached:
                ideas_result = st.session_state[cache_key]
            elif _ti_bg_status == "running": 
                from streamlit_autorefresh import st_autorefresh
                st_autorefresh(interval=3000, key=f"_ti_poll_{stock_symbol}")
                st.info(
                    "🔄 **Trade ideas are being fetched in the background.**  \n"
                    "Started automatically when you loaded the stock on the Data "
                    "Dashboard. This page refreshes every 3 seconds until ready."
                )
                ideas_result = None
            elif _ti_bg_status == "error":
                _err = st.session_state.get(f"_bg_trade_ideas_error_{stock_symbol}", "unknown error")
                st.error(f"❌ Background trade-ideas fetch failed: {_err}")
                if st.button("🔄 Retry trade ideas", key="retry_trade_ideas_from_error"):
                    from utils.background_tasks import reset_bg_status_for_symbol
                    reset_bg_status_for_symbol(stock_symbol)
                    st.rerun()
                ideas_result = None
            else:
                # Legacy inline path: no bg task was started.
                with st.spinner("🔍 Fetching trade ideas from TradingView..."):
                    try:
                        from utils.tradingview_ideas_scraper import scrape_trade_ideas
                        # ── Phase-3 timing: Trade Ideas (TradingView) ──
                        from utils.timing import phase_timer as _phase_timer
                        with _phase_timer("Trade Ideas (TradingView)", symbol=str(stock_symbol).strip().upper()):
                            ideas_result = scrape_trade_ideas(clean_symbol, exchange, 9)
                        st.session_state[cache_key] = ideas_result
                        st.session_state.trade_ideas_stock = stock_symbol
                        # Chain — kick off the 5-Year Analysis in the
                        # background now that trade_ideas finished, so the
                        # FA tab is pre-warmed by the time the user opens
                        # it. Mirrors the chain inside `_run_trade_ideas`.
                        try:
                            from utils.background_tasks import (
                                _maybe_run_fundamentals_inline,
                            )
                            import threading as _th
                            try:
                                from streamlit.runtime.scriptrunner import (
                                    add_script_run_ctx as _add_ctx,
                                )
                            except Exception:
                                from streamlit.scriptrunner import add_script_run_ctx as _add_ctx  # type: ignore
                            _t = _th.Thread(
                                target=_maybe_run_fundamentals_inline,
                                args=(stock_symbol, st.session_state.get("current_stock_name")),
                                daemon=True,
                                name=f"bg-fundamentals-{stock_symbol}",
                            )
                            try:
                                _add_ctx(_t)
                            except Exception:
                                pass
                            _t.start()
                        except Exception as _bg_err:
                            print(f"⚠️ FA chain from legacy trade_ideas failed: {_bg_err}")
                    except Exception as e:
                        st.error(f"❌ Error fetching trade ideas: {e}")
                        ideas_result = None

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

                    # Escape HTML in user content BEFORE building the <img>
                    # tag — titles like `ITC: Got "Sin Taxed"` contain raw
                    # double-quotes that close the `alt="..."` attribute
                    # early and dump the rest of the markup as visible text.
                    import html as _html_mod
                    safe_title = _html_mod.escape(title, quote=True)
                    safe_desc = _html_mod.escape(description, quote=True)
                    safe_author = _html_mod.escape(author, quote=True)
                    safe_image_url = _html_mod.escape(image_url, quote=True)

                    # Chart image or placeholder
                    has_image = image_url and 's3.tradingview.com' in image_url
                    if has_image:
                        img_block = f'<img class="tv-card-img" src="{safe_image_url}" alt="{safe_title}" loading="lazy" onerror="this.parentElement.innerHTML=\'<div style=padding:40px;text-align:center;color:#9598a1>Chart unavailable</div>\'">'
                    else:
                        img_block = '<div style="width:100%;aspect-ratio:16/10;background:#f0f3fa;display:flex;align-items:center;justify-content:center;color:#9598a1;font-size:14px;">Chart unavailable</div>'

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
                        # Reset bg task status so the fallback inline path runs.
                        from utils.background_tasks import reset_bg_status_for_symbol
                        reset_bg_status_for_symbol(stock_symbol)
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
        # TradingWize Agent — separate chat for the deep analysis pipeline
        st.markdown("### TradingWize Deep Analysis Agent")

        # Initialize FinRobot chat state
        if 'finrobot_messages' not in st.session_state:
            st.session_state.finrobot_messages = []
        # View mode for FinRobot report rendering — "expert" (default, the
        # existing in-depth format) or "plain" (beginner-friendly version).
        if 'finrobot_view_mode' not in st.session_state:
            st.session_state.finrobot_view_mode = "expert"

        # Check if a stock is loaded
        _fr_company_data = st.session_state.get('deps')
        _fr_company_data = getattr(_fr_company_data, 'company_data', None) if _fr_company_data else None
        _fr_stock_name = getattr(_fr_company_data, 'name', None) if _fr_company_data else None
        _fr_stock_symbol = getattr(_fr_company_data, 'symbol', None) if _fr_company_data else None

        if _fr_stock_name:
            st.markdown(f"**Currently loaded:** {_fr_stock_name} (`{_fr_stock_symbol}`)")
        else:
            st.info("Analyze a stock first in the **Chat** tab, then come back here to run TradingWize deep analysis.")

        # ── View Toggle (Expert ⇄ Plain English) ──
        # Show it whenever the chat history contains at least one
        # assistant message that carries a plain-english variant. If no
        # analysis has been run yet, the toggle is hidden so we don't
        # confuse the user before any report exists.
        _fr_has_plain = any(
            isinstance(m, dict) and m.get("role") == "assistant" and m.get("content_plain")
            for m in st.session_state.finrobot_messages
        )
        if _fr_has_plain:
            _vt_col1, _vt_col2 = st.columns([1, 1])
            with _vt_col1:
                if st.button(
                    "🔬 Expert View"
                    + (" ✓" if st.session_state.finrobot_view_mode == "expert" else ""),
                    key="finrobot_view_expert",
                    type=("primary" if st.session_state.finrobot_view_mode == "expert" else "secondary"),
                    use_container_width=True,
                    help="Full numeric memo — ratios, peer multiples, fiscal-tagged financials, and institutional-grade citations. For analysts and investors comfortable with financial terminology.",
                ):
                    st.session_state.finrobot_view_mode = "expert"
                    st.rerun()
            with _vt_col2:
                if st.button(
                    "🧑‍🏫 Plain English"
                    + (" ✓" if st.session_state.finrobot_view_mode == "plain" else ""),
                    key="finrobot_view_plain",
                    type=("primary" if st.session_state.finrobot_view_mode == "plain" else "secondary"),
                    use_container_width=True,
                    help="Beginner-friendly version — everyday analogies, letter grades, and plain-language takeaways. For users new to investing or who prefer a narrative summary.",
                ):
                    st.session_state.finrobot_view_mode = "plain"
                    st.rerun()
            # Purpose description directly beneath the buttons — one line
            # per mode so users can map each button to what it produces
            # without hunting through a single concatenated caption.
            st.markdown(
                "🔬 **Expert View** — full numeric memo: ratios, scores, peer multiples, and institutional-grade citations.  \n"
                "🧑‍🏫 **Plain English** — beginner-friendly analogies, letter grades (A/B/C), and plain-language takeaways.",
                help="Click a button above to switch between the two views. Your choice is remembered for this session.",
            )

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
            <div style="display:flex; align-items:center; gap:1rem; margin-bottom:0.25rem;">
                <div style="display:inline-block; background:{_rec_color}22; border:2px solid {_rec_color};
                            border-radius:0.5rem; padding:0.4rem 1rem; font-size:1.1rem;
                            font-weight:700; color:{_rec_color};">
                    {_r.recommendation}
                </div>
                <span style="color:#666;">Confidence: <b>{_r.confidence}</b> &nbsp;|&nbsp;
                Recommendation Score: <b>{_r.final_score:.1f}/100</b> &nbsp;|&nbsp;
                Horizon: <b>{_r.time_horizon}</b></span>
            </div>
            """, unsafe_allow_html=True)

            # Show the sub-scores that feed the recommendation. Four
            # fundamental tiles plus one sentiment tile so users can see
            # exactly what got blended into the Recommendation Score.
            _f = _fr_report.fundamental
            _s = _fr_report.sentiment
            _sc1, _sc2, _sc3, _sc4, _sc5 = st.columns(5)
            _sc1.metric(
                "Fundamentals — Overall",
                f"{_f.overall_fundamental_score:.1f}" if _f else "—",
                help="Composite fundamental health score (valuation + balance-sheet + growth).",
            )
            _sc2.metric(
                "Valuation",
                f"{_f.valuation_score:.1f}" if _f else "—",
                help="P/E, P/B, EV/EBITDA vs sector norms.",
            )
            _sc3.metric(
                "Financial Health",
                f"{_f.financial_health_score:.1f}" if _f else "—",
                help="Debt/equity, cash reserves, profitability margins.",
            )
            _sc4.metric(
                "Growth",
                f"{_f.growth_score:.1f}" if _f else "—",
                help="Revenue and earnings growth trajectory.",
            )
            _sc5.metric(
                "Future Outlook (input)",
                f"{_s.sentiment_score:.1f}" if _s else "—",
                help="Future-outlook score (derived from the future_senti DB column) fed into the Recommendation Score.",
            )

            st.markdown("---")

        # Chat messages display — the assistant may carry both an "expert"
        # and a "plain" version of the report; pick the one matching the
        # active view mode, falling back to the expert text if the plain
        # variant wasn't produced (e.g. older cached messages).
        _fr_view = st.session_state.finrobot_view_mode
        _fr_use_html = (_fr_view == "plain")  # plain view embeds HTML callouts
        for msg in st.session_state.finrobot_messages:
            with st.chat_message(msg["role"]):
                if msg.get("role") == "assistant" and _fr_view == "plain" and msg.get("content_plain"):
                    st.markdown(msg["content_plain"], unsafe_allow_html=True)
                else:
                    st.markdown(msg.get("content", ""), unsafe_allow_html=_fr_use_html)

        # Run Deep Analysis button (replaces the chat input)
        _fr_run_disabled = not bool(_fr_stock_name)
        _fr_run_clicked = st.button(
            "🚀 Run Deep Analysis",
            key="finrobot_run_deep_analysis",
            type="primary",
            use_container_width=True,
            disabled=_fr_run_disabled,
            help="Run the TradingWize deep-analysis pipeline on the currently loaded stock"
                 if not _fr_run_disabled
                 else "Load a stock on the Data Dashboard first",
        )

        fr_user_input = "Run deep analysis" if _fr_run_clicked else None

        if fr_user_input:
            # Add user message
            st.session_state.finrobot_messages.append({"role": "user", "content": fr_user_input})
            with st.chat_message("user"):
                st.markdown(fr_user_input)

            # Process with FinRobot
            with st.chat_message("assistant"):
                with st.spinner("TradingWize pipeline running..."):
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
                        fr_response_plain = result.get("response_plain", "") or ""
                        fr_report = result.get("report")

                        # Cache report
                        if fr_report and _fr_stock_symbol:
                            st.session_state[f"finrobot_report_{_fr_stock_symbol}"] = fr_report
                            if _fr_company_data:
                                _fr_company_data.finrobot_report = fr_report

                        # Persist the deep-analysis output to the latest
                        # stock_analysis row so the report + its headline
                        # recommendation + final score are available to
                        # downstream consumers (PPT generator, bulk
                        # selector, any future dashboards). Best-effort —
                        # DB errors are logged but don't block the UI.
                        if fr_report and _fr_stock_symbol:
                            try:
                                from database_utility.database import StockDatabase as _FR_DB
                                _fr_db = _FR_DB()
                                if _fr_db.connect():
                                    _fr_db.create_table()
                                    _fr_rec = (
                                        fr_report.reasoning.recommendation
                                        if fr_report.reasoning else None
                                    )
                                    _fr_score = (
                                        float(fr_report.reasoning.final_score)
                                        if fr_report.reasoning else None
                                    )
                                    _fr_db.update_finrobot_columns(
                                        stock_symbol=_fr_stock_symbol,
                                        finrobot_response=fr_response,
                                        finrobot_recommendation=_fr_rec,
                                        finrobot_score=_fr_score,
                                    )
                                    _fr_db.disconnect()
                            except Exception as _fr_db_err:
                                print(f"⚠️ FinRobot DB persist failed for {_fr_stock_symbol}: {_fr_db_err}")

                    except Exception as e:
                        fr_response = f"TradingWize pipeline error: {e}"
                        fr_response_plain = ""

                    # Pick the view that matches the user's current toggle.
                    # Expert = default; Plain English uses HTML callouts so
                    # unsafe_allow_html must be on.
                    _fr_live_view = st.session_state.get("finrobot_view_mode", "expert")
                    if _fr_live_view == "plain" and fr_response_plain:
                        st.markdown(fr_response_plain, unsafe_allow_html=True)
                    else:
                        st.markdown(fr_response)

            # Persist BOTH variants on the message so the toggle can flip
            # between them on subsequent reruns without re-running the LLM.
            st.session_state.finrobot_messages.append({
                "role": "assistant",
                "content": fr_response,
                "content_plain": fr_response_plain,
            })
            st.rerun()

    if not _OPTION_CHAIN_TAB_DISABLED:
     with fund_tab5:
        # ── OPTION CHAIN TAB ──
        bx_header("NSE Option Chain — OI Analysis", "bx-candles", level=2)
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
                    bx_header("Call OI Signal", "bx-trending-up", level=4, color="#16a34a")
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
                    bx_header("Put OI Signal", "bx-trending-down", level=4, color="#e53935")
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

                bx_header("Complete Signal Breakdown", "bx-list-check", level=4)
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

    # Scoped CSS — shrink the oversized Streamlit nav buttons (Previous,
    # Next, Restart from Slide 1) on this page only. The global button
    # styles still apply elsewhere; this block just overrides the
    # height / padding / font-size inside the Presentation Viewer so
    # the nav bar fits on one line at 100% zoom.
    st.markdown("""
    <style>
        /* Compact primary/nav buttons — this view only */
        .stButton > button,
        .stDownloadButton > button {
            min-height: 2.25rem !important;
            height: 2.25rem !important;
            padding: 0.25rem 1rem !important;
            font-size: 0.85rem !important;
            font-weight: 600 !important;
        }
        .stButton > button p,
        .stDownloadButton > button p {
            font-size: 0.85rem !important;
            line-height: 1.1 !important;
            margin: 0 !important;
        }
    </style>
    """, unsafe_allow_html=True)
    
    # Check if PPT was generated (check new bilingual structure first, then fall back to old)
    has_ppt = (hasattr(st.session_state, 'ppt_path_en') and st.session_state.ppt_path_en) or \
              (hasattr(st.session_state, 'ppt_path') and st.session_state.ppt_path)
    
    if not has_ppt:
        st.warning("⚠️ No presentation available")
        st.info("💡 Generate a presentation first by analyzing a stock and clicking 'Generate Presentation' in the sidebar")
        
        if st.button("🔙 Back to Chat", use_container_width=True):
            st.session_state.view_selector = "🔬 Deep Analysis"
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

        # Top controls bar — the old video-synchronized layout
        # (Automatic-mode checkbox + side video panel) was removed per
        # client request; the viewer now just renders the PDF/PPT and
        # lets the user page through it manually.
        col_info, col_restart = st.columns([4, 1])

        with col_info:
            lang_emoji = "🇬🇧" if st.session_state.ppt_language == "english" else "🇮🇳"
            lang_text = "English" if st.session_state.ppt_language == "english" else "हिंदी"
            st.success(f"📁 {ppt_filename} | {lang_emoji} {lang_text} | Slide {st.session_state.current_slide}/{st.session_state.total_slides}")

        with col_restart:
            if st.button("🔄 Restart", use_container_width=True):
                st.session_state.current_slide = 1
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
                # Outer spacer columns keep the buttons compact and
                # centred instead of stretching edge-to-edge.
                _, col_prev, col_next, _ = st.columns([2, 2, 2, 2])

                with col_prev:
                    if st.button("⬅️ Previous", use_container_width=True, disabled=(st.session_state.current_slide <= 1)):
                        st.session_state.current_slide = max(1, st.session_state.current_slide - 1)
                        st.rerun()

                with col_next:
                    if st.button("➡️ Next", use_container_width=True, disabled=(st.session_state.current_slide >= st.session_state.total_slides)):
                        st.session_state.current_slide = min(st.session_state.total_slides, st.session_state.current_slide + 1)
                        st.rerun()

                st.markdown("---")

                # Full-width PDF viewer (the side video panel was removed).
                if True:
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
                                padding: 8px 12px;
                                box-sizing: border-box;
                            }}
                            canvas {{
                                border: 1px solid #ccc;
                                box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                                background: white;
                                margin-bottom: 8px;
                                max-width: 100%;
                                height: auto;
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
                            
                            // Load and render PDF — scale the page so it
                            // fits the iframe width (minus a small
                            // padding) instead of a fixed 1.5x zoom.
                            // This keeps the page visible alongside
                            // the Previous / Next buttons in the same
                            // viewport on any screen size.
                            const loadingTask = pdfjsLib.getDocument({{data: pdfArray}});
                            loadingTask.promise.then(function(pdf) {{
                                console.log('PDF loaded, pages:', pdf.numPages);

                                const pageNumber = {current_page};
                                pdf.getPage(pageNumber).then(function(page) {{
                                    console.log('Page loaded:', pageNumber);

                                    const container = document.getElementById('pdf-container');
                                    container.innerHTML = '';

                                    // Width-fit scaling with a sensible
                                    // cap — prevents absurdly large
                                    // renders on ultrawide monitors.
                                    const baseViewport = page.getViewport({{scale: 1}});
                                    const containerWidth = (container.clientWidth || window.innerWidth) - 24;
                                    const fitScale = Math.min(containerWidth / baseViewport.width, 1.1);
                                    const viewport = page.getViewport({{scale: fitScale}});

                                    // Render sharper on HiDPI screens
                                    // without blowing up CSS size.
                                    const dpr = window.devicePixelRatio || 1;
                                    const canvas = document.createElement('canvas');
                                    const context = canvas.getContext('2d');
                                    canvas.width = Math.floor(viewport.width * dpr);
                                    canvas.height = Math.floor(viewport.height * dpr);
                                    canvas.style.width = viewport.width + 'px';
                                    canvas.style.height = viewport.height + 'px';
                                    context.scale(dpr, dpr);
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

                    # Iframe height sized so the PDF page + the
                    # Previous / Next buttons fit in one viewport at
                    # 100% zoom (was 920px — too tall).
                    components.html(pdf_viewer_html, height=620, scrolling=True)
                    print(f"✅ PDF viewer rendered - Page {current_page} (timestamp: {pdf_timestamp})")
                    
                    # Add download button as fallback
                    st.download_button(
                        label="📥 Download PDF",
                        data=pdf_bytes,
                        file_name=f"presentation_slide_{current_page}.pdf",
                        mime="application/pdf",
                        help="Download the PDF if it's not displaying correctly"
                    )
                
                # Action buttons BELOW the PDF viewer.
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
                        st.session_state.view_selector = "🔬 Deep Analysis"
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
                        st.session_state.view_selector = "🔬 Deep Analysis"
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
                st.session_state.view_selector = "🔬 Deep Analysis"
                st.rerun()

elif view_option == "📈 Data Dashboard":
    # ══════════════════════════════════════════════════════════════
    # DASHBOARD — unified stock analysis interface with embedded search
    # ══════════════════════════════════════════════════════════════
    # Detect the active Streamlit theme so downstream code that needs
    # theme-aware colors (hero welcome state, Plotly chart templates,
    # etc.) can branch on it. Returns "dark" or "light"; falls back to
    # "light" when the option isn't configured.
    try:
        _tw_theme_base = (st.get_option("theme.base") or "light").lower()
    except Exception:
        _tw_theme_base = "light"

    # Skeleton loader + card styles
    st.markdown("""
    <style>
    @keyframes tw_shimmer {
        0%   { background-position: -400px 0; }
        100% { background-position: 400px 0; }
    }
    .tw-skeleton {
        background: linear-gradient(90deg, #1a1a1a 0%, #2a2a2a 50%, #1a1a1a 100%);
        background-size: 800px 100%;
        animation: tw_shimmer 1.4s infinite linear;
        border-radius: 8px;
    }
    .tw-welcome {
        background: #0f0f0f;
        border: 1px dashed #2a2a2a;
        border-radius: 12px;
        padding: 48px 24px;
        text-align: center;
        color: #888;
        margin-top: 12px;
    }
    .tw-welcome-title { color: #fff; font-size: 20px; font-weight: 600; margin-bottom: 8px; }
    .tw-welcome-sub   { color: #888; font-size: 14px; }
    .tw-variant-card {
        background: #1a1a1a;
        border: 1px solid #2a2a2a;
        border-radius: 10px;
        padding: 14px 18px;
        margin: 10px 0 4px 0;
    }
    .tw-variant-title { color: #fff; font-weight: 600; font-size: 14px; margin-bottom: 8px; }
    </style>
    """, unsafe_allow_html=True)

    # ── Future-sentiment DB persister ────────────────────────────────
    # Called after the parallel news-analysis finishes successfully.
    # Composes a compact text block from the distilled outlook_data (or
    # the raw analysis if distillation failed) and UPDATEs the
    # stock_analysis.future_senti + future_senti_status columns on the
    # latest row for the given symbol. Best-effort — swallows DB errors.
    def _build_future_senti_text(stock_name: str, news_result: dict) -> tuple[str, str]:
        """Return (text, status) for the future_senti DB columns.
        Status is derived from outlook verdict — "bullish"/"bearish"/"neutral".
        """
        _od = news_result.get("outlook_data") or {}
        _verdict = _od.get("outlook", "") or ""
        _low = _verdict.lower()
        _status = "bullish" if "bullish" in _low else (
            "bearish" if "bearish" in _low else "neutral"
        )

        _lines = [f"🔮 Future Outlook & News Analysis for {stock_name}", ""]

        if _verdict:
            _lines.append(
                f"Overall Outlook: {_od.get('outlook_emoji', '')} {_verdict}".strip()
            )
            _lines.append("")

        _av = (_od.get("analyst_view") or "").strip()
        if _av:
            _lines += ["Analyst & Market View:", _av, ""]

        _perf = (_od.get("performance") or "").strip()
        if _perf:
            _lines += ["Recent Financial Performance:", _perf, ""]

        _drivers = _od.get("growth_drivers") or []
        if _drivers:
            _lines.append("🟢 Growth Drivers:")
            for _d in _drivers:
                _lines.append(f"  • {_d}")
            _lines.append("")

        _risks = _od.get("risk_factors") or []
        if _risks:
            _lines.append("🔴 Risk Factors:")
            for _r in _risks:
                _lines.append(f"  • {_r}")
            _lines.append("")

        _tp = (_od.get("target_price") or "").strip()
        _cons = (_od.get("consensus") or "").strip()
        if _tp and _tp.lower() != "not available":
            _lines.append(f"🎯 Analyst Price Target: {_tp}")
        if _cons and _cons.lower() != "not available":
            _lines.append(f"📊 Analyst Consensus: {_cons}")

        # Fallback to the raw analysis text if distillation produced
        # nothing — still better than leaving the column empty.
        if not _od:
            _raw = (news_result.get("analysis") or "").strip()
            if _raw:
                _lines.append(_raw)

        return "\n".join(_lines).strip(), _status

    def _persist_future_sentiment(stock_symbol: str, stock_name: str, news_result: dict) -> None:
        """Best-effort UPDATE of future_senti + future_senti_status columns."""
        try:
            _text, _status = _build_future_senti_text(stock_name, news_result)
            if not _text:
                return
            from database_utility.database import StockDatabase
            _db = StockDatabase()
            if _db.connect():
                _db.update_sentiment_columns(
                    stock_symbol=stock_symbol,
                    future_senti=_text,
                    future_senti_status=_status,
                )
                _db.disconnect()
        except Exception as _e:
            print(f"⚠️ future_senti DB persist failed for {stock_symbol}: {_e}")

    # ── Structured outlook distiller — used by the news-analysis pipeline ──
    # Defined here (top of dashboard view) so both the agent-call block
    # and the Refresh-button handler further down can reference it.
    def _distill_outlook(raw_result: dict, query: str) -> dict:
        """Condense the full news analysis into a structured outlook dict
        with sections: verdict, analyst view, performance highlights,
        growth drivers, risk factors, and target/consensus. Returns a
        dict (or empty dict on failure).

        Uses a model fallback chain (same as the sentiment classifier)
        and a generous token budget (1800) to avoid the truncated-JSON
        bug that hit with the previous 900-token limit.
        """
        _body_parts: list[str] = []
        _analysis = (raw_result.get("analysis") or "").strip()
        _tavily = (raw_result.get("tavily_summary") or "").strip()
        if _analysis:
            _body_parts.append(_analysis)
        if _tavily:
            _body_parts.append(_tavily)
        if not _body_parts:
            return {}

        _combined = "\n\n".join(_body_parts)[:8000]

        _sys = (
            "You are a senior equity research analyst. "
            "Read the report and return a JSON object with EXACTLY these keys:\n"
            "  outlook: \"Strongly Bullish\"|\"Moderately Bullish\"|\"Neutral\"|\"Moderately Bearish\"|\"Strongly Bearish\"\n"
            "  outlook_emoji: \"🟢\" (bullish) | \"🟡\" (neutral) | \"🔴\" (bearish)\n"
            "  analyst_view: 2-3 sentences — analyst names, targets, ratings\n"
            "  performance: 2-3 sentences — recent quarter numbers, YoY changes\n"
            "  growth_drivers: array of 3-5 short strings (1 sentence each, include numbers)\n"
            "  risk_factors: array of 2-4 short strings (1 sentence each, include numbers)\n"
            "  target_price: e.g. \"₹3,800 (13% upside)\" or \"Not available\"\n"
            "  consensus: e.g. \"32 Buy / 10 Hold / 4 Sell\" or \"Not available\"\n\n"
            "RULES: Be specific with numbers from the text. Do NOT invent data. "
            "Keep each growth_driver/risk_factor to ONE sentence max. "
            "Return ONLY valid JSON — no markdown fences, no extra text."
        )
        _usr = (
            f"Full future-outlook report for {query}:\n\n"
            f"{_combined}\n\n"
            "Return ONLY the JSON object."
        )

        _models = [
            "openai/gpt-oss-120b",
            "google/gemini-2.0-flash-001",
            "meta-llama/llama-3.1-8b-instruct",
            "openai/gpt-oss-20b",
        ]

        import json as _json
        import re as _re
        from utils.model_config import guarded_llm_call as _g

        for _model in _models:
            try:
                _resp = _g(
                    messages=[
                        {"role": "system", "content": _sys},
                        {"role": "user", "content": _usr},
                    ],
                    model=_model,
                    temperature=0.2,
                    max_tokens=1800,
                )
                _raw = _resp.choices[0].message.content.strip() if _resp and _resp.choices else ""
                if not _raw:
                    print(f"⚠️ Outlook distill: {_model} returned empty — trying next")
                    continue
                # Strip code fences
                if _raw.startswith("```"):
                    _raw = _re.sub(r"^```(?:json)?\s*", "", _raw, count=1)
                    _raw = _re.sub(r"\s*```\s*$", "", _raw, count=1)
                _obj = _json.loads(_raw)
                if isinstance(_obj, dict) and "outlook" in _obj:
                    print(f"✅ Distilled structured outlook via {_model}: {_obj.get('outlook')}")
                    return _obj
                print(f"⚠️ Outlook distill: {_model} returned JSON without 'outlook' key — trying next")
            except _json.JSONDecodeError as _je:
                print(f"⚠️ Outlook distill: {_model} JSON parse error ({_je}) — trying next")
            except Exception as _e:
                print(f"⚠️ Outlook distill: {_model} failed ({_e}) — trying next")

        print("⚠️ All models failed for outlook distillation — returning empty")
        return {}

    # ── Search-bar state ──────────────────────────────────────────
    st.session_state.setdefault("dash_is_loading", False)
    st.session_state.setdefault("dash_pending_query", None)
    st.session_state.setdefault("dash_variants", [])
    st.session_state.setdefault("dash_error", None)
    st.session_state.setdefault("dash_parsed", None)  # parsed agent text
    st.session_state.setdefault("dash_news_analysis", None)
    st.session_state.setdefault("dash_news_analysis_symbol", None)
    st.session_state.setdefault("dash_active_tab", "🏢 Snapshot")

    # ── Search bar ────────────────────────────────────────────────
    _search_col, _btn_col = st.columns([6, 1])
    with _search_col:
        _q = st.text_input(
            "Search stock",
            key="dash_search_input",
            placeholder="Search any stock or company... (e.g., 'TCS', 'Reliance', 'INFY.NS')",
            label_visibility="collapsed",
            disabled=st.session_state.dash_is_loading,
        )
    with _btn_col:
        _go = st.button(
            "🔍 Search",
            use_container_width=True,
            type="primary",
            disabled=st.session_state.dash_is_loading,
        )

    if (_go or (_q and _q != st.session_state.get("_dash_last_q", ""))) and _q.strip():
        st.session_state._dash_last_q = _q
        st.session_state.dash_pending_query = _q.strip()
        st.session_state.dash_is_loading = True
        st.session_state.dash_error = None
        st.session_state.dash_variants = []
        # Clear any previous stock's cached view so a partial/failed re-analysis
        # can't leave stale fields (e.g. wrong dividend yield, empty holdings)
        # visible on the dashboard while the new search is running.
        st.session_state.company_data = None
        st.session_state.dash_parsed = None
        st.session_state._dash_last_raw_response = None
        st.session_state.dash_news_analysis = None
        st.session_state.dash_news_analysis_symbol = None
        # Reset the per-symbol enrichment flag so the new stock's yfinance
        # gap-fill runs fresh instead of being skipped as "already enriched".
        for _k in [k for k in st.session_state.keys() if k.startswith("_dash_enriched_")]:
            del st.session_state[_k]
        # Clear any cached OHLC candlestick dataframes from previous searches.
        for _k in [k for k in st.session_state.keys() if k.startswith("_dash_ohlc_")]:
            del st.session_state[_k]
        st.rerun()

    # ── Error banner ──────────────────────────────────────────────
    if st.session_state.dash_error:
        st.error(f"❌ {st.session_state.dash_error}")

    # ── Multi-stock selection card ────────────────────────────────
    if st.session_state.dash_variants and not st.session_state.dash_is_loading:
        st.markdown(
            '<div class="tw-variant-card">'
            '<div class="tw-variant-title">Multiple stocks found — select one to analyze</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        for idx, variant in enumerate(st.session_state.dash_variants):
            _vname = variant.get("name", "Unknown")
            _vticker = variant.get("ticker") or variant.get("symbol", "")
            if st.button(
                f"{idx + 1}. {_vname}  ·  {_vticker}",
                key=f"dash_variant_{idx}",
                use_container_width=True,
            ):
                st.session_state.dash_pending_query = _vticker
                st.session_state.dash_is_loading = True
                st.session_state.dash_variants = []
                st.session_state.company_data = None
                st.session_state.dash_parsed = None
                for _k in [k for k in st.session_state.keys() if k.startswith("_dash_enriched_")]:
                    del st.session_state[_k]
                st.rerun()
        if st.button("✖ Dismiss", key="dash_variant_dismiss"):
            st.session_state.dash_variants = []
            st.rerun()

    # ── Agent call (runs when a query is pending) ─────────────────
    if st.session_state.dash_pending_query:
        _pending = st.session_state.dash_pending_query
        st.session_state.dash_pending_query = None

        # Show skeleton loaders while waiting
        _sk_placeholder = st.empty()
        with _sk_placeholder.container():
            st.markdown(
                '<div class="tw-skeleton" style="height:380px;margin:12px 0;"></div>'
                '<div style="display:flex;gap:12px;margin:12px 0;">'
                '<div class="tw-skeleton" style="flex:1;height:100px"></div>'
                '<div class="tw-skeleton" style="flex:1;height:100px"></div>'
                '<div class="tw-skeleton" style="flex:1;height:100px"></div>'
                '<div class="tw-skeleton" style="flex:1;height:100px"></div>'
                '</div>'
                '<div class="tw-skeleton" style="height:220px;margin:12px 0;"></div>'
                '<div class="tw-skeleton" style="height:160px;margin:12px 0;"></div>',
                unsafe_allow_html=True,
            )

        import asyncio as _asyncio
        import concurrent.futures as _cf
        from utils.parse_agent_response import (
            parse_agent_response,
            is_multi_stock_response,
            parse_multi_stock_options,
        )
        from tools import StockTools as _DashStockTools

        # Ensure session-state scaffolding the agent expects
        if "message_history" not in st.session_state:
            st.session_state.message_history = []
        if "deps" not in st.session_state:
            st.session_state.deps = ConversationState()

        _deps = st.session_state.deps
        _deps.current_user_input = _pending
        _deps.validation_done_this_turn = False
        _deps.last_analysis_response = None
        _deps.last_validation_response = None
        # Force a fresh analysis for each new dashboard search
        _deps.analysis_complete = False
        _deps.company_data = None
        _deps.stock_symbol = None
        _deps.stock_name = None
        _deps.pending_variants = None
        _deps.report_generated = False
        # Don't carry chat-era history into dashboard searches — tools will skip work if they think
        # the stock was already analyzed in the conversation.
        _local_history: list = []

        async def _dash_run_agent(query: str):
            try:
                _res = await agent.run(
                    query,
                    message_history=_local_history,
                    deps=_deps,
                )
                return _res, None
            except Exception as e:
                return None, str(e)

        def _dash_run_news_analysis(query: str):
            """Parallel Future-Outlook news analysis fetcher. Runs alongside the
            main agent so the extra Tavily + LLM cost is fully overlapped with
            the stock-data pipeline instead of adding serial latency.

            After the full Tavily+LLM report is fetched, an extra LLM call
            distils it into a structured outlook dict (verdict, analyst view,
            performance, drivers, risks, target) stored under ``outlook_data``
            so the dashboard can render a rich card instead of raw text.
            """
            try:
                _result = _DashStockTools.get_stock_news_analysis(query, max_articles=5)
                if _result and not _result.get("error"):
                    _result["outlook_data"] = _distill_outlook(_result, query)
                return _result
            except Exception as _e:
                print(f"⚠️ Dashboard news analysis failed: {_e}")
                return {"error": str(_e)}

        # Timeout budget: cold-cache runs can realistically take 4–6 minutes because
        # the agent fans out to screener.in, Tavily, yfinance, Perplexity (competitors),
        # news, validation retries, missing-field LLM gap-fill, expert opinion, and
        # PDF summarisation. 360s gives comfortable headroom.
        _DASH_TIMEOUT_SECS = 360
        _NEWS_TIMEOUT_SECS = 120  # news analysis is ~30–90s; allow some headroom

        _raw_response = ""
        _err = None
        _result = None
        _news_result: dict | None = None
        _timed_out = False
        try:
            # max_workers=2 so the news analysis runs concurrently with the agent
            # instead of being queued behind it.
            with _cf.ThreadPoolExecutor(max_workers=2) as _ex:
                _fut = _ex.submit(lambda: _asyncio.run(_dash_run_agent(_pending)))
                _news_fut = _ex.submit(_dash_run_news_analysis, _pending)
                try:
                    _result, _err = _fut.result(timeout=_DASH_TIMEOUT_SECS)
                except _cf.TimeoutError:
                    # ThreadPoolExecutor.__exit__ still blocks on shutdown(wait=True)
                    # until the background task completes — Python can't kill a
                    # running thread. That means by the time we leave this `with`
                    # block the tool WILL have finished and `deps.last_analysis_response`
                    # should be populated. Keep going to the cached-response check
                    # below instead of aborting immediately.
                    print(f"⏰ Dashboard agent.run exceeded {_DASH_TIMEOUT_SECS}s — will recover from tool cache.")
                    _timed_out = True

                # Harvest the news analysis result. It ran fully in parallel with
                # the agent so its wall-clock cost is already absorbed. Use a
                # short secondary wait — if it's still chewing after the agent
                # finishes, give it a bit more time, otherwise move on.
                try:
                    _news_result = _news_fut.result(timeout=_NEWS_TIMEOUT_SECS)
                except _cf.TimeoutError:
                    print(f"⏰ Dashboard news analysis exceeded {_NEWS_TIMEOUT_SECS}s — rendering without it.")
                    _news_result = None
                except Exception as _ne:
                    print(f"⚠️ Dashboard news analysis errored: {_ne}")
                    _news_result = None
        except Exception as e:
            _err = f"Error: {e}"

        # Authoritative response source: the tool-cached output on deps. The analysis
        # tool writes here as soon as it finishes, so this is set even when the
        # pydantic-ai wrapper errors or we hit the timeout above.
        _cached_a = getattr(_deps, "last_analysis_response", None)
        _cached_v = getattr(_deps, "last_validation_response", None)
        if _cached_a:
            _raw_response = _cached_a
            _err = None
            _timed_out = False
        elif _cached_v:
            _raw_response = _cached_v
            _err = None
            _timed_out = False
        elif _result is not None and not _err:
            _raw_response = getattr(_result, "output", None) or getattr(_result, "data", "") or ""

        if isinstance(_raw_response, ToolResponse):
            _raw_response = _raw_response.content or ""
        if isinstance(_raw_response, str) and _raw_response.startswith("FINAL_ANSWER:\n"):
            _raw_response = _raw_response[len("FINAL_ANSWER:\n"):]
        if _raw_response and not isinstance(_raw_response, str):
            _raw_response = str(_raw_response)

        # If we have company_data on deps, analysis effectively succeeded regardless
        # of what the wrapper reported — clear any residual error state.
        if getattr(_deps, "company_data", None):
            _err = None
            _timed_out = False

        if _timed_out and not _raw_response:
            _err = f"Analysis exceeded {_DASH_TIMEOUT_SECS} seconds. Please try again."

        _sk_placeholder.empty()
        st.session_state.dash_is_loading = False

        if _err and not _raw_response and not getattr(_deps, "company_data", None):
            st.session_state.dash_error = f"Could not fetch data for '{_pending}'. {_err}"
            st.rerun()

        # Multi-stock selection: detect either via text pattern or via pending_variants
        # that the validation tool populated when multiple matches exist.
        _has_variants = bool(getattr(_deps, "pending_variants", None)) and not _deps.company_data
        if _has_variants or (_raw_response and is_multi_stock_response(_raw_response)):
            _opts = parse_multi_stock_options(_raw_response) if _raw_response else []
            if not _opts and getattr(_deps, "pending_variants", None):
                _opts = [
                    {"name": v.get("name", ""), "ticker": v.get("symbol", "")}
                    for v in _deps.pending_variants
                ]
            if _opts:
                st.session_state.dash_variants = _opts
                st.rerun()

        # Full analysis — persist company_data + parsed text, then rerun
        if _deps.company_data:
            st.session_state.company_data = _deps.company_data
            if _deps.stock_name:
                st.session_state.current_stock = _deps.stock_name
            st.session_state.dash_parsed = parse_agent_response(_raw_response) if _raw_response else None
            # Keep the raw response so downstream render code can recover values
            # that aren't in the structured CompanyData (e.g. Indian Promoter /
            # FII / DII holdings when a cached analysis came back without them).
            st.session_state._dash_last_raw_response = _raw_response or ""
            # Persist the parallel news analysis keyed by symbol so the dashboard
            # renders the Future Outlook section without re-fetching on every rerun.
            if _news_result and not _news_result.get("error"):
                st.session_state.dash_news_analysis = _news_result
                st.session_state.dash_news_analysis_symbol = _deps.company_data.symbol
                # Persist the future-outlook summary to the stock_analysis
                # row for this symbol so FinRobot / PPT generator / any other
                # consumer that reads `future_senti` from the DB sees real
                # data instead of NULL. Best-effort — DB errors are logged
                # but don't interrupt the UI render.
                try:
                    _persist_future_sentiment(
                        _deps.company_data.symbol,
                        _deps.company_data.name,
                        _news_result,
                    )
                except Exception as _fs_err:
                    print(f"⚠️ future_senti DB persist failed: {_fs_err}")
            elif _news_result and _news_result.get("error"):
                # Keep the error around so the section can show "couldn't fetch".
                st.session_state.dash_news_analysis = _news_result
                st.session_state.dash_news_analysis_symbol = _deps.company_data.symbol
        elif not _raw_response:
            # Agent returned nothing and produced no structured data — surface an error
            st.session_state.dash_error = f"Could not analyze '{_pending}'. Please try a different query."
        st.rerun()

    if st.session_state.company_data:
        data = st.session_state.company_data
        _parsed = st.session_state.get("dash_parsed") or {}
        _website = getattr(getattr(data, 'snapshot', None), 'website', None) or ''
        st.markdown(
            f"<h3 style='margin:0 0 0.5rem 0;'>"
            f"<span>{data.name}</span>"
            f"</h3>",
            unsafe_allow_html=True,
        )

        # Background task kickoff used to fire here (at the top of the
        # dashboard render). That caused the trade-ideas subprocess to
        # race with the dashboard's own yfinance / screener enrichment
        # and frequently return an empty result that got cached as
        # success. The kickoff is now deferred to the END of this
        # `if st.session_state.company_data:` block (just after the
        # FII/DII section) so every dashboard widget has finished its
        # own network work before the trade-ideas scraper is spawned.

        # Auto-enrich from yfinance if key dashboard fields are missing (e.g. DB cache hit)
        _fin = data.financials
        _md = data.market_data
        _needs_enrich = (
            not getattr(_fin, 'ebitda', None) or
            not getattr(_fin, 'eps', None) or
            not _md.price_history or
            not getattr(_fin, 'total_assets', None) or
            not getattr(_fin, 'total_liabilities', None) or
            not getattr(_fin, 'total_debt', None) or
            not getattr(_fin, 'cash_balance', None) or
            not getattr(_fin, 'operating_cash_flow', None) or
            not getattr(_fin, 'enterprise_value', None) or
            not getattr(_fin, 'ev_ebitda', None)
        )
        if _needs_enrich and data.symbol and not st.session_state.get(f'_dash_enriched_{data.symbol}'):
            try:
                import math
                import yfinance as yf
                _dash_tk = yf.Ticker(data.symbol)
                _dash_info = _dash_tk.info or {}
                _dash_hist = _dash_tk.history(period="1y")

                def _clean(v):
                    """Strip NaN / None / non-numeric values that sneak in from yfinance."""
                    if v is None:
                        return None
                    try:
                        f = float(v)
                    except (TypeError, ValueError):
                        return None
                    if math.isnan(f) or math.isinf(f):
                        return None
                    return f

                # ── Income / cash-flow fields from info ──
                if not getattr(_fin, 'ebitda', None):
                    _fin.ebitda = _clean(_dash_info.get('ebitda'))
                if not getattr(_fin, 'eps', None):
                    _fin.eps = _clean(_dash_info.get('trailingEps'))
                if not getattr(_fin, 'free_cash_flow', None):
                    _fin.free_cash_flow = _clean(_dash_info.get('freeCashflow'))
                if not getattr(_fin, 'operating_cash_flow', None):
                    _fin.operating_cash_flow = _clean(_dash_info.get('operatingCashflow'))
                if not getattr(_fin, 'total_debt', None):
                    _fin.total_debt = _clean(_dash_info.get('totalDebt'))
                if not getattr(_fin, 'cash_balance', None):
                    _fin.cash_balance = _clean(_dash_info.get('totalCash'))
                if not getattr(_fin, 'enterprise_value', None):
                    _fin.enterprise_value = _clean(_dash_info.get('enterpriseValue'))
                if not getattr(_fin, 'ev_ebitda', None):
                    _fin.ev_ebitda = _clean(_dash_info.get('enterpriseToEbitda'))
                if not getattr(_fin, 'pb_ratio', None):
                    _fin.pb_ratio = _clean(_dash_info.get('priceToBook'))

                # ── Market-data fields from info (volume / beta) ──
                # These come straight from yfinance and the cache-hit builder
                # usually fills them, but the safety net here covers any path
                # that left them empty (e.g. a partial CompanyData rebuild).
                if not getattr(_md, 'volume', None):
                    _vol = _clean(_dash_info.get('volume'))
                    _md.volume = int(_vol) if _vol else None
                if not getattr(_md, 'avg_volume', None):
                    _avg_vol = _clean(_dash_info.get('averageVolume'))
                    _md.avg_volume = int(_avg_vol) if _avg_vol else None
                if not getattr(_md, 'beta', None):
                    _md.beta = _clean(_dash_info.get('beta'))

                # ── Balance-sheet fields (not in info) from the balance_sheet DataFrame ──
                #    yfinance returns a DataFrame with row labels like "Total Assets",
                #    "Total Liabilities Net Minority Interest", etc. Most recent column first.
                _missing_bs = (
                    not getattr(_fin, 'total_assets', None)
                    or not getattr(_fin, 'total_liabilities', None)
                    or not getattr(_fin, 'total_debt', None)
                    or not getattr(_fin, 'cash_balance', None)
                )
                if _missing_bs:
                    try:
                        _bs = _dash_tk.balance_sheet
                        if _bs is not None and not _bs.empty:
                            _bs_col = _bs.columns[0]

                            def _bs_lookup(*needles: str):
                                """Return the first numeric row whose label contains every needle."""
                                for idx in _bs.index:
                                    label = str(idx).lower()
                                    if all(n in label for n in needles):
                                        val = _clean(_bs[_bs_col].get(idx))
                                        if val is not None:
                                            return val
                                return None

                            if not getattr(_fin, 'total_assets', None):
                                _fin.total_assets = _bs_lookup("total", "assets")
                            if not getattr(_fin, 'total_liabilities', None):
                                _fin.total_liabilities = _bs_lookup("total", "liabilities")
                            if not getattr(_fin, 'total_debt', None):
                                _fin.total_debt = _bs_lookup("total", "debt")
                            if not getattr(_fin, 'cash_balance', None):
                                _fin.cash_balance = (
                                    _bs_lookup("cash", "equivalent")
                                    or _bs_lookup("cash", "short term")
                                    or _bs_lookup("cash")
                                )
                    except Exception as _bs_err:
                        print(f"⚠️ balance_sheet fetch failed: {_bs_err}")

                # ── operating_cash_flow from cashflow DataFrame if info missed it ──
                if not getattr(_fin, 'operating_cash_flow', None):
                    try:
                        _cf_df = _dash_tk.cashflow
                        if _cf_df is not None and not _cf_df.empty:
                            _cf_col = _cf_df.columns[0]
                            for idx in _cf_df.index:
                                _lab = str(idx).lower()
                                if "operat" in _lab and "cash" in _lab:
                                    _v = _clean(_cf_df[_cf_col].get(idx))
                                    if _v is not None:
                                        _fin.operating_cash_flow = _v
                                        break
                    except Exception as _cf_err:
                        print(f"⚠️ cashflow fetch failed: {_cf_err}")

                # ── Compute ev_ebitda if we now have both pieces ──
                if not getattr(_fin, 'ev_ebitda', None) and _fin.enterprise_value and _fin.ebitda:
                    try:
                        _fin.ev_ebitda = _fin.enterprise_value / _fin.ebitda
                    except Exception:
                        pass

                # ── Price history ──
                if not _md.price_history and not _dash_hist.empty:
                    _md.price_history = {
                        str(dt.date()): float(row["Close"])
                        for dt, row in _dash_hist.iterrows()
                    }

                # ── Overall high/low from history ──
                if not _dash_hist.empty:
                    if not getattr(_md, 'overall_high', None):
                        _md.overall_high = float(_dash_hist['High'].max())
                    if not getattr(_md, 'overall_low', None):
                        _md.overall_low = float(_dash_hist['Low'].min())
                    if _md.overall_high and _md.current_price:
                        _md.percentage_change_from_high = round(
                            ((_md.current_price - _md.overall_high) / _md.overall_high) * 100, 2
                        )

                # Note: Indian promoter / FII / DII holdings come from screener.in via the
                # agent's scraper (tools.py). yfinance only exposes a single
                # `heldPercentInstitutions` field which is a different metric (combined
                # institutional ownership under US reporting rules), so we intentionally
                # do NOT fall back to it — displaying a dash is more honest than showing
                # a misleading number. If the screener.in scrape failed upstream, the
                # Holdings row on the Market Data tab will show "—" for those fields.

                st.session_state[f'_dash_enriched_{data.symbol}'] = True
            except Exception as _e:
                print(f"⚠️ Dashboard enrichment failed: {_e}")

        col1, col2 = st.columns([2, 1])

        # -------- Price Trend (TradingView-style candlestick) --------
        with col1:
            # ── Fetch OHLC data (yfinance first, mentor API as fallback) ──
            # Cached per-symbol on session_state so the period-button reruns
            # don't re-fetch; cleared when a new stock is searched.
            _ohlc_cache_key = f"_dash_ohlc_{data.symbol}"
            _ohlc_df = st.session_state.get(_ohlc_cache_key)

            if _ohlc_df is None:
                import pandas as _pd
                # Try yfinance first — it's free, reliable, and already
                # used elsewhere in the pipeline.
                try:
                    import yfinance as _yf
                    _hist = _yf.Ticker(data.symbol).history(period="2y", interval="1d")
                    if _hist is not None and not _hist.empty:
                        _ohlc_df = _hist[["Open", "High", "Low", "Close", "Volume"]].copy()
                        print(f"✅ OHLC from yfinance: {len(_ohlc_df)} daily candles for {data.symbol}")
                except Exception as _yf_err:
                    print(f"⚠️ yfinance OHLC fetch failed: {_yf_err}")

                # Fall back to the mentor API if yfinance didn't return data.
                if _ohlc_df is None or _ohlc_df.empty:
                    try:
                        import os as _os
                        # `get_lms_base_url()` reads LMS_BASE_URL / API_BASE_URL /
                        # DRAWING_EXPLAINER_BASE_URL — single env-var source of truth.
                        from utils.base_url import get_lms_base_url as _get_lms_base_url
                        _api_base = _get_lms_base_url()
                        _api_token = _os.getenv("API_BEARER_TOKEN")
                        _csrf = _os.getenv("API_CSRF_TOKEN")
                        if _api_base and _api_token:
                            from drawing_instruction.api_price_fetcher import APIPriceFetcher
                            from datetime import datetime as _dt, timedelta as _td
                            _fetcher = APIPriceFetcher(_api_base, _api_token, _csrf)
                            _ohlc_df = _fetcher.fetch_price_data(
                                symbol=data.symbol,
                                timeframe="1d",
                                from_date=(_dt.now() - _td(days=730)).strftime("%Y-%m-%d"),
                                to_date=_dt.now().strftime("%Y-%m-%d"),
                                market="stocks",
                            )
                            if _ohlc_df is not None and not _ohlc_df.empty:
                                print(f"✅ OHLC from mentor API: {len(_ohlc_df)} candles for {data.symbol}")
                        else:
                            print("⚠️ Mentor API token missing (API_BEARER_TOKEN) — set it in .env")
                    except Exception as _api_err:
                        print(f"⚠️ Mentor API OHLC fetch failed: {_api_err}")

                if _ohlc_df is not None and not _ohlc_df.empty:
                    st.session_state[_ohlc_cache_key] = _ohlc_df

            if _ohlc_df is not None and not _ohlc_df.empty:
                st.markdown("#### Chart")

                # Period selector via session state
                if "pt_period" not in st.session_state:
                    st.session_state.pt_period = "1Y"

                _selected = st.session_state.pt_period
                _period_days_map = {
                    "1W": 7, "1M": 30, "3M": 90, "6M": 180,
                    "1Y": 365, "ALL": len(_ohlc_df),
                }
                _days = _period_days_map.get(_selected, 365)
                _sliced = _ohlc_df.tail(_days)

                _opens = _sliced["Open"].tolist()
                _highs = _sliced["High"].tolist()
                _lows = _sliced["Low"].tolist()
                _closes = _sliced["Close"].tolist()
                _dates_idx = _sliced.index

                # For annotations / below-chart metrics we still need a plain
                # dates / close-prices pair compatible with the old code path.
                all_dates = [str(d.date()) if hasattr(d, "date") else str(d) for d in _ohlc_df.index]
                all_prices = _ohlc_df["Close"].tolist()
                dates = all_dates[-_days:]
                prices = all_prices[-_days:]
                days = _days  # used by the below-chart code

                current_price = _closes[-1] if _closes else 0
                price_change = _closes[-1] - _closes[0] if len(_closes) > 1 else 0
                is_positive = price_change >= 0
                up_color = "#089981"
                down_color = "#F23645"
                annot_color = up_color if is_positive else down_color

                # ── Candlestick chart (TradingView style) ──
                fig = go.Figure(
                    data=[
                        go.Candlestick(
                            x=_dates_idx,
                            open=_opens, high=_highs, low=_lows, close=_closes,
                            increasing=dict(
                                line=dict(color=up_color, width=1),
                                fillcolor=up_color,
                            ),
                            decreasing=dict(
                                line=dict(color=down_color, width=1),
                                fillcolor=down_color,
                            ),
                            hoverlabel=dict(bgcolor="#1E222D", font_size=12, font_color="#D1D4DC"),
                            name="Price",
                            showlegend=False,
                        )
                    ]
                )

                fig.update_layout(
                    template="plotly_dark",
                    height=420,
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    showlegend=False,
                    margin=dict(l=0, r=60, t=10, b=10),
                    xaxis=dict(
                        showgrid=False,
                        showline=False,
                        zeroline=False,
                        rangeslider=dict(visible=False),
                        tickfont=dict(color="#787B86", size=11),
                        tickformat="%b '%y" if _days > 90 else "%d %b",
                        # Hide weekend gaps for daily candlesticks
                        rangebreaks=[dict(bounds=["sat", "mon"])] if _days <= 365 else [],
                    ),
                    yaxis=dict(
                        showgrid=True,
                        gridcolor="rgba(120,123,134,0.12)",
                        showline=False,
                        zeroline=False,
                        side="right",
                        tickprefix="₹" if data.symbol.endswith((".NS", ".BO")) else "$",
                        tickfont=dict(color="#787B86", size=11),
                    ),
                    hovermode="x unified",
                )

                # Current price tag on the right edge
                fig.add_annotation(
                    x=_dates_idx[-1], y=current_price,
                    text=f"{'₹' if data.symbol.endswith(('.NS', '.BO')) else '$'}{current_price:,.2f}",
                    showarrow=False,
                    xanchor="left", xshift=8,
                    font=dict(color="white", size=12),
                    bgcolor=annot_color,
                    borderpad=4,
                )

                # Previous close reference line (first candle's open)
                _prev_close = _opens[0] if _opens else 0
                fig.add_hline(
                    y=_prev_close, line_dash="dot",
                    line_color="#787B86", line_width=0.8,
                    annotation_text=(
                        f"Prev open  "
                        f"{'₹' if data.symbol.endswith(('.NS', '.BO')) else '$'}{_prev_close:,.2f}"
                    ),
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
                # Labels and day windows match the 6 period buttons above 1-to-1
                # so each button has its own metric directly underneath it.
                metric_periods = [
                    ("1W",  "1 week",   7),
                    ("1M",  "1 month",  30),
                    ("3M",  "3 months", 90),
                    ("6M",  "6 months", 180),
                    ("1Y",  "1 year",   365),
                    ("ALL", "All time", len(all_dates)),
                ]
                metric_cols = st.columns(len(metric_periods))
                for idx, (_btn, mlabel, mdays) in enumerate(metric_periods):
                    mdays = min(mdays, len(all_prices))
                    with metric_cols[idx]:
                        if mdays >= 2:
                            start_p = all_prices[-mdays]
                            end_p = all_prices[-1]
                            pct = ((end_p - start_p) / start_p) * 100 if start_p else 0
                            color = "#089981" if pct >= 0 else "#F23645"
                            st.markdown(
                                f"<div style='text-align:center;padding:4px 0'>"
                                f"<div style='color:var(--tw-muted);font-size:12px'>{mlabel}</div>"
                                f"<div style='color:{color};font-size:14px;font-weight:600'>{pct:+.2f}%</div>"
                                f"</div>",
                                unsafe_allow_html=True,
                            )
                        else:
                            # Not enough history for this window — render an empty
                            # placeholder so the column widths stay aligned with
                            # the buttons above.
                            st.markdown(
                                f"<div style='text-align:center;padding:4px 0'>"
                                f"<div style='color:var(--tw-muted);font-size:12px'>{mlabel}</div>"
                                f"<div style='color:var(--tw-muted);font-size:14px;font-weight:600'>—</div>"
                                f"</div>",
                                unsafe_allow_html=True,
                            )
            else:
                # Both yfinance and the mentor API failed to return OHLC data.
                # Show a clear notice so the user understands why the chart is
                # missing instead of seeing a silent empty column.
                st.markdown("#### Chart")
                st.info(
                    "📉 Candlestick data unavailable for this stock. "
                    "Both yfinance and the mentor API failed to return OHLC. "
                    "Try again in a moment or check the terminal for fetch errors."
                )

        with col2:
            bx_header("Financial Breakdown", "bx-dollar-circle")
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

        # ── Theme-aware CSS via Streamlit's injected custom properties.
        # Streamlit sets these on the <body>/root element and updates them
        # live when the user switches theme via the hamburger menu, so
        # we don't have to branch in Python (st.get_option reads the
        # config-file theme, not the runtime choice). Borders, dividers
        # and muted labels use neutral rgba so they stay readable in both
        # themes without having to know the theme at render time.
        _tw_tokens = {
            "__CARD_BG__":      "var(--secondary-background-color, #1a1a1a)",
            "__CARD_BORDER__":  "rgba(128, 128, 128, 0.22)",
            "__MUTED__":        "color-mix(in srgb, var(--text-color, #fafafa) 62%, transparent)",
            "__TEXT__":         "var(--text-color, #fafafa)",
            "__DIVIDER__":      "rgba(128, 128, 128, 0.18)",
            "__TRACK__":        "rgba(128, 128, 128, 0.30)",
            "__SHADOW__":       "0 1px 3px rgba(15, 23, 42, 0.08)",
        }

        def _tw_apply_tokens(css: str) -> str:
            """Substitute theme-aware placeholder tokens in a CSS template."""
            for _k, _v in _tw_tokens.items():
                css = css.replace(_k, _v)
            return css

        # ── CSS for Technical Analysis cards ──
        st.markdown(_tw_apply_tokens("""
        <style>
        .ta-section-title {
            font-size: 12px; color: __MUTED__; letter-spacing: 0.06em;
            text-transform: uppercase; font-weight: 600;
            border-bottom: 0.5px solid __DIVIDER__; padding-bottom: 8px;
            margin-bottom: 12px; margin-top: 24px;
        }
        .ta-card {
            background: __CARD_BG__; border: 1px solid __CARD_BORDER__;
            border-radius: 8px; padding: 14px 16px;
            height: 100%; min-height: 90px;
            box-shadow: __SHADOW__;
        }
        .ta-label { font-size: 11px; color: __MUTED__; margin-bottom: 4px; }
        .ta-value { font-size: 20px; font-weight: 500; color: __TEXT__; margin-bottom: 4px; }
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
            background: __TRACK__; border-radius: 99px; height: 4px; width: 100%;
            margin: 8px 0 4px 0; position: relative;
        }
        .ta-range-fill {
            border-radius: 99px; height: 4px; position: absolute; top: 0; left: 0;
        }
        .ta-ma-row {
            display: flex; justify-content: space-between; align-items: center;
            padding: 6px 0; border-bottom: 0.5px solid __DIVIDER__;
        }
        .ta-ma-row:last-child { border-bottom: none; }
        .ta-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 6px; }

        /* ── SWOT-style treatment for every st.container(border=True)
           card in the main content area.

           Baseline: rounded corners + an always-visible green left
           accent bar that gives the card a clear identity (same as
           the SWOT cards' `--accent` stripe).

           On hover: background tints green, border sharpens, card
           slides right 2px, and a soft green glow blooms — identical
           animation to the SWOT / News cards so every section looks
           coherent.

           Every property is !important because Streamlit's emotion-css
           generates high-specificity classes that would otherwise beat
           a plain data-testid selector. */
        section[data-testid="stMain"] div[data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 10px !important;
            border-left: 3px solid rgba(116, 229, 4, 0.55) !important;
            transition: background-color 0.25s ease,
                        border-color 0.25s ease,
                        border-left-color 0.25s ease,
                        box-shadow 0.3s ease,
                        transform 0.25s ease !important;
        }
        section[data-testid="stMain"] div[data-testid="stVerticalBlockBorderWrapper"]:hover {
            background: rgba(116, 229, 4, 0.09) !important;
            border-color: rgba(116, 229, 4, 0.50) !important;
            border-left-color: #74e504 !important;
            box-shadow: 0 4px 18px rgba(116, 229, 4, 0.22) !important;
            transform: translateX(2px) !important;
        }
        /* Keep the chat-area scroll container flat: we explicitly null
           out border/shadow on height-constrained wrappers elsewhere in
           this stylesheet, so make sure the hover rule above does not
           re-introduce a border there. */
        section[data-testid="stMain"] div[data-testid="stVerticalBlockBorderWrapper"]:has(> div[style*="overflow"]) {
            border-left: none !important;
        }
        section[data-testid="stMain"] div[data-testid="stVerticalBlockBorderWrapper"]:has(> div[style*="overflow"]):hover {
            background: transparent !important;
            border-color: transparent !important;
            border-left: none !important;
            box-shadow: none !important;
            transform: none !important;
        }
        </style>
        """), unsafe_allow_html=True)

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
        # Tabbed Info Panel — Snapshot / Overview / Financials / Market Data / Performance
        # ══════════════════════════════════════════════
        st.markdown(_tw_apply_tokens("""
        <style>
        .tw-info-card {
            background: __CARD_BG__; border: 1px solid __CARD_BORDER__;
            border-radius: 8px; padding: 16px; height: 100%;
            box-shadow: __SHADOW__;
        }
        .tw-info-icon { font-size: 18px; }
        .tw-info-label { font-size: 11px; color: __MUTED__; letter-spacing: 0.04em;
            text-transform: uppercase; margin-bottom: 4px; }
        .tw-info-value { font-size: 15px; font-weight: 600; color: __TEXT__; word-break: break-word; }
        .tw-metric-row {
            display: flex; justify-content: space-between; padding: 8px 0;
            border-bottom: 0.5px solid __DIVIDER__; font-size: 13px;
        }
        .tw-metric-row:last-child { border-bottom: none; }
        .tw-metric-label { color: __MUTED__; }
        .tw-metric-value { color: __TEXT__; font-weight: 600; }
        .tw-metric-value.neg { color: #ef4444; }
        .tw-sub-title { font-size: 13px; font-weight: 700; color: __TEXT__;
            margin-bottom: 6px; display: flex; align-items: center; gap: 6px; }
        .tw-period-badge {
            display: inline-block; padding: 8px 14px; border-radius: 999px;
            font-size: 12px; font-weight: 600; margin-right: 8px; margin-bottom: 8px;
        }
        .tw-period-pos { background: #dcfce7; color: #166534; border: 1px solid #22c55e55; }
        .tw-period-neg { background: #fee2e2; color: #991b1b; border: 1px solid #ef444455; }
        .tw-period-label { display: block; color: __MUTED__; font-size: 10px;
            letter-spacing: 0.08em; text-transform: uppercase; }
        </style>
        """), unsafe_allow_html=True)

        _snap_obj = getattr(data, "snapshot", None)
        _parsed_snap = _parsed.get("snapshot", {}) if _parsed else {}

        def _snap_val(obj_field: str, parsed_key: str) -> str:
            if _snap_obj is not None:
                _v = getattr(_snap_obj, obj_field, None)
                if _v and _v != "N/A":
                    return str(_v)
            return _parsed_snap.get(parsed_key, "") or "—"

        # ── Jump-nav bar (looks like tabs, but just scrolls to anchors) ──
        # All 5 sections now stack vertically on the same page. The "tabs"
        # here are anchor links that jump-scroll to the section headers
        # below, giving users the scroll-through-everything experience
        # they asked for while keeping the familiar tab-style navigation.
        st.markdown(_tw_apply_tokens("""
        <style>
        .tw-jumpnav {
            display: flex;
            flex-wrap: wrap;
            gap: 2px;
            border-bottom: 1px solid __DIVIDER__;
            margin-bottom: 18px;
            padding-bottom: 2px;
        }
        .tw-jumpnav a {
            padding: 10px 16px;
            color: inherit;       /* use page text color */
            opacity: 0.70;        /* muted, but readable on any bg */
            text-decoration: none;
            font-size: 14px;
            font-weight: 600;
            border-bottom: 2px solid transparent;
            transition: color 0.15s, border-color 0.15s, opacity 0.15s;
        }
        .tw-jumpnav a:hover,
        .tw-jumpnav a:focus,
        .tw-jumpnav a:active {
            color: #74e504;
            opacity: 1;
            border-bottom-color: #74e504;
        }
        .tw-section-anchor {
            position: relative;
            top: -20px;
            visibility: hidden;
        }
        .tw-section-title {
            font-size: 20px;
            font-weight: 700;
            color: __TEXT__;
            margin: 32px 0 14px 0;
            padding-bottom: 8px;
            border-bottom: 1px solid __DIVIDER__;
        }
        .tw-section-title:first-of-type { margin-top: 8px; }
        .tw-jumpnav a .bx,
        .tw-section-title .bx {
            color: #74e504;
            margin-right: 6px;
            vertical-align: -2px;
        }
        </style>
        <div class="tw-jumpnav">
            <a href="#sec-snap"><i class='bx bxs-building-house'></i>Snapshot</a>
            <a href="#sec-over"><i class='bx bxs-file-doc'></i>Overview</a>
            <a href="#sec-fin"><i class='bx bxs-dollar-circle'></i>Financials</a>
            <a href="#sec-mkt"><i class='bx bx-line-chart'></i>Market Data</a>
            <a href="#sec-perf"><i class='bx bx-bar-chart-alt-2'></i>Performance</a>
        </div>
        """), unsafe_allow_html=True)

        # ── Section 1: Company Snapshot ───────────────────────────
        # Invisible anchor so the jump-nav bar above can still scroll to
        # this section. The visible heading below is a native Streamlit
        # <h3> (via bx_header) so Streamlit themes it automatically in
        # both light and dark modes.
        st.markdown('<div id="sec-snap" style="position:relative;top:-20px;height:0;"></div>',
                    unsafe_allow_html=True)
        bx_header("Snapshot", "bxs-building-house", level=3)

        _snap_fields = [
            ("🏢", "Company Name", "company_name", "companyName"),
            ("📈", "Ticker Symbol", "ticker_symbol", "tickerSymbol"),
            ("🏦", "Exchange", "exchange", "exchange"),
            ("🏭", "Sector", "sector", "sector"),
            ("🔧", "Industry", "industry", "industry"),
            ("📍", "Headquarters", "headquarters", "headquarters"),
            ("📅", "Founded", "founded_year", "founded"),
            ("👤", "CEO", "ceo", "ceo"),
            ("👥", "Employees", "employees", "employees"),
            ("🌐", "Website", "website", "website"),
        ]

        # Same rounded-card + hover-animation treatment as the SWOT
        # quadrants: theme-neutral gray background, green left-accent bar,
        # on hover a green tint + slide-right + soft glow. All cards
        # share the app's accent green since Snapshot fields are neutral
        # informational items (unlike SWOT which has semantic colours
        # per quadrant).
        st.markdown("""
        <style>
        .tw-snap-card {
            --accent: #74e504;
            background: rgba(128, 128, 128, 0.06);
            border: 1px solid rgba(128, 128, 128, 0.22);
            border-left: 3px solid var(--accent);
            border-radius: 8px;
            padding: 14px 18px;
            margin-bottom: 12px;
            min-height: 78px;
            transition: background 0.2s ease,
                        border-color 0.2s ease,
                        transform 0.2s ease,
                        box-shadow 0.2s ease;
        }
        .tw-snap-card:hover {
            background: color-mix(in srgb, var(--accent) 10%, transparent);
            border-color: color-mix(in srgb, var(--accent) 40%, transparent);
            border-left-color: var(--accent);
            transform: translateX(2px);
            box-shadow: 0 2px 12px color-mix(in srgb, var(--accent) 18%, transparent);
        }
        /* Modifier: green accent on all four sides (not just the left).
           Used by the Performance period-return cards per client request. */
        .tw-snap-card--ring {
            border: 1px solid var(--accent);
            border-left: 1px solid var(--accent);
        }
        .tw-snap-card--ring:hover {
            border-color: var(--accent);
            border-left-color: var(--accent);
        }
        .tw-snap-label {
            font-size: 11px;
            opacity: 0.65;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            font-weight: 500;
            margin-bottom: 4px;
        }
        .tw-snap-value {
            font-size: 15px;
            font-weight: 600;
            color: inherit;
            word-break: break-word;
            line-height: 1.35;
        }
        .tw-snap-value a {
            color: #74e504;
            text-decoration: none;
            transition: text-decoration 0.15s ease;
        }
        .tw-snap-value a:hover { text-decoration: underline; }
        </style>
        """, unsafe_allow_html=True)

        import html as _snap_html_mod
        for row_start in range(0, len(_snap_fields), 3):
            _cols = st.columns(3)
            for _col, (icon, label, f_obj, f_parsed) in zip(
                _cols, _snap_fields[row_start : row_start + 3]
            ):
                _val = _snap_val(f_obj, f_parsed)
                # Build the value HTML depending on the field type.
                if label == "Website" and _val not in ("—", ""):
                    _esc = _snap_html_mod.escape(_val)
                    _val_html = (
                        f"<a href='{_esc}' target='_blank' rel='noopener'>"
                        f"{_esc}</a>"
                    )
                elif label == "Employees" and _val not in ("—", ""):
                    try:
                        _val_html = f"{int(float(str(_val).replace(',', ''))):,}"
                    except (ValueError, TypeError):
                        _val_html = _snap_html_mod.escape(_val)
                else:
                    _val_html = _snap_html_mod.escape(_val)
                with _col:
                    st.markdown(
                        f"<div class='tw-snap-card'>"
                        f"<div class='tw-snap-label'>{icon} {label.upper()}</div>"
                        f"<div class='tw-snap-value'>{_val_html}</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

        # ── Tab 2: Business Overview ──────────────────────────────
        # ── Section 2: Business Overview ──────────────────────────
        st.markdown('<div id="sec-over" style="position:relative;top:-20px;height:0;"></div>',
                    unsafe_allow_html=True)
        bx_header("Overview", "bxs-file-doc", level=3)
        _biz_obj = getattr(data, "business_overview", None)
        _biz_text = ""
        if _biz_obj is not None:
            _biz_text = getattr(_biz_obj, "description", "") or ""
        if not _biz_text and _parsed.get("businessOverview"):
            _biz_text = _parsed["businessOverview"]

        if _biz_text:
            import html as _ov_html
            _safe_name = _ov_html.escape(data.name)
            _safe_text = _ov_html.escape(_biz_text)
            # Render Overview as a custom HTML card using the same
            # .tw-snap-card class (rounded corners, green left accent,
            # SWOT-style hover animation). Full description is shown
            # directly — no expander, so users see it at a glance.
            st.markdown(
                f"<div class='tw-snap-card' style='padding:18px 24px;"
                f"min-height:auto;margin-bottom:14px;'>"
                f"<div style='font-size:1.05rem;font-weight:700;color:inherit;"
                f"margin-bottom:10px;'>{_safe_name}</div>"
                f"<div style='color:inherit;opacity:0.82;line-height:1.6;"
                f"font-size:14px;'>{_safe_text}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.info("Business overview not available for this stock.")

        _screener_summary = (_parsed.get("screenerSummary") or "").strip()
        if _screener_summary:
            with st.container():
                bx_header("Screener.in Quarterly Summary", "bx-bar-chart-square", level=4)
                with st.expander("View summary", expanded=False):
                    st.markdown(_screener_summary)

        # ── Tab 3: Financial Metrics ──────────────────────────────
        # ── Section 3: Financials ─────────────────────────────────
        st.markdown('<div id="sec-fin" style="position:relative;top:-20px;height:0;"></div>',
                    unsafe_allow_html=True)
        bx_header("Financials", "bxs-dollar-circle", level=3)

        # Helper: render a titled key/value card as custom HTML using the
        # same .tw-snap-card class as the Snapshot / SWOT cards — so the
        # Financials sub-cards get the same rounded corners, green left
        # accent bar, and slide-right hover animation. Rows are flex
        # layouts with the label on the left (muted) and value on the
        # right (bold, red if negative).
        import html as _fin_html
        def _kv_card(title: str, rows: list[tuple[str, str, bool]]) -> None:
            _rows_html = ""
            for _label, _value, _neg in rows:
                _vv = _value if _value not in (None, "", "N/A") else "—"
                _val_style = "color:#dc2626;" if _neg else "color:inherit;"
                _rows_html += (
                    f"<div style='display:flex;justify-content:space-between;"
                    f"align-items:center;padding:7px 0;"
                    f"border-bottom:0.5px solid rgba(128,128,128,0.18);"
                    f"font-size:13.5px;'>"
                    f"<span style='color:inherit;opacity:0.7'>"
                    f"{_fin_html.escape(_label)}</span>"
                    f"<span style='{_val_style}font-weight:700;"
                    f"text-align:right'>{_fin_html.escape(_vv)}</span>"
                    f"</div>"
                )
            st.markdown(
                f"<div class='tw-snap-card' style='padding:16px 20px;"
                f"min-height:auto;margin-bottom:14px;'>"
                f"<div style='font-weight:700;font-size:14px;color:inherit;"
                f"margin-bottom:8px;'>{title}</div>"
                f"{_rows_html}"
                f"</div>",
                unsafe_allow_html=True,
            )

        def _fmt_ccy(v):
            return _fmt_large(v) if v is not None else "—"

        _fin = data.financials
        _rev = getattr(_fin, "revenue", None)
        _np = getattr(_fin, "net_profit", None)
        _ebitda = getattr(_fin, "ebitda", None)
        _eps = getattr(_fin, "eps", None)
        _ta = getattr(_fin, "total_assets", None)
        _tl = getattr(_fin, "total_liabilities", None)
        _td = getattr(_fin, "total_debt", None)
        _cash = getattr(_fin, "cash_balance", None)
        _de = getattr(_fin, "debt_to_equity", None)
        _ocf = getattr(_fin, "operating_cash_flow", None)
        _fcf = getattr(_fin, "free_cash_flow", None)
        _pe = getattr(_fin, "pe_ratio", None)
        _pb = getattr(_fin, "pb_ratio", None)
        _mcap_f = getattr(data.market_data, "market_cap", None)
        _ev = getattr(_fin, "enterprise_value", None)
        _evebitda = getattr(_fin, "ev_ebitda", None)
        _pm_f = getattr(_fin, "profit_margin", None)
        _om_f = getattr(_fin, "operating_margin", None)
        _gm_f = getattr(_fin, "gross_margin", None)

        _sector = getattr(data.snapshot, "sector", None) or getattr(data.market_data, "sector", None)
        _industry = getattr(data.snapshot, "industry", None)
        _is_bank = is_banking_sector(_sector, _industry)
        _is_finco = is_financial_sector(_sector, _industry)

        def _pct(v):
            if v is None:
                return "—"
            _mul = 100 if abs(v) < 1 else 1
            return f"{v * _mul:.2f}%"

        _row_a, _row_b = st.columns(2)
        with _row_a:
            _income_rows = [
                ("Revenue" if not _is_bank else "Interest Income", _fmt_ccy(_rev), False),
                ("Net Profit", _fmt_ccy(_np), _np is not None and _np < 0),
            ]
            if not _is_bank:
                _income_rows.append(("EBITDA", _fmt_ccy(_ebitda), False))
            _income_rows.append(
                ("EPS (TTM)", f"{_cur}{_eps:,.2f}" if _eps is not None else "—", False)
            )
            _kv_card("📊 Income Statement", _income_rows)
        with _row_b:
            _bs_rows = [
                ("Total Assets", _fmt_ccy(_ta), False),
                ("Total Liabilities", _fmt_ccy(_tl), False),
                (
                    "Total Borrowings" if _is_bank else "Total Debt",
                    _fmt_ccy(_td),
                    False,
                ),
                ("Cash Balance", _fmt_ccy(_cash), False),
            ]
            if not _is_bank:
                _bs_rows.append(
                    ("Debt / Equity", f"{_de:.2f}" if _de is not None else "—", False)
                )
            _kv_card("🏦 Balance Sheet", _bs_rows)

        _row_c, _row_d = st.columns(2)
        with _row_c:
            if _is_bank:
                # FCF is not meaningful for banks — show OCF only, and a note.
                _cf_rows = [("Operating CF", _fmt_ccy(_ocf), False)]
                _kv_card("💸 Cash Flow", _cf_rows)
                st.caption(
                    "ℹ️ Free cash flow is not a standard metric for banks — "
                    "cash-generation is captured via Net Interest Income and "
                    "is shown in the Banking Metrics section."
                )
            else:
                _kv_card(
                    "💸 Cash Flow",
                    [
                        ("Operating CF", _fmt_ccy(_ocf), False),
                        ("Free Cash Flow", _fmt_ccy(_fcf), _fcf is not None and _fcf < 0),
                    ],
                )
        with _row_d:
            _val_rows = [
                ("P/E Ratio", f"{_pe:.2f}" if _pe is not None else "—", False),
                ("P/B Ratio", f"{_pb:.2f}" if _pb is not None else "—", False),
                ("Market Cap", _fmt_ccy(_mcap_f), False),
            ]
            if not _is_bank:
                _val_rows.append(("Enterprise Value", _fmt_ccy(_ev), False))
                _val_rows.append(
                    ("EV / EBITDA", f"{_evebitda:.2f}" if _evebitda is not None else "—", False)
                )
            _kv_card("📐 Valuation", _val_rows)

        if _is_bank:
            # For banks, show Profit & Operating Margin only. Gross Margin is
            # not meaningful (banks don't have COGS in the industrial sense).
            _kv_card(
                "📈 Margins",
                [
                    ("Profit Margin", _pct(_pm_f), _pm_f is not None and _pm_f < 0),
                    ("Operating Margin", _pct(_om_f), _om_f is not None and _om_f < 0),
                ],
            )
        else:
            _kv_card(
                "📈 Margins",
                [
                    ("Profit Margin", _pct(_pm_f), _pm_f is not None and _pm_f < 0),
                    ("Operating Margin", _pct(_om_f), _om_f is not None and _om_f < 0),
                    ("Gross Margin", _pct(_gm_f), _gm_f is not None and _gm_f < 0),
                ],
            )

        # ── Banking Metrics section (banks only) ──
        # NIM / NPA / CASA / CAR / ROA / C-D / PCR / Cost-to-Income — the
        # ratios that actually matter for a bank's health. Rendered across
        # three paired cards (Profitability, Asset Quality, Funding & Capital).
        # Shown as "—" where screener.in didn't expose the field, so users see
        # the gap rather than getting a silently truncated section.
        _bm = getattr(data, "banking_metrics", None)
        if _is_bank and _bm is not None:
            st.markdown("")
            bx_header("Banking Metrics", "bx-landmark", level=3)

            def _pct_or_dash(v, suffix: str = "%"):
                if v is None:
                    return "—"
                # screener.in exports banking ratios as plain numbers already
                # in percent form (e.g. 3.45 means 3.45%). Don't rescale.
                return f"{v:.2f}{suffix}"

            def _bm_neg_if(v, threshold: float) -> bool:
                """NPA/cost-to-income above threshold is flagged red."""
                return v is not None and v >= threshold

            _bm_a, _bm_b = st.columns(2)
            with _bm_a:
                _kv_card(
                    "📈 Profitability",
                    [
                        ("Net Interest Margin", _pct_or_dash(_bm.net_interest_margin), False),
                        ("Return on Assets", _pct_or_dash(_bm.return_on_assets), False),
                        ("Return on Equity", _pct_or_dash(_bm.return_on_equity), False),
                        (
                            "Cost-to-Income",
                            _pct_or_dash(_bm.cost_to_income),
                            _bm_neg_if(_bm.cost_to_income, 60),
                        ),
                    ],
                )
            with _bm_b:
                _kv_card(
                    "🩺 Asset Quality",
                    [
                        (
                            "Gross NPA",
                            _pct_or_dash(_bm.gross_npa),
                            _bm_neg_if(_bm.gross_npa, 3),
                        ),
                        (
                            "Net NPA",
                            _pct_or_dash(_bm.net_npa),
                            _bm_neg_if(_bm.net_npa, 1),
                        ),
                        ("Provision Coverage", _pct_or_dash(_bm.provision_coverage), False),
                    ],
                )

            _kv_card(
                "💰 Funding & Capital",
                [
                    ("CASA Ratio", _pct_or_dash(_bm.casa_ratio), False),
                    ("Capital Adequacy (CAR)", _pct_or_dash(_bm.capital_adequacy), False),
                    ("Credit-Deposit Ratio", _pct_or_dash(_bm.credit_deposit), False),
                ],
            )

            # Caption: explains what's missing vs. what's N/A.
            _any_present = any(
                getattr(_bm, _f) is not None
                for _f in (
                    "net_interest_margin", "return_on_assets", "return_on_equity",
                    "cost_to_income", "gross_npa", "net_npa", "provision_coverage",
                    "casa_ratio", "capital_adequacy", "credit_deposit",
                )
            )
            if not _any_present:
                st.caption(
                    "ℹ️ Banking ratios not available from data source — "
                    "screener.in may not expose these for this bank yet."
                )

        # ── Tab 4: Market Data ────────────────────────────────────
        # ── Section 4: Market Data ────────────────────────────────
        st.markdown('<div id="sec-mkt" style="position:relative;top:-20px;height:0;"></div>',
                    unsafe_allow_html=True)
        bx_header("Market Data", "bx-line-chart", level=3)

        cp = data.market_data.current_price
        day_chg = data.market_data.day_change
        w52h = data.market_data.week_52_high
        w52l = data.market_data.week_52_low
        mcap = data.market_data.market_cap
        vol = getattr(data.market_data, "volume", None)
        avg_vol = data.market_data.avg_volume
        beta = getattr(data.market_data, "beta", None)
        dy = getattr(data.financials, "dividend_yield", None)

        def _fmt_vol(v):
            if v is None:
                return "—"
            if _is_indian:
                if v >= 1e7:
                    return f"{v / 1e7:.2f} Cr"
                if v >= 1e5:
                    return f"{v / 1e5:.2f} L"
                return f"{v:,.0f}"
            if v >= 1e6:
                return f"{v / 1e6:.2f}M"
            return f"{v:,.0f}"

        # Helper: render a single metric card as custom HTML using the
        # same .tw-snap-card class as the Snapshot / Overview / Financials
        # cards — so each Market Data card gets the rounded corners, green
        # left accent bar, and SWOT-style slide-right hover animation.
        # sub_color: "green" | "red" | None (default muted caption).
        import html as _mkt_html
        def _metric_card(label: str, value: str, sub: str | None = None, sub_color: str | None = None):
            _safe_label = _mkt_html.escape(label)
            _safe_value = _mkt_html.escape(value)
            if sub:
                if sub_color == "green":
                    _sub_style = "color:#16a34a;font-weight:600;"
                elif sub_color == "red":
                    _sub_style = "color:#dc2626;font-weight:600;"
                else:
                    _sub_style = "color:inherit;opacity:0.65;"
                _sub_html = (
                    f"<div style='{_sub_style}font-size:12px;"
                    f"margin-top:4px;'>{_mkt_html.escape(sub)}</div>"
                )
            else:
                _sub_html = ""
            st.markdown(
                f"<div class='tw-snap-card' style='padding:14px 18px;"
                f"min-height:92px;margin-bottom:12px;'>"
                f"<div style='font-size:11px;opacity:0.65;"
                f"letter-spacing:0.04em;text-transform:uppercase;"
                f"font-weight:500;margin-bottom:6px;'>{_safe_label}</div>"
                f"<div style='font-size:1.15rem;font-weight:700;"
                f"color:inherit;line-height:1.2;'>{_safe_value}</div>"
                f"{_sub_html}"
                f"</div>",
                unsafe_allow_html=True,
            )

        _m_row1 = st.columns(4)
        with _m_row1[0]:
            if cp is not None:
                _sub = f"{day_chg:+.2f}% today" if day_chg is not None else None
                _sub_c = None
                if day_chg is not None:
                    _sub_c = "green" if day_chg >= 0 else "red"
                _metric_card("Current Price", f"{_cur}{cp:,.2f}", _sub, _sub_c)
            else:
                _metric_card("Current Price", "—")
        with _m_row1[1]:
            if w52h and w52l and cp:
                _r = max(0, min(100, ((cp - w52l) / (w52h - w52l)) * 100 if w52h != w52l else 50))
                # 52W Range card: custom HTML with an inline progress bar
                # so the whole card lives in one .tw-snap-card div (same
                # hover animation as the other metric cards).
                st.markdown(
                    f"<div class='tw-snap-card' style='padding:14px 18px;"
                    f"min-height:92px;margin-bottom:12px;'>"
                    f"<div style='font-size:11px;opacity:0.65;"
                    f"letter-spacing:0.04em;text-transform:uppercase;"
                    f"font-weight:500;margin-bottom:6px;'>52W RANGE</div>"
                    f"<div style='font-size:0.95rem;font-weight:700;"
                    f"color:inherit;line-height:1.2;margin-bottom:8px;'>"
                    f"{_cur}{w52l:,.0f} – {_cur}{w52h:,.0f}</div>"
                    f"<div style='background:rgba(128,128,128,0.25);"
                    f"border-radius:99px;height:4px;width:100%;"
                    f"position:relative;margin-bottom:6px;'>"
                    f"<div style='background:#2962FF;border-radius:99px;"
                    f"height:4px;width:{_r:.1f}%;position:absolute;"
                    f"top:0;left:0;'></div></div>"
                    f"<div style='font-size:11px;color:inherit;opacity:0.65;'>"
                    f"at {_r:.0f}% of range</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            else:
                _metric_card("52W Range", "—")
        with _m_row1[2]:
            _metric_card("Market Cap", _fmt_large(mcap) if mcap else "—")
        with _m_row1[3]:
            _metric_card("Volume", _fmt_vol(vol))

        _m_row2 = st.columns(4)
        with _m_row2[0]:
            _metric_card("Avg Volume (10D)", _fmt_vol(avg_vol))
        with _m_row2[1]:
            _metric_card("Beta", f"{beta:.2f}" if beta is not None else "—")
        with _m_row2[2]:
            # Dividend yield is ambiguous: screener.in stores a fraction
            # (0.0051 for 0.51%), yfinance sometimes returns a raw percent
            # for Indian stocks (0.52 for 0.52%). Split at 0.5 — below that
            # must be a fraction (scale x100), at or above is already a
            # percentage. 0.5 is safe: Indian stocks very rarely exceed 10%
            # yield, and no realistic stock has a raw-percent yield below
            # 0.5 that would be misinterpreted as 50%.
            if dy is not None:
                _dy = dy * 100 if abs(dy) < 0.5 else dy
                _metric_card("Dividend Yield", f"{_dy:.2f}%")
            else:
                _metric_card("Dividend Yield", "—")
        with _m_row2[3]:
            _ev = getattr(data.financials, "enterprise_value", None)
            _metric_card("Enterprise Value", _fmt_large(_ev) if _ev is not None else "—")

        # ── Holdings sub-row: Promoter / FII / DII ──
            def _fmt_holding(v):
                """Holdings may be stored as fraction (0.7177) or percentage (71.77)."""
                if v is None:
                    return None
                try:
                    f = float(v)
                except (TypeError, ValueError):
                    return None
                return f * 100 if abs(f) < 1 else f

            def _parse_holding_from_text(label: str):
                """Recover a holding percentage from the cached agent response text.
                Used as a fallback when company_data doesn't have structured
                holdings (e.g. cached analyses that predate the new builder)."""
                import re as _re
                _txt = st.session_state.get("_dash_last_raw_response") or ""
                if not _txt:
                    # Also look at the last message in chat messages (legacy path)
                    _msgs = st.session_state.get("messages") or []
                    for _msg in reversed(_msgs):
                        if _msg.get("role") == "assistant":
                            _txt = _msg.get("content", "")
                            break
                if not _txt:
                    return None
                _m = _re.search(rf"\*?\*?{label}:?\*?\*?\s*([\d.]+)\s*%", _txt, _re.IGNORECASE)
                if not _m:
                    return None
                try:
                    return float(_m.group(1))
                except ValueError:
                    return None

            _promoter = (
                _fmt_holding(getattr(data.market_data, "promoter_holding", None))
                or _parse_holding_from_text("Promoter Holding")
            )
            _fii = (
                _fmt_holding(getattr(data.market_data, "fii_holding", None))
                or _parse_holding_from_text("FII Holding")
            )
            _dii = (
                _fmt_holding(getattr(data.market_data, "dii_holding", None))
                or _parse_holding_from_text("DII Holding")
            )

        st.markdown("")
        st.markdown("**Holdings**")
        _m_row3 = st.columns(3)
        for _col, _label, _val, _icon in zip(
            _m_row3,
            ["Promoter Holding", "FII Holding", "DII Holding"],
            [_promoter, _fii, _dii],
            ["🏛️", "🌐", "🏦"],
        ):
            with _col:
                _metric_card(
                    f"{_icon} {_label}",
                    f"{_val:.2f}%" if _val is not None else "—",
                )

        # ── Holdings donut chart ──
        # Visualises Promoter / FII / DII / Public split so the reader can
        # eyeball the ownership structure without mentally summing the cards.
        # "Public" is derived as the residual (100 - known categories), floored
        # at 0 — guards against rounding drift when screener.in reports the
        # categories from independent percentages.
        _hold_items = [
            ("Promoter", _promoter, "#6366F1"),
            ("FII",      _fii,      "#22C55E"),
            ("DII",      _dii,      "#F59E0B"),
        ]
        _hold_items = [(lbl, v, c) for (lbl, v, c) in _hold_items if v is not None]
        if _hold_items:
            _known_sum = sum(v for (_, v, _) in _hold_items)
            _public_v = max(0.0, 100.0 - _known_sum)
            # Only add Public slice if there's a meaningful remainder — prevents
            # a 0.01% sliver from appearing when categories already sum to ~100.
            if _public_v >= 1.0:
                _hold_items.append(("Public", _public_v, "#94A3B8"))

            import plotly.graph_objects as _pgo
            _hold_fig = _pgo.Figure(
                data=[
                    _pgo.Pie(
                        labels=[lbl for (lbl, _, _) in _hold_items],
                        values=[v for (_, v, _) in _hold_items],
                        hole=0.62,
                        marker=dict(
                            colors=[c for (_, _, c) in _hold_items],
                            line=dict(color="rgba(0,0,0,0)", width=0),
                        ),
                        textinfo="label+percent",
                        textposition="outside",
                        textfont=dict(size=11, color="#cbd5e1"),
                        hovertemplate="<b>%{label}</b>: %{value:.2f}%<extra></extra>",
                        sort=False,
                        direction="clockwise",
                    )
                ]
            )
            _hold_fig.update_layout(
                template="plotly_dark",
                height=260,
                margin=dict(l=10, r=10, t=10, b=10),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                showlegend=False,
                annotations=[
                    dict(
                        text="Ownership",
                        x=0.5, y=0.5,
                        font=dict(size=12, color="#94a3b8"),
                        showarrow=False,
                    )
                ],
            )
            st.plotly_chart(_hold_fig, width='stretch')

        # ── Tab 5: Price Performance ──────────────────────────────
        # ── Section 5: Performance ────────────────────────────────
        st.markdown('<div id="sec-perf" style="position:relative;top:-20px;height:0;"></div>',
                    unsafe_allow_html=True)
        bx_header("Performance", "bx-bar-chart-alt-2", level=3)

        _periods = (_parsed.get("pricePerformance") or {}).get("periods", [])
        # Build from company_data if parser output missing
        if not _periods:
            _mapping = [
                ("1D", getattr(data.market_data, "day_change", None)),
                ("1W", getattr(data.market_data, "week_change", None)),
                ("1M", getattr(data.market_data, "month_change", None)),
                ("6M", getattr(data.market_data, "month_6_change", None)),
                ("1Y", getattr(data.market_data, "year_change", None)),
                ("5Y CAGR", getattr(data.market_data, "year_5_cagr", None)),
            ]
            for _lbl, _v in _mapping:
                if _v is not None:
                    _periods.append(
                        {
                            "label": _lbl,
                            "value": f"{_v:+.2f}%",
                            "isPositive": _v >= 0,
                        }
                    )

        if _periods:
            # Render period returns as custom HTML cards using the same
            # .tw-snap-card class as the Snapshot / Overview / Financials /
            # Market Data cards — rounded corners, green left accent bar,
            # and SWOT-style slide-right hover animation. Positive values
            # are green, negatives are red, using fixed hex colours that
            # read correctly in both light and dark themes.
            import html as _perf_html
            _pcols = st.columns(len(_periods))
            for _c, _p in zip(_pcols, _periods):
                _is_pos = _p.get("isPositive")
                _val_color = "#16a34a" if _is_pos else "#dc2626"
                _label = _perf_html.escape(str(_p.get("label", "")))
                _value = _perf_html.escape(str(_p.get("value", "—")))
                with _c:
                    st.markdown(
                        f"<div class='tw-snap-card tw-snap-card--ring' "
                        f"style='padding:14px 16px;"
                        f"min-height:82px;margin-bottom:12px;text-align:center;'>"
                        f"<div style='font-size:11px;opacity:0.65;"
                        f"letter-spacing:0.04em;text-transform:uppercase;"
                        f"font-weight:500;margin-bottom:6px;'>{_label}</div>"
                        f"<div style='font-size:1.05rem;font-weight:700;"
                        f"color:{_val_color};line-height:1.2;'>{_value}</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
        else:
            st.info("No period-return data available.")

        # 7-day history — prefer live price_history, fall back to parsed
        _history_rows: list[tuple[str, str, str, bool]] = []
        if data.market_data.price_history:
            _items = list(data.market_data.price_history.items())[-7:]
            for _i, (_date, _price) in enumerate(_items):
                if _i == 0:
                    _history_rows.append((str(_date), f"{_cur}{_price:,.2f}", "—", True))
                else:
                    _prev = _items[_i - 1][1]
                    _chg = ((_price - _prev) / _prev) * 100 if _prev else 0
                    _history_rows.append(
                        (
                            str(_date),
                            f"{_cur}{_price:,.2f}",
                            f"{_chg:+.2f}%",
                            _chg >= 0,
                        )
                    )
        else:
            for _h in (_parsed.get("pricePerformance") or {}).get("sevenDayHistory", []):
                _history_rows.append(
                    (
                        _h.get("date", ""),
                        _h.get("price", "—"),
                        _h.get("change", "—"),
                        bool(_h.get("isPositive")),
                    )
                )

        if _history_rows:
            # Render the 7-day price history as a custom HTML table wrapped
            # in a .tw-snap-card so it gets the same rounded corners, green
            # left accent bar, and SWOT-style slide-right hover animation
            # as every other section. Row-level colour on the Change column
            # uses fixed hex (#16a34a / #dc2626) that reads in both themes.
            import html as _hist_html
            _POS = "#16a34a"
            _NEG = "#dc2626"
            _hdr_style = (
                "text-align:left;padding:10px 12px;font-size:11px;"
                "letter-spacing:0.06em;text-transform:uppercase;"
                "font-weight:600;color:inherit;opacity:0.65;"
                "border-bottom:1px solid rgba(128,128,128,0.22);"
            )
            _cell_base = (
                "padding:10px 12px;font-size:13.5px;color:inherit;"
                "border-bottom:0.5px solid rgba(128,128,128,0.14);"
            )
            _rows_html = ""
            for _d, _price, _chg, _pos in _history_rows:
                _cell_l = f"{_cell_base}text-align:left;"
                _cell_c = f"{_cell_base}text-align:right;font-weight:600;"
                if _chg == "—":
                    _chg_style = f"{_cell_c}opacity:0.55;"
                else:
                    _chg_color = _POS if _pos else _NEG
                    _chg_style = f"{_cell_c}color:{_chg_color};"
                _rows_html += (
                    f"<tr>"
                    f"<td style='{_cell_l}'>{_hist_html.escape(str(_d))}</td>"
                    f"<td style='{_cell_c}'>{_hist_html.escape(str(_price))}</td>"
                    f"<td style='{_chg_style}'>{_hist_html.escape(str(_chg))}</td>"
                    f"</tr>"
                )

            st.markdown(
                f"<div class='tw-snap-card' style='padding:6px 8px;"
                f"min-height:auto;margin-bottom:14px;'>"
                f"<div style='font-weight:700;font-size:14px;"
                f"color:inherit;padding:10px 14px 4px 14px;'>"
                f"Recent Price History (Last 7 Days)</div>"
                f"<table style='width:100%;border-collapse:collapse;"
                f"table-layout:auto;'>"
                f"<thead><tr>"
                f"<th style='{_hdr_style}text-align:left;'>Date</th>"
                f"<th style='{_hdr_style}text-align:right;'>Price</th>"
                f"<th style='{_hdr_style}text-align:right;'>Change</th>"
                f"</tr></thead>"
                f"<tbody>{_rows_html}</tbody>"
                f"</table>"
                f"</div>",
                unsafe_allow_html=True,
            )

        # ══════════════════════════════════════════════
        # 4. TECHNICAL SIGNALS
        # ══════════════════════════════════════════════
        bx_header("Technical Signals", "bx-pulse", level=3)

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

            # All three Technical Signals cards are rendered as custom
            # HTML using the same .tw-snap-card class as Snapshot /
            # Overview / Financials / Market Data / Performance — so
            # they get the rounded corners, green left accent bar, and
            # SWOT-style slide-right hover animation. A shared fixed
            # pixel height keeps the row visually balanced.
            _TS_CARD_HEIGHT = 220
            _POS_COLOR = "#16a34a"
            _NEG_COLOR = "#dc2626"
            _MUTED = "opacity:0.65"

            def _ts_row(label: str, value_html: str) -> str:
                """One label/value row inside a Technical Signals card."""
                return (
                    f"<div style='display:flex;justify-content:space-between;"
                    f"align-items:center;padding:7px 0;font-size:13.5px;'>"
                    f"<span style='color:inherit;{_MUTED}'>{label}</span>"
                    f"<span style='text-align:right;font-weight:600;"
                    f"color:inherit'>{value_html}</span>"
                    f"</div>"
                )

            def _ts_card(title: str, body_html: str) -> str:
                """Wrap inner rows in a .tw-snap-card with a fixed height."""
                return (
                    f"<div class='tw-snap-card' style='padding:16px 20px;"
                    f"min-height:auto;height:{_TS_CARD_HEIGHT}px;"
                    f"margin-bottom:12px;overflow:hidden;'>"
                    f"<div style='font-weight:700;font-size:14px;"
                    f"color:inherit;margin-bottom:8px;'>{title}</div>"
                    f"{body_html}"
                    f"</div>"
                )

            # ── Moving Averages card ──
            _ma_rows = ""
            _ma_states: list[bool] = []  # True if price above MA, False if below
            for ma_label, ma_val in [
                ("MA 20", latest_sma20),
                ("MA 50", latest_sma50),
                ("MA 200", latest_sma200),
            ]:
                if ma_val is not None:
                    _above = latest_price > ma_val
                    _ma_states.append(_above)
                    _dot_col = _POS_COLOR if _above else _NEG_COLOR
                    _signal = "Above" if _above else "Below"
                    _left = (
                        f"<span style='color:{_dot_col};margin-right:6px;"
                        f"font-size:11px;'>●</span>"
                        f"<span style='color:inherit;{_MUTED}'>{ma_label}</span>"
                        f"<span style='color:inherit;opacity:0.5;margin:0 6px;'>·</span>"
                        f"<span style='color:{_dot_col};font-weight:700;'>{_signal}</span>"
                    )
                    _right = f"{_cur}{ma_val:,.0f}"
                else:
                    _left = (
                        f"<span style='color:inherit;opacity:0.4;margin-right:6px;'>○</span>"
                        f"<span style='color:inherit;{_MUTED}'>{ma_label}</span>"
                    )
                    _right = "<span style='opacity:0.5'>—</span>"
                _ma_rows += (
                    f"<div style='display:flex;justify-content:space-between;"
                    f"align-items:center;padding:7px 0;font-size:13.5px;'>"
                    f"<span>{_left}</span>"
                    f"<span style='text-align:right;font-weight:700;"
                    f"color:inherit;'>{_right}</span>"
                    f"</div>"
                )

            # ── Trend interpretation (appended below MA rows) ──
            # Summarise the short-/medium-/long-term stack in plain English so
            # the user doesn't have to piece it together from the three dots.
            # Assumes _ma_states is in the order [MA20, MA50, MA200] as built
            # from the loop above.
            _trend_text = ""
            _trend_col = "inherit"
            if len(_ma_states) == 3:
                _a20, _a50, _a200 = _ma_states
                if _a20 and _a50 and _a200:
                    _trend_text = "Strong uptrend — price above all 3 MAs."
                    _trend_col = _POS_COLOR
                elif not _a20 and not _a50 and not _a200:
                    _trend_text = "Strong downtrend — price below all 3 MAs."
                    _trend_col = _NEG_COLOR
                elif _a20 and _a200 and not _a50:
                    _trend_text = (
                        "Mixed signal — above short- and long-term MAs but "
                        "below MA50. Watch for reclaim of MA50."
                    )
                elif _a20 and not _a50 and not _a200:
                    _trend_text = (
                        "Early recovery — price reclaimed MA20 but medium- "
                        "and long-term trends still down."
                    )
                elif not _a20 and _a50 and _a200:
                    _trend_text = (
                        "Pullback within uptrend — below MA20 but holding "
                        "above MA50/MA200."
                    )
                elif not _a20 and not _a50 and _a200:
                    _trend_text = (
                        "Weakening trend — broke MA20 and MA50, MA200 still "
                        "providing long-term support."
                    )
                elif _a20 and _a50 and not _a200:
                    _trend_text = (
                        "Short-term rally against a long-term downtrend — "
                        "below MA200."
                    )
                else:
                    _trend_text = "Mixed short- vs. long-term signals."
            elif len(_ma_states) >= 1:
                _above_ct = sum(_ma_states)
                _trend_text = (
                    f"{_above_ct} of {len(_ma_states)} MAs above price — "
                    "partial data only."
                )

            if _trend_text:
                _ma_rows += (
                    f"<div style='margin-top:8px;padding-top:8px;"
                    f"border-top:1px solid rgba(128,128,128,0.18);"
                    f"font-size:11.5px;color:{_trend_col};opacity:0.95;"
                    f"line-height:1.35;'>{_trend_text}</div>"
                )

            with ts1:
                st.markdown(_ts_card("Moving Averages", _ma_rows), unsafe_allow_html=True)

            # ── Momentum card ──
            with ts2:
                if latest_rsi is not None:
                    _rsi_label = (
                        "Neutral" if 30 < latest_rsi < 70
                        else ("Overbought" if latest_rsi >= 70 else "Oversold")
                    )
                    _rsi_kind = (
                        "amber" if _rsi_label == "Neutral"
                        else ("red" if _rsi_label == "Overbought" else "green")
                    )
                    # Plain-English RSI interpretation so the user doesn't have
                    # to recall what the 30/70 thresholds imply.
                    if _rsi_label == "Overbought":
                        _rsi_hint = "Potential short-term pullback risk."
                        _rsi_hint_col = _NEG_COLOR
                    elif _rsi_label == "Oversold":
                        _rsi_hint = "Potential reversal opportunity."
                        _rsi_hint_col = _POS_COLOR
                    else:
                        _rsi_hint = "Momentum within normal range."
                        _rsi_hint_col = "inherit"

                    _macd_badge = (
                        _badge("Bullish", "green") if macd_bullish
                        else _badge("Bearish", "red")
                    )
                    _mom_body = (
                        _ts_row(
                            "RSI (14)",
                            f"{latest_rsi:.1f} {_badge(_rsi_label, _rsi_kind)}",
                        )
                        + _ts_row("MACD", _macd_badge)
                        + _ts_row("Volatility", f"{volatility:.1%}")
                        + (
                            f"<div style='margin-top:6px;padding-top:6px;"
                            f"border-top:1px solid rgba(128,128,128,0.18);"
                            f"font-size:11.5px;color:{_rsi_hint_col};"
                            f"opacity:0.95;line-height:1.35;'>"
                            f"{_rsi_hint}</div>"
                        )
                    )
                else:
                    _mom_body = "<div style='opacity:0.5'>—</div>"
                st.markdown(_ts_card("Momentum", _mom_body), unsafe_allow_html=True)

            # ── Drawdown & Risk card ──
            with ts3:
                pct_from_ath = data.market_data.percentage_change_from_high
                yr_return = data.market_data.year_change
                beta = data.market_data.beta
                _dr_rows: list[str] = []
                if pct_from_ath is not None:
                    _col = _NEG_COLOR if pct_from_ath < 0 else _POS_COLOR
                    _dr_rows.append(_ts_row(
                        "From ATH",
                        f"<span style='color:{_col}'>{pct_from_ath:+.2f}%</span>",
                    ))
                if yr_return is not None:
                    _col = _POS_COLOR if yr_return >= 0 else _NEG_COLOR
                    _dr_rows.append(_ts_row(
                        "1Y Return",
                        f"<span style='color:{_col}'>{yr_return:+.2f}%</span>",
                    ))
                if beta is not None:
                    _dr_rows.append(_ts_row("Beta", f"{beta:.2f}"))
                _dr_body = "".join(_dr_rows) if _dr_rows else "<div style='opacity:0.5'>—</div>"
                st.markdown(_ts_card("Drawdown & Risk", _dr_body), unsafe_allow_html=True)

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
            for _c, _title in zip((ts1, ts2, ts3), ("Moving Averages", "Momentum", "Drawdown & Risk")):
                with _c:
                    st.markdown(
                        f"<div class='tw-snap-card' style='padding:16px 20px;"
                        f"min-height:120px;margin-bottom:12px;'>"
                        f"<div style='font-weight:700;font-size:14px;"
                        f"color:inherit;margin-bottom:8px;'>{_title}</div>"
                        f"<div style='opacity:0.5'>—</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
            st.info("No price history available for technical analysis")

        # ══════════════════════════════════════════════
        # 5. ANALYST & SENTIMENT
        # ══════════════════════════════════════════════
        bx_header("Analyst & Sentiment", "bx-user-voice", level=3)

        an1, an2 = st.columns(2)

        # Both cards use the same .tw-snap-card class (rounded corners,
        # green left accent bar, SWOT-style slide-right hover animation).
        # A shared fixed pixel height keeps the row visually balanced.
        _AN_CARD_HEIGHT = 160
        _AN_POS = "#16a34a"
        _AN_NEG = "#dc2626"

        # ── Drawdown Alert card ──
        # Flags stocks that have fallen ≥25% from their recent peak — a
        # "value candidate" screen used by the portfolio tracker. The old
        # "Selected / Not Selected" wording was ambiguous, so the card is
        # now titled "Drawdown Alert" with explicit Triggered / No Alert
        # states and a tooltip explaining the criterion.
        with an1:
            max_drop = getattr(data.market_data, 'max_drop_after_high', None)
            if max_drop is not None:
                _alert_on = max_drop <= -25
                _drop_val = max_drop
            elif data.market_data.percentage_change_from_high is not None:
                _alert_on = data.market_data.percentage_change_from_high <= -25
                _drop_val = data.market_data.percentage_change_from_high
            else:
                _alert_on = None
                _drop_val = None

            if _alert_on is not None:
                _sel_text = "Alert Triggered" if _alert_on else "No Alert"
                _sel_icon = "bxs-error-alt" if _alert_on else "bxs-check-shield"
                _sel_color = _AN_NEG if _alert_on else _AN_POS
                if _drop_val is not None:
                    if _alert_on:
                        _sub = f"Dropped {abs(_drop_val):.1f}% after peak — meets ≥25% drawdown threshold."
                    else:
                        _sub = f"Dropped {abs(_drop_val):.1f}% after peak — below 25% threshold."
                else:
                    _sub = ""
                _sub_html = (
                    f"<div style='font-size:12px;color:inherit;opacity:0.7;"
                    f"margin-top:6px;line-height:1.35;'>{_sub}</div>"
                    if _sub else ""
                )
                _body = (
                    f"<div style='font-size:1.4rem;font-weight:700;"
                    f"margin-top:4px;color:inherit;'>"
                    f"<i class='bx {_sel_icon}' style='color:{_sel_color};"
                    f"margin-right:8px;vertical-align:-3px;'></i>{_sel_text}"
                    f"</div>{_sub_html}"
                )
            else:
                _body = (
                    "<div style='opacity:0.5;margin-top:4px;'>—</div>"
                    "<div style='font-size:12px;opacity:0.65;margin-top:6px;'>"
                    "Insufficient price history to evaluate drawdown.</div>"
                )
            st.markdown(
                f"<div class='tw-snap-card' style='padding:16px 20px;"
                f"min-height:auto;height:{_AN_CARD_HEIGHT}px;"
                f"margin-bottom:12px;overflow:hidden;'>"
                f"<div style='font-weight:700;font-size:14px;"
                f"color:inherit;margin-bottom:4px;' "
                f"title='Flags stocks that have dropped 25%+ from their recent peak — a value-candidate screen.'>"
                f"Drawdown Alert</div>"
                f"{_body}"
                f"</div>",
                unsafe_allow_html=True,
            )

        # ── Overall Price Range card ──
        with an2:
            oh = data.market_data.overall_high
            ol = data.market_data.overall_low
            pct_ath = data.market_data.percentage_change_from_high
            if oh is not None and ol is not None:
                _range_html = (
                    f"<div style='font-size:1.2rem;font-weight:700;"
                    f"margin-top:4px;color:inherit;'>"
                    f"{_cur}{ol:,.2f} – {_cur}{oh:,.2f}</div>"
                )
                if pct_ath is not None:
                    _col = _AN_NEG if pct_ath < 0 else _AN_POS
                    _range_html += (
                        f"<div style='color:{_col};font-weight:600;"
                        f"margin-top:6px;font-size:13px;'>"
                        f"{pct_ath:+.2f}% from ATH</div>"
                    )
                _body2 = _range_html
            else:
                _body2 = "<div style='opacity:0.5;margin-top:4px;'>—</div>"
            st.markdown(
                f"<div class='tw-snap-card' style='padding:16px 20px;"
                f"min-height:auto;height:{_AN_CARD_HEIGHT}px;"
                f"margin-bottom:12px;overflow:hidden;'>"
                f"<div style='font-weight:700;font-size:14px;"
                f"color:inherit;margin-bottom:4px;'>Overall Price Range</div>"
                f"{_body2}"
                f"</div>",
                unsafe_allow_html=True,
            )

        # =========================
        # =========================
        # Competitors (with detailed table)
        # =========================
        if data.market_data.competitors:
            st.markdown("---")
            bx_header("Competitors", "bx-buildings")
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
            
            # Render the comparison as a custom HTML table wrapped in a
            # .tw-snap-card — so it gets the same rounded corners, green
            # left accent bar, and SWOT-style slide-right hover animation
            # as every other dashboard section. Metric labels live in the
            # left column; each company has its own right-aligned column,
            # and the main company's column header gets a highlighted
            # background so users can spot it at a glance.
            if companies and company_data:
                import html as _comp_html
                metrics = ['Symbol', 'Market Cap', 'Revenue', 'PE Ratio', 'Profit Margin']

                _hdr_style = (
                    "padding:10px 12px;font-size:11px;"
                    "letter-spacing:0.06em;text-transform:uppercase;"
                    "font-weight:700;color:inherit;opacity:0.75;"
                    "border-bottom:1px solid rgba(128,128,128,0.25);"
                    "white-space:nowrap;"
                )
                _hdr_main_style = (
                    _hdr_style
                    + "background:rgba(116,229,4,0.12);color:#74e504;opacity:1;"
                )
                _cell_base = (
                    "padding:9px 12px;font-size:13px;color:inherit;"
                    "border-bottom:0.5px solid rgba(128,128,128,0.14);"
                )

                # Build header row: "METRIC" + one column per company
                _ths = [f"<th style='{_hdr_style}text-align:left;'>METRIC</th>"]
                for _comp in companies:
                    _is_main = "⭐" in _comp
                    _style = _hdr_main_style if _is_main else _hdr_style
                    _ths.append(
                        f"<th style='{_style}text-align:right;'>"
                        f"{_comp_html.escape(_comp)}</th>"
                    )
                _header_html = "<thead><tr>" + "".join(_ths) + "</tr></thead>"

                # Build body rows: one row per metric
                _trs = []
                for _metric in metrics:
                    _cells = [
                        f"<td style='{_cell_base}text-align:left;"
                        f"font-weight:600;opacity:0.75;'>{_comp_html.escape(_metric)}</td>"
                    ]
                    for _comp in companies:
                        _val = company_data[_comp].get(_metric, 'N/A') or 'N/A'
                        _is_main = "⭐" in _comp
                        _cell_style = _cell_base + "text-align:right;font-weight:600;"
                        if _is_main:
                            _cell_style += "background:rgba(116,229,4,0.06);"
                        _cells.append(
                            f"<td style='{_cell_style}'>"
                            f"{_comp_html.escape(str(_val))}</td>"
                        )
                    _trs.append("<tr>" + "".join(_cells) + "</tr>")
                _body_html = "<tbody>" + "".join(_trs) + "</tbody>"

                st.markdown(
                    f"<div class='tw-snap-card' style='padding:6px 8px;"
                    f"min-height:auto;margin-bottom:12px;overflow-x:auto;'>"
                    f"<div style='font-weight:700;font-size:14px;"
                    f"color:inherit;padding:10px 14px 4px 14px;'>"
                    f"Competitor Comparison"
                    f"</div>"
                    f"<table style='width:100%;border-collapse:collapse;'>"
                    f"{_header_html}{_body_html}"
                    f"</table>"
                    f"<div style='font-size:11px;color:inherit;opacity:0.6;"
                    f"padding:8px 14px 10px 14px;'>"
                    f"⭐ = Your selected company &nbsp;·&nbsp; "
                    f"Data from real-time sources</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

        # ══════════════════════════════════════════════
        # SWOT ANALYSIS — 2x2 grid
        # ══════════════════════════════════════════════
        _swot_obj = getattr(data, "swot", None)
        _swot_src = {
            "strengths": list(getattr(_swot_obj, "strengths", []) or []),
            "weaknesses": list(getattr(_swot_obj, "weaknesses", []) or []),
            "opportunities": list(getattr(_swot_obj, "opportunities", []) or []),
            "threats": list(getattr(_swot_obj, "threats", []) or []),
        }
        if not any(_swot_src.values()):
            _swot_src = _parsed.get("swot", _swot_src) or _swot_src

        if any(_swot_src.values()):
            st.markdown("---")
            bx_header("SWOT Analysis", "bx-target-lock", level=3)

            # Rounded-corner cards with the same hover-animation treatment
            # as the news cards: theme-neutral gray background, per-quadrant
            # accent on the left border, and on hover a tinted background +
            # stronger border + subtle slide & glow — all using the card's
            # own accent colour via a CSS custom property (`--accent`).
            import html as _swot_html_mod
            st.markdown("""
            <style>
            .tw-swot-card {
                --accent: #74e504;
                background: rgba(128, 128, 128, 0.06);
                border: 1px solid rgba(128, 128, 128, 0.22);
                border-left: 3px solid var(--accent);
                border-radius: 8px;
                padding: 16px 20px;
                height: 220px;
                margin-bottom: 12px;
                transition: background 0.2s ease,
                            border-color 0.2s ease,
                            transform 0.2s ease,
                            box-shadow 0.2s ease;
                overflow: hidden;
            }
            .tw-swot-card:hover {
                background: color-mix(in srgb, var(--accent) 10%, transparent);
                border-color: color-mix(in srgb, var(--accent) 40%, transparent);
                border-left-color: var(--accent);
                transform: translateX(2px);
                box-shadow: 0 2px 12px color-mix(in srgb, var(--accent) 18%, transparent);
            }
            .tw-swot-title {
                color: var(--accent);
                font-weight: 700; font-size: 13px;
                letter-spacing: 0.08em; text-transform: uppercase;
                margin-bottom: 10px;
                display: flex; align-items: center; gap: 6px;
            }
            .tw-swot-list {
                list-style: disc; padding-left: 20px; margin: 0;
                color: inherit;
            }
            .tw-swot-list li {
                font-size: 13.5px; line-height: 1.55; margin-bottom: 4px;
            }
            </style>
            """, unsafe_allow_html=True)

            def _render_swot_card(
                items: list[str],
                title: str,
                icon_cls: str,
                accent: str,
            ) -> None:
                """Render one SWOT quadrant as a rounded hover-animated card."""
                _rendered = [i for i in items if i]
                if _rendered:
                    _items_html = "".join(
                        f"<li>{_swot_html_mod.escape(_item)}</li>"
                        for _item in _rendered
                    )
                    _body = f'<ul class="tw-swot-list">{_items_html}</ul>'
                else:
                    _body = ("<div style='color:inherit;opacity:0.55;"
                             "font-size:13px;'>Not available</div>")
                st.markdown(
                    f"<div class='tw-swot-card' style='--accent:{accent};'>"
                    f"<div class='tw-swot-title'>"
                    f"<i class='bx {icon_cls}' style='color:{accent};"
                    f"vertical-align:-2px;font-size:1.1em;'></i>{title}"
                    f"</div>"
                    f"{_body}"
                    f"</div>",
                    unsafe_allow_html=True,
                )

            _sw_row1 = st.columns(2)
            with _sw_row1[0]:
                _render_swot_card(
                    _swot_src["strengths"], "Strengths",
                    "bxs-check-shield", "#22c55e",
                )
            with _sw_row1[1]:
                _render_swot_card(
                    _swot_src["weaknesses"], "Weaknesses",
                    "bxs-error-alt", "#ef4444",
                )
            _sw_row2 = st.columns(2)
            with _sw_row2[0]:
                _render_swot_card(
                    _swot_src["opportunities"], "Opportunities",
                    "bxs-rocket", "#3b82f6",
                )
            with _sw_row2[1]:
                _render_swot_card(
                    _swot_src["threats"], "Threats",
                    "bxs-shield-x", "#f97316",
                )

        # ══════════════════════════════════════════════
        # NEWS & ANNOUNCEMENTS
        # ══════════════════════════════════════════════
        _news_items: list[dict] = []
        for _n in getattr(data, "news", None) or []:
            if isinstance(_n, dict):
                _news_items.append(
                    {
                        "headline": _n.get("title") or _n.get("headline", ""),
                        "source": _n.get("source", "") or "",
                        "date": _n.get("date", "") or _n.get("published", "") or "",
                        "url": _n.get("url", "") or _n.get("link", "") or "",
                    }
                )
        if not _news_items and _parsed.get("news"):
            _news_items = list(_parsed["news"])

        if _news_items:
            st.markdown("---")
            bx_header("News & Announcements", "bx-news", level=3)
            # Keep the rounded pill card + green hover animation, but swap
            # every hardcoded dark colour for a theme-neutral rgba (soft
            # gray outline, `inherit` text) so the same card renders fine
            # on both light and dark backgrounds. The accent green
            # (#74e504) on hover / icon / link stays the same because it
            # reads well on either theme.
            st.markdown("""
            <style>
            .tw-news-card {
                background: rgba(128, 128, 128, 0.06);
                border: 1px solid rgba(128, 128, 128, 0.22);
                border-radius: 8px;
                padding: 14px 16px; margin-bottom: 10px;
                transition: background 0.2s ease,
                            border-left-color 0.2s ease,
                            border-color 0.2s ease,
                            transform 0.2s ease,
                            box-shadow 0.2s ease;
                border-left: 3px solid transparent;
                display: flex; justify-content: space-between; gap: 12px;
            }
            .tw-news-card:hover {
                background: rgba(116, 229, 4, 0.10);
                border-color: rgba(116, 229, 4, 0.35);
                border-left-color: #74e504;
                transform: translateX(2px);
                box-shadow: 0 2px 10px rgba(116, 229, 4, 0.15);
            }
            .tw-news-headline {
                color: inherit;
                font-size: 14px; font-weight: 600;
                line-height: 1.45; display: -webkit-box;
                -webkit-line-clamp: 2; -webkit-box-orient: vertical;
                overflow: hidden; text-overflow: ellipsis;
            }
            .tw-news-meta {
                color: inherit; opacity: 0.65;
                font-size: 12px; margin-top: 4px;
            }
            .tw-news-link {
                color: #74e504; text-decoration: none; font-size: 12px;
                font-weight: 600;
                white-space: nowrap; align-self: flex-start;
            }
            .tw-news-link:hover { text-decoration: underline; }
            .tw-news-headline .bx {
                color: #74e504; margin-right: 8px; vertical-align: -2px;
                font-size: 1.05em;
            }
            </style>
            """, unsafe_allow_html=True)

            _visible = _news_items[:5]
            for _item in _visible:
                _link = _item.get("url", "")
                _headline = _item.get("headline", "")
                _meta_bits = [b for b in [_item.get("source", ""), _item.get("date", "")] if b]
                _meta_line = "  ·  ".join(_meta_bits)
                # Build the "Read ↗" link inline with the meta row so it's
                # clearly visible right under the headline — not a tiny
                # floating element on the far right that gets cropped.
                if _link:
                    if _meta_line:
                        _meta_line += "  ·  "
                    _meta_line += f'<a class="tw-news-link" href="{_link}" target="_blank">Read ↗</a>'
                _meta_html = (
                    f'<div class="tw-news-meta">{_meta_line}</div>'
                    if _meta_line
                    else ""
                )
                st.markdown(
                    f'<div class="tw-news-card">'
                    f'<div style="flex:1">'
                    f'<div class="tw-news-headline"><i class="bx bxs-news"></i>{_headline}</div>'
                    f'{_meta_html}'
                    f'</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            if len(_news_items) > 5:
                with st.expander(f"Show {len(_news_items) - 5} more"):
                    for _item in _news_items[5:]:
                        _link = _item.get("url", "")
                        _headline = _item.get("headline", "")
                        if _link:
                            st.markdown(f"- **{_headline}**  ·  [Read ↗]({_link})")
                        else:
                            st.markdown(f"- **{_headline}**")

        # ══════════════════════════════════════════════
        # UNIFIED INVESTMENT INSIGHT
        # Merges expert-opinion (market/analyst view) and Screener.in quarterly
        # PDF summary (fundamentals/financials view) into a single analyst
        # synthesis rendered as one card. For cached analyses written before
        # the unified rollout we fall back to concatenating the two legacy
        # sections so older reports still render something meaningful.
        # ══════════════════════════════════════════════
        _unified_text = (_parsed.get("unifiedInsight") or "").strip()
        _expert_text = (_parsed.get("expertOpinion") or "").strip()
        _screener_text = (_parsed.get("screenerSummary") or "").strip()

        # Prefer the unified insight. If absent (legacy cached response),
        # stitch the two legacy blocks together so the user sees the content.
        _insight_body = ""
        _insight_is_legacy = False
        if _unified_text:
            _insight_body = _unified_text
        elif _expert_text and _screener_text:
            _insight_body = (
                f"{_expert_text}\n\n"
                "— — —\n\n"
                f"{_screener_text}"
            )
            _insight_is_legacy = True
        elif _expert_text:
            _insight_body = _expert_text
            _insight_is_legacy = True
        elif _screener_text:
            _insight_body = _screener_text
            _insight_is_legacy = True

        if _insight_body:
            st.markdown("---")

            # Render the Unified Investment Insight card using the same
            # .tw-snap-card class as every other dashboard section —
            # rounded corners, green left accent bar, SWOT-style slide-
            # right hover animation. Theme-neutral colours replace the
            # old hardcoded dark gradient/white text so the card reads
            # correctly in both light and dark modes.
            import html as _html
            _safe_body = _html.escape(_insight_body).replace("\n", "<br>")
            _subtitle = (
                "Synthesized from expert analysis &amp; official quarterly reports"
                if not _insight_is_legacy
                else "Legacy report — expert opinion &amp; screener summary "
                     "(re-analyze to generate a unified insight)"
            )
            _footer = (
                "<i class='bx bxs-book-bookmark' style='vertical-align:-2px;"
                "margin-right:6px;'></i>Sources: Expert Market Analysis "
                "+ Screener.in Quarterly PDFs"
                if not _insight_is_legacy
                else "<i class='bx bxs-book-bookmark' style='vertical-align:-2px;"
                     "margin-right:6px;'></i>Sources: archived expert-opinion "
                     "+ screener summary"
            )
            st.markdown(
                f"<div class='tw-snap-card' style='padding:22px 26px;"
                f"min-height:auto;margin-top:12px;margin-bottom:14px;"
                f"border-left-width:4px;'>"
                f"<div style='color:#74e504;font-weight:700;font-size:14px;"
                f"letter-spacing:0.08em;text-transform:uppercase;"
                f"margin-bottom:4px;'>"
                f"<i class='bx bx-brain' style='color:#74e504;margin-right:6px;"
                f"vertical-align:-2px;font-size:1.15em;'></i>"
                f"Unified Investment Insight</div>"
                f"<div style='color:inherit;opacity:0.65;font-size:12px;"
                f"font-weight:500;margin-bottom:18px;'>{_subtitle}</div>"
                f"<div style='color:inherit;font-size:15px;line-height:1.7;"
                f"white-space:pre-wrap;'>{_safe_body}</div>"
                f"<div style='color:inherit;opacity:0.6;font-size:12px;"
                f"margin-top:18px;padding-top:12px;"
                f"border-top:1px solid rgba(128,128,128,0.22);'>{_footer}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

        # ══════════════════════════════════════════════
        # FUTURE OUTLOOK & NEWS ANALYSIS
        # Fetched in parallel with the main agent in the dashboard search block.
        # Keyed by stock symbol so switching stocks shows the right result.
        # ══════════════════════════════════════════════
        _news_cache = st.session_state.get("dash_news_analysis")
        _news_symbol = st.session_state.get("dash_news_analysis_symbol")
        if _news_cache and _news_symbol == data.symbol:
            st.markdown("---")
            bx_header("Future Outlook & News Analysis", "bx-bulb", level=3)

            _articles = _news_cache.get("articles") or []
            _n_sources = len({(_a.get("source") or "").strip() or "Unknown" for _a in _articles})

            if _news_cache.get("error"):
                st.warning(f"⚠️ Could not fetch news analysis: {_news_cache.get('error')}")
            else:
                _od = _news_cache.get("outlook_data") or {}

                # Build the main body as a single HTML string, then wrap
                # it all in one .tw-snap-card so the whole outlook +
                # analysis slides right with a green wash on hover — same
                # animation as SWOT / Snapshot / every other section.
                import html as _fut_html
                _body_parts: list[str] = []

                # ── Outlook verdict badge ────────────────────────────────
                _verdict = _od.get("outlook", "")
                _emoji = _od.get("outlook_emoji", "🟡")
                if _verdict:
                    _v_lower = _verdict.lower()
                    if "bullish" in _v_lower:
                        _vcolor = "#16a34a"
                    elif "bearish" in _v_lower:
                        _vcolor = "#dc2626"
                    else:
                        _vcolor = "#d97706"
                    _body_parts.append(
                        f"<div style='display:flex;align-items:center;"
                        f"gap:12px;margin:4px 0 18px 0;flex-wrap:wrap;'>"
                        f"<span style='font-size:1.6rem'>{_emoji}</span>"
                        f"<span style='background:{_vcolor}1f;"
                        f"border:1px solid {_vcolor}66;color:{_vcolor};"
                        f"padding:6px 16px;border-radius:999px;"
                        f"font-weight:700;font-size:14px;"
                        f"letter-spacing:0.02em;'>"
                        f"{_fut_html.escape(_verdict)}</span>"
                        f"<span style='color:inherit;opacity:0.65;font-size:13px;'>"
                        f"Based on {len(_articles)} "
                        f"article{'s' if len(_articles)!=1 else ''} "
                        f"from {_n_sources} "
                        f"source{'s' if _n_sources!=1 else ''}</span>"
                        f"</div>"
                    )

                _section_label_style = (
                    "font-size:11px;color:inherit;opacity:0.65;"
                    "text-transform:uppercase;letter-spacing:0.08em;"
                    "font-weight:600;margin:14px 0 6px 0;"
                )

                # ── Analyst & Market View ────────────────────────────────
                _av = (_od.get("analyst_view") or "").strip()
                if _av:
                    _body_parts.append(
                        f"<div style='{_section_label_style}'>"
                        f"Analyst &amp; Market View</div>"
                        f"<div style='color:inherit;font-size:14px;"
                        f"line-height:1.6;'>{_fut_html.escape(_av)}</div>"
                    )

                # ── Financial Performance ────────────────────────────────
                _perf = (_od.get("performance") or "").strip()
                if _perf:
                    _body_parts.append(
                        f"<div style='{_section_label_style}'>"
                        f"Recent Financial Performance</div>"
                        f"<div style='color:inherit;font-size:14px;"
                        f"line-height:1.6;'>{_fut_html.escape(_perf)}</div>"
                    )

                # ── Growth Drivers + Risk Factors side by side ───────────
                _drivers = _od.get("growth_drivers") or []
                _risks = _od.get("risk_factors") or []
                if _drivers or _risks:
                    _bullet_style = (
                        "padding:8px 12px;border-radius:0 6px 6px 0;"
                        "margin-bottom:6px;font-size:13px;line-height:1.55;"
                        "color:inherit;background:rgba(128,128,128,0.05);"
                    )
                    _drivers_html = ""
                    for _d in _drivers:
                        _drivers_html += (
                            f"<div style='{_bullet_style}"
                            f"border-left:3px solid #16a34a;'>"
                            f"{_fut_html.escape(_d)}</div>"
                        )
                    _risks_html = ""
                    for _r in _risks:
                        _risks_html += (
                            f"<div style='{_bullet_style}"
                            f"border-left:3px solid #dc2626;'>"
                            f"{_fut_html.escape(_r)}</div>"
                        )
                    _body_parts.append(
                        f"<div style='display:grid;"
                        f"grid-template-columns:1fr 1fr;gap:14px;"
                        f"margin-top:14px;'>"
                        f"<div>"
                        f"<div style='font-size:11px;color:#16a34a;"
                        f"text-transform:uppercase;letter-spacing:0.08em;"
                        f"font-weight:600;margin-bottom:6px;'>"
                        f"🟢 Growth Drivers</div>"
                        f"{_drivers_html}"
                        f"</div>"
                        f"<div>"
                        f"<div style='font-size:11px;color:#dc2626;"
                        f"text-transform:uppercase;letter-spacing:0.08em;"
                        f"font-weight:600;margin-bottom:6px;'>"
                        f"🔴 Risk Factors</div>"
                        f"{_risks_html}"
                        f"</div>"
                        f"</div>"
                    )

                # Render the whole body as one animated .tw-snap-card.
                if _body_parts:
                    st.markdown(
                        f"<div class='tw-snap-card' style='padding:20px 24px;"
                        f"min-height:auto;margin-bottom:14px;"
                        f"border-left-width:4px;'>"
                        f"{''.join(_body_parts)}"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

                # ── Target & Consensus row — each as its own animated card ──
                _target = (_od.get("target_price") or "").strip()
                _consensus = (_od.get("consensus") or "").strip()
                if (_target and _target.lower() != "not available") or \
                   (_consensus and _consensus.lower() != "not available"):
                    _tc1, _tc2 = st.columns(2)
                    _metric_card_style = (
                        "padding:14px 18px;min-height:auto;margin-bottom:12px;"
                    )
                    _metric_label_style = (
                        "font-size:11px;opacity:0.65;letter-spacing:0.04em;"
                        "text-transform:uppercase;font-weight:500;"
                        "margin-bottom:6px;color:inherit;"
                    )
                    _metric_value_style = (
                        "font-size:1.15rem;font-weight:700;color:inherit;"
                        "line-height:1.2;"
                    )
                    if _target and _target.lower() != "not available":
                        with _tc1:
                            st.markdown(
                                f"<div class='tw-snap-card' style='{_metric_card_style}'>"
                                f"<div style='{_metric_label_style}'>"
                                f"🎯 Analyst Price Target</div>"
                                f"<div style='{_metric_value_style}'>"
                                f"{_fut_html.escape(_target)}</div>"
                                f"</div>",
                                unsafe_allow_html=True,
                            )
                    if _consensus and _consensus.lower() != "not available":
                        with _tc2:
                            st.markdown(
                                f"<div class='tw-snap-card' style='{_metric_card_style}'>"
                                f"<div style='{_metric_label_style}'>"
                                f"📊 Analyst Consensus</div>"
                                f"<div style='{_metric_value_style}'>"
                                f"{_fut_html.escape(_consensus)}</div>"
                                f"</div>",
                                unsafe_allow_html=True,
                            )

                # ── Fallback: if outlook_data is empty, show raw text ────
                if not _od:
                    _analysis_text = (_news_cache.get("analysis") or "").strip()
                    if _analysis_text:
                        st.caption(
                            f"Based on {len(_articles)} article{'s' if len(_articles)!=1 else ''} "
                            f"from {_n_sources} source{'s' if _n_sources!=1 else ''}"
                        )
                        st.markdown(_analysis_text)

                # ── Full report (collapsible) ────────────────────────────
                _analysis_text = (_news_cache.get("analysis") or "").strip()
                _tavily_summary = (_news_cache.get("tavily_summary") or "").strip()
                if _analysis_text or _tavily_summary:
                    with st.expander("📝 View full detailed report", expanded=False):
                        if _analysis_text:
                            st.markdown(_analysis_text)
                        if _tavily_summary:
                            st.markdown("---")
                            st.info(_tavily_summary)

                # ── Source articles (collapsible) ────────────────────────
                if _articles:
                    with st.expander(f"📚 Source Articles ({len(_articles)})", expanded=False):
                        for _i, _a in enumerate(_articles, 1):
                            _title = (_a.get("title") or "Untitled").strip()
                            _src = _a.get("source", "Unknown")
                            _snippet = (_a.get("snippet") or "").strip()
                            _url = _a.get("url")
                            st.markdown(f"**{_i}. {_title[:100]}**")
                            _meta = f"*{_src}*"
                            if _url:
                                _meta += f"  ·  [Read ↗]({_url})"
                            st.caption(_meta)
                            if _snippet:
                                st.markdown(f"> {_snippet[:200]}")
                            if _i < len(_articles):
                                st.markdown("---")

                # ── Refresh button ───────────────────────────────────────
                if st.button("🔄 Refresh News Analysis", key="dash_refresh_news"):
                    st.session_state.dash_news_analysis = None
                    st.session_state.dash_news_analysis_symbol = None
                    try:
                        with st.spinner("🔍 Re-fetching future outlook & news..."):
                            from tools import StockTools as _RefreshTools
                            _refreshed = _RefreshTools.get_stock_news_analysis(data.name, max_articles=5)
                            if _refreshed and not _refreshed.get("error"):
                                _refreshed["outlook_data"] = _distill_outlook(_refreshed, data.name)
                                st.session_state.dash_news_analysis = _refreshed
                                st.session_state.dash_news_analysis_symbol = data.symbol
                    except Exception as _re:
                        st.error(f"❌ Refresh failed: {_re}")
                    st.rerun()

        # ══════════════════════════════════════════════
        # FII & DII INSTITUTIONAL SENTIMENT
        # Quarterly shareholding analysis from screener.in.
        # Auto-runs once per symbol; cached in session state so switching
        # stocks or reruns don't re-fetch. Placed below Future Outlook
        # per client request.
        # ══════════════════════════════════════════════
        _fii_symbol_dash = data.symbol
        _fii_cache_key_dash = f"fii_dii_{_fii_symbol_dash}"

        st.markdown("---")
        bx_header("FII & DII Institutional Sentiment", "bxs-bank", level=3)
        st.caption("Track Foreign & Domestic Institutional buying/selling activity")

        _run_fii_dash = st.button("🔄 Refresh FII/DII", key="dash_run_fii_dii")
        _auto_run_fii_dash = _fii_cache_key_dash not in st.session_state

        if _run_fii_dash or _auto_run_fii_dash:
            _cached_fii_v = None
            _cached_dii_v = None
            if data.market_data:
                _cached_fii_v = data.market_data.fii_holding
                _cached_dii_v = data.market_data.dii_holding
                if _cached_fii_v is not None and _cached_fii_v < 1:
                    _cached_fii_v *= 100
                if _cached_dii_v is not None and _cached_dii_v < 1:
                    _cached_dii_v *= 100
            with st.spinner("Fetching FII/DII shareholding pattern..."):
                try:
                    from utils.fii_dii_analyzer import (
                        get_fii_dii_sentiment as _compute_fii_dii_dash,
                        persist_fii_dii_analysis as _persist_fii_dii_dash,
                    )
                    _fii_result_dash = _compute_fii_dii_dash(
                        symbol=_fii_symbol_dash,
                        company_name=data.name,
                        cached_fii=float(_cached_fii_v) if _cached_fii_v is not None else None,
                        cached_dii=float(_cached_dii_v) if _cached_dii_v is not None else None,
                    )
                    st.session_state[_fii_cache_key_dash] = _fii_result_dash
                    # Persist to DB so FinRobot can read it back as context
                    _persist_fii_dii_dash(_fii_symbol_dash, _fii_result_dash)
                except Exception as _fii_err_dash:
                    st.error(f"FII/DII analysis failed: {_fii_err_dash}")

        _fii_result_dash = st.session_state.get(_fii_cache_key_dash)
        if _fii_result_dash:
            _rec_colors_dash = {
                "green":   ("#e8f5e9", "#2e7d32"),
                "#4caf50": ("#f1f8e9", "#33691e"),
                "gray":    ("#f5f5f5", "#424242"),
                "orange":  ("#fff3e0", "#e65100"),
                "red":     ("#ffebee", "#c62828"),
            }
            _bg_dash, _fg_dash = _rec_colors_dash.get(
                _fii_result_dash.recommendation_color, ("#f5f5f5", "#424242")
            )
            st.markdown(
                f"<div style='background:{_bg_dash}; border-left:5px solid {_fg_dash}; "
                f"padding:14px 18px; border-radius:6px; margin:12px 0;'>"
                f"<div style='font-size:1.2em; font-weight:700; color:{_fg_dash};'>"
                f"{_fii_result_dash.recommendation}</div>"
                f"<div style='color:{_fg_dash}; margin-top:4px;'>"
                f"Institutional Score: {_fii_result_dash.institutional_sentiment_score:.1f}/100 "
                f"- {_fii_result_dash.sentiment_label}</div></div>",
                unsafe_allow_html=True,
            )

            _m1, _m2, _m3, _m4 = st.columns(4)
            with _m1:
                _fii_delta_dash = (
                    f"{_fii_result_dash.fii_change_1q:+.2f}pp"
                    if _fii_result_dash.fii_change_1q is not None else None
                )
                st.metric(
                    "FII Holding",
                    f"{_fii_result_dash.current_fii_pct:.2f}%",
                    delta=_fii_delta_dash,
                    delta_color="normal",
                )
            with _m2:
                _dii_delta_dash = (
                    f"{_fii_result_dash.dii_change_1q:+.2f}pp"
                    if _fii_result_dash.dii_change_1q is not None else None
                )
                st.metric(
                    "DII Holding",
                    f"{_fii_result_dash.current_dii_pct:.2f}%",
                    delta=_dii_delta_dash,
                    delta_color="normal",
                )
            with _m3:
                st.metric(
                    "Total Institutional",
                    f"{_fii_result_dash.current_total_institutional:.2f}%",
                )
            with _m4:
                st.metric(
                    "Inst. Score",
                    f"{_fii_result_dash.institutional_sentiment_score:.1f}/100",
                )

            def _trend_badge_dash(trend):
                colors = {
                    "Strongly Increasing": ("++", "green"),
                    "Increasing": ("+", "#4caf50"),
                    "Stable": ("=", "gray"),
                    "Decreasing": ("-", "orange"),
                    "Strongly Decreasing": ("--", "red"),
                }
                arrow, color = colors.get(trend, ("=", "gray"))
                return f"<span style='color:{color}; font-weight:600;'>{arrow} {trend}</span>"

            _t1, _t2 = st.columns(2)
            with _t1:
                st.markdown(
                    f"**FII Trend:** {_trend_badge_dash(_fii_result_dash.fii_trend)}",
                    unsafe_allow_html=True,
                )
                if _fii_result_dash.fii_change_4q is not None:
                    st.caption(f"4-quarter FII change: {_fii_result_dash.fii_change_4q:+.2f}pp")
            with _t2:
                st.markdown(
                    f"**DII Trend:** {_trend_badge_dash(_fii_result_dash.dii_trend)}",
                    unsafe_allow_html=True,
                )
                if _fii_result_dash.dii_change_4q is not None:
                    st.caption(f"4-quarter DII change: {_fii_result_dash.dii_change_4q:+.2f}pp")

            if len(_fii_result_dash.quarterly_history) >= 2:
                st.subheader("Quarterly Shareholding Trend")
                _quarters = [h.quarter for h in _fii_result_dash.quarterly_history]
                _fii_vals = [h.fii_pct for h in _fii_result_dash.quarterly_history]
                _dii_vals = [h.dii_pct for h in _fii_result_dash.quarterly_history]
                _total_vals = [round(f + d, 2) for f, d in zip(_fii_vals, _dii_vals)]

                _fig_dash = go.Figure()
                _fig_dash.add_trace(go.Scatter(
                    x=_quarters, y=_fii_vals, mode="lines+markers", name="FII %",
                    line=dict(color="#1976d2", width=2.5), marker=dict(size=7),
                    hovertemplate="Quarter: %{x}<br>FII: %{y:.2f}%<extra></extra>",
                ))
                _fig_dash.add_trace(go.Scatter(
                    x=_quarters, y=_dii_vals, mode="lines+markers", name="DII %",
                    line=dict(color="#388e3c", width=2.5), marker=dict(size=7),
                    hovertemplate="Quarter: %{x}<br>DII: %{y:.2f}%<extra></extra>",
                ))
                _fig_dash.add_trace(go.Scatter(
                    x=_quarters, y=_total_vals, mode="lines", name="Total Inst. %",
                    line=dict(color="#f57c00", width=2, dash="dot"),
                    hovertemplate="Quarter: %{x}<br>Total: %{y:.2f}%<extra></extra>",
                ))
                _fig_dash.update_layout(
                    xaxis_title="Quarter",
                    yaxis_title="Holding (%)",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    height=320,
                    margin=dict(t=20, b=20, l=10, r=10),
                    hovermode="x unified",
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                )
                _fig_dash.update_yaxes(gridcolor="rgba(128,128,128,0.15)")
                st.plotly_chart(_fig_dash, use_container_width=True)

            if _fii_result_dash.reasoning:
                st.subheader("Analysis")
                for _reason_dash in _fii_result_dash.reasoning:
                    st.info(f"  {_reason_dash}")

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
                f"Data source: {_fii_result_dash.data_source.replace('_', '.')} | "
                f"Freshness: {_fii_result_dash.data_freshness} | "
                f"Analyzed: {_fii_result_dash.timestamp.strftime('%d %b %Y %H:%M UTC')}"
            )

        # ── Deferred background-task kickoff ─────────────────────────
        # Fire the TradingView trade-ideas scraper AFTER every dashboard
        # section (Header → Chart → Snapshot → Overview → Financials →
        # Market Data → Performance → SWOT → Future Outlook → FII/DII)
        # has already rendered. Running it earlier raced with the
        # dashboard's own yfinance / screener enrichment and frequently
        # returned an empty result that got cached as success. Kickoff
        # is idempotent — duplicate calls for the same stock are
        # suppressed by `_should_start` in utils/background_tasks.py.
        try:
            from utils.background_tasks import kickoff_dashboard_bg_tasks
            _bg_clean_symbol = data.symbol.split(".")[0]
            _bg_exchange = "BSE" if data.symbol.endswith(".BO") else "NSE"
            kickoff_dashboard_bg_tasks(
                stock_name=data.name,
                stock_symbol=data.symbol,
                clean_symbol=_bg_clean_symbol,
                exchange=_bg_exchange,
            )
        except Exception as _bg_err:
            print(f"⚠️ Background task kickoff failed: {_bg_err}")

    elif not st.session_state.dash_is_loading and not st.session_state.dash_variants:
        # ── Welcome / hero state — shown until the user runs their first search ──
        # Uses SOLID colors (not color-mix / custom properties) inside the HTML
        # so the hero renders consistently in Streamlit's iframe on both themes.
        # Card layout uses st.columns for reliable cross-theme / cross-browser
        # rendering instead of CSS grid inside a markdown block.
        _hero_text_dark = _tw_theme_base == "dark"
        _hero_text_color = "#ffffff" if _hero_text_dark else "#0b1a05"
        _hero_sub_color = "#f3fff0" if _hero_text_dark else "#14290a"

        st.markdown(
            f"""
            <div style="
                background: linear-gradient(135deg, #74e504 0%, #5bb300 100%);
                border-radius: 14px;
                padding: 2.25rem 1.75rem;
                text-align: center;
                margin: 1rem 0 1.25rem 0;
                box-shadow: 0 8px 24px -10px rgba(116, 229, 4, 0.45);
            ">
                <div style="
                    font-size: 2rem; font-weight: 800;
                    color: {_hero_text_color};
                    margin-bottom: 0.4rem; letter-spacing: -0.01em;
                    line-height: 1.15;
                ">
                    <i class='bx bx-bar-chart-alt-2' style='color:{_hero_text_color};margin-right:10px;vertical-align:-3px;'></i>AI-Powered Stock Dashboard
                </div>
                <div style="
                    font-size: 1rem; font-weight: 500;
                    color: {_hero_sub_color};
                    max-width: 640px; margin: 0 auto; line-height: 1.5;
                ">
                    Real-time financials, technicals, sentiment &amp; expert
                    analysis — all in one view.
                </div>
            </div>

            <div style="
                background: #E1FDC6;
                border: 1px solid #9EF04D;
                border-left: 4px solid #74e504;
                border-radius: 10px;
                padding: 1rem 1.2rem;
                margin: 0 0 1.5rem 0;
                display: flex; align-items: center; gap: 0.75rem;
                box-shadow: 0 2px 10px rgba(116, 229, 4, 0.18);
            ">
                <i class='bx bxs-info-circle' style='color:#2E590E;font-size:1.5rem;flex-shrink:0;'></i>
                <div style="
                    color: #2E590E;
                    font-weight: 600; font-size: 0.95rem; line-height: 1.55;
                ">
                    Hi! Type a stock name or ticker in the search bar above and I'll
                    pull together a full analysis — fundamentals, holdings, news
                    sentiment, and a Buy/Hold/Sell view.
                </div>
            </div>

            <div style="
                display: flex; flex-wrap: wrap; gap: 8px;
                justify-content: center; margin-bottom: 1.75rem;
            ">
                <span style="background:{'#1e2b0c' if _hero_text_dark else '#E1FDC6'};
                    border:1.5px solid #74e504;
                    color:{'#ffffff' if _hero_text_dark else '#2E590E'};
                    padding:6px 14px;border-radius:999px;
                    font-size:12px;font-weight:700;letter-spacing:0.02em;">
                    Try <code style="color:{'#9EF04D' if _hero_text_dark else '#2E590E'};background:transparent;font-weight:800;">TCS</code>
                </span>
                <span style="background:{'#1e2b0c' if _hero_text_dark else '#E1FDC6'};
                    border:1.5px solid #74e504;
                    color:{'#ffffff' if _hero_text_dark else '#2E590E'};
                    padding:6px 14px;border-radius:999px;
                    font-size:12px;font-weight:700;letter-spacing:0.02em;">
                    Try <code style="color:{'#9EF04D' if _hero_text_dark else '#2E590E'};background:transparent;font-weight:800;">Reliance</code>
                </span>
                <span style="background:{'#1e2b0c' if _hero_text_dark else '#E1FDC6'};
                    border:1.5px solid #74e504;
                    color:{'#ffffff' if _hero_text_dark else '#2E590E'};
                    padding:6px 14px;border-radius:999px;
                    font-size:12px;font-weight:700;letter-spacing:0.02em;">
                    Try <code style="color:{'#9EF04D' if _hero_text_dark else '#2E590E'};background:transparent;font-weight:800;">INFY.NS</code>
                </span>
                <span style="background:transparent;border:1px dashed {'#3a3a3a' if _hero_text_dark else '#c8ccd1'};
                    color:{'#8a8a8a' if _hero_text_dark else '#656d76'};padding:6px 14px;border-radius:999px;
                    font-size:12px;font-weight:500;">
                    …or paste any NSE / BSE ticker
                </span>
            </div>

            <div style="color:{'#8a8a8a' if _hero_text_dark else '#656d76'};font-size:11px;
                letter-spacing:0.08em;text-transform:uppercase;font-weight:600;
                margin-bottom:0.5rem;">
                What you'll get
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Feature cards — use st.columns so Streamlit handles responsive layout
        # instead of relying on CSS grid inside a markdown block (which can
        # collapse to a single column in light theme / certain viewports).
        _feat_card_bg = "#1a1a1a" if _hero_text_dark else "#f6f8fa"
        _feat_card_border = "#2a2a2a" if _hero_text_dark else "#d8dee4"
        _feat_title_color = "#ffffff" if _hero_text_dark else "#1f2328"
        _feat_body_color = "#a0a0a0" if _hero_text_dark else "#57606a"

        def _feat_card(icon_cls: str, title: str, body: str) -> str:
            """icon_cls is a Boxicons class name, e.g. 'bx-line-chart'."""
            return (
                f'<div style="background:{_feat_card_bg};border:1px solid {_feat_card_border};'
                f'border-radius:10px;padding:16px 18px;height:100%;">'
                f'<div style="color:{_feat_title_color};font-weight:700;font-size:13px;'
                f'margin-bottom:6px;">'
                f'<i class="bx {icon_cls}" style="color:#74e504;margin-right:8px;'
                f'vertical-align:-2px;font-size:1.1em;"></i>{title}</div>'
                f'<div style="color:{_feat_body_color};font-size:12.5px;line-height:1.55;">'
                f'{body}</div></div>'
            )

        _f1, _f2, _f3, _f4 = st.columns(4)
        _f1.markdown(
            _feat_card(
                "bx-line-chart", "Live Market Data",
                "Price, 52W range, volume, beta, market cap, and holdings breakdown.",
            ),
            unsafe_allow_html=True,
        )
        _f2.markdown(
            _feat_card(
                "bxs-dollar-circle", "Deep Financials",
                "Income statement, balance sheet, cash flow, valuation ratios, margins.",
            ),
            unsafe_allow_html=True,
        )
        _f3.markdown(
            _feat_card(
                "bx-target-lock", "SWOT &amp; News",
                "AI-summarised strengths / risks plus latest headlines from top sources.",
            ),
            unsafe_allow_html=True,
        )
        _f4.markdown(
            _feat_card(
                "bx-bulb", "Expert Outlook",
                "LLM-generated thesis, forward sentiment, and quarterly-report highlights.",
            ),
            unsafe_allow_html=True,
        )


elif view_option == "📅 5-Year Analysis":
    # Enhanced multi-source fundamental dashboard:
    #   • 5-year P&L / balance-sheet / shareholding trends from screener.in
    #   • Director / promoter background (Tavily + LLM extraction)
    #   • Political-link flags (best-effort — no public ECI API)
    #   • Company + director news with LLM-tagged sentiment
    #   • Legal / SEBI / SFIO mentions (best-effort — no public eCourts feed)
    #   • Promoter cross-holdings + portfolio-company performance (yfinance)
    #   • Quarterly promoter-pledge trend with risk badge
    #
    # Implementation lives in utils/fundamental_analyzer.py (data layer,
    # parallel fan-out across 8 sub-fetchers) and utils/fundamental_renderer.py
    # (Streamlit + plotly rendering). Persistence: stock_fundamentals
    # JSONB table from Alembic 0004 with a 24h TTL.
    bx_header("5-Year Analysis", "bx-calendar")
    st.markdown(
        "Multi-source fundamental dashboard: **5Y financials · directors · "
        "political · news · legal · investments · pledge**. Best-effort for "
        "items without public APIs."
    )

    _stock_symbol = None
    _stock_name = None
    if hasattr(st.session_state, "deps") and st.session_state.deps:
        _stock_symbol = getattr(st.session_state.deps, "stock_symbol", None)
        _stock_name = getattr(st.session_state.deps, "stock_name", None)
    if not _stock_symbol:
        _stock_symbol = st.session_state.get("current_stock")

    if not _stock_symbol:
        st.info(
            "🔎 Load a stock from **📈 Data Dashboard** first (search a "
            "symbol or company name), then come back to this view."
        )
    else:
        # The 5-Year Analysis runs automatically in the background after
        # the Trade Ideas scrape finishes (see `utils/background_tasks.py`
        # — `_run_trade_ideas` chains into `_run_fundamentals` so both
        # heavy bg tasks run sequentially per stock). The manual "Run /
        # Refresh" button stays as an explicit override / retry.
        from utils.background_tasks import bg_status as _bg_status
        _fund_state_key = f"_fund_analysis::{_stock_symbol}"
        _fund_bg = _bg_status("fundamentals", _stock_symbol)

        col_a, col_b = st.columns([4, 1])
        with col_a:
            st.markdown(f"#### {_stock_name or _stock_symbol}  \n`{_stock_symbol}`")
        with col_b:
            _refresh = st.button(
                "🔬 Run / Refresh",
                key=f"fund_run_{_stock_symbol}",
                use_container_width=True,
                type="primary",
                help=(
                    "Force a fresh fetch even when a recent snapshot or "
                    "background run exists. Otherwise the FA runs "
                    "automatically after Trade Ideas finishes."
                ),
            )

        if _refresh:
            # Explicit refresh: drop the cached result + reset bg status
            # so a fresh run can start. The button click itself will then
            # trigger the inline `analyze_fundamentals` call below.
            st.session_state.pop(_fund_state_key, None)
            try:
                from utils.background_tasks import reset_bg_status_for_symbol
                reset_bg_status_for_symbol(_stock_symbol)
            except Exception:
                pass

        _cached_fa = st.session_state.get(_fund_state_key)

        # DB-cache-only peek — instant when a recent snapshot exists,
        # never triggers a fresh Tavily/LLM fetch. Always runs unless the
        # user explicitly clicked Refresh (so we don't hit the DB after
        # they asked for a fresh run).
        if _cached_fa is None and not _refresh:
            try:
                from utils.fundamental_analyzer import load_cached_fundamentals
                _cached_fa = load_cached_fundamentals(_stock_symbol, max_age_hours=24)
                if _cached_fa is not None:
                    st.session_state[_fund_state_key] = _cached_fa
            except Exception:
                _cached_fa = None

        if _cached_fa is None and _refresh:
            # Manual refresh: run inline (foreground) so the user sees the
            # spinner while they wait. The analyzer streams its detailed
            # timestamped progress to stdout (visible in the Streamlit
            # server console).
            from utils.fundamental_analyzer import analyze_fundamentals
            with st.spinner(
                "Running 5-Year Analysis (~60–90s on first run — 8 sections "
                "fan out in parallel; cached for 24h afterwards so repeat "
                "visits render instantly)..."
            ):
                try:
                    _cached_fa = analyze_fundamentals(
                        _stock_symbol, _stock_name, force_refresh=True,
                    )
                    st.session_state[_fund_state_key] = _cached_fa
                except Exception as _exc:
                    st.error(f"❌ Analysis failed: {_exc}")
                    _cached_fa = None

        # ── No result yet — surface the background task's progress ──
        if _cached_fa is None:
            if _fund_bg == "running":
                # Background pipeline is in flight (chained from Trade
                # Ideas). Auto-refresh every few seconds so the section
                # populates as soon as the bg task finishes — the user
                # doesn't have to touch the page.
                try:
                    from streamlit_autorefresh import st_autorefresh
                    st_autorefresh(
                        interval=5000,
                        key=f"fa_autorefresh_{_stock_symbol}",
                        limit=60,  # 5 min × 12 = enough for a 90s+50s chain
                    )
                except Exception:
                    pass
                st.info(
                    "⏳ **5-Year Analysis is running in the background** "
                    "(launched automatically after Trade Ideas). This page "
                    "auto-refreshes every 5 seconds and will populate as "
                    "soon as the run completes — usually 60–90 seconds. "
                    "Click 🔬 Run / Refresh above to force a fresh run "
                    "instead."
                )
            elif _fund_bg == "error":
                _err = st.session_state.get(
                    f"_bg_fundamentals_error_{_stock_symbol}", "unknown error"
                )
                st.error(
                    f"❌ Background analysis failed: {_err}\n\n"
                    "Click 🔬 Run / Refresh above to retry."
                )
            else:
                # "not_started" — either the user hasn't loaded a stock
                # in Data Dashboard yet, or the bg chain hasn't reached
                # this stock. The Run / Refresh button is the manual path.
                st.info(
                    "Load a stock from **📈 Data Dashboard** to start the "
                    "Trade Ideas + 5-Year Analysis background chain. "
                    "Already loaded? Click **🔬 Run / Refresh** above to "
                    "run the analysis now."
                )
        else:
            from utils.fundamental_renderer import render_fundamental_analysis
            render_fundamental_analysis(_cached_fa)

elif view_option == "⚡ Bulk Stock Analyzer":
    # Bulk Stock Analyzer - Full-featured version matching bulk_stock_dashboard.py
    bx_header("Bulk Stock Analyzer", "bx-search-alt-2", level=3)
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
        bx_header("Summary", "bx-line-chart", level=2)
        
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
        
        """)

        st.markdown("""
        <ul style='list-style:none;padding-left:0;margin:0;'>
          <li style='margin:4px 0;'><i class='bx bxs-check-circle' style='color:#22c55e;margin-right:8px;vertical-align:-2px;'></i>Concurrent processing for fast results</li>
          <li style='margin:4px 0;'><i class='bx bxs-check-circle' style='color:#22c55e;margin-right:8px;vertical-align:-2px;'></i>Automatic retry on failures</li>
          <li style='margin:4px 0;'><i class='bx bxs-check-circle' style='color:#22c55e;margin-right:8px;vertical-align:-2px;'></i>Detailed visualizations</li>
          <li style='margin:4px 0;'><i class='bx bxs-check-circle' style='color:#22c55e;margin-right:8px;vertical-align:-2px;'></i>Export to CSV/JSON</li>
          <li style='margin:4px 0;'><i class='bx bxs-check-circle' style='color:#22c55e;margin-right:8px;vertical-align:-2px;'></i>Individual stock charts</li>
        </ul>
        """, unsafe_allow_html=True)

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
            "Stock Symbol", value="JIO",
            help="e.g. JIO, RELIANCE, TCS  (exchange suffix added automatically)"
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

    # Drawing API URL is fixed; not exposed in the UI.
    api_url = "http://localhost:8000"

    st.markdown("---")
    # ── What to generate ─────────────────────────────────────────────────────
    bx_header("Select Analysis Tasks", "bx-list-ul", level=4)
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
                        bx_header("Generation Statistics", "bx-stats", level=4)
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
                        <i class='bx bxs-check-circle' style='vertical-align:-2px;margin-right:4px;'></i>Copied!
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
    bx_header("System Information", "bx-cog")
    st.info("**Pydantic AI Agent**: Using Google Gemini with 4-key rotation")
    st.info("**Tools**: Stock validation, Q&A, scenario analysis, summaries")
    st.info("**Data Sources**: Yahoo Finance + Tavily web search (screener.in only)")

# Footer
st.markdown("""
<div style="text-align: center; color: #94a3b8; padding: 0.25rem 0; margin: 0; font-size: 0.8rem; border-top: 1px solid #333;">
    <strong>Stock Analysis</strong> | AI-Powered Investment Insights
</div>
""", unsafe_allow_html=True)
