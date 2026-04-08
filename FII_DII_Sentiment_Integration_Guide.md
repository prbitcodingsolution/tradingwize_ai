# TradingWize — FII & DII Institutional Sentiment Feature
### Implementation Guide for Claude Code

---

## 📌 What This Task Is

Add a new **FII/DII Institutional Sentiment** section inside the existing **Sentiment tab** of TradingWize. This section will:

1. Fetch current FII % and DII % holding data for any NSE/BSE stock
2. Fetch **historical quarterly FII/DII holding data** (trend over last 4–6 quarters)
3. Compute an **Institutional Sentiment Score** (0–100) based on holding levels + trend direction
4. Display a clear **Buy / Neutral / Avoid** recommendation with reasoning
5. Show a **trend chart** (FII + DII holdings over quarters)
6. Add a new `get_fii_dii_sentiment` agent tool so the chat interface can also answer FII/DII questions

---

## 📂 Where FII/DII Data Already Exists

**Important**: The existing `CompanyData` model already stores FII and DII as **current snapshot percentages** inside `market_data.Holdings`. These come from `yfinance` via the existing `data_fetcher.py` or `tools.py`.

```
CompanyData
└── market_data
    └── Holdings
        ├── promoter   (promoter holding %)
        ├── FII        (foreign institutional investor %)
        └── DII        (domestic institutional investor %)
```

This gives us the **current period** snapshot. What we need to ADD is:
- **Historical quarterly trend** (last 4–8 quarters of FII/DII %) — for trend analysis
- **Quarter-over-quarter change** (is FII increasing or decreasing?)
- **Computed sentiment score and recommendation**

---

## 📡 Data Sources for Historical FII/DII Trend

Use these two sources (in priority order):

### Source 1 — `yfinance` (primary, always try first)
```python
import yfinance as yf
ticker = yf.Ticker("TCS.NS")

# Institutional holders (FII-equivalent for Indian stocks on yfinance)
inst_holders = ticker.institutional_holders    # DataFrame
major_holders = ticker.major_holders          # Shows % breakdown
```

`major_holders` returns a table with rows like:
- `% of Shares Held by All Insider` (Promoter equivalent)
- `% of Shares Held by Institutions` (FII + FPI equivalent)

`institutional_holders` gives individual institution names and their share counts — use this to compute total institutional holding % over time when quarterly data is available.

### Source 2 — `screener.in` scraping (fallback for Indian-specific quarterly data)
The existing `screener_scraper.py` already scrapes screener.in. Screener.in has a "Shareholding Pattern" section with quarterly FII/DII data in a table format.

URL pattern: `https://www.screener.in/company/{SYMBOL_WITHOUT_NS}/`

The shareholding table on screener.in has columns like:
```
Quarter | Promoters% | FII%  | DII%  | Public%
Sep 24  | 72.38      | 12.54 | 5.21  | 9.87
Jun 24  | 72.38      | 11.98 | 5.45  | 10.19
Mar 24  | 72.38      | 11.20 | 5.89  | 10.53
Dec 23  | 72.38      | 10.87 | 6.02  | 10.73
```

This is the **best source** for Indian stock quarterly FII/DII trend — use it as primary when screener scraping is available.

---

## 🏗️ Implementation Plan

### Files to Create (new)
```
utils/
└── fii_dii_analyzer.py     ← New: all FII/DII logic (fetching, scoring, recommendation)
```

### Files to Update (additive only)
```
app_advanced.py             ← Add FII/DII section inside existing Sentiment tab
agent1.py                   ← Add get_fii_dii_sentiment tool
models.py                   ← Add FIIDIIData Pydantic model
```

---

## 📋 Detailed Implementation

---

### STEP 1 — Add Pydantic Models to `models.py`

Add these new models to the existing `models.py`. Do NOT change any existing models:

```python
# Add to models.py

from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime


class QuarterlyHolding(BaseModel):
    """FII/DII holding for a single quarter."""
    quarter: str            # e.g., "Sep 2024", "Jun 2024"
    fii_pct: float          # FII holding % for that quarter
    dii_pct: float          # DII holding % for that quarter
    promoter_pct: Optional[float] = None
    public_pct: Optional[float] = None


class FIIDIISentiment(BaseModel):
    """
    Complete FII/DII institutional sentiment analysis for a stock.
    """
    symbol: str
    company_name: Optional[str] = None

    # Current snapshot
    current_fii_pct: float          # Latest FII holding %
    current_dii_pct: float          # Latest DII holding %
    current_total_institutional: float  # FII + DII combined

    # Trend data (last 4-8 quarters, oldest first)
    quarterly_history: List[QuarterlyHolding] = []

    # Trend direction
    fii_trend: str                  # "Increasing" | "Decreasing" | "Stable"
    dii_trend: str                  # "Increasing" | "Decreasing" | "Stable"
    fii_change_1q: Optional[float] = None   # change vs last quarter (percentage points)
    fii_change_4q: Optional[float] = None   # change vs 4 quarters ago
    dii_change_1q: Optional[float] = None
    dii_change_4q: Optional[float] = None

    # Scoring
    institutional_sentiment_score: float    # 0-100
    sentiment_label: str                    # "Very Bullish" | "Bullish" | "Neutral" | "Bearish" | "Very Bearish"

    # Recommendation
    recommendation: str                     # "Strong Buy Signal" | "Buy Signal" | "Neutral" | "Caution" | "Avoid"
    recommendation_color: str              # "green" | "lightgreen" | "gray" | "orange" | "red"
    reasoning: List[str]                   # bullet points explaining the recommendation

    # Metadata
    data_source: str                        # "screener_in" | "yfinance" | "cached"
    data_freshness: str                     # "Live" | "Cached" | "Estimated"
    timestamp: datetime
```

