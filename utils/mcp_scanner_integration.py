"""
MCP Scanner Integration for Streamlit
Connects MCP Scanner Agent with Technical Scanner UI
"""

import asyncio
import json
from typing import Dict, Any, Optional, List
from datetime import datetime
import pandas as pd

# Import the MCP Scanner Agent
try:
    from mcp_scanner_agent import (
        run_mcp_scanner,
        ScannerDrawingOutput,
        DrawingTranslator,
        save_drawings_to_cache,
        get_latest_drawings
    )
    MCP_SCANNER_AVAILABLE = True
except ImportError:
    MCP_SCANNER_AVAILABLE = False
    print("⚠️ MCP Scanner Agent not available")


class MCPScannerIntegration:
    """Integration layer between Streamlit and MCP Scanner Agent"""
    
    def __init__(self):
        self.cache = {}
        self.last_scan_time = {}
    
    async def scan_with_mcp(
        self,
        query: str,
        symbols: List[str],
        timeframe: str = "1D",
        max_results: int = 5
    ) -> Dict[str, Any]:
        """
        Run MCP scanner across multiple symbols
        
        Args:
            query: Scanner query (e.g., "Find Bollinger Band squeeze")
            symbols: List of stock symbols to scan
            timeframe: Chart timeframe
            max_results: Maximum number of results to return
        
        Returns:
            Dictionary with scan results and drawing instructions
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
                drawing_output = await run_mcp_scanner(
                    query=query,
                    symbol=symbol,
                    timeframe=timeframe
                )
                
                # Save to cache
                save_drawings_to_cache(symbol, drawing_output)
                
                # Store in memory cache
                self.cache[symbol] = drawing_output
                self.last_scan_time[symbol] = datetime.now()
                
                results.append({
                    "symbol": symbol,
                    "success": True,
                    "drawings": drawing_output.model_dump(),
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
    
    def get_drawings_for_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get cached drawing instructions for a symbol"""
        
        # Try memory cache first
        if symbol in self.cache:
            return self.cache[symbol].model_dump()
        
        # Try file cache
        cached = get_latest_drawings(symbol)
        if cached:
            return cached
        
        return None
    
    def get_drawing_json_for_frontend(self, symbol: str) -> str:
        """
        Get drawing instructions as JSON string for frontend consumption
        
        This is the endpoint that Next.js will call
        """
        drawings = self.get_drawings_for_symbol(symbol)
        
        if drawings:
            return json.dumps(drawings, indent=2)
        
        return json.dumps({
            "symbol": symbol,
            "timeframe": "1D",
            "drawings": [],
            "indicators": [],
            "metadata": {"error": "No drawings available"}
        })
    
    def convert_mcp_result_to_drawings(
        self,
        mcp_result: Dict[str, Any],
        symbol: str,
        timeframe: str
    ) -> ScannerDrawingOutput:
        """
        Convert raw MCP tool result to drawing instructions
        
        This is a fallback for when MCP agent doesn't return structured output
        """
        
        drawings = []
        translator = DrawingTranslator()
        
        # Parse MCP result and create drawings
        # This is a simplified example - expand based on actual MCP output
        
        if "bollinger_bands" in mcp_result:
            bb_data = mcp_result["bollinger_bands"]
            # Create Bollinger Band visualization
            # ... (implement based on actual data structure)
        
        if "rsi" in mcp_result:
            rsi_data = mcp_result["rsi"]
            # Create RSI signal arrows
            # ... (implement based on actual data structure)
        
        if "volume_breakout" in mcp_result:
            vol_data = mcp_result["volume_breakout"]
            # Create volume breakout box
            # ... (implement based on actual data structure)
        
        return ScannerDrawingOutput(
            symbol=symbol,
            timeframe=timeframe,
            drawings=drawings,
            indicators=[],
            metadata={"source": "fallback_converter"}
        )


# ============================================================================
# Streamlit Helper Functions
# ============================================================================

def run_scanner_sync(
    query: str,
    symbols: List[str],
    timeframe: str = "1D",
    max_results: int = 5
) -> Dict[str, Any]:
    """
    Synchronous wrapper for Streamlit
    
    Use this in Streamlit app:
    result = run_scanner_sync("Find Bollinger squeeze", ["AAPL", "MSFT"])
    """
    
    integration = MCPScannerIntegration()
    
    # Run async function in sync context
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        result = loop.run_until_complete(
            integration.scan_with_mcp(query, symbols, timeframe, max_results)
        )
        return result
    finally:
        loop.close()


def get_drawing_endpoint(symbol: str) -> str:
    """
    Get drawing JSON for a specific symbol
    
    This is what Next.js frontend will call:
    GET /api/drawings?symbol=AAPL
    """
    integration = MCPScannerIntegration()
    return integration.get_drawing_json_for_frontend(symbol)


# ============================================================================
# Example Integration with Streamlit
# ============================================================================

def streamlit_scanner_example():
    """
    Example of how to integrate with Streamlit Technical Scanner
    
    Add this to app_advanced.py in the Technical Scanner section
    """
    
    import streamlit as st
    
    st.markdown("### 📊 MCP Technical Scanner")
    
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
    if st.button("🔍 Scan with MCP Agent", type="primary"):
        with st.spinner("🤖 MCP Agent analyzing..."):
            
            # Run scanner
            result = run_scanner_sync(
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
                        
                        with st.expander(f"📈 {symbol} - {len(drawings.get('drawings', []))} signals"):
                            # Show drawing instructions
                            st.json(drawings)
                            
                            # Show API endpoint for frontend
                            st.code(
                                f"GET /api/drawings?symbol={symbol}",
                                language="bash"
                            )
                            
                            # Download button
                            st.download_button(
                                label="📥 Download Drawing JSON",
                                data=json.dumps(drawings, indent=2),
                                file_name=f"{symbol}_drawings_{timeframe}.json",
                                mime="application/json"
                            )
            else:
                st.error(f"❌ Scanner failed: {result.get('error')}")


if __name__ == "__main__":
    # Test the integration
    result = run_scanner_sync(
        query="Find Bollinger Band squeeze",
        symbols=["AAPL", "MSFT"],
        timeframe="1D",
        max_results=2
    )
    
    print("📊 Scanner Result:")
    print(json.dumps(result, indent=2))
