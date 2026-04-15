"""
FastAPI Backend for Stock News Summary Generation
Endpoint: GET /api/v1/news/summary?symbol=TCS.NS

Reads stored news from the stock_news database table and generates
an LLM-powered summary using OpenRouter (openai-oss model).

Run: uvicorn api_news_summary:app --port 5002
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import logging

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="TradingWize News Summary API",
    description="Fetches stored stock news and generates AI-powered summaries",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Response Models ---

class NewsItem(BaseModel):
    title: str
    publisher: str = ""
    link: str = ""
    summary: str = ""
    source: str = ""
    fetched_at: Optional[str] = None


class NewsSummaryResponse(BaseModel):
    symbol: str
    stock_name: Optional[str] = None
    news_count: int
    news: List[NewsItem]
    summary: str
    generated_at: str


# --- News domains for Tavily search ---
_NEWS_DOMAINS = [
    "moneycontrol.com",
    "economictimes.indiatimes.com",
    "livemint.com",
    "financialexpress.com",
    "simplywall.st",
    "reuters.com",
    "investing.com",
    "tipranks.com",
    "morningstar.in",
    "stockanalysis.com",
    "in.tradingview.com",
    "kotakneo.com",
    "koyfin.com",
    "forecaster.biz",
]


def _fetch_fresh_news(symbol: str) -> list:
    """
    Fetch fresh news from multiple financial news domains via Tavily API.
    Returns list of dicts with title, publisher, link, summary, source.
    """
    try:
        from tools import StockTools
    except ImportError:
        # Fallback: call Tavily directly
        return _fetch_news_via_tavily_direct(symbol)

    clean_sym = symbol.split('.')[0]
    queries = [
        f"{clean_sym} stock latest news analysis 2025 2026",
        f"{clean_sym} share price news today recent",
    ]

    news = []
    seen = set()

    for query in queries:
        try:
            results, _ = StockTools._search_with_tavily(query, domain=_NEWS_DOMAINS)
            for r in results:
                title = (r.get('title') or '').strip()
                url = (r.get('url') or '').strip()
                content = (r.get('content') or '').strip()[:300]
                if not title or len(title) < 10 or not url:
                    continue
                key = title.lower()[:60]
                if key in seen:
                    continue
                seen.add(key)
                try:
                    publisher = url.split('/')[2].replace('www.', '')
                except Exception:
                    publisher = 'Web'
                news.append({
                    'title': title,
                    'publisher': publisher,
                    'link': url,
                    'summary': content,
                    'source': 'tavily',
                })
        except Exception as e:
            logger.warning(f"News query failed: {e}")

    return news


def _fetch_news_via_tavily_direct(symbol: str) -> list:
    """Fallback: call Tavily API directly without StockTools."""
    import os
    import requests as _req

    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return []

    clean_sym = symbol.split('.')[0]
    query = f"{clean_sym} stock latest news analysis 2026"

    try:
        resp = _req.post("https://api.tavily.com/search", json={
            "api_key": api_key,
            "query": query,
            "search_depth": "advanced",
            "max_results": 10,
            "include_answer": False,
            "include_domains": _NEWS_DOMAINS,
        }, timeout=15)
        data = resp.json()
        news = []
        for r in data.get("results", []):
            title = (r.get('title') or '').strip()
            url = (r.get('url') or '').strip()
            if title and url and len(title) > 10:
                try:
                    publisher = url.split('/')[2].replace('www.', '')
                except Exception:
                    publisher = 'Web'
                news.append({
                    'title': title,
                    'publisher': publisher,
                    'link': url,
                    'summary': (r.get('content') or '')[:300],
                    'source': 'tavily',
                })
        return news
    except Exception as e:
        logger.error(f"Direct Tavily call failed: {e}")
        return []


# --- Endpoints ---

@app.get("/")
async def root():
    """Root endpoint — shows available routes."""
    return {
        "service": "TradingWize News Summary API",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": {
            "summary": "/api/v1/news/summary?symbol=TCS",
            "list": "/api/v1/news/list?symbol=TCS",
            "health": "/health",
        },
    }


@app.get("/api/v1/news/summary", response_model=NewsSummaryResponse)
async def get_news_summary(
    symbol: str = Query(..., description="Stock symbol (e.g., TCS.NS, RELIANCE.NS, TCS, RELIANCE)"),
    limit: int = Query(20, ge=1, le=50, description="Max news items to return"),
):
    """
    Fetch FRESH news from 14 financial news domains, save to DB, and return with LLM summary.

    Always fetches live news — never returns stale cached data.
    """
    symbol = symbol.strip().upper()
    if not any(symbol.endswith(s) for s in ['.NS', '.BO', '.L', '.N']):
        symbol = f"{symbol}.NS"

    from database_utility.database import StockDatabase

    # Step 1: Always fetch fresh news from 14 domains
    logger.info(f"Fetching fresh news for {symbol} from 14 news domains...")
    news_rows = _fetch_fresh_news(symbol)[:limit]

    # Step 2: Save fresh news to DB
    if news_rows:
        try:
            db = StockDatabase()
            if db.connect():
                db.create_news_table()
                _name = symbol.replace('.NS', '').replace('.BO', '')
                db.save_news(symbol, _name, news_rows)
                db.disconnect()
                logger.info(f"Saved {len(news_rows)} news items to DB for {symbol}")
        except Exception as e:
            logger.warning(f"DB save failed: {e}")

    if not news_rows:
        raise HTTPException(
            status_code=404,
            detail=f"No news found for {symbol}. Try with a different symbol or check the symbol format (e.g., TCS.NS)."
        )

    # Build news items
    stock_name = symbol.split('.')[0]
    try:
        _sn_db = StockDatabase()
        if _sn_db.connect():
            _sn_db.cursor.execute(
                "SELECT stock_name FROM stock_news WHERE stock_symbol = %s LIMIT 1", (symbol,)
            )
            _sn_row = _sn_db.cursor.fetchone()
            if _sn_row and _sn_row[0]:
                stock_name = _sn_row[0]
            _sn_db.disconnect()
    except Exception:
        pass

    news_items = [
        NewsItem(
            title=row.get("title", ""),
            publisher=row.get("publisher", ""),
            link=row.get("link", ""),
            summary=row.get("summary", ""),
            source=row.get("source", ""),
            fetched_at=str(row["fetched_at"]) if row.get("fetched_at") else None,
        )
        for row in news_rows
    ]

    # Step 2: Generate LLM summary
    try:
        from utils.model_config import guarded_llm_call

        # Build news context for LLM
        news_text = "\n".join(
            f"- {item.title}" + (f": {item.summary}" if item.summary else "")
            for item in news_items
        )

        prompt = f"""You are a financial news analyst. Summarize the following recent news for {stock_name or symbol} into a concise, investor-focused summary.

