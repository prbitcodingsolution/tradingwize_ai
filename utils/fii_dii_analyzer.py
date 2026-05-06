"""
FII/DII Institutional Sentiment Analyzer

Data sources (priority order):
1. screener.in shareholding pattern table (quarterly history)
2. yfinance major_holders (current snapshot only)
3. Cached CompanyData (if already fetched)

Scoring: score = (level_score * 0.4) + (trend_score * 0.6)
Trend is weighted more because rising FII from 5->8% is more bullish
than falling FII from 20->15%.
"""

import requests
import yfinance as yf
from bs4 import BeautifulSoup
from datetime import datetime
from typing import Optional, List, Dict, Tuple

from models import FIIDIISentiment, QuarterlyHolding

# ─────────────────────────────────────────────────────────
# SCORING CONSTANTS
# ─────────────────────────────────────────────────────────
FII_LEVEL_BENCHMARKS = {
    "very_high": 20.0,
    "high":      12.0,
    "moderate":   6.0,
    "low":        2.0,
}

DII_LEVEL_BENCHMARKS = {
    "very_high": 15.0,
    "high":       8.0,
    "moderate":   3.0,
    "low":        1.0,
}

TREND_THRESHOLDS = {
    "strong_increase":  1.5,
    "increase":         0.3,
    "decrease":        -0.3,
    "strong_decrease": -1.5,
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


# ─────────────────────────────────────────────────────────
# DATA FETCHER: screener.in (quarterly history)
# ─────────────────────────────────────────────────────────

def _clean_pct(text: str) -> Optional[float]:
    """Parse '19.09%' or '19.09' to float. Returns None on failure."""
    try:
        clean = text.strip().replace('%', '').replace(',', '')
        if not clean or clean == '-':
            return None
        return round(float(clean), 2)
    except (ValueError, TypeError):
        return None


def fetch_quarterly_holdings_from_screener(symbol: str) -> Optional[List[QuarterlyHolding]]:
    """
    Scrape quarterly FII/DII history from screener.in shareholding table.
    Returns list of QuarterlyHolding (oldest first), or None on failure.
    """
    clean_sym = symbol.replace(".NS", "").replace(".BO", "").upper()

    # Try consolidated first, then standalone (10s timeout to avoid blocking UI)
    resp = None
    for suffix in ["/consolidated/", "/"]:
        url = f"https://www.screener.in/company/{clean_sym}{suffix}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code == 200:
                break
            resp = None
        except Exception:
            resp = None
            continue

    if resp is None or resp.status_code != 200:
        return None

    try:
        soup = BeautifulSoup(resp.text, 'html.parser')
        sh_section = soup.find('section', {'id': 'shareholding'})
        if not sh_section:
            return None

        table = sh_section.find('table')
        if not table:
            return None

        # Parse header row to find column indices
        thead = table.find('thead')
        if not thead:
            return None

        headers_row = thead.find('tr')
        if not headers_row:
            return None

        ths = headers_row.find_all('th')
        col_names = [th.get_text(strip=True).lower() for th in ths]

        # Map column indices
        col_map = {}
        for i, name in enumerate(col_names):
            if 'promoter' in name:
                col_map['promoter'] = i
            elif 'fii' in name or 'foreign' in name:
                col_map['fii'] = i
            elif 'dii' in name or 'domestic' in name:
                col_map['dii'] = i
            elif 'public' in name:
                col_map['public'] = i

        if 'fii' not in col_map and 'dii' not in col_map:
            return None

        # Parse body rows — each row is a quarter
        tbody = table.find('tbody')
        if not tbody:
            return None

        holdings = []
        rows = tbody.find_all('tr')
        for row in rows:
            cells = row.find_all('td')
            if len(cells) < 2:
                continue

            # First cell is the category name (Promoters+, FIIs+, etc.)
            # This is the TRANSPOSED layout — rows are categories, columns are quarters
            # We need to detect the layout
            first_text = cells[0].get_text(strip=True)

            # Check if first cell looks like a quarter name (e.g., "Sep 2024")
            # or a category name (e.g., "Promoters+", "FIIs+")
            if any(m in first_text for m in ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                                              'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']):
                # Row-per-quarter layout (rare on screener.in)
                quarter = first_text
                fii = _clean_pct(cells[col_map['fii']].get_text(strip=True)) if 'fii' in col_map else None
                dii = _clean_pct(cells[col_map['dii']].get_text(strip=True)) if 'dii' in col_map else None
                promoter = _clean_pct(cells[col_map['promoter']].get_text(strip=True)) if 'promoter' in col_map else None
                public = _clean_pct(cells[col_map['public']].get_text(strip=True)) if 'public' in col_map else None

                if fii is not None or dii is not None:
                    holdings.append(QuarterlyHolding(
                        quarter=quarter,
                        fii_pct=fii if fii is not None else 0.0,
                        dii_pct=dii if dii is not None else 0.0,
                        promoter_pct=promoter,
                        public_pct=public,
                    ))

        # If no row-per-quarter data found, try the TRANSPOSED layout
        # (screener.in default: rows=categories, columns=quarters)
        if not holdings:
            holdings = _parse_transposed_shareholding(table)

        if holdings:
            # Oldest first
            holdings.reverse()
            return holdings[-8:]  # max 8 quarters

        return None

    except Exception as e:
        print(f"   FII/DII scraper error: {e}")
        return None


