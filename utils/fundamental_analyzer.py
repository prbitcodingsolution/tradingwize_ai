"""Enhanced fundamental analysis pipeline for Indian (NSE/BSE) stocks.

Eight sub-analyses run in parallel and produce a single
`models.FundamentalAnalysis` payload:

  1. 5Y NSE financials   — screener.in P&L / Balance Sheet / Cash Flow tables
                           + shareholding pattern + corporate actions
  2. Director profiles   — Tavily search (annual reports, NSE filings) +
                           LLM extraction
  3. Political relations — Tavily news / ECI-related search + LLM tagging
                           (best-effort flag; ECI has no public API and the
                           electoral-bond data was struck down in Feb 2024)
  4. News & sentiment    — Tavily multi-domain search + LLM sentiment tag
                           (extends api_news_summary._fetch_fresh_news)
  5. Legal cases         — Tavily search across SEBI / SFIO / court /
                           defaulter terms + LLM extraction (best-effort —
                           eCourts / SEBI have no public structured feed)
  6. Promoter investments — Tavily search for related-party / shareholding
                           disclosures + LLM extraction (best-effort —
                           MCA21 cross-stake feed is paid)
  7. Portfolio performance — yfinance lookup for each listed portfolio
                           company found in (6)
  8. Pledge data         — screener.in promoter-pledge table

Persistence: results are written to the `stock_fundamentals` PostgreSQL
table (Alembic 0004). Callers can re-use a cached snapshot via the
`max_age_hours` parameter on `analyze_fundamentals` rather than re-paying
the Tavily / LLM cost on every render.

Failure mode policy: every sub-fetcher is wrapped in a try/except that
falls back to a `SectionStatus(available=False, ...)` shape. A failure in
one section MUST NOT break the others — the Streamlit renderer relies on
the full payload always being parseable, just with some blocks empty.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from models import (
    CorporateAction,
    DirectorBlock,
    DirectorProfile,
    FinancialTrend,
    FinancialTrendPoint,
    FundamentalAnalysis,
    InvestmentsBlock,
    LegalBlock,
    LegalCase,
    NewsBlock,
    NewsHeadline,
    PledgeBlock,
    PledgeEvent,
    PledgePoint,
    PoliticalBlock,
    PoliticalConnection,
    PortfolioPerformance,
    PromoterInvestment,
    SectionStatus,
    ShareholdingSnapshot,
)
from utils.screener_scraper import (
    BASE_URL as SCREENER_BASE_URL,
    HEADERS as SCREENER_HEADERS,
    parse_number,
    search_stock_on_screener,
)

logger = logging.getLogger(__name__)


ANALYSIS_VERSION = "v2"  # bump invalidates pre-pledge-NSE-fallback caches
# Each section is mostly I/O wait (Tavily + LLM + screener.in HTTP), not
# CPU — so the limit is Tavily's per-key concurrency, not local threads.
# Running all 7 sections concurrently (was 4) brings wall-clock down to
# roughly max(slowest section) instead of summing pairs of slow ones.
_MAX_PARALLEL_FETCHERS = 8
_TAVILY_TIMEOUT = 15
_FETCH_TIMEOUT = 15
_LLM_MAX_TOKENS = 1200
# Hard ceiling on how long the orchestrator will wait for a single
# section's future to complete. A typical fresh run finishes in 60–90s
# total; we set this generously so it never trips on a healthy run, but
# tight enough that one hung Tavily / LLM call cannot keep the whole UI
# stuck on the spinner forever. When a section trips this budget the
# orchestrator falls back to that section's default and logs a warning.
_SECTION_TIMEOUT_SEC = 90.0
# Per-LLM-call HTTP timeout — propagated to the OpenAI/OpenRouter client.
# Long-tail LLM responses are the most common cause of section hangs;
# capping the request at this value lets the section error out cleanly
# instead of blocking the orchestrator indefinitely.
_LLM_HTTP_TIMEOUT_SEC = 60.0

_NEWS_DOMAINS = [
    "moneycontrol.com",
    "economictimes.indiatimes.com",
    "livemint.com",
    "financialexpress.com",
    "business-standard.com",
    "thehindubusinessline.com",
    "reuters.com",
    "bloombergquint.com",
    "ndtvprofit.com",
    "investing.com",
]

_LEGAL_DOMAINS = _NEWS_DOMAINS + [
    "sebi.gov.in",
    "bseindia.com",
    "nseindia.com",
    "rbi.org.in",
]


# ─────────────────────────────────────────────────────────
# Progress logging — visible timing for every step
# ─────────────────────────────────────────────────────────
#
# The 5-Year Analysis pipeline runs ~7 sections in parallel, each with
# its own Tavily/LLM/scrape sub-steps. Without per-step timing the user
# sees only a spinner. `_log()` writes a timestamped line to stdout
# (visible in the Streamlit server console) AND forwards it to an
# optional sink — used by the UI to mirror the run inside an expander.
#
# The sink is registered for the duration of a single `analyze_
# fundamentals` call via the `progress_sink()` context manager. The
# ThreadPoolExecutor's worker threads inherit the same module-level
# reference, so a sink set on the orchestrator thread is visible to
# every section worker without explicit propagation.

_progress_sink: Optional[Callable[[str], None]] = None
_progress_sink_lock = threading.Lock()


def _log(message: str) -> None:
    """Emit a timestamped progress log line.

    Always prints to stdout (visible wherever Streamlit / the CLI is
    running). When a sink callable is registered via `progress_sink()`,
    each line is also forwarded to it — this is how the Streamlit UI
    mirrors the run inside an expander so users can see what each
    section is doing in real time.
    """
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    line = f"[FA {ts}] {message}"
    try:
        print(line, flush=True)
    except Exception:
        # stdout encoding issues (Windows cp1252 vs unicode emoji) must
        # never abort the analysis — log to the project logger and move on.
        logger.debug("stdout write failed for FA log line: %r", line)
    sink = _progress_sink
    if sink is not None:
        try:
            sink(line)
        except Exception as exc:
            logger.debug("progress sink raised: %s", exc)


@contextmanager
def progress_sink(sink: Optional[Callable[[str], None]]) -> Iterator[None]:
    """Register a per-run progress callback.

    Use as a `with` block around `analyze_fundamentals(...)`. Inside the
    block every `_log()` call also invokes `sink(line)`. The previous
    sink (usually None) is restored on exit, even on exception.
    """
    global _progress_sink
    with _progress_sink_lock:
        prev = _progress_sink
        _progress_sink = sink
    try:
        yield
    finally:
        with _progress_sink_lock:
            _progress_sink = prev


def _fmt_secs(seconds: float) -> str:
    """Compact duration formatter used in every section's "done" line."""
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.2f}s"
    return f"{seconds // 60:.0f}m{seconds % 60:.1f}s"


# ─────────────────────────────────────────────────────────
# Tavily + LLM helpers (shared by every "best-effort" fetcher)
# ─────────────────────────────────────────────────────────

def _tavily_search(query: str, *, domains: Optional[List[str]] = None,
                   max_results: int = 5) -> List[Dict[str, Any]]:
    """Run a Tavily search and return the raw result list.

    Prefer `StockTools._search_with_tavily` because it has the project's
    rate-limit accounting; fall back to a direct API call only when the
    helper isn't importable (CLI / test paths). Network or auth errors
    return [] — the caller treats that as "section unavailable".
    """
    try:
        from tools import StockTools  # heavy import; do it lazily
        results, _ = StockTools._search_with_tavily(query, domain=domains)
        return results or []
    except Exception as exc:
        logger.debug("Tavily via StockTools failed (%s); trying direct.", exc)

    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return []
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "search_depth": "advanced",
                "max_results": max_results,
                "include_answer": False,
                "include_domains": domains,
            },
            timeout=_TAVILY_TIMEOUT,
        )
        return (resp.json() or {}).get("results", []) or []
    except Exception as exc:
        logger.warning("Tavily direct call failed: %s", exc)
        return []


