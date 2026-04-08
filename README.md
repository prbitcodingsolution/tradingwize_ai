# TradingWize - AI-Powered Stock Analysis Agent

An intelligent stock analysis platform built with **pydantic-ai** and **Streamlit**, focused on the **Indian stock market (NSE/BSE)**. Combines LLM-powered fundamental analysis, real-time sentiment tracking, TradingView chart integration, and automated report generation into a single conversational interface.

---

## Table of Contents

- [Features](#features)
- [Architecture Overview](#architecture-overview)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Environment Variables](#environment-variables)
  - [Running the App](#running-the-app)
- [Application Views](#application-views)
  - [Fundamental Analysis (Chat)](#1-fundamental-analysis--chat)
  - [Sentiment Analysis](#2-sentiment-analysis)
  - [Trade Ideas](#3-trade-ideas)
  - [Data Dashboard](#4-data-dashboard)
  - [Presentation Viewer](#5-presentation-viewer)
  - [Bulk Stock Analyzer](#6-bulk-stock-analyzer)
  - [Drawing Generator](#7-drawing-generator)
  - [System Info](#8-system-info)
- [Core Modules](#core-modules)
  - [Agent Pipeline](#agent-pipeline-agent1py--toolspy)
  - [Drawing Instruction Module](#drawing-instruction-module)
  - [Utilities](#utilities)
  - [Database](#database)
- [Data Models](#data-models)
- [Key Patterns & Conventions](#key-patterns--conventions)
- [Corporate Actions Handling](#corporate-actions-handling)
- [Deployment](#deployment)
- [Troubleshooting](#troubleshooting)

---

## Features

| Feature | Description |
|---------|-------------|
| **Conversational Stock Analysis** | Chat-based interface to analyze any NSE/BSE stock. Ask "Tell me about TCS" and get a full report. |
| **Smart Stock Resolution** | Handles company names, tickers, business groups. "Tata" returns all Tata group companies. |
| **Merged/Delisted Stock Detection** | Automatically redirects merged stocks (e.g., HDFC Ltd → HDFC Bank) with explanatory notes. |
| **Fundamental Analysis** | Financial metrics, SWOT analysis, business overview, competitor comparison via yfinance + screener.in. |
| **Sentiment Analysis** | Multi-source sentiment from News, Yahoo Finance, Twitter/X, and Reddit with scoring (0-100). |
| **Future Outlook & News** | AI-powered analysis of latest news articles using Tavily search + LLM summarization. |
| **TradingView Trade Ideas** | Scrapes top 9 trading ideas from TradingView with chart images, displayed in a grid UI. |
| **Technical Drawing Generator** | Generates TradingView-compatible drawing instructions: supply/demand zones, candlestick patterns, Bollinger Bands, RSI, MACD, Smart Money Concepts. |
| **PDF Report Generation** | Auto-generates downloadable PDF reports with charts, financials, and analysis. |
| **PowerPoint Generation** | Creates bilingual (English/Hindi) presentation decks for stock pitches. |
| **Bulk Stock Analyzer** | Analyze multiple stocks at once, filter by drop-from-high percentage. |
| **Data Dashboard** | Interactive Plotly charts with price history, volume, financial metrics. |
| **Database Persistence** | Stores all analyses in PostgreSQL for retrieval and comparison. |
| **LangSmith Tracing** | Full observability of LLM calls and agent tool usage. |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Streamlit Frontend                     │
│                   (app_advanced.py)                       │
│                                                          │
│  ┌──────────┐  ┌───────────┐  ┌────────────────────┐   │
│  │  Chat     │  │ Sentiment │  │  Trade Ideas       │   │
│  │  Tab      │  │ Tab       │  │  Tab (TradingView) │   │
│  └────┬─────┘  └─────┬─────┘  └────────┬───────────┘   │
└───────┼──────────────┼─────────────────┼────────────────┘
        │              │                 │
        ▼              ▼                 ▼
┌──────────────┐ ┌───────────┐  ┌──────────────────┐
│  Agent       │ │ Adanos    │  │ Playwright        │
│  (agent1.py) │ │ Sentiment │  │ Scraper           │
│              │ │ API       │  │ (subprocess)      │
│  Tools:      │ └───────────┘  └──────────────────┘
│  - yfinance  │
│  - Tavily    │ ┌───────────────────────────────┐
│  - screener  │ │  Drawing Instruction Module    │
│  - LLM calls │ │  (Flask API on port 5001)     │
│  - PDF gen   │ │  - Zone Detection             │
│  - PPT gen   │ │  - Pattern Detection          │
└──────┬───────┘ │  - SMC Indicators             │
       │         │  - Bollinger / RSI / MACD     │
       ▼         └───────────────────────────────┘
┌──────────────┐
│  PostgreSQL  │
│  Database    │
└──────────────┘
```

### LLM Flow

```
User Input → Agent (pydantic-ai) → Tool Selection → Tool Execution → Response
                                        │
                    ┌───────────────────┼───────────────────┐
                    ▼                   ▼                   ▼
             validate_and_get_stock  analyze_stock    handle_greeting
                    │                   │
                    ▼                   ▼
              LLM (OpenRouter)    yfinance + Tavily + screener.in
                    │                   │
                    ▼                   ▼
              Stock List           CompanyData (Pydantic model)
              for selection        → PDF / PPT / DB storage
```

---

## Project Structure

```
trader_agent_17_03/
│
├── app_advanced.py              # Streamlit frontend (main entry point)
├── agent1.py                    # pydantic-ai Agent + all tool definitions
├── tools.py                     # StockTools class (data fetching, analysis)
├── models.py                    # Pydantic data models (CompanyData, etc.)
│
├── utils/                       # Utility modules
│   ├── model_config.py          # LLM provider config (OpenRouter)
│   ├── pdf_generator.py         # ReportLab PDF generation
│   ├── ppt_generator.py         # PowerPoint generation
│   ├── screener_scraper.py      # screener.in web scraping
│   ├── stock_news_analyzer.py   # Tavily news search + LLM analysis
│   ├── sentiment_analyzer_adanos.py  # Multi-source sentiment (News/Yahoo/Twitter/Reddit)
│   ├── reddit_sentiment.py      # Reddit sentiment analysis
│   ├── chart_visualizer.py      # Plotly chart generation
│   ├── data_fetcher.py          # yfinance data pipeline
│   ├── data_validator.py        # Data validation utilities
│   ├── bulk_stock_selector.py   # Batch stock analysis
│   ├── stock_symbol_resolver.py # Tavily-based symbol resolution
│   ├── tradingview_ideas_scraper.py  # Trade ideas scraper (subprocess wrapper)
│   ├── _tradingview_worker.py   # Playwright worker (runs in subprocess)
│   └── pdf_text_summarizer.py   # PDF content extraction
│
├── drawing_instruction/         # TradingView drawing generation module
│   ├── api_server.py            # Flask API server (port 5001)
│   ├── drawing_generator.py     # Main orchestrator
│   ├── llm_drawing_generator.py # LLM-enhanced generator
│   ├── zone_detector.py         # Supply/demand zone detection
│   ├── pattern_detector.py      # Candlestick pattern recognition
│   ├── llm_pattern_detector.py  # LLM-powered pattern detection
│   ├── indicator_calculator.py  # Bollinger Bands, RSI, MACD
│   ├── smc_indicator.py         # Smart Money Concepts
│   ├── supply_demand_indicator.py  # Supply/demand indicators
│   ├── liquidity_sweeps.py      # Liquidity sweep detection
│   ├── macd_indicator.py        # MACD calculations
│   ├── json_builder.py          # TradingView JSON format builder
│   ├── price_fetcher.py         # yfinance OHLCV data
│   ├── api_price_fetcher.py     # External API price fetcher
│   ├── symbol_resolver.py       # Symbol resolution for drawings
│   └── chat_drawing_agent.py    # Chat-based drawing generation
│
├── database_utility/            # Database layer
│   └── database.py              # PostgreSQL (psycopg2) operations
│
├── .devcontainer/               # GitHub Codespaces / VS Code dev container
│   └── devcontainer.json
│
├── backup-all/                  # Legacy backup files (DO NOT MODIFY)
├── downloads/                   # Downloaded PDF reports
├── pdf_summaries/               # Generated PDF summaries
├── generated_ai_scripts/        # AI-generated content output
├── PPT_json/                    # PowerPoint JSON data
├── test/                        # Test JSON data files
│
├── requirements.txt             # Python dependencies
├── pyproject.toml               # Project metadata
├── stock_list_sample.txt        # Sample stock list for bulk analysis
├── CLAUDE.md                    # AI assistant instructions
└── .env                         # Environment variables (not committed)
```

---

## Getting Started

### Prerequisites

- **Python 3.11+** (3.14 supported, devcontainer uses 3.11)
- **PostgreSQL** database (for persisting analysis results)
- **Playwright browsers** (for TradingView scraping)
- API keys (see [Environment Variables](#environment-variables))

### Installation

```bash
# 1. Clone the repository
git clone <repo-url>
cd trader_agent_17_03

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install Playwright browsers (required for Trade Ideas tab)
playwright install chromium

# 5. Set up environment variables
cp .env.example .env  # Then edit .env with your API keys
```

### Environment Variables

Create a `.env` file in the project root with the following:

```env
# LLM Provider (OpenRouter)
OPENROUTER_API_KEY=your_openrouter_api_key
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

# Web Search (Tavily)
TAVILY_API_KEY=your_tavily_api_key

# Google AI (multiple rotating keys for rate limit handling)
GOOGLE_API_KEY_1=your_google_key_1
GOOGLE_API_KEY_2=your_google_key_2
GOOGLE_API_KEY_3=your_google_key_3
GOOGLE_API_KEY_4=your_google_key_4

# Database (PostgreSQL)
DB_HOST=localhost
DB_PORT=5432
DB_NAME=stock_analysis
DB_USER=your_db_user
DB_PASSWORD=your_db_password

# Observability (LangSmith)
LANGSMITH_API_KEY=your_langsmith_key
LANGSMITH_PROJECT=trader_agent
LANGSMITH_TRACING=true
```

**Where to get API keys:**

| Key | Provider | URL |
|-----|----------|-----|
| `OPENROUTER_API_KEY` | OpenRouter | https://openrouter.ai/keys |
| `TAVILY_API_KEY` | Tavily | https://tavily.com |
| `GOOGLE_API_KEY_*` | Google AI Studio | https://aistudio.google.com/apikey |
| `LANGSMITH_API_KEY` | LangSmith | https://smith.langchain.com |

### Running the App

```bash
# Start the Streamlit UI (main entry point)
streamlit run app_advanced.py --server.address=0.0.0.0 --server.port=8501

# (Optional) Start the Drawing Instruction API server
python -m drawing_instruction.api_server  # serves on port 5001
```

The app will be available at **http://localhost:8501**

---

## Application Views

The sidebar provides navigation between these views:

### 1. Fundamental Analysis / Chat

The primary interface. Three tabs:

**Chat Tab**
- Type a stock name (e.g., "TCS", "Reliance", "HDFC Bank") or a question
- The agent validates the stock, fetches data, and generates a comprehensive report
- Supports follow-up questions about the analyzed stock
- Auto-generates PDF reports after analysis
- For business groups (e.g., "Tata"), shows all group companies for selection

**Sentiment Analysis Tab** (appears after stock is analyzed)
- Real-time multi-source sentiment scoring (0-100)
- Sources: News articles, Yahoo Finance analyst ratings, Twitter/X, Reddit
- Positive/negative factor breakdown
- Future Outlook with AI-summarized news from top financial sources

**Trade Ideas Tab** (appears after stock is analyzed)
- Scrapes top 9 trading ideas from TradingView
- Shows real chart preview images in a 3-column grid
- Displays author, likes, date, and description
- Each card links to the full idea on TradingView
- Results cached for 10 minutes

### 2. Presentation Viewer

View and download auto-generated PowerPoint presentations:
- Bilingual support (English + Hindi)
- Company overview, financials, SWOT, charts

### 3. Data Dashboard

Interactive data exploration:
- Price history charts (Plotly)
- Volume analysis
- Financial metric visualizations
- Competitor comparison

### 4. Bulk Stock Analyzer

Analyze multiple stocks simultaneously:
- Upload a stock list or use the sample list
- Filter by percentage drop from all-time high
- Export results as CSV
- Visual comparison charts

### 5. Drawing Generator

Generate TradingView-compatible technical drawings:
- Supply/demand zones
- Candlestick patterns
- Bollinger Bands, RSI, MACD overlays
- Smart Money Concept indicators
- Export as TradingView JSON

### 6. System Info

System diagnostics:
- API key status
- Database connection test
- LLM model info
- Environment details

---

## Core Modules

### Agent Pipeline (`agent1.py` + `tools.py`)

**`agent1.py`** — The brain of the system:
- Defines a `pydantic-ai` `Agent` with a comprehensive system prompt
- Manages `ConversationState` (chat history, current stock, analysis state)
- Registers ~15 tools the agent can call
- Includes `MERGED_STOCKS` registry for corporate action handling
- Key tools:
  - `validate_and_get_stock` — Stock search + validation via LLM + yfinance
  - `analyze_stock_request` — Full analysis pipeline
  - `handle_greeting` — Conversational greetings
  - `handle_stock_selection` — User selection from multiple matches
  - `handle_trader_question` — Follow-up Q&A about analyzed stocks
  - `perform_scenario_analysis` — What-if scenarios
  - `generate_presentation` — PPT generation trigger

**`tools.py`** — Data fetching and analysis:
- `StockTools` class with static methods
- yfinance integration for price/financial data
- Tavily web search for news and context
- screener.in scraping for Indian market data
- LLM-powered SWOT analysis, business overview, and report generation
- PDF generation via ReportLab
- PowerPoint generation via python-pptx

**Important**: All tool functions must return `ToolResponse` objects using `create_tool_response()`.

### Drawing Instruction Module

Self-contained Flask-based module (`drawing_instruction/`):

```bash
# Run standalone
python -m drawing_instruction.api_server  # Port 5001

# API Endpoints
POST /api/generate          # Full analysis (zones + patterns + indicators)
POST /api/zones             # Supply/demand zones only
POST /api/patterns          # Candlestick patterns only
POST /api/indicators        # Technical indicators only
GET  /api/trade-ideas/<SYM> # TradingView trade ideas
```

**Zone Detection Pipeline:**
1. Fetch OHLCV data (yfinance or external API)
2. Detect base candles (low volatility, consolidation)
3. Identify impulse moves (strong directional candles)
4. Validate departure patterns (institutional accumulation/distribution)
5. Output supply/demand zones with price levels

### Utilities

| Module | Purpose |
|--------|---------|
| `model_config.py` | OpenRouter LLM configuration. All LLM calls route through here. |
| `stock_news_analyzer.py` | Tavily search → article extraction → LLM sentiment + summary. Uses fallback model chain. |
| `sentiment_analyzer_adanos.py` | Multi-source sentiment aggregation (News + Yahoo + Twitter + Reddit). |
| `tradingview_ideas_scraper.py` | Subprocess-based Playwright scraper for TradingView ideas. |
| `_tradingview_worker.py` | Actual Playwright browser automation (runs in isolated subprocess). |
| `pdf_generator.py` | ReportLab PDF with charts, tables, and formatted analysis. |
| `ppt_generator.py` | python-pptx PowerPoint decks with company data. |
| `screener_scraper.py` | Scrapes financial ratios and data from screener.in. |
| `stock_symbol_resolver.py` | Resolves company names to NSE/BSE tickers via Tavily + yfinance. |
| `bulk_stock_selector.py` | Batch analysis with filtering and comparison. |
| `chart_visualizer.py` | Plotly chart generation for the Data Dashboard. |

### Database

**`database_utility/database.py`** — PostgreSQL storage:
- `StockDatabase` class with connect/disconnect lifecycle
- Stores full analysis results, sentiment data, technical metrics
- Methods: `save_analysis()`, `get_latest_analysis()`, `update_sentiment()`
- Connection via env vars: `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`

---

## Data Models

Defined in `models.py`:

```
CompanyData (root model)
├── symbol: str
├── name: str
├── snapshot: CompanySnapshot
│   ├── company_name, ticker_symbol, exchange
│   ├── sector, industry, headquarters
│   └── ceo, employees, website
├── business_overview: BusinessOverview
│   ├── description, main_products
│   └── revenue_sources, growth_segments
├── financials: FinancialData
│   ├── Income: revenue, net_profit, ebitda, eps
│   ├── Balance: total_assets, debt_to_equity, cash
│   ├── Cash Flow: operating_cf, free_cf
│   ├── Valuation: pe, pb, peg, ev_ebitda
│   └── Margins: profit, operating, gross
├── market_data: MarketData
│   ├── Prices: current, 52w high/low, overall high/low
│   ├── Holdings: promoter, FII, DII
│   ├── Performance: day/week/month/year changes
│   └── Competitors: list of peer companies
├── swot: SWOTAnalysis
│   └── strengths, weaknesses, opportunities, threats
├── news: List[Dict]
└── timestamp: datetime
```

---

## Key Patterns & Conventions

1. **ToolResponse Wrapper** — Every agent tool must return a `ToolResponse`:
   ```python
   return create_tool_response("result text", "tool_name")
   ```

2. **Indian Stock Symbols** — NSE stocks use `.NS` suffix, BSE uses `.BO`:
   ```
   RELIANCE.NS, TCS.NS, HDFCBANK.NS, INFY.BO
   ```

3. **LLM Provider** — All LLM calls go through **OpenRouter** (not direct OpenAI):
   ```python
   from utils.model_config import get_model, get_client
   ```

4. **Fallback Model Chain** — News analysis uses multiple models with fallback:
   ```
   openai/gpt-oss-120b → google/gemini-2.0-flash-001 → meta-llama/llama-3.1-8b-instruct → openai/gpt-4o-mini
   ```

5. **Playwright in Subprocess** — TradingView scraping runs Playwright in a separate process to avoid Python 3.14/Windows asyncio issues:
   ```
   tradingview_ideas_scraper.py → subprocess.run → _tradingview_worker.py
   ```

6. **Session State Caching** — Streamlit `st.session_state` is used extensively:
   - `company_data` — Current analyzed stock
   - `messages` — Chat history
   - `sentiment_data` — Cached sentiment results
   - `trade_ideas_{SYMBOL}` — Cached trade ideas

7. **Do Not Modify** — `backup-all/` contains legacy code for reference only.

---

## Corporate Actions Handling

The system includes a `MERGED_STOCKS` registry in `agent1.py` that handles Indian stock market mergers and delistings:

| Merged Entity | Successor | Date |
|---------------|-----------|------|
| HDFC Ltd (HDFC.NS) | HDFC Bank (HDFCBANK.NS) | July 2023 |
| IDFC Ltd (IDFC.NS) | IDFC First Bank (IDFCFIRSTB.NS) | Oct 2023 |
| Vijaya Bank | Bank of Baroda (BANKBARODA.NS) | April 2019 |
| Dena Bank | Bank of Baroda (BANKBARODA.NS) | April 2019 |
| Andhra Bank | Union Bank (UNIONBANK.NS) | April 2020 |
| Corporation Bank | Union Bank (UNIONBANK.NS) | April 2020 |
| Syndicate Bank | Canara Bank (CANBK.NS) | April 2020 |
| Allahabad Bank | Indian Bank (INDIANB.NS) | April 2020 |
| Gruh Finance | Bandhan Bank (BANDHANBNK.NS) | Oct 2019 |

**Behavior**: If a user searches for a merged stock, the system automatically redirects to the successor with an explanatory note. Delisted stocks with no successor show an error message.

To add new mergers, update the `MERGED_STOCKS` dict and `MERGED_NAME_ALIASES` in `agent1.py`.

---

## Deployment

### Dev Container (GitHub Codespaces)

The project includes a `.devcontainer/devcontainer.json` for one-click setup:

```bash
# Automatically:
# - Uses Python 3.11 image
# - Installs requirements.txt
# - Starts Streamlit on port 8501
```

### Manual Deployment

```bash
# 1. Install dependencies
pip install -r requirements.txt
playwright install chromium

# 2. Set up PostgreSQL database
createdb stock_analysis

# 3. Configure .env file with all API keys

# 4. Run
streamlit run app_advanced.py --server.address=0.0.0.0 --server.port=8501

# (Optional) Run drawing API server
python -m drawing_instruction.api_server &
```

### Docker (example)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt && playwright install chromium --with-deps
COPY . .
EXPOSE 8501 5001
CMD ["streamlit", "run", "app_advanced.py", "--server.address=0.0.0.0", "--server.port=8501"]
```

---

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `No module named 'playwright'` | Playwright not installed | `pip install playwright && playwright install chromium` |
| `NotImplementedError` in Playwright | Python 3.14 asyncio issue on Windows | Already handled — scraper uses subprocess. Ensure `_tradingview_worker.py` exists in `utils/`. |
| `status_code: 500` from LLM | OpenRouter model temporarily down | Retry. Free models (`gpt-oss-120b`) can be flaky under load. |
| `Exceeded maximum retries for output validation` | LLM response doesn't match expected Pydantic schema | Usually a model issue. Check `model_config.py` model name. |
| `'NoneType' object is not subscriptable` | LLM returned `null` content | Null checks are in place. If persists, try a different model in `model_config.py`. |
| Database connection errors | PostgreSQL not running or wrong credentials | Check `DB_*` env vars. Ensure PostgreSQL is running. |
| Trade Ideas shows no images | TradingView DOM changed | Update selectors in `utils/_tradingview_worker.py`. |
| Sentiment analysis fails | Adanos API or Tavily API down | Check API keys. Falls back to neutral (50/100) score. |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Streamlit |
| AI Agent | pydantic-ai |
| LLM Provider | OpenRouter (supports 100+ models) |
| Financial Data | yfinance, screener.in |
| Web Search | Tavily API |
| Sentiment | Adanos API, Reddit API |
| Web Scraping | Playwright (Chromium) |
| Charts | Plotly |
| PDF Reports | ReportLab |
| Presentations | python-pptx |
| Database | PostgreSQL (psycopg2) |
| Observability | LangSmith |
| Dev Container | VS Code / GitHub Codespaces |

---

## License

Private repository. All rights reserved.