def _parse_transposed_shareholding(table) -> List[QuarterlyHolding]:
    """
    Parse screener.in transposed table where:
    - Columns = quarters (header row has dates like Sep 2024, Jun 2024, ...)
    - Rows = categories (Promoters+, FIIs+, DIIs+, Public+)
    """
    thead = table.find('thead')
    if not thead:
        return []

    # Get quarter names from header
    ths = thead.find_all('th')
    quarters = []
    for th in ths[1:]:  # skip first (empty or label)
        text = th.get_text(strip=True)
        if text:
            quarters.append(text)

    if not quarters:
        return []

    # Build per-quarter data from body rows
    tbody = table.find('tbody')
    if not tbody:
        return []

    # Initialize data for each quarter
    q_data = {q: {} for q in quarters}

    rows = tbody.find_all('tr')
    for row in rows:
        cells = row.find_all('td')
        if len(cells) < 2:
            continue

        cat = cells[0].get_text(strip=True).lower()

        # Determine category
        cat_key = None
        if 'promoter' in cat:
            cat_key = 'promoter'
        elif 'fii' in cat or 'foreign' in cat:
            cat_key = 'fii'
        elif 'dii' in cat or 'domestic' in cat:
            cat_key = 'dii'
        elif 'public' in cat:
            cat_key = 'public'

        if not cat_key:
            continue

        # Fill values for each quarter column
        for i, cell in enumerate(cells[1:]):
            if i < len(quarters):
                val = _clean_pct(cell.get_text(strip=True))
                if val is not None:
                    q_data[quarters[i]][cat_key] = val

    # Build QuarterlyHolding list (newest first, will be reversed by caller)
    holdings = []
    for q in quarters:
        d = q_data[q]
        fii = d.get('fii')
        dii = d.get('dii')

        # Calculate DII from other values if missing
        if dii is None and d.get('promoter') is not None and fii is not None and d.get('public') is not None:
            dii = round(100.0 - d.get('promoter', 0) - fii - d.get('public', 0), 2)
            if dii < 0:
                dii = 0.0

        if fii is not None or dii is not None:
            holdings.append(QuarterlyHolding(
                quarter=q,
                fii_pct=fii if fii is not None else 0.0,
                dii_pct=dii if dii is not None else 0.0,
                promoter_pct=d.get('promoter'),
                public_pct=d.get('public'),
            ))

    return holdings


# ─────────────────────────────────────────────────────────
# DATA FETCHER: yfinance fallback
# ─────────────────────────────────────────────────────────

def fetch_current_holdings_from_yfinance(symbol: str) -> Optional[Dict]:
    """Fetch current FII/DII from yfinance. Returns dict or None."""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        inst = info.get("heldPercentInstitutions")
        if inst:
            inst_pct = float(inst) * 100
            return {
                "fii_pct": round(inst_pct * 0.60, 2),
                "dii_pct": round(inst_pct * 0.40, 2),
                "source": "yfinance_estimated",
            }
        return None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────
# TREND CALCULATOR
# ─────────────────────────────────────────────────────────