def _tavily_search_many(
    queries: List[str],
    *,
    domains: Optional[List[str]] = None,
    max_results: int = 5,
    max_workers: int = 4,
    label: str = "tavily",
) -> List[Dict[str, Any]]:
    """Fan out multiple Tavily queries in parallel and dedupe results by URL.

    Each Tavily `search_depth=advanced` call takes 5–15s; running 2–4
    queries serially used to dominate every section's wall-clock time.
    With a small thread pool we collapse that to roughly the *slowest*
    individual call.

    Returns results in the original query order (with duplicates removed)
    so callers that rely on per-query ranking still get sensible output.

    The `label` is used purely for log lines so the user can tell which
    section a given Tavily batch belongs to.
    """
    if not queries:
        return []
    per_query: List[List[Dict[str, Any]]] = [[] for _ in queries]
    workers = max(1, min(max_workers, len(queries)))
    _log(f"  [{label}] Tavily fan-out: {len(queries)} queries × {workers} workers …")
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_tavily_search, q, domains=domains, max_results=max_results): idx
            for idx, q in enumerate(queries)
        }
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                per_query[idx] = fut.result() or []
            except Exception as exc:
                logger.debug("Parallel Tavily query #%d failed: %s", idx, exc)
                per_query[idx] = []

    seen: set = set()
    merged: List[Dict[str, Any]] = []
    for batch in per_query:
        for r in batch:
            url = (r.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            merged.append(r)
    raw_total = sum(len(b) for b in per_query)
    _log(
        f"  [{label}] Tavily done: {raw_total} raw → {len(merged)} unique "
        f"results in {_fmt_secs(time.time() - t0)}"
    )
    return merged


def _llm_extract_json(prompt: str, *, schema_hint: str,
                      max_tokens: int = _LLM_MAX_TOKENS,
                      label: str = "llm") -> Optional[Any]:
    """Ask the project LLM (OpenRouter via `guarded_llm_call`) to return
    JSON for the given prompt. Returns None on any failure — every caller
    must tolerate that.

    The `label` is used purely for log lines so the user can tell which
    section a given LLM call belongs to (e.g. `directors`, `news`,
    `news.minimal-retry`).
    """
    try:
        from utils.model_config import guarded_llm_call
    except Exception as exc:
        logger.warning("guarded_llm_call unavailable: %s", exc)
        return None

    system = (
        "You are a financial data extractor. Read the supplied search "
        "results / raw text and emit STRICT JSON matching the schema "
        f"described below. No markdown fences, no commentary.\n\n"
        f"Schema: {schema_hint}\n\n"
        "If the input doesn't contain the requested facts, return the "
        "schema with empty arrays / null fields — do NOT invent data."
    )

    _log(
        f"  [{label}] LLM call: prompt={len(prompt):,} chars, "
        f"max_tokens={max_tokens}, timeout={_LLM_HTTP_TIMEOUT_SEC:.0f}s …"
    )
    t0 = time.time()
    try:
        resp = guarded_llm_call(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            timeout=_LLM_HTTP_TIMEOUT_SEC,
        )
    except Exception:
        # Some OpenRouter models reject response_format; retry without.
        try:
            resp = guarded_llm_call(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=max_tokens,
                timeout=_LLM_HTTP_TIMEOUT_SEC,
            )
        except Exception as exc:
            _log(f"  [{label}] LLM FAILED after {_fmt_secs(time.time() - t0)}: {exc}")
            logger.warning("LLM extraction failed: %s", exc)
            return None
    _log(f"  [{label}] LLM responded in {_fmt_secs(time.time() - t0)}")

    text = ((resp.choices[0].message.content if resp and resp.choices else "") or "").strip()
    if not text:
        logger.warning("LLM returned empty content for prompt with %d chars", len(prompt))
        return None
    # Strip ```json fences when the model ignored the instruction.
    fenced = re.match(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Outermost-object slice — handles "Here is the JSON: { ... }".
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    # Truncation recovery — when the model's response was cut off mid-output
    # by max_tokens, walk the string and auto-close open strings/brackets/braces
    # at the latest safe cut point. Same pattern used in drawing_explainer.
    if start != -1:
        repaired = _close_open_json(text[start:])
        if repaired is not None:
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                pass
    logger.warning(
        "LLM emitted unparseable output (%d chars). First 200: %r",
        len(text), text[:200],
    )
    return None


_DANGLING_KEY_RE = re.compile(r',?\s*"[^"\\]*(?:\\.[^"\\]*)*"\s*:\s*$')


def _close_open_json(s: str) -> Optional[str]:
    """Best-effort repair for JSON truncated mid-output. Walks the string,
    records every position where it would be safe to chop and append the
    right closers, then tries those candidates from latest to earliest.
    Drops any trailing half-written value/key automatically.

    Mirrors the helper used by the drawing-explainer's `_parse_json` —
    see drawing_explainer/llm_explainer.py for the full rationale."""
    if not s:
        return None
    in_string = False
    escape = False
    stack: List[str] = []
    candidates: List[Tuple[int, List[str]]] = [(0, [])]
    for i, ch in enumerate(s):
        if escape:
            escape = False
            continue
        if in_string:
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = False
                candidates.append((i + 1, list(stack)))
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            stack.append("}")
            continue
        if ch == "[":
            stack.append("]")
            continue
        if ch in "}]":
            if stack:
                stack.pop()
            candidates.append((i + 1, list(stack)))
            continue
        if ch == ",":
            candidates.append((i, list(stack)))
            continue
    for cut, snap in reversed(candidates):
        prefix = s[:cut].rstrip(" \t\n\r,:")
        if not prefix:
            continue
        prefix = _DANGLING_KEY_RE.sub("", prefix).rstrip(" \t\n\r,:")
        candidate = prefix + "".join(reversed(snap))
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            continue
    return None


def _tavily_results_to_blob(results: List[Dict[str, Any]], limit: int = 5,
                            chars_per_result: int = 600) -> str:
    """Flatten Tavily results into a readable blob for the LLM.

    `chars_per_result` defaults to 600 (keeps news / brief sections
    cheap). For sections that need to extract structured detail
    (directors, cross-holdings, legal cases), bump this to 2000+ so the
    LLM actually has the names/numbers to extract — Tavily snippets
    starting from the page top often haven't reached the relevant block
    by char 600 (Wikipedia infobox, annual-report leadership pages).
    """
    bits: List[str] = []
    for r in results[:limit]:
        title = (r.get("title") or "").strip()
        url = (r.get("url") or "").strip()
        body = (r.get("content") or "").strip()[:chars_per_result]
        if not title and not body:
            continue
        bits.append(f"TITLE: {title}\nURL: {url}\nCONTENT: {body}\n---")
    return "\n".join(bits) or "(no search results)"


# Heuristic for pages that almost always carry director / management info
# inline. When a Tavily result hits one of these patterns we fetch the
# page directly with BeautifulSoup and add ~3000 chars of cleaned text
# to the LLM blob — Tavily snippets are too short to surface the actual
# board listing on most company sites.
_LEADERSHIP_PATH_HINTS = (
    "leadership", "leader", "board", "director", "management",
    "governance", "about-us", "about_us", "about/team", "team",
    "key-people", "kmp", "investor-relations/corporate",
)


# Short-lived cache for the screener.in company page. Both
# `_fetch_financial_trend` (section 1) and `_fetch_pledge` (section 8)
# scrape the same URL — without this cache each call paid the
# 0.5–1.5s screener.in round-trip twice per run.
#
# A *per-symbol* lock guards the first fetch so concurrent sections
# don't race-fire two HTTP requests for the same page. The outer
# cache map lock is only held while creating / looking up the
# per-symbol lock, never during the network call.
_SCREENER_PAGE_TTL_SEC = 300  # 5 min — well past any single analyze run
_screener_page_cache: Dict[str, Tuple[float, Optional[BeautifulSoup], Optional[str]]] = {}
_screener_symbol_locks: Dict[str, threading.Lock] = {}
_screener_map_lock = threading.Lock()


def _get_screener_soup(symbol: str) -> Tuple[Optional[BeautifulSoup], Optional[str], Optional[str]]:
    """Fetch the screener.in company page once and share the parsed
    BeautifulSoup across sections.

    Returns `(soup, url, error)`:
      • soup  — parsed page on success, None on failure
      • url   — the resolved screener.in URL (None when the search step
                failed to find the company)
      • error — human-readable error string when soup is None, else None
    """
    clean = (symbol or "").strip().upper().replace(".NS", "").replace(".BO", "")
    if not clean:
        return None, None, "Empty symbol"

    now = time.time()
    with _screener_map_lock:
        cached = _screener_page_cache.get(clean)
        if cached and (now - cached[0]) < _SCREENER_PAGE_TTL_SEC:
            _, soup, url = cached
            _log(f"  [screener] cache HIT for {clean} (age {_fmt_secs(now - cached[0])})")
            return soup, url, None if soup else "Stock not found on screener.in"
        sym_lock = _screener_symbol_locks.setdefault(clean, threading.Lock())

    with sym_lock:
        # Re-check inside the per-symbol lock — another waiter may have
        # populated the cache while we were queued.
        with _screener_map_lock:
            cached = _screener_page_cache.get(clean)
            if cached and (time.time() - cached[0]) < _SCREENER_PAGE_TTL_SEC:
                _, soup, url = cached
                _log(f"  [screener] cache HIT for {clean} (after wait)")
                return soup, url, None if soup else "Stock not found on screener.in"

        _log(f"  [screener] cache MISS for {clean} — searching company URL …")
        t_search = time.time()
        url = search_stock_on_screener(symbol)
        if not url:
            _log(f"  [screener] {clean} not found on screener.in "
                 f"(search took {_fmt_secs(time.time() - t_search)})")
            with _screener_map_lock:
                _screener_page_cache[clean] = (time.time(), None, None)
            return None, None, "Stock not found on screener.in"
        _log(f"  [screener] URL resolved in {_fmt_secs(time.time() - t_search)}: {url}")

        try:
            t_get = time.time()
            resp = requests.get(url, headers=SCREENER_HEADERS, timeout=_FETCH_TIMEOUT)
            if resp.status_code != 200:
                raise RuntimeError(f"screener.in returned HTTP {resp.status_code}")
            soup = BeautifulSoup(resp.text, "html.parser")
            _log(
                f"  [screener] page fetched + parsed in "
                f"{_fmt_secs(time.time() - t_get)} ({len(resp.content):,} bytes)"
            )
        except Exception as exc:
            _log(f"  [screener] fetch FAILED: {exc}")
            return None, url, f"screener.in fetch failed: {exc}"

        with _screener_map_lock:
            _screener_page_cache[clean] = (time.time(), soup, url)
        return soup, url, None


def _fetch_page_text(url: str, *, max_chars: int = 3000,
                     timeout: int = _FETCH_TIMEOUT) -> str:
    """Best-effort scrape of a webpage's visible text. Returns "" on any
    failure — caller should treat that as "no extra content"."""
    try:
        resp = requests.get(url, headers=SCREENER_HEADERS, timeout=timeout)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
            tag.decompose()
        text = soup.get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]
    except Exception as exc:
        logger.debug("Direct page fetch failed for %s: %s", url, exc)
        return ""


def _fetch_page_text_many(urls: List[str], *, max_chars: int = 3000,
                          max_workers: int = 3) -> List[Tuple[str, str]]:
    """Fan out a small batch of `_fetch_page_text` calls in parallel.

    Returns `[(url, body)]` preserving the input order, with empty strings
    for URLs that failed. Used by the directors section so the 2–3
    leadership-page fetches don't add 5–10s of serial latency on top of
    the Tavily round-trip.
    """
    if not urls:
        return []
    bodies: List[str] = [""] * len(urls)
    workers = max(1, min(max_workers, len(urls)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_fetch_page_text, u, max_chars=max_chars): idx
            for idx, u in enumerate(urls)
        }
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                bodies[idx] = fut.result() or ""
            except Exception as exc:
                logger.debug("Parallel page fetch #%d failed: %s", idx, exc)
                bodies[idx] = ""
    return list(zip(urls, bodies))


def _is_leadership_url(url: str) -> bool:
    if not url:
        return False
    lower = url.lower()
    return any(hint in lower for hint in _LEADERSHIP_PATH_HINTS)


# ─────────────────────────────────────────────────────────
# Section 1 — 5-year financial trends (screener.in extension)
# ─────────────────────────────────────────────────────────

def _parse_screener_table(soup: BeautifulSoup, section_id: str) -> Tuple[List[str], Dict[str, List[Optional[float]]]]:
    """Pull a screener.in metric table by its anchor section id (e.g.
    "profit-loss", "balance-sheet", "cash-flow", "quarters"). Returns the
    column headers (period labels) and a dict {row_label: [values]}."""
    section = soup.find("section", id=section_id)
    if section is None:
        return [], {}
    table = section.find("table")
    if table is None:
        return [], {}

    head = table.find("thead")
    headers: List[str] = []
    if head is not None:
        headers = [th.get_text(strip=True) for th in head.find_all("th")][1:]  # drop the row-label col

    rows: Dict[str, List[Optional[float]]] = {}
    body = table.find("tbody")
    if body is None:
        return headers, rows
    for tr in body.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        label = cells[0].get_text(" ", strip=True)
        # screener.in indents derived rows (e.g. "Net Profit") with a leading
        # button/span — collapse whitespace so lookups by label work.
        label = re.sub(r"\s+", " ", label).strip()
        values = [parse_number(c.get_text(strip=True)) for c in cells[1:]]
        rows[label] = values
    return headers, rows


def _build_trend_points(headers: List[str], pnl: Dict[str, List[Optional[float]]],
                       bs: Dict[str, List[Optional[float]]],
                       ratios: Dict[str, List[Optional[float]]],
                       last_n: int = 5) -> List[FinancialTrendPoint]:
    """Pivot screener.in's row-per-metric tables into one
    FinancialTrendPoint per column (year/quarter), keeping the most recent
    `last_n` columns."""
    if not headers:
        return []

    def _series(d: Dict[str, List[Optional[float]]], *names: str) -> List[Optional[float]]:
        for name in names:
            for key in d:
                if key.lower().startswith(name.lower()):
                    series = d[key]
                    if len(series) >= len(headers):
                        return series[-len(headers):]
                    pad = [None] * (len(headers) - len(series))
                    return pad + series
        return [None] * len(headers)

    revenue = _series(pnl, "Sales", "Revenue")
    ebitda = _series(pnl, "Operating Profit", "EBITDA")
    pat = _series(pnl, "Net Profit", "PAT")
    eps = _series(pnl, "EPS")
    op_margin = _series(pnl, "OPM")
    debt = _series(bs, "Borrowings", "Total Debt", "Debt")
    roe = _series(ratios, "ROE", "Return on Equity")
    roce = _series(ratios, "ROCE", "Return on Capital")

    points: List[FinancialTrendPoint] = []
    for i, period in enumerate(headers[-last_n:]):
        idx = len(headers) - last_n + i if len(headers) >= last_n else i
        if idx < 0:
            continue
        points.append(FinancialTrendPoint(
            period=period,
            revenue=revenue[idx] if idx < len(revenue) else None,
            ebitda=ebitda[idx] if idx < len(ebitda) else None,
            pat=pat[idx] if idx < len(pat) else None,
            eps=eps[idx] if idx < len(eps) else None,
            debt=debt[idx] if idx < len(debt) else None,
            roe=roe[idx] if idx < len(roe) else None,
            roce=roce[idx] if idx < len(roce) else None,
            operating_margin=op_margin[idx] if idx < len(op_margin) else None,
        ))
    return points


def _build_shareholding(soup: BeautifulSoup) -> List[ShareholdingSnapshot]:
    """Parse the shareholding-pattern table — wide format with one column
    per quarter and rows for Promoters / FIIs / DIIs / Government / Public."""
    headers, rows = _parse_screener_table(soup, "shareholding")
    if not headers:
        return []

    def _series_or_none(*names: str) -> List[Optional[float]]:
        for name in names:
            for key in rows:
                if key.lower().startswith(name.lower()):
                    return rows[key][-len(headers):] if rows[key] else []
        return []

    promoters = _series_or_none("Promoters", "Promoter")
    fiis = _series_or_none("FIIs", "FII")
    diis = _series_or_none("DIIs", "DII")
    public = _series_or_none("Public")
    govt = _series_or_none("Government")

    out: List[ShareholdingSnapshot] = []
    for i, q in enumerate(headers[-12:]):  # last 3 years of quarterly data
        idx = len(headers) - min(len(headers), 12) + i
        out.append(ShareholdingSnapshot(
            quarter=q,
            promoter=promoters[idx] if idx < len(promoters) else None,
            fii=fiis[idx] if idx < len(fiis) else None,
            dii=diis[idx] if idx < len(diis) else None,
            public=public[idx] if idx < len(public) else None,
            government=govt[idx] if idx < len(govt) else None,
        ))
    return out


def _build_corporate_actions(soup: BeautifulSoup) -> List[CorporateAction]:
    """Look for screener.in's corporate-actions / announcements blurbs.
    Best-effort — screener doesn't render this as a consistent table."""
    actions: List[CorporateAction] = []
    for sec_id in ("documents", "announcements"):
        sec = soup.find("section", id=sec_id)
        if sec is None:
            continue
        for li in sec.find_all("li")[:10]:
            text = li.get_text(" ", strip=True)
            lower = text.lower()
            action_type = None
            for hint, tag in (("dividend", "dividend"), ("buyback", "buyback"),
                              ("split", "split"), ("bonus", "bonus"),
                              ("rights", "rights")):
                if hint in lower:
                    action_type = tag
                    break
            if action_type is None:
                continue
            actions.append(CorporateAction(period="recent", action_type=action_type, detail=text[:200]))
    return actions


def _fetch_financial_trend(symbol: str, name: str) -> FinancialTrend:
    """Section 1 — extend screener_scraper to pull P&L / BS / quarterly
    trend tables + shareholding pattern + announcements."""
    trend = FinancialTrend()
    soup, url, error = _get_screener_soup(symbol)
    if soup is None:
        trend.status = SectionStatus(
            available=False, confidence="low",
            notes=error or "Could not load screener.in page",
            sources=[url] if url else [],
        )
        return trend

    pnl_headers, pnl_rows = _parse_screener_table(soup, "profit-loss")
    bs_headers, bs_rows = _parse_screener_table(soup, "balance-sheet")
    _, ratios = _parse_screener_table(soup, "ratios")
    q_headers, q_rows = _parse_screener_table(soup, "quarters")

    if pnl_headers:
        # P&L and BS share the same column count on screener.in but BS
        # rows are addressed under its own table — we still pivot by P&L
        # headers since those are the canonical FY labels.
        trend.yearly = _build_trend_points(pnl_headers, pnl_rows, bs_rows, ratios, last_n=5)
    if q_headers:
        trend.quarterly = _build_trend_points(q_headers, q_rows, {}, {}, last_n=8)

    trend.shareholding = _build_shareholding(soup)
    trend.corporate_actions = _build_corporate_actions(soup)

    if not trend.yearly and not trend.quarterly:
        trend.status = SectionStatus(
            available=False, confidence="low",
            notes="No P&L or quarterly tables found on screener.in",
            sources=[url],
        )
    else:
        trend.status = SectionStatus(
            available=True,
            confidence="high" if len(trend.yearly) >= 4 else "medium",
            notes=f"{len(trend.yearly)} fiscal year(s) parsed",
            sources=[url],
        )
    return trend


# ─────────────────────────────────────────────────────────
# Section 2 — director / promoter background
# ─────────────────────────────────────────────────────────

def _fetch_directors(symbol: str, name: str) -> DirectorBlock:
    """Tavily search + direct leadership-page scrape + LLM extraction.

    Three-stage pipeline because Tavily snippets alone aren't enough:
      1. Two complementary Tavily queries (governance + named-roles) so
         we cover both annual-report style pages AND
         "CEO / chairman / MD" pages where actual names appear.
      2. For any result whose URL looks like a leadership / board /
         governance page, fetch the page directly with BeautifulSoup
         and add ~3000 chars of cleaned text — Tavily snippets are too
         short to reach the board listing on most company sites.
      3. LLM extracts a structured list. Permissive prompt — we want
         every named person mentioned as a director / KMP, even when
         the background is sparse.
    """
    block = DirectorBlock()
    clean = symbol.replace(".NS", "").replace(".BO", "")

    # Stage 1 — two complementary Tavily queries, fanned out in parallel
    # and deduped by URL. Each `search_depth=advanced` call is 5–15s; the
    # fan-out collapses that to roughly the slowest single call.
    queries = [
        f"{name} {clean} board of directors management profile background "
        f"other directorships annual report corporate governance",
        f"{name} {clean} CEO chairman managing director CFO COO "
        f"executives leadership team key managerial personnel 2025 2026",
    ]
    results = _tavily_search_many(queries, max_results=6, label="directors")
    if not results:
        block.status = SectionStatus(
            available=False, confidence="low",
            notes="No Tavily results returned for directors / management",
        )
        return block

    # Stage 2 — Tavily blob with deeper snippets PLUS direct page fetches
    # for HTML leadership pages. We DROP results whose URL ends in `.pdf`
    # before passing to the LLM — Tavily's PDF text extraction is noisy
    # (page headers / table cells flattened to gibberish) and tends to
    # poison the LLM's JSON output. The PDFs still appear in `sources`
    # so the user can see what was checked.
    html_results = [
        r for r in results
        if not (r.get("url") or "").lower().endswith(".pdf")
    ]
    if not html_results:
        # All hits were PDFs — keep a smaller subset so the LLM at least
        # has SOMETHING to chew on, but cap snippet length to limit noise.
        html_results = results
        snippet_chars = 1200
    else:
        snippet_chars = 2500

    blob_parts: List[str] = [
        _tavily_results_to_blob(html_results, limit=6, chars_per_result=snippet_chars)
    ]
    leadership_urls = [
        (r.get("url") or "").strip() for r in html_results
        if _is_leadership_url(r.get("url") or "")
    ][:3]
    for url, body in _fetch_page_text_many(leadership_urls, max_chars=3500):
        if body:
            blob_parts.append(
                f"DIRECT-FETCH FROM: {url}\nBODY: {body}\n---"
            )

    blob = "\n".join(blob_parts)

    # Stage 3 — LLM extraction with a permissive prompt. We ask for
    # ANY named person who appears to be on the board / in KMP, even
    # if their background is one line — it's better to surface a name
    # with a "designation pending" entry than to drop it entirely.
    schema = (
        '{"directors": [{"name": str, "designation": str|null, '
        '"since_year": str|null, "din": str|null, "background": str|null, '
        '"other_directorships": [str], "source_links": [str]}]}'
    )
    prompt = (
        f"Company: {name} ({clean}).\n\n"
        f"From the search results AND directly-fetched leadership pages "
        f"below, extract EVERY named individual who appears to be a "
        f"director, executive, or key managerial personnel of this "
        f"company. Be permissive:\n"
        f"  • Include the person even if only their name + designation "
        f"is given (e.g. 'K Krithivasan, CEO and MD').\n"
        f"  • Include both executive directors AND independent / "
        f"non-executive directors when listed.\n"
        f"  • For `since_year`, extract the year the person took their "
        f"CURRENT role (e.g. '2023' from 'Director since 2023', "
        f"'June 2024' from 'appointed Chairman in June 2024'). If the "
        f"input only says 'serves on the board' with no date, leave "
        f"null — do NOT guess.\n"
        f"  • Background can be a single line — don't skip a director "
        f"just because the snippet is short.\n"
        f"  • For `other_directorships`, include any other companies "
        f"explicitly mentioned alongside the person; leave the array "
        f"empty when none are named — do NOT invent.\n"
        f"  • Include the URL from the relevant TITLE / DIRECT-FETCH "
        f"FROM block in `source_links`.\n\n"
        f"Return JSON. If the input genuinely contains zero named "
        f"directors, return `directors: []` — but exhaust the input "
        f"first before deciding it's empty.\n\n"
        f"{blob}"
    )
    data = _llm_extract_json(prompt, schema_hint=schema, max_tokens=3000, label="directors")

    # Fallback — when the rich extraction fails (parse error, model
    # refusal, truncation that the closer couldn't recover), retry with
    # a slim "name + designation + year" schema. Shorter output → far
    # less likely to be truncated, and a barebones list with at least
    # the appointment year beats "0 directors found".
    if not data or not isinstance(data, dict) or not (data.get("directors") or []):
        logger.info("Director extraction empty on first pass — retrying minimal schema")
        minimal_schema = (
            '{"directors": [{"name": str, "designation": str|null, '
            '"since_year": str|null}]}'
        )
        minimal_prompt = (
            f"From the text below about {name} ({clean}), list the "
            f"names, designations, and year-appointed for the company's "
            f"directors / executives / key managerial personnel. Output "
            f"the JSON schema given. Include every named person who "
            f"appears to be on the board or in senior management. For "
            f"`since_year`, extract the year only when it's explicitly "
            f"stated in the text (e.g. '2023' from 'Director since 2023'); "
            f"otherwise leave null.\n\n"
            f"{blob}"
        )
        data = _llm_extract_json(minimal_prompt, schema_hint=minimal_schema, max_tokens=1500, label="directors.retry")

    if not data or not isinstance(data, dict):
        block.status = SectionStatus(
            available=False, confidence="low",
            notes="LLM extraction returned no parseable JSON (both passes)",
            sources=[r.get("url") for r in results if r.get("url")][:5],
        )
        return block

    raw = data.get("directors") or []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        nm = (entry.get("name") or "").strip()
        if not nm:
            continue
        since_raw = entry.get("since_year")
        since_year = str(since_raw).strip() if since_raw not in (None, "", 0) else None
        block.directors.append(DirectorProfile(
            name=nm,
            designation=(entry.get("designation") or None),
            since_year=since_year,
            din=(entry.get("din") or None),
            background=(entry.get("background") or None),
            other_directorships=[
                str(x).strip() for x in (entry.get("other_directorships") or []) if str(x).strip()
            ],
            source_links=[
                str(x).strip() for x in (entry.get("source_links") or []) if str(x).strip()
            ],
        ))
    block.status = SectionStatus(
        available=bool(block.directors),
        confidence="medium" if block.directors else "low",
        notes=(
            f"{len(block.directors)} director(s) extracted from public search "
            "results — not cross-checked against MCA21."
        ),
        sources=[r.get("url") for r in results if r.get("url")][:5],
    )
    return block


# ─────────────────────────────────────────────────────────
# Section 3 — political relations (best-effort)
# ─────────────────────────────────────────────────────────

_POLITICAL_CATEGORIES = (
    "government_ownership", "political_appointment", "donation",
    "affiliation", "controversy", "regulatory", "contracts", "other",
)


def _fetch_political(symbol: str, name: str, directors: DirectorBlock) -> PoliticalBlock:
    """Multi-query Tavily sweep + LLM extraction of political / government
    linkages — broad definition: includes structural ties (state ownership,
    ACC-appointed chairman for PSUs, ex-bureaucrat board members) as well
    as partisan signals (electoral-bond donations, party contributions,
    director affiliations).

    Three short queries beat one giant Boolean — Tavily handles them more
    cleanly and we get distinct angles in the same blob. Director-level
    queries are run separately for the top 3 directors so the LLM has
    individual context for each person.
    """
    block = PoliticalBlock()
    clean = symbol.replace(".NS", "").replace(".BO", "")
    director_names = [d.name for d in directors.directors][:3]

    # Three complementary company-level queries — each focuses on a
    # different facet of "political". Director-level queries are added
    # below.
    queries: List[str] = [
        # 1. Structural / ownership / appointment
        f"{name} {clean} government stake ownership ministry "
        f"appointment chairman board nominee public sector",
        # 2. Donations / electoral bonds / party contributions
        f"{name} {clean} electoral bond donation political party "
        f"contribution funding corporate political",
        # 3. Contracts / policy / lobbying / controversy
        f"{name} {clean} government contract policy regulation "
        f"lobbying political controversy minister",
    ]
    # Director-level queries — only when we have at least one extracted
    # director, capped at 3 to keep Tavily quota in check.
    for dn in director_names:
        if dn:
            queries.append(
                f'"{dn}" {clean} political affiliation party election '
                f"contested government nominee bureaucrat appointment"
            )

    # Fan out every query in parallel — political adds up to 3 + len(director_names)
    # queries; running them serially was a measurable contributor to wall-clock.
    results = _tavily_search_many(queries, max_results=4, label="political")

    if not results:
        block.status = SectionStatus(
            available=True, confidence="low",
            notes="No political / governance mentions surfaced in public news search.",
        )
        return block

    # Drop PDFs — same reason as the directors fix. Tavily's PDF text
    # extraction is too noisy to be useful for structured extraction.
    html_results = [
        r for r in results
        if not (r.get("url") or "").lower().endswith(".pdf")
    ] or results

    blob = _tavily_results_to_blob(html_results, limit=10, chars_per_result=1800)

    schema = (
        '{"connections": [{"subject": str, "finding": str, '
        '"category": "government_ownership|political_appointment|donation|'
        'affiliation|controversy|regulatory|contracts|other", '
        '"confidence": "high|medium|low", "source_links": [str]}]}'
    )
    prompt = (
        f"Company: {name} ({clean}). Directors of interest: {director_names}.\n\n"
        f"From the search results below, extract every credible mention of "
        f"the company's POLITICAL / GOVERNMENT context. Treat 'political' "
        f"BROADLY — include any of the following when explicitly mentioned:\n"
        f"  • government_ownership — central / state government holding "
        f"a stake (e.g. 'Government of India owns 60.41% through President of India')\n"
        f"  • political_appointment — chairman / director appointed by "
        f"ACC (Appointments Committee of Cabinet), MoP, ministry, or "
        f"a state body; ex-IAS / ex-IPS / ex-bureaucrat on board\n"
        f"  • donation — electoral-bond purchases, political-party "
        f"donations, corporate contributions (when reported)\n"
        f"  • affiliation — a director / promoter known to be aligned "
        f"with a political party or to have contested an election\n"
        f"  • controversy — political / governance scandal in the news\n"
        f"  • regulatory — major regulatory / ministerial decision "
        f"affecting the company (positive or negative)\n"
        f"  • contracts — significant government contract dependence "
        f"(e.g. Defence MoUs, PSU supply contracts)\n"
        f"  • other — anything political-adjacent not covered above\n\n"
        f"Rules:\n"
        f"  • For each finding, fill `subject` with the company name OR "
        f"the specific director / executive named.\n"
        f"  • Quote concrete details in `finding` (% stakes, ministry "
        f"names, year of appointment, contract sizes when stated).\n"
        f"  • `confidence='high'` when a credible outlet states the fact "
        f"explicitly; 'medium' when reported but indirect; 'low' for "
        f"inference from context.\n"
        f"  • Do NOT invent — include only what's in the snippets.\n"
        f"  • For PSUs / banks / oil & gas / defence companies, "
        f"government_ownership and political_appointment are usually "
        f"the most relevant categories — surface them when they appear.\n\n"
        f"If the snippets genuinely contain no political context at all, "
        f"return an empty `connections` array.\n\n"
        f"{blob}"
    )
    data = _llm_extract_json(prompt, schema_hint=schema, max_tokens=2500, label="political")

    # Fallback — slimmer schema if the rich one fails (parse error,
    # truncation past recovery, model refusal).
    if not data or not isinstance(data, dict) or not (data.get("connections") or []):
        logger.info(
            "Political extraction empty on first pass — retrying minimal schema"
        )
        minimal_schema = (
            '{"connections": [{"subject": str, "finding": str, '
            '"category": str|null}]}'
        )
        minimal_prompt = (
            f"From the text below about {name} ({clean}) and directors "
            f"{director_names}, list every mention of political or "
            f"government context — including government ownership stakes, "
            f"ministerial / ACC appointments, ex-bureaucrats on the board, "
            f"electoral-bond donations, party affiliations, or "
            f"government contract dependence. Be permissive: surface even "
            f"brief mentions. Return JSON.\n\n"
            f"{blob}"
        )
        data = _llm_extract_json(
            minimal_prompt, schema_hint=minimal_schema, max_tokens=1500,
            label="political.retry",
        )

    if data and isinstance(data, dict):
        for entry in (data.get("connections") or []):
            if not isinstance(entry, dict):
                continue
            finding = (entry.get("finding") or "").strip()
            if not finding:
                continue
            cat_raw = (entry.get("category") or "other").strip().lower()
            category = cat_raw if cat_raw in _POLITICAL_CATEGORIES else "other"
            block.connections.append(PoliticalConnection(
                subject=(entry.get("subject") or name).strip(),
                finding=finding,
                category=category,
                confidence=(entry.get("confidence") or "low").strip().lower(),
                source_links=[
                    str(x).strip() for x in (entry.get("source_links") or []) if str(x).strip()
                ],
            ))

    block.status = SectionStatus(
        available=True,
        confidence="medium" if block.connections else "low",
        notes=(
            f"{len(block.connections)} mention(s) flagged across "
            f"{len(queries)} search angles — best-effort from public news; "
            "not authoritative (no ECI / electoral-bond feed)."
        ),
        sources=[r.get("url") for r in results if r.get("url")][:5],
    )
    return block


# ─────────────────────────────────────────────────────────
# Section 4 — news & sentiment
# ─────────────────────────────────────────────────────────

def _fetch_news(symbol: str, name: str) -> NewsBlock:
    """Tavily search across 10 financial news domains; LLM tags each
    headline with sentiment + category. Re-uses the existing news flow
    from api_news_summary but with an added classification step."""
    block = NewsBlock()
    clean = symbol.replace(".NS", "").replace(".BO", "")
    queries = [
        f"{name} {clean} stock latest news 2025 2026",
        f"{clean} earnings results corporate action board management",
    ]
    # Parallel fan-out — both queries hit the same news-domain list, so
    # running them concurrently roughly halves the Tavily wall-clock.
    raw_results = _tavily_search_many(queries, domains=_NEWS_DOMAINS, max_results=5, label="news")
    seen: set = set()
    raw_items: List[Dict[str, Any]] = []
    for r in raw_results:
        title = (r.get("title") or "").strip()
        url = (r.get("url") or "").strip()
        if not title or len(title) < 10 or not url:
            continue
        key = title.lower()[:60]
        if key in seen:
            continue
        seen.add(key)
        raw_items.append(r)
    if not raw_items:
        block.status = SectionStatus(
            available=False, confidence="low",
            notes="No fresh news returned by Tavily across financial domains.",
        )
        return block

    # Bulk-classify with one LLM call (cheaper than per-headline).
    blob = "\n".join(
        f"{i + 1}. {(r.get('title') or '').strip()} | "
        f"{(r.get('content') or '').strip()[:300]}"
        for i, r in enumerate(raw_items)
    )
    schema = (
        '{"items": [{"index": int, "sentiment": "positive|negative|neutral", '
        '"category": "earnings|regulatory|governance|management|macro|other"}]}'
    )
    prompt = (
        f"Classify each numbered news headline below for {name} ({clean}).\n"
        f"Return one entry per index with `sentiment` and `category`. Be strict "
        f"about negative — only when the headline is materially adverse "
        f"(downgrade, regulatory action, fraud, loss, miss). Default to neutral.\n\n"
        f"{blob}"
    )
    data = _llm_extract_json(prompt, schema_hint=schema, label="news")
    classifications: Dict[int, Dict[str, str]] = {}
    if data and isinstance(data, dict):
        for entry in (data.get("items") or []):
            if isinstance(entry, dict) and isinstance(entry.get("index"), int):
                classifications[entry["index"]] = {
                    "sentiment": (entry.get("sentiment") or "neutral").lower(),
                    "category": (entry.get("category") or "other").lower(),
                }

    pos = neg = neu = 0
    for i, r in enumerate(raw_items, start=1):
        cls = classifications.get(i) or {}
        sent = cls.get("sentiment", "neutral")
        cat = cls.get("category", "other")
        if sent == "positive":
            pos += 1
        elif sent == "negative":
            neg += 1
        else:
            neu += 1
        publisher = "Web"
        try:
            publisher = (r.get("url") or "").split("/")[2].replace("www.", "")
        except Exception:
            pass
        block.items.append(NewsHeadline(
            title=(r.get("title") or "").strip(),
            publisher=publisher,
            link=(r.get("url") or "").strip(),
            summary=(r.get("content") or "").strip()[:300],
            published=(r.get("published_date") or None),
            sentiment=sent,
            category=cat,
        ))
    block.positive, block.negative, block.neutral = pos, neg, neu

    # Augment with NSE corporate announcements — these are the authoritative
    # exchange filings (board meetings, dividends, allotments, results
    # notifications) that the Tavily news domains often summarise hours or
    # days later. Silent fallback: if NSE returns nothing or errors, we
    # just keep the Tavily-only set.
    nse_added = 0
    try:
        from utils.nse_client import fetch_announcements as _nse_announcements
        t_nse = time.time()
        nse_items = _nse_announcements(clean, limit=15, max_days_old=90)
        _log(
            f"  [news] NSE announcements: {len(nse_items)} item(s) "
            f"(last 90 days) in {_fmt_secs(time.time() - t_nse)}"
        )
        # Dedupe against Tavily hits (by lowercased title prefix) so the
        # same announcement doesn't appear twice when both sources have it.
        existing_keys = {(h.title or "").lower()[:60] for h in block.items}
        for it in nse_items:
            title = (it.get("title") or it.get("category") or "").strip()
            if not title:
                continue
            key = title.lower()[:60]
            if key in existing_keys:
                continue
            existing_keys.add(key)
            block.items.append(NewsHeadline(
                title=title[:300],
                publisher="NSE",
                link=it.get("link") or "https://www.nseindia.com/",
                summary=(it.get("category") or "Official corporate filing"),
                published=it.get("published") or None,
                sentiment="neutral",  # raw filings — sentiment is read by user
                category="regulatory",
            ))
            block.neutral += 1
            nse_added += 1
    except Exception as exc:
        logger.debug("NSE announcements augmentation skipped: %s", exc)

    note_bits = [f"{len(block.items)} headline(s) — pos {pos}, neg {neg}, neu {neu + nse_added}"]
    if nse_added:
        note_bits.append(f"+{nse_added} NSE filing(s)")
    block.status = SectionStatus(
        available=True,
        confidence="high" if len(block.items) >= 8 else "medium",
        notes=". ".join(note_bits) + ".",
        sources=[r.get("url") for r in raw_items if r.get("url")][:5],
    )
    return block


# ─────────────────────────────────────────────────────────
# Section 5 — criminal / legal cases (best-effort)
# ─────────────────────────────────────────────────────────

_LEGAL_CASE_TYPES = (
    "regulator",       # SEBI / RBI / CCI / SFIO / IT / ED / customs
    "court",           # civil / criminal / NCLT / NCLAT / high court / SC
    "penalty",         # fine / settlement / consent order
    "tax",             # income tax / GST / customs dispute
    "defaulter",       # wilful defaulter / NPA
    "governance",      # insider trading / fraud / related-party
    "ipr",             # IP / trademark / patent dispute
    "arbitration",     # commercial arbitration
    "other",
)


def _fetch_legal(symbol: str, name: str, directors: DirectorBlock) -> LegalBlock:
    """Multi-query Tavily sweep + LLM extraction of legal / regulatory /
    enforcement matters. Broad scope — beyond just SEBI / SFIO we also
    look at court proceedings (civil, criminal, NCLT, NCLAT, HC, SC),
    tax disputes (IT / GST / customs), arbitration, CCI / RBI / ED
    actions, and any contingent-liability disclosures from annual reports.

    Five short queries cover distinct legal angles. PDF results are
    filtered out of the LLM blob (Tavily's PDF text extraction is too
    noisy for structured extraction) but kept in `sources` so the user
    can click through to the primary filing.
    """
    block = LegalBlock()
    clean = symbol.replace(".NS", "").replace(".BO", "")
    director_names = [d.name for d in directors.directors][:3]

    # Five complementary queries. Each targets a different legal facet
    # — Tavily handles plain keywords better than one giant Boolean.
    queries: List[str] = [
        # 1. Securities regulator + market enforcement
        f"{name} {clean} SEBI order penalty show cause notice consent "
        f"settlement insider trading market manipulation",
        # 2. Other regulators
        f"{name} {clean} RBI CCI SFIO Enforcement Directorate ED "
        f"investigation FIR raid",
        # 3. Court / tribunal proceedings
        f"{name} {clean} court case NCLT NCLAT high court Supreme Court "
        f"writ petition criminal civil litigation",
        # 4. Tax disputes + contingent liabilities
        f"{name} {clean} income tax GST customs dispute demand notice "
        f"contingent liability tax tribunal ITAT",
        # 5. Defaulter / fraud / governance scandals
        f"{name} {clean} wilful defaulter NPA fraud whistleblower "
        f"governance scandal allegations",
    ]
    # Director-level queries — one per top director, capped at 3.
    for dn in director_names:
        if dn:
            queries.append(
                f'"{dn}" {clean} SEBI case fraud allegation FIR court '
                f"investigation penalty"
            )

    # Parallel fan-out — legal runs up to 8 queries (5 legal facets +
    # 3 director-level). Concurrent dispatch keeps the section's wall-clock
    # close to the slowest single Tavily call.
    results = _tavily_search_many(queries, domains=_LEGAL_DOMAINS, max_results=4, label="legal")

    if not results:
        block.status = SectionStatus(
            available=True, confidence="low",
            notes="No legal / enforcement mentions found in public sources.",
        )
        return block

    # Strip PDFs from the LLM blob — Tavily's PDF text extraction
    # produces noisy output that confuses structured extraction.
    # Keep them in `sources` so the renderer still surfaces the link.
    html_results = [
        r for r in results
        if not (r.get("url") or "").lower().endswith(".pdf")
    ] or results

    blob = _tavily_results_to_blob(html_results, limit=10, chars_per_result=1800)

    schema = (
        '{"cases": [{"subject": str, "case_type": "regulator|court|penalty|'
        'tax|defaulter|governance|ipr|arbitration|other", '
        '"summary": str, "published": str|null, '
        '"confidence": "high|medium|low", "source_links": [str]}]}'
    )
    prompt = (
        f"Company: {name} ({clean}). Directors of interest: {director_names}.\n\n"
        f"From the search results below, extract every legal / regulatory / "
        f"enforcement / litigation matter associated with the company OR its "
        f"directors. Be PERMISSIVE — surface every credible mention, even when "
        f"it's a small or historical matter. Categorize each one:\n"
        f"  • regulator — SEBI / RBI / CCI / SFIO / ED / IT / customs orders, "
        f"show-cause notices, investigations\n"
        f"  • court — civil / criminal cases, writs, petitions in HC / SC / "
        f"NCLT / NCLAT\n"
        f"  • penalty — fines, consent orders, settlements, disgorgement\n"
        f"  • tax — income tax / GST / customs disputes, ITAT proceedings, "
        f"contingent-liability tax demands disclosed in annual reports\n"
        f"  • defaulter — wilful defaulter listing, NPA classification, "
        f"loan default proceedings\n"
        f"  • governance — insider trading, related-party transactions under "
        f"scrutiny, fraud allegations, whistleblower complaints\n"
        f"  • ipr — IP / trademark / patent infringement litigation\n"
        f"  • arbitration — domestic / international commercial arbitration\n"
        f"  • other — anything legal-adjacent not covered above\n\n"
        f"Rules:\n"
        f"  • For each item, fill `subject` with the company OR the specific "
        f"director / executive named.\n"
        f"  • In `summary`, quote concrete details — case number, court, "
        f"penalty amount, year — when the snippet has them.\n"
        f"  • `published` = year or YYYY-MM-DD when stated; null otherwise.\n"
        f"  • `confidence='high'` when a credible outlet states the fact "
        f"explicitly; 'medium' when reported but indirect; 'low' for "
        f"inference. Set 'low' for any 'similar-name confusion' risk.\n"
        f"  • Do NOT invent — include only what's in the snippets.\n"
        f"  • Even SMALL or HISTORICAL matters count — don't filter for "
        f"recency or magnitude.\n\n"
        f"If the snippets genuinely contain no legal / regulatory mentions, "
        f"return an empty `cases` array — but exhaust the input first.\n\n"
        f"{blob}"
    )
    data = _llm_extract_json(prompt, schema_hint=schema, max_tokens=2500, label="legal")

    # Fallback — minimal schema if rich extraction fails or returns empty.
    if not data or not isinstance(data, dict) or not (data.get("cases") or []):
        logger.info("Legal extraction empty on first pass — retrying minimal schema")
        minimal_schema = (
            '{"cases": [{"subject": str, "case_type": str|null, '
            '"summary": str}]}'
        )
        minimal_prompt = (
            f"From the text below about {name} ({clean}) and directors "
            f"{director_names}, list every legal / regulatory / "
            f"enforcement matter mentioned — SEBI orders, court cases, "
            f"tax disputes, penalties, FIRs, investigations, "
            f"contingent liabilities, arbitration. Be permissive: include "
            f"even small or historical matters. Return JSON.\n\n"
            f"{blob}"
        )
        data = _llm_extract_json(
            minimal_prompt, schema_hint=minimal_schema, max_tokens=1500,
            label="legal.retry",
        )

    if data and isinstance(data, dict):
        for entry in (data.get("cases") or []):
            if not isinstance(entry, dict):
                continue
            summary = (entry.get("summary") or "").strip()
            if not summary:
                continue
            ct_raw = (entry.get("case_type") or "other").strip().lower()
            # Be tolerant about the model's category — many LLMs emit
            # legacy values from older prompts (e.g. "SEBI", "SFIO"),
            # so we map those into the new canonical list.
            ct_alias = {
                "sebi": "regulator", "sfio": "regulator", "rbi": "regulator",
                "cci": "regulator", "ed": "regulator", "customs": "regulator",
                "income tax": "tax", "gst": "tax", "itat": "tax",
                "wilful_defaulter": "defaulter", "wilful defaulter": "defaulter",
                "civil": "court", "criminal": "court", "nclt": "court",
                "nclat": "court", "hc": "court", "sc": "court",
                "fraud": "governance", "insider trading": "governance",
            }
            case_type = ct_alias.get(ct_raw, ct_raw)
            if case_type not in _LEGAL_CASE_TYPES:
                case_type = "other"
            block.cases.append(LegalCase(
                subject=(entry.get("subject") or name).strip(),
                case_type=case_type,
                summary=summary,
                published=(entry.get("published") or None),
                confidence=(entry.get("confidence") or "low").strip().lower(),
                source_links=[
                    str(x).strip() for x in (entry.get("source_links") or []) if str(x).strip()
                ],
            ))

    block.status = SectionStatus(
        available=True,
        confidence="medium" if block.cases else "low",
        notes=(
            f"{len(block.cases)} matter(s) flagged across {len(queries)} "
            "search angles — best-effort from news + SEBI/NSE/BSE/RBI "
            "snippets. eCourts / SEBI PDFs are not queryable as structured "
            "feeds; verify any flagged case against the primary filing."
        ),
        sources=[r.get("url") for r in results if r.get("url")][:5],
    )
    return block


# ─────────────────────────────────────────────────────────
# Section 6 + 7 — promoter investments in other companies +
#                 portfolio performance lookup
# ─────────────────────────────────────────────────────────

def _portfolio_performance_via_yfinance(ticker: str) -> Optional[PortfolioPerformance]:
    """Pull a quick 1Y / 3Y return and revenue trend from yfinance for a
    portfolio company. Tolerant of missing data — returns None when the
    ticker doesn't resolve."""
    try:
        import yfinance as yf
    except Exception:
        return None
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period="3y", auto_adjust=True)
        if hist is None or hist.empty:
            return None
        last = float(hist["Close"].iloc[-1])
        first_3y = float(hist["Close"].iloc[0])
        return_3y = ((last - first_3y) / first_3y) * 100 if first_3y else None
        one_year_idx = max(0, len(hist) - 252)
        first_1y = float(hist["Close"].iloc[one_year_idx])
        return_1y = ((last - first_1y) / first_1y) * 100 if first_1y else None
        try:
            fin = tk.financials
            if fin is not None and not fin.empty and "Total Revenue" in fin.index:
                rev = fin.loc["Total Revenue"].dropna().tolist()
                if len(rev) >= 2:
                    if rev[0] > rev[-1]:
                        trend = "growing"
                    elif rev[0] < rev[-1]:
                        trend = "declining"
                    else:
                        trend = "flat"
                else:
                    trend = None
            else:
                trend = None
        except Exception:
            trend = None
        info = getattr(tk, "info", {}) or {}
        return PortfolioPerformance(
            company_name=info.get("longName") or info.get("shortName") or ticker,
            ticker=ticker,
            last_price=last,
            return_1y_pct=round(return_1y, 2) if return_1y is not None else None,
            return_3y_pct=round(return_3y, 2) if return_3y is not None else None,
            revenue_trend=trend,
        )
    except Exception as exc:
        logger.debug("yfinance lookup failed for %s: %s", ticker, exc)
        return None


