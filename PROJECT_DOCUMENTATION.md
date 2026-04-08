# TradingWize - AI-Powered Stock Analysis Platform

## Complete Project Documentation

---

## 1. Project Overview

**TradingWize** is a production-grade, AI-powered stock analysis platform built for the **Indian stock market** (NSE/BSE). It combines multiple analysis perspectives - fundamental, sentiment, technical, institutional, and options - into a single conversational interface powered by a **pydantic-ai agent** and a **Streamlit** frontend.

### What It Does

- **Conversational Stock Analysis**: Chat with an AI agent that fetches live data, runs analysis, and presents findings in a structured format.
- **Multi-Source Data Aggregation**: Pulls data from Yahoo Finance, screener.in, NSE India, Tavily web search, Twitter, Reddit, and more.
- **Institutional Investor Tracking**: FII/DII quarterly holding trends with directional scoring.
- **NSE Option Chain OI Analysis**: Live Open Interest data with PCR, Max Pain, OI shift detection, and weighted signal scoring.
- **TradingView Drawing Generation**: Auto-generates supply/demand zones, Smart Money Concepts, candlestick patterns, and indicator overlays as TradingView-compatible JSON.
- **Bilingual Report Generation**: PowerPoint and PDF reports in English and Hindi.
- **Bulk Stock Screening**: Analyze 200+ stocks concurrently, filtering for value opportunities (e.g., stocks fallen 25%+ from 52-week high).
- **FinRobot Deep Analysis**: Three-agent pipeline (Fundamental + Sentiment + Reasoning) for investment thesis generation.

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Streamlit (Python) |
| AI Agent Framework | pydantic-ai |
| LLM Provider | OpenRouter (GPT-4o, GPT-o3, etc.) |
| Financial Data | yfinance, screener.in, NSE India API |
| Web Search | Tavily API |
| Sentiment Sources | Twitter API, Reddit (RapidAPI), Adanos API, FinBERT |
| Database | PostgreSQL (psycopg2) |
| Charting | Plotly |
| Report Generation | python-pptx (PPT), ReportLab (PDF) |
| Browser Automation | Playwright (NSE bot protection bypass) |
| Observability | LangSmith (tracing & cost tracking) |

---

## 2. Architecture

### High-Level Data Flow

```
User (Streamlit Chat UI)
        |
        v
  app_advanced.py  <-- Streamlit frontend (UI, routing, display)
        |
        v
    agent1.py      <-- pydantic-ai Agent (system prompt, tool selection)
        |
        v
    tools.py       <-- StockTools (data fetching, LLM analysis)
        |
        +----> yfinance (price, financials)
        +----> screener.in (holdings, fundamentals)
        +----> Tavily (web search, news)
        +----> OpenRouter LLM (analysis generation)
        +----> NSE API via Playwright (option chains)
        +----> Twitter/Reddit (sentiment)
        |
        v
    models.py      <-- Pydantic data models
        |
        v
  database.py      <-- PostgreSQL storage
```

### Core Files

| File | Size | Purpose |
|------|------|---------|
| `app_advanced.py` | ~255 KB | Streamlit frontend - all UI views, tabs, charts, session management |
| `agent1.py` | ~124 KB | pydantic-ai Agent definition, system prompt, 9 registered tools, conversation state |
| `tools.py` | ~80 KB | `StockTools` class with data fetching, web search, scraping, LLM-powered analysis |
| `models.py` | ~8 KB | All Pydantic data models (StockValidation, CompanyData, FinancialData, etc.) |

---

## 3. The AI Agent (`agent1.py`)

### Agent Configuration

The core agent is built with `pydantic-ai.Agent` and uses OpenRouter as the LLM provider. The agent has a detailed system prompt that:

- Instructs the agent to act as a financial analyst
- Defines strict tool output passthrough rules (never summarize or modify tool responses)
- Contains auto-analysis logic (single match -> auto-analyze)
- Handles merged/delisted stock awareness (e.g., HDFC merged into HDFC Bank)
- Includes 100+ stock name aliases for fast lookup (e.g., "jio" -> JIOFIN.NS)

