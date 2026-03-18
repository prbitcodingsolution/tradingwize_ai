"""
MCP Visualization Pipeline
Complete pipeline from MCP signal to visual chart
Supports ALL TradingView MCP tools
Generates overlay JSON for Next.js integration
"""

from typing import Optional, Dict, Tuple, List
import pandas as pd
import plotly.graph_objects as go
import os

from .data_fetcher import get_data_fetcher
from .indicators import TechnicalIndicators, detect_squeeze
from .chart_visualizer import ChartVisualizer
from .mcp_parser import MCPResponseParser
from .comprehensive_chart_types import get_chart_for_tool_type, CHART_TYPES
from .overlay_generator import OverlayGenerator, convert_analysis_to_overlay
from .chart_overlay_client import get_overlay_client


class MCPVisualizationPipeline:
    """
    Complete pipeline for MCP-driven stock visualization
    Supports ALL TradingView MCP tools
    
    Flow:
    1. Parse MCP response → Extract symbols
    2. Fetch OHLC data → yfinance
    3. Calculate indicators → Based on tool type
    4. Create visualization → Appropriate chart type
    5. Generate explanation → AI analysis
    """
    
    def __init__(self):
        self.data_fetcher = get_data_fetcher()
        self.parser = MCPResponseParser()
        self.visualizer = ChartVisualizer()
        self.overlay_enabled = os.getenv("ENABLE_CHART_OVERLAY", "false").lower() == "true"
        self.overlay_client = get_overlay_client() if self.overlay_enabled else None
    
    def _calculate_indicators_for_tool_type(self, df: pd.DataFrame, tool_type: str) -> pd.DataFrame:
        """
        Calculate required indicators based on tool type
        
        Args:
            df: DataFrame with OHLC data
            tool_type: Type of analysis
            
        Returns:
            DataFrame with calculated indicators
        """
        if tool_type in ['bollinger', 'rating']:
            df = TechnicalIndicators.calculate_bollinger_bands(df)
        elif tool_type == 'rsi':
            df = TechnicalIndicators.calculate_rsi(df)
            df = TechnicalIndicators.calculate_bollinger_bands(df)  # For context
        elif tool_type == 'macd':
            df = TechnicalIndicators.calculate_macd(df)
            df = TechnicalIndicators.calculate_bollinger_bands(df)  # For context
        elif tool_type in ['moving_average', 'ma']:
            df = TechnicalIndicators.calculate_moving_averages(df)
        elif tool_type == 'volume':
            # Volume is already in OHLC data
            pass
        elif tool_type in ['multi', 'complete', 'coin_analysis']:
            df = TechnicalIndicators.add_all_indicators(df)
        elif tool_type in ['candlestick', 'pattern', 'consecutive_candles']:
            # Candlestick patterns don't need indicators, just OHLC
            pass
        else:
            # Default: add all indicators
            df = TechnicalIndicators.add_all_indicators(df)
        
        return df
    
    def process_mcp_response(
        self,
        mcp_response: str,
        timeframe: str = '1d',
        max_stocks: int = 5,
        tool_type: str = 'unknown'
    ) -> Dict:
        """
        Process MCP response and generate visualizations
        
        Args:
            mcp_response: Text response from MCP tool (string or ToolResponse object)
            timeframe: Timeframe for charts ('1m', '5m', '1h', '1d', etc.)
            max_stocks: Maximum number of stocks to visualize
            tool_type: Type of MCP tool ('bollinger', 'candlestick', 'rating', 'unknown')
            
        Returns:
            Dictionary with:
            {
                'stocks': [
                    {
                        'symbol': 'RELIANCE.NS',
                        'data': DataFrame,
                        'chart': Plotly Figure,
                        'squeeze_detected': bool (for bollinger),
                        'pattern': str (for candlestick),
                        'explanation': str
                    },
                    ...
                ],
                'summary': str,
                'total_found': int,
                'tool_type': str
            }
        """
        print(f"\n📊 Processing MCP response for visualization...")
        
        # Handle ToolResponse object at entry point
        if hasattr(mcp_response, 'content'):
            print(f"   🔄 Converting ToolResponse to string...")
            mcp_response = mcp_response.content
        elif not isinstance(mcp_response, str):
            print(f"   🔄 Converting {type(mcp_response)} to string...")
            mcp_response = str(mcp_response)
        
        # Step 1: Parse MCP response with generic parser
        parsed_stocks = self.parser.parse_generic_mcp_response(mcp_response, tool_type)
        
        # Auto-detect tool type from parsed results if still unknown
        if tool_type == 'unknown' and parsed_stocks:
            tool_type = parsed_stocks[0].get('tool_type', 'unknown')
        
        print(f"   🔍 Detected tool type: {tool_type}")
        
        # Check for empty MCP response
        if not parsed_stocks:
            print("   ⚠️ No stocks found in MCP response")
            
            # Check if MCP returned empty array [] or just no parseable data
            is_empty_array = '[]' in mcp_response or 'no stocks' in mcp_response.lower() or 'not found' in mcp_response.lower()
            
            return {
                'stocks': [],
                'summary': 'No stocks found matching criteria',
                'total_found': 0,
                'processed': 0,
                'empty_response': True,  # Flag for empty response
                'is_empty_array': is_empty_array,  # Distinguish between empty [] and parse failure
                'tool_type': tool_type
            }
        
        print(f"   ✅ Found {len(parsed_stocks)} stocks in MCP response")
        
        # Limit to max_stocks
        stocks_to_process = parsed_stocks[:max_stocks]
        
        # Step 2-4: Process each stock
        results = []
        skipped_crypto = []
        
        for stock_info in stocks_to_process:
            symbol = stock_info['symbol']
            
            # Check if it's a crypto symbol
            if self.parser.is_crypto_symbol(symbol):
                print(f"\n   ⚠️ Skipping crypto symbol: {symbol}")
                print(f"      (Crypto analysis not supported in current version)")
                skipped_crypto.append(symbol)
                continue
            
            # Normalize symbol for yfinance
            normalized_symbol = self.parser.normalize_symbol_for_yfinance(symbol)
            
            print(f"\n   📈 Processing {normalized_symbol}...")
            
            # Fetch OHLC data
            df, error = self.data_fetcher.fetch_ohlc(
                normalized_symbol,
                timeframe=timeframe
            )
            
            if error or df is None:
                print(f"      ❌ Failed to fetch data: {error}")
                continue
            
            # Create chart based on tool type
            try:
                # Calculate required indicators
                df = self._calculate_indicators_for_tool_type(df, tool_type)
                
                # Get appropriate chart function
                chart_func = get_chart_for_tool_type(tool_type)
                
                # Create chart with tool-specific parameters
                if tool_type in ['candlestick', 'pattern', 'consecutive_candles']:
                    pattern_name = stock_info.get('pattern', 'Pattern Detected')
                    chart = chart_func(
                        df,
                        normalized_symbol,
                        pattern_name=pattern_name,
                        show_volume=True
                    )
                    analysis = {
                        'pattern': pattern_name,
                        'explanation': stock_info.get('description', f'{pattern_name} detected'),
                        'data': df
                    }
                    print(f"      ✅ {tool_type.title()} chart created: {pattern_name}")
                    
                else:
                    # For other tool types (bollinger, rsi, macd, etc.)
                    chart = chart_func(df, normalized_symbol, show_volume=True)
                    
                    # Tool-specific analysis
                    if tool_type in ['bollinger', 'rating']:
                        is_squeeze, percentile, explanation = detect_squeeze(df)
                        analysis = {
                            'squeeze_detected': is_squeeze,
                            'squeeze_percentile': percentile,
                            'explanation': explanation,
                            'data': df
                        }
                    elif tool_type == 'rsi':
                        rsi_value = float(df['rsi'].iloc[-1]) if 'rsi' in df.columns else None
                        analysis = {
                            'rsi_value': rsi_value,
                            'explanation': f'RSI: {rsi_value:.2f}' if rsi_value else 'RSI analysis',
                            'data': df
                        }
                    elif tool_type == 'macd':
                        macd_signal = stock_info.get('macd_signal', 'Neutral')
                        analysis = {
                            'macd_signal': macd_signal,
                            'explanation': f'MACD Signal: {macd_signal}',
                            'data': df
                        }
                    else:
                        analysis = {
                            'explanation': stock_info.get('description', f'{tool_type.title()} analysis'),
                            'data': df
                        }
                    
                    print(f"      ✅ {tool_type.title()} chart created")
                
            except Exception as e:
                print(f"      ❌ Failed to create chart: {e}")
                chart = None
                analysis = {}
            
            # Compile result
            result = {
                'symbol': normalized_symbol,
                'original_symbol': symbol,
                'data': df,
                'chart': chart,
                'timeframe': timeframe,
                'signal_strength': stock_info.get('signal_strength', 'medium'),
                'mcp_description': stock_info.get('description', ''),
                'tool_type': tool_type
            }
            
            # Add tool-specific fields
            if tool_type == 'candlestick':
                result['pattern'] = analysis.get('pattern', 'Pattern')
                result['explanation'] = analysis.get('explanation', '')
            else:
                result['squeeze_detected'] = analysis.get('squeeze_detected', False)
                result['squeeze_percentile'] = analysis.get('squeeze_percentile', 0)
                result['explanation'] = analysis.get('explanation', '')
            
            results.append(result)
        
        # Generate summary
        summary = self._generate_summary(results, len(parsed_stocks), skipped_crypto, tool_type)
        
        analysis_results = {
            'stocks': results,
            'summary': summary,
            'total_found': len(parsed_stocks),
            'processed': len(results),
            'skipped_crypto': skipped_crypto,
            'tool_type': tool_type
        }
        
        # Generate and send overlay JSON for Next.js integration
        if self.overlay_enabled and self.overlay_client and results:
            try:
                overlay_json = convert_analysis_to_overlay(analysis_results, tool_type)
                if overlay_json:
                    self.overlay_client.send_batch(overlay_json)
                    print(f"   📡 Overlay signals sent to Next.js ({len(results)} stocks)")
            except Exception as e:
                print(f"   ⚠️ Failed to send overlay signals: {e}")
        
        return analysis_results
    
    def visualize_single_stock(
        self,
        symbol: str,
        timeframe: str = '1d',
        period: Optional[str] = None,
        tool_type: str = 'bollinger'
    ) -> Tuple[Optional[go.Figure], Optional[str], Dict]:
        """
        Visualize a single stock with specified analysis type
        
        Args:
            symbol: Stock symbol (e.g., "RELIANCE.NS")
            timeframe: Timeframe for chart
            period: Period to fetch (optional)
            tool_type: Type of analysis (bollinger, candlestick, rsi, macd, ma, volume, multi)
            
        Returns:
            Tuple of (Figure, error_message, analysis_dict)
        """
        print(f"\n📊 Visualizing {symbol} ({timeframe}) - Tool type: {tool_type}...")
        
        # Fetch data
        df, error = self.data_fetcher.fetch_ohlc(symbol, timeframe, period)
        
        if error or df is None:
            return None, error, {}
        
        # Calculate indicators based on tool type
        df = self._calculate_indicators_for_tool_type(df, tool_type)
        
        # Get appropriate chart function
        chart_func = get_chart_for_tool_type(tool_type)
        
        # Create chart
        try:
            if tool_type in ['candlestick', 'pattern']:
                chart = chart_func(df, symbol, pattern_name="Candlestick Patterns", show_volume=True)
                analysis = {
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'pattern': 'Multiple Patterns',
                    'explanation': f'Candlestick pattern analysis for {symbol}',
                    'latest_price': float(df['close'].iloc[-1]),
                    'data': df
                }
            elif tool_type in ['bollinger', 'rating']:
                chart = chart_func(df, symbol, show_volume=True, show_squeeze_markers=True)
                is_squeeze, percentile, explanation = detect_squeeze(df)
                analysis = {
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'squeeze_detected': is_squeeze,
                    'squeeze_percentile': percentile,
                    'explanation': explanation,
                    'latest_price': float(df['close'].iloc[-1]),
                    'bb_upper': float(df['bb_upper'].iloc[-1]) if 'bb_upper' in df.columns else None,
                    'bb_middle': float(df['bb_middle'].iloc[-1]) if 'bb_middle' in df.columns else None,
                    'bb_lower': float(df['bb_lower'].iloc[-1]) if 'bb_lower' in df.columns else None,
                    'bb_width': float(df['bb_width'].iloc[-1]) if 'bb_width' in df.columns else None,
                    'data': df
                }
            elif tool_type == 'rsi':
                chart = chart_func(df, symbol, show_volume=True)
                rsi_value = float(df['rsi'].iloc[-1]) if 'rsi' in df.columns else None
                analysis = {
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'rsi_value': rsi_value,
                    'explanation': f'RSI: {rsi_value:.2f} - {"Overbought" if rsi_value and rsi_value > 70 else "Oversold" if rsi_value and rsi_value < 30 else "Neutral"}',
                    'latest_price': float(df['close'].iloc[-1]),
                    'data': df
                }
            elif tool_type == 'macd':
                chart = chart_func(df, symbol, show_volume=True)
                analysis = {
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'explanation': f'MACD analysis for {symbol}',
                    'latest_price': float(df['close'].iloc[-1]),
                    'data': df
                }
            else:
                # Default: use the chart function as-is
                chart = chart_func(df, symbol, show_volume=True)
                analysis = {
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'explanation': f'{tool_type.title()} analysis for {symbol}',
                    'latest_price': float(df['close'].iloc[-1]),
                    'data': df
                }
            
            # Add RSI if available
            if 'rsi' in df.columns:
                analysis['rsi'] = float(df['rsi'].iloc[-1])
            
            print(f"   ✅ {tool_type.title()} visualization complete")
            
            # Generate and send overlay JSON for Next.js integration
            if self.overlay_enabled and self.overlay_client:
                try:
                    # Generate overlay based on tool type
                    if tool_type == 'bollinger':
                        overlay_json = OverlayGenerator.generate_bollinger_overlay(
                            df, symbol, timeframe,
                            analysis.get('squeeze_detected', False),
                            analysis.get('squeeze_percentile', 0)
                        )
                    elif tool_type == 'rsi':
                        overlay_json = OverlayGenerator.generate_rsi_overlay(
                            df, symbol, timeframe, analysis.get('rsi_value')
                        )
                    elif tool_type == 'macd':
                        overlay_json = OverlayGenerator.generate_macd_overlay(
                            df, symbol, timeframe, analysis.get('macd_signal')
                        )
                    elif tool_type == 'volume':
                        overlay_json = OverlayGenerator.generate_volume_overlay(
                            df, symbol, timeframe
                        )
                    elif tool_type in ['candlestick', 'pattern']:
                        overlay_json = OverlayGenerator.generate_candlestick_overlay(
                            df, symbol, timeframe, analysis.get('pattern')
                        )
                    elif tool_type in ['multi', 'complete']:
                        overlay_json = OverlayGenerator.generate_complete_overlay(
                            df, symbol, timeframe, analysis
                        )
                    else:
                        overlay_json = OverlayGenerator.generate_bollinger_overlay(
                            df, symbol, timeframe
                        )
                    
                    if overlay_json:
                        self.overlay_client.send_overlay(overlay_json)
                        print(f"   📡 Overlay signal sent to Next.js")
                except Exception as e:
                    print(f"   ⚠️ Failed to send overlay signal: {e}")
            
        except Exception as e:
            return None, f"Failed to create chart: {e}", {}
        
        return chart, None, analysis
    
    def _generate_summary(self, results: List[Dict], total_found: int, skipped_crypto: List[str] = None, tool_type: str = 'unknown') -> str:
        """Generate summary of visualization results"""
        if skipped_crypto is None:
            skipped_crypto = []
        
        if not results and not skipped_crypto:
            return f"Found {total_found} stocks but failed to visualize any."
        
        summary = f"📊 Visualization Summary:\n"
        summary += f"   • Total stocks found: {total_found}\n"
        
        if skipped_crypto:
            summary += f"   • Crypto symbols skipped: {len(skipped_crypto)} (not supported)\n"
        
        summary += f"   • Successfully visualized: {len(results)}\n"
        
        if results:
            if tool_type == 'candlestick':
                # Candlestick pattern summary
                patterns = {}
                for result in results:
                    pattern = result.get('pattern', 'Unknown')
                    patterns[pattern] = patterns.get(pattern, 0) + 1
                
                summary += f"   • Patterns detected:\n"
                for pattern, count in patterns.items():
                    summary += f"      - {pattern}: {count} stock(s)\n"
                
                summary += "\n🔥 Stocks with Patterns:\n"
                for result in results:
                    pattern = result.get('pattern', 'Pattern')
                    summary += f"   • {result['symbol']}: {pattern}\n"
                
            else:
                # Bollinger Band summary
                squeeze_count = sum(1 for r in results if r.get('squeeze_detected', False))
                summary += f"   • Bollinger squeeze detected: {squeeze_count}/{len(results)}\n\n"
                
                if squeeze_count > 0:
                    summary += "🔥 Stocks with Bollinger Squeeze:\n"
                    for result in results:
                        if result.get('squeeze_detected', False):
                            summary += f"   • {result['symbol']}: {result.get('squeeze_percentile', 0):.1f}% percentile\n"
        
        if skipped_crypto:
            summary += f"\n⚠️ Note: Crypto symbols were skipped:\n"
            for crypto in skipped_crypto[:5]:  # Show max 5
                summary += f"   • {crypto}\n"
            if len(skipped_crypto) > 5:
                summary += f"   • ... and {len(skipped_crypto) - 5} more\n"
            summary += "\n💡 Tip: For Indian stocks, try queries like:\n"
            summary += "   'Find Indian stocks with Bollinger squeeze on NSE'\n"
        
        return summary


# Singleton instance
_pipeline_instance = None

def get_visualization_pipeline() -> MCPVisualizationPipeline:
    """Get singleton instance of visualization pipeline"""
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = MCPVisualizationPipeline()
    return _pipeline_instance


# Convenience functions
def visualize_mcp_response(mcp_response: str, timeframe: str = '1d', max_stocks: int = 5) -> Dict:
    """Convenience function to visualize MCP response"""
    pipeline = get_visualization_pipeline()
    return pipeline.process_mcp_response(mcp_response, timeframe, max_stocks)


def visualize_stock(symbol: str, timeframe: str = '1d') -> Tuple[Optional[go.Figure], Optional[str], Dict]:
    """Convenience function to visualize single stock"""
    pipeline = get_visualization_pipeline()
    return pipeline.visualize_single_stock(symbol, timeframe)
