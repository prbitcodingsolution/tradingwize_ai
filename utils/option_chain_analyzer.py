"""
NSE Option Chain Fetcher & OI Analyzer for TradingWize

Data source: NSE India public API (no API key required)
  - Indices: https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY
  - Stocks:  https://www.nseindia.com/api/option-chain-equities?symbol=RELIANCE

Uses Playwright (headed Chromium, off-screen) to bypass NSE's Akamai bot
protection. The browser window is positioned off-screen so the user never
sees it. Results are cached for 3 minutes to avoid repeated browser launches.

OI Analysis Logic:
  1. Max Pain: strike where total option premium decay is maximized
  2. PCR (Put-Call Ratio): Put OI / Call OI
     - PCR > 1.2 = Bullish (more Put writers = market expects upside)
     - PCR < 0.8 = Bearish (more Call writers = market expects downside)
     - PCR 0.8-1.2 = Neutral
  3. OI Walls: strike with highest Call OI = resistance, highest Put OI = support
  4. OI Shift: if top OI strikes are moving upward over time = bullish
  5. Change in OI: positive Chng OI = new positions being written
"""

import time
import subprocess
import sys
import json
import os
import pandas as pd
from typing import Optional, List, Dict, Tuple
from datetime import datetime

from models import OptionChainData, OptionStrike, OIAnalysis, OIShiftSignal


# -----------------------------------------------------------------
# NSE CONSTANTS & CACHE
# -----------------------------------------------------------------

NSE_BASE = "https://www.nseindia.com"

# Indices that use the indices endpoint (not equities)
NSE_INDICES = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"}

# In-memory cache: {cache_key: (timestamp, data_dict)}
_oc_cache: Dict[str, Tuple[float, Dict]] = {}
_OC_CACHE_TTL = 180  # 3 minutes


def _clean_symbol_for_nse(symbol: str) -> str:
    """
    Convert yfinance symbol to NSE-compatible symbol.
    TCS.NS -> TCS, RELIANCE.NS -> RELIANCE, NIFTY50 -> NIFTY, ^NSEI -> NIFTY
    """
    s = symbol.upper().replace(".NS", "").replace(".BO", "").replace("^", "")
    aliases = {
        "NSEI": "NIFTY",
        "NIFTY50": "NIFTY",
        "NIFTY 50": "NIFTY",
        "BANKNIFTY": "BANKNIFTY",
        "NIFTYBANK": "BANKNIFTY",
    }
    return aliases.get(s, s)