def _compute_trend(history: List[QuarterlyHolding], key: str) -> Tuple[str, Optional[float], Optional[float]]:
    """Compute trend direction and change for FII or DII."""
    if not history or len(history) < 2:
        return "Stable", None, None

    values = [getattr(h, key) for h in history]
    latest = values[-1]
    prev_1q = values[-2]
    prev_4q = values[-5] if len(values) >= 5 else values[0]

    change_1q = round(latest - prev_1q, 2)
    change_4q = round(latest - prev_4q, 2)

    if change_1q >= TREND_THRESHOLDS["strong_increase"]:
        trend = "Strongly Increasing"
    elif change_1q >= TREND_THRESHOLDS["increase"]:
        trend = "Increasing"
    elif change_1q <= TREND_THRESHOLDS["strong_decrease"]:
        trend = "Strongly Decreasing"
    elif change_1q <= TREND_THRESHOLDS["decrease"]:
        trend = "Decreasing"
    else:
        trend = "Stable"

    return trend, change_1q, change_4q


# ─────────────────────────────────────────────────────────
# SCORING ENGINE
# ─────────────────────────────────────────────────────────

def _compute_level_score(fii_pct: float, dii_pct: float) -> float:
    """Score (0-100) based on absolute FII + DII holding levels."""
    if fii_pct >= FII_LEVEL_BENCHMARKS["very_high"]:     fii_level = 50
    elif fii_pct >= FII_LEVEL_BENCHMARKS["high"]:        fii_level = 38
    elif fii_pct >= FII_LEVEL_BENCHMARKS["moderate"]:    fii_level = 25
    elif fii_pct >= FII_LEVEL_BENCHMARKS["low"]:         fii_level = 12
    else:                                                 fii_level = 5

    if dii_pct >= DII_LEVEL_BENCHMARKS["very_high"]:     dii_level = 50
    elif dii_pct >= DII_LEVEL_BENCHMARKS["high"]:        dii_level = 38
    elif dii_pct >= DII_LEVEL_BENCHMARKS["moderate"]:    dii_level = 25
    elif dii_pct >= DII_LEVEL_BENCHMARKS["low"]:         dii_level = 12
    else:                                                 dii_level = 5

    return float(fii_level + dii_level)


def _compute_trend_score(fii_trend: str, dii_trend: str,
                         fii_change_1q: Optional[float],
                         dii_change_1q: Optional[float]) -> float:
    """Score (0-100) based on trend direction."""
    TREND_SCORES = {
        "Strongly Increasing": 90,
        "Increasing":          70,
        "Stable":              50,
        "Decreasing":          30,
        "Strongly Decreasing": 10,
    }
    fii_score = TREND_SCORES.get(fii_trend, 50)
    dii_score = TREND_SCORES.get(dii_trend, 50)
    return round(fii_score * 0.55 + dii_score * 0.45, 2)


def _compute_institutional_sentiment_score(
    fii_pct: float, dii_pct: float,
    fii_trend: str, dii_trend: str,
    fii_change_1q: Optional[float], dii_change_1q: Optional[float],
) -> float:
    """Final score (0-100). Formula: level*0.4 + trend*0.6"""
    level = _compute_level_score(fii_pct, dii_pct)
    trend = _compute_trend_score(fii_trend, dii_trend, fii_change_1q, dii_change_1q)
    score = (level * 0.40) + (trend * 0.60)
    return round(min(100, max(0, score)), 2)


def _get_sentiment_label(score: float) -> str:
    if score >= 75:   return "Very Bullish"
    elif score >= 60: return "Bullish"
    elif score >= 40: return "Neutral"
    elif score >= 25: return "Bearish"
    else:             return "Very Bearish"


# ─────────────────────────────────────────────────────────
# RECOMMENDATION ENGINE
# ─────────────────────────────────────────────────────────

