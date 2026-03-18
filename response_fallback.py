#!/usr/bin/env python3
"""
Response Fallback Utility

This module provides functions to retrieve cached analysis responses from the database
when the agent gets stuck or fails to display responses properly.

Usage in Streamlit app:
1. When agent.run() completes but response is not displayed
2. When agent gets stuck in retry loops
3. When user sees "returning cached analysis" but no display
"""

import streamlit as st
from database_utility.database import StockDatabase
from datetime import datetime
import uuid

def get_cached_analysis_response(stock_symbol=None):
    """
    Retrieve cached analysis response from database when agent gets stuck.
    
    Args:
        stock_symbol: Optional stock symbol to retrieve specific analysis
        
    Returns:
        tuple: (success, response_text, stock_info)
    """
    try:
        db = StockDatabase()
        if not db.connect():
            return False, "Could not connect to database", None
        
        # Get analysis (latest if no symbol specified)
        if stock_symbol:
            analysis = db.get_latest_analysis(stock_symbol)
        else:
            analysis = db.get_latest_analysis()
        
        if not analysis:
            db.disconnect()
            return False, "No cached analysis found", None
        
        analyzed_response = analysis.get('analyzed_response', '')
        if not analyzed_response or len(analyzed_response) < 500:
            db.disconnect()
            return False, "Cached response is too short or empty", None
        
        stock_info = {
            'name': analysis.get('stock_name'),
            'symbol': analysis.get('stock_symbol'),
            'timestamp': analysis.get('created_at'),
            'id': analysis.get('id')
        }
        
        db.disconnect()
        return True, analyzed_response, stock_info
        
    except Exception as e:
        return False, f"Error retrieving cached analysis: {e}", None

def display_cached_response_in_streamlit(stock_symbol=None):
    """
    Function to be used in streamlit app when agent response gets stuck.
    Call this when agent.run() completes but response is not displayed.
    
    Args:
        stock_symbol: Optional stock symbol to retrieve specific analysis
        
    Returns:
        bool: True if response was successfully displayed, False otherwise
    """
    success, response, stock_info = get_cached_analysis_response(stock_symbol)
    
    if success:
        print(f"✅ Retrieved cached response for {stock_info['name']} ({stock_info['symbol']})")
        print(f"📊 Response length: {len(response)} characters")
        
        # Update session state
        st.session_state.messages.append({
            "role": "assistant", 
            "content": response
        })
        
        # Update current stock info
        st.session_state.current_stock = stock_info['name']
        
        # Update deps if available
        if hasattr(st.session_state, 'deps'):
            st.session_state.deps.stock_name = stock_info['name']
            st.session_state.deps.stock_symbol = stock_info['symbol']
            st.session_state.deps.analysis_complete = True
        
        # Show success message
        st.success(f"✅ Displayed cached analysis for {stock_info['name']}")
        
        # Force rerun to display
        st.rerun()
        
        return True
    else:
        print(f"❌ Could not retrieve cached response: {response}")
        st.error(f"❌ Could not retrieve cached response: {response}")
        return False

def save_response_with_unique_id(stock_symbol, stock_name, response_text):
    """
    Save response with unique ID for easy retrieval.
    
    Args:
        stock_symbol: Stock symbol (e.g., "TCS.NS")
        stock_name: Company name (e.g., "Tata Consultancy Services Limited")
        response_text: The formatted analysis response
        
    Returns:
        str: Unique ID for this response, or None if failed
    """
    try:
        # Generate unique ID
        unique_id = str(uuid.uuid4())[:8]  # Short 8-character ID
        
        db = StockDatabase()
        if not db.connect():
            return None
        
        # Save with unique ID (you may need to modify database schema to add unique_id field)
        # For now, we'll use the existing save_analysis method
        # In a future update, add unique_id field to the database
        
        success = db.save_analysis(
            stock_name=stock_name,
            stock_symbol=stock_symbol,
            analyzed_response=response_text,
            tech_analysis=None,  # Will be updated separately
            selection=None,      # Will be calculated separately
            market_senti=None,   # Will be updated when sentiment is analyzed
            current_market_senti_status=None,
            future_senti=None,
            future_senti_status=None
        )
        
        db.disconnect()
        
        if success:
            print(f"✅ Response saved with ID: {unique_id}")
            return unique_id
        else:
            print("❌ Failed to save response")
            return None
            
    except Exception as e:
        print(f"❌ Error saving response: {e}")
        return None

