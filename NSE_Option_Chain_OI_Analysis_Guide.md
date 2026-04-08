# TradingWize — NSE Option Chain & OI Analysis Feature
### Implementation Guide for Claude Code

---

## 📌 What This Task Is

Add a brand-new **"📊 Option Chain"** tab to TradingWize that:

1. Fetches live option chain data from the **official NSE India API** for any stock or index
2. Extracts only the 5 required columns: `Call OI`, `Call Chng in OI`, `Strike Price`, `Put OI`, `Put Chng in OI`
3. Performs **OI-based market direction analysis** using:
   - Max Pain Strike detection
   - Put/Call OI Ratio (PCR)
   - OI Shift tracking (where is highest OI concentration moving?)
   - Support & Resistance levels from OI walls
4. Generates a plain-English **Buy / Neutral / Avoid recommendation** with reasoning
5. Displays a clean interactive table + Plotly OI bar chart
6. Adds a `get_option_chain_analysis` agent tool for the chat interface

---

## 🌐 NSE Data Source — How to Fetch

NSE India provides a **free public JSON API** for option chain data. No API key required. The trick is that NSE's website requires proper browser-like headers and a session cookie — without these, the request gets blocked with a 403 error.

### NSE Option Chain API Endpoints

**For Indices (NIFTY, BANKNIFTY, FINNIFTY):**
```
https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY
https://www.nseindia.com/api/option-chain-indices?symbol=BANKNIFTY
https://www.nseindia.com/api/option-chain-indices?symbol=FINNIFTY
```

**For Individual Stocks (RELIANCE, TCS, INFY, etc.):**
```
https://www.nseindia.com/api/option-chain-equities?symbol=RELIANCE
https://www.nseindia.com/api/option-chain-equities?symbol=TCS
```

### Why Direct `requests.get()` Fails — And How to Fix It

NSE blocks simple HTTP requests. The solution is a **two-step session approach**:

**Step 1:** First visit the NSE homepage to get a valid session cookie
```
GET https://www.nseindia.com/
```

**Step 2:** Use that same session (with cookies) to hit the API
```
GET https://www.nseindia.com/api/option-chain-equities?symbol=RELIANCE
```

This must be done using `requests.Session()` so cookies persist between the two calls.

### Required Headers (MUST use all of these)
```python
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/option-chain",
    "X-Requested-With": "XMLHttpRequest",
    "Connection": "keep-alive",
}
```

### NSE API JSON Response Structure

The JSON response has this structure:
```json
{
  "records": {
    "underlyingValue": 24500.50,
    "expiryDates": ["27-Mar-2025", "03-Apr-2025", "10-Apr-2025"],
    "data": [
      {
        "strikePrice": 24000,
        "expiryDate": "27-Mar-2025",
        "CE": {
          "openInterest": 12500,
          "changeinOpenInterest": 1200,
          "totalTradedVolume": 45000,
          "impliedVolatility": 14.5,
          "lastPrice": 520.0,
          "change": 15.5,
          "pChange": 3.07
        },
        "PE": {
          "openInterest": 8500,
          "changeinOpenInterest": -400,
          "totalTradedVolume": 22000,
          "impliedVolatility": 13.8,
          "lastPrice": 45.0,
          "change": -5.0,
          "pChange": -10.0
        }
      }
    ]
  }
}
```

**Field mapping** (NSE JSON → our column names):
| NSE JSON field | Our column name |
|----------------|----------------|
| `CE.openInterest` | `call_oi` |
| `CE.changeinOpenInterest` | `call_chng_oi` |
| `strikePrice` | `strike` |
| `PE.openInterest` | `put_oi` |
| `PE.changeinOpenInterest` | `put_chng_oi` |

### Symbol Handling for NSE
- Indices: use exact symbols `NIFTY`, `BANKNIFTY`, `FINNIFTY` — no `.NS` suffix
- Stocks: strip `.NS` or `.BO` → `RELIANCE.NS` becomes `RELIANCE`
- NSE only has option chains for F&O eligible stocks (about 200+ stocks)
- If a stock is not F&O eligible, the API returns an error — handle gracefully

---

## 🏗️ Implementation Plan

### New Files to Create
```
utils/
└── option_chain_analyzer.py    ← All NSE fetching + OI analysis logic
```

### Existing Files to Update (additive only)
```
app_advanced.py     ← Add new "📊 Option Chain" tab
agent1.py           ← Add get_option_chain_analysis tool
models.py           ← Add OptionChainData + OIAnalysis Pydantic models
```

### No new dependencies needed
All required libraries (`requests`, `pandas`, `plotly`, `re`) are already in `requirements.txt`.

---

## 📋 Detailed Implementation

---

### STEP 1 — Add Pydantic Models to `models.py`

Add these new models to the existing `models.py`. Do NOT change any existing models.

```python
# Add to models.py

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class OptionStrike(BaseModel):
    """Single strike row from the option chain table."""
    strike: float
    call_oi: int = 0
    call_chng_oi: int = 0
    put_oi: int = 0
    put_chng_oi: int = 0
    # Derived flags (set during analysis)
    is_max_call_oi: bool = False      # highest call OI strike
    is_max_put_oi: bool = False       # highest put OI strike
    is_atm: bool = False              # closest to current market price
    call_oi_change_pct: Optional[float] = None   # % change in call OI
    put_oi_change_pct: Optional[float] = None    # % change in put OI


class OIShiftSignal(BaseModel):
    """Tracks where OI concentration is shifting."""
    direction: str              # "UP" | "DOWN" | "SIDEWAYS"
    description: str            # plain English explanation
    strength: str               # "Strong" | "Moderate" | "Weak"


class OIAnalysis(BaseModel):
    """
    Complete OI-based market analysis output.
    All the intelligence derived from the raw option chain data.
    """
    symbol: str
    expiry_date: str
    underlying_price: float

    # Key levels
    max_call_oi_strike: float       # strongest resistance (Call OI wall)
    max_put_oi_strike: float        # strongest support (Put OI wall)
    max_pain_strike: float          # strike where max option buyers lose

    # Ratios
    put_call_ratio: float           # Total Put OI / Total Call OI
    pcr_label: str                  # "Bearish" | "Neutral" | "Bullish"

    # OI shift signals
    call_oi_shift: OIShiftSignal    # where call OI is concentrating
    put_oi_shift: OIShiftSignal     # where put OI is concentrating

    # Support / Resistance
    key_support: float              # strike with highest Put OI (floor)
    key_resistance: float           # strike with highest Call OI (ceiling)
    range_low: float                # expected range lower bound
    range_high: float               # expected range upper bound

    # Final verdict
    market_bias: str                # "Bullish" | "Bearish" | "Range-bound"
    bias_strength: str              # "Strong" | "Moderate" | "Weak"
    recommendation: str             # "Buy / Go Long" | "Sell / Go Short" | "Wait / Neutral" | "Range Trade"
    recommendation_color: str       # "green" | "red" | "gray" | "orange"
    verdict_points: List[str]       # bullet points (the full reasoning)
    confidence: str                 # "High" | "Medium" | "Low"

    timestamp: datetime = Field(default_factory=datetime.utcnow)


class OptionChainData(BaseModel):
    """Complete option chain fetch result — raw data + analysis."""
    symbol: str
    expiry_date: str
    underlying_price: float
    available_expiries: List[str]
    strikes: List[OptionStrike]     # filtered strikes around ATM (±20 strikes)
    analysis: OIAnalysis
    data_source: str = "nse_api"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
```