Stock: {stock_name or symbol} ({symbol})
Number of articles: {len(news_items)}

Recent News:
{news_text}

Write a 3-5 paragraph summary covering:
1. Key developments and corporate actions
2. Market sentiment and analyst views
3. Potential impact on stock price and outlook

Be factual, concise, and focus on what matters to investors. Use specific details from the news.
Do not use markdown formatting. Write plain text paragraphs."""

        response = guarded_llm_call(
            messages=[
                {"role": "system", "content": "You are a financial news analyst. Provide concise, factual summaries for investors."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1500,
        )

        summary_text = (response.choices[0].message.content or "").strip()
        if not summary_text:
            summary_text = "Summary generation failed. Please review the individual news items below."

    except Exception as e:
        logger.error(f"LLM summary generation failed for {symbol}: {e}")
        summary_text = f"Summary generation unavailable: {e}. Please review the individual news items below."

    return NewsSummaryResponse(
        symbol=symbol,
        stock_name=stock_name,
        news_count=len(news_items),
        news=news_items,
        summary=summary_text,
        generated_at=datetime.utcnow().isoformat(),
    )


@app.get("/api/v1/news/list")
async def list_news(
    symbol: str = Query(..., description="Stock symbol (e.g., TCS.NS)"),
    limit: int = Query(20, ge=1, le=50),
    max_age_hours: int = Query(72, ge=1, le=720),
):
    """Get stored news items without generating a summary (faster)."""
    symbol = symbol.strip().upper()

    try:
        from database_utility.database import StockDatabase
        db = StockDatabase()
        if not db.connect():
            raise HTTPException(status_code=503, detail="Database connection failed")

        db.create_news_table()
        news_rows = db.get_news(symbol, limit=limit, max_age_hours=max_age_hours)
        db.disconnect()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

    return {
        "symbol": symbol,
        "news_count": len(news_rows),
        "news": news_rows,
    }


@app.get("/health")
async def health():
    return {"status": "ok", "service": "news-summary-api"}
