"""
Chart Visualization Module for TradingView MCP Integration
Creates interactive Plotly charts with Bollinger Bands overlay
"""

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from typing import Optional, Dict, List
from datetime import datetime


class ChartVisualizer:
    """Create interactive stock charts with technical indicators"""
    
    @staticmethod
    def create_candlestick_with_bollinger(
        df: pd.DataFrame,
        symbol: str,
        title: Optional[str] = None,
        show_volume: bool = True,
        show_squeeze_markers: bool = True,
        height: int = 600
    ) -> go.Figure:
        """
        Create candlestick chart with Bollinger Bands overlay
        
        Args:
            df: DataFrame with OHLC data and Bollinger Bands
            symbol: Stock symbol for title
            title: Custom title (optional)
            show_volume: Whether to show volume subplot
            show_squeeze_markers: Whether to mark squeeze periods
            height: Chart height in pixels
            
        Returns:
            Plotly Figure object
        """
        # Validate required columns
        required_cols = ['datetime', 'open', 'high', 'low', 'close']
        if not all(col in df.columns for col in required_cols):
            raise ValueError(f"DataFrame missing required columns: {required_cols}")
        
        # Create subplots
        if show_volume:
            fig = make_subplots(
                rows=2, cols=1,
                shared_xaxes=True,
                vertical_spacing=0.03,
                row_heights=[0.7, 0.3],
                subplot_titles=(title or f"{symbol} - Candlestick with Bollinger Bands", "Volume")
            )
        else:
            fig = go.Figure()
        
        # Add candlestick chart
        candlestick = go.Candlestick(
            x=df['datetime'],
            open=df['open'],
            high=df['high'],
            low=df['low'],
            close=df['close'],
            name='Price',
            increasing_line_color='#26a69a',
            decreasing_line_color='#ef5350'
        )
        
        if show_volume:
            fig.add_trace(candlestick, row=1, col=1)
        else:
            fig.add_trace(candlestick)
        
        # Add Bollinger Bands if available
        if 'bb_upper' in df.columns and 'bb_middle' in df.columns and 'bb_lower' in df.columns:
            # Upper band
            fig.add_trace(
                go.Scatter(
                    x=df['datetime'],
                    y=df['bb_upper'],
                    name='BB Upper',
                    line=dict(color='rgba(250, 128, 114, 0.5)', width=1, dash='dash'),
                    hovertemplate='Upper: %{y:.2f}<extra></extra>'
                ),
                row=1, col=1
            )
            
            # Middle band (SMA)
            fig.add_trace(
                go.Scatter(
                    x=df['datetime'],
                    y=df['bb_middle'],
                    name='BB Middle (SMA 20)',
                    line=dict(color='rgba(255, 193, 7, 0.8)', width=2),
                    hovertemplate='Middle: %{y:.2f}<extra></extra>'
                ),
                row=1, col=1
            )
            
            # Lower band
            fig.add_trace(
                go.Scatter(
                    x=df['datetime'],
                    y=df['bb_lower'],
                    name='BB Lower',
                    line=dict(color='rgba(250, 128, 114, 0.5)', width=1, dash='dash'),
                    hovertemplate='Lower: %{y:.2f}<extra></extra>'
                ),
                row=1, col=1
            )
            
            # Add band fill
            fig.add_trace(
                go.Scatter(
                    x=df['datetime'].tolist() + df['datetime'].tolist()[::-1],
                    y=df['bb_upper'].tolist() + df['bb_lower'].tolist()[::-1],
                    fill='toself',
                    fillcolor='rgba(250, 128, 114, 0.1)',
                    line=dict(color='rgba(255,255,255,0)'),
                    showlegend=False,
                    hoverinfo='skip'
                ),
                row=1, col=1
            )
            
            # Mark squeeze periods if requested
            if show_squeeze_markers and 'bb_width' in df.columns:
                # Calculate squeeze threshold (lowest 5% of band width)
                lookback = min(125, len(df))
                recent_widths = df['bb_width'].tail(lookback)
                threshold = recent_widths.quantile(0.05)
                
                # Find squeeze periods
                squeeze_mask = df['bb_width'] <= threshold
                squeeze_df = df[squeeze_mask]
                
                if not squeeze_df.empty:
                    fig.add_trace(
                        go.Scatter(
                            x=squeeze_df['datetime'],
                            y=squeeze_df['high'] * 1.02,  # Slightly above high
                            mode='markers',
                            name='Squeeze',
                            marker=dict(
                                symbol='triangle-down',
                                size=10,
                                color='red',
                                line=dict(color='darkred', width=1)
                            ),
                            hovertemplate='Bollinger Squeeze<br>Date: %{x}<extra></extra>'
                        ),
                        row=1, col=1
                    )
        
        # Add volume bars if requested
        if show_volume and 'volume' in df.columns:
            colors = ['red' if close < open else 'green' 
                     for close, open in zip(df['close'], df['open'])]
            
            fig.add_trace(
                go.Bar(
                    x=df['datetime'],
                    y=df['volume'],
                    name='Volume',
                    marker_color=colors,
                    opacity=0.5,
                    hovertemplate='Volume: %{y:,.0f}<extra></extra>'
                ),
                row=2, col=1
            )
        
        # Update layout
        fig.update_layout(
            title=title or f"{symbol} - Candlestick with Bollinger Bands",
            xaxis_title="Date",
            yaxis_title="Price",
            height=height,
            hovermode='x unified',
            xaxis_rangeslider_visible=False,
            template='plotly_white',
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            )
        )
        
        # Update axes
        fig.update_xaxes(
            gridcolor='rgba(128, 128, 128, 0.2)',
            showgrid=True
        )
        fig.update_yaxes(
            gridcolor='rgba(128, 128, 128, 0.2)',
            showgrid=True
        )
        
        return fig
    
    @staticmethod
    def create_candlestick_with_patterns(
        df: pd.DataFrame,
        symbol: str,
        pattern_name: Optional[str] = None,
        pattern_indices: Optional[List[int]] = None,
        title: Optional[str] = None,
        show_volume: bool = True,
        height: int = 600
    ) -> go.Figure:
        """
        Create candlestick chart with pattern markers
        
        Args:
            df: DataFrame with OHLC data
            symbol: Stock symbol for title
            pattern_name: Name of the pattern (e.g., "Hammer", "Doji")
            pattern_indices: List of indices where pattern occurs
            title: Custom title (optional)
            show_volume: Whether to show volume subplot
            height: Chart height in pixels
            
        Returns:
            Plotly Figure object
        """
        # Validate required columns
        required_cols = ['datetime', 'open', 'high', 'low', 'close']
        if not all(col in df.columns for col in required_cols):
            raise ValueError(f"DataFrame missing required columns: {required_cols}")
        
        # Create subplots
        if show_volume:
            fig = make_subplots(
                rows=2, cols=1,
                shared_xaxes=True,
                vertical_spacing=0.03,
                row_heights=[0.7, 0.3],
                subplot_titles=(title or f"{symbol} - Candlestick Patterns", "Volume")
            )
        else:
            fig = go.Figure()
        
        # Add candlestick chart
        candlestick = go.Candlestick(
            x=df['datetime'],
            open=df['open'],
            high=df['high'],
            low=df['low'],
            close=df['close'],
            name='Price',
            increasing_line_color='#26a69a',
            decreasing_line_color='#ef5350'
        )
        
        if show_volume:
            fig.add_trace(candlestick, row=1, col=1)
        else:
            fig.add_trace(candlestick)
        
        # Add 20-period SMA for reference
        if len(df) >= 20:
            sma_20 = df['close'].rolling(window=20).mean()
            fig.add_trace(
                go.Scatter(
                    x=df['datetime'],
                    y=sma_20,
                    name='SMA 20',
                    line=dict(color='rgba(255, 193, 7, 0.8)', width=2),
                    hovertemplate='SMA 20: %{y:.2f}<extra></extra>'
                ),
                row=1, col=1
            )
        
        # Mark pattern occurrences
        if pattern_indices and len(pattern_indices) > 0:
            pattern_df = df.iloc[pattern_indices]
            
            # Determine marker position and color based on pattern type
            is_bullish = pattern_name and any(word in pattern_name.lower() for word in ['bullish', 'hammer', 'morning', 'white', 'piercing'])
            
            if is_bullish:
                marker_y = pattern_df['low'] * 0.98  # Below low for bullish
                marker_symbol = 'triangle-up'
                marker_color = 'green'
            else:
                marker_y = pattern_df['high'] * 1.02  # Above high for bearish
                marker_symbol = 'triangle-down'
                marker_color = 'red'
            
            fig.add_trace(
                go.Scatter(
                    x=pattern_df['datetime'],
                    y=marker_y,
                    mode='markers',
                    name=pattern_name or 'Pattern',
                    marker=dict(
                        symbol=marker_symbol,
                        size=12,
                        color=marker_color,
                        line=dict(color='darkgreen' if is_bullish else 'darkred', width=1)
                    ),
                    hovertemplate=f'{pattern_name or "Pattern"}<br>Date: %{{x}}<extra></extra>'
                ),
                row=1, col=1
            )
        else:
            # No specific indices - mark recent patterns (last 10 candles)
            recent_df = df.tail(10)
            fig.add_trace(
                go.Scatter(
                    x=recent_df['datetime'],
                    y=recent_df['high'] * 1.02,
                    mode='markers',
                    name=pattern_name or 'Pattern Detected',
                    marker=dict(
                        symbol='star',
                        size=12,
                        color='gold',
                        line=dict(color='orange', width=1)
                    ),
                    hovertemplate=f'{pattern_name or "Pattern"}<br>Date: %{{x}}<extra></extra>'
                ),
                row=1, col=1
            )
        
        # Add volume bars if requested
        if show_volume and 'volume' in df.columns:
            colors = ['red' if close < open else 'green' 
                     for close, open in zip(df['close'], df['open'])]
            
            fig.add_trace(
                go.Bar(
                    x=df['datetime'],
                    y=df['volume'],
                    name='Volume',
                    marker_color=colors,
                    opacity=0.5,
                    hovertemplate='Volume: %{y:,.0f}<extra></extra>'
                ),
                row=2, col=1
            )
        
        # Update layout
        pattern_title = f" - {pattern_name}" if pattern_name else ""
        fig.update_layout(
            title=title or f"{symbol} - Candlestick Patterns{pattern_title}",
            xaxis_title="Date",
            yaxis_title="Price",
            height=height,
            hovermode='x unified',
            xaxis_rangeslider_visible=False,
            template='plotly_white',
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            )
        )
        
        # Update axes
        fig.update_xaxes(
            gridcolor='rgba(128, 128, 128, 0.2)',
            showgrid=True
        )
        fig.update_yaxes(
            gridcolor='rgba(128, 128, 128, 0.2)',
            showgrid=True
        )
        
        return fig
    
    @staticmethod
    def create_multi_stock_comparison(
        data_dict: Dict[str, pd.DataFrame],
        title: str = "Stock Comparison",
        height: int = 500
    ) -> go.Figure:
        """
        Create comparison chart for multiple stocks
        
        Args:
            data_dict: Dictionary mapping symbol to DataFrame
            title: Chart title
            height: Chart height
            
        Returns:
            Plotly Figure object
        """
        fig = go.Figure()
        
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', 
                  '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']
        
        for idx, (symbol, df) in enumerate(data_dict.items()):
            if 'datetime' in df.columns and 'close' in df.columns:
                # Normalize to percentage change from first value
                normalized = (df['close'] / df['close'].iloc[0] - 1) * 100
                
                fig.add_trace(
                    go.Scatter(
                        x=df['datetime'],
                        y=normalized,
                        name=symbol,
                        line=dict(color=colors[idx % len(colors)], width=2),
                        hovertemplate=f'{symbol}: %{{y:.2f}}%<extra></extra>'
                    )
                )
        
        fig.update_layout(
            title=title,
            xaxis_title="Date",
            yaxis_title="% Change",
            height=height,
            hovermode='x unified',
            template='plotly_white',
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            )
        )
        
        return fig
    
    @staticmethod
    def create_indicator_panel(
        df: pd.DataFrame,
        symbol: str,
        indicators: List[str] = ['rsi', 'macd'],
        height: int = 400
    ) -> go.Figure:
        """
        Create panel with technical indicators
        
        Args:
            df: DataFrame with indicator data
            symbol: Stock symbol
            indicators: List of indicators to show
            height: Chart height
            
        Returns:
            Plotly Figure object
        """
        num_indicators = len(indicators)
        
        fig = make_subplots(
            rows=num_indicators,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.05,
            subplot_titles=[ind.upper() for ind in indicators]
        )
        
        for idx, indicator in enumerate(indicators, 1):
            if indicator == 'rsi' and 'rsi' in df.columns:
                # RSI
                fig.add_trace(
                    go.Scatter(
                        x=df['datetime'],
                        y=df['rsi'],
                        name='RSI',
                        line=dict(color='purple', width=2)
                    ),
                    row=idx, col=1
                )
                
                # Add overbought/oversold lines
                fig.add_hline(y=70, line_dash="dash", line_color="red", 
                             annotation_text="Overbought", row=idx, col=1)
                fig.add_hline(y=30, line_dash="dash", line_color="green", 
                             annotation_text="Oversold", row=idx, col=1)
                
            elif indicator == 'macd' and 'macd' in df.columns:
                # MACD
                fig.add_trace(
                    go.Scatter(
                        x=df['datetime'],
                        y=df['macd'],
                        name='MACD',
                        line=dict(color='blue', width=2)
                    ),
                    row=idx, col=1
                )
                
                fig.add_trace(
                    go.Scatter(
                        x=df['datetime'],
                        y=df['macd_signal'],
                        name='Signal',
                        line=dict(color='red', width=2)
                    ),
                    row=idx, col=1
                )
                
                # MACD histogram
                colors = ['green' if val >= 0 else 'red' for val in df['macd_histogram']]
                fig.add_trace(
                    go.Bar(
                        x=df['datetime'],
                        y=df['macd_histogram'],
                        name='Histogram',
                        marker_color=colors,
                        opacity=0.5
                    ),
                    row=idx, col=1
                )
        
        fig.update_layout(
            title=f"{symbol} - Technical Indicators",
            height=height,
            hovermode='x unified',
            template='plotly_white',
            showlegend=True
        )
        
        return fig


# Convenience functions
def plot_stock_with_bollinger(df: pd.DataFrame, symbol: str, **kwargs) -> go.Figure:
    """Convenience function to create candlestick chart with Bollinger Bands"""
    return ChartVisualizer.create_candlestick_with_bollinger(df, symbol, **kwargs)


def plot_comparison(data_dict: Dict[str, pd.DataFrame], **kwargs) -> go.Figure:
    """Convenience function to create comparison chart"""
    return ChartVisualizer.create_multi_stock_comparison(data_dict, **kwargs)
