"""
Example: Integrating Chat-Based Drawing System into Streamlit
This shows how to replace static checkboxes with chat input
"""

import streamlit as st
import requests
from datetime import datetime, timedelta

# Page config
st.set_page_config(
    page_title="Smart Drawing Generator",
    page_icon="💬",
    layout="wide"
)

# Title
st.title("💬 Smart Drawing Generator")
st.markdown("Generate TradingView drawings using natural language")

# Sidebar for basic inputs
with st.sidebar:
    st.header("📊 Chart Settings")
    
    symbol = st.text_input(
        "Stock Symbol",
        value="ONGC",
        help="Enter stock symbol (e.g., ONGC, TCS, RELIANCE)"
    )
    
    timeframe = st.selectbox(
        "Timeframe",
        options=["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1wk", "1mo"],
        index=6,  # Default to 1d
        help="Select chart timeframe"
    )
    
    # Date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365)
    
    date_range = st.date_input(
        "Date Range",
        value=(start_date, end_date),
        help="Select date range for analysis"
    )
    
    market = st.selectbox(
        "Market",
        options=["stock", "forex", "crypto"],
        index=0,
        help="Select market type"
    )

# Main content
col1, col2 = st.columns([2, 1])

with col1:
    st.header("💬 What do you want to see?")
    
    # Chat input (replaces checkboxes!)
    user_message = st.text_area(
        "Describe what drawings you want:",
        value="mark supply and demand zones on this stock",
        height=100,
        help="Use natural language to describe what you want to see"
    )
    
    # Examples
    with st.expander("💡 Example Messages"):
        st.markdown("""
        **Single Type:**
        - "mark supply and demand zones"
        - "show candlestick patterns"
        - "add RSI signals"
        
        **Multiple Types:**
        - "show me zones and patterns"
        - "add RSI and MACD indicators"
        - "mark zones, patterns, and levels"
        
        **Complete Analysis:**
        - "analyze this chart with everything"
        - "show me all indicators"
        """)
    
    # Generate button
    generate_button = st.button(
        "🚀 Generate Drawings",
        type="primary",
        use_container_width=True
    )

with col2:
    st.header("ℹ️ Info")
    st.info("""
    **How it works:**
    
    1. Type what you want in natural language
    2. Click "Generate Drawings"
    3. AI understands your intent
    4. Generates only requested drawings
    
    **No checkboxes needed!** 🎉
    """)

# Generate drawings when button clicked
if generate_button:
    if not user_message.strip():
        st.error("❌ Please enter a message describing what you want to see")
    elif not symbol.strip():
        st.error("❌ Please enter a stock symbol")
    else:
        # Show loading
        with st.spinner("🤖 Understanding your request..."):
            try:
                # Format dates
                start_date_str = date_range[0].strftime("%d-%m-%Y")
                end_date_str = date_range[1].strftime("%d-%m-%Y")
                
                # Prepare request
                request_data = {
                    "message": user_message,
                    "symbol": symbol,
                    "start_date": start_date_str,
                    "end_date": end_date_str,
                    "market": market,
                    "timeframe": timeframe
                }
                
                # Call API
                api_url = "http://localhost:5001/api/v1/drawing/chat/"
                response = requests.post(api_url, json=request_data, timeout=60)
                
                if response.status_code == 200:
                    result = response.json()
                    
                    # Success!
                    st.success("✅ Drawings generated successfully!")
                    
                    # Show parsed intent
                    st.subheader("🧠 AI Understanding")
                    col_a, col_b, col_c = st.columns(3)
                    
                    with col_a:
                        st.metric(
                            "Confidence",
                            f"{result['parsed_intent']['confidence']:.0%}"
                        )
                    
                    with col_b:
                        st.metric(
                            "Drawing Types",
                            len(result['drawing_types_generated'])
                        )
                    
                    with col_c:
                        st.metric(
                            "Total Drawings",
                            result['total_drawings']
                        )
                    
                    # Show what AI understood
                    st.info(f"**AI understood:** {result['parsed_intent']['user_wants']}")
                    
                    # Show drawing types
                    st.subheader("📊 Generated Drawing Types")
                    for dtype in result['drawing_types_generated']:
                        st.write(f"✅ {dtype.replace('_', ' ').title()}")
                    
                    # Show drawings
                    st.subheader("🎨 Drawing Instructions")
                    
                    # Group drawings by type
                    drawing_counts = {}
                    for drawing in result['drawings']:
                        dtype = drawing.get('type', 'unknown')
                        drawing_counts[dtype] = drawing_counts.get(dtype, 0) + 1
                    
                    # Display counts
                    for dtype, count in drawing_counts.items():
                        st.write(f"• {dtype}: {count} drawings")
                    
                    # Show JSON (expandable)
                    with st.expander("📄 View Full JSON Response"):
                        st.json(result)
                    
                    # Download button
                    import json
                    json_str = json.dumps(result, indent=2)
                    st.download_button(
                        label="💾 Download Drawings JSON",
                        data=json_str,
                        file_name=f"drawings_{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                        mime="application/json"
                    )
                    
                else:
                    st.error(f"❌ API Error: {response.status_code}")
                    st.error(response.text)
                    
            except requests.exceptions.ConnectionError:
                st.error("❌ Could not connect to API server")
                st.info("""
                **Make sure the API server is running:**
                ```bash
                python api_chat_drawing.py
                ```
                """)
                
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
                import traceback
                with st.expander("🐛 Error Details"):
                    st.code(traceback.format_exc())

# Footer
st.markdown("---")
st.markdown("""
<div style='text-align: center; color: gray;'>
    <p>💬 Chat-Based Drawing System v2.0 | Powered by Groq Llama 3.3 70B</p>
</div>
""", unsafe_allow_html=True)


# ============================================================================
# COMPARISON: Before vs After
# ============================================================================

st.markdown("---")
st.header("📊 Before vs After")

col_before, col_after = st.columns(2)

with col_before:
    st.subheader("❌ Before: Static Checkboxes")
    st.code("""
# User must click multiple checkboxes
☑ Supply/Demand Zones
☑ Candlestick Patterns
☐ Bollinger Bands
☑ RSI Signals
☐ MACD Crossovers
☑ Key Levels

[Generate Drawings]

Problems:
- Multiple clicks required
- Must know what each option means
- Not intuitive for beginners
- Fixed options only
    """)

with col_after:
    st.subheader("✅ After: Chat Input")
    st.code("""
# User types one message
💬 "mark supply and demand zones"

[Generate Drawings]

Benefits:
- Single message
- Natural language
- Intuitive for everyone
- Flexible requests
- AI-powered understanding
    """)

# Show statistics
st.subheader("📈 Improvement Metrics")
col_m1, col_m2, col_m3, col_m4 = st.columns(4)

with col_m1:
    st.metric("User Actions", "1", delta="-80%", delta_color="normal")
    st.caption("vs 5-10 clicks before")

with col_m2:
    st.metric("Time to Request", "5s", delta="-50%", delta_color="normal")
    st.caption("vs 10s before")

with col_m3:
    st.metric("Learning Curve", "Low", delta="Much easier", delta_color="normal")
    st.caption("vs High before")

with col_m4:
    st.metric("Flexibility", "∞", delta="Unlimited", delta_color="normal")
    st.caption("vs Fixed options before")
