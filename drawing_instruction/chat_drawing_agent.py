"""
Chat-Based Drawing Instruction Generator
Uses LLM to understand user intent and generate appropriate drawing instructions
"""

import logging
from openai import OpenAI
import os
import json
from dotenv import load_dotenv
from typing import Dict, List, Optional

load_dotenv()

logger = logging.getLogger(__name__)


class ChatDrawingAgent:
    """
    Intelligent agent that understands natural language requests
    and generates appropriate drawing instructions
    """
    
    def __init__(self):
        """Initialize the chat agent with OpenRouter LLM"""
        self.openrouter_api_key = os.getenv('OPENROUTER_API_KEY')
        self.openrouter_base_url = os.getenv('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')
        
        if not self.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY not found in environment variables")
        
        self.client = OpenAI(
            api_key=self.openrouter_api_key,
            base_url=self.openrouter_base_url
        )
        self.model = "openai/gpt-oss-120b"
        
        logger.info(f"✅ Initialized ChatDrawingAgent with {self.model}")
    
    def parse_user_intent(self, user_message: str, symbol: str) -> Dict:
        """
        Parse user message to understand what drawing instructions they want
        
        Args:
            user_message: Natural language request from user
            symbol: Stock symbol
            
        Returns:
            Dict with parsed intent and parameters
        """
        
        system_prompt = """You are an expert technical analysis assistant that understands user requests for chart drawings.

Your job is to analyze the user's message and determine what technical analysis drawings they want to see on their chart.

Available drawing types:
1. supply_demand_zones - Supply and demand zones (rectangles showing price levels)
2. fvg - Fair Value Gaps (FVG) - 3-candle imbalance patterns
3. smc - Smart Money Concepts (BOS, CHoCH, Order Blocks, Equal Highs/Lows)
4. liquidity_sweeps - Liquidity Sweeps (wick sweeps and outbreak retests)
5. macd - MACD (Moving Average Convergence Divergence) indicator with signals
6. candlestick_patterns - Candlestick patterns (doji, hammer, engulfing, etc.)
7. bollinger_bands - Bollinger Bands indicator
8. rsi_signals - RSI overbought/oversold signals
9. macd_crossovers - MACD bullish/bearish crossovers
10. key_levels - Support and resistance levels
11. all - All available analysis

Respond with ONLY a JSON object in this exact format:
{
  "intent": "generate_drawings",
  "drawing_types": ["supply_demand_zones", "candlestick_patterns"],
  "confidence": 0.95,
  "user_wants": "brief description of what user wants"
}

Examples:
User: "mark supply and demand zones on this stock"
Response: {"intent": "generate_drawings", "drawing_types": ["supply_demand_zones"], "confidence": 0.98, "user_wants": "supply and demand zones"}

User: "mark FVG on this stock" or "show fair value gaps"
Response: {"intent": "generate_drawings", "drawing_types": ["fvg"], "confidence": 0.98, "user_wants": "Fair Value Gaps (FVG)"}

User: "mark SMC on this stock" or "show smart money concepts"
Response: {"intent": "generate_drawings", "drawing_types": ["smc"], "confidence": 0.98, "user_wants": "Smart Money Concepts (SMC) analysis"}

User: "mark liquidity on this stock" or "show liquidity sweeps"
Response: {"intent": "generate_drawings", "drawing_types": ["liquidity_sweeps"], "confidence": 0.98, "user_wants": "Liquidity Sweeps analysis"}

User: "mark MACD on this stock" or "show MACD indicator"
Response: {"intent": "generate_drawings", "drawing_types": ["macd"], "confidence": 0.98, "user_wants": "MACD indicator analysis"}

User: "show me candlestick patterns and support resistance"
Response: {"intent": "generate_drawings", "drawing_types": ["candlestick_patterns", "key_levels"], "confidence": 0.95, "user_wants": "candlestick patterns and support/resistance levels"}

User: "analyze this chart with all indicators"
Response: {"intent": "generate_drawings", "drawing_types": ["all"], "confidence": 0.90, "user_wants": "complete technical analysis"}

User: "show RSI and MACD signals"
Response: {"intent": "generate_drawings", "drawing_types": ["rsi_signals", "macd_crossovers"], "confidence": 0.97, "user_wants": "RSI and MACD indicators"}

IMPORTANT: Return ONLY valid JSON, no other text."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Stock: {symbol}\nUser request: {user_message}"}
                ],
                temperature=0.3,
                max_tokens=300
            )
            
            result_text = response.choices[0].message.content.strip()
            logger.info(f"LLM intent parsing response: {result_text}")
            
            # Parse JSON response
            intent_data = json.loads(result_text)
            
            # Validate response structure
            if 'intent' not in intent_data or 'drawing_types' not in intent_data:
                raise ValueError("Invalid intent response structure")
            
            return intent_data
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.error(f"Response was: {result_text}")
            # Fallback: try to extract drawing types from text
            return self._fallback_intent_parsing(user_message)
        
        except Exception as e:
            logger.error(f"Error parsing user intent: {e}")
            return self._fallback_intent_parsing(user_message)
    
    def _fallback_intent_parsing(self, user_message: str) -> Dict:
        """
        Fallback intent parsing using keyword matching
        
        Args:
            user_message: User's message
            
        Returns:
            Dict with parsed intent
        """
        message_lower = user_message.lower()
        drawing_types = []
        
        # Keyword matching
        if any(word in message_lower for word in ['supply', 'demand', 'zone', 'zones']):
            drawing_types.append('supply_demand_zones')
        
        if any(word in message_lower for word in ['fvg', 'fair value gap', 'fair value', 'gap', 'imbalance', 'inefficiency', 'liquidity void']):
            drawing_types.append('fvg')
        
        if any(word in message_lower for word in ['smc', 'smart money', 'smart money concepts', 'bos', 'choch', 'order block', 'order blocks']):
            drawing_types.append('smc')
        
        if any(word in message_lower for word in ['liquidity', 'sweep', 'sweeps', 'liquidity sweep', 'liquidity sweeps', 'wick sweep', 'outbreak']):
            drawing_types.append('liquidity_sweeps')
        
        if any(word in message_lower for word in ['macd', 'moving average convergence divergence', 'macd indicator', 'macd signals', 'macd crossover']):
            drawing_types.append('macd')
        
        if any(word in message_lower for word in ['pattern', 'candlestick', 'doji', 'hammer', 'engulfing']):
            drawing_types.append('candlestick_patterns')
        
        if any(word in message_lower for word in ['bollinger', 'bb', 'bands']):
            drawing_types.append('bollinger_bands')
        
        if any(word in message_lower for word in ['rsi', 'overbought', 'oversold']):
            drawing_types.append('rsi_signals')
        
        if any(word in message_lower for word in ['macd', 'crossover']):
            drawing_types.append('macd_crossovers')
        
        if any(word in message_lower for word in ['support', 'resistance', 'level', 'levels']):
            drawing_types.append('key_levels')
        
        if any(word in message_lower for word in ['all', 'everything', 'complete', 'full']):
            drawing_types = ['all']
        
        # Default to all if nothing matched
        if not drawing_types:
            drawing_types = ['all']
        
        return {
            'intent': 'generate_drawings',
            'drawing_types': drawing_types,
            'confidence': 0.70,
            'user_wants': 'technical analysis',
            'method': 'fallback_keyword_matching'
        }
    
    def generate_from_chat(
        self,
        user_message: str,
        symbol: str,
        timeframe: str = "1d",
        start_date: str = None,
        end_date: str = None,
        market: str = "stock"
    ) -> Dict:
        """
        Generate drawing instructions based on natural language chat input
        
        Args:
            user_message: Natural language request (e.g., "mark supply and demand zones")
            symbol: Stock symbol
            timeframe: Chart timeframe
            start_date: Start date (YYYY-MM-DD format)
            end_date: End date (YYYY-MM-DD format)
            market: Market type (stock, forex, crypto)
            
        Returns:
            Dict with drawing instructions and metadata
        """
        
        logger.info(f"📥 Chat request: '{user_message}' for {symbol}")
        
        try:
            # Step 1: Parse user intent
            logger.info("🤖 Parsing user intent with LLM...")
            intent = self.parse_user_intent(user_message, symbol)
            
            logger.info(f"✅ Intent parsed: {intent['drawing_types']} (confidence: {intent['confidence']})")
            logger.info(f"   User wants: {intent['user_wants']}")
            
            # Step 2: Generate drawings based on intent
            # Try absolute import first, then relative
            try:
                from llm_drawing_generator import generate_drawings_with_llm
                from symbol_resolver import resolve_symbol
            except ImportError:
                from .llm_drawing_generator import generate_drawings_with_llm
                from .symbol_resolver import resolve_symbol
            
            # Resolve symbol
            resolved_symbol = resolve_symbol(symbol)
            logger.info(f"🔍 Resolved symbol: {symbol} -> {resolved_symbol}")
            
            # Prepare API config
            api_config = {
                'base_url': os.getenv('API_BASE_URL', 'http://192.168.0.126:8000'),
                'from_date': start_date,
                'to_date': end_date,
                'market': market,
                'bearer_token': os.getenv('API_BEARER_TOKEN'),
                'csrf_token': os.getenv('API_CSRF_TOKEN')
            }
            
            # Generate drawings
            logger.info(f"🎨 Generating drawings for: {', '.join(intent['drawing_types'])}")
            
            result = generate_drawings_with_llm(
                symbol=resolved_symbol,
                timeframe=timeframe,
                use_api=True,
                api_config=api_config
            )
            
            # Filter drawings based on user intent
            if 'all' not in intent['drawing_types']:
                result = self._filter_drawings_by_intent(result, intent['drawing_types'])
            
            # Add chat metadata
            result['chat_metadata'] = {
                'user_message': user_message,
                'parsed_intent': intent,
                'drawing_types_requested': intent['drawing_types'],
                'confidence': intent['confidence']
            }
            
            logger.info(f"✅ Generated {result.get('total_drawings', 0)} drawings based on chat request")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Error in chat-based generation: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            return {
                'success': False,
                'error': str(e),
                'symbol': symbol,
                'total_drawings': 0,
                'drawings': []
            }
    
    def _filter_drawings_by_intent(self, result: Dict, drawing_types: List[str]) -> Dict:
        """
        Filter drawings based on user's requested types
        
        Args:
            result: Full drawing result
            drawing_types: List of requested drawing types
            
        Returns:
            Filtered result
        """
        
        if not result.get('drawings'):
            return result
        
        # Preserve original drawings for debugging
        result['original_drawings'] = result['drawings'].copy()
        
        logger.info(f"🔍 Starting filtering: {len(result['drawings'])} total drawings, requested types: {drawing_types}")
        
        filtered_drawings = []
        
        # Type mapping
        type_mapping = {
            'supply_demand_zones': ['LineToolRectangle'],
            'fvg': ['LineToolRectangle'],  # FVG also uses rectangles
            'smc': ['LineToolRectangle', 'LineToolTrendLine', 'LineToolNote', 'LineToolHorzLine'],  # SMC uses multiple types
            'liquidity_sweeps': ['LineToolRectangle', 'LineToolHorzLine', 'LineToolNote'],  # Liquidity sweeps use rectangles, lines, and notes
            'macd': ['LineToolTrendLine', 'LineToolNote', 'LineToolHorzLine'],  # MACD uses trend lines, notes, and horizontal lines
            'candlestick_patterns': ['LineToolNote'],
            'bollinger_bands': ['LineToolTrendLine'],
            'rsi_signals': ['LineToolNote'],
            'macd_crossovers': ['LineToolNote'],
            'key_levels': ['LineToolHorzLine']
        }
        
        # Collect allowed types
        allowed_types = set()
        for drawing_type in drawing_types:
            if drawing_type in type_mapping:
                allowed_types.update(type_mapping[drawing_type])
        
        # Filter drawings
        for drawing in result['drawings']:
            drawing_type = drawing.get('type')
            
            # For supply/demand zones, check if it's a zone (has zone-specific metadata)
            if 'supply_demand_zones' in drawing_types and drawing_type == 'LineToolRectangle':
                if 'metadata' in drawing and 'base_candles' in drawing.get('metadata', {}):
                    filtered_drawings.append(drawing)
                    continue
            
            # For FVG zones, check if it's an FVG (has FVG-specific metadata)
            if 'fvg' in drawing_types and drawing_type == 'LineToolRectangle':
                metadata = drawing.get('metadata', {})
                if 'fvg_type' in metadata or 'gap_size' in metadata:
                    filtered_drawings.append(drawing)
                    continue
            
            # For SMC drawings, check if it's SMC-related (has SMC-specific metadata)
            if 'smc' in drawing_types:
                metadata = drawing.get('metadata', {})
                logger.info(f"🔍 Checking SMC drawing: type={drawing_type}, metadata_keys={list(metadata.keys())}")
                
                # Check for any SMC-related metadata
                smc_metadata_found = False
                smc_indicators = ['smc_type', 'order_block_type', 'structure_type', 'equal_level_type', 'smc_fvg_type']
                
                for indicator in smc_indicators:
                    if indicator in metadata:
                        smc_metadata_found = True
                        logger.info(f"✅ SMC metadata found: {indicator}={metadata[indicator]}")
                        break
                
                # Also include regular FVGs and zones when SMC is requested (they're part of SMC analysis)
                if not smc_metadata_found:
                    # Include FVGs (they're part of SMC analysis)
                    if 'fvg_type' in metadata or 'gap_size' in metadata:
                        logger.info(f"✅ Including FVG as part of SMC analysis")
                        smc_metadata_found = True
                    # Include supply/demand zones (they're part of SMC analysis)  
                    elif 'base_candles' in metadata and drawing_type == 'LineToolRectangle':
                        logger.info(f"✅ Including supply/demand zone as part of SMC analysis")
                        smc_metadata_found = True
                
                if smc_metadata_found:
                    logger.info(f"✅ SMC drawing matched and added to filtered results")
                    filtered_drawings.append(drawing)
                    continue
                else:
                    logger.info(f"❌ SMC drawing did not match - no SMC metadata found")
                    logger.info(f"   Available metadata: {metadata}")
            
            # Also check for SMC drawings that might have different metadata structure
            if 'smc' in drawing_types:
                text = drawing.get('state', {}).get('text', '')
                # Check for SMC-specific text patterns
                smc_text_patterns = ['BOS', 'CHoCH', 'OB', 'Bull OB', 'Bear OB', 'Premium', 'Discount', 'EQ', 'EQH', 'EQL', 'FVG', 'SMC']
                if any(pattern in text for pattern in smc_text_patterns):
                    logger.info(f"✅ SMC drawing matched by text pattern: {text}")
                    filtered_drawings.append(drawing)
                    continue
            
            # For Liquidity Sweeps, check if it's a liquidity sweep (has liquidity-specific metadata)
            if 'liquidity_sweeps' in drawing_types:
                metadata = drawing.get('metadata', {})
                text = drawing.get('state', {}).get('text', '')
                
                # Check for liquidity sweep metadata
                liquidity_metadata_found = False
                liquidity_indicators = ['sweep_type', 'pivot_price', 'sweep_direction', 'sweep_kind']
                
                for indicator in liquidity_indicators:
                    if indicator in metadata:
                        liquidity_metadata_found = True
                        logger.info(f"✅ Liquidity sweep metadata found: {indicator}={metadata[indicator]}")
                        break
                
                # Also check for liquidity sweep text patterns
                if not liquidity_metadata_found:
                    liquidity_text_patterns = ['Bull Sweep', 'Bear Sweep', 'Liquidity', 'Sweep', 'wick', 'outbreak']
                    if any(pattern in text for pattern in liquidity_text_patterns):
                        logger.info(f"✅ Liquidity sweep matched by text pattern: {text}")
                        liquidity_metadata_found = True
                
                if liquidity_metadata_found:
                    logger.info(f"✅ Liquidity sweep drawing matched and added to filtered results")
                    filtered_drawings.append(drawing)
                    continue
                else:
                    logger.info(f"❌ Liquidity sweep drawing did not match - no liquidity metadata found")
            
            # For MACD drawings, check if it's a MACD-related drawing (has MACD-specific metadata)
            if 'macd' in drawing_types:
                metadata = drawing.get('metadata', {})
                text = drawing.get('state', {}).get('text', '')
                
                # Check for MACD metadata
                macd_metadata_found = False
                macd_indicators = ['macd_type', 'macd_value', 'signal_value', 'histogram_value', 'alert_type']
                
                for indicator in macd_indicators:
                    if indicator in metadata:
                        macd_metadata_found = True
                        logger.info(f"✅ MACD metadata found: {indicator}={metadata[indicator]}")
                        break
                
                # Also check for MACD text patterns
                if not macd_metadata_found:
                    macd_text_patterns = ['MACD', 'Signal', 'Histogram', 'F→R', 'R→F', 'Bullish Cross', 'Bearish Cross']
                    if any(pattern in text for pattern in macd_text_patterns):
                        logger.info(f"✅ MACD drawing matched by text pattern: {text}")
                        macd_metadata_found = True
                
                if macd_metadata_found:
                    logger.info(f"✅ MACD drawing matched and added to filtered results")
                    filtered_drawings.append(drawing)
                    continue
                else:
                    logger.info(f"❌ MACD drawing did not match - no MACD metadata found")
            
            # For patterns, check if it's a pattern note
            if 'candlestick_patterns' in drawing_types and drawing_type == 'LineToolNote':
                text = drawing.get('state', {}).get('text', '')
                if any(emoji in text for emoji in ['📈', '📉', '⚠️']) and 'RSI' not in text and 'MACD' not in text:
                    filtered_drawings.append(drawing)
                    continue
            
            # For RSI signals
            if 'rsi_signals' in drawing_types and drawing_type == 'LineToolNote':
                text = drawing.get('state', {}).get('text', '')
                if 'RSI' in text:
                    filtered_drawings.append(drawing)
                    continue
            
            # For MACD signals
            if 'macd_crossovers' in drawing_types and drawing_type == 'LineToolNote':
                text = drawing.get('state', {}).get('text', '')
                if 'MACD' in text:
                    filtered_drawings.append(drawing)
                    continue
            
            # For Bollinger Bands
            if 'bollinger_bands' in drawing_types and drawing_type == 'LineToolTrendLine':
                text = drawing.get('state', {}).get('text', '')
                if 'BB' in text or 'Bollinger' in text:
                    filtered_drawings.append(drawing)
                    continue
            
            # For key levels
            if 'key_levels' in drawing_types and drawing_type == 'LineToolHorzLine':
                filtered_drawings.append(drawing)
                continue
        
        result['drawings'] = filtered_drawings
        result['total_drawings'] = len(filtered_drawings)
        result['filtered'] = True
        result['filter_types'] = drawing_types
        
        logger.info(f"🔍 Filtered to {len(filtered_drawings)} drawings matching: {', '.join(drawing_types)}")
        
        # Special handling for SMC - if no SMC drawings found but SMC was requested, log detailed info
        if 'smc' in drawing_types and len(filtered_drawings) == 0:
            logger.warning(f"⚠️  SMC requested but 0 drawings found after filtering!")
            logger.warning(f"   Total drawings before filtering: {len(result.get('original_drawings', result.get('drawings', [])))}")
            
            # Count potential SMC drawings that might have been missed
            original_drawings = result.get('original_drawings', result.get('drawings', []))
            potential_smc = 0
            for drawing in original_drawings:
                metadata = drawing.get('metadata', {})
                text = drawing.get('state', {}).get('text', '')
                if (any(key in metadata for key in ['smc_type', 'order_block_type', 'structure_type', 'equal_level_type']) or
                    any(pattern in text for pattern in ['BOS', 'CHoCH', 'OB', 'Premium', 'Discount', 'EQ'])):
                    potential_smc += 1
            
            logger.warning(f"   Potential SMC drawings found: {potential_smc}")
            
            # If we found potential SMC drawings, add them as a fallback
            if potential_smc > 0:
                logger.info(f"🔧 Adding potential SMC drawings as fallback...")
                for drawing in original_drawings:
                    metadata = drawing.get('metadata', {})
                    text = drawing.get('state', {}).get('text', '')
                    if (any(key in metadata for key in ['smc_type', 'order_block_type', 'structure_type', 'equal_level_type']) or
                        any(pattern in text for pattern in ['BOS', 'CHoCH', 'OB', 'Premium', 'Discount', 'EQ'])):
                        filtered_drawings.append(drawing)
                
                result['drawings'] = filtered_drawings
                result['total_drawings'] = len(filtered_drawings)
                logger.info(f"✅ Added {len(filtered_drawings)} SMC drawings via fallback mechanism")
        
        return result


# Test function
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python chat_drawing_agent.py <SYMBOL> <USER_MESSAGE>")
        print('Example: python chat_drawing_agent.py ONGC "mark supply and demand zones"')
        sys.exit(1)
    
    symbol = sys.argv[1]
    user_message = sys.argv[2]
    
    agent = ChatDrawingAgent()
    
    result = agent.generate_from_chat(
        user_message=user_message,
        symbol=symbol,
        timeframe="1d",
        start_date="2025-01-01",
        end_date="2026-03-03",
        market="stock"
    )
    
    print(f"\n{'='*70}")
    print(f"Chat-Based Drawing Generation")
    print(f"{'='*70}\n")
    print(f"Symbol: {symbol}")
    print(f"User Message: {user_message}")
    print(f"\nResult:")
    print(f"  Total Drawings: {result.get('total_drawings', 0)}")
    print(f"  Drawing Types: {result.get('chat_metadata', {}).get('drawing_types_requested', [])}")
    print(f"  Confidence: {result.get('chat_metadata', {}).get('confidence', 0)}")
    
    if result.get('error'):
        print(f"\n❌ Error: {result['error']}")
    else:
        print(f"\n✅ Success!")
        
        # Save result
        output_file = f"chat_drawings_{symbol}.json"
        with open(output_file, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"📁 Saved to: {output_file}")