### Conversation State

```python
@dataclass
class ConversationState:
    stock_symbol: str | None          # Current stock being analyzed
    stock_name: str | None            # Human-readable name
    company_data: CompanyData | None  # Full analysis data
    conversation_history: deque       # Last 10 interactions
    pending_variants: list            # Multi-match results awaiting selection
    analysis_complete: bool           # Prevents duplicate analysis
    validation_done_this_turn: bool   # Prevents re-validation in same turn
    last_analysis_response: str       # Cached for retry handling
    conversation_context: dict        # Rich tracking (recent_actions, user_intent, etc.)
```

### Registered Tools (9 total)

| # | Tool | Trigger | What It Does |
|---|------|---------|-------------|
| 1 | `validate_and_get_stock` | User mentions a stock name | Resolves name to symbol, handles ambiguity, auto-analyzes single matches |
| 2 | `analyze_stock_request` | After validation, or user requests analysis | Runs comprehensive 9-section analysis (snapshot, financials, market data, SWOT, etc.) |
| 3 | `return_existing_analysis` | User asks about already-analyzed stock | Returns cached analysis without re-fetching |
| 4 | `handle_trader_question` | Follow-up questions | Answers from CEO/CFO perspective with specific data points |
| 5 | `perform_scenario_analysis` | "What if..." questions | What-if scenario analysis from CFO perspective |
| 6 | `generate_summary_report` | User requests summary | Comprehensive summary with highlights, pros/cons, outlook |
| 7 | `handle_greeting` | User says hello/hi | Friendly greeting with capabilities overview |
| 8 | `get_fii_dii_sentiment` | User asks about institutional holdings | FII/DII quarterly trends with directional scoring |
| 9 | `get_option_chain_analysis` | User asks about option chain/OI/PCR | NSE option chain with weighted OI signal analysis |

### ToolResponse Pattern

Every tool must return a `ToolResponse` object:

```python
class ToolResponse:
    content: str          # The analysis text (markdown)
    tool_name: str        # Name of the tool that generated it
    is_tool_response: bool = True
```

The system prompt strictly forbids the agent from adding commentary to tool responses - they must be passed through to the user exactly as returned.

---

## 4. Data Models (`models.py`)

### Core Analysis Models

```
StockValidation
  - is_valid, stock_symbol, stock_name
  - variants (for multi-match)
  - needs_clarification, message

CompanyData (the main container)
  - CompanySnapshot (name, ticker, sector, CEO, employees, etc.)
  - BusinessOverview (description, products, revenue sources)
  - FinancialData (income statement, balance sheet, cash flow, margins, valuation)
  - MarketData (current price, 52-week data, holdings %, performance, competitors)
  - SWOTAnalysis (strengths, weaknesses, opportunities, threats)
  - news, announcements, timestamp
  - finrobot_report (optional deep analysis)

CompanyReport (CEO/CFO pitch format)
ScenarioAnalysis (what-if impact)
Summary (investment verdict)
```

### Institutional Sentiment Models

```
QuarterlyHolding
  - quarter, fii_pct, dii_pct, promoter_pct

FIIDIISentiment
  - Current holdings (FII/DII/total institutional %)
  - Trends (increasing/decreasing/stable)
  - Quarterly history (last 6-8 quarters)
  - Scoring: institutional_sentiment_score (0-100)
  - Recommendation with color + reasoning
```

### Option Chain Models

```
OptionStrike
  - strike, call_oi, call_chng_oi, put_oi, put_chng_oi
  - Flags: is_max_call_oi, is_max_put_oi, is_atm

OIShiftSignal
  - direction: "UP" | "DOWN" | "SIDEWAYS"
  - description, strength, score_contribution (-3 to +3)

OIAnalysis
  - Key levels: max_call_oi_strike, max_put_oi_strike, max_pain_strike
  - PCR: put_call_ratio, pcr_label, pcr_score
  - OI shifts: call_oi_shift, put_oi_shift
  - Support/resistance, expected range
  - Verdict: market_bias, recommendation, confidence
  - Weighted scoring: total_signal_score, has_contradiction

OptionChainData
  - symbol, expiry_date, underlying_price
  - available_expiries, strikes[], analysis
```

