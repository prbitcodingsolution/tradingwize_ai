"""
FastAPI Backend for Drawing Instruction Generation
Endpoint: POST /api/v1/drawing/generate/

This API accepts user input and generates TradingView drawing instructions
using AI-powered technical analysis.
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

from drawing_instruction.llm_drawing_generator import generate_drawings_with_llm
from drawing_instruction.symbol_resolver import resolve_symbol

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Drawing Instruction API",
    description="Generate TradingView drawing instructions using AI analysis",
    version="1.0.0"
)

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request Model
class DrawingRequest(BaseModel):
    """Request model for drawing instruction generation"""
    
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
        valid_markets = ['stock', 'forex', 'crypto']
        v_lower = v.lower()
        if v_lower not in valid_markets:
            raise ValueError(f"Invalid market. Must be one of: {', '.join(valid_markets)}")
        return v_lower


# Response Model for Drawing Instructions
class DrawingResponse(BaseModel):
    """Response model for drawing instructions"""
    
    success: bool = Field(description="Whether the request was successful")
    symbol: str = Field(description="Stock symbol processed")
    resolved_symbol: str = Field(description="Resolved symbol with exchange suffix")
    timeframe: str = Field(description="Chart timeframe")
    start_date: str = Field(description="Start date")
    end_date: str = Field(description="End date")
    market: str = Field(description="Market type")
    total_drawings: int = Field(description="Total number of drawings generated")
    drawings: List[dict] = Field(description="Array of drawing instructions")
    metadata: dict = Field(description="Additional metadata about the analysis")
    message: Optional[str] = Field(None, description="Success or error message")


# Response Model for Candles Data
class CandlesResponse(BaseModel):
    """Response model for candles data"""
    
    success: bool = Field(description="Whether the request was successful")
    symbol: str = Field(description="Stock symbol processed")
    resolved_symbol: str = Field(description="Resolved symbol with exchange suffix")
    timeframe: str = Field(description="Chart timeframe")
    start_date: str = Field(description="Start date")
    end_date: str = Field(description="End date")
    market: str = Field(description="Market type")
    total_candles: int = Field(description="Total number of candles fetched")
    candles: List[dict] = Field(description="Array of candlestick data (OHLCV)")
    metadata: dict = Field(description="Additional metadata")
    message: Optional[str] = Field(None, description="Success or error message")


class ErrorResponse(BaseModel):
    """Error response model"""
    
    success: bool = False
    error: str = Field(description="Error message")
    details: Optional[str] = Field(None, description="Detailed error information")


def convert_date_format(date_str: str) -> str:
    """
    Convert date from DD-MM-YYYY to YYYY-MM-DD format
    
    Args:
        date_str: Date in DD-MM-YYYY format
        
    Returns:
        Date in YYYY-MM-DD format
    """
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
        "name": "Drawing Instruction API",
        "version": "1.0.0",
        "status": "active",
        "endpoints": {
            "generate_drawings": "POST /api/v1/drawing/generate/",
            "fetch_candles": "POST /api/v1/candles/fetch/",
            "health_check": "GET /health"
        },
        "documentation": "/docs"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "drawing-instruction-api"
    }


@app.post(
    "/api/v1/drawing/generate/",
    response_model=DrawingResponse,
    responses={
        200: {"description": "Successfully generated drawing instructions"},
        400: {"model": ErrorResponse, "description": "Invalid request parameters"},
        500: {"model": ErrorResponse, "description": "Internal server error"}
    }
)
async def generate_drawing_instructions(request: DrawingRequest):
    """
    Generate TradingView drawing instructions using AI analysis
    
    This endpoint:
    1. Accepts stock symbol, date range, market type, and timeframe
    2. Fetches historical price data from external API
    3. Performs AI-powered technical analysis
    4. Generates drawing instructions (zones, patterns, indicators)
    5. Returns JSON compatible with TradingView
    
    Args:
        request: DrawingRequest with symbol, dates, market, and timeframe
        
    Returns:
        DrawingResponse with drawing instructions and metadata
        
    Raises:
        HTTPException: If validation fails or generation errors occur
    """
    
    logger.info(f"📥 Received request: {request.symbol} | {request.start_date} to {request.end_date} | {request.timeframe}")
    
    try:
        # Step 1: Resolve symbol (handle common names like JIO → JIOFIN.NS)
        logger.info(f"🔍 Resolving symbol: {request.symbol}")
        resolved_symbol = resolve_symbol(request.symbol)
        logger.info(f"✅ Resolved to: {resolved_symbol}")
        
        # Step 2: Convert date format from DD-MM-YYYY to YYYY-MM-DD
        logger.info(f"📅 Converting date format...")
        start_date_converted = convert_date_format(request.start_date)
        end_date_converted = convert_date_format(request.end_date)
        logger.info(f"✅ Dates: {start_date_converted} to {end_date_converted}")
        
        # Step 3: Prepare API configuration for external data source
        api_config = {
            "base_url": "http://192.168.0.126:8000",
            "from_date": start_date_converted,
            "to_date": end_date_converted,
            "market": request.market,
            "bearer_token": None,  # Optional: Add if your API requires authentication
            "csrf_token": None     # Optional: Add if your API requires CSRF token
        }
        
        logger.info(f"🔧 API Config: {api_config['base_url']} | Market: {request.market}")
        
        # Step 4: Generate drawing instructions using LLM-powered analysis
        logger.info(f"🤖 Starting AI analysis for {resolved_symbol}...")
        logger.info(f"   Timeframe: {request.timeframe}")
        logger.info(f"   Using external API for data fetch")
        
        result = generate_drawings_with_llm(
            symbol=resolved_symbol,
            timeframe=request.timeframe,
            use_api=True,
            api_config=api_config
        )
        
        logger.info(f"✅ Analysis complete!")
        logger.info(f"   Total drawings: {result.get('total_drawings', 0)}")
        
        # Step 5: Prepare response (drawings only)
        response = DrawingResponse(
            success=True,
            symbol=request.symbol,
            resolved_symbol=resolved_symbol,
            timeframe=request.timeframe,
            start_date=request.start_date,
            end_date=request.end_date,
            market=request.market,
            total_drawings=result.get('total_drawings', 0),
            drawings=result.get('drawings', []),
            metadata={
                "generated_at": datetime.now().isoformat(),
                "data_source": "external_api",
                "api_endpoint": api_config['base_url'],
                "analysis_type": "llm_powered",
                "candles_analyzed": result.get('total_candles', 0),
                "date_range": {
                    "start": start_date_converted,
                    "end": end_date_converted
                }
            },
            message=f"Successfully generated {result.get('total_drawings', 0)} drawing instructions"
        )
        
        logger.info(f"📤 Sending response with {response.total_drawings} drawings")
        return response
        
    except ValueError as ve:
        # Validation errors
        logger.error(f"❌ Validation error: {ve}")
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": "Validation Error",
                "details": str(ve)
            }
        )
        
    except Exception as e:
        # Unexpected errors
        logger.error(f"❌ Unexpected error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": "Internal Server Error",
                "details": str(e)
            }
        )


@app.post(
    "/api/v1/candles/fetch/",
    response_model=CandlesResponse,
    responses={
        200: {"description": "Successfully fetched candles data"},
        400: {"model": ErrorResponse, "description": "Invalid request parameters"},
        500: {"model": ErrorResponse, "description": "Internal server error"}
    }
)
async def fetch_candles_data(request: DrawingRequest):
    """
    Fetch candlestick (OHLCV) data for a given symbol and date range
    
    This endpoint:
    1. Accepts stock symbol, date range, market type, and timeframe
    2. Fetches historical price data from external API
    3. Returns candlestick data in JSON format
    
    Args:
        request: DrawingRequest with symbol, dates, market, and timeframe
        
    Returns:
        CandlesResponse with candlestick data
        
    Raises:
        HTTPException: If validation fails or data fetch errors occur
    """
    
    logger.info(f"📥 Candles request: {request.symbol} | {request.start_date} to {request.end_date} | {request.timeframe}")
    
    try:
        # Step 1: Resolve symbol
        logger.info(f"🔍 Resolving symbol: {request.symbol}")
        resolved_symbol = resolve_symbol(request.symbol)
        logger.info(f"✅ Resolved to: {resolved_symbol}")
        
        # Step 2: Convert date format
        logger.info(f"📅 Converting date format...")
        start_date_converted = convert_date_format(request.start_date)
        end_date_converted = convert_date_format(request.end_date)
        logger.info(f"✅ Dates: {start_date_converted} to {end_date_converted}")
        
        # Step 3: Fetch candles data
        logger.info(f"📊 Fetching candles data from external API...")
        
        from drawing_instruction.api_price_fetcher import APIPriceFetcher
        
        fetcher = APIPriceFetcher(
            base_url="http://192.168.0.126:8000",
            bearer_token=None,
            csrf_token=None
        )
        
        df = fetcher.fetch_price_data(
            symbol=resolved_symbol,
            timeframe=request.timeframe,
            from_date=start_date_converted,
            to_date=end_date_converted,
            market=request.market
        )
        
        if df is None or df.empty:
            raise ValueError("Failed to fetch candles data from external API")
        
        logger.info(f"✅ Fetched {len(df)} candles")
        
        # Step 4: Convert DataFrame to JSON format
        candles_data = []
        for idx, row in df.iterrows():
            candles_data.append({
                'timestamp': int(idx.timestamp()),
                'date': idx.strftime('%Y-%m-%d'),
                'open': float(row['Open']),
                'high': float(row['High']),
                'low': float(row['Low']),
                'close': float(row['Close']),
                'volume': float(row['Volume'])
            })
        
        # Step 5: Prepare response
        response = CandlesResponse(
            success=True,
            symbol=request.symbol,
            resolved_symbol=resolved_symbol,
            timeframe=request.timeframe,
            start_date=request.start_date,
            end_date=request.end_date,
            market=request.market,
            total_candles=len(candles_data),
            candles=candles_data,
            metadata={
                "fetched_at": datetime.now().isoformat(),
                "data_source": "external_api",
                "api_endpoint": "http://192.168.0.126:8000",
                "date_range": {
                    "start": start_date_converted,
                    "end": end_date_converted
                }
            },
            message=f"Successfully fetched {len(candles_data)} candles"
        )
        
        logger.info(f"📤 Sending response with {response.total_candles} candles")
        return response
        
    except ValueError as ve:
        # Validation errors
        logger.error(f"❌ Validation error: {ve}")
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": "Validation Error",
                "details": str(ve)
            }
        )
        
    except Exception as e:
        # Unexpected errors
        logger.error(f"❌ Unexpected error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": "Internal Server Error",
                "details": str(e)
            }
        )


@app.get("/api/v1/drawing/test")
async def test_endpoint():
    """
    Test endpoint to verify API is working
    Returns sample formats for both endpoints
    """
    return {
        "success": True,
        "message": "API is working correctly",
        "endpoints": {
            "drawings": {
                "url": "POST /api/v1/drawing/generate/",
                "description": "Generate drawing instructions with AI analysis",
                "sample_request": {
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
                    "timeframe": "1d",
                    "total_drawings": 10,
                    "drawings": [
                        {
                            "type": "LineToolRectangle",
                            "state": {
                                "points": [
                                    {"time": 1704067200, "price": 250.5},
                                    {"time": 1704326400, "price": 255.3}
                                ],
                                "fillBackground": True,
                                "backgroundColor": "rgba(255, 0, 0, 0.1)",
                                "linecolor": "#ff0000",
                                "text": "Supply Zone"
                            }
                        }
                    ],
                    "metadata": {
                        "generated_at": "2026-03-05T10:30:00",
                        "data_source": "external_api",
                        "candles_analyzed": 252
                    }
                }
            },
            "candles": {
                "url": "POST /api/v1/candles/fetch/",
                "description": "Fetch candlestick (OHLCV) data",
                "sample_request": {
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
                    "timeframe": "1d",
                    "total_candles": 252,
                    "candles": [
                        {
                            "timestamp": 1704067200,
                            "date": "2025-01-01",
                            "open": 248.5,
                            "high": 252.3,
                            "low": 247.8,
                            "close": 250.5,
                            "volume": 1234567
                        }
                    ],
                    "metadata": {
                        "fetched_at": "2026-03-05T10:30:00",
                        "data_source": "external_api"
                    }
                }
            }
        }
    }



if __name__ == "__main__":
    import uvicorn
    
    print("\n" + "="*70)
    print("🚀 Starting Drawing Instruction API Server")
    print("="*70)
    print("\n📍 Server URL: http://0.0.0.0:5000")
    print("📍 API Endpoint: POST http://0.0.0.0:5000/api/v1/drawing/generate/")
    print("📍 Documentation: http://0.0.0.0:5000/docs")
    print("📍 Health Check: http://0.0.0.0:5000/health")
    print("\n" + "="*70 + "\n")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=5000,
        log_level="info"
    )