---

### STEP 2 — Create `utils/fii_dii_analyzer.py`

This is the main new file. It handles all data fetching, trend computation, scoring, and recommendation logic.

```python
# utils/fii_dii_analyzer.py

"""
FII/DII Institutional Sentiment Analyzer for TradingWize

Data sources (in priority order):
1. screener.in shareholding pattern table (best for Indian quarterly data)
2. yfinance major_holders / institutional_holders
3. CompanyData cache (if already fetched)

Scoring Logic:
- FII % level:      higher = more foreign institutional confidence
- DII % level:      higher = more domestic institutional confidence  
- FII trend:        increasing = bullish signal, decreasing = bearish
- DII trend:        increasing = bullish signal, decreasing = bearish
- Combined trend:   both increasing = strong buy signal

The score uses:
  score = (level_score * 0.4) + (trend_score * 0.6)
  
Trend is weighted more than level because a RISING FII from 5%→8%
is more bullish than a FALLING FII from 20%→15%.
"""

import re
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime
from typing import Optional, List, Dict, Tuple
from models import FIIDIISentiment, QuarterlyHolding


# ─────────────────────────────────────────────────────────────
# SCORING CONSTANTS
# ─────────────────────────────────────────────────────────────

# FII level benchmarks for Indian market (NSE/BSE)
# These are approximate market norms — adjust if needed
FII_LEVEL_BENCHMARKS = {
    "very_high": 20.0,   # FII > 20% = very high foreign interest
    "high":      12.0,   # FII > 12% = high
    "moderate":   6.0,   # FII > 6%  = moderate
    "low":        2.0,   # FII > 2%  = low
    # below 2% = very low
}

DII_LEVEL_BENCHMARKS = {
    "very_high": 15.0,
    "high":       8.0,
    "moderate":   3.0,
    "low":        1.0,
}

# Trend thresholds (percentage point change)
TREND_THRESHOLDS = {
    "strong_increase":  1.5,   # > +1.5 pp in one quarter = strong increase
    "increase":         0.3,   # > +0.3 pp = increasing
    "decrease":        -0.3,   # < -0.3 pp = decreasing
    "strong_decrease": -1.5,   # < -1.5 pp = strong decrease
}


# ─────────────────────────────────────────────────────────────
# DATA FETCHER: screener.in
# ─────────────────────────────────────────────────────────────

def _clean_symbol_for_screener(symbol: str) -> str:
    """Convert TCS.NS → TCS, HDFCBANK.NS → HDFCBANK"""
    return symbol.replace(".NS", "").replace(".BO", "").replace(".BSE", "").upper()


def fetch_quarterly_holdings_from_screener(symbol: str) -> Optional[List[QuarterlyHolding]]:
    """
    Scrape the shareholding pattern table from screener.in.
    Returns a list of QuarterlyHolding ordered oldest-first, or None on failure.
    
    screener.in URL: https://www.screener.in/company/{SYMBOL}/
    The shareholding section has a table with quarterly FII/DII data.
    """
    clean_sym = _clean_symbol_for_screener(symbol)
    url = f"https://www.screener.in/company/{clean_sym}/"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return None

        html = resp.text

        # Find the shareholding section
        # screener.in uses a section with id="shareholding" or similar
        # The table has headers like: Quarter | Promoters | FII | DII | Public | Others
        
        # Use regex to find the shareholding table rows
        # Pattern: find table rows with percentage values
        # screener.in table format (approximate HTML):
        # <tr><td>Sep 2024</td><td>72.38</td><td>12.54</td><td>5.21</td><td>9.87</td></tr>
        
        # Find the shareholding section block
        sh_section_match = re.search(
            r'Shareholding Pattern.*?(<table.*?</table>)',
            html, re.DOTALL | re.IGNORECASE
        )
        
        if not sh_section_match:
            # Try alternative: look for the table directly by structure
            sh_section_match = re.search(
                r'(Promoter|Promoters).*?(<table[^>]*>.*?</table>)',
                html, re.DOTALL | re.IGNORECASE
            )

        if not sh_section_match:
            return None

        table_html = sh_section_match.group(1) if sh_section_match.lastindex >= 1 else ""
        
        # Parse using pandas read_html if table_html found
        try:
            tables = pd.read_html(f"<table>{table_html}</table>" if "<table>" not in table_html else table_html)
            if not tables:
                return None
            df = tables[0]
        except Exception:
            return None

        # Identify columns: Quarter, Promoters, FII, DII, Public
        # Column names vary — normalize
        col_map = {}
        for col in df.columns:
            col_lower = str(col).lower()
            if any(x in col_lower for x in ["quarter", "date", "period", "month"]):
                col_map["quarter"] = col
            elif "fii" in col_lower or "foreign" in col_lower:
                col_map["fii"] = col
            elif "dii" in col_lower or "domestic" in col_lower:
                col_map["dii"] = col
            elif "promoter" in col_lower:
                col_map["promoter"] = col
            elif "public" in col_lower:
                col_map["public"] = col

        # Need at least quarter + fii + dii
        if "quarter" not in col_map or "fii" not in col_map or "dii" not in col_map:
            return None

        holdings = []
        for _, row in df.iterrows():
            try:
                quarter = str(row[col_map["quarter"]]).strip()
                fii = float(str(row[col_map["fii"]]).replace("%", "").strip())
                dii = float(str(row[col_map["dii"]]).replace("%", "").strip())
                promoter = None
                public_pct = None
                if "promoter" in col_map:
                    try:
                        promoter = float(str(row[col_map["promoter"]]).replace("%", "").strip())
                    except Exception:
                        pass
                if "public" in col_map:
                    try:
                        public_pct = float(str(row[col_map["public"]]).replace("%", "").strip())
                    except Exception:
                        pass

                if quarter and 0 <= fii <= 100 and 0 <= dii <= 100:
                    holdings.append(QuarterlyHolding(
                        quarter=quarter,
                        fii_pct=round(fii, 2),
                        dii_pct=round(dii, 2),
                        promoter_pct=round(promoter, 2) if promoter is not None else None,
                        public_pct=round(public_pct, 2) if public_pct is not None else None,
                    ))
            except Exception:
                continue

        # Return oldest-first (screener usually shows newest first, so reverse)
        if holdings:
            holdings.reverse()
            return holdings[-8:]  # last 8 quarters max

        return None

    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
# DATA FETCHER: yfinance fallback
# ─────────────────────────────────────────────────────────────

def fetch_current_holdings_from_yfinance(symbol: str) -> Optional[Dict]:
    """
    Fetch current FII/DII from yfinance major_holders.
    Returns dict with fii_pct, dii_pct, or None on failure.
    
    Note: yfinance doesn't have perfect Indian FII/DII separation.
    We use institutional_holders % as FII proxy and estimate DII.
    """
    try:
        ticker = yf.Ticker(symbol)
        
        # major_holders has a small table with key holding percentages
        major = ticker.major_holders
        
        if major is not None and not major.empty:
            # major_holders DataFrame has 2 columns: value and description
            # Row index or description contains "Institution" 
            inst_pct = None
            for idx, row in major.iterrows():
                desc = str(row.iloc[1]).lower() if len(row) > 1 else str(row.iloc[0]).lower()
                val_str = str(row.iloc[0])
                if "institution" in desc:
                    try:
                        inst_pct = float(val_str.replace("%", "").strip())
                    except Exception:
                        pass

            if inst_pct is not None:
                # For Indian stocks: approximate FII = 60% of total institutional
                # DII = 40% of total institutional (rough approximation)
                fii_est = round(inst_pct * 0.60, 2)
                dii_est = round(inst_pct * 0.40, 2)
                return {
                    "fii_pct": fii_est,
                    "dii_pct": dii_est,
                    "source": "yfinance_estimated",
                    "note": "Estimated from total institutional holding. For exact FII/DII use screener.in."
                }

        # Fallback: try info dict
        info = ticker.info
        # yfinance info has 'heldPercentInstitutions' for institutional holders
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


# ─────────────────────────────────────────────────────────────
# TREND CALCULATOR
# ─────────────────────────────────────────────────────────────

def _compute_trend(history: List[QuarterlyHolding], key: str) -> Tuple[str, Optional[float], Optional[float]]:
    """
    Compute trend direction and change values for FII or DII.
    
    Args:
        history: List of QuarterlyHolding (oldest first)
        key: "fii_pct" or "dii_pct"
    
    Returns:
        (trend_label, change_1q, change_4q)
        trend_label: "Increasing" | "Decreasing" | "Stable"
    """
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


# ─────────────────────────────────────────────────────────────
# SCORING ENGINE
# ─────────────────────────────────────────────────────────────

def _compute_level_score(fii_pct: float, dii_pct: float) -> float:
    """
    Score (0-100) based on absolute FII + DII holding levels.
    Higher combined institutional holding = higher score.
    """
    # FII level score (0-50 contribution)
    if fii_pct >= FII_LEVEL_BENCHMARKS["very_high"]:
        fii_level = 50
    elif fii_pct >= FII_LEVEL_BENCHMARKS["high"]:
        fii_level = 38
    elif fii_pct >= FII_LEVEL_BENCHMARKS["moderate"]:
        fii_level = 25
    elif fii_pct >= FII_LEVEL_BENCHMARKS["low"]:
        fii_level = 12
    else:
        fii_level = 5

    # DII level score (0-50 contribution)
    if dii_pct >= DII_LEVEL_BENCHMARKS["very_high"]:
        dii_level = 50
    elif dii_pct >= DII_LEVEL_BENCHMARKS["high"]:
        dii_level = 38
    elif dii_pct >= DII_LEVEL_BENCHMARKS["moderate"]:
        dii_level = 25
    elif dii_pct >= DII_LEVEL_BENCHMARKS["low"]:
        dii_level = 12
    else:
        dii_level = 5

    return float(fii_level + dii_level)


def _compute_trend_score(
    fii_trend: str,
    dii_trend: str,
    fii_change_1q: Optional[float],
    dii_change_1q: Optional[float],
) -> float:
    """
    Score (0-100) based on trend direction.
    Both increasing = high score. Both decreasing = low score.
    """
    TREND_SCORES = {
        "Strongly Increasing": 90,
        "Increasing":          70,
        "Stable":              50,
        "Decreasing":          30,
        "Strongly Decreasing": 10,
    }

    fii_score = TREND_SCORES.get(fii_trend, 50)
    dii_score = TREND_SCORES.get(dii_trend, 50)

    # FII trend weighted slightly more (foreign money flows are stronger signal)
    combined = fii_score * 0.55 + dii_score * 0.45
    return round(combined, 2)


def _compute_institutional_sentiment_score(
    fii_pct: float,
    dii_pct: float,
    fii_trend: str,
    dii_trend: str,
    fii_change_1q: Optional[float],
    dii_change_1q: Optional[float],
) -> float:
    """
    Final institutional sentiment score (0-100).
    Formula: (level_score * 0.40) + (trend_score * 0.60)
    Trend is weighted more because trend direction matters more than absolute level.
    """
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


# ─────────────────────────────────────────────────────────────
# RECOMMENDATION ENGINE
# ─────────────────────────────────────────────────────────────

def _generate_recommendation(
    score: float,
    fii_pct: float,
    dii_pct: float,
    fii_trend: str,
    dii_trend: str,
    fii_change_1q: Optional[float],
    dii_change_1q: Optional[float],
    fii_change_4q: Optional[float],
    dii_change_4q: Optional[float],
) -> Tuple[str, str, List[str]]:
    """
    Generate a plain-English recommendation with reasoning bullets.
    Returns (recommendation_label, color, reasoning_bullets).
    """
    reasoning = []

    # Build reasoning bullets
    total_inst = round(fii_pct + dii_pct, 2)
    reasoning.append(
        f"Total institutional holding is {total_inst:.2f}% "
        f"(FII: {fii_pct:.2f}% + DII: {dii_pct:.2f}%)"
    )

    # FII trend reasoning
    if "Increasing" in fii_trend and fii_change_1q:
        reasoning.append(
            f"FII holding has {fii_trend.lower()} by {fii_change_1q:+.2f}pp this quarter — "
            f"foreign investors are actively buying"
        )
    elif "Decreasing" in fii_trend and fii_change_1q:
        reasoning.append(
            f"FII holding has {fii_trend.lower()} by {fii_change_1q:+.2f}pp this quarter — "
            f"foreign investors are reducing positions"
        )
    else:
        reasoning.append("FII holding is stable — no significant foreign buying or selling")

    # DII trend reasoning
    if "Increasing" in dii_trend and dii_change_1q:
        reasoning.append(
            f"DII holding has {dii_trend.lower()} by {dii_change_1q:+.2f}pp — "
            f"domestic institutions (mutual funds, insurance) are accumulating"
        )
    elif "Decreasing" in dii_trend and dii_change_1q:
        reasoning.append(
            f"DII holding has {dii_trend.lower()} by {dii_change_1q:+.2f}pp — "
            f"domestic funds are trimming holdings"
        )

    # 4-quarter view
    if fii_change_4q is not None:
        if fii_change_4q > 2.0:
            reasoning.append(
                f"Over 4 quarters, FII has increased by {fii_change_4q:+.2f}pp — "
                f"consistent long-term foreign confidence"
            )
        elif fii_change_4q < -2.0:
            reasoning.append(
                f"Over 4 quarters, FII has declined by {fii_change_4q:+.2f}pp — "
                f"sustained foreign selling is a concern"
            )

    # Divergence signal (FII vs DII moving in opposite directions)
    if "Increasing" in fii_trend and "Decreasing" in dii_trend:
        reasoning.append(
            "⚡ Divergence: FII buying while DII selling — "
            "foreign investors more optimistic than domestic funds"
        )
    elif "Decreasing" in fii_trend and "Increasing" in dii_trend:
        reasoning.append(
            "⚡ Divergence: DII buying while FII selling — "
            "domestic funds accumulating as foreign money exits (could be opportunity)"
        )

    # Final recommendation
    if score >= 75:
        rec = "Strong Buy Signal"
        color = "green"
    elif score >= 60:
        rec = "Buy Signal"
        color = "#4caf50"
    elif score >= 40:
        rec = "Neutral — Monitor"
        color = "gray"
    elif score >= 25:
        rec = "Caution — Weak Institutional Interest"
        color = "orange"
    else:
        rec = "Avoid — Institutional Selling"
        color = "red"

    return rec, color, reasoning


# ─────────────────────────────────────────────────────────────
# MAIN PUBLIC FUNCTION
# ─────────────────────────────────────────────────────────────

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
        FIIDIISentiment — complete analysis with score, trend, and recommendation
    """

    # ── Step 1: Fetch quarterly history from screener.in ──
    quarterly_history = fetch_quarterly_holdings_from_screener(symbol)
    data_source = "screener_in"
    data_freshness = "Live"

    # ── Step 2: Get current FII/DII ──
    current_fii = None
    current_dii = None

    if quarterly_history:
        # Use latest quarter from screener as current
        latest_q = quarterly_history[-1]
        current_fii = latest_q.fii_pct
        current_dii = latest_q.dii_pct
    
    # If screener failed or no quarterly data, try cached values
    if current_fii is None and cached_fii is not None:
        current_fii = cached_fii
        current_dii = cached_dii or 0.0
        data_source = "cached"
        data_freshness = "Cached"

    # Last resort: yfinance
    if current_fii is None:
        yf_data = fetch_current_holdings_from_yfinance(symbol)
        if yf_data:
            current_fii = yf_data["fii_pct"]
            current_dii = yf_data["dii_pct"]
            data_source = "yfinance"
            data_freshness = "Estimated"
        else:
            # Complete fallback: use zeros with a neutral score
            current_fii = 0.0
            current_dii = 0.0
            data_source = "unavailable"
            data_freshness = "Unavailable"

    current_fii = current_fii or 0.0
    current_dii = current_dii or 0.0

    # ── Step 3: If no quarterly history, create a single-point history ──
    if not quarterly_history:
        quarterly_history = [
            QuarterlyHolding(
                quarter="Current",
                fii_pct=current_fii,
                dii_pct=current_dii,
            )
        ]

    # ── Step 4: Compute trends ──
    fii_trend, fii_change_1q, fii_change_4q = _compute_trend(quarterly_history, "fii_pct")
    dii_trend, dii_change_1q, dii_change_4q = _compute_trend(quarterly_history, "dii_pct")

    # ── Step 5: Score ──
    score = _compute_institutional_sentiment_score(
        fii_pct=current_fii,
        dii_pct=current_dii,
        fii_trend=fii_trend,
        dii_trend=dii_trend,
        fii_change_1q=fii_change_1q,
        dii_change_1q=dii_change_1q,
    )
    sentiment_label = _get_sentiment_label(score)

    # ── Step 6: Recommendation ──
    recommendation, rec_color, reasoning = _generate_recommendation(
        score=score,
        fii_pct=current_fii,
        dii_pct=current_dii,
        fii_trend=fii_trend,
        dii_trend=dii_trend,
        fii_change_1q=fii_change_1q,
        dii_change_1q=dii_change_1q,
        fii_change_4q=fii_change_4q,
        dii_change_4q=dii_change_4q,
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
        dii_change_1q=dii_change_1q,
        fii_change_4q=fii_change_4q,
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
```