---

## 5. Frontend UI (`app_advanced.py`)

### Navigation Views

The sidebar provides navigation between 6 main views:

#### View 1: Fundamental Analysis (Main)

Contains 5 tabs:

| Tab | Content |
|-----|---------|
| **Chat** | Conversational interface with the AI agent. Message history, streaming responses, tool tracking. |
| **Sentiment Analysis** | Market sentiment from News, Yahoo Finance, Twitter, Reddit. Future outlook. Confidence scores. |
| **Trade Ideas** | TradingView community trade ideas scraped for the current stock. |
| **FinRobot Agent** | Three-agent deep analysis pipeline with scoring (fundamental, valuation, health, growth). |
| **Option Chain** | NSE OI analysis with recommendation banner, key metrics, OI table, combined chart, and full signal breakdown. |

#### View 2: Drawing Generator

Generates TradingView-compatible drawing instructions:
- Symbol, timeframe (1m to 1M), period (1m to 5y)
- Analysis types: SMC, Supply/Demand, Patterns, Bollinger, MACD, RSI
- Output: JSON with drawing coordinates, downloadable

#### View 3: Bulk Stock Analyzer

Screens 200+ stocks concurrently:
- Input: manual list, CSV upload, or preset
- Multi-threaded analysis with progress tracking
- Filters stocks fallen >25% from 52-week high
- Export: CSV/Excel

#### View 4: Presentation Viewer

Displays generated bilingual (English/Hindi) PowerPoint presentations.

#### View 5: Data Dashboard

Financial metrics visualization with interactive charts.

#### View 6: System Info

API configuration status, model info, data sources.

### Option Chain Tab - Detailed

The Option Chain tab provides live NSE OI analysis:

**Input Section**:
- Symbol text input (auto-fills from currently loaded stock)
- Expiry selector (Nearest Weekly, Next Week, Monthly, +1 Month)
- Fetch button

**Recommendation Banner**: Color-coded (green/orange/red/gray) with bias and confidence.

**Key Metrics Row**: 5 columns showing Resistance, Support, Max Pain, PCR, Expected Range.

**Inner Tabs**:
1. **OI Table**: Styled dataframe with highlighted rows (blue=ATM, red=Max Call OI, green=Max Put OI)
2. **OI Chart**: Combined Plotly chart with OI bars (left axis) + Change in OI lines (right axis) + vertical key level markers
3. **Full Analysis**: Signal score meter (X/9), contradiction warning, Call/Put OI signals with scores, complete signal breakdown, educational explainer

---

## 6. NSE Option Chain System (`utils/option_chain_analyzer.py`)

### Data Fetching Challenge

NSE India uses Akamai bot protection that blocks normal HTTP requests. The solution uses **Playwright** (headed Chromium, positioned off-screen) to:

1. Open the NSE option chain page (solves the JS challenge)
2. Intercept the XHR response containing option chain JSON
3. For equities: click "Equity Stock" tab and select from dropdown

A separate subprocess worker (`_nse_fetch_worker.py`) runs Playwright to avoid asyncio event loop conflicts with Streamlit on Windows.

Results are cached in memory for 3 minutes.

### OI Analysis Engine

**Inputs**: Raw option chain JSON from NSE (strikes with Call OI, Put OI, Change in OI)

**Analysis Steps**:

1. **Max Pain Calculation**: Strike where total option premium decay is maximized (option sellers profit most)

2. **Put-Call Ratio (PCR)**: `Total Put OI / Total Call OI`
   - PCR > 1.5 = Extremely Bullish (+2)
   - PCR 1.2-1.5 = Bullish (+1)
   - PCR 0.8-1.2 = Neutral (0)
   - PCR 0.5-0.8 = Bearish (-1)
   - PCR < 0.5 = Extremely Bearish (-2)

