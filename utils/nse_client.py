"""Minimal NSE India client for the 5-Year Analysis pipeline.

Scope: only the two endpoints where NSE adds clear value over screener.in +
Tavily:

  * `/api/corporate-announcements` — official BSE/NSE filings (board meetings,
    dividends, allotments, results notifications). Feeds the News section as
    high-confidence "regulatory" items.
  * `/api/corporates-pit` — Prohibition of Insider Trading filings, which
    include the SAST pledge/encumbrance disclosures (Annex 7(2)/7(3)). Feeds
    the Pledge section with exact transaction history.

Design notes
------------
* **Silent fallback.** Every public helper returns `[]` on any error
  (network, parse, Akamai block). The caller treats that as "NSE has nothing
  to add" and keeps using the existing screener.in / Tavily output.
* **Thread-safe in-process cache.** The orchestrator runs sections in
  parallel; both the news and pledge sections may call NSE for the same
  symbol. We cache responses for `_NSE_TTL_SEC` so the second caller hits
  memory instead of the network.
* **No Playwright.** NSE's `/api/...` endpoints respond to plain `requests`
  with a real-browser User-Agent. The homepage warmup is best-effort — we
  attempt it once per process and continue even if it 403s (which it
  sometimes does, but the JSON endpoints stay accessible).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


_NSE_BASE = "https://www.nseindia.com"
_NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": f"{_NSE_BASE}/",
    "Connection": "keep-alive",
}
_NSE_HTTP_TIMEOUT = 10.0
_NSE_TTL_SEC = 300  # 5-min cache TTL per (endpoint, symbol)

# ─────────────────────────────────────────────────────────
# Session + cache (thread-safe)
# ─────────────────────────────────────────────────────────

_session: Optional[requests.Session] = None
_session_lock = threading.Lock()
_warmed_up = False

_cache: Dict[Tuple[str, str], Tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def _get_session() -> requests.Session:
    """Lazy-initialize the module session with browser-like headers and a
    one-shot homepage warmup. The warmup attempts to seed Akamai cookies;
    even if it 403s we still return the session because the JSON endpoints
    have been observed to respond regardless."""
    global _session, _warmed_up
    if _session is not None and _warmed_up:
        return _session
    with _session_lock:
        if _session is None:
            s = requests.Session()
            s.headers.update(_NSE_HEADERS)
            _session = s
        if not _warmed_up:
            try:
                _session.get(_NSE_BASE + "/", timeout=_NSE_HTTP_TIMEOUT)
            except Exception as exc:
                logger.debug("NSE warmup request failed (ignored): %s", exc)
            _warmed_up = True
    return _session


def _cache_get(endpoint: str, symbol: str) -> Optional[Any]:
    key = (endpoint, symbol)
    with _cache_lock:
        hit = _cache.get(key)
    if hit and (time.time() - hit[0]) < _NSE_TTL_SEC:
        return hit[1]
    return None


def _cache_put(endpoint: str, symbol: str, value: Any) -> None:
    with _cache_lock:
        _cache[(endpoint, symbol)] = (time.time(), value)


def _clean_symbol(symbol: str) -> str:
    """Strip `.NS` / `.BO` and uppercase — NSE expects the bare ticker."""
    return (symbol or "").strip().upper().replace(".NS", "").replace(".BO", "")


def _get_json(endpoint: str, symbol: str) -> Optional[Any]:
    """GET an NSE endpoint, returning parsed JSON or None on any failure.
    Silent — callers treat None as "no extra data"."""
    cached = _cache_get(endpoint, symbol)
    if cached is not None:
        return cached
    sess = _get_session()
    url = f"{_NSE_BASE}{endpoint}"
    try:
        resp = sess.get(url, timeout=_NSE_HTTP_TIMEOUT)
        if resp.status_code != 200:
            logger.debug("NSE %s returned HTTP %s", url, resp.status_code)
            _cache_put(endpoint, symbol, None)
            return None
        data = resp.json()
    except Exception as exc:
        logger.debug("NSE %s failed: %s", url, exc)
        _cache_put(endpoint, symbol, None)
        return None
    _cache_put(endpoint, symbol, data)
    return data


# ─────────────────────────────────────────────────────────
# Public helpers
# ─────────────────────────────────────────────────────────

def fetch_announcements(
    symbol: str, *, limit: int = 25, max_days_old: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Return recent corporate announcements for `symbol`.

    Each item is a dict with the relevant NSE fields normalised:
      * `symbol`         — NSE ticker
      * `title`          — `attchmntText` (full headline) or `desc`
      * `category`       — short `desc` (e.g. "Press Release", "Acquisition")
      * `published`      — `an_dt` (human-readable announcement timestamp)
      * `published_iso`  — same parsed to ISO when possible
      * `link`           — `attchmntFile` (PDF on nsearchives.nseindia.com)

    Returns `[]` silently on any error.

    `limit`: cap the returned list (NSE serves ~3000 items historically).
    `max_days_old`: optional — drop items older than this many days.
    """
    clean = _clean_symbol(symbol)
    if not clean:
        return []
    endpoint = f"/api/corporate-announcements?index=equities&symbol={clean}"
    raw = _get_json(endpoint, clean)
    if not raw:
        return []
    items = raw if isinstance(raw, list) else raw.get("data", []) or []

    cutoff: Optional[float] = None
    if max_days_old is not None:
        cutoff = time.time() - (max_days_old * 86400.0)

    out: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        an_dt = (it.get("an_dt") or "").strip()
        published_iso = _parse_nse_datetime(an_dt)
        if cutoff is not None and published_iso is not None:
            if published_iso < cutoff:
                continue
        out.append({
            "symbol": (it.get("symbol") or clean).strip(),
            "title": (it.get("attchmntText") or it.get("desc") or "").strip(),
            "category": (it.get("desc") or "").strip(),
            "published": an_dt,
            "published_ts": published_iso,
            "link": (it.get("attchmntFile") or "").strip() or None,
            "industry": (it.get("smIndustry") or "").strip() or None,
        })
        if len(out) >= limit:
            break
    return out