---

### STEP 3 — Update `agent1.py` (Add New Tool)

Find the section with `@agent.tool` definitions. Add this tool — do NOT touch existing tools:

```python
# Add to agent1.py — at the top imports section:
from utils.fii_dii_analyzer import get_fii_dii_sentiment as _get_fii_dii_data

# Add this new tool alongside existing tools:

@agent.tool
async def get_fii_dii_sentiment(
    ctx: RunContext[AgentDeps],
    symbol: str,
) -> ToolResponse:
    """
    Get FII (Foreign Institutional Investor) and DII (Domestic Institutional Investor)
    sentiment analysis for a stock.

    Use this tool when the user asks:
    - What is FII or DII holding for [stock]?
    - Is FII buying or selling [stock]?
    - What is institutional sentiment for [stock]?
    - Are foreign investors buying [stock]?
    - Should I buy [stock] based on institutional activity?
    - What is the institutional holding trend?

    Args:
        symbol: NSE/BSE ticker (e.g., "TCS.NS", "RELIANCE.NS")
    """
    try:
        # Pull cached FII/DII from existing company_data if available
        cached_fii = None
        cached_dii = None
        company_name = None

        if hasattr(ctx.deps, 'company_data') and ctx.deps.company_data:
            cd = ctx.deps.company_data
            try:
                # CompanyData.market_data.holdings has FII and DII
                holdings = cd.market_data.holdings if hasattr(cd.market_data, 'holdings') else None
                if holdings:
                    cached_fii = getattr(holdings, 'fii', None) or getattr(holdings, 'FII', None)
                    cached_dii = getattr(holdings, 'dii', None) or getattr(holdings, 'DII', None)
                company_name = cd.name or (cd.snapshot.company_name if cd.snapshot else None)
            except Exception:
                pass

        result = _get_fii_dii_data(
            symbol=symbol,
            company_name=company_name,
            cached_fii=float(cached_fii) if cached_fii else None,
            cached_dii=float(cached_dii) if cached_dii else None,
        )

        # Format trend arrow
        def trend_arrow(trend: str) -> str:
            if "Strongly Increasing" in trend:  return "⬆⬆ Strongly Increasing"
            if "Increasing" in trend:           return "⬆ Increasing"
            if "Decreasing" in trend:           return "⬇ Decreasing"  
            if "Strongly Decreasing" in trend:  return "⬇⬇ Strongly Decreasing"
            return "➡ Stable"

        def change_str(change: float | None) -> str:
            if change is None: return "N/A"
            sign = "+" if change >= 0 else ""
            return f"{sign}{change:.2f}pp"

        response_text = f"""
## 🏦 FII/DII Institutional Sentiment: {symbol}

### 🎯 Recommendation: {result.recommendation}
**Institutional Sentiment Score**: {result.institutional_sentiment_score:.1f}/100 — {result.sentiment_label}

### 📊 Current Holdings
| Type | Holding | Trend (1Q) | Change (1Q) | Change (4Q) |
|------|---------|------------|-------------|-------------|
| 🌍 FII | {result.current_fii_pct:.2f}% | {trend_arrow(result.fii_trend)} | {change_str(result.fii_change_1q)} | {change_str(result.fii_change_4q)} |
| 🏠 DII | {result.current_dii_pct:.2f}% | {trend_arrow(result.dii_trend)} | {change_str(result.dii_change_1q)} | {change_str(result.dii_change_4q)} |
| 📦 Total Inst. | {result.current_total_institutional:.2f}% | — | — | — |

### 📈 Quarterly History
{chr(10).join(f"• {h.quarter}: FII {h.fii_pct:.2f}% | DII {h.dii_pct:.2f}%" for h in result.quarterly_history[-6:])}

### 🔍 Analysis
{chr(10).join(f"• {r}" for r in result.reasoning)}

### 💡 What This Means
- **FII (Foreign Institutional Investors)** = Foreign funds, FPIs, hedge funds investing from abroad
- **DII (Domestic Institutional Investors)** = Indian mutual funds, insurance companies, banks
- Rising FII + DII = Strong institutional buying → Bullish signal
- Falling FII + DII = Institutional distribution → Bearish signal

*Data source: {result.data_source} | Freshness: {result.data_freshness}*
"""
        return create_tool_response(response_text.strip(), "get_fii_dii_sentiment")

    except Exception as e:
        return create_tool_response(
            f"Could not fetch FII/DII data for {symbol}: {str(e)}. "
            f"Try checking screener.in manually for shareholding pattern.",
            "get_fii_dii_sentiment"
        )
```