def _fetch_investments(symbol: str, name: str) -> InvestmentsBlock:
    """Section 6 + 7 — multi-query Tavily sweep + LLM extraction of
    every OTHER company in the group: subsidiaries, joint ventures,
    associates, step-down subsidiaries, listed group entities. Then
    yfinance lookup for each entry that looks listed on NSE/BSE.

    Broad scope on purpose — "promoter investments" for a PSU like
    ONGC means ONGC Videsh / MRPL / HPCL stake history; for a private
    group like Tata it means TCS / Tata Motors / Tata Power etc.
    Single Boolean queries miss most of this; four narrow queries
    cover the angles cleanly.
    """
    block = InvestmentsBlock()
    clean = symbol.replace(".NS", "").replace(".BO", "")

    queries: List[str] = [
        # 1. Direct subsidiaries / joint ventures / step-down entities
        f"{name} {clean} subsidiary subsidiaries joint venture JV "
        f"step-down associate group companies",
        # 2. Related-party + cross-holding disclosures
        f"{name} {clean} \"related party\" cross-holding promoter "
        f"holding pattern shareholders disclosure annual report",
        # 3. Listed group / sister concerns
        f"{name} {clean} group companies sister concern listed "
        f"associate company NSE BSE stake holding",
        # 4. Investments in other companies / strategic stakes
        f"{name} {clean} strategic investment stake equity partner "
        f"acquired merger amalgamation portfolio company",
    ]

    # Parallel fan-out — investments runs 4 complementary queries that
    # used to add ~30s of sequential Tavily latency on top of the LLM call.
    results = _tavily_search_many(queries, max_results=4, label="investments")

    if not results:
        block.status = SectionStatus(
            available=False, confidence="low",
            notes="No subsidiary / cross-holding mentions found in public sources.",
        )
        return block

    # Strip PDFs from the LLM blob (Tavily PDF extraction is noisy).
    # Annual-report PDFs often have the cleanest related-party data but
    # the noise → garbled output trade-off makes them unreliable inputs
    # for structured LLM extraction. They stay visible in `sources`.
    html_results = [
        r for r in results
        if not (r.get("url") or "").lower().endswith(".pdf")
    ] or results

    blob = _tavily_results_to_blob(html_results, limit=10, chars_per_result=2000)

    schema = (
        '{"investments": [{"investor_name": str, "company_name": str, '
        '"stake_percent": float|null, "listed": bool, '
        '"ticker": str|null, "investment_value": str|null, '
        '"relationship": "subsidiary|jv|associate|cross-holding|other"|null, '
        '"source_links": [str]}]}'
    )
    prompt = (
        f"Company: {name} ({clean}).\n\n"
        f"From the search results below, extract EVERY other company "
        f"that {name} (the parent), its promoters, or its directors "
        f"hold a stake in. Be PERMISSIVE — include subsidiaries (any "
        f"%), joint ventures, associates, step-down entities, and "
        f"listed group / sister-concern companies.\n\n"
        f"Rules:\n"
        f"  • `investor_name` = '{name}' for subsidiaries / JVs / "
        f"associates of the parent; the director / promoter name for "
        f"their personal investments.\n"
        f"  • `relationship` — one of: 'subsidiary' (parent owns >50%), "
        f"'jv' (joint venture), 'associate' (20-50% stake), "
        f"'cross-holding' (group company cross-shareholding), or "
        f"'other' (strategic stake / portfolio holding).\n"
        f"  • `stake_percent` — numeric % when stated (e.g. 51.0 from "
        f"'ONGC holds 51% of MRPL'); null when not stated.\n"
        f"  • `listed=true` only when the entity appears to trade on "
        f"NSE / BSE. For listed entities, include the NSE ticker in "
        f"`ticker` (e.g. 'MRPL.NS', 'HPCL.NS') — without it the "
        f"performance lookup can't run.\n"
        f"  • `investment_value` — Rs / Cr / % figure when stated, "
        f"else null.\n"
        f"  • Include the relevant URL in `source_links`.\n"
        f"  • Do NOT invent — only extract what's in the snippets.\n\n"
        f"Even a partial entry (just the company name + relationship) "
        f"is more useful than skipping it. Exhaust the input before "
        f"deciding it's empty.\n\n"
        f"{blob}"
    )
    data = _llm_extract_json(prompt, schema_hint=schema, max_tokens=2500, label="investments")

    # Fallback — minimal schema if the rich one fails.
    if not data or not isinstance(data, dict) or not (data.get("investments") or []):
        logger.info(
            "Investments extraction empty on first pass — retrying minimal schema"
        )
        minimal_schema = (
            '{"investments": [{"investor_name": str, "company_name": str, '
            '"relationship": str|null, "stake_percent": float|null}]}'
        )
        minimal_prompt = (
            f"From the text below about {name} ({clean}), list every "
            f"other company that is a subsidiary, JV, associate, group "
            f"company, or sister concern of this entity. Include "
            f"directors' personal investments in other companies when "
            f"explicitly mentioned. Be permissive: surface even brief "
            f"mentions. Return JSON.\n\n"
            f"{blob}"
        )
        data = _llm_extract_json(
            minimal_prompt, schema_hint=minimal_schema, max_tokens=1500,
            label="investments.retry",
        )

    if data and isinstance(data, dict):
        for entry in (data.get("investments") or []):
            if not isinstance(entry, dict):
                continue
            comp = (entry.get("company_name") or "").strip()
            if not comp:
                continue
            stake_raw = entry.get("stake_percent")
            try:
                stake = float(stake_raw) if stake_raw is not None else None
            except (TypeError, ValueError):
                stake = None
            # Build a richer "investor_name" field that includes the
            # relationship type — renders nicely in the table column.
            rel = (entry.get("relationship") or "").strip().lower()
            investor = (entry.get("investor_name") or name).strip()
            if rel and rel != "other":
                investor = f"{investor} ({rel})"
            block.investments.append(PromoterInvestment(
                investor_name=investor,
                company_name=comp,
                stake_percent=stake,
                listed=bool(entry.get("listed")),
                ticker=(entry.get("ticker") or None),
                investment_value=(entry.get("investment_value") or None),
                source_links=[
                    str(x).strip() for x in (entry.get("source_links") or []) if str(x).strip()
                ],
            ))

    # Section 7 — performance lookup for each listed entry, run in
    # parallel. yfinance fetches are network-bound and independent, so
    # serial calls would otherwise stack 1–2s per ticker.
    seen_tickers: set = set()
    tickers: List[str] = []
    for inv in block.investments:
        if not inv.listed or not inv.ticker:
            continue
        ticker = inv.ticker.strip().upper()
        if "." not in ticker:
            ticker += ".NS"
        if ticker in seen_tickers:
            continue
        seen_tickers.add(ticker)
        tickers.append(ticker)

    if tickers:
        _log(
            f"  [investments] yfinance performance lookup for "
            f"{len(tickers)} ticker(s) in parallel …"
        )
        t_yf = time.time()
        with ThreadPoolExecutor(max_workers=min(6, len(tickers))) as ypool:
            for perf in ypool.map(_portfolio_performance_via_yfinance, tickers):
                if perf is not None:
                    block.performance.append(perf)
        _log(
            f"  [investments] yfinance done: "
            f"{len(block.performance)}/{len(tickers)} succeeded in "
            f"{_fmt_secs(time.time() - t_yf)}"
        )

    block.status = SectionStatus(
        available=bool(block.investments),
        confidence="medium" if block.investments else "low",
        notes=(
            f"{len(block.investments)} cross-holding(s) extracted across "
            f"{len(queries)} search angles, "
            f"{len(block.performance)} performance lookup(s) succeeded."
        ),
        sources=[r.get("url") for r in results if r.get("url")][:5],
    )
    return block