---

### STEP 2 — Create `utils/option_chain_analyzer.py`

This is the core new file. It handles NSE API fetching, data parsing, and all OI analysis logic.

```python
# utils/option_chain_analyzer.py

"""
NSE Option Chain Fetcher & OI Analyzer for TradingWize

Data source: NSE India public API (no API key required)
  - Indices: https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY
  - Stocks:  https://www.nseindia.com/api/option-chain-equities?symbol=RELIANCE

Requires two-step session approach to bypass NSE's bot protection:
  Step 1: GET https://www.nseindia.com/ to get session cookies
  Step 2: Use same session to GET the API endpoint

OI Analysis Logic:
  1. Max Pain: strike where total option premium decay is maximized
  2. PCR (Put-Call Ratio): Put OI / Call OI
     - PCR > 1.2 = Bullish (more Put writers = market expects upside)
     - PCR < 0.8 = Bearish (more Call writers = market expects downside)
     - PCR 0.8–1.2 = Neutral
  3. OI Walls: strike with highest Call OI = resistance, highest Put OI = support
  4. OI Shift: if top OI strikes are moving upward over time = bullish
  5. Change in OI: positive Chng OI = new positions being written
"""

import time
import requests
import pandas as pd
from typing import Optional, List, Dict, Tuple
from datetime import datetime

from models import OptionChainData, OptionStrike, OIAnalysis, OIShiftSignal


# ─────────────────────────────────────────────────────────────
# NSE SESSION MANAGER
# ─────────────────────────────────────────────────────────────

NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/option-chain",
    "X-Requested-With": "XMLHttpRequest",
    "Connection": "keep-alive",
    "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

NSE_BASE = "https://www.nseindia.com"
NSE_INDICES_API = f"{NSE_BASE}/api/option-chain-indices"
NSE_EQUITIES_API = f"{NSE_BASE}/api/option-chain-equities"

# Indices that use the indices endpoint (not equities)
NSE_INDICES = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"}


def _clean_symbol_for_nse(symbol: str) -> str:
    """
    Convert yfinance symbol to NSE-compatible symbol.
    TCS.NS → TCS
    RELIANCE.NS → RELIANCE
    NIFTY50 → NIFTY
    ^NSEI → NIFTY
    """
    s = symbol.upper().replace(".NS", "").replace(".BO", "").replace("^", "")
    # Common aliases
    aliases = {
        "NSEI": "NIFTY",
        "NIFTY50": "NIFTY",
        "NIFTY 50": "NIFTY",
        "BANKNIFTY": "BANKNIFTY",
        "NIFTYBANK": "BANKNIFTY",
    }
    return aliases.get(s, s)


def _create_nse_session() -> requests.Session:
    """
    Create a requests.Session with NSE cookies.
    MUST visit the homepage first to get valid cookies.
    Returns an active session or raises on failure.
    """
    session = requests.Session()
    session.headers.update(NSE_HEADERS)

    # Step 1: Hit homepage to get cookies
    try:
        resp = session.get(NSE_BASE, timeout=10)
        resp.raise_for_status()
        time.sleep(0.5)  # small delay to appear human
    except Exception as e:
        raise ConnectionError(f"Failed to establish NSE session: {e}")

    return session


def fetch_nse_option_chain(symbol: str, expiry_index: int = 0) -> Dict:
    """
    Fetch raw option chain JSON from NSE API.

    Args:
        symbol: NSE symbol (e.g., "RELIANCE", "NIFTY", "TCS")
        expiry_index: 0 = nearest expiry, 1 = next, etc.

    Returns:
        Raw JSON dict from NSE API

    Raises:
        ValueError: If symbol not found or not F&O eligible
        ConnectionError: If NSE is unreachable
    """
    nse_sym = _clean_symbol_for_nse(symbol)
    is_index = nse_sym in NSE_INDICES

    url = NSE_INDICES_API if is_index else NSE_EQUITIES_API
    params = {"symbol": nse_sym}

    session = _create_nse_session()

    try:
        resp = session.get(url, params=params, timeout=15)

        if resp.status_code == 404:
            raise ValueError(
                f"Symbol '{nse_sym}' not found on NSE option chain. "
                f"The stock may not be F&O eligible."
            )
        if resp.status_code == 403:
            raise ConnectionError(
                "NSE blocked the request (403). Try again in a few seconds."
            )
        resp.raise_for_status()

        data = resp.json()
        return data

    except requests.exceptions.Timeout:
        raise ConnectionError("NSE API timed out. Try again.")
    except requests.exceptions.JSONDecodeError:
        raise ValueError("NSE returned invalid data. Market may be closed.")
    finally:
        session.close()


# ─────────────────────────────────────────────────────────────
# DATA PARSER
# ─────────────────────────────────────────────────────────────

def parse_option_chain(raw_data: Dict, expiry_index: int = 0) -> Tuple[
    float, str, List[str], pd.DataFrame
]:
    """
    Parse NSE raw JSON into a clean DataFrame with only the 5 required columns.

    Returns:
        (underlying_price, selected_expiry, all_expiries, dataframe)

    DataFrame columns: strike, call_oi, call_chng_oi, put_oi, put_chng_oi
    """
    records = raw_data.get("records", {})

    underlying_price = float(records.get("underlyingValue", 0))
    expiry_dates = records.get("expiryDates", [])

    if not expiry_dates:
        raise ValueError("No expiry dates found in option chain data.")

    # Clamp expiry_index to valid range
    expiry_index = max(0, min(expiry_index, len(expiry_dates) - 1))
    selected_expiry = expiry_dates[expiry_index]

    raw_strikes = records.get("data", [])

    rows = []
    for item in raw_strikes:
        if item.get("expiryDate") != selected_expiry:
            continue

        strike = float(item.get("strikePrice", 0))
        ce = item.get("CE", {}) or {}
        pe = item.get("PE", {}) or {}

        call_oi = int(ce.get("openInterest", 0) or 0)
        call_chng_oi = int(ce.get("changeinOpenInterest", 0) or 0)
        put_oi = int(pe.get("openInterest", 0) or 0)
        put_chng_oi = int(pe.get("changeinOpenInterest", 0) or 0)

        rows.append({
            "strike": strike,
            "call_oi": call_oi,
            "call_chng_oi": call_chng_oi,
            "put_oi": put_oi,
            "put_chng_oi": put_chng_oi,
        })

    if not rows:
        raise ValueError(f"No data found for expiry {selected_expiry}.")

    df = pd.DataFrame(rows).sort_values("strike").reset_index(drop=True)
    return underlying_price, selected_expiry, expiry_dates, df


def filter_atm_strikes(df: pd.DataFrame, underlying: float, n_strikes: int = 20) -> pd.DataFrame:
    """
    Keep only ±n_strikes around the ATM (at-the-money) strike.
    This reduces noise and focuses on the most relevant data.
    """
    atm_idx = (df["strike"] - underlying).abs().idxmin()
    low = max(0, atm_idx - n_strikes)
    high = min(len(df) - 1, atm_idx + n_strikes)
    return df.iloc[low:high + 1].reset_index(drop=True)


# ─────────────────────────────────────────────────────────────
# OI ANALYSIS ENGINE
# ─────────────────────────────────────────────────────────────

def _compute_max_pain(df: pd.DataFrame) -> float:
    """
    Max Pain = strike where total value of expiring options is minimized
    (i.e., where option sellers — writers — profit most).

    For each strike K, compute:
      Total Call Pain = sum of (max(0, K - each_call_strike) * call_oi) for all strikes
      Total Put Pain  = sum of (max(0, each_put_strike - K) * put_oi)  for all strikes
      Total Pain at K = Total Call Pain + Total Put Pain

    Max Pain Strike = K with minimum Total Pain
    """
    strikes = df["strike"].values
    call_ois = df["call_oi"].values
    put_ois = df["put_oi"].values
    min_pain = float("inf")
    max_pain_strike = strikes[len(strikes) // 2]  # default to middle

    for k in strikes:
        call_pain = sum(max(0.0, k - s) * c for s, c in zip(strikes, call_ois))
        put_pain = sum(max(0.0, s - k) * p for s, p in zip(strikes, put_ois))
        total = call_pain + put_pain
        if total < min_pain:
            min_pain = total
            max_pain_strike = k

    return float(max_pain_strike)


def _compute_pcr(df: pd.DataFrame) -> Tuple[float, str]:
    """
    Put-Call Ratio = Total Put OI / Total Call OI

    Interpretation for INDIAN MARKET:
    - PCR > 1.5 = Extremely Bullish (heavy put writing = sellers expect upside)
    - PCR 1.2–1.5 = Bullish
    - PCR 0.8–1.2 = Neutral / Range-bound
    - PCR 0.5–0.8 = Bearish (call writing dominates)
    - PCR < 0.5 = Extremely Bearish

    Note: In India, PCR > 1 is considered bullish because put writers (sellers)
    are confident market won't fall — they collect premium by writing puts.
    """
    total_call_oi = df["call_oi"].sum()
    total_put_oi = df["put_oi"].sum()

    if total_call_oi == 0:
        return 1.0, "Neutral"

    pcr = round(total_put_oi / total_call_oi, 3)

    if pcr > 1.5:
        label = "Extremely Bullish"
    elif pcr > 1.2:
        label = "Bullish"
    elif pcr >= 0.8:
        label = "Neutral"
    elif pcr >= 0.5:
        label = "Bearish"
    else:
        label = "Extremely Bearish"

    return pcr, label


def _detect_oi_shift(df: pd.DataFrame, oi_col: str, underlying: float) -> OIShiftSignal:
    """
    Detect where OI is concentrating relative to the underlying price.

    For CALL OI:
    - Top 3 strikes with highest Call OI all ABOVE underlying → bears writing calls far OTM → bullish
    - Top 3 strikes with highest Call OI clustering just ABOVE underlying → strong resistance nearby → bearish/range

    For PUT OI:
    - Top 3 strikes with highest Put OI all BELOW underlying → bulls writing puts far OTM → bullish
    - Top 3 strikes with highest Put OI clustering just BELOW underlying → strong support nearby → bullish

    OI Shift Tracking (the example from the brief):
    - If PUT OI is concentrating at progressively higher strikes → market moving UP
    - If CALL OI is concentrating at progressively lower strikes → market moving DOWN
    """
    is_call = oi_col == "call_oi"

    # Get top 5 strikes by OI
    top5 = df.nlargest(5, oi_col)["strike"].values

    if len(top5) == 0:
        return OIShiftSignal(
            direction="SIDEWAYS",
            description="Insufficient OI data",
            strength="Weak"
        )

    avg_top_strike = sum(top5) / len(top5)
    distance_pct = ((avg_top_strike - underlying) / underlying) * 100

    if is_call:
        # Call OI interpretation
        if distance_pct > 3.0:
            # Calls written far above → market expected to stay below → mildly bullish
            direction = "UP"
            desc = (
                f"Call OI concentrated at {avg_top_strike:,.0f} — "
                f"{abs(distance_pct):.1f}% above current price. "
                f"Call writers don't expect market to reach here — bullish for short term."
            )
            strength = "Moderate" if distance_pct < 6 else "Strong"
        elif distance_pct < -1.0:
            # Calls written below current price → very bearish
            direction = "DOWN"
            desc = (
                f"Call OI concentrated BELOW spot at {avg_top_strike:,.0f} — "
                f"aggressive call writing below spot signals bearish expectation."
            )
            strength = "Strong"
        elif -1.0 <= distance_pct <= 3.0:
            # Calls just above → tight resistance
            direction = "SIDEWAYS"
            desc = (
                f"Call OI wall just {distance_pct:.1f}% above at {avg_top_strike:,.0f} — "
                f"strong resistance nearby, upside likely capped short term."
            )
            strength = "Moderate"
        else:
            direction = "SIDEWAYS"
            desc = f"Call OI distributed around {avg_top_strike:,.0f}. No clear directional bias."
            strength = "Weak"
    else:
        # Put OI interpretation
        if distance_pct < -3.0:
            # Puts written far below → market expected to stay above → bullish
            direction = "UP"
            desc = (
                f"Put OI concentrated at {avg_top_strike:,.0f} — "
                f"{abs(distance_pct):.1f}% below current price. "
                f"Put writers are confident market won't fall here — strong support, bullish."
            )
            strength = "Moderate" if abs(distance_pct) < 6 else "Strong"
        elif distance_pct > 1.0:
            # Puts written above current price → very bearish
            direction = "DOWN"
            desc = (
                f"Put OI concentrated ABOVE spot at {avg_top_strike:,.0f} — "
                f"puts being bought aggressively above current price signals bearish hedge."
            )
            strength = "Strong"
        elif -3.0 <= distance_pct <= 1.0:
            # Puts just below → tight support
            direction = "UP"
            desc = (
                f"Put OI wall just {abs(distance_pct):.1f}% below at {avg_top_strike:,.0f} — "
                f"nearby support zone, downside likely cushioned."
            )
            strength = "Moderate"
        else:
            direction = "SIDEWAYS"
            desc = f"Put OI distributed around {avg_top_strike:,.0f}. No clear directional bias."
            strength = "Weak"

    return OIShiftSignal(direction=direction, description=desc, strength=strength)


def _compute_expected_range(
    max_call_strike: float,
    max_put_strike: float,
    underlying: float
) -> Tuple[float, float]:
    """
    Expected range = between max Put OI (support) and max Call OI (resistance).
    If the underlying is already outside this range, extend the range.
    """
    low = min(max_put_strike, underlying * 0.97)
    high = max(max_call_strike, underlying * 1.03)
    return round(low, 0), round(high, 0)


def _generate_verdict(
    pcr: float,
    pcr_label: str,
    call_shift: OIShiftSignal,
    put_shift: OIShiftSignal,
    max_pain: float,
    underlying: float,
    max_call_oi_strike: float,
    max_put_oi_strike: float,
    df: pd.DataFrame,
) -> Tuple[str, str, str, str, List[str], str]:
    """
    Generate the final market bias, recommendation, and reasoning bullets.

    Returns:
        (market_bias, bias_strength, recommendation, recommendation_color,
         verdict_points, confidence)
    """
    verdict_points = []
    bullish_signals = 0
    bearish_signals = 0

    # ── Signal 1: PCR ──
    verdict_points.append(
        f"📊 Put-Call Ratio (PCR): {pcr:.2f} → {pcr_label}"
    )
    if "Bullish" in pcr_label:
        bullish_signals += 2 if "Extremely" in pcr_label else 1
    elif "Bearish" in pcr_label:
        bearish_signals += 2 if "Extremely" in pcr_label else 1

    # ── Signal 2: OI Walls (Support/Resistance) ──
    distance_to_resistance = ((max_call_oi_strike - underlying) / underlying) * 100
    distance_to_support = ((underlying - max_put_oi_strike) / underlying) * 100

    verdict_points.append(
        f"🧱 Key Resistance (Max Call OI): {max_call_oi_strike:,.0f} "
        f"({distance_to_resistance:+.1f}% from spot)"
    )
    verdict_points.append(
        f"🛡️ Key Support (Max Put OI): {max_put_oi_strike:,.0f} "
        f"({-distance_to_support:+.1f}% from spot)"
    )

    # If market is closer to support than resistance → slightly bullish
    if distance_to_support < distance_to_resistance:
        bullish_signals += 1
        verdict_points.append(
            "📍 Market is closer to Put support than Call resistance → slight bullish lean"
        )
    else:
        bearish_signals += 1
        verdict_points.append(
            "📍 Market is closer to Call resistance than Put support → slight bearish lean"
        )

    # ── Signal 3: Max Pain ──
    pain_diff_pct = ((max_pain - underlying) / underlying) * 100
    verdict_points.append(
        f"⚙️ Max Pain Strike: {max_pain:,.0f} ({pain_diff_pct:+.1f}% from spot)"
    )
    if pain_diff_pct > 1.0:
        bullish_signals += 1
        verdict_points.append(
            f"   → Max Pain above spot: market may get pulled UP toward {max_pain:,.0f} by expiry"
        )
    elif pain_diff_pct < -1.0:
        bearish_signals += 1
        verdict_points.append(
            f"   → Max Pain below spot: market may get pulled DOWN toward {max_pain:,.0f} by expiry"
        )
    else:
        verdict_points.append(
            f"   → Max Pain near spot: market likely to stay rangebound near {max_pain:,.0f}"
        )

    # ── Signal 4: OI Shift (Call side) ──
    verdict_points.append(f"📈 Call OI Shift: {call_shift.description}")
    if call_shift.direction == "UP":
        bullish_signals += 1
    elif call_shift.direction == "DOWN":
        bearish_signals += 1

    # ── Signal 5: OI Shift (Put side) ──
    verdict_points.append(f"📉 Put OI Shift: {put_shift.description}")
    if put_shift.direction == "UP":
        bullish_signals += 1
    elif put_shift.direction == "DOWN":
        bearish_signals += 1

    # ── Signal 6: Change in OI (new positions being built) ──
    top_call_chng = df.nlargest(3, "call_chng_oi")[["strike", "call_chng_oi"]]
    top_put_chng = df.nlargest(3, "put_chng_oi")[["strike", "put_chng_oi"]]
    neg_call_chng = df.nsmallest(3, "call_chng_oi")[["strike", "call_chng_oi"]]

    if not top_put_chng.empty:
        top_put_strike = float(top_put_chng.iloc[0]["strike"])
        top_put_val = int(top_put_chng.iloc[0]["put_chng_oi"])
        if top_put_val > 0 and top_put_strike < underlying:
            bullish_signals += 1
            verdict_points.append(
                f"🔼 New Put OI being added at {top_put_strike:,.0f} (below spot) → "
                f"Put writers building support → Bullish"
            )

    if not top_call_chng.empty:
        top_call_strike = float(top_call_chng.iloc[0]["strike"])
        top_call_val = int(top_call_chng.iloc[0]["call_chng_oi"])
        if top_call_val > 0 and top_call_strike > underlying:
            verdict_points.append(
                f"🔽 New Call OI being added at {top_call_strike:,.0f} (above spot) → "
                f"Call writers building resistance → Watch this level"
            )

    if not neg_call_chng.empty:
        neg_strike = float(neg_call_chng.iloc[0]["strike"])
        neg_val = int(neg_call_chng.iloc[0]["call_chng_oi"])
        if neg_val < 0 and neg_strike < underlying:
            bullish_signals += 1
            verdict_points.append(
                f"📤 Call OI unwinding at {neg_strike:,.0f} (below spot) → "
                f"Resistance dissolving → Bullish"
            )

    # ── Final Verdict ──
    total_signals = bullish_signals + bearish_signals
    net = bullish_signals - bearish_signals

    if net >= 3:
        bias = "Bullish"
        strength = "Strong" if net >= 4 else "Moderate"
        recommendation = "Buy / Go Long"
        color = "green"
        confidence = "High" if net >= 4 else "Medium"
    elif net >= 1:
        bias = "Bullish"
        strength = "Weak"
        recommendation = "Cautious Buy — Watch for Confirmation"
        color = "#4caf50"
        confidence = "Medium"
    elif net <= -3:
        bias = "Bearish"
        strength = "Strong" if net <= -4 else "Moderate"
        recommendation = "Avoid / Consider Short"
        color = "red"
        confidence = "High" if net <= -4 else "Medium"
    elif net <= -1:
        bias = "Bearish"
        strength = "Weak"
        recommendation = "Caution — Avoid Fresh Longs"
        color = "orange"
        confidence = "Medium"
    else:
        bias = "Range-bound"
        strength = "Moderate"
        recommendation = "Wait / Range Trade (Buy near support, sell near resistance)"
        color = "gray"
        confidence = "Medium"

    verdict_points.append(
        f"\n🏁 VERDICT: {bullish_signals} Bullish signals vs {bearish_signals} Bearish signals"
    )
    verdict_points.append(
        f"➡️ {recommendation}"
    )

    return bias, strength, recommendation, color, verdict_points, confidence


# ─────────────────────────────────────────────────────────────
# MAIN PUBLIC FUNCTION
# ─────────────────────────────────────────────────────────────

def get_option_chain_analysis(
    symbol: str,
    expiry_index: int = 0,
    n_strikes: int = 20,
) -> OptionChainData:
    """
    Main entry point — fetch + parse + analyze NSE option chain.

    Args:
        symbol: Any format — "TCS.NS", "RELIANCE", "NIFTY", "BANKNIFTY"
        expiry_index: 0 = nearest expiry (default), 1 = weekly+1, etc.
        n_strikes: Number of strikes around ATM to show (default 20 each side)

    Returns:
        OptionChainData — complete data + analysis

    Raises:
        ValueError: Symbol not F&O eligible or no data
        ConnectionError: NSE unreachable
    """
    nse_sym = _clean_symbol_for_nse(symbol)

    # ── Fetch ──
    raw_data = fetch_nse_option_chain(nse_sym, expiry_index)

    # ── Parse ──
    underlying, expiry, all_expiries, df = parse_option_chain(raw_data, expiry_index)

    # ── Filter to ATM ± n_strikes ──
    df_filtered = filter_atm_strikes(df, underlying, n_strikes)

    # ── Compute Key Metrics ──
    max_call_oi_strike = float(df_filtered.loc[df_filtered["call_oi"].idxmax(), "strike"])
    max_put_oi_strike = float(df_filtered.loc[df_filtered["put_oi"].idxmax(), "strike"])
    max_pain = _compute_max_pain(df_filtered)
    pcr, pcr_label = _compute_pcr(df_filtered)
    call_shift = _detect_oi_shift(df_filtered, "call_oi", underlying)
    put_shift = _detect_oi_shift(df_filtered, "put_oi", underlying)
    range_low, range_high = _compute_expected_range(
        max_call_oi_strike, max_put_oi_strike, underlying
    )

    # ── Generate Verdict ──
    bias, strength, recommendation, color, verdict_points, confidence = _generate_verdict(
        pcr=pcr,
        pcr_label=pcr_label,
        call_shift=call_shift,
        put_shift=put_shift,
        max_pain=max_pain,
        underlying=underlying,
        max_call_oi_strike=max_call_oi_strike,
        max_put_oi_strike=max_put_oi_strike,
        df=df_filtered,
    )

    # ── Build OptionStrike list ──
    atm_strike = float(df_filtered.iloc[(df_filtered["strike"] - underlying).abs().argsort().iloc[0]]["strike"])
    strikes = []
    for _, row in df_filtered.iterrows():
        s = row["strike"]
        c_oi = int(row["call_oi"])
        p_oi = int(row["put_oi"])
        c_chng = int(row["call_chng_oi"])
        p_chng = int(row["put_chng_oi"])

        c_pct = round((c_chng / c_oi * 100) if c_oi > 0 else 0, 1)
        p_pct = round((p_chng / p_oi * 100) if p_oi > 0 else 0, 1)

        strikes.append(OptionStrike(
            strike=s,
            call_oi=c_oi,
            call_chng_oi=c_chng,
            put_oi=p_oi,
            put_chng_oi=p_chng,
            is_max_call_oi=(s == max_call_oi_strike),
            is_max_put_oi=(s == max_put_oi_strike),
            is_atm=(s == atm_strike),
            call_oi_change_pct=c_pct,
            put_oi_change_pct=p_pct,
        ))

    analysis = OIAnalysis(
        symbol=nse_sym,
        expiry_date=expiry,
        underlying_price=underlying,
        max_call_oi_strike=max_call_oi_strike,
        max_put_oi_strike=max_put_oi_strike,
        max_pain_strike=max_pain,
        put_call_ratio=pcr,
        pcr_label=pcr_label,
        call_oi_shift=call_shift,
        put_oi_shift=put_shift,
        key_support=max_put_oi_strike,
        key_resistance=max_call_oi_strike,
        range_low=range_low,
        range_high=range_high,
        market_bias=bias,
        bias_strength=strength,
        recommendation=recommendation,
        recommendation_color=color,
        verdict_points=verdict_points,
        confidence=confidence,
    )

    return OptionChainData(
        symbol=nse_sym,
        expiry_date=expiry,
        underlying_price=underlying,
        available_expiries=all_expiries,
        strikes=strikes,
        analysis=analysis,
    )
```