3. **OI Shift Detection** (weighted average of top 5 OI strikes):
   - **Call OI Logic**: Far above spot = mildly bullish (+1), just above = resistance cap (-1), below spot = extremely bearish (-3)
   - **Put OI Logic**: Far below spot = strong support (+2), just below = support (+1), above spot = panic hedging (-2)

4. **Max Pain Scoring**: Weak signal (max +/-1) based on distance from spot

5. **OI Wall Proximity**: Which wall (support or resistance) is closer to spot price

6. **Fresh OI Changes**: New put writing below spot (+1), new call writing above spot (-1), call OI unwinding below spot (+1)

7. **Contradiction Detection**: If Call OI and Put OI signals are strongly opposed, score is capped to +/-1 and recommendation becomes "Wait - Conflicting Signals"

**Scoring Range**: -9 to +9 total, mapped to recommendations:

| Score | Recommendation |
|-------|---------------|
| >= 5 | Buy / Go Long (High Confidence) |
| 2-4 | Cautious Buy (Medium Confidence) |
| 1 | Neutral-Bullish (Low Confidence) |
| 0 | Range Trade |
| -1 | Neutral-Bearish (Low Confidence) |
| -2 to -4 | Caution - Avoid Longs (Medium Confidence) |
| <= -5 | Avoid / Consider Short (High Confidence) |
| Contradiction | Wait - Conflicting Signals (Low Confidence) |

---

## 7. Drawing Instruction Module (`drawing_instruction/`)

A self-contained module that generates TradingView-compatible drawing instructions from price analysis.

### Pipeline

```
price_fetcher.py (OHLCV from yfinance)
        |
        v
  +-----+------+------+------+
  |     |      |      |      |
zone  pattern  smc  indicator liquidity
detect detect  ind  calculator sweeps
  |     |      |      |      |
  +-----+------+------+------+
        |
        v
  json_builder.py (TradingView JSON format)
        |
        v
  drawing_generator.py (orchestrator)
```

### Key Components

| File | Purpose |
|------|---------|
| `price_fetcher.py` | Fetch OHLCV data from yfinance |
| `zone_detector.py` | Supply/demand zone detection (base -> impulse -> departure) |
| `pattern_detector.py` | Candlestick pattern recognition (hammer, engulfing, doji, etc.) |
| `smc_indicator.py` | Smart Money Concepts (BOS, CHoCH, Order Blocks, FVG) |
| `supply_demand_indicator.py` | Institutional supply/demand zones |
| `liquidity_sweeps.py` | Liquidity sweep pattern detection |
| `indicator_calculator.py` | Bollinger Bands, RSI, MACD, Moving Averages |
| `json_builder.py` | Converts analysis into TradingView drawing JSON |
| `api_server.py` | Flask API server (port 5001) |
| `symbol_resolver.py` | NSE/BSE symbol normalization |

### Output Format

TradingView-compatible JSON with drawing objects:

```json
{
  "type": "LineToolRectangle",
  "state": {
    "fillBackground": true,
    "backgroundColor": "rgba(76, 175, 80, 0.2)",
    "text": "Demand Zone"
  },
  "points": [
    {"price": 1280.5, "time_t": 1711900800},
    {"price": 1305.0, "time_t": 1712160000}
  ]
}
```

---

## 8. FinRobot Module (`finrobot/`)

### Three-Agent Pipeline

```
Stock Data (CompanyData)
        |
        +---> Fundamental Agent --> FundamentalAnalysisResult
        |       (valuation, health, growth scores)
        |
        +---> Sentiment Agent --> SentimentAgentResult
        |       (market mood, bullish/bearish indicators)
        |
        +---> Reasoning Agent --> ReasoningResult
                (investment thesis, risks, recommendation)
        |
        v
  FinRobotReport (combined results)
```

Each agent runs independently - if one fails, the pipeline continues with the others. Results are cached in `CompanyData.finrobot_report`.

---

## 9. Utilities (`utils/`)

### LLM Configuration (`model_config.py`)

