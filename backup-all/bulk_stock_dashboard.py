"""
Streamlit Dashboard for Bulk Stock Selection
Visualizes stocks that have fallen 25%+ from their 52-week high
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from bulk_stock_selector import BulkStockSelector, SAMPLE_INDIAN_STOCKS
import json
from datetime import datetime
import yfinance as yf


# Page configuration
st.set_page_config(
    page_title="Bulk Stock Selector",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        text-align: center;
        padding: 1rem 0;
    }
    
    .metric-card {
        background: white;
        padding: 1.5rem;
        border-radius: 1rem;
        border-left: 4px solid #667eea;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        margin: 0.5rem 0;
    }
    
    .selected-badge {
        background: #10b981;
        color: white;
        padding: 0.25rem 0.75rem;
        border-radius: 1rem;
        font-size: 0.875rem;
        font-weight: 600;
    }
    
    .not-selected-badge {
        background: #ef4444;
        color: white;
        padding: 0.25rem 0.75rem;
        border-radius: 1rem;
        font-size: 0.875rem;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'results' not in st.session_state:
    st.session_state.results = None
if 'processing' not in st.session_state:
    st.session_state.processing = False
if 'stock_list' not in st.session_state:
    st.session_state.stock_list = SAMPLE_INDIAN_STOCKS


def load_stock_price_chart(symbol: str):
    """Load and display price chart for a stock"""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1y")
        
        if hist.empty:
            st.warning(f"No data available for {symbol}")
            return
        
        # Create candlestick chart
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


# Header
st.markdown('<h1 class="main-header">📊 Bulk Stock Selector Dashboard</h1>', unsafe_allow_html=True)
st.markdown("### Find stocks that have fallen ≥25% from their 52-week high")

# Sidebar
with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/000000/stock-share.png", width=80)
    st.title("Configuration")
    st.markdown("---")
    
    # Stock list input
    st.subheader("📝 Stock List")
    
    input_method = st.radio(
        "Input Method",
        ["Use Sample List", "Upload File", "Manual Entry"],
        help="Choose how to provide stock symbols"
    )
    
    if input_method == "Use Sample List":
        st.info(f"Using {len(SAMPLE_INDIAN_STOCKS)} sample stocks")
        st.session_state.stock_list = SAMPLE_INDIAN_STOCKS
        
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
            # Ticker symbols end with .NS or .BO
            ticker_symbols = [line for line in lines if line.endswith('.NS') or line.endswith('.BO')]
            company_names = [line for line in lines if not (line.endswith('.NS') or line.endswith('.BO'))]
            
            if company_names:
                # File contains company names - need to resolve
                st.info(f"📋 Detected {len(company_names)} company names and {len(ticker_symbols)} ticker symbols")
                
                if st.button("🔍 Resolve Company Names to Ticker Symbols", key="resolve_btn"):
                    with st.spinner(f"Resolving {len(company_names)} company names... This may take a few minutes."):
                        from stock_symbol_resolver import StockSymbolResolver
                        
                        resolver = StockSymbolResolver()
                        results = resolver.resolve_list(company_names)
                        
                        # Combine resolved symbols with existing ticker symbols
                        all_symbols = ticker_symbols + results['resolved_symbols']
                        st.session_state.stock_list = all_symbols
                        
                        # Show results
                        st.success(f"✅ Resolved {results['resolved']}/{results['total']} company names")
                        st.metric("Success Rate", f"{results['success_rate']:.1f}%")
                        
                        col1, col2 = st.columns(2)
                        with col1:
                            st.metric("Total Symbols", len(all_symbols))
                        with col2:
                            st.metric("Failed", results['failed'])
                        
                        if results['failed_names']:
                            with st.expander(f"❌ Failed to resolve {len(results['failed_names'])} names"):
                                for name in results['failed_names']:
                                    st.write(f"- {name}")
                        
                        # Show resolved details
                        with st.expander("📊 Resolution Details"):
                            for detail in results['results_detail']:
                                if detail['success']:
                                    st.write(f"✅ {detail['original_name']} → {detail['symbol']}")
                                else:
                                    st.write(f"❌ {detail['original_name']} → Not found")
            else:
                # All ticker symbols
                st.session_state.stock_list = ticker_symbols
                
                # Validate ticker symbols
                invalid_symbols = [s for s in ticker_symbols if not (s.endswith('.NS') or s.endswith('.BO'))]
                valid_symbols = [s for s in ticker_symbols if s.endswith('.NS') or s.endswith('.BO')]
                
                if invalid_symbols:
                    st.error(f"❌ Found {len(invalid_symbols)} invalid symbols")
                    st.warning(f"✅ Found {len(valid_symbols)} valid symbols")
                    
                    with st.expander("Show invalid symbols (first 20)"):
                        st.write(invalid_symbols[:20])
                    
                    if st.checkbox("Use only valid symbols"):
                        st.session_state.stock_list = valid_symbols
                        st.success(f"Using {len(valid_symbols)} valid symbols")
                else:
                    st.success(f"✅ Loaded {len(ticker_symbols)} valid ticker symbols")
    
    else:  # Manual Entry
        manual_input = st.text_area(
            "Enter stock symbols (one per line)",
            value="\n".join(SAMPLE_INDIAN_STOCKS[:10]),
            height=200,
            help="Enter ticker symbols like RELIANCE.NS, TCS.NS (not company names)"
        )
        if manual_input:
            stocks = [line.strip() for line in manual_input.split('\n') if line.strip()]
            st.session_state.stock_list = stocks
            
            # Validate stock symbols
            invalid_symbols = [s for s in stocks if not (s.endswith('.NS') or s.endswith('.BO'))]
            if invalid_symbols:
                st.warning(f"⚠️ {len(invalid_symbols)} symbols may be invalid (should end with .NS or .BO)")
                with st.expander("Show invalid symbols"):
                    st.write(invalid_symbols[:10])  # Show first 10
    
    st.markdown("---")
    
    # Processing settings
    st.subheader("⚙️ Settings")
    max_workers = st.slider("Concurrent Workers", 5, 20, 10)
    timeout = st.slider("Timeout (seconds)", 5, 30, 15)
    
    st.markdown("---")
    
    # Process button
    if st.button("🚀 Process Stocks", type="primary", width='stretch'):
        st.session_state.processing = True
        st.rerun()
    
    # Clear results
    if st.session_state.results and st.button("🔄 Clear Results", width='stretch'):
        st.session_state.results = None
        st.rerun()

# Main content
if st.session_state.processing:
    st.session_state.processing = False
    
    with st.spinner(f"Processing {len(st.session_state.stock_list)} stocks..."):
        processor = BulkStockSelector(max_workers=max_workers, timeout=timeout)
        results = processor.process_bulk_stocks(st.session_state.stock_list)
        st.session_state.results = results
    
    st.success("✅ Processing complete!")
    st.rerun()

# Display results
if st.session_state.results:
    results = st.session_state.results
    
    # Summary metrics
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
                    
                    # Load price chart - use index to ensure unique keys
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
                    # Only one category exists
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
                    # Both categories exist
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
    st.info("👈 Configure settings in the sidebar and click 'Process Stocks' to begin")
    
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

# Footer
st.markdown("---")
st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Data source: Yahoo Finance")