---

### STEP 3 — Update `agent1.py` (Add New Tool)

Find the `@agent.tool` definitions section. Add the following — do NOT touch any existing tools:

```python
# Add to the imports section at top of agent1.py:
from utils.option_chain_analyzer import get_option_chain_analysis as _fetch_option_chain

# Add this new tool:
@agent.tool
async def get_option_chain_analysis(
    ctx: RunContext[AgentDeps],
    symbol: str,
    expiry_index: int = 0,
) -> ToolResponse:
    """
    Fetch and analyze NSE option chain data for a stock or index.
    Provides OI-based market direction analysis with Buy/Sell/Wait recommendation.

    Use this tool when the user asks:
    - What does the option chain say for [stock/index]?
    - Show me OI analysis for [symbol]
    - What is Put-Call Ratio for [symbol]?
    - Where is Max Pain for [symbol]?
    - Is the market bullish or bearish based on options?
    - Should I buy [stock] based on OI data?
    - What are the support and resistance levels from options?
    - Show option chain for NIFTY / BANKNIFTY / [stock]

    Args:
        symbol: Stock or index symbol. Examples: NIFTY, BANKNIFTY, RELIANCE.NS, TCS.NS
        expiry_index: 0 = nearest expiry (default), 1 = next expiry
    """
    try:
        result = _fetch_option_chain(symbol=symbol, expiry_index=expiry_index)
        a = result.analysis

        # Format numbers with Indian comma style (lakhs/crores)
        def fmt(n: int) -> str:
            if n >= 10_000_000:
                return f"{n/10_000_000:.1f}Cr"
            elif n >= 100_000:
                return f"{n/100_000:.1f}L"
            else:
                return f"{n:,}"

        # Top 5 strikes by Call OI and Put OI
        top_call = sorted(result.strikes, key=lambda x: x.call_oi, reverse=True)[:5]
        top_put = sorted(result.strikes, key=lambda x: x.put_oi, reverse=True)[:5]

        response_text = f"""
## 📊 Option Chain Analysis: {result.symbol}
**Expiry**: {result.expiry_date} | **Spot**: ₹{result.underlying_price:,.2f}

---

### 🎯 Recommendation: {a.recommendation}
**Market Bias**: {a.bias_strength} {a.market_bias} | **Confidence**: {a.confidence}

---

### 📐 Key OI Levels
| Level | Strike |
|-------|--------|
| 🧱 Max Call OI (Resistance) | {a.max_call_oi_strike:,.0f} |
| 🛡️ Max Put OI (Support) | {a.max_put_oi_strike:,.0f} |
| ⚙️ Max Pain | {a.max_pain_strike:,.0f} |
| 📊 Put-Call Ratio | {a.put_call_ratio:.3f} ({a.pcr_label}) |
| 📏 Expected Range | {a.range_low:,.0f} – {a.range_high:,.0f} |

---

### 🔝 Top 5 Call OI Strikes (Resistance Zones)
{chr(10).join(f"• {s.strike:,.0f} → OI: {fmt(s.call_oi)} (Chng: {s.call_chng_oi:+,})" for s in top_call)}

### 🔝 Top 5 Put OI Strikes (Support Zones)
{chr(10).join(f"• {s.strike:,.0f} → OI: {fmt(s.put_oi)} (Chng: {s.put_chng_oi:+,})" for s in top_put)}

---

### 🔍 OI Shift Analysis
**Call OI**: {a.call_oi_shift.description}
**Put OI**: {a.put_oi_shift.description}

---

### 📋 Full Verdict
{chr(10).join(a.verdict_points)}
"""
        return create_tool_response(response_text.strip(), "get_option_chain_analysis")

    except ValueError as e:
        return create_tool_response(
            f"Option chain not available for {symbol}: {str(e)}. "
            f"This stock may not be F&O eligible on NSE.",
            "get_option_chain_analysis"
        )
    except ConnectionError as e:
        return create_tool_response(
            f"Could not connect to NSE for option chain data: {str(e)}. "
            f"NSE API may be temporarily unavailable. Try again shortly.",
            "get_option_chain_analysis"
        )
    except Exception as e:
        return create_tool_response(
            f"Option chain analysis failed for {symbol}: {str(e)}",
            "get_option_chain_analysis"
        )
```