- **Provider**: OpenRouter (not direct OpenAI)
- **API Key Rotation**: Round-robin across up to 10 keys
- **Concurrency Limiter**: Max 6 concurrent LLM calls (semaphore)
- **Lazy Initialization**: Client created on first use to avoid import hangs
- All LLM calls route through `guarded_llm_call()` with semaphore protection

### FII/DII Analyzer (`fii_dii_analyzer.py`)

- **Sources**: screener.in (quarterly history), yfinance (current snapshot)
- **Scoring Formula**: `(level_score * 0.4) + (trend_score * 0.6)` - trend weighted more heavily
- **Benchmarks**: FII (very_high=20%, high=12%), DII (very_high=15%, high=8%)
- Generates quarterly holding history and directional recommendations

### Sentiment Analysis

Multiple sources:

| Module | Source | Method |
|--------|--------|--------|
| `finbert_sentiment.py` | Financial news | FinBERT model (ProsusAI/finbert, ~440MB) |
| `stock_news_analyzer.py` | News aggregation | Multi-source news pipeline |
| `sentiment_analyzer_adanos.py` | Adanos API | Cloud sentiment API |
| `reddit_sentiment.py` | Reddit | RapidAPI scraping |

### Bulk Stock Selector (`bulk_stock_selector.py`)

- Processes 200+ stocks concurrently via `ThreadPoolExecutor`
- Filters stocks fallen 25%+ from 52-week high
- Returns `StockResult` with symbol, price, high, drop%, selection flag

### Report Generation

| Module | Output | Features |
|--------|--------|----------|
| `ppt_generator.py` | PowerPoint (.pptx) | Bilingual (EN + HI), stock data integration |
| `pdf_generator.py` | PDF | ReportLab-based stock reports |
| `pdf_text_summarizer.py` | Text summary | Extracts key points from PDFs |

---

## 10. Database (`database_utility/database.py`)

### PostgreSQL Schema

**Table**: `stock_analysis`

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PRIMARY KEY | Auto-increment |
| stock_name | VARCHAR(255) | Company name |
| stock_symbol | VARCHAR(50) INDEXED | Trading symbol |
| analyzed_response | TEXT | Full analysis text |
| tech_analysis | JSONB | Technical analysis data |
| selection | BOOLEAN INDEXED | Selected/filtered flag |
| market_senti | TEXT | Market sentiment |
| future_senti | TEXT | Future sentiment |
| analyzed_at | TIMESTAMP INDEXED | Analysis timestamp |
| current_market_senti_status | VARCHAR(50) | Sentiment label |
| future_senti_status | VARCHAR(50) | Future sentiment label |

### Connection

Environment variables: `DB_HOST`, `DB_PORT`, `DB_NAME` (trading_wise_analyzer), `DB_USER`, `DB_PASSWORD`

### Methods

- `connect()` / `disconnect()` - Connection management
- `create_table()` - Schema initialization
- `save_analysis()` - Store analysis results
- `get_latest_analysis()` - Retrieve most recent
- `search_by_symbol()` - Lookup by ticker

---

## 11. Configuration & Environment

### Environment Variables (`.env`)

```
# LLM Provider (primary)
OPENROUTER_API_KEY=...
OPENROUTER_API_KEY_2=...
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

# Search
TAVILY_API_KEY=...

# Google AI (rotating keys)
GOOGLE_API_KEY_1=...
GOOGLE_API_KEY_2=...
GOOGLE_API_KEY_3=...
GOOGLE_API_KEY_4=...

# Alternative LLM
GROQ_API_KEY_10=...

# Social Media
TWITTER_BEARER_TOKEN=...
TWITTER_API_KEY=...
TWITTER_SECRET_KEY=...
REDDIT_RAPIDAPI_KEY=...
REDDIT_RAPIDAPI_HOST=...

# Sentiment
ADANOS_API_KEY=...

# Observability
LANGSMITH_API_KEY=...
LANGSMITH_PROJECT=trader_agent
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_TRACING=true
LOGFIRE_API_KEY=...

# Database
DB_HOST=...
DB_PORT=5432
DB_NAME=trading_wise_analyzer
DB_USER=...
DB_PASSWORD=...

# Other
API_BASE_URL=...
USE_MCP=false
```

