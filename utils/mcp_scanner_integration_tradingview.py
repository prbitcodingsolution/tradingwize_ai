"""
MCP Scanner Integration for Streamlit - TradingView API Format
Connects MCP Scanner Agent with Technical Scanner UI
Returns exact TradingView drawing JSON format
"""

import asyncio
import json
from typing import Dict, Any, Optional, List
from datetime import datetime

# Import the TradingView-format MCP Scanner Agent
try:
    from mcp_scanner_agent_tradingview import (
        run_mcp_scanner_tradingview,
        ScannerDrawingOutput,
        TradingViewDrawingTranslator,
        save_drawings_tradingview,
        get_latest_drawings_tradingview
    )
    MCP_SCANNER_AVAILABLE = True
except ImportError:
    MCP_SCANNER_AVAILABLE = False
    print("⚠️ MCP Scanner Agent (TradingView format) not available")


class MCPScannerIntegrationTradingView:
    """Integration layer for TradingView-format drawings"""
    
    def __init__(self):
        self.cache = {}
        self.last_scan_time = {}
    
    async def scan_with_mcp_tradingview(
        self,
        query: str,
        symbols: List[str],
        timeframe: str = "1D",
        max_results: int = 5
    ) -> Dict[str, Any]:
        """
        Run MCP scanner and return TradingView-format drawings
        
        Returns:
            {
                "success": True,
                "results": [
                    {
                        "symbol": "AAPL",
                        "drawings": [
                            {
                                "id": "6VgiHl",
                                "type": "LineToolRiskRewardLong",
                                "state": {...},
                                "points": [...],
                                ...
                            }
                        ]
                    }
                ]
            }
        """
        
        if not MCP_SCANNER_AVAILABLE:
            return {
                "success": False,
                "error": "MCP Scanner not available",
                "results": []
            }
        
        results = []
        
        for symbol in symbols[:max_results]:
            try:
                # Run scanner for this symbol
                drawing_output = await run_mcp_scanner_tradingview(
                    query=query,
                    symbol=symbol,
                    timeframe=timeframe
                )
                
                # Save to cache
                save_drawings_tradingview(symbol, drawing_output)
                
                # Store in memory cache
                self.cache[symbol] = drawing_output
                self.last_scan_time[symbol] = datetime.now()
                
                results.append({
                    "symbol": symbol,
                    "success": True,
                    "drawings": drawing_output.drawings,
                    "metadata": drawing_output.metadata,
                    "timestamp": datetime.now().isoformat()
                })
                
            except Exception as e:
                results.append({
                    "symbol": symbol,
                    "success": False,
                    "error": str(e)
                })
        
        return {
            "success": True,
            "query": query,
            "timeframe": timeframe,
            "results": results,
            "total_scanned": len(symbols),
            "total_results": len([r for r in results if r.get("success")])
        }
    
    def get_drawings_for_symbol_tradingview(self, symbol: str) -> Optional[List[Dict[str, Any]]]:
        """Get TradingView-format drawings for a symbol"""
        
        # Try memory cache first
        if symbol in self.cache:
            return [d.model_dump() for d in self.cache[symbol].drawings]
        
        # Try file cache
        cached = get_latest_drawings_tradingview(symbol)
        if cached and "drawings" in cached:
            return cached["drawings"]
        
        return None
    
    def get_drawing_json_for_frontend(self, symbol: str) -> str:
        """
        Get TradingView drawing JSON for frontend
        
        Returns exact TradingView API format
        """
        drawings = self.get_drawings_for_symbol_tradingview(symbol)
        
        if drawings:
            return json.dumps(drawings, indent=2)
        
        return json.dumps([])


# ============================================================================
# Streamlit Helper Functions
# ============================================================================