def _generate_recommendation(
    score: float, fii_pct: float, dii_pct: float,
    fii_trend: str, dii_trend: str,
    fii_change_1q: Optional[float], dii_change_1q: Optional[float],
    fii_change_4q: Optional[float], dii_change_4q: Optional[float],
) -> Tuple[str, str, List[str]]:
    """Generate recommendation with reasoning bullets."""
    reasoning = []

    total_inst = round(fii_pct + dii_pct, 2)
    reasoning.append(
        f"Total institutional holding is {total_inst:.2f}% "
        f"(FII: {fii_pct:.2f}% + DII: {dii_pct:.2f}%)"
    )

    if "Increasing" in fii_trend and fii_change_1q:
        reasoning.append(
            f"FII holding has {fii_trend.lower()} by {fii_change_1q:+.2f}pp this quarter "
            f"- foreign investors are actively buying"
        )
    elif "Decreasing" in fii_trend and fii_change_1q:
        reasoning.append(
            f"FII holding has {fii_trend.lower()} by {fii_change_1q:+.2f}pp this quarter "
            f"- foreign investors are reducing positions"
        )
    else:
        reasoning.append("FII holding is stable - no significant foreign buying or selling")

    if "Increasing" in dii_trend and dii_change_1q:
        reasoning.append(
            f"DII holding has {dii_trend.lower()} by {dii_change_1q:+.2f}pp "
            f"- domestic institutions (mutual funds, insurance) are accumulating"
        )
    elif "Decreasing" in dii_trend and dii_change_1q:
        reasoning.append(
            f"DII holding has {dii_trend.lower()} by {dii_change_1q:+.2f}pp "
            f"- domestic funds are trimming holdings"
        )

    if fii_change_4q is not None:
        if fii_change_4q > 2.0:
            reasoning.append(
                f"Over 4 quarters, FII increased by {fii_change_4q:+.2f}pp "
                f"- consistent long-term foreign confidence"
            )
        elif fii_change_4q < -2.0:
            reasoning.append(
                f"Over 4 quarters, FII declined by {fii_change_4q:+.2f}pp "
                f"- sustained foreign selling is a concern"
            )

    if "Increasing" in fii_trend and "Decreasing" in dii_trend:
        reasoning.append(
            "Divergence: FII buying while DII selling "
            "- foreign investors more optimistic than domestic funds"
        )
    elif "Decreasing" in fii_trend and "Increasing" in dii_trend:
        reasoning.append(
            "Divergence: DII buying while FII selling "
            "- domestic funds accumulating as foreign money exits (could be opportunity)"
        )

    if score >= 75:
        rec, color = "Strong Buy Signal", "green"
    elif score >= 60:
        rec, color = "Buy Signal", "#4caf50"
    elif score >= 40:
        rec, color = "Neutral - Monitor", "gray"
    elif score >= 25:
        rec, color = "Caution - Weak Institutional Interest", "orange"
    else:
        rec, color = "Avoid - Institutional Selling", "red"

    return rec, color, reasoning


# ─────────────────────────────────────────────────────────
# MAIN PUBLIC FUNCTION
# ─────────────────────────────────────────────────────────

def get_fii_dii_sentiment(
    symbol: str,
    company_name: Optional[str] = None,
    cached_fii: Optional[float] = None,
    cached_dii: Optional[float] = None,
) -> FIIDIISentiment:
    """
    Main entry point. Computes the full FII/DII institutional sentiment.

    Args:
        symbol: NSE/BSE ticker (e.g., "TCS.NS")
        company_name: Optional display name
        cached_fii: If CompanyData already has FII %, pass it to skip re-fetching
        cached_dii: If CompanyData already has DII %, pass it to skip re-fetching

    Returns:
        FIIDIISentiment with score, trend, chart data, and recommendation
    """
    # Step 1: Fetch quarterly history from screener.in
    quarterly_history = fetch_quarterly_holdings_from_screener(symbol)
    data_source = "screener_in"
    data_freshness = "Live"

    # Step 2: Get current FII/DII
    current_fii = None
    current_dii = None

    if quarterly_history:
        latest_q = quarterly_history[-1]
        current_fii = latest_q.fii_pct
        current_dii = latest_q.dii_pct

    if current_fii is None and cached_fii is not None:
        current_fii = cached_fii
        current_dii = cached_dii or 0.0
        data_source = "cached"
        data_freshness = "Cached"

    if current_fii is None:
        yf_data = fetch_current_holdings_from_yfinance(symbol)
        if yf_data:
            current_fii = yf_data["fii_pct"]
            current_dii = yf_data["dii_pct"]
            data_source = "yfinance"
            data_freshness = "Estimated"
        else:
            current_fii = 0.0
            current_dii = 0.0
            data_source = "unavailable"
            data_freshness = "Unavailable"

    current_fii = current_fii or 0.0
    current_dii = current_dii or 0.0

    # Step 3: If no quarterly history, create single-point
    if not quarterly_history:
        quarterly_history = [
            QuarterlyHolding(quarter="Current", fii_pct=current_fii, dii_pct=current_dii)
        ]

    # Step 4: Compute trends
    fii_trend, fii_change_1q, fii_change_4q = _compute_trend(quarterly_history, "fii_pct")
    dii_trend, dii_change_1q, dii_change_4q = _compute_trend(quarterly_history, "dii_pct")

    # Step 5: Score
    score = _compute_institutional_sentiment_score(
        current_fii, current_dii, fii_trend, dii_trend, fii_change_1q, dii_change_1q
    )
    sentiment_label = _get_sentiment_label(score)

    # Step 6: Recommendation
    recommendation, rec_color, reasoning = _generate_recommendation(
        score, current_fii, current_dii,
        fii_trend, dii_trend,
        fii_change_1q, dii_change_1q,
        fii_change_4q, dii_change_4q,
    )

    return FIIDIISentiment(
        symbol=symbol,
        company_name=company_name,
        current_fii_pct=round(current_fii, 2),
        current_dii_pct=round(current_dii, 2),
        current_total_institutional=round(current_fii + current_dii, 2),
        quarterly_history=quarterly_history,
        fii_trend=fii_trend,
        dii_trend=dii_trend,
        fii_change_1q=fii_change_1q,
        fii_change_4q=fii_change_4q,
        dii_change_1q=dii_change_1q,
        dii_change_4q=dii_change_4q,
        institutional_sentiment_score=score,
        sentiment_label=sentiment_label,
        recommendation=recommendation,
        recommendation_color=rec_color,
        reasoning=reasoning,
        data_source=data_source,
        data_freshness=data_freshness,
        timestamp=datetime.utcnow(),
    )


