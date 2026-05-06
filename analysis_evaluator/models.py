"""Pydantic models for the /analyze endpoint."""

from typing import List, Optional, Tuple, Dict, Any, Literal
from pydantic import BaseModel, Field


# ─────────────────────────  Inputs  ──────────────────────────

class Candle(BaseModel):
    time: int  # unix seconds
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class FibInput(BaseModel):
    start_index: Optional[int] = None
    end_index: Optional[int] = None
    start_price: Optional[float] = None
    end_price: Optional[float] = None
    start_time: Optional[int] = None
    end_time: Optional[int] = None


class ChannelLine(BaseModel):
    """Two-point trendline (the channel itself is a pair of these)."""
    p1_time: int
    p1_price: float
    p2_time: int
    p2_price: float


class ChannelInput(BaseModel):
    upper: Optional[ChannelLine] = None
    lower: Optional[ChannelLine] = None


class ZoneInput(BaseModel):
    top: float
    bottom: float
    start_time: Optional[int] = None
    end_time: Optional[int] = None
    label: Optional[str] = None  # "entry" / "stop" / "target" / free-form


class UserAnalysis(BaseModel):
    fib: Optional[FibInput] = None
    channels: List[ChannelInput] = Field(default_factory=list)
    zones: List[ZoneInput] = Field(default_factory=list)
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    direction: Optional[Literal["buy", "sell"]] = None


class ManualAnalyzeRequest(BaseModel):
    """Direct mode — caller already has the candles and parsed drawings."""
    candles: List[Candle]
    analysis: UserAnalysis


class UpstreamAnalyzeRequest(BaseModel):
    """Auto-fetch mode — server pulls both candles and drawings from the LMS."""
    base_url: str = Field(default="http://192.168.0.122:8000")
    bearer_token: Optional[str] = None
    csrf_token: Optional[str] = None

    # Drawings query — passed straight to /api/v1/learning/result-screenshot-view/
    category: str = "patterns"
    sub_category: str = "patterns-patterns"
    type: str = "Smart"
    date: str  # "DD-MM-YYYY"
    chapter_id: int
    user_type: str = "student"
    is_challenge_only: bool = True
    # The LMS returns a session wrapper with multiple `questions[]`. Pick one
    # by its `id` (e.g. 433, 434, 435, 436). If omitted, the first question
    # with chart metadata wins.
    question_id: Optional[int] = None


# ─────────────────────────  Outputs  ─────────────────────────

EvalLabel = Literal["correct", "partially correct", "weak", "incorrect", "invalid", "missing"]


class Evaluation(BaseModel):
    trend: EvalLabel
    fibonacci: EvalLabel
    channel: EvalLabel
    entry_zone: EvalLabel


class EntryZone(BaseModel):
    top: float
    bottom: float


class CorrectAnalysis(BaseModel):
    trend: Literal["bullish", "bearish", "sideways"]
    fib_range: Tuple[int, int]                 # (low_index, high_index)
    fib_prices: Tuple[float, float]            # (low_price, high_price)
    key_levels: List[float] = Field(default_factory=lambda: [0.5, 0.618])
    entry_zone: EntryZone


class AnalyzeResponse(BaseModel):
    success: bool = True

    # Chart context — populated automatically in upstream mode, optional in manual mode
    symbol: Optional[str] = None
    timeframe: Optional[str] = None
    market: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None

    # Time window the user was analysing — drives the AI's drawing focus and
    # the frontend's initial visible range on the AI chart so both panels open
    # on the same dates instead of jumping to the latest candles.
    focus_start_time: Optional[int] = None
    focus_end_time: Optional[int] = None

    score: float
    evaluation: Evaluation
    mistakes: List[str]

    # Structured "ideal" read (indices, prices, golden pocket)
    correct_analysis: CorrectAnalysis

    # Same read converted to TradingView drawing JSON, ready for the chart to render
    total_drawings: int = 0
    drawings: List[Dict[str, Any]] = Field(default_factory=list)

    ai_explanation: str

    # Raw debug info — handy for QA / building UI on top
    debug: Dict[str, Any] = Field(default_factory=dict)