# ─────────────────────────────────────────────────────────
# Section 8 — pledge data (screener.in)
# ─────────────────────────────────────────────────────────

_PLEDGE_KEY_PATTERNS = (
    re.compile(r"\bpledged?\b", re.IGNORECASE),
    re.compile(r"pledg\w*\s+share", re.IGNORECASE),
)

# Screener.in's Pros/Cons block surfaces the pledge percentage as a
# plain-English sentence — the *only* place on the public page where
# pledge data appears for non-PSU stocks. The shareholding-pattern
# table never shows a "Pledged" row (the breakdown lives behind a
# JS-driven modal that requires auth / CSRF). These regexes target
# the canonical phrasings observed across pledge-heavy tickers
# (DBREALTY, BAJAJHIND, etc.) so we can still surface a current
# snapshot when the table is silent.
_PLEDGE_TEXT_PATTERNS = (
    re.compile(r"promoters?\s+(?:have\s+)?pledged\s+([0-9]+(?:\.[0-9]+)?)\s*%", re.IGNORECASE),
    re.compile(r"pledged\s+([0-9]+(?:\.[0-9]+)?)\s*%\s+of\s+(?:their|promoter)", re.IGNORECASE),
    re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*%\s+of\s+(?:their|promoter)\s+(?:holding|shares?)\s+(?:is|are)\s+pledged", re.IGNORECASE),
)


