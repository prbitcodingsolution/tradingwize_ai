"""
FastAPI Backend for Chat-Based Drawing Instruction Generation
Endpoint: POST /api/v1/drawing/chat/

This API accepts natural language chat messages and generates appropriate
TradingView drawing instructions using AI-powered intent understanding.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime
import logging
import sys
import os

# Add drawing_instruction to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'drawing_instruction'))

from drawing_instruction.chat_drawing_agent import ChatDrawingAgent

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Chat Drawing Instruction API",
    description="Generate TradingView drawing instructions using natural language chat",
    version="2.0.0"
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize chat agent (singleton)
chat_agent = None

def get_chat_agent():
    """Get or create chat agent instance"""
    global chat_agent
    if chat_agent is None:
        logger.info("🤖 Initializing ChatDrawingAgent...")
        chat_agent = ChatDrawingAgent()
        logger.info("✅ ChatDrawingAgent initialized")
    return chat_agent


# Request Model
class ChatDrawingRequest(BaseModel):
    """Request model for chat-based drawing generation"""
    
    message: str = Field(
        ...,
        description="Natural language message describing what drawings you want",
        example="mark supply and demand zones on this stock"
    )
    symbol: str = Field(
        ...,
        description="Stock symbol (e.g., ONGC, RELIANCE, TCS)",
        example="ONGC"
    )
    start_date: str = Field(
        ...,
        description="Start date in DD-MM-YYYY format",
        example="01-01-2025"
    )
    end_date: str = Field(
        ...,
        description="End date in DD-MM-YYYY format",
        example="31-12-2025"
    )
    market: str = Field(
        default="stock",
        description="Market type (stock, forex, crypto)",
        example="stock"
    )
    timeframe: str = Field(
        default="1d",
        description="Chart timeframe (1m, 5m, 15m, 1h, 1d, 1wk, 1mo)",
        example="1d"
    )
    
    @validator('message')
    def validate_message(cls, v):
        """Validate message"""
        if not v or not v.strip():
            raise ValueError("Message cannot be empty")
        if len(v) > 500:
            raise ValueError("Message too long (max 500 characters)")
        return v.strip()
    
    @validator('symbol')
    def validate_symbol(cls, v):
        """Validate and clean symbol"""
        if not v or not v.strip():
            raise ValueError("Symbol cannot be empty")
        return v.strip().upper()
    
    @validator('start_date', 'end_date')
    def validate_date_format(cls, v):
        """Validate date format DD-MM-YYYY"""
        try:
            datetime.strptime(v, '%d-%m-%Y')
            return v
        except ValueError:
            raise ValueError(f"Date must be in DD-MM-YYYY format, got: {v}")
    
    @validator('timeframe')
    def validate_timeframe(cls, v):
        """Validate timeframe"""
        valid_timeframes = ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1wk', '1mo']
        if v not in valid_timeframes:
            raise ValueError(f"Invalid timeframe. Must be one of: {', '.join(valid_timeframes)}")
        return v
    
    @validator('market')
    def validate_market(cls, v):
        """Validate market type"""
        valid_markets = ['stock', 'nasdaq', 'nyse', 'us', 'forex', 'crypto']
        v_lower = v.lower()
        if v_lower not in valid_markets:
            raise ValueError(f"Invalid market. Must be one of: {', '.join(valid_markets)}")
        return v_lower


# Response Model
class ChatDrawingResponse(BaseModel):
    """Response model for chat-based drawing generation"""
    
    success: bool = Field(description="Whether the request was successful")
    symbol: str = Field(description="Stock symbol processed")
    resolved_symbol: str = Field(description="Resolved symbol with exchange suffix")
    timeframe: str = Field(description="Chart timeframe")
    start_date: str = Field(description="Start date")
    end_date: str = Field(description="End date")
    market: str = Field(description="Market type")
    user_message: str = Field(description="Original user message")
    parsed_intent: dict = Field(description="Parsed user intent from LLM")
    drawing_types_generated: List[str] = Field(description="Types of drawings generated")
    total_drawings: int = Field(description="Total number of drawings generated")
    drawings: List[dict] = Field(description="Array of drawing instructions")
    explanations: dict = Field(
        default_factory=dict,
        description=(
            "LLM-powered explanations of the returned drawings — "
            "includes a summary, per-drawing rationale, key levels, "
            "and actionable trading insights."
        ),
    )
    metadata: dict = Field(description="Additional metadata about the analysis")
    message: Optional[str] = Field(None, description="Success or error message")


class ErrorResponse(BaseModel):
    """Error response model"""
    success: bool = False
    error: str = Field(description="Error message")
    details: Optional[str] = Field(None, description="Detailed error information")


def convert_date_format(date_str: str) -> str:
    """Convert date from DD-MM-YYYY to YYYY-MM-DD format"""
    try:
        dt = datetime.strptime(date_str, '%d-%m-%Y')
        return dt.strftime('%Y-%m-%d')
    except Exception as e:
        logger.error(f"Date conversion error: {e}")
        raise ValueError(f"Invalid date format: {date_str}")


@app.get("/")
async def root():
    """Root endpoint - API information"""
    return {
        "name": "Chat Drawing Instruction API",
        "version": "2.0.0",
        "status": "active",
        "description": "Generate drawing instructions using natural language chat",
        "endpoints": {
            "chat_generate": "POST /api/v1/drawing/chat/",
            "health_check": "GET /health",
            "examples": "GET /api/v1/drawing/chat/examples"
        },
        "documentation": "/docs"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "chat-drawing-api",
        "agent_initialized": chat_agent is not None
    }


@app.get("/api/v1/drawing/chat/examples")
async def get_examples():
    """Get example chat messages and their expected outputs"""
    return {
        "examples": [
            {
                "message": "mark supply and demand zones on this stock",
                "description": "Generates BigBeluga Supply/Demand Zones — ATR-tall boxes anchored at high-volume 3-bar impulses, labelled with impulse-leg volume delta and its share of total",
                "drawing_types": ["supply_demand_zones"]
            },
            {
                "message": "show me candlestick patterns",
                "description": "Generates candlestick pattern markers",
                "drawing_types": ["candlestick_patterns"]
            },
            {
                "message": "add RSI and MACD indicators",
                "description": "Generates RSI overbought/oversold and MACD crossover signals",
                "drawing_types": ["rsi_signals", "macd_crossovers"]
            },
            {
                "message": "show support and resistance levels",
                "description": "Generates key support and resistance horizontal lines",
                "drawing_types": ["key_levels"]
            },
            {
                "message": "mark SMC on this stock",
                "description": "Generates Smart Money Concepts (BOS, CHoCH, Order Blocks, Equal Highs/Lows)",
                "drawing_types": ["smc"]
            },
            {
                "message": "mark market structure on this stock",
                "description": "Generates Market Structure Breaks (MSB) with Order Blocks (OB) and Breaker/Mitigation Blocks (BB/MB)",
                "drawing_types": ["market_structure"]
            },
            {
                "message": "draw price action on this stock",
                "description": "Generates BigBeluga Price-Action / SMC: 5-bar swing BOS & CHoCH structure lines, sweeps (x), and volumetric order blocks",
                "drawing_types": ["price_action"]
            },
            {
                "message": "draw order blocks on this stock",
                "description": "Generates wugamlo Order Block Finder zones: institutional OB = last opposite-colour candle before N consecutive trending candles",
                "drawing_types": ["order_block"]
            },
            {
                "message": "draw liquidity on this stock",
                "description": "Generates LuxAlgo Liquidity Swings: pivot-high/low liquidity levels with per-zone touch count and accumulated volume",
                "drawing_types": ["liquidity"]
            },
            {
                "message": "show smart money concepts",
                "description": "Generates the legacy SMC output PLUS the BigBeluga Price-Action BOS/CHoCH/VOB visualisation",
                "drawing_types": ["smc", "price_action"]
            },
            {
                "message": "draw all the patterns and zones",
                "description": "Generates supply/demand zones, candlestick patterns and market structure together",
                "drawing_types": ["supply_demand_zones", "candlestick_patterns", "market_structure"]
            },
            {
                "message": "show fair value gaps (FVG)",
                "description": "Generates Fair Value Gap rectangles plus ATR-wide order-block zones (BigBeluga FVG-OB)",
                "drawing_types": ["fvg"]
            },
            {
                "message": "draw fvg order blocks",
                "description": "Same as above — 3-candle imbalance gap + ATR-wide OB zone per gap",
                "drawing_types": ["fvg"]
            },
            {
                "message": "add bollinger bands",
                "description": "Generates Bollinger Bands indicator lines",
                "drawing_types": ["bollinger_bands"]
            },
            {
                "message": "analyze this chart with everything",
                "description": "Generates all available technical analysis drawings",
                "drawing_types": ["all"]
            },
            {
                "message": "show me zones and patterns",
                "description": "Generates both supply/demand zones and candlestick patterns",
                "drawing_types": ["supply_demand_zones", "candlestick_patterns"]
            }
        ],
        "available_drawing_types": [
            "supply_demand_zones",
            "fvg",
            "smc",
            "price_action",
            "order_block",
            "liquidity",
            "market_structure",
            "candlestick_patterns",
            "bollinger_bands",
            "rsi_signals",
            "macd",
            "macd_crossovers",
            "key_levels",
            "liquidity_sweeps",
            "all"
        ]
    }


@app.post(
    "/api/v1/drawing/chat/",
    response_model=ChatDrawingResponse,
    responses={
        200: {"description": "Successfully generated drawing instructions from chat"},
        400: {"model": ErrorResponse, "description": "Invalid request parameters"},
        500: {"model": ErrorResponse, "description": "Internal server error"}
    }
)
async def generate_from_chat(request: ChatDrawingRequest):
    """
    Generate TradingView drawing instructions from natural language chat
    
    This endpoint:
    1. Accepts a natural language message describing what drawings the user wants
    2. Uses LLM to understand the user's intent
    3. Fetches historical price data from external API
    4. Performs AI-powered technical analysis
    5. Generates only the requested drawing types
    6. Returns JSON compatible with TradingView
    
    Example messages:
    - "mark supply and demand zones on this stock"
    - "show me candlestick patterns"
    - "add RSI and MACD indicators"
    - "show support and resistance levels"
    - "analyze this chart with everything"
    
    Args:
        request: ChatDrawingRequest with message, symbol, dates, market, and timeframe
        
    Returns:
        ChatDrawingResponse with drawing instructions and metadata
        
    Raises:
        HTTPException: If validation fails or generation errors occur
    """
    
    logger.info(f"📥 Chat request: '{request.message}' for {request.symbol}")
    logger.info(f"   Date range: {request.start_date} to {request.end_date}")
    logger.info(f"   Timeframe: {request.timeframe} | Market: {request.market}")
    
    try:
        # Get chat agent
        agent = get_chat_agent()
        
        # Convert date format
        start_date_converted = convert_date_format(request.start_date)
        end_date_converted = convert_date_format(request.end_date)
        
        logger.info(f"📅 Dates converted: {start_date_converted} to {end_date_converted}")
        
        # Generate drawings from chat
        logger.info(f"🤖 Processing chat message with LLM...")
        
        result = agent.generate_from_chat(
            user_message=request.message,
            symbol=request.symbol,
            timeframe=request.timeframe,
            start_date=start_date_converted,
            end_date=end_date_converted,
            market=request.market
        )
        
        # Check for errors
        if result.get('error'):
            raise ValueError(result['error'])
        
        # Extract chat metadata
        chat_metadata = result.get('chat_metadata', {})
        parsed_intent = chat_metadata.get('parsed_intent', {})
        
        logger.info(f"✅ Generated {result.get('total_drawings', 0)} drawings")
        logger.info(f"   Drawing types: {parsed_intent.get('drawing_types', [])}")
        logger.info(f"   Confidence: {parsed_intent.get('confidence', 0)}")
        
        # Prepare response
        response = ChatDrawingResponse(
            success=True,
            symbol=request.symbol,
            resolved_symbol=result.get('symbol', request.symbol),
            timeframe=request.timeframe,
            start_date=request.start_date,
            end_date=request.end_date,
            market=request.market,
            user_message=request.message,
            parsed_intent=parsed_intent,
            drawing_types_generated=parsed_intent.get('drawing_types', []),
            total_drawings=result.get('total_drawings', 0),
            drawings=result.get('drawings', []),
            explanations=result.get('explanations', {}),
            metadata={
                "generated_at": datetime.now().isoformat(),
                "data_source": "external_api",
                "analysis_type": "chat_based_llm",
                "candles_analyzed": result.get('total_candles', 0),
                "date_range": {
                    "start": start_date_converted,
                    "end": end_date_converted
                },
                "intent_confidence": parsed_intent.get('confidence', 0),
                "user_wants": parsed_intent.get('user_wants', ''),
                "filtered": result.get('filtered', False)
            },
            # Prefer the agent's chat-ready explanation summary as the
            # `message` so the user sees real analysis in the chat. Fall
            # back to a generic line if the agent didn't produce one
            # (e.g. when the explanation pipeline was skipped entirely).
            message=result.get('message') or (
                f"Successfully generated {result.get('total_drawings', 0)} "
                f"drawings based on your request"
            )
        )
        
        logger.info(f"📤 Sending response with {response.total_drawings} drawings")
        return response
        
    except ValueError as ve:
        logger.error(f"❌ Validation error: {ve}")
        
        # Check if it's a token error
        error_msg = str(ve)
        if "401" in error_msg or "token" in error_msg.lower() or "expired" in error_msg.lower():
            logger.error("\n" + "="*70)
            logger.error("🔐 API AUTHENTICATION ERROR - TOKEN EXPIRED")
            logger.error("="*70)
            logger.error("\n📋 How to fix:")
            logger.error("   1. Login to your API at: http://192.168.0.126:8000")
            logger.error("   2. Get a new access token")
            logger.error("   3. Update .env file:")
            logger.error("      API_BEARER_TOKEN=your_new_token_here")
            logger.error("   4. Restart this API server")
            logger.error("\n" + "="*70 + "\n")
            
            raise HTTPException(
                status_code=401,
                detail={
                    "success": False,
                    "error": "API Authentication Error - Token Expired",
                    "details": str(ve),
                    "fix_instructions": {
                        "step_1": "Login to your API at http://192.168.0.126:8000",
                        "step_2": "Get a new access token from the authentication endpoint",
                        "step_3": "Update API_BEARER_TOKEN in your .env file with the new token",
                        "step_4": "Restart the API server (python api_chat_drawing.py)"
                    },
                    "current_token_status": "expired",
                    "api_endpoint": os.getenv("API_BASE_URL", "http://192.168.0.126:8000")
                }
            )
        
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": "Validation Error",
                "details": str(ve)
            }
        )
        
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": "Internal Server Error",
                "details": str(e)
            }
        )


@app.get("/api/v1/drawing/chat/test")
async def test_chat_endpoint():
    """Test endpoint with sample request/response"""
    return {
        "success": True,
        "message": "Chat Drawing API is working",
        "sample_request": {
            "message": "mark supply and demand zones on this stock",
            "symbol": "ONGC",
            "start_date": "01-01-2025",
            "end_date": "31-12-2025",
            "market": "stock",
            "timeframe": "1d"
        },
        "sample_response": {
            "success": True,
            "symbol": "ONGC",
            "resolved_symbol": "ONGC.NS",
            "user_message": "mark supply and demand zones on this stock",
            "parsed_intent": {
                "intent": "generate_drawings",
                "drawing_types": ["supply_demand_zones"],
                "confidence": 0.98,
                "user_wants": "supply and demand zones"
            },
            "drawing_types_generated": ["supply_demand_zones"],
            "total_drawings": 5,
            "drawings": [
                {
                    "type": "LineToolRectangle",
                    "state": {
                        "text": "Supply: -1.66M | 5%",
                        "backgroundColor": "rgba(255, 152, 0, 0.18)"
                    },
                    "metadata": {
                        "sdz_type": "supply_zone",
                        "sdz_direction": "supply",
                        "sdz_delta": -1660000.0,
                        "sdz_share_pct": 5.0
                    }
                }
            ],
            "explanations": {
                "summary": "Detected 3 active supply zones above current price and 2 demand zones below — bias is mildly bearish.",
                "context": "Stock has been in a corrective down-leg for the past 8 sessions after failing to break 105.",
                "drawings": [
                    {
                        "id": "Ab3c9Z",
                        "category": "supply_zone",
                        "title": "Active Supply 96–99",
                        "why": "Marked at the last bullish candle before a 3-bar bearish impulse with above-average volume — classic institutional distribution signature.",
                        "how_to_trade": "Treat 96–99 as overhead resistance; look for rejection on retest with declining volume before considering shorts."
                    }
                ],
                "key_levels": ["96.50–99.00 (supply_zone)", "89.20–91.40 (demand_zone)"],
                "trading_insights": "Let price come to the zones — chasing entries in between is lower probability.",
                "disclaimer": "This analysis is for educational purposes only and does not constitute financial advice."
            }
        },
        "example_messages": [
            "mark supply and demand zones",
            "show fair value gaps (FVG)",
            "mark SMC on this stock",
            "mark market structure on this stock",
            "draw all the patterns and zones",
            "show candlestick patterns",
            "add RSI and MACD",
            "show support resistance",
            "analyze with all indicators"
        ]
    }


if __name__ == "__main__":
    import uvicorn
    
    print("\n" + "="*70)
    print("🚀 Starting Chat-Based Drawing Instruction API Server")
    print("="*70)
    
    # Check if token is configured
    api_token = os.getenv("API_BEARER_TOKEN", "")
    api_base_url = os.getenv("API_BASE_URL", "")
    
    if not api_base_url:
        print("\n⚠️  WARNING: API_BASE_URL not configured in .env file")
        print("   Add: API_BASE_URL=http://192.168.0.126:8000")
    
    if not api_token:
        print("\n⚠️  WARNING: API_BEARER_TOKEN not configured in .env file")
        print("   The API may fail with 401 authentication errors")
        print("   Run: python refresh_api_token.py to fix")
    else:
        print(f"\n✅ API Configuration:")
        print(f"   Base URL: {api_base_url}")
        print(f"   Token: {api_token[:20]}...{api_token[-10:] if len(api_token) > 30 else ''}")
    
    print("\n📍 Server URL: http://0.0.0.0:8000")
    print("📍 API Endpoint: POST http://0.0.0.0:8000/api/v1/drawing/chat/")
    print("📍 Examples: GET http://0.0.0.0:8000/api/v1/drawing/chat/examples")
    print("📍 Documentation: http://0.0.0.0:8000/docs")
    print("📍 Health Check: http://0.0.0.0:8000/health")
    print("\n💬 Chat-based generation enabled!")
    print("   Send natural language messages like:")
    print("   - 'mark supply and demand zones'")
    print("   - 'show candlestick patterns'")
    print("   - 'mark market structure on this stock'")
    print("   - 'draw price action on this stock'")
    print("   - 'draw order blocks on this stock'")
    print("   - 'draw liquidity on this stock'")
    print("   - 'show fair value gaps (FVG)'")
    print("   - 'draw all the patterns and zones'")
    print("   - 'add RSI and MACD indicators'")
    print("\n" + "="*70 + "\n")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