### Dependencies (Key packages from `requirements.txt`)

**AI/LLM**: pydantic-ai, openai, langchain, langchain-openai, langchain-google-genai, langchain-groq, langgraph, langsmith, anthropic, groq

**Finance**: yfinance, pandas, numpy, plotly

**Web/Scraping**: requests, httpx, beautifulsoup4, lxml, playwright

**PDF/PPT**: PyPDF2, pdfplumber, PyMuPDF, reportlab, python-pptx

**Database**: psycopg2-binary, SQLAlchemy, peewee

**ML/NLP**: transformers (>=4.36.0), torch (>=2.0.0) - for FinBERT

**Core**: streamlit, pydantic, python-dotenv, python-dateutil

---

## 12. Running the Application

### Prerequisites

- Python 3.14+
- PostgreSQL database
- Playwright browsers installed (`playwright install chromium`)
- All API keys configured in `.env`

### Starting the App

```bash
# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Run the Streamlit app
streamlit run app_advanced.py --server.address=0.0.0.0 --server.port=8501
```

### Optional: Drawing API Server

```bash
python -m drawing_instruction.api_server  # Port 5001
```

### Optional: CLI Drawing Generation

```bash
python -m drawing_instruction.drawing_generator RELIANCE 1d 6mo
```

---

## 13. Project Directory Structure

```
trader_agent_17_03/
|
|-- app_advanced.py              # Streamlit frontend (main entry point)
|-- agent1.py                    # pydantic-ai Agent (tools, system prompt)
|-- tools.py                     # StockTools class (data fetching, analysis)
|-- models.py                    # All Pydantic data models
|-- api_chat_drawing.py          # Chat-based drawing API
|-- api_logger.py                # API usage logging
|
|-- utils/
|   |-- model_config.py          # LLM provider config (OpenRouter, key rotation)
|   |-- option_chain_analyzer.py # NSE OI analysis engine
|   |-- _nse_fetch_worker.py     # Playwright subprocess worker for NSE
|   |-- fii_dii_analyzer.py      # FII/DII institutional sentiment
|   |-- finbert_sentiment.py     # FinBERT ML sentiment analysis
|   |-- stock_news_analyzer.py   # News aggregation pipeline
|   |-- sentiment_analyzer_adanos.py # Adanos sentiment API
|   |-- reddit_sentiment.py      # Reddit sentiment scraping
|   |-- bulk_stock_selector.py   # Concurrent stock screening
|   |-- screener_scraper.py      # screener.in web scraping
|   |-- stock_symbol_resolver.py # Symbol normalization (NSE/BSE)
|   |-- ppt_generator.py         # Bilingual PowerPoint generation
|   |-- pdf_generator.py         # PDF report generation
|   |-- pdf_text_summarizer.py   # PDF text extraction
|   |-- chart_visualizer.py      # Plotly chart generation
|   |-- data_fetcher.py          # Price data fetching
|   |-- data_validator.py        # Data validation
|   |-- indicators.py            # Technical indicators
|   |-- narration_script_generator.py # Audio narration scripts
|   |-- tradingview_ideas_scraper.py  # TradingView ideas
|   |-- _tradingview_worker.py   # TradingView subprocess worker
|
|-- drawing_instruction/
|   |-- drawing_generator.py     # Main orchestrator
|   |-- llm_drawing_generator.py # AI-powered drawing generation
|   |-- price_fetcher.py         # OHLCV data from yfinance
|   |-- api_price_fetcher.py     # API-based price data
|   |-- zone_detector.py         # Supply/demand zone detection
|   |-- pattern_detector.py      # Candlestick pattern recognition
|   |-- llm_pattern_detector.py  # AI pattern detection
|   |-- smc_indicator.py         # Smart Money Concepts
|   |-- supply_demand_indicator.py # Supply/demand indicators
|   |-- liquidity_sweeps.py      # Liquidity sweep detection
|   |-- indicator_calculator.py  # Bollinger, RSI, MACD
|   |-- macd_indicator.py        # MACD indicator
|   |-- json_builder.py          # TradingView JSON builder
|   |-- symbol_resolver.py       # Symbol resolution
|   |-- chat_drawing_agent.py    # Chat interface for drawings
|   |-- api_server.py            # Flask API (port 5001)
|
|-- finrobot/
|   |-- finrobot_orchestrator.py # Three-agent pipeline orchestrator
|   |-- chat_agent.py            # Chat interface for FinRobot
|   |-- (agent modules)          # Fundamental, Sentiment, Reasoning agents
|
|-- database_utility/
|   |-- database.py              # PostgreSQL StockDatabase class
|
|-- data/                        # Reference PDFs (SMC, patterns, etc.)
|-- downloads/                   # Generated PPTs, PDFs
|-- backup-all/                  # Legacy file backups
|-- PPT_json/                    # JSON representations of presentations
|-- test/                        # Test data files
|
|-- .env                         # Environment variables (API keys, DB config)
|-- requirements.txt             # Python dependencies
|-- pyproject.toml               # Project metadata
|-- CLAUDE.md                    # Claude Code guidance
```

