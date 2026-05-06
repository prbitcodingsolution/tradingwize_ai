# -*- coding: utf-8 -*-
"""
Background task launchers for dashboard-driven analyses.

When the Data Dashboard finishes loading a stock, we want to start the
slower downstream analyses (market sentiment, TradingView trade ideas)
in the background — so they're already cached by the time the user
navigates to the Fundamental Analysis tabs.

Streamlit re-executes the main script on every user interaction, which
means any analysis running inline in a tab's render path gets killed
if the user switches views mid-run and has to restart on the next
visit. Running these tasks in background `threading.Thread`s — tagged
with Streamlit's `add_script_run_ctx` so they can read/write
`st.session_state` — sidesteps that: the thread keeps running through
script reruns and writes its result to session state whenever it
finishes. The next rerun after completion picks the cached result up.

Status convention per stock symbol:

    st.session_state["_bg_<task>_status_<SYMBOL>"] ∈
        {"running", "done", "error", "stale"}

Callers should treat a missing key as "not started yet".
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

import streamlit as st

try:
    # Streamlit ≥ 1.20
    from streamlit.runtime.scriptrunner import add_script_run_ctx
except Exception:  # pragma: no cover
    # Older Streamlit fallback
    from streamlit.scriptrunner import add_script_run_ctx  # type: ignore


# ──────────────────────────────────────────────────────────────────
# Status helpers
# ──────────────────────────────────────────────────────────────────

def _status_key(task: str, symbol: str) -> str:
    return f"_bg_{task}_status_{symbol}"


def bg_status(task: str, symbol: str) -> str:
    """Return the status of a named background task for a stock symbol.

    Args:
        task:   Short task name (e.g. "sentiment", "trade_ideas").
        symbol: Stock ticker (e.g. "TCS.NS").

    Returns:
        "running" | "done" | "error" | "not_started"
    """
    return st.session_state.get(_status_key(task, symbol), "not_started")


def _set_status(task: str, symbol: str, status: str) -> None:
    st.session_state[_status_key(task, symbol)] = status


# ──────────────────────────────────────────────────────────────────
# Task runners
# ──────────────────────────────────────────────────────────────────

def _build_market_senti_text(stock_name: str, result: dict) -> tuple[str, str]:
    """Compose the market_senti block that gets persisted to the DB.
    Returns (text, status) — status is lowercased overall_label so the
    status column is 'bullish' / 'bearish' / 'neutral' / etc.
    """
    if not result:
        return "", "neutral"

    _score = result.get("overall_score", 0)
    _label = result.get("overall_label", "Neutral")
    _status = str(_label).lower()

    _news = result.get("news_sentiment", {}) or {}
    _yahoo = result.get("yahoo_sentiment", {}) or {}
    _twitter = result.get("twitter_sentiment", {}) or {}
    _reddit = result.get("reddit_sentiment", {}) or {}

    _lines = [
        f"📈 Current Market Sentiment for {stock_name}",
        "",
        f"Overall Score: {_score}/100",
        f"Overall Label: {_label}",
        "",
        "Source Breakdown:",
        f"  • News:    {_news.get('sentiment_score', 'N/A')}/100 "
        f"({_news.get('sentiment_label', 'N/A')})",
        f"  • Yahoo:   {_yahoo.get('sentiment_score', 'N/A')}/100 "
        f"({_yahoo.get('analyst_rating', 'N/A')})",
        f"  • Twitter: {_twitter.get('sentiment_score', 'N/A')}/100 "
        f"({_twitter.get('sentiment_label', 'N/A')})",
        f"  • Reddit:  {_reddit.get('sentiment_score', 'N/A')}/100 "
        f"({_reddit.get('sentiment_label', 'N/A')})",
    ]

    # Positive factors
    _pos = _news.get("positive_points") or []
    _neg = _news.get("negative_points") or []
    if _pos and _pos != ["Insufficient data"]:
        _lines += ["", "✅ Positive Factors:"]
        for _p in _pos[:8]:
            _lines.append(f"  • {_p}")
    if _neg and _neg != ["Insufficient data"]:
        _lines += ["", "⚠️ Negative Factors:"]
        for _n in _neg[:8]:
            _lines.append(f"  • {_n}")

    _final = result.get("final_analysis") or result.get("market_mood") or ""
    if _final:
        _lines += ["", "💭 Market Mood & Analysis:", _final]

    return "\n".join(_lines), _status


def persist_market_sentiment(stock_symbol: str, stock_name: str, result: dict) -> None:
    """Persist the news/Yahoo/Reddit/Twitter market-sentiment status.

    Historical note: this used to write the formatted sentiment block into
    the ``stock_analysis.market_senti`` column. That column has since
    been renamed to ``fii_dii_analysis`` and repurposed for the FII/DII
    institutional analysis, so only the status label is written now —
    into ``current_market_senti_status``. The full sentiment pipeline is
    also gated off via ``_SENTIMENT_BG_DISABLED``, so in practice this
    function is dormant; it's kept as a no-op-safe hook in case the
    client re-enables live sentiment later.

    Best-effort — any DB failure is logged but doesn't affect the UI.
    """
    try:
        _text, _status = _build_market_senti_text(stock_name, result)
        if not _text:
            print(f"⚠️ [sentiment] empty market_senti text for {stock_symbol}; skipping DB write")
            return
        from database_utility.database import StockDatabase
        _db = StockDatabase()
        if _db.connect():
            _db.update_sentiment_columns(
                stock_symbol=stock_symbol,
                current_market_senti_status=_status,
            )
            _db.disconnect()
        else:
            print(f"⚠️ [sentiment] DB connect failed while persisting {stock_symbol}")
    except Exception as _e:
        print(f"⚠️ [sentiment] market_senti DB persist failed for {stock_symbol}: {_e}")


# Back-compat alias so the existing private call inside _run_sentiment
# keeps working without further renames.
_persist_market_sentiment = persist_market_sentiment


def _run_sentiment(stock_name: str, stock_symbol: str) -> None:
    """Run full market sentiment pipeline and cache the result.

    Writes:
        st.session_state.sentiment_data  (dict | None)
        st.session_state.sentiment_stock (str)
        _bg_sentiment_status_<SYMBOL>    ("done" | "error")
        stock_analysis.market_senti + current_market_senti_status  (DB)
    """
    try:
        from utils.sentiment_analyzer_adanos import analyze_stock_sentiment
        ticker = stock_symbol.split(".")[0]
        result = analyze_stock_sentiment(stock_name, stock_symbol, ticker)
        st.session_state["sentiment_data"] = result
        st.session_state["sentiment_stock"] = stock_symbol
        # Persist the computed sentiment to the DB so FinRobot / the PPT
        # generator / any other consumer that reads `market_senti` from
        # stock_analysis sees real data instead of NULL.
        _persist_market_sentiment(stock_symbol, stock_name, result)
        _set_status("sentiment", stock_symbol, "done")
        print(f"✅ [bg] sentiment done for {stock_symbol}")
    except Exception as e:
        st.session_state[f"_bg_sentiment_error_{stock_symbol}"] = str(e)
        _set_status("sentiment", stock_symbol, "error")
        print(f"⚠️ [bg] sentiment failed for {stock_symbol}: {e}")


def _run_trade_ideas(clean_symbol: str, exchange: str, stock_symbol: str, limit: int = 9) -> None:
    """Run the TradingView trade-ideas scraper and cache the result.

    Writes:
        st.session_state[f"trade_ideas_{clean_symbol}"]  (dict | None)
        st.session_state.trade_ideas_stock               (str)
        _bg_trade_ideas_status_<SYMBOL>                  ("done" | "error")

    Empty / error scrapes (e.g. scraper returned `{"ideas": [], "error":
    "No ideas found"}` because the subprocess died early) are NOT cached
    as "done" — they are surfaced as "error" so the Trade Ideas tab
    shows its retry UI instead of a permanent empty-state banner.
    """
    try:
        from utils.tradingview_ideas_scraper import scrape_trade_ideas
        # ── Phase-3 timing: Trade Ideas (TradingView) [background task] ──
        from utils.timing import phase_timer as _phase_timer
        with _phase_timer("Trade Ideas (TradingView)", symbol=str(stock_symbol).strip().upper()):
            result = scrape_trade_ideas(clean_symbol, exchange, limit)
        _ideas = (result or {}).get("ideas") or []
        _err = (result or {}).get("error")

        if _ideas:
            st.session_state[f"trade_ideas_{clean_symbol}"] = result
            st.session_state["trade_ideas_stock"] = stock_symbol
            _set_status("trade_ideas", stock_symbol, "done")
            print(f"✅ [bg] trade_ideas done for {stock_symbol} ({len(_ideas)} ideas)")
            return

        # Empty result — treat as error so the UI offers a retry rather
        # than a cached "No ideas found" sticky state.
        _msg = _err or "scraper returned no ideas"
        st.session_state[f"_bg_trade_ideas_error_{stock_symbol}"] = _msg
        _set_status("trade_ideas", stock_symbol, "error")
        print(f"⚠️ [bg] trade_ideas empty for {stock_symbol}: {_msg}")
    except Exception as e:
        st.session_state[f"_bg_trade_ideas_error_{stock_symbol}"] = str(e)
        _set_status("trade_ideas", stock_symbol, "error")
        print(f"⚠️ [bg] trade_ideas failed for {stock_symbol}: {e}")


# ──────────────────────────────────────────────────────────────────
# Public kickoff API
# ──────────────────────────────────────────────────────────────────

def _spawn(target: Callable, args: tuple, thread_name: Optional[str] = None) -> None:
    """Spawn a daemon thread with the Streamlit script-run context
    attached so it can read/write session state safely.
    """
    t = threading.Thread(target=target, args=args, daemon=True, name=thread_name)
    try:
        add_script_run_ctx(t)
    except Exception as e:
        # If ctx attachment fails, the thread can still run — just won't see
        # live session_state writes until the main run reads the container.
        print(f"⚠️ [bg] add_script_run_ctx failed: {e}")
    t.start()


def _should_start(task: str, symbol: str, has_cached: bool) -> bool:
    """Decide whether to spawn a new thread for this task.

    - If cached data already exists for this symbol → no.
    - If a task for this symbol is already running → no (don't duplicate).
    - If a prior attempt errored → yes, retry on demand.
    - Otherwise → yes.
    """
    status = bg_status(task, symbol)
    if has_cached and status == "done":
        return False
    if status == "running":
        return False
    return True


# ── Feature flag ──────────────────────────────────────────────────
# Client removed the Sentiment Analysis tab from the UI and asked us
# to stop processing market sentiment to cut News/Tavily/Twitter/Reddit
# API costs. Flip back to False to re-enable the full pipeline.
_SENTIMENT_BG_DISABLED = True


def kickoff_dashboard_bg_tasks(
    stock_name: str,
    stock_symbol: str,
    clean_symbol: str,
    exchange: str,
) -> None:
    """Start trade-ideas background work for the currently displayed
    stock. (Sentiment kickoff is gated by ``_SENTIMENT_BG_DISABLED`` —
    the sentiment code is preserved but not triggered.)
    Idempotent — safe to call on every dashboard render; duplicate
    kickoffs for the same symbol are suppressed.
    """
    if not stock_symbol:
        return

    # Sentiment — gated off per client cost-reduction request
    if not _SENTIMENT_BG_DISABLED:
        sent_cached = (
            "sentiment_data" in st.session_state
            and st.session_state.get("sentiment_stock") == stock_symbol
        )
        if _should_start("sentiment", stock_symbol, sent_cached):
            _set_status("sentiment", stock_symbol, "running")
            print(f"🚀 [bg] launching sentiment for {stock_symbol}")
            _spawn(
                _run_sentiment,
                args=(stock_name, stock_symbol),
                thread_name=f"bg-sentiment-{stock_symbol}",
            )

    # Trade ideas
    ti_cache_key = f"trade_ideas_{clean_symbol}"
    ti_cached = (
        ti_cache_key in st.session_state
        and st.session_state.get("trade_ideas_stock") == stock_symbol
    )
    if _should_start("trade_ideas", stock_symbol, ti_cached):
        _set_status("trade_ideas", stock_symbol, "running")
        print(f"🚀 [bg] launching trade_ideas for {stock_symbol}")
        _spawn(
            _run_trade_ideas,
            args=(clean_symbol, exchange, stock_symbol, 9),
            thread_name=f"bg-trade-ideas-{stock_symbol}",
        )


def reset_bg_status_for_symbol(symbol: str) -> None:
    """Wipe status + cache flags for a symbol. Call on explicit refresh."""
    for task in ("sentiment", "trade_ideas"):
        st.session_state.pop(_status_key(task, symbol), None)
        st.session_state.pop(f"_bg_{task}_error_{symbol}", None)