---

### STEP 4 — Update `app_advanced.py` (Add New Tab)

Find the existing `st.tabs(...)` call. Add `"📊 Option Chain"` to the list of tabs. Then add the following content block for the new tab — do NOT remove or modify any existing tab content:

```python
# Add import at top of app_advanced.py:
from utils.option_chain_analyzer import get_option_chain_analysis as fetch_option_chain
import plotly.graph_objects as go  # likely already imported

# ── OPTION CHAIN TAB CONTENT ──────────────────────────────────

with tab_option_chain:  # use whatever variable name matches the new tab
    st.header("📊 NSE Option Chain — OI Analysis")
    st.caption("Live Open Interest data from NSE India · Supports stocks & indices (F&O eligible only)")

    # ── INPUT SECTION ──
    oc_col1, oc_col2, oc_col3 = st.columns([3, 1.5, 1.5])

    with oc_col1:
        # Auto-fill with current stock if loaded
        default_sym = ""
        if st.session_state.get("company_data"):
            from utils.option_chain_analyzer import _clean_symbol_for_nse
            default_sym = _clean_symbol_for_nse(st.session_state.company_data.symbol)
        
        oc_symbol = st.text_input(
            "Symbol",
            value=default_sym,
            placeholder="NIFTY, BANKNIFTY, RELIANCE, TCS...",
            key="oc_symbol_input",
            help="Enter NSE symbol. Indices: NIFTY, BANKNIFTY, FINNIFTY. Stocks: RELIANCE, TCS, etc."
        )

    with oc_col2:
        oc_expiry_idx = st.selectbox(
            "Expiry",
            options=[0, 1, 2, 3],
            format_func=lambda x: ["Nearest (Weekly)", "Next Week", "Monthly", "+1 Month"][x],
            key="oc_expiry_idx",
        )

    with oc_col3:
        oc_n_strikes = st.slider(
            "Strikes around ATM",
            min_value=10, max_value=40, value=20, step=5,
            key="oc_n_strikes",
        )

    run_oc = st.button("🔍 Fetch & Analyze Option Chain", type="primary", key="run_option_chain")

    # ── POPULAR QUICK BUTTONS ──
    st.write("**Quick Select:**")
    qb_cols = st.columns(6)
    quick_symbols = ["NIFTY", "BANKNIFTY", "FINNIFTY", "RELIANCE", "TCS", "HDFCBANK"]
    for i, qsym in enumerate(quick_symbols):
        with qb_cols[i]:
            if st.button(qsym, key=f"qb_{qsym}"):
                st.session_state["oc_symbol_input"] = qsym
                st.rerun()

    # ── FETCH + CACHE ──
    cache_key = f"option_chain_{oc_symbol}_{oc_expiry_idx}"

    if run_oc and oc_symbol:
        with st.spinner(f"Fetching live option chain from NSE for {oc_symbol}..."):
            try:
                oc_data = fetch_option_chain(
                    symbol=oc_symbol,
                    expiry_index=oc_expiry_idx,
                    n_strikes=oc_n_strikes,
                )
                st.session_state[cache_key] = oc_data
                st.success(f"✅ Loaded {len(oc_data.strikes)} strikes for {oc_data.symbol} | Expiry: {oc_data.expiry_date}")
            except ValueError as e:
                st.error(f"❌ {str(e)}")
                st.info("💡 Make sure the symbol is F&O eligible on NSE. Try NIFTY or BANKNIFTY.")
                st.stop()
            except ConnectionError as e:
                st.error(f"🌐 NSE connection failed: {str(e)}")
                st.info("NSE API can be slow during market hours. Try again in a few seconds.")
                st.stop()
            except Exception as e:
                st.error(f"Unexpected error: {str(e)}")
                st.stop()

    oc_data = st.session_state.get(cache_key)

    if oc_data:
        a = oc_data.analysis

        # ── HEADER INFO ──
        st.markdown(
            f"**{oc_data.symbol}** | Spot: **₹{oc_data.underlying_price:,.2f}** | "
            f"Expiry: **{oc_data.expiry_date}** | "
            f"Data: {oc_data.timestamp.strftime('%H:%M:%S UTC')}"
        )

        # ── RECOMMENDATION BANNER ──
        rec_styles = {
            "green":   ("#e8f5e9", "#1b5e20"),
            "#4caf50": ("#f1f8e9", "#33691e"),
            "gray":    ("#f5f5f5", "#424242"),
            "orange":  ("#fff3e0", "#bf360c"),
            "red":     ("#ffebee", "#b71c1c"),
        }
        bg, fg = rec_styles.get(a.recommendation_color, ("#f5f5f5", "#424242"))
        st.markdown(
            f"<div style='background:{bg}; border-left:6px solid {fg}; "
            f"padding:14px 18px; border-radius:6px; margin:12px 0;'>"
            f"<div style='font-size:1.15em; font-weight:700; color:{fg};'>"
            f"🎯 {a.recommendation}</div>"
            f"<div style='color:{fg}; margin-top:4px;'>"
            f"{a.bias_strength} {a.market_bias} · Confidence: {a.confidence}</div>"
            f"</div>",
            unsafe_allow_html=True
        )

        # ── KEY METRICS ROW ──
        m1, m2, m3, m4, m5 = st.columns(5)
        with m1:
            st.metric("🧱 Resistance", f"{a.key_resistance:,.0f}",
                      delta=f"+{((a.key_resistance - a.underlying_price)/a.underlying_price*100):.1f}%")
        with m2:
            st.metric("🛡️ Support", f"{a.key_support:,.0f}",
                      delta=f"{((a.key_support - a.underlying_price)/a.underlying_price*100):.1f}%",
                      delta_color="inverse")
        with m3:
            st.metric("⚙️ Max Pain", f"{a.max_pain_strike:,.0f}")
        with m4:
            pcr_delta_color = "normal" if a.put_call_ratio >= 1.0 else "inverse"
            st.metric("📊 PCR", f"{a.put_call_ratio:.3f}",
                      delta=a.pcr_label, delta_color=pcr_delta_color)
        with m5:
            st.metric("📏 Range", f"{a.range_low:,.0f}–{a.range_high:,.0f}")

        # ── TABS INSIDE THE TAB: Table | Chart | Analysis ──
        inner_tab1, inner_tab2, inner_tab3 = st.tabs(
            ["📋 OI Table", "📈 OI Chart", "🔍 Full Analysis"]
        )

        with inner_tab1:
            # ── OI TABLE ──
            st.subheader("Option Chain — OI Data")

            # Build display DataFrame
            table_rows = []
            for s in oc_data.strikes:
                # Highlight ATM, max call OI, max put OI
                row_flag = ""
                if s.is_atm:
                    row_flag = "🔵 ATM"
                elif s.is_max_call_oi:
                    row_flag = "🧱 Max Call OI"
                elif s.is_max_put_oi:
                    row_flag = "🛡️ Max Put OI"

                def fmt_oi(v: int) -> str:
                    if v >= 10_000_000: return f"{v/10_000_000:.1f}Cr"
                    if v >= 100_000:    return f"{v/100_000:.1f}L"
                    return f"{v:,}"

                def fmt_chng(v: int) -> str:
                    sign = "+" if v > 0 else ""
                    if abs(v) >= 10_000_000: return f"{sign}{v/10_000_000:.1f}Cr"
                    if abs(v) >= 100_000:    return f"{sign}{v/100_000:.1f}L"
                    return f"{sign}{v:,}"

                table_rows.append({
                    "Call OI": fmt_oi(s.call_oi),
                    "Call Chng OI": fmt_chng(s.call_chng_oi),
                    "⚡": row_flag,
                    "Strike": f"₹{s.strike:,.0f}",
                    "Put Chng OI": fmt_chng(s.put_chng_oi),
                    "Put OI": fmt_oi(s.put_oi),
                })

            table_df = pd.DataFrame(table_rows)

            # Style the table
            def highlight_rows(row):
                flag = row["⚡"]
                if "ATM" in flag:
                    return ["background-color: #e3f2fd; font-weight: bold"] * len(row)
                elif "Max Call" in flag:
                    return ["background-color: #fce4ec"] * len(row)
                elif "Max Put" in flag:
                    return ["background-color: #e8f5e9"] * len(row)
                return [""] * len(row)

            styled = table_df.style.apply(highlight_rows, axis=1)
            st.dataframe(styled, use_container_width=True, height=500)

            # Legend
            st.caption(
                "🔵 ATM = At-the-Money (nearest to current price) | "
                "🧱 Red = Max Call OI (resistance) | "
                "🛡️ Green = Max Put OI (support)"
            )

        with inner_tab2:
            # ── OI CHART ──
            st.subheader("Open Interest Distribution")

            strikes_list = [s.strike for s in oc_data.strikes]
            call_ois = [s.call_oi for s in oc_data.strikes]
            put_ois = [s.put_oi for s in oc_data.strikes]
            call_chng = [s.call_chng_oi for s in oc_data.strikes]
            put_chng = [s.put_chng_oi for s in oc_data.strikes]

            chart_type = st.radio(
                "Chart type",
                ["OI Bar Chart", "Change in OI", "Combined"],
                horizontal=True,
                key="oc_chart_type"
            )

            fig = go.Figure()

            if chart_type in ["OI Bar Chart", "Combined"]:
                fig.add_trace(go.Bar(
                    x=strikes_list, y=call_ois,
                    name="Call OI",
                    marker_color="#ef5350",
                    opacity=0.8,
                    hovertemplate="Strike: %{x:,.0f}<br>Call OI: %{y:,}<extra></extra>"
                ))
                fig.add_trace(go.Bar(
                    x=strikes_list, y=put_ois,
                    name="Put OI",
                    marker_color="#26a69a",
                    opacity=0.8,
                    hovertemplate="Strike: %{x:,.0f}<br>Put OI: %{y:,}<extra></extra>"
                ))

            if chart_type in ["Change in OI", "Combined"]:
                fig.add_trace(go.Scatter(
                    x=strikes_list, y=call_chng,
                    name="Call Chng OI",
                    mode="lines+markers",
                    line=dict(color="#e53935", dash="dot", width=1.5),
                    marker=dict(size=4),
                    yaxis="y2" if chart_type == "Combined" else "y",
                    hovertemplate="Strike: %{x:,.0f}<br>Call Chng: %{y:+,}<extra></extra>"
                ))
                fig.add_trace(go.Scatter(
                    x=strikes_list, y=put_chng,
                    name="Put Chng OI",
                    mode="lines+markers",
                    line=dict(color="#00897b", dash="dot", width=1.5),
                    marker=dict(size=4),
                    yaxis="y2" if chart_type == "Combined" else "y",
                    hovertemplate="Strike: %{x:,.0f}<br>Put Chng: %{y:+,}<extra></extra>"
                ))

            # Vertical lines for key levels
            for level, label, color_line in [
                (a.underlying_price, f"Spot ₹{a.underlying_price:,.0f}", "#1565c0"),
                (a.max_call_oi_strike, f"Resistance {a.max_call_oi_strike:,.0f}", "#b71c1c"),
                (a.max_put_oi_strike, f"Support {a.max_put_oi_strike:,.0f}", "#1b5e20"),
                (a.max_pain_strike, f"Max Pain {a.max_pain_strike:,.0f}", "#f57f17"),
            ]:
                fig.add_vline(
                    x=level,
                    line_dash="dash",
                    line_color=color_line,
                    line_width=1.5,
                    annotation_text=label,
                    annotation_position="top",
                    annotation_font_size=10,
                )

            layout_kwargs = dict(
                barmode="group",
                xaxis_title="Strike Price",
                yaxis_title="Open Interest",
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                height=420,
                margin=dict(t=40, b=30, l=10, r=10),
                hovermode="x unified",
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
            )
            if chart_type == "Combined":
                layout_kwargs["yaxis2"] = dict(
                    title="Change in OI",
                    overlaying="y",
                    side="right",
                    showgrid=False,
                )
            fig.update_layout(**layout_kwargs)
            fig.update_yaxes(gridcolor="rgba(128,128,128,0.1)")

            st.plotly_chart(fig, use_container_width=True)

            # Expiry selector (if multiple expiries available)
            if len(oc_data.available_expiries) > 1:
                st.caption(
                    f"Available expiries: {' · '.join(oc_data.available_expiries[:5])}"
                )

        with inner_tab3:
            # ── FULL ANALYSIS ──
            st.subheader("OI Signal Analysis & Verdict")

            # OI Shift section
            sc1, sc2 = st.columns(2)
            with sc1:
                st.markdown("#### 📈 Call OI Signal")
                direction = a.call_oi_shift.direction
                dir_color = {"UP": "green", "DOWN": "red", "SIDEWAYS": "gray"}.get(direction, "gray")
                st.markdown(
                    f"<span style='color:{dir_color}; font-size:1.1em; font-weight:600;'>"
                    f"{'⬆' if direction=='UP' else ('⬇' if direction=='DOWN' else '➡')} "
                    f"{direction} · {a.call_oi_shift.strength}</span>",
                    unsafe_allow_html=True
                )
                st.write(a.call_oi_shift.description)

            with sc2:
                st.markdown("#### 📉 Put OI Signal")
                direction = a.put_oi_shift.direction
                dir_color = {"UP": "green", "DOWN": "red", "SIDEWAYS": "gray"}.get(direction, "gray")
                st.markdown(
                    f"<span style='color:{dir_color}; font-size:1.1em; font-weight:600;'>"
                    f"{'⬆' if direction=='UP' else ('⬇' if direction=='DOWN' else '➡')} "
                    f"{direction} · {a.put_oi_shift.strength}</span>",
                    unsafe_allow_html=True
                )
                st.write(a.put_oi_shift.description)

            st.divider()

            # Full verdict bullets
            st.markdown("#### 📋 Complete Signal Breakdown")
            for point in a.verdict_points:
                if point.startswith("\n🏁") or point.startswith("➡️"):
                    st.markdown(f"**{point.strip()}**")
                elif "Bullish" in point or "bullish" in point or "support" in point.lower():
                    st.success(point)
                elif "Bearish" in point or "bearish" in point or "resistance" in point.lower():
                    st.warning(point)
                else:
                    st.info(point)

            st.divider()

            # Explainer
            with st.expander("📖 How to read Option Chain OI"):
                st.markdown("""
**Open Interest (OI)** = Total number of outstanding option contracts not yet settled.

**Call OI** = Open positions in Call options at that strike.
High Call OI at a strike = that level is a **resistance** (writers expect price to stay below)

**Put OI** = Open positions in Put options at that strike.
High Put OI at a strike = that level is a **support** (writers expect price to stay above)

**Change in OI (Chng OI)**
- Positive = New positions being created (increased activity)
- Negative = Old positions being closed (unwinding)

**OI Shift Tracking**
- PUT OI concentration shifting HIGHER → Supports moving up → Market moving **UP** ⬆
- CALL OI concentration shifting LOWER → Resistance moving down → Market moving **DOWN** ⬇

**Put-Call Ratio (PCR)**
| PCR Value | Interpretation |
|-----------|---------------|
| > 1.5 | Extremely Bullish — heavy put writing |
| 1.2–1.5 | Bullish |
| 0.8–1.2 | Neutral / Range-bound |
| 0.5–0.8 | Bearish |
| < 0.5 | Extremely Bearish |

**Max Pain** = Strike where maximum option buyers lose money at expiry.
Market tends to gravitate toward Max Pain as expiry approaches.

*Note: Option chain data is only available for F&O-eligible stocks and indices on NSE.*
                """)
```

