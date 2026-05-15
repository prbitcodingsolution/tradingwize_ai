"""
================================================================================
 LEARNING SCRIPT: Fetching Stock News from Financial Domains using Tavily API
================================================================================

PURPOSE (for intern):
    This is a self-contained educational script that shows how to fetch the
    latest stock-related news from a curated list of financial news websites
    using the Tavily Search API.

    Read top-to-bottom. Every section has comments explaining WHAT and WHY.

WHAT IS TAVILY?
    Tavily (https://tavily.com) is a search API designed for AI/LLM apps.
    Unlike Google, it returns clean JSON results with title, URL, and a short
    content snippet — perfect for feeding into an LLM or storing in a DB.

    You need a free API key from https://app.tavily.com/

HOW TO RUN:
    1. Install dependencies:
           pip install requests python-dotenv

    2. Create a `.env` file in the same folder containing:
           TAVILY_API_KEY=tvly-xxxxxxxxxxxxxxxxxxxx

    3. Run from the terminal:
           python learn_tavily_news_fetcher.py TCS
           python learn_tavily_news_fetcher.py RELIANCE
           python learn_tavily_news_fetcher.py INFY

WHAT THE SCRIPT DOES (high-level flow):
    1. Loads the Tavily API key from the .env file.
    2. Takes a stock symbol (e.g. TCS) as input.
    3. Builds 2 search queries about that stock.
    4. Calls the Tavily API, restricting search to 14 trusted finance domains.
    5. Cleans + de-duplicates the results.
    6. Prints the news list as a nicely-formatted JSON.

================================================================================
"""

import os
import sys
import json
import logging
from typing import List, Dict

import requests
from dotenv import load_dotenv


load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


TAVILY_API_URL = "https://api.tavily.com/search"

NEWS_DOMAINS: List[str] = [
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


def call_tavily(query: str, api_key: str, domains: List[str], max_results: int = 10) -> List[Dict]:
    """
    Send a single search request to the Tavily API.

    Args:
        query:        The search phrase (e.g. "TCS stock latest news").
        api_key:      Your Tavily API key (from https://app.tavily.com/).
        domains:      List of websites Tavily should restrict the search to.
                      This is the KEY trick — it filters out junk sites and
                      keeps results to trusted financial publishers.
        max_results:  How many search results to ask for (1–20 typical).

    Returns:
        A list of raw result dicts from Tavily. Each dict contains:
            - "title":   headline of the article
            - "url":     full link to the article
            - "content": short snippet (~300 chars) from the article body

    Notes for intern:
        - `search_depth="advanced"` gives better content snippets but uses more
          Tavily credits. Use "basic" if you want to save credits.
        - `include_answer=False` because we don't need Tavily's own AI summary —
          we'll generate our own summary later with an LLM.
        - We use a 15-second timeout to avoid hanging if Tavily is slow.
    """
    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": "advanced",
        "max_results": max_results,
        "include_answer": False,
        "include_domains": domains,
    }

    try:
        response = requests.post(TAVILY_API_URL, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        return data.get("results", [])
    except requests.exceptions.RequestException as exc:
        logger.error(f"Tavily request failed for query '{query}': {exc}")
        return []
    except ValueError:
        logger.error(f"Tavily returned invalid JSON for query '{query}'")
        return []


def fetch_news_for_symbol(symbol: str, api_key: str) -> List[Dict]:
    """
    Fetch news for a stock symbol from all configured financial news domains.

    Strategy:
        - Run TWO different queries to widen the news coverage.
          One query targets analytical articles, the other targets price-action
          news. More queries = better recall, but uses more Tavily credits.
        - De-duplicate by lower-cased first 60 chars of the title (cheap and
          effective). Two articles with the same title from different sites
          would otherwise pollute the list.

    Args:
        symbol:  Stock ticker, with or without exchange suffix. Examples:
                 "TCS", "TCS.NS", "RELIANCE.NS", "INFY.BO".
        api_key: Tavily API key.

    Returns:
        A list of clean news dicts ready to display, store in a DB, or feed
        into an LLM. Each dict has:
            - title      (str)  article headline
            - publisher  (str)  domain name (e.g. "moneycontrol.com")
            - link       (str)  full URL
            - summary    (str)  short snippet (up to 300 chars)
            - source     (str)  always "tavily" — useful when you mix sources
    """
    clean_symbol = symbol.split(".")[0].upper()

    queries = [
        f"{clean_symbol} stock latest news analysis 2025 2026",
        f"{clean_symbol} share price news today recent",
    ]

    collected: List[Dict] = []
    seen_titles = set()

    for query in queries:
        logger.info(f"Searching Tavily for: {query!r}")
        raw_results = call_tavily(query, api_key, NEWS_DOMAINS, max_results=10)

        for item in raw_results:
            title = (item.get("title") or "").strip()
            url = (item.get("url") or "").strip()
            snippet = (item.get("content") or "").strip()[:300]

            if not title or not url or len(title) < 10:
                continue

            dedup_key = title.lower()[:60]
            if dedup_key in seen_titles:
                continue
            seen_titles.add(dedup_key)

            try:
                publisher = url.split("/")[2].replace("www.", "")
            except IndexError:
                publisher = "unknown"

            collected.append({
                "title": title,
                "publisher": publisher,
                "link": url,
                "summary": snippet,
                "source": "tavily",
            })

    logger.info(f"Collected {len(collected)} unique news items for {symbol}")
    return collected


def main():
    """Command-line entry point so the intern can try this script easily."""
    if len(sys.argv) < 2:
        print("Usage: python learn_tavily_news_fetcher.py <STOCK_SYMBOL>")
        print("Example: python learn_tavily_news_fetcher.py TCS")
        sys.exit(1)

    symbol = sys.argv[1]

    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        print("ERROR: TAVILY_API_KEY is missing.")
        print("Create a .env file with: TAVILY_API_KEY=tvly-xxxxxxxxxxxx")
        sys.exit(1)

    news_items = fetch_news_for_symbol(symbol, api_key)

    if not news_items:
        print(f"No news found for {symbol}.")
        return

    print(json.dumps(news_items, indent=2, ensure_ascii=False))
    print(f"\nTotal news items: {len(news_items)}")


if __name__ == "__main__":
    main()