---

### STEP 4 — Update `app_advanced.py` (Add to Sentiment Tab)

Locate the existing **Sentiment tab** section in `app_advanced.py`. At the **bottom** of that tab (after all existing sentiment content), add the FII/DII section. Do NOT change anything above it.

```python
# In app_advanced.py — inside the existing Sentiment tab, at the BOTTOM

# Add import at top of app_advanced.py:
from utils.fii_dii_analyzer import get_fii_dii_sentiment as compute_fii_dii
import plotly.graph_objects as go  # likely already imported

# ── FII/DII SECTION (add at bottom of Sentiment tab) ──────────────────

st.divider()
st.subheader("🏦 FII & DII Institutional Sentiment")
st.caption("Track Foreign & Domestic Institutional buying/selling activity")

# Symbol: auto-use current stock if loaded, else let user type
fii_symbol = None
if st.session_state.get("company_data"):
    fii_symbol = st.session_state.company_data.symbol
    st.info(f"📌 Analyzing institutional sentiment for: **{fii_symbol}**")
else:
    fii_symbol = st.text_input(
        "Enter symbol for FII/DII analysis",
        placeholder="TCS.NS, RELIANCE.NS...",
        key="fii_dii_symbol_input"
    )

run_fii = st.button("📊 Fetch FII/DII Data", key="run_fii_dii", type="primary")

# Auto-run if company_data is already loaded (seamless UX)
auto_run = (
    st.session_state.get("company_data") is not None
    and f"fii_dii_{fii_symbol}" not in st.session_state
)

if (run_fii or auto_run) and fii_symbol:
    # Pull cached holdings from existing company_data to skip re-fetch
    cached_fii_val = None
    cached_dii_val = None
    company_name_val = None

    if st.session_state.get("company_data"):
        cd = st.session_state.company_data
        try:
            holdings = cd.market_data.holdings
            cached_fii_val = getattr(holdings, 'fii', None) or getattr(holdings, 'FII', None)
            cached_dii_val = getattr(holdings, 'dii', None) or getattr(holdings, 'DII', None)
            company_name_val = cd.name
        except Exception:
            pass

    with st.spinner("Fetching FII/DII shareholding pattern..."):
        fii_result = compute_fii_dii(
            symbol=fii_symbol,
            company_name=company_name_val,
            cached_fii=float(cached_fii_val) if cached_fii_val else None,
            cached_dii=float(cached_dii_val) if cached_dii_val else None,
        )
    
    # Cache result in session
    st.session_state[f"fii_dii_{fii_symbol}"] = fii_result

# Display cached result if available
fii_result = st.session_state.get(f"fii_dii_{fii_symbol}")

if fii_result:
    # ── RECOMMENDATION BANNER ──
    rec_colors = {
        "green":  ("#e8f5e9", "#2e7d32"),
        "#4caf50": ("#f1f8e9", "#33691e"),
        "gray":   ("#f5f5f5", "#424242"),
        "orange": ("#fff3e0", "#e65100"),
        "red":    ("#ffebee", "#c62828"),
    }
    bg, fg = rec_colors.get(fii_result.recommendation_color, ("#f5f5f5", "#424242"))

    st.markdown(
        f"<div style='background:{bg}; border-left:5px solid {fg}; "
        f"padding:14px 18px; border-radius:6px; margin:12px 0;'>"
        f"<div style='font-size:1.2em; font-weight:700; color:{fg};'>"
        f"🎯 {fii_result.recommendation}</div>"
        f"<div style='color:{fg}; margin-top:4px;'>"
        f"Institutional Score: {fii_result.institutional_sentiment_score:.1f}/100 "
        f"— {fii_result.sentiment_label}</div>"
        f"</div>",
        unsafe_allow_html=True
    )

    # ── METRIC CARDS ──
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        fii_delta = f"{fii_result.fii_change_1q:+.2f}pp" if fii_result.fii_change_1q is not None else None
        st.metric(
            "🌍 FII Holding",
            f"{fii_result.current_fii_pct:.2f}%",
            delta=fii_delta,
            delta_color="normal"
        )
    with m2:
        dii_delta = f"{fii_result.dii_change_1q:+.2f}pp" if fii_result.dii_change_1q is not None else None
        st.metric(
            "🏠 DII Holding",
            f"{fii_result.current_dii_pct:.2f}%",
            delta=dii_delta,
            delta_color="normal"
        )
    with m3:
        st.metric(
            "📦 Total Institutional",
            f"{fii_result.current_total_institutional:.2f}%"
        )
    with m4:
        st.metric(
            "📈 Inst. Score",
            f"{fii_result.institutional_sentiment_score:.1f}/100"
        )

    # ── TREND LABELS ──
    t1, t2 = st.columns(2)
    def trend_badge(trend: str) -> str:
        colors = {
            "Strongly Increasing": ("⬆⬆", "green"),
            "Increasing":          ("⬆",  "#4caf50"),
            "Stable":              ("➡",  "gray"),
            "Decreasing":          ("⬇",  "orange"),
            "Strongly Decreasing": ("⬇⬇", "red"),
        }
        arrow, color = colors.get(trend, ("➡", "gray"))
        return f"<span style='color:{color}; font-weight:600;'>{arrow} {trend}</span>"

    with t1:
        st.markdown(f"**FII Trend:** {trend_badge(fii_result.fii_trend)}", unsafe_allow_html=True)
        if fii_result.fii_change_4q is not None:
            st.caption(f"4-quarter FII change: {fii_result.fii_change_4q:+.2f}pp")
    with t2:
        st.markdown(f"**DII Trend:** {trend_badge(fii_result.dii_trend)}", unsafe_allow_html=True)
        if fii_result.dii_change_4q is not None:
            st.caption(f"4-quarter DII change: {fii_result.dii_change_4q:+.2f}pp")

    # ── QUARTERLY TREND CHART ──
    if len(fii_result.quarterly_history) >= 2:
        st.subheader("📉 Quarterly Shareholding Trend")

        quarters = [h.quarter for h in fii_result.quarterly_history]
        fii_vals = [h.fii_pct for h in fii_result.quarterly_history]
        dii_vals = [h.dii_pct for h in fii_result.quarterly_history]
        total_vals = [round(f + d, 2) for f, d in zip(fii_vals, dii_vals)]

        fig = go.Figure()

        # FII line
        fig.add_trace(go.Scatter(
            x=quarters, y=fii_vals,
            mode="lines+markers",
            name="FII %",
            line=dict(color="#1976d2", width=2.5),
            marker=dict(size=7),
            hovertemplate="Quarter: %{x}<br>FII: %{y:.2f}%<extra></extra>"
        ))

        # DII line
        fig.add_trace(go.Scatter(
            x=quarters, y=dii_vals,
            mode="lines+markers",
            name="DII %",
            line=dict(color="#388e3c", width=2.5),
            marker=dict(size=7),
            hovertemplate="Quarter: %{x}<br>DII: %{y:.2f}%<extra></extra>"
        ))

        # Total institutional (dashed)
        fig.add_trace(go.Scatter(
            x=quarters, y=total_vals,
            mode="lines",
            name="Total Inst. %",
            line=dict(color="#f57c00", width=2, dash="dot"),
            hovertemplate="Quarter: %{x}<br>Total: %{y:.2f}%<extra></extra>"
        ))

        fig.update_layout(
            xaxis_title="Quarter",
            yaxis_title="Holding (%)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            height=320,
            margin=dict(t=20, b=20, l=10, r=10),
            hovermode="x unified",
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        fig.update_yaxes(gridcolor="rgba(128,128,128,0.15)")

        st.plotly_chart(fig, use_container_width=True)

    # ── ANALYSIS REASONING ──
    st.subheader("🔍 Analysis")
    for reason in fii_result.reasoning:
        if "⚡" in reason:
            st.warning(reason)
        else:
            st.info(f"• {reason}")

    # ── WHAT IS FII/DII EXPLAINER ──
    with st.expander("ℹ️ What is FII & DII? How to read this?"):
        st.markdown("""
**FII — Foreign Institutional Investors**
Foreign funds, hedge funds, FPIs (Foreign Portfolio Investors) investing in Indian markets from abroad.
Rising FII % means foreign money is flowing INTO this stock — strong confidence signal.

**DII — Domestic Institutional Investors**
Indian mutual funds, insurance companies (LIC), pension funds, and banks.
Rising DII % means domestic institutions are accumulating — seen as a "smart money" signal.

**How to read the trend:**
| Situation | What It Means |
|-----------|--------------|
| FII ⬆ + DII ⬆ | Both buying → Strong bullish signal |
| FII ⬆ + DII ⬇ | Foreign buying, domestic selling → Moderate bullish |
| FII ⬇ + DII ⬆ | Domestic buying on FII exit → Could be contrarian opportunity |
| FII ⬇ + DII ⬇ | Both selling → Strong bearish signal, avoid |

**Scoring:**
- Score 75–100: Very Bullish → Strong Buy Signal
- Score 60–74: Bullish → Buy Signal
- Score 40–59: Neutral → Monitor and wait
- Score 25–39: Bearish → Caution
- Score 0–24: Very Bearish → Avoid

*Note: FII/DII data updates quarterly. Source: screener.in shareholding pattern.*
        """)

    # ── DATA FRESHNESS NOTE ──
    st.caption(
        f"📡 Data source: {fii_result.data_source.replace('_', '.')} | "
        f"Freshness: {fii_result.data_freshness} | "
        f"Last analyzed: {fii_result.timestamp.strftime('%d %b %Y %H:%M UTC')}"
    )
```