---

## ✅ Implementation Checklist for Claude Code

### New Files to Create
- [ ] `utils/option_chain_analyzer.py`

### Existing Files to Update (additive only)
- [ ] `models.py` — add `OptionStrike`, `OIShiftSignal`, `OIAnalysis`, `OptionChainData` models
- [ ] `agent1.py` — add `get_option_chain_analysis` tool + import
- [ ] `app_advanced.py` — add `"📊 Option Chain"` to `st.tabs(...)` + new tab content

### No new dependencies needed
`requests`, `pandas`, `plotly` are all already in `requirements.txt`.

---

## ⚠️ Critical Rules for Claude Code

1. **Two-step NSE session is mandatory** — `_create_nse_session()` MUST visit `https://www.nseindia.com/` before hitting the API. Skipping this causes 403 errors 100% of the time.

2. **Headers are non-negotiable** — All headers in `NSE_HEADERS` must be sent. Missing any of them (especially `Referer`, `X-Requested-With`, `sec-ch-ua`) will cause NSE to block the request.

3. **Indices vs Equities endpoint** — `NIFTY`, `BANKNIFTY`, `FINNIFTY` use `option-chain-indices`. All stocks use `option-chain-equities`. Check `NSE_INDICES` set before choosing URL.

4. **Symbol format** — strip `.NS`/`.BO` before sending to NSE. The `_clean_symbol_for_nse()` function handles this. NSE expects raw uppercase symbols like `RELIANCE`, `TCS`, `NIFTY`.