def run_scanner_tradingview_sync(
    query: str,
    symbols: List[str],
    timeframe: str = "1D",
    max_results: int = 5
) -> Dict[str, Any]:
    """
    Synchronous wrapper for Streamlit - Returns TradingView format
    
    Use this in Streamlit app:
    result = run_scanner_tradingview_sync("Find Bollinger squeeze", ["AAPL", "MSFT"])
    """
    
    integration = MCPScannerIntegrationTradingView()
    
    # Run async function in sync context
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        result = loop.run_until_complete(
            integration.scan_with_mcp_tradingview(query, symbols, timeframe, max_results)
        )
        return result
    finally:
        loop.close()


def get_tradingview_drawing_endpoint(symbol: str) -> str:
    """
    Get TradingView drawing JSON for a specific symbol
    
    This is what Next.js frontend will call:
    GET /api/drawings/tradingview?symbol=AAPL
    
    Returns array of TradingView drawing objects
    """
    integration = MCPScannerIntegrationTradingView()
    return integration.get_drawing_json_for_frontend(symbol)


# ============================================================================
# Example Integration with Streamlit
# ============================================================================

def streamlit_tradingview_scanner_example():
    """
    Example of how to integrate TradingView-format scanner with Streamlit
    
    Add this to app_advanced.py in the Technical Scanner section
    """
    
    import streamlit as st
    
    st.markdown("### 📊 MCP Technical Scanner (TradingView Format)")
    
    # Scanner inputs
    col1, col2 = st.columns([3, 1])
    
    with col1:
        query = st.text_input(
            "Scanner Query",
            value="Find stocks with Bollinger Band squeeze",
            help="Describe the technical pattern you're looking for"
        )
    
    with col2:
        timeframe = st.selectbox(
            "Timeframe",
            options=["1m", "5m", "15m", "1h", "4h", "1D", "1W"],
            index=5
        )
    
    # Stock selection
    symbols = st.multiselect(
        "Symbols to Scan",
        options=["AAPL", "MSFT", "GOOGL", "TSLA", "NVDA", "TCS.NS", "RELIANCE.NS"],
        default=["AAPL", "MSFT", "GOOGL"]
    )
    
    # Scan button
    if st.button("🔍 Scan with MCP Agent (TradingView Format)", type="primary"):
        with st.spinner("🤖 MCP Agent analyzing..."):
            
            # Run scanner
            result = run_scanner_tradingview_sync(
                query=query,
                symbols=symbols,
                timeframe=timeframe,
                max_results=len(symbols)
            )
            
            if result.get("success"):
                st.success(f"✅ Scanned {result['total_scanned']} symbols, found {result['total_results']} setups")
                
                # Display results
                for scan_result in result["results"]:
                    if scan_result.get("success"):
                        symbol = scan_result["symbol"]
                        drawings = scan_result["drawings"]
                        
                        with st.expander(f"📈 {symbol} - {len(drawings)} TradingView drawings"):
                            
                            # Show drawing summary
                            st.markdown("##### Drawing Summary")
                            for drawing in drawings:
                                draw_type = drawing.get("type", "unknown")
                                draw_id = drawing.get("id", "")
                                num_points = len(drawing.get("points", []))
                                
                                st.markdown(f"- **{draw_type}** (ID: `{draw_id}`, {num_points} points)")
                            
                            # Show full JSON
                            st.markdown("##### Full TradingView JSON")
                            st.json(drawings)
                            
                            # Show API endpoint
                            st.markdown("##### API Endpoint")
                            st.code(
                                f"GET /api/drawings/tradingview?symbol={symbol}",
                                language="bash"
                            )
                            
                            # Download button
                            st.download_button(
                                label="📥 Download TradingView JSON",
                                data=json.dumps(drawings, indent=2),
                                file_name=f"{symbol}_tradingview_drawings_{timeframe}.json",
                                mime="application/json"
                            )
            else:
                st.error(f"❌ Scanner failed: {result.get('error')}")


if __name__ == "__main__":
    # Test the integration
    result = run_scanner_tradingview_sync(
        query="Find Bollinger Band squeeze",
        symbols=["AAPL", "MSFT"],
        timeframe="1D",
        max_results=2
    )
    
    print("📊 TradingView Scanner Result:")
    print(json.dumps(result, indent=2))