---

## ✅ Implementation Checklist for Claude Code

### New Files to Create
- [ ] `utils/fii_dii_analyzer.py` — complete file as specified above

### Existing Files to Update (additive only, do NOT break existing code)
- [ ] `models.py` — add `QuarterlyHolding` and `FIIDIISentiment` Pydantic models
- [ ] `agent1.py` — add `get_fii_dii_sentiment` tool (import + tool function)
- [ ] `app_advanced.py` — add FII/DII section at the bottom of the existing Sentiment tab

### No new dependencies needed
All libraries used (`requests`, `pandas`, `yfinance`, `plotly`, `re`) are already in `requirements.txt`.

---

## ⚠️ Critical Rules for Claude Code

1. **Do NOT touch any existing sentiment code** — the FII/DII section is appended BELOW all existing sentiment content inside the Sentiment tab. Do not reorganize or wrap existing code.

2. **Do NOT add a new tab** — this feature goes INSIDE the existing Sentiment tab, not as a new tab.

3. **The `get_fii_dii_sentiment` tool name must match exactly** — including the import alias (`_get_fii_dii_data` internally), and the tool function decorated with `@agent.tool`.

4. **`CompanyData.market_data.holdings` field access** — inspect the actual `models.py` field names for FII/DII in the `MarketData` and holdings sub-model before writing the access code in `agent1.py` and `app_advanced.py`. The README shows `Holdings: promoter, FII, DII` but the actual field names might be lowercase (`fii`, `dii`) — check and match exactly.