def get_response_by_id(response_id):
    """
    Retrieve response by unique ID (future feature).
    
    Args:
        response_id: Unique ID of the response
        
    Returns:
        tuple: (success, response_text, stock_info)
    """
    # This is a placeholder for future implementation
    # Would require adding unique_id field to database schema
    return False, "Feature not implemented yet", None

def check_agent_stuck_and_fallback():
    """
    Check if agent is stuck in retry loops and provide fallback.
    Call this function when you see repeated "returning cached analysis" messages.
    
    Returns:
        bool: True if fallback was successful, False otherwise
    """
    print("🔍 Checking for stuck agent and attempting fallback...")
    
    # Check if we have deps with analysis_complete flag
    if hasattr(st.session_state, 'deps') and hasattr(st.session_state.deps, 'analysis_complete'):
        if st.session_state.deps.analysis_complete:
            print("✅ Analysis marked as complete, attempting to display cached response")
            
            # Try to get the stock symbol from deps
            stock_symbol = getattr(st.session_state.deps, 'stock_symbol', None)
            
            return display_cached_response_in_streamlit(stock_symbol)
    
    # If no deps info, try to get latest analysis
    print("⚠️ No analysis completion info, trying latest cached response")
    return display_cached_response_in_streamlit()

def create_streamlit_fallback_button():
    """
    Create a Streamlit button that users can click when responses get stuck.
    Add this to your Streamlit sidebar or main area.
    """
    if st.button("🔄 Display Cached Response", help="Click if analysis completed but not displayed"):
        success = check_agent_stuck_and_fallback()
        if not success:
            st.error("❌ No cached response available. Please try analyzing a stock first.")

def monitor_response_display():
    """
    Monitor function to detect when responses are not being displayed.
    This can be called periodically or after agent.run() calls.
    
    Returns:
        dict: Status information about response display
    """
    status = {
        'has_deps': hasattr(st.session_state, 'deps'),
        'analysis_complete': False,
        'has_cached_response': False,
        'messages_count': len(st.session_state.get('messages', [])),
        'current_stock': st.session_state.get('current_stock'),
        'recommendation': 'none'
    }
    
    if status['has_deps']:
        deps = st.session_state.deps
        status['analysis_complete'] = getattr(deps, 'analysis_complete', False)
        status['has_cached_response'] = hasattr(deps, 'last_analysis_response') and deps.last_analysis_response
        
        # Determine recommendation
        if status['analysis_complete'] and not status['current_stock']:
            status['recommendation'] = 'display_cached'
        elif status['has_cached_response'] and status['messages_count'] == 0:
            status['recommendation'] = 'display_cached'
    
    return status

# Example usage in Streamlit app:
"""
# Add this to your Streamlit app where agent.run() is called:

# After agent.run() completes:
if result and not error_msg:
    # Normal processing...
    pass
else:
    # Check if we can use cached response
    from response_fallback import check_agent_stuck_and_fallback
    
    if not check_agent_stuck_and_fallback():
        # Show error message as fallback
        st.error("Analysis failed and no cached response available")

# Add this button to sidebar for manual fallback:
from response_fallback import create_streamlit_fallback_button
create_streamlit_fallback_button()

# Monitor response display status:
from response_fallback import monitor_response_display
status = monitor_response_display()
if status['recommendation'] == 'display_cached':
    st.info("💡 Analysis completed but not displayed. Click 'Display Cached Response' button.")
"""