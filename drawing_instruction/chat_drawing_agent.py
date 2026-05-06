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
1. supply_demand_zones - Supply and demand zones (BigBeluga: ATR-tall rectangles drawn from a high-volume 3-bar impulse, labelled with the impulse-leg volume delta and its share of total)
2. fvg - Fair Value Gaps (FVG) - 3-candle imbalance patterns
3. smc - Smart Money Concepts (BOS, CHoCH, Order Blocks, Equal Highs/Lows)
4. price_action - BigBeluga Price-Action / SMC: 5-bar swings, BOS/CHoCH structure, sweeps (x), and volumetric order blocks
5. order_block - wugamlo Order Block Finder: institutional OB = last opposite-colour candle before N consecutive trending candles
6. liquidity - LuxAlgo Liquidity Swings: pivot-high/low liquidity levels with per-zone touch count + accumulated volume
7. liquidity_sweeps - Liquidity Sweeps (wick sweeps and outbreak retests)
8. macd - MACD (Moving Average Convergence Divergence) indicator with signals
9. market_structure - Market Structure Breaks (MSB) with Order Blocks (OB) and Breaker/Mitigation Blocks (BB/MB)
10. candlestick_patterns - Candlestick patterns (doji, hammer, engulfing, etc.)
11. bollinger_bands - Bollinger Bands indicator
12. rsi_signals - RSI overbought/oversold signals
13. macd_crossovers - MACD bullish/bearish crossovers
14. key_levels - Support and resistance levels
15. all - All available analysis

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

User: "mark FVG on this stock" or "show fair value gaps" or "draw fvg order blocks" or "show imbalance zones"
Response: {"intent": "generate_drawings", "drawing_types": ["fvg"], "confidence": 0.98, "user_wants": "Fair Value Gaps (FVG) with order blocks"}

User: "mark SMC on this stock" or "show smart money concepts"
Response: {"intent": "generate_drawings", "drawing_types": ["smc"], "confidence": 0.98, "user_wants": "Smart Money Concepts (SMC) analysis"}

User: "mark liquidity on this stock" or "show liquidity sweeps"
Response: {"intent": "generate_drawings", "drawing_types": ["liquidity_sweeps"], "confidence": 0.98, "user_wants": "Liquidity Sweeps analysis"}

User: "mark MACD on this stock" or "show MACD indicator"
Response: {"intent": "generate_drawings", "drawing_types": ["macd"], "confidence": 0.98, "user_wants": "MACD indicator analysis"}

User: "mark market structure" or "show MSB and order blocks" or "draw market structure break"
Response: {"intent": "generate_drawings", "drawing_types": ["market_structure"], "confidence": 0.98, "user_wants": "Market Structure Breaks with Order / Breaker Blocks"}

User: "draw price action" or "show smart money concepts" or "mark BOS and CHoCH" or "draw volumetric order blocks"
Response: {"intent": "generate_drawings", "drawing_types": ["price_action"], "confidence": 0.98, "user_wants": "BigBeluga Price-Action / SMC — BOS, CHoCH, sweeps, and volumetric order blocks"}

User: "draw order blocks" or "mark order block" or "show institutional order blocks" or "find OB"
Response: {"intent": "generate_drawings", "drawing_types": ["order_block"], "confidence": 0.98, "user_wants": "Institutional Order Blocks (last opposite candle before a strong trend move)"}

User: "draw liquidity" or "show liquidity levels" or "mark liquidity zones" or "show liquidity swings"
Response: {"intent": "generate_drawings", "drawing_types": ["liquidity"], "confidence": 0.98, "user_wants": "LuxAlgo Liquidity Swings — pivot-high/low levels with touch-count and accumulated volume"}

User: "mark liquidity sweeps" or "show wick sweeps" or "draw outbreak retests"
Response: {"intent": "generate_drawings", "drawing_types": ["liquidity_sweeps"], "confidence": 0.98, "user_wants": "Liquidity Sweeps (wick-through / outbreak-retest markers)"}