# Pledge / encumbrance signals inside PIT filings. Most pledge events use
# `tdpTransactionType=Pledge` and `acqMode` includes "Pledge Creation",
# "Pledge Invocation", or "Pledge Release"; we also match the broader
# "encumbrance" wording in case NSE renames the field.
_PLEDGE_TX_KEYWORDS = ("pledge", "encumbr")


def fetch_pledge_filings(
    symbol: str, *, limit: int = 50,
) -> List[Dict[str, Any]]:
    """Return SAST/PIT pledge events for `symbol`, newest first.

    Each item is a dict with:
      * `acquirer`           — `acqName` (pledger / pledgee / trustee)
      * `transaction_type`   — `tdpTransactionType` (usually "Pledge")
      * `mode`               — `acqMode` (Pledge Creation/Release/Invocation/...)
      * `shares`             — `secAcq` (number of shares in this event)
      * `value`              — `secVal` (transaction value in rupees)
      * `before_pct`         — `befAcqSharesPer` (% holding before event)
      * `after_pct`          — `afterAcqSharesPer` (% holding after event)
      * `date`               — `acqfromDt` (event date)
      * `intimation_date`    — `intimDt` (filing date)
      * `category`           — `personCategory` (Promoter / Designated Employee)
      * `xbrl_url`           — link to the underlying XBRL filing

    Returns `[]` silently on any error. Non-pledge PIT items (regular
    buys/sells by employees) are filtered out.

    The endpoint defaults to ~20 most-recent filings — passing an
    explicit wide date range bumps this to the full history (verified
    27 vs. 20 for BAJAJHIND), so we always request from 2015 to next
    year to catch every filing on file.
    """
    clean = _clean_symbol(symbol)
    if not clean:
        return []
    from datetime import datetime
    to_year = datetime.utcnow().year + 1
    endpoint = (
        f"/api/corporates-pit?symbol={clean}"
        f"&from_date=01-01-2015&to_date=31-12-{to_year}"
    )
    raw = _get_json(endpoint, clean)
    if not raw or not isinstance(raw, dict):
        return []
    items = raw.get("data", []) or []
    out: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        tx = (it.get("tdpTransactionType") or "").lower()
        mode = (it.get("acqMode") or "").lower()
        if not any(k in tx or k in mode for k in _PLEDGE_TX_KEYWORDS):
            continue
        out.append({
            "acquirer": (it.get("acqName") or "").strip(),
            "transaction_type": it.get("tdpTransactionType") or "",
            "mode": it.get("acqMode") or "",
            "shares": _safe_int(it.get("secAcq")),
            "value": _safe_int(it.get("secVal")),
            "before_pct": _safe_float(it.get("befAcqSharesPer")),
            "after_pct": _safe_float(it.get("afterAcqSharesPer")),
            "date": (it.get("acqfromDt") or "").strip(),
            "intimation_date": (it.get("intimDt") or "").strip(),
            "category": (it.get("personCategory") or "").strip(),
            "xbrl_url": (it.get("xbrl") or "").strip() or None,
        })
        if len(out) >= limit:
            break
    # Newest first by intimation_date when present.
    out.sort(key=lambda r: r.get("intimation_date") or "", reverse=True)
    return out


# ─────────────────────────────────────────────────────────
# Internal parsing helpers
# ─────────────────────────────────────────────────────────

def _parse_nse_datetime(s: str) -> Optional[float]:
    """Parse NSE's `'12-May-2026 11:30:07'` timestamp to a unix epoch.
    Returns None on failure."""
    if not s:
        return None
    from datetime import datetime
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y"):
        try:
            return datetime.strptime(s, fmt).timestamp()
        except ValueError:
            continue
    return None


def _safe_int(v: Any) -> Optional[int]:
    if v is None or v == "" or v == "-":
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _safe_float(v: Any) -> Optional[float]:
    if v is None or v == "" or v == "-":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