def _extract_pledge_trend(soup: BeautifulSoup) -> Tuple[List[PledgePoint], Optional[float]]:
    """Find the 'Pledged' row inside the shareholding-pattern table.
    Returns the trend list (most recent first → most recent last) and the
    latest non-null percent."""
    headers, rows = _parse_screener_table(soup, "shareholding")
    if not headers or not rows:
        return [], None
    pledge_series: Optional[List[Optional[float]]] = None
    for row_label, series in rows.items():
        if any(p.search(row_label) for p in _PLEDGE_KEY_PATTERNS):
            pledge_series = series
            break
    if not pledge_series:
        return [], None

    # Align to the headers' length (the table may have a trailing summary col).
    trim = pledge_series[-len(headers):]
    points: List[PledgePoint] = []
    for q, val in zip(headers[-12:], trim[-12:]):  # last 3y of quarters
        points.append(PledgePoint(quarter=q, percent_pledged=val))
    latest = next((p.percent_pledged for p in reversed(points)
                   if p.percent_pledged is not None), None)
    return points, latest


def _extract_pledge_from_analysis(soup: BeautifulSoup) -> Optional[float]:
    """Scan screener.in's Pros/Cons (analysis) section for the canonical
    pledge sentence — e.g. *"Promoters have pledged 44.7% of their
    holding."*. Returns the percent as float, or None when no pledge
    mention is found (which screener.in treats as 0% pledged).

    Scope is restricted to the `analysis` and `insights` sections so a
    pledge mention in unrelated news / commentary doesn't pollute the
    reading. Falls back to the full page text only if those sections
    are missing entirely.
    """
    scopes: List[str] = []
    for sid in ("analysis", "insights"):
        sec = soup.find("section", id=sid)
        if sec:
            scopes.append(sec.get_text(" ", strip=True))
    if not scopes:
        scopes.append(soup.get_text(" ", strip=True))

    for text in scopes:
        for pattern in _PLEDGE_TEXT_PATTERNS:
            m = pattern.search(text)
            if m:
                try:
                    pct = float(m.group(1))
                except (TypeError, ValueError):
                    continue
                # Sanity clamp — screener never prints >100% pledged.
                if 0 <= pct <= 100:
                    return pct
    return None