def _fetch_via_subprocess(nse_sym: str, is_index: bool) -> Dict:
    """
    Fetch NSE option chain data by running a worker script as a separate process.

    This avoids all asyncio event loop conflicts with Streamlit on Windows.
    The worker script (utils/_nse_fetch_worker.py) launches an off-screen
    Playwright browser, captures the data, and prints JSON to stdout.
    """
    worker_path = os.path.join(os.path.dirname(__file__), "_nse_fetch_worker.py")
    python_exe = sys.executable

    try:
        proc = subprocess.run(
            [python_exe, worker_path, nse_sym, "1" if is_index else "0"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=os.path.dirname(os.path.dirname(__file__)),
        )
    except subprocess.TimeoutExpired:
        raise ConnectionError("NSE option chain fetch timed out after 60s. Try again.")

    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()

    if proc.returncode != 0 or stdout.startswith("ERROR:"):
        err_msg = stdout.replace("ERROR:", "") if stdout.startswith("ERROR:") else stderr
        raise ConnectionError(f"NSE fetch failed: {err_msg}")

    if not stdout:
        raise ConnectionError("NSE fetch returned no data. NSE may be temporarily unavailable.")

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        raise ConnectionError(f"Invalid response from NSE fetch worker: {stdout[:200]}")

    return data


def fetch_nse_option_chain(symbol: str, expiry_index: int = 0) -> Dict:
    """
    Fetch raw option chain JSON from NSE API.

    Uses an off-screen Playwright browser to bypass NSE's Akamai bot protection.
    Results are cached for 3 minutes to minimize browser launches.

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
    cache_key = f"{nse_sym}_{expiry_index}"

    # Check cache
    if cache_key in _oc_cache:
        cached_time, cached_data = _oc_cache[cache_key]
        age = time.time() - cached_time
        if age < _OC_CACHE_TTL:
            print(f"[OC] Using cached data for {nse_sym} (age: {age:.0f}s)")
            return cached_data

    # Fetch via a separate subprocess to completely avoid asyncio event loop
    # conflicts with Streamlit on Windows + Python 3.14
    data = _fetch_via_subprocess(nse_sym, is_index)

    records = data.get("records", {})

    if not records.get("expiryDates"):
        raise ValueError(
            f"No option chain data available for '{nse_sym}'. "
            f"The stock may not be F&O eligible, or NSE data is temporarily unavailable."
        )

    # Cache the result
    _oc_cache[cache_key] = (time.time(), data)

    return data


# -----------------------------------------------------------------
# DATA PARSER
# -----------------------------------------------------------------

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

    # NSE default page load returns data without expiryDate field (all None).
    # In that case, all rows belong to the selected (nearest) expiry.
    has_expiry_field = any(item.get("expiryDate") is not None for item in raw_strikes)

    rows = []
    for item in raw_strikes:
        if has_expiry_field and item.get("expiryDate") != selected_expiry:
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
    Keep only +/-n_strikes around the ATM (at-the-money) strike.
    """
    atm_idx = (df["strike"] - underlying).abs().idxmin()
    low = max(0, atm_idx - n_strikes)
    high = min(len(df) - 1, atm_idx + n_strikes)
    return df.iloc[low:high + 1].reset_index(drop=True)


# -----------------------------------------------------------------
# OI ANALYSIS ENGINE
# -----------------------------------------------------------------

def _compute_max_pain(df: pd.DataFrame) -> float:
    """
    Max Pain = strike where total value of expiring options is minimized
    (i.e., where option sellers profit most).
    """
    strikes = df["strike"].values
    call_ois = df["call_oi"].values
    put_ois = df["put_oi"].values
    min_pain = float("inf")
    max_pain_strike = strikes[len(strikes) // 2]

    for k in strikes:
        call_pain = sum(max(0.0, k - s) * c for s, c in zip(strikes, call_ois))
        put_pain = sum(max(0.0, s - k) * p for s, p in zip(strikes, put_ois))
        total = call_pain + put_pain
        if total < min_pain:
            min_pain = total
            max_pain_strike = k

    return float(max_pain_strike)


def _compute_pcr(df: pd.DataFrame) -> Tuple[float, str, int]:
    """
    Put-Call Ratio = Total Put OI / Total Call OI
    Returns (pcr_value, label, score_contribution)

    Indian market PCR interpretation:
    - PCR > 1.5  = Extremely Bullish (+2): Heavy put writing = bulls very confident
    - PCR 1.2-1.5 = Bullish (+1)
    - PCR 0.8-1.2 = Neutral (0): balanced market
    - PCR 0.5-0.8 = Bearish (-1): call writing dominates
    - PCR < 0.5  = Extremely Bearish (-2): very aggressive call writing
    """
    total_call_oi = int(df["call_oi"].sum())
    total_put_oi = int(df["put_oi"].sum())

    if total_call_oi == 0:
        return 1.0, "Neutral", 0

    pcr = round(total_put_oi / total_call_oi, 3)

    if pcr > 1.5:
        label, score = "Extremely Bullish", 2
    elif pcr > 1.2:
        label, score = "Bullish", 1
    elif pcr >= 0.8:
        label, score = "Neutral", 0
    elif pcr >= 0.5:
        label, score = "Bearish", -1
    else:
        label, score = "Extremely Bearish", -2

    return pcr, label, score


def _detect_oi_shift(df: pd.DataFrame, oi_col: str, underlying: float) -> OIShiftSignal:
    """
    Correctly interpret where OI is concentrated relative to the spot price.

    CALL OI Rules (calls are written by bears, bought by bulls):
    - Call OI FAR above spot (>5%): resistance is distant -> mild bullish (room to move up)
    - Call OI JUST above spot (1-5%): tight resistance cap -> neutral to bearish
    - Call OI AT spot (+-1%): max pain zone -> neutral, expect consolidation
    - Call OI BELOW spot: extremely bearish (call writers below spot = very confident bears)

    PUT OI Rules (puts are written by bulls, bought by bears):
    - Put OI FAR below spot (>5%): floor is distant -> put writers confident -> strong bullish
    - Put OI JUST below spot (1-5%): nearby floor -> mild bullish support
    - Put OI AT spot (+-1%): max pain zone -> neutral
    - Put OI ABOVE spot: bearish hedge buying above spot -> STRONGLY BEARISH
    """
    is_call = (oi_col == "call_oi")

    top_df = df.nlargest(5, oi_col)
    if top_df.empty or top_df[oi_col].sum() == 0:
        return OIShiftSignal(
            direction="SIDEWAYS",
            description="Insufficient OI data to determine shift.",
            strength="Weak",
            score_contribution=0,
        )

    # Weighted average strike of top OI (weights = OI values)
    weighted_avg_strike = float(
        (top_df["strike"] * top_df[oi_col]).sum() / top_df[oi_col].sum()
    )
    top_strike = float(top_df.iloc[0]["strike"])
    distance_pct = ((weighted_avg_strike - underlying) / underlying) * 100

    if is_call:
        # -- CALL OI LOGIC --
        if weighted_avg_strike < underlying * 0.99:
            return OIShiftSignal(
                direction="DOWN",
                description=(
                    f"Call OI concentrated BELOW spot at {weighted_avg_strike:,.0f} "
                    f"({distance_pct:.1f}% below spot). "
                    f"Call writers are betting market falls further — extremely bearish signal."
                ),
                strength="Strong",
                score_contribution=-3,
            )
        elif weighted_avg_strike <= underlying * 1.02:
            return OIShiftSignal(
                direction="SIDEWAYS",
                description=(
                    f"Call OI wall at {top_strike:,.0f} is very close "
                    f"({distance_pct:+.1f}% above spot). "
                    f"Tight resistance cap — upside is limited short term. Neutral to slightly bearish."
                ),
                strength="Moderate",
                score_contribution=-1,
            )
        elif weighted_avg_strike <= underlying * 1.05:
            return OIShiftSignal(
                direction="SIDEWAYS",
                description=(
                    f"Call OI concentrated at {top_strike:,.0f} "
                    f"({distance_pct:+.1f}% above spot). "
                    f"Moderate resistance — some room to move up but watch this level."
                ),
                strength="Moderate",
                score_contribution=0,
            )
        else:
            return OIShiftSignal(
                direction="UP",
                description=(
                    f"Call OI concentrated at {top_strike:,.0f} "
                    f"({distance_pct:+.1f}% above spot). "
                    f"Resistance is far away — market has room to move up. Mildly bullish."
                ),
                strength="Weak",
                score_contribution=1,
            )

    else:
        # -- PUT OI LOGIC --
        if weighted_avg_strike > underlying * 1.01:
            return OIShiftSignal(
                direction="DOWN",
                description=(
                    f"Put OI concentrated ABOVE spot at {weighted_avg_strike:,.0f} "
                    f"({distance_pct:+.1f}% above spot). "
                    f"Puts being bought aggressively ABOVE current price — "
                    f"participants hedging against a sharp drop. Strongly bearish signal."
                ),
                strength="Strong",
                score_contribution=-2,
            )
        elif weighted_avg_strike >= underlying * 0.98:
            return OIShiftSignal(
                direction="UP",
                description=(
                    f"Put OI floor at {top_strike:,.0f} "
                    f"({distance_pct:.1f}% below spot). "
                    f"Put writers defending just below spot — immediate support zone. Mildly bullish."
                ),
                strength="Moderate",
                score_contribution=1,
            )
        elif weighted_avg_strike >= underlying * 0.95:
            return OIShiftSignal(
                direction="UP",
                description=(
                    f"Put OI support at {top_strike:,.0f} "
                    f"({distance_pct:.1f}% below spot). "
                    f"Put writers building a floor below spot — bullish support zone."
                ),
                strength="Moderate",
                score_contribution=2,
            )
        else:
            return OIShiftSignal(
                direction="UP",
                description=(
                    f"Put OI concentrated at {top_strike:,.0f} "
                    f"({distance_pct:.1f}% below spot). "
                    f"Put writers are very confident market won't fall this far — "
                    f"strong long-term support. Bullish."
                ),
                strength="Strong",
                score_contribution=2,
            )


def _compute_expected_range(
    max_call_strike: float,
    max_put_strike: float,
    underlying: float
) -> Tuple[float, float]:
    """
    Expected range = between max Put OI (support) and max Call OI (resistance).
    """
    low = min(max_put_strike, underlying * 0.97)
    high = max(max_call_strike, underlying * 1.03)
    return round(low, 0), round(high, 0)


def _score_max_pain(max_pain: float, underlying: float) -> Tuple[str, int]:
    """
    Max Pain scoring relative to spot.
    Max Pain is a WEAK signal — market gravitates toward it near expiry only.
    Returns (description, score_contribution)
    """
    diff_pct = ((max_pain - underlying) / underlying) * 100

    if diff_pct > 2.0:
        return (
            f"Max Pain at {max_pain:,.0f} is {diff_pct:+.1f}% above spot — "
            f"market may drift UP toward max pain as expiry approaches.",
            1
        )
    elif diff_pct < -2.0:
        return (
            f"Max Pain at {max_pain:,.0f} is {diff_pct:+.1f}% below spot — "
            f"market may drift DOWN toward max pain as expiry approaches.",
            -1
        )
    else:
        return (
            f"Max Pain at {max_pain:,.0f} is near spot ({diff_pct:+.1f}%) — "
            f"market likely to stay range-bound near this level into expiry.",
            0
        )


def _generate_verdict(
    pcr: float,
    pcr_label: str,
    pcr_score: int,
    call_shift: OIShiftSignal,
    put_shift: OIShiftSignal,
    max_pain: float,
    underlying: float,
    max_call_oi_strike: float,
    max_put_oi_strike: float,
    df: pd.DataFrame,
) -> Tuple[str, str, str, str, List[str], str, int, bool]:
    """
    Generate final verdict using WEIGHTED scoring from all signals.

    Each signal contributes a signed score: positive = bullish, negative = bearish.
    Contradiction detection: if call and put OI signals are strongly opposed -> NEUTRAL/WAIT.

    Returns:
        (market_bias, bias_strength, recommendation, recommendation_color,
         verdict_points, confidence, total_score, has_contradiction)
    """
    verdict_points = []
    total_score = 0

    # -- SIGNAL 1: PCR --
    verdict_points.append(
        f"Put-Call Ratio: {pcr:.3f} -> {pcr_label} "
        f"(Score: {'+' if pcr_score >= 0 else ''}{pcr_score})"
    )
    total_score += pcr_score

    # -- SIGNAL 2: Call OI position --
    verdict_points.append(f"Call OI Signal: {call_shift.description}")
    verdict_points.append(
        f"   -> Score contribution: {'+' if call_shift.score_contribution >= 0 else ''}"
        f"{call_shift.score_contribution}"
    )
    total_score += call_shift.score_contribution

    # -- SIGNAL 3: Put OI position --
    verdict_points.append(f"Put OI Signal: {put_shift.description}")
    verdict_points.append(
        f"   -> Score contribution: {'+' if put_shift.score_contribution >= 0 else ''}"
        f"{put_shift.score_contribution}"
    )
    total_score += put_shift.score_contribution

    # -- SIGNAL 4: Max Pain (weak signal) --
    pain_desc, pain_score = _score_max_pain(max_pain, underlying)
    verdict_points.append(f"Max Pain Analysis: {pain_desc}")
    total_score += pain_score

    # -- SIGNAL 5: OI Wall proximity --
    dist_to_resistance_pct = ((max_call_oi_strike - underlying) / underlying) * 100
    dist_to_support_pct = ((underlying - max_put_oi_strike) / underlying) * 100

    verdict_points.append(
        f"Resistance (Max Call OI): {max_call_oi_strike:,.0f} "
        f"({dist_to_resistance_pct:+.1f}% from spot)"
    )
    verdict_points.append(
        f"Support (Max Put OI): {max_put_oi_strike:,.0f} "
        f"({-dist_to_support_pct:+.1f}% from spot)"
    )

    if dist_to_support_pct < dist_to_resistance_pct * 0.5:
        wall_score = 1
        verdict_points.append(
            f"Market is much closer to Put support than Call resistance -> bullish lean (+1)"
        )
    elif dist_to_resistance_pct < dist_to_support_pct * 0.5:
        wall_score = -1
        verdict_points.append(
            f"Market is much closer to Call resistance than Put support -> bearish lean (-1)"
        )
    else:
        wall_score = 0
        verdict_points.append(
            f"Market is balanced between support and resistance -> neutral (0)"
        )
    total_score += wall_score

    # -- SIGNAL 6: Change in OI (fresh positioning) --
    fresh_put_below = df[(df["strike"] < underlying) & (df["put_chng_oi"] > 0)]
    fresh_call_above = df[(df["strike"] > underlying) & (df["call_chng_oi"] > 0)]
    unwinding_call_below = df[(df["strike"] < underlying) & (df["call_chng_oi"] < 0)]

    chng_score = 0
    if not fresh_put_below.empty:
        top_fresh_put = fresh_put_below.loc[fresh_put_below["put_chng_oi"].idxmax()]
        if int(top_fresh_put["put_chng_oi"]) > 0:
            chng_score += 1
            verdict_points.append(
                f"Fresh Put OI being written at {top_fresh_put['strike']:,.0f} "
                f"(below spot) — bulls adding support (+1)"
            )

    if not fresh_call_above.empty:
        top_fresh_call = fresh_call_above.loc[fresh_call_above["call_chng_oi"].idxmax()]
        if int(top_fresh_call["call_chng_oi"]) > 0:
            chng_score -= 1
            verdict_points.append(
                f"Fresh Call OI being written at {top_fresh_call['strike']:,.0f} "
                f"(above spot) — bears building resistance (-1)"
            )

    if not unwinding_call_below.empty:
        top_unwind = unwinding_call_below.loc[unwinding_call_below["call_chng_oi"].idxmin()]
        if int(top_unwind["call_chng_oi"]) < 0:
            chng_score += 1
            verdict_points.append(
                f"Call OI unwinding at {top_unwind['strike']:,.0f} "
                f"(below spot) — bearish resistance dissolving (+1)"
            )

    total_score += chng_score

    # -- CONTRADICTION DETECTION --
    call_is_strong = call_shift.strength == "Strong"
    put_is_strong = put_shift.strength == "Strong"
    signals_opposed = (
        (call_shift.direction == "UP" and put_shift.direction == "DOWN") or
        (call_shift.direction == "DOWN" and put_shift.direction == "UP")
    )
    strong_contradiction = signals_opposed and (call_is_strong or put_is_strong)

    if strong_contradiction:
        verdict_points.append(
            "CONTRADICTION DETECTED: Call OI and Put OI signals are pointing in "
            "opposite directions. Market is sending mixed signals. "
            "Wait for signals to align before trading."
        )
        total_score = max(-1, min(1, total_score))

    # -- FINAL RECOMMENDATION --
    verdict_points.append(f"\nTOTAL SIGNAL SCORE: {'+' if total_score >= 0 else ''}{total_score}")

    if strong_contradiction:
        bias = "Conflicting"
        strength = "Mixed Signals"
        recommendation = "Wait — Conflicting OI Signals. Do not trade until signals align."
        color = "orange"
        confidence = "Low"
    elif total_score >= 5:
        bias = "Bullish"
        strength = "Strong"
        recommendation = "Buy / Go Long — Strong OI Support"
        color = "green"
        confidence = "High"
    elif total_score >= 2:
        bias = "Bullish"
        strength = "Moderate"
        recommendation = "Cautious Buy — Bullish OI bias, confirm with price action"
        color = "#4caf50"
        confidence = "Medium"
    elif total_score >= 1:
        bias = "Slightly Bullish"
        strength = "Weak"
        recommendation = "Neutral-Bullish — Wait for stronger confirmation"
        color = "#4caf50"
        confidence = "Low"
    elif total_score <= -5:
        bias = "Bearish"
        strength = "Strong"
        recommendation = "Avoid / Consider Short — Strong OI resistance"
        color = "red"
        confidence = "High"
    elif total_score <= -2:
        bias = "Bearish"
        strength = "Moderate"
        recommendation = "Caution — Avoid fresh long positions"
        color = "orange"
        confidence = "Medium"
    elif total_score <= -1:
        bias = "Slightly Bearish"
        strength = "Weak"
        recommendation = "Neutral-Bearish — Monitor before entering"
        color = "orange"
        confidence = "Low"
    else:
        bias = "Range-bound"
        strength = "Neutral"
        recommendation = "Range Trade — Buy near support {:.0f}, Sell near resistance {:.0f}".format(
            max_put_oi_strike, max_call_oi_strike
        )
        color = "gray"
        confidence = "Medium"

    verdict_points.append(f"RECOMMENDATION: {recommendation}")

    return bias, strength, recommendation, color, verdict_points, confidence, total_score, strong_contradiction


# -----------------------------------------------------------------
# MAIN PUBLIC FUNCTION
# -----------------------------------------------------------------

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

    # Fetch
    raw_data = fetch_nse_option_chain(nse_sym, expiry_index)

    # Parse
    underlying, expiry, all_expiries, df = parse_option_chain(raw_data, expiry_index)

    # Filter to ATM +/- n_strikes
    df_filtered = filter_atm_strikes(df, underlying, n_strikes)

    # Compute Key Metrics
    max_call_oi_strike = float(df_filtered.loc[df_filtered["call_oi"].idxmax(), "strike"])
    max_put_oi_strike = float(df_filtered.loc[df_filtered["put_oi"].idxmax(), "strike"])
    max_pain = _compute_max_pain(df_filtered)
    pcr, pcr_label, pcr_score = _compute_pcr(df_filtered)
    call_shift = _detect_oi_shift(df_filtered, "call_oi", underlying)
    put_shift = _detect_oi_shift(df_filtered, "put_oi", underlying)
    range_low, range_high = _compute_expected_range(
        max_call_oi_strike, max_put_oi_strike, underlying
    )

    # Generate Verdict
    bias, strength, recommendation, color, verdict_points, confidence, total_score, has_contradiction = _generate_verdict(
        pcr=pcr,
        pcr_label=pcr_label,
        pcr_score=pcr_score,
        call_shift=call_shift,
        put_shift=put_shift,
        max_pain=max_pain,
        underlying=underlying,
        max_call_oi_strike=max_call_oi_strike,
        max_put_oi_strike=max_put_oi_strike,
        df=df_filtered,
    )

    # Build OptionStrike list
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
        total_signal_score=total_score,
        has_contradiction=has_contradiction,
        pcr_score=pcr_score,
    )

    return OptionChainData(
        symbol=nse_sym,
        expiry_date=expiry,
        underlying_price=underlying,
        available_expiries=all_expiries,
        strikes=strikes,
        analysis=analysis,
    )