User: "draw all the patterns and zones"
Response: {"intent": "generate_drawings", "drawing_types": ["supply_demand_zones", "candlestick_patterns", "market_structure"], "confidence": 0.95, "user_wants": "all zones, patterns and market structure"}

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
        
        # 'smc' keyword group — intentionally excludes bare "order block" /
        # "order blocks" so those phrases can route to the dedicated
        # `order_block` (wugamlo) drawing type below.
        if any(word in message_lower for word in ['smc', 'smart money', 'smart money concepts', 'bos', 'choch']):
            drawing_types.append('smc')

        # Order Block Finder (wugamlo) — triggered by "order block(s)" /
        # "institutional order block" / "OB finder". We add it whenever
        # the user mentions order blocks without specifying a richer
        # SMC / MSB context.
        if any(phrase in message_lower for phrase in [
            'order block', 'order blocks', 'orderblock', 'orderblocks',
            'institutional order block', 'institutional ob',
            'ob finder', 'order block finder',
            'find ob', 'find order block',
        ]):
            # Only add 'order_block' if the user hasn't already steered
            # toward a richer SMC/MSB context via other keywords.
            if 'market_structure' not in drawing_types:
                drawing_types.append('order_block')
        
        # liquidity_sweeps — explicit sweep / outbreak phrases only.
        # The bare word "liquidity" no longer maps here; it now routes
        # to the dedicated `liquidity` (LuxAlgo Swings) drawing type.
        if any(phrase in message_lower for phrase in [
            'liquidity sweep', 'liquidity sweeps',
            'wick sweep', 'outbreak', 'sweep', 'sweeps',
        ]):
            drawing_types.append('liquidity_sweeps')

        # liquidity (LuxAlgo Liquidity Swings) — pivot-based liquidity
        # levels/zones. Triggered by bare "liquidity" / "liquidity level(s)"
        # / "liquidity swing(s)" / "liquidity zone(s)" when the user is
        # NOT specifically asking for sweeps.
        if any(phrase in message_lower for phrase in [
            'liquidity', 'liquidity level', 'liquidity levels',
            'liquidity swing', 'liquidity swings',
            'liquidity zone', 'liquidity zones',
            'liquidity pool', 'liquidity pools',
        ]):
            if 'liquidity_sweeps' not in drawing_types:
                drawing_types.append('liquidity')
        
        if any(word in message_lower for word in ['macd', 'moving average convergence divergence', 'macd indicator', 'macd signals', 'macd crossover']):
            drawing_types.append('macd')

        if any(phrase in message_lower for phrase in [
            'market structure', 'msb', 'msb-ob', 'structure break', 'market structure break',
            'market-structure', 'break of structure', 'breaker block', 'mitigation block',
            'order block and', 'msb and ob', 'ob and bb', 'pine msb'
        ]):
            drawing_types.append('market_structure')

        # Price-Action / SMC (BigBeluga) — separate from the legacy `smc`
        # type. Triggered by explicit 'price action' mentions plus a handful
        # of BigBeluga-specific phrases. When the user says "smart money
        # concept(s)" we also include it alongside the legacy smc output
        # so they see the richer BOS/CHoCH/sweep/VOB visualisation.
        if any(phrase in message_lower for phrase in [
            'price action', 'price-action', 'priceaction',
            'volumetric order block', 'volumetric ob', 'volumetric orderblock',
            'bigbeluga', 'big beluga',
            'bos and choch', 'bos/choch', 'bos choch',
        ]):
            drawing_types.append('price_action')
        if ('smart money concept' in message_lower) or ('smart money concepts' in message_lower):
            if 'price_action' not in drawing_types:
                drawing_types.append('price_action')

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

        # If the user asked for both zones and patterns together, also include
        # market structure — MSB + OB/BB is the natural structural context for
        # pattern + zone analysis.
        if (
            'supply_demand_zones' in drawing_types
            and 'candlestick_patterns' in drawing_types
            and 'market_structure' not in drawing_types
        ):
            drawing_types.append('market_structure')

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
            
            # Resolve symbol — pass market so US/forex symbols skip .NS suffix
            resolved_symbol = resolve_symbol(symbol, market=market)
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

            # Step 3: Generate LLM-powered explanations for the returned drawings.
            # Only run when we actually have something to explain — saves a
            # round-trip when the filter produces zero matches.
            drawings_for_explain = result.get('drawings', [])
            if drawings_for_explain:
                try:
                    logger.info(
                        f"🧠 Generating explanations for "
                        f"{len(drawings_for_explain)} drawings..."
                    )
                    result['explanations'] = self._generate_explanations(
                        user_message=user_message,
                        symbol=resolved_symbol,
                        drawing_types=intent['drawing_types'],
                        drawings=drawings_for_explain,
                        candles=result.get('candles'),
                    )
                except Exception as ex_err:
                    logger.error(f"⚠️  Explanation generation failed: {ex_err}")
                    result['explanations'] = {
                        'summary': '',
                        'drawings': [],     
                        'error': str(ex_err),
                    }
            else:
                logger.info("ℹ️  No drawings to explain — skipping explanation step")
                result['explanations'] = {
                    'summary': (
                        f"No {', '.join(intent['drawing_types'])} detected for "
                        f"{resolved_symbol} in the requested window."
                    ),
                    'drawings': [],
                }

            # Step 4: Render the structured explanations into a chat-ready
            # markdown string. This becomes the `message` returned to the
            # user — they read it directly in the chat UI, so it must
            # stand on its own without referencing the JSON payload.
            result['message'] = self._format_explanations_message(
                explanations=result['explanations'],
                symbol=resolved_symbol,
                total_drawings=result.get('total_drawings', 0),
                drawing_types=intent['drawing_types'],
            )

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
            'liquidity': ['LineToolRectangle', 'LineToolTrendLine'],                         # LuxAlgo Liquidity Swings: level line + zone box
            'macd': ['LineToolTrendLine', 'LineToolNote', 'LineToolHorzLine'],  # MACD uses trend lines, notes, and horizontal lines
            'market_structure': ['LineToolRectangle', 'LineToolTrendLine', 'LineToolNote'],  # MSB line + label + OB/BB boxes
            'price_action': ['LineToolRectangle', 'LineToolTrendLine', 'LineToolNote'],      # BOS/CHoCH + volumetric OBs + mid-lines
            'order_block': ['LineToolRectangle', 'LineToolTrendLine'],                       # wugamlo OB rect + mid-line
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
                metadata = drawing.get('metadata', {})
                # Match either:
                #   - BigBeluga SDZ indicator output (sdz_type metadata), or
                #   - LLM-generated zones (base_candles metadata).
                if metadata.get('sdz_type') in ('supply_zone', 'demand_zone'):
                    filtered_drawings.append(drawing)
                    continue
                if 'base_candles' in metadata:
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
                metadata = drawing.get('metadata', {})
                text = drawing.get('state', {}).get('text', '')
                # Skip drawings that already belong to a different dedicated
                # indicator bucket — otherwise the generic "OB" / "BOS" text
                # pattern here would swallow wugamlo OB-finder and BigBeluga
                # price-action drawings into the SMC bucket.
                _is_other_bucket = any(
                    k in metadata for k in (
                        'ob_finder_type',
                        'price_action_type',
                        'market_structure_type',
                        'fvg_ob_type',
                        'liquidity_type',
                        'sdz_type',
                    )
                )
                if not _is_other_bucket:
                    # Check for SMC-specific text patterns
                    smc_text_patterns = ['BOS', 'CHoCH', 'OB', 'Bull OB', 'Bear OB', 'Premium', 'Discount', 'EQ', 'EQH', 'EQL', 'FVG', 'SMC']
                    if any(pattern in text for pattern in smc_text_patterns):
                        logger.info(f"✅ SMC drawing matched by text pattern: {text}")
                        filtered_drawings.append(drawing)
                        continue
            
            # For Liquidity Swings (LuxAlgo) — dedicated drawings bucket
            if 'liquidity' in drawing_types:
                metadata = drawing.get('metadata', {})
                liq_types = {'level_line', 'zone_box'}
                if metadata.get('liquidity_type') in liq_types:
                    logger.info(f"✅ Liquidity-swings drawing matched by metadata: {metadata.get('liquidity_type')}")
                    filtered_drawings.append(drawing)
                    continue

            # For Liquidity Sweeps, check if it's a liquidity sweep (has liquidity-specific metadata)
            if 'liquidity_sweeps' in drawing_types:
                metadata = drawing.get('metadata', {})
                text = drawing.get('state', {}).get('text', '')

                # Guard: skip drawings that already belong to the LuxAlgo
                # Liquidity Swings bucket (they also carry a `pivot_price`
                # metadata key, which would otherwise match the sweep
                # filter below and pollute the output).
                liquidity_metadata_found = False
                if 'liquidity_type' in metadata:
                    pass  # handled by the dedicated `liquidity` branch above
                else:
                    # Check for liquidity sweep metadata
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
            
            # For Order Block Finder (wugamlo) drawings
            if 'order_block' in drawing_types:
                metadata = drawing.get('metadata', {})
                text = drawing.get('state', {}).get('text', '')

                obf_types = {'order_block', 'ob_avg_line'}
                obf_matched = False
                if metadata.get('ob_finder_type') in obf_types:
                    obf_matched = True
                    logger.info(f"✅ OB-Finder drawing matched by metadata: {metadata.get('ob_finder_type')}")
                elif any(tag in text for tag in ['Bull OB ·', 'Bear OB ·']):
                    obf_matched = True
                    logger.info(f"✅ OB-Finder drawing matched by text: {text}")

                if obf_matched:
                    filtered_drawings.append(drawing)
                    continue

            # For Price-Action / SMC (BigBeluga) drawings
            if 'price_action' in drawing_types:
                metadata = drawing.get('metadata', {})
                text = drawing.get('state', {}).get('text', '')

                pa_types = {'structure_line', 'structure_label', 'volumetric_ob', 'ob_midline'}
                pa_matched = False
                if metadata.get('price_action_type') in pa_types:
                    pa_matched = True
                    logger.info(f"✅ Price-Action drawing matched by metadata: {metadata.get('price_action_type')}")
                elif any(tag == text for tag in ['BOS', 'CHoCH', 'x']):
                    pa_matched = True
                    logger.info(f"✅ Price-Action drawing matched by text: {text}")

                if pa_matched:
                    filtered_drawings.append(drawing)
                    continue

            # For Market Structure drawings, match by dedicated metadata key or known tags
            if 'market_structure' in drawing_types:
                metadata = drawing.get('metadata', {})
                text = drawing.get('state', {}).get('text', '')

                ms_types = {'zigzag', 'msb_line', 'msb_label', 'order_block', 'breaker_block'}
                ms_matched = False
                if metadata.get('market_structure_type') in ms_types:
                    ms_matched = True
                    logger.info(f"✅ Market Structure drawing matched by metadata: {metadata.get('market_structure_type')}")
                elif any(tag in text for tag in ['MSB', 'Bu-OB', 'Be-OB', 'Bu-BB', 'Be-BB', 'Bu-MB', 'Be-MB']):
                    ms_matched = True
                    logger.info(f"✅ Market Structure drawing matched by text: {text}")

                if ms_matched:
                    filtered_drawings.append(drawing)
                    continue

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

            # Skip drawings that already belong to a dedicated bucket —
            # otherwise the "OB" text pattern below pulls wugamlo OB-finder
            # and BigBeluga price-action / FVG-OB drawings into SMC.
            _other_bucket_keys = (
                'ob_finder_type',
                'price_action_type',
                'market_structure_type',
                'fvg_ob_type',
                'liquidity_type',
                'sdz_type',
            )

            # Count potential SMC drawings that might have been missed
            original_drawings = result.get('original_drawings', result.get('drawings', []))
            potential_smc = 0
            for drawing in original_drawings:
                metadata = drawing.get('metadata', {})
                if any(k in metadata for k in _other_bucket_keys):
                    continue
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
                    if any(k in metadata for k in _other_bucket_keys):
                        continue
                    text = drawing.get('state', {}).get('text', '')
                    if (any(key in metadata for key in ['smc_type', 'order_block_type', 'structure_type', 'equal_level_type']) or
                        any(pattern in text for pattern in ['BOS', 'CHoCH', 'OB', 'Premium', 'Discount', 'EQ'])):
                        filtered_drawings.append(drawing)

                result['drawings'] = filtered_drawings
                result['total_drawings'] = len(filtered_drawings)
                logger.info(f"✅ Added {len(filtered_drawings)} SMC drawings via fallback mechanism")

        return result

    # ------------------------------------------------------------------
    #  LLM-powered explanations for the returned drawings
    # ------------------------------------------------------------------
    def _summarise_drawing_for_llm(self, drawing: Dict) -> Dict:
        """Extract the human-relevant fields from a drawing for the LLM.

        We can't send the whole TradingView drawing JSON — most of it
        (IDs, linkKeys, intervalsVisibilities, …) is noise. Pull the
        bits that describe *what* the marking represents and *where*
        it sits, then let the LLM reason over that compact view.
        """
        metadata = drawing.get('metadata', {}) or {}
        state = drawing.get('state', {}) or {}
        points = drawing.get('points', []) or []

        # Prefer the richest label — many builders set it on `text`.
        label = state.get('text', '')

        prices = [p.get('price') for p in points if isinstance(p, dict)]
        times = [p.get('time_t') for p in points if isinstance(p, dict)]

        # Derive a single "category" the LLM can group on — preferring
        # the most specific metadata key each indicator sets.
        category = (
            metadata.get('sdz_type')
            or metadata.get('fvg_ob_type')
            or metadata.get('price_action_type')
            or metadata.get('ob_finder_type')
            or metadata.get('liquidity_type')
            or metadata.get('market_structure_type')
            or metadata.get('smc_type')
            or metadata.get('macd_type')
            or metadata.get('fvg_type')
            or drawing.get('type')
        )

        return {
            'id': drawing.get('id'),
            'category': category,
            'tool': drawing.get('type'),
            'label': label,
            'prices': prices,
            'timestamps': times,
            # Pass through the richest reason-style metadata the builders
            # already produce — avoids the LLM hallucinating numbers.
            'reason': metadata.get('full_reason'),
            # Hand-picked numeric fields that commonly matter. Unknown
            # keys are skipped; we favour signal over completeness so the
            # LLM isn't flooded with internal bookkeeping.
            'stats': {
                k: metadata[k] for k in (
                    'sdz_delta', 'sdz_share_pct', 'sdz_atr',
                    'gap_percentage', 'gap_size', 'atr',
                    'ob_volume', 'ob_volume_share_pct',
                    'confidence',
                    'invalidated', 'mitigated',
                    'base_candles', 'impulse_candles',
                    'impulse_strength', 'wick_ratio',
                )
                if k in metadata
            },
        }

    def _generate_explanations(
        self,
        user_message: str,
        symbol: str,
        drawing_types: List[str],
        drawings: List[Dict],
        candles: Optional[List[Dict]] = None,
    ) -> Dict:
        """Call the LLM to produce a structured explanation of the
        drawings that were just generated.

        The returned dict has this shape:
            {
              "summary":      "<1–3 sentence headline>",
              "context":      "<market context — recent trend, price action>",
              "drawings":     [ {id, category, title, why, how_to_trade}, ... ],
              "key_levels":   [ "<e.g. $95–97 (supply)>", ... ],
              "trading_insights": "<actionable synthesis>",
              "disclaimer":   "<standard not-advice note>"
            }

        We ask the LLM for strict JSON and fall back to a deterministic
        template if parsing fails so the API never returns an empty
        `explanations` field when drawings are present.
        """
        # Compact the drawings for the prompt — one dict per drawing,
        # keyed on the bits the LLM actually needs to reason with.
        summaries = [self._summarise_drawing_for_llm(d) for d in drawings]

        # Last close is useful context for "how to trade" reasoning.
        last_close = None
        last_date = None
        if candles:
            try:
                last_close = float(candles[-1].get('close'))
                last_date = candles[-1].get('date')
            except Exception:
                pass

        system_prompt = (
            "You are a senior technical analyst explaining chart drawings to a trader. "
            "For each drawing the user's chart is about to display, explain in plain English "
            "WHY that zone / pattern / level was marked where it is, what it implies about "
            "supply/demand or momentum, and how a trader might act on it. Be concrete: "
            "reference price levels from the data, not generic advice.\n\n"
            "IMPORTANT RULES:\n"
            "  • Base every claim on the numeric fields in the input — do NOT invent prices, "
            "dates, or volume figures.\n"
            "  • If a drawing is marked invalidated or mitigated, call that out and adjust "
            "the trading insight accordingly.\n"
            "  • Keep each drawing explanation to 2–4 sentences.\n"
            "  • End with a standard not-financial-advice disclaimer.\n"
            "Return ONLY valid JSON matching this schema — no prose, no markdown, no code fences:\n"
            "{\n"
            '  "summary": "1-3 sentence headline of what was detected and the overall bias",\n'
            '  "context": "what is the stock doing recently (trend, momentum)",\n'
            '  "drawings": [\n'
            '    {\n'
            '      "id": "<drawing.id from input>",\n'
            '      "category": "<drawing.category from input>",\n'
            '      "title": "short human title, e.g. \'Active Supply Zone 95-97\'",\n'
            '      "why":   "why this zone/pattern was detected here",\n'
            '      "how_to_trade": "what a trader should watch for around this level"\n'
            '    }\n'
            '  ],\n'
            '  "key_levels": ["<level> (<type>)", ...],\n'
            '  "trading_insights": "1-3 sentence synthesis across all drawings",\n'
            '  "disclaimer": "standard disclaimer"\n'
            "}"
        )

        user_payload = {
            'symbol': symbol,
            'user_message': user_message,
            'requested_drawing_types': drawing_types,
            'last_close': last_close,
            'last_bar_date': last_date,
            'drawings': summaries,
        }

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': json.dumps(user_payload, default=str)},
                ],
                temperature=0.4,
                max_tokens=1800,
            )
            raw = response.choices[0].message.content.strip()
            # Strip fenced blocks defensively — some models ignore the
            # "no code fences" rule when the payload is long.
            if raw.startswith('```'):
                raw = raw.strip('`')
                if raw.lower().startswith('json'):
                    raw = raw[4:].lstrip()

            explanations = json.loads(raw)

            # Guarantee the schema keys exist so downstream consumers
            # (FastAPI, UI) don't have to defensively null-check.
            explanations.setdefault('summary', '')
            explanations.setdefault('context', '')
            explanations.setdefault('drawings', [])
            explanations.setdefault('key_levels', [])
            explanations.setdefault('trading_insights', '')
            explanations.setdefault(
                'disclaimer',
                'This analysis is for educational purposes only and does not '
                'constitute financial advice.',
            )
            explanations['generated_by'] = self.model

            logger.info(
                f"✅ Explanations: summary={len(explanations.get('summary', ''))} chars, "
                f"per-drawing={len(explanations.get('drawings', []))}"
            )
            return explanations

        except json.JSONDecodeError as e:
            logger.error(f"Explanation JSON parse failed: {e}")
            logger.error(f"LLM raw response: {raw[:500] if 'raw' in locals() else '(no response)'}")
            return self._fallback_explanations(drawings, drawing_types, symbol)
        except Exception as e:
            logger.error(f"Explanation LLM call failed: {e}")
            return self._fallback_explanations(drawings, drawing_types, symbol)

    def _format_explanations_message(
        self,
        explanations: Dict,
        symbol: str,
        total_drawings: int,
        drawing_types: List[str],
    ) -> str:
        """Render the structured `explanations` dict as a chat-ready markdown
        message. The result lives in `result['message']` so the FastAPI
        endpoint can return it verbatim — the user reads this string
        directly in the chat UI.

        Falls back gracefully when individual fields are missing so a
        partial LLM response still produces a usable message.
        """
        if not explanations:
            return (
                f"Generated {total_drawings} drawings on {symbol} for "
                f"{', '.join(drawing_types) or 'requested types'}."
            )

        parts: List[str] = []

        summary = (explanations.get('summary') or '').strip()
        if summary:
            parts.append(f"**{summary}**")

        context = (explanations.get('context') or '').strip()
        if context:
            parts.append(f"📊 **Context:** {context}")

        key_levels = explanations.get('key_levels') or []
        if key_levels:
            level_lines = '\n'.join(f"• {lvl}" for lvl in key_levels)
            parts.append(f"🎯 **Key Levels:**\n{level_lines}")

        per_drawing = explanations.get('drawings') or []
        if per_drawing:
            drawing_blocks: List[str] = []
            for i, d in enumerate(per_drawing, start=1):
                title = (d.get('title') or d.get('category') or 'Drawing').strip()
                category = (d.get('category') or '').strip()
                why = (d.get('why') or '').strip()
                how = (d.get('how_to_trade') or '').strip()

                header = f"**{i}. {title}**"
                if category and category not in title:
                    header += f"  _({category})_"
                lines = [header]
                if why:
                    lines.append(f"_Why:_ {why}")
                if how:
                    lines.append(f"_Trade:_ {how}")
                drawing_blocks.append('\n'.join(lines))
            parts.append("🔍 **Detected Drawings:**\n\n" + "\n\n".join(drawing_blocks))

        insights = (explanations.get('trading_insights') or '').strip()
        if insights:
            parts.append(f"💡 **Trading Insights:** {insights}")

        disclaimer = (explanations.get('disclaimer') or '').strip()
        if disclaimer:
            parts.append(f"⚠️ _{disclaimer}_")

        if not parts:
            return (
                f"Generated {total_drawings} drawings on {symbol} for "
                f"{', '.join(drawing_types) or 'requested types'}."
            )

        return "\n\n".join(parts)

    def _fallback_explanations(
        self,
        drawings: List[Dict],
        drawing_types: List[str],
        symbol: str,
    ) -> Dict:
        """Deterministic explanation scaffold used when the LLM call fails.

        Pulls directly from the `full_reason` metadata each builder
        already writes, so the output is still grounded in the actual
        drawing data — just less polished than the LLM version.
        """
        per_drawing = []
        key_levels: List[str] = []
        for d in drawings:
            summary = self._summarise_drawing_for_llm(d)
            label = summary.get('label') or summary.get('category') or 'Drawing'
            reason = summary.get('reason') or 'Detected by the indicator pipeline.'
            per_drawing.append({
                'id': summary.get('id'),
                'category': summary.get('category'),
                'title': str(label)[:80],
                'why': str(reason),
                'how_to_trade': (
                    'Watch price reaction at this level; confirm with volume and '
                    'lower-timeframe structure before acting.'
                ),
            })
            prices = [p for p in (summary.get('prices') or []) if isinstance(p, (int, float))]
            if prices:
                lo, hi = min(prices), max(prices)
                if abs(hi - lo) > 1e-9:
                    key_levels.append(f"{lo:.2f}–{hi:.2f} ({summary.get('category')})")
                else:
                    key_levels.append(f"{lo:.2f} ({summary.get('category')})")

        return {
            'summary': (
                f"Generated {len(drawings)} {', '.join(drawing_types)} "
                f"markings on {symbol}."
            ),
            'context': (
                'LLM explanation unavailable — showing deterministic summary '
                'pulled from each drawing\'s metadata.'
            ),
            'drawings': per_drawing,
            'key_levels': key_levels,
            'trading_insights': (
                'Review each marked level on the chart; align with your existing '
                'risk rules before taking a position.'
            ),
            'disclaimer': (
                'This analysis is for educational purposes only and does not '
                'constitute financial advice.'
            ),
            'generated_by': 'fallback_template',
        }


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