def _latest_quarter_label(soup: BeautifulSoup) -> Optional[str]:
    """Return the most recent column label from the shareholding-pattern
    table (e.g. "Mar 2026"). Used to anchor a single-point pledge trend
    when only the headline percentage is available from text scrape."""
    headers, _rows = _parse_screener_table(soup, "shareholding")
    if headers:
        # The last column is the latest; strip trailing whitespace/footnotes.
        return headers[-1].strip() or None
    return None


def _shareholding_quarters(soup: BeautifulSoup, *, last_n: int = 12) -> List[str]:
    """Return the most recent `last_n` quarter labels from the
    shareholding-pattern table. Used to synthesise a flat-line pledge
    trend in the 0%-pledged case so the renderer can still show the
    chart + table instead of bailing on empty trend data."""
    headers, _rows = _parse_screener_table(soup, "shareholding")
    if not headers:
        return []
    cleaned = [h.strip() for h in headers if h and h.strip()]
    return cleaned[-last_n:]


def _flat_zero_trend(soup: BeautifulSoup) -> List[PledgePoint]:
    """Build a 12-quarter flat-line trend at 0% pledged.

    Screener.in omits the "Pledged" row entirely when the figure is 0%
    for every quarter, so we'd otherwise have no time-series to render.
    Reconstructing the timeline from the shareholding-pattern column
    headers (which we already parsed) lets the chart and dataframe show
    the same 12-quarter window the rest of the section uses — visual
    confirmation that the 0% reading is consistent over time, not just
    a missing data point.
    """
    quarters = _shareholding_quarters(soup)
    if not quarters:
        return []
    return [PledgePoint(quarter=q, percent_pledged=0.0) for q in quarters]