# ─────────────────────────────────────────────────────────
# DB PERSISTENCE HELPERS
# ─────────────────────────────────────────────────────────

def _fmt_change(change: Optional[float]) -> str:
    if change is None:
        return "N/A"
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.2f}pp"


def build_fii_dii_analysis_text(result: "FIIDIISentiment") -> str:
    """Render a FIIDIISentiment into the plain-text block that gets
    stored in ``stock_analysis.fii_dii_analysis`` and later fed to the
    FinRobot reasoning agent. Structure mirrors what the UI renders so
    the LLM sees the same numbers the user sees on the dashboard.
    """
    if result is None:
        return ""

    lines: List[str] = [
        f"FII/DII Institutional Sentiment — {result.company_name or result.symbol}",
        "",
        f"Recommendation: {result.recommendation}",
        f"Institutional Score: {result.institutional_sentiment_score:.1f}/100 ({result.sentiment_label})",
        "",
        "Current Holdings:",
        f"  - FII:   {result.current_fii_pct:.2f}%   "
        f"(1Q: {_fmt_change(result.fii_change_1q)}, "
        f"4Q: {_fmt_change(result.fii_change_4q)}, trend: {result.fii_trend})",
        f"  - DII:   {result.current_dii_pct:.2f}%   "
        f"(1Q: {_fmt_change(result.dii_change_1q)}, "
        f"4Q: {_fmt_change(result.dii_change_4q)}, trend: {result.dii_trend})",
        f"  - Total Institutional: {result.current_total_institutional:.2f}%",
    ]

    if result.quarterly_history:
        lines.append("")
        lines.append("Quarterly History (oldest → newest):")
        for h in result.quarterly_history[-8:]:
            lines.append(
                f"  - {h.quarter}: FII {h.fii_pct:.2f}% | DII {h.dii_pct:.2f}%"
            )

    if result.reasoning:
        lines.append("")
        lines.append("Analysis:")
        for r in result.reasoning:
            lines.append(f"  - {r}")

    lines.append("")
    lines.append(
        f"Source: {result.data_source} | Freshness: {result.data_freshness} | "
        f"Computed: {result.timestamp.strftime('%Y-%m-%d %H:%M UTC')}"
    )
    return "\n".join(lines)


def persist_fii_dii_analysis(stock_symbol: str, result: "FIIDIISentiment") -> bool:
    """Format the FII/DII sentiment result and write it to the
    ``stock_analysis.fii_dii_analysis`` column for the latest row of the
    given symbol. Best-effort — failures are logged, not raised, so
    the dashboard render never breaks because of a DB hiccup.

    Returns True on success, False otherwise.
    """
    try:
        if not stock_symbol or result is None:
            return False
        text = build_fii_dii_analysis_text(result)
        if not text:
            return False
        from database_utility.database import StockDatabase
        db = StockDatabase()
        if not db.connect():
            print(f"⚠️ [fii_dii] DB connect failed while persisting {stock_symbol}")
            return False
        try:
            return db.update_fii_dii_analysis(
                stock_symbol=stock_symbol,
                fii_dii_analysis=text,
            )
        finally:
            db.disconnect()
    except Exception as e:
        print(f"⚠️ [fii_dii] persist failed for {stock_symbol}: {e}")
        return False