5. **screener.in HTML structure may vary** — the scraper uses regex + `pd.read_html`. If screener.in's HTML changes, the fallback to yfinance must still work silently. Every step of `get_fii_dii_sentiment()` is wrapped in try/except and returns valid data even on total failure.

6. **Session state key for caching** — use `f"fii_dii_{symbol}"` as the session state key, consistent with the naming convention used for `trade_ideas_{SYMBOL}` in the existing code.

7. **Auto-run behavior** — the FII/DII section auto-runs when the Sentiment tab is opened and a stock is already loaded (via `company_data` in session state), but only if no cached result exists yet. This avoids redundant fetches on tab switching.

8. **Indian market context** — FII/DII percentages are expressed as % of total shares outstanding. The benchmarks in `FII_LEVEL_BENCHMARKS` and `DII_LEVEL_BENCHMARKS` are calibrated for the Indian NSE/BSE market where typical FII for a large-cap might be 10–25% and DII 5–15%.

---

## 📐 Data Flow Summary

```
Sentiment Tab Opens
      │
      ▼
company_data already loaded?
      ├── YES → auto-extract cached FII/DII from market_data.holdings
      │           ↓
      │     call get_fii_dii_sentiment(symbol, cached_fii, cached_dii)
      │
      └── NO → user types symbol → clicks "Fetch FII/DII Data"
                    ↓
              call get_fii_dii_sentiment(symbol)

Inside get_fii_dii_sentiment():
      │
      ├── Try screener.in quarterly table scrape
      │       → parse HTML table (Quarter | FII% | DII%)
      │       → returns last 8 quarters of history
      │
      ├── Fallback: use cached_fii / cached_dii from CompanyData
      │
      └── Last resort: yfinance institutional_holders estimate
                    │
                    ▼
            Compute trends (1Q change, 4Q change)
                    │
                    ▼
            Score = (level_score × 0.40) + (trend_score × 0.60)
                    │
                    ▼
            Recommendation + Reasoning bullets
                    │
                    ▼
            Return FIIDIISentiment
                    │
                    ▼
            Display in Sentiment tab:
            • Recommendation banner
            • 4 metric cards (FII%, DII%, Total, Score)
            • Trend badges with arrows
            • Plotly line chart (FII + DII + Total over quarters)
            • Analysis reasoning bullets
            • Explainer expander
```