def _classify_pledge_risk(pct: Optional[float]) -> str:
    if pct is None:
        return "unknown"
    if pct <= 5:
        return "low"
    if pct <= 25:
        return "medium"
    if pct <= 50:
        return "high"
    return "critical"


def _detect_government_promoter(soup: BeautifulSoup) -> Tuple[bool, Optional[float]]:
    """Detect whether the company is government-owned (PSU / public-sector
    bank / oil & gas / defence) by scanning the shareholding pattern for
    a 'Government' row with a substantive stake.

    Returns (is_govt_owned, government_percent_latest)."""
    headers, rows = _parse_screener_table(soup, "shareholding")
    if not headers or not rows:
        return False, None
    for label, series in rows.items():
        lower = label.lower()
        if "government" in lower or "president of india" in lower:
            for val in reversed(series):
                if val is not None and val > 5:  # 5%+ counts as state-controlled
                    return True, val
            return False, None
    # Also detect via "Promoters" row label that includes "Government"
    for label, _series in rows.items():
        if "promoter" in label.lower() and (
            "government" in label.lower() or "president" in label.lower()
        ):
            return True, None
    return False, None


def _augment_with_nse_pledge(block: PledgeBlock, symbol: str) -> int:
    """Fetch NSE SAST/PIT pledge filings and attach them as
    `block.events`. Returns the number of filings added.

    Silent on any failure — NSE Akamai blocks, network errors, or empty
    responses all result in `block.events` left untouched. The screener.in
    reading remains the primary signal; NSE just adds authoritative
    transaction-level history when available.
    """
    try:
        from utils.nse_client import fetch_pledge_filings
        t_nse = time.time()
        filings = fetch_pledge_filings(symbol, limit=50)
        _log(
            f"  [pledge] NSE SAST/PIT: {len(filings)} pledge filing(s) in "
            f"{_fmt_secs(time.time() - t_nse)}"
        )
    except Exception as exc:
        logger.debug("NSE pledge augmentation skipped: %s", exc)
        return 0
    if not filings:
        return 0
    for f in filings:
        try:
            block.events.append(PledgeEvent(**f))
        except Exception:
            # Field shape mismatch — skip this entry but keep the rest.
            continue
    return len(block.events)


def _fetch_pledge(symbol: str, name: str) -> PledgeBlock:
    """Section 8 — promoter pledge data from screener.in (primary) + NSE
    SAST/PIT filings (transaction-level augmentation).

    Screener.in surfaces pledge data in two places, in priority order:

      a) **Shareholding-pattern table** — a `Pledged` row with a quarterly
         series. This is the richest source (gives a full 3-year trend)
         but is rarely populated on the public HTML; screener.in only
         exposes it for a small subset of tickers.
      b) **Pros / Cons analysis sentence** — for any stock where the
         pledge is material, screener.in prints
         *"Promoters have pledged X% of their holding."* in the
         analysis section. This is the canonical public-page source.

    Once one of those gives us the headline percentage, we also pull
    NSE's `/api/corporates-pit` — every Annex 7(2)/7(3) SAST filing
    related to a pledge event (creation / release / invocation). These
    are authoritative exchange disclosures with exact share counts,
    rupee values, and dates; they go on `block.events` and the renderer
    surfaces them as a transaction timeline. Silent fallback on any NSE
    failure: the section still renders with screener.in data only.

    The four outcomes are:
      1. Stock not on screener.in → unavailable.
      2. Government / state-owned promoter → structurally not applicable
         (e.g. ONGC's promoter is President of India; cannot be pledged).
      3. Pledge data found (table OR analysis text) → populate
         `current_percent`, `risk_level`, and `trend`.
      4. Neither source mentions pledge → promoters likely have 0%
         pledged (screener.in omits the analysis line below ~1%).
    """
    block = PledgeBlock()
    soup, url, error = _get_screener_soup(symbol)
    if soup is None:
        block.status = SectionStatus(
            available=False, confidence="low",
            notes=error or "Could not load screener.in page",
            sources=[url] if url else [],
        )
        return block

    is_govt, govt_pct = _detect_government_promoter(soup)
    trend, latest = _extract_pledge_trend(soup)
    block.trend = trend

    # Augment with NSE SAST/PIT pledge filings regardless of which case
    # below we hit — even for a "0% pledged" stock the filings list is
    # useful confirmation (empty = no pledge events on record).
    nse_count = _augment_with_nse_pledge(block, symbol)

    # Composable bits the note builder uses in every case below — keeps
    # the NSE augmentation phrasing consistent across cases A/B/C/D.
    nse_suffix = (
        f" NSE SAST/PIT history: {nse_count} pledge filing(s) on record."
        if nse_count else
        " NSE SAST/PIT: no pledge filings on record."
    )
    nse_source = "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading"
    sources = [url, nse_source] if nse_count else [url]

    # Case A — government-owned: pledge is structurally inapplicable.
    # The President of India / state authority cannot pledge shares to
    # a bank as collateral, so pledge=0 here is a structural fact, not
    # missing data. Reflect that in the notes and mark risk='low'.
    if is_govt and not trend:
        block.current_percent = 0.0
        block.risk_level = "low"
        # Synthesise a 12-quarter flat-line at 0% so the renderer can
        # still show the chart + dataframe ("verified flat across 12
        # quarters") instead of bailing on an empty trend.
        block.trend = _flat_zero_trend(soup)
        block.status = SectionStatus(
            available=True, confidence="high",
            notes=(
                f"Government-owned entity"
                f"{f' (state holds ~{govt_pct:.1f}%)' if govt_pct else ''}"
                " — promoter pledging is structurally not applicable. "
                "Sovereign promoters cannot pledge shares as collateral."
                + nse_suffix
            ),
            sources=sources,
        )
        return block

    # Case B — pledge row found with quarterly data (rare).
    if trend:
        block.current_percent = latest
        block.risk_level = _classify_pledge_risk(latest)
        block.status = SectionStatus(
            available=True,
            confidence="high" if len(trend) >= 4 else "medium",
            notes=(
                f"Pledge trend across {len(trend)} quarter(s); latest "
                f"{latest if latest is not None else 'n/a'}% — risk: {block.risk_level}."
                + nse_suffix
            ),
            sources=sources,
        )
        return block

    # Case C — fall back to screener.in's Pros/Cons sentence, which is
    # how the site exposes pledge data for every pledge-heavy ticker.
    # If we extract a percent here, treat the latest shareholding-pattern
    # quarter as the anchor and emit a single-point trend. When NSE
    # corroborates with actual pledge filings, bump confidence to high.
    text_pct = _extract_pledge_from_analysis(soup)
    if text_pct is not None and text_pct > 0:
        quarter = _latest_quarter_label(soup) or "Latest"
        block.trend = [PledgePoint(quarter=quarter, percent_pledged=text_pct)]
        block.current_percent = text_pct
        block.risk_level = _classify_pledge_risk(text_pct)
        block.status = SectionStatus(
            available=True,
            confidence="high" if nse_count else "medium",
            notes=(
                f"Pledge of {text_pct:.2f}% extracted from screener.in's "
                f"Pros/Cons summary (as of {quarter}); risk: {block.risk_level}."
                + nse_suffix
                + (" Quarterly trend not available on the public page — "
                   "see NSE filings below for exact transaction history."
                   if nse_count else
                   " Quarterly trend not available on the public page — "
                   "verify against the latest BSE/NSE shareholding-pattern filing.")
            ),
            sources=sources,
        )
        return block

    # Case D — no pledge row AND no Pros/Cons mention. Two very different
    # scenarios collapse into this branch and the NSE filing count is what
    # tells them apart:
    #   • nse_count == 0 → genuinely clean stock. Screener.in suppresses the
    #     "X% pledged" sentence when the value is immaterial AND NSE has no
    #     SAST/PIT filings on record either; two independent sources agree
    #     on ~0%.
    #   • nse_count  > 0 → screener.in's text scrape missed the percentage
    #     (page-structure drift, network truncation, regex gap) but NSE
    #     has *active pledge filings* on file. Claiming 0% here directly
    #     contradicts the NSE evidence — e.g. BAJAJHIND has 50 SAST/PIT
    #     pledge filings yet would otherwise render as 0% clean. Surface
    #     it as 'unknown' instead so the renderer doesn't mislead the user.
    if nse_count > 0:
        block.current_percent = None
        block.risk_level = "unknown"
        block.trend = []
        block.status = SectionStatus(
            available=True,
            confidence="low",
            notes=(
                "Could not extract the headline pledge % from screener.in "
                f"(no 'Pledged' row, no Pros/Cons mention) — but NSE has "
                f"{nse_count} SAST/PIT pledge filing(s) on record, so "
                "0% would be misleading. Inspect the filings below for "
                "the authoritative transaction history; verify the "
                "current % against the latest BSE/NSE shareholding pattern."
            ),
            sources=sources,
        )
        return block

    block.current_percent = 0.0
    block.risk_level = "low"
    # Build a 12-quarter flat-line trend at 0% so the user sees the
    # full timeline rendered as a chart + table, mirroring how every
    # other "clean" stock looks rather than leaving the section empty.
    block.trend = _flat_zero_trend(soup)
    qcount = len(block.trend)
    block.status = SectionStatus(
        available=True,
        confidence="high",
        notes=(
            "No 'Pledged Percentage' row and no pledge mention in "
            "screener.in's Pros/Cons block — promoters appear to have ~0% "
            f"pledged{f' across the last {qcount} quarter(s)' if qcount else ''}."
            + nse_suffix
        ),
        sources=sources,
    )
    return block


# ─────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────

def _run_section(fn: Callable[..., Any], label: str, *args: Any) -> Any:
    """Time + log + swallow exceptions for one sub-fetcher. Each section
    is responsible for returning its own fallback `SectionStatus` on
    handled errors; this catch is for the truly unexpected ones."""
    t0 = time.time()
    _log(f"▶ section start  : {label}")
    try:
        result = fn(*args)
        _log(f"✓ section done   : {label} in {_fmt_secs(time.time() - t0)}")
        logger.info("Fundamental section %s done in %.2fs", label, time.time() - t0)
        return result
    except Exception as exc:
        _log(f"✗ section ERROR  : {label} after {_fmt_secs(time.time() - t0)} — {exc}")
        logger.exception("Fundamental section %s raised: %s", label, exc)
        return None