5. **F&O eligibility** — not all stocks have option chains. If NSE returns 404, show a clear error: "This stock is not F&O eligible on NSE."

6. **Market hours** — NSE API works best during market hours (9:15 AM – 3:30 PM IST). Outside hours it may return stale or empty data. Handle gracefully with a note.

7. **Do NOT add a new top-level tab if the tab count is already high** — check how many tabs currently exist in `app_advanced.py`. If there are already 7+ tabs, add the Option Chain tab and verify the `st.tabs()` call is updated correctly.

8. **Session state cache key** — use `f"option_chain_{symbol}_{expiry_index}"` so that different symbols and expiries are cached independently.

9. **NSE rate limiting** — add a `time.sleep(0.5)` between the homepage visit and API call (already in the code). Do not remove it — aggressive calling gets IP-blocked by NSE.

10. **`pd.DataFrame` import** — ensure `import pandas as pd` is at the top of `app_advanced.py` if not already present (it likely is, given existing chart functionality).

---

## 📐 Complete Data Flow

```
User enters symbol (e.g., "RELIANCE" or "NIFTY")
              │
              ▼
  _clean_symbol_for_nse()
  "RELIANCE.NS" → "RELIANCE"
  "NIFTY50"     → "NIFTY"
              │
              ▼
  _create_nse_session()
  Step 1: GET https://www.nseindia.com/  → get cookies
  Step 2: headers + cookies ready
              │
              ▼
  fetch_nse_option_chain()
  GET https://www.nseindia.com/api/option-chain-equities?symbol=RELIANCE
  → raw JSON with all strikes × all expiries
              │
              ▼
  parse_option_chain()
  Filter for selected expiry date
  Extract only: strike, CE.openInterest, CE.changeinOpenInterest,
                PE.openInterest,  PE.changeinOpenInterest
  → pandas DataFrame (all strikes)
              │
              ▼
  filter_atm_strikes()
  Keep only ±20 strikes around current spot price
  → filtered DataFrame (40 rows approx)
              │
              ▼
  OI Analysis:
  ├── _compute_max_pain()    → single strike float
  ├── _compute_pcr()         → ratio + label
  ├── _detect_oi_shift()     → OIShiftSignal (call side)
  ├── _detect_oi_shift()     → OIShiftSignal (put side)
  └── _generate_verdict()    → bias + recommendation + verdict_points
              │
              ▼
  OptionChainData returned
  (symbol, expiry, underlying, strikes[], analysis)
              │
         ┌────┴────┐
         ▼         ▼
    Streamlit    Agent Tool
    Tab UI       (chat reply)
    ├── Banner
    ├── 5 Metrics
    ├── OI Table (styled)
    ├── OI Chart (Plotly)
    └── Full Analysis
```
