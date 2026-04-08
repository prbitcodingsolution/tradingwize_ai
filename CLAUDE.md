# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI-powered stock analysis agent built with **pydantic-ai** and **Streamlit**. Focuses on Indian stock market (NSE/BSE) analysis with technical analysis, fundamental research, sentiment analysis, and automated TradingView drawing generation.

## Running the App

```bash
# Install dependencies
pip install -r requirements.txt

# Run the Streamlit UI (main entry point)
streamlit run app_advanced.py --server.address=0.0.0.0 --server.port=8501

# Run the drawing instruction API server
python -m drawing_instruction.api_server  # serves on port 5001

# Generate TradingView drawings from CLI
python -m drawing_instruction.drawing_generator SYMBOL TIMEFRAME PERIOD
```

## Architecture

### Core Agent Pipeline

- **`agent1.py`** — Main pydantic-ai `Agent` definition with system prompt, conversation state (`ConversationState` dataclass), and all tool registrations. Uses `ToolResponse` wrapper for all tool outputs. Orchestrates stock validation, data gathering, analysis, and report generation.
- **`tools.py`** — `StockTools` class with all stock analysis tools: yfinance data fetching, Tavily web search, screener.in scraping, financial metrics, SWOT analysis, news gathering, PDF summary generation, PPT creation, and LLM-powered analysis via OpenAI client.
- **`app_advanced.py`** — Streamlit frontend (~295K lines). Handles chat UI, message history, chart rendering (Plotly), drawing generator integration, MCP scanner panel, and response formatting.
- **`models.py`** — Pydantic models for all data structures: `StockValidation`, `CompanyData`, `FinancialData`, `MarketData`, `SWOTAnalysis`, `CompanyReport`, `ScenarioAnalysis`, `Summary`.

### MCP (Model Context Protocol) Integration

- **`mcp_agent.py`** — Separate pydantic-ai agent for TradingView MCP technical scanning. Has its own `MCPConversationState` and `ToolResponse`.
- **`mcp_scanner_agent_tradingview.py`** — TradingView scanner integration using MCP tools.
- **`mcp_config.json`** — MCP server config pointing to TradingView MCP via `uv tool run`.

### Drawing Instruction Module (`drawing_instruction/`)

Self-contained module for generating TradingView-compatible drawing instructions:
- `price_fetcher.py` / `api_price_fetcher.py` — OHLCV data from yfinance
- `zone_detector.py` — Supply/demand zone detection with institutional validation (base → impulse → departure)
- `pattern_detector.py` / `llm_pattern_detector.py` — Candlestick pattern recognition
- `indicator_calculator.py` — Bollinger Bands, RSI, MACD
- `smc_indicator.py` / `supply_demand_indicator.py` / `liquidity_sweeps.py` — Smart Money Concept indicators
- `json_builder.py` — Builds TradingView JSON format
- `drawing_generator.py` / `llm_drawing_generator.py` — Main orchestrator
- `api_server.py` — Flask API (port 5001)
- `chat_drawing_agent.py` — Chat-based drawing generation

### Utilities (`utils/`)

- `model_config.py` — LLM provider config. Uses **OpenRouter** (not direct OpenAI). Configures `pydantic_ai.models.openai.OpenAIModel` with OpenRouter base URL and API key.
- `pdf_generator.py` — ReportLab PDF generation for stock reports
- `ppt_generator.py` — python-pptx PowerPoint generation
- `screener_scraper.py` — Web scraping from screener.in
- `stock_news_analyzer.py` — News analysis pipeline
- `sentiment_analyzer_adanos.py` — Sentiment analysis
- `reddit_sentiment.py` — Reddit sentiment analysis
- `chart_visualizer.py` — Plotly chart generation
- `data_fetcher.py` / `data_validator.py` — Data pipeline utilities
- `bulk_stock_selector.py` — Batch stock selection
- `stock_symbol_resolver.py` — Symbol resolution (NSE/BSE)

### Database (`database_utility/`)

- `database.py` — PostgreSQL via psycopg2. `StockDatabase` class stores analyzed stock data with technical metrics. Connection params from env vars (`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`).

## Key Configuration

- **LLM Provider**: OpenRouter (env: `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`). Model configured in `utils/model_config.py`.
- **Search**: Tavily API (env: `TAVILY_API_KEY`) for web search in tools.
- **Google AI**: Multiple rotating keys (env: `GOOGLE_API_KEY_1` through `GOOGLE_API_KEY_4`).
- **Tracing**: LangSmith integration (env: `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_TRACING`).
- **Database**: PostgreSQL (env: `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`).
- All config loaded via `python-dotenv` from `.env` file.

## Important Patterns

- All agent tool functions must return `ToolResponse` objects (wrapper with `content`, `tool_name`, `is_tool_response` fields). Use `create_tool_response()` helper.
- Indian stocks use `.NS` suffix for NSE (e.g., `RELIANCE.NS`, `TCS.NS`).
- The `backup-all/` directory contains legacy/backup versions of files — do not modify.
- `generated_ai_scripts/` and `PPT_json/` are output directories for generated content.
- Python version: 3.14+ per pyproject.toml, but devcontainer uses 3.11.