def analyze_fundamentals(
    symbol: str,
    stock_name: Optional[str] = None,
    *,
    max_age_hours: int = 24,
    force_refresh: bool = False,
    persist: bool = True,
) -> FundamentalAnalysis:
    """Run all 8 fundamental sub-analyses and return a unified payload.

    Cache: when `max_age_hours` is positive and a recent row exists in
    `stock_fundamentals`, it's returned with `cached=True` (no Tavily /
    LLM cost). Pass `force_refresh=True` to bypass the cache.

    Persistence: when `persist=True` (default) and a DB connection is
    available, the result is written to `stock_fundamentals` so later
    calls can hit the cache. Database failures are logged but never
    raised — the caller still gets the full payload.
    """
    sym = (symbol or "").strip().upper()
    if not sym:
        raise ValueError("symbol is required")
    if "." not in sym:
        sym = f"{sym}.NS"
    name = (stock_name or sym.split(".")[0]).strip()

    run_t0 = time.time()
    _log(
        f"════ analyze_fundamentals: {sym} ({name}) "
        f"force_refresh={force_refresh} max_age_hours={max_age_hours} ════"
    )

    # 1. Cache check.
    if not force_refresh and max_age_hours > 0:
        _log(f"  [cache] checking DB for snapshot ≤ {max_age_hours}h old …")
        t_cache = time.time()
        cached = _load_cached(sym, max_age_hours)
        if cached is not None:
            cached.cached = True
            _log(
                f"  [cache] HIT — returning cached snapshot in "
                f"{_fmt_secs(time.time() - t_cache)}"
            )
            _log(
                f"════ analyze_fundamentals: {sym} DONE in "
                f"{_fmt_secs(time.time() - run_t0)} (cached) ════"
            )
            return cached
        _log(
            f"  [cache] MISS in {_fmt_secs(time.time() - t_cache)} — running "
            "fresh analysis"
        )

    # 2. Parallel fan-out. Political (section 3) and Legal (section 5)
    # historically waited for Directors (section 2) so they could add
    # per-director Tavily queries. That serial chain dominated wall-clock
    # (directors=60–80s, then political+legal another 60–80s on top).
    #
    # We now give directors a *short* head-start window — if it finishes
    # within `_DIRECTOR_WAIT_SEC`, political/legal pick up the names and
    # add the per-director angle. If directors is still running past that
    # budget, we dispatch political/legal at company-level only and lose
    # the per-director enrichment in exchange for a much tighter total
    # wall-clock. Sections 1, 4, 6, 8 are independent and start immediately.
    result = FundamentalAnalysis(
        symbol=sym, stock_name=name, analysis_version=ANALYSIS_VERSION,
    )

    _DIRECTOR_WAIT_SEC = 15.0  # max time political/legal will wait for director names

    from concurrent.futures import TimeoutError as _FutTimeout

    _log(
        f"  [orchestrator] dispatching 5 base sections in parallel "
        f"(max_workers={_MAX_PARALLEL_FETCHERS}): financials, directors, "
        "news, investments, pledge"
    )
    # NOTE — we use an explicit try/finally rather than `with
    # ThreadPoolExecutor(...) as pool:` because the `with` block's
    # __exit__ calls `shutdown(wait=True)`, which would block on any
    # still-running worker thread (e.g. a hung LLM call) and undo the
    # per-section timeout in `_join` below. `shutdown(wait=False,
    # cancel_futures=True)` lets the orchestrator return to the UI
    # immediately; orphaned threads eventually unblock when their
    # underlying HTTP timeout (Tavily 15s, LLM 60s) fires.
    pool = ThreadPoolExecutor(max_workers=_MAX_PARALLEL_FETCHERS)
    try:
        f_fin = pool.submit(_run_section, _fetch_financial_trend, "financials", sym, name)
        f_dir = pool.submit(_run_section, _fetch_directors, "directors", sym, name)
        f_news = pool.submit(_run_section, _fetch_news, "news", sym, name)
        f_inv = pool.submit(_run_section, _fetch_investments, "investments", sym, name)
        f_pledge = pool.submit(_run_section, _fetch_pledge, "pledge", sym, name)

        _log(
            f"  [orchestrator] waiting up to {_DIRECTOR_WAIT_SEC:.0f}s for "
            "directors before dispatching political/legal …"
        )
        t_wait = time.time()
        try:
            directors_for_aug = f_dir.result(timeout=_DIRECTOR_WAIT_SEC) or DirectorBlock()
            _log(
                f"  [orchestrator] directors ready in "
                f"{_fmt_secs(time.time() - t_wait)} "
                f"({len(directors_for_aug.directors)} found) — political/"
                "legal will use per-director queries"
            )
        except _FutTimeout:
            _log(
                f"  [orchestrator] directors still running after "
                f"{_DIRECTOR_WAIT_SEC:.0f}s — dispatching political/legal at "
                "company-level only (no per-director enrichment)"
            )
            logger.info(
                "Directors still running after %.0fs — dispatching political/"
                "legal with no per-director enrichment to keep wall-clock low",
                _DIRECTOR_WAIT_SEC,
            )
            directors_for_aug = DirectorBlock()

        f_pol = pool.submit(_run_section, _fetch_political, "political", sym, name, directors_for_aug)
        f_legal = pool.submit(_run_section, _fetch_legal, "legal", sym, name, directors_for_aug)

        # Join with a *shared* deadline so a single hung section can't
        # block the UI forever. By the time we start joining most sections
        # are usually already done; the deadline only ever triggers when
        # one section's LLM / Tavily request stalls past every retry.
        # Hung sections fall back to their default empty block so the
        # remaining 6 still render.
        join_deadline = time.time() + _SECTION_TIMEOUT_SEC
        _log(
            f"  [orchestrator] waiting up to {_SECTION_TIMEOUT_SEC:.0f}s "
            "for sections to complete …"
        )

        def _join(fut, default, label):
            """Block on `fut` up to the shared deadline; on timeout log a
            warning, cancel the future (if still pending), and return the
            section's default block so the rest of the analysis renders."""
            remaining = max(0.5, join_deadline - time.time())
            try:
                return fut.result(timeout=remaining) or default
            except _FutTimeout:
                _log(
                    f"⚠ section TIMEOUT: {label} exceeded "
                    f"{_SECTION_TIMEOUT_SEC:.0f}s — using empty default so "
                    "the rest of the analysis can render"
                )
                logger.warning(
                    "Fundamental section %s timed out after %.0fs — using default",
                    label, _SECTION_TIMEOUT_SEC,
                )
                fut.cancel()
                return default
            except Exception as exc:
                _log(f"⚠ section ERROR joining {label}: {exc}")
                logger.exception("Fundamental section %s join failed", label)
                return default

        result.financials = _join(f_fin, FinancialTrend(), "financials")
        result.directors = _join(f_dir, DirectorBlock(), "directors")
        result.news = _join(f_news, NewsBlock(), "news")
        result.investments = _join(f_inv, InvestmentsBlock(), "investments")
        result.pledge = _join(f_pledge, PledgeBlock(), "pledge")
        result.political = _join(f_pol, PoliticalBlock(), "political")
        result.legal = _join(f_legal, LegalBlock(), "legal")
        _log("  [orchestrator] all sections joined")
    finally:
        # Don't wait for any still-running worker threads — they have
        # their own HTTP timeouts (Tavily 15s, LLM 60s) as the safety
        # net. cancel_futures=True clears anything that hasn't started
        # yet; running futures will exit on their own when their HTTP
        # call returns.
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            # cancel_futures was added in Python 3.9 — fall back for
            # older interpreters by skipping the cancel hint.
            pool.shutdown(wait=False)

    # Surface overall notes — high-risk pledge, critical legal mentions, etc.
    notes: List[str] = []
    if result.pledge.risk_level in ("high", "critical"):
        notes.append(
            f"⚠️ Promoter pledge is {result.pledge.risk_level.upper()} "
            f"({result.pledge.current_percent}%) — verify with the latest "
            "NSE/BSE shareholding pattern filing."
        )
    if any(c.confidence in ("medium", "high") for c in result.legal.cases):
        notes.append(
            "⚠️ Legal / enforcement mentions surfaced — review the Legal "
            "section before relying on this analysis for an entry decision."
        )
    if result.news.negative >= max(3, result.news.positive):
        notes.append(
            "⚠️ Negative news outweighs positive in recent headlines — "
            "check the News section for context."
        )
    result.overall_notes = notes

    # 3. Persist.
    if persist:
        _log("  [persist] writing snapshot to stock_fundamentals …")
        t_persist = time.time()
        try:
            _persist(result)
            _log(f"  [persist] saved in {_fmt_secs(time.time() - t_persist)}")
        except Exception as exc:
            _log(f"  [persist] FAILED after {_fmt_secs(time.time() - t_persist)}: {exc}")
            logger.warning("Failed to persist fundamentals snapshot: %s", exc)

    total = time.time() - run_t0
    _log(
        f"════ analyze_fundamentals: {sym} DONE in {_fmt_secs(total)} — "
        f"financials={'✓' if result.financials.status.available else '—'} "
        f"({len(result.financials.yearly)}y), "
        f"directors={len(result.directors.directors)}, "
        f"political={len(result.political.connections)}, "
        f"news={len(result.news.items)} "
        f"({result.news.positive}+/{result.news.negative}-/{result.news.neutral}~), "
        f"legal={len(result.legal.cases)}, "
        f"investments={len(result.investments.investments)} "
        f"(perf×{len(result.investments.performance)}), "
        f"pledge={result.pledge.current_percent}% "
        f"[{result.pledge.risk_level}] ════"
    )
    return result


# ─────────────────────────────────────────────────────────
# Cache / persistence helpers (delegate to StockDatabase)
# ─────────────────────────────────────────────────────────

def _load_cached(symbol: str, max_age_hours: int) -> Optional[FundamentalAnalysis]:
    try:
        from database_utility.database import StockDatabase
    except Exception:
        return None
    db = StockDatabase()
    if not db.connect():
        return None
    try:
        db.create_table()  # runs migrations idempotently
        payload = db.get_fundamentals(  # type: ignore[attr-defined]
            symbol,
            max_age_hours=max_age_hours,
            analysis_version=ANALYSIS_VERSION,
        )
    except Exception as exc:
        logger.debug("Cache lookup failed: %s", exc)
        payload = None
    finally:
        db.disconnect()
    if not payload:
        return None
    try:
        return FundamentalAnalysis.model_validate(payload)
    except Exception as exc:
        logger.debug("Cached payload failed validation, ignoring: %s", exc)
        return None


def load_cached_fundamentals(
    symbol: str, max_age_hours: int = 24,
) -> Optional[FundamentalAnalysis]:
    """Public 'cache-only' lookup — returns the most recent DB snapshot
    for `symbol` if it's within `max_age_hours`, otherwise None. Never
    triggers a fresh Tavily/LLM fetch. Use this from a Streamlit page
    that wants to render an existing analysis without paying for a new
    one if the user hasn't asked for it yet."""
    sym = (symbol or "").strip().upper()
    if not sym:
        return None
    if "." not in sym:
        sym = f"{sym}.NS"
    cached = _load_cached(sym, max_age_hours)
    if cached is not None:
        cached.cached = True
    return cached


def _persist(result: FundamentalAnalysis) -> None:
    try:
        from database_utility.database import StockDatabase
    except Exception:
        return
    db = StockDatabase()
    if not db.connect():
        return
    try:
        db.create_table()
        db.save_fundamentals(  # type: ignore[attr-defined]
            stock_symbol=result.symbol,
            stock_name=result.stock_name or "",
            payload=result.model_dump(mode="json"),
            analysis_version=result.analysis_version,
        )
    finally:
        db.disconnect()