---

## 14. Key Design Patterns

### Tool Response Passthrough

The agent is strictly instructed to pass tool responses to the user verbatim. This ensures consistent, well-formatted output without LLM hallucination or summarization.

### Concurrent LLM Call Limiting

All LLM calls go through `guarded_llm_call()` with a semaphore limiting to 6 concurrent calls. This prevents API rate limiting and manages costs.

### Subprocess Workers (Windows Compatibility)

Playwright and TradingView scrapers run in separate Python subprocesses to avoid asyncio event loop conflicts with Streamlit on Windows + Python 3.14. Workers communicate via stdout JSON.

### Session State Management

Streamlit session state tracks:
- Message history, current stock, analysis data
- Cached option chain data (with TTL)
- FinRobot reports
- PPT/PDF paths
- UI state (selected view, tab, etc.)

### Graceful Degradation

- If one FinRobot agent fails, the pipeline continues
- If Tavily API is unavailable, analysis proceeds without web search
- If NSE API is slow, clear error messages guide the user
- Missing API keys are detected at startup with warnings

---

## 15. API Endpoints

### Drawing API (`api_chat_drawing.py`)

```
POST /api/v1/drawing/generate/
Body: { symbol, start_date, end_date, market, timeframe }
Response: TradingView-compatible drawing JSON
```

### Drawing Instruction Server (`drawing_instruction/api_server.py`)

```
Flask server on port 5001
Endpoints for drawing generation via HTTP
```

---

## 16. Observability & Tracing

### LangSmith Integration

All major functions are decorated with `@traceable` from the langsmith library:

- Agent tool calls
- LLM invocations
- Data fetching operations
- Analysis pipeline steps

**Dashboard**: LangSmith project "trader_agent" provides:
- Real-time trace visualization
- Token usage and cost tracking
- Latency monitoring
- Error tracking

---

## 17. Special Features

### Merged/Delisted Stock Registry

`agent1.py` maintains a registry of corporate actions:

```python
MERGED_STOCKS = {
    "HDFC.NS": {"merged_into": "HDFCBANK.NS", "note": "Merged July 2023"},
    "VIJAYABANK.NS": {"merged_into": "BANKBARODA.NS", "note": "Merged April 2019"},
    ...
}
```

When a user asks about a merged stock, the agent automatically redirects to the surviving entity.

### Common Stock Aliases

100+ aliases for fast lookup without LLM:

```python
"jio" -> "JIOFIN.NS"
"ril" -> "RELIANCE.NS"
"tcs" -> "TCS.NS"
"infosys" -> "INFY.NS"
...
```

### Bilingual Report Generation

PPT reports are generated in both English and Hindi, with language selection in the Presentation Viewer.
