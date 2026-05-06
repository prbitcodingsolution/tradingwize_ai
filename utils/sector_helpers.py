"""Sector classification and exchange normalization helpers.

Used by tools.py and app_advanced.py to make dashboard rendering
sector-aware (banking vs non-banking metrics) and to clean up the
raw yfinance exchange codes before display.
"""
from __future__ import annotations
from typing import Optional


# yfinance returns non-standard exchange codes (e.g. "NSI" for NSE).
# Map them to the user-facing codes shown in the dashboard.
_EXCHANGE_CODE_MAP = {
    "NSI": "NSE",   # yfinance code for National Stock Exchange of India
    "BSE": "BSE",
    "NSE": "NSE",
    "BOM": "BSE",   # yfinance alt code for Bombay Stock Exchange
    "NMS": "NASDAQ",
    "NYQ": "NYSE",
    "NGM": "NASDAQ",
    "ASE": "AMEX",
}


def normalize_exchange(code: Optional[str], symbol: Optional[str] = None) -> str:
    """Convert raw yfinance exchange codes to the standard display form.

    Args:
        code: Raw code from `info.get('exchange')` — may be None, "NSI", etc.
        symbol: Optional ticker symbol. When code is missing or unknown, fall
                back to inferring exchange from the `.NS` / `.BO` suffix.

    Returns:
        Cleaned exchange string. Defaults to "NSE" for unknown Indian tickers,
        "BSE" for `.BO` tickers, or the raw code uppercased if nothing matches.
    """
    if code:
        up = str(code).strip().upper()
        if up in _EXCHANGE_CODE_MAP:
            return _EXCHANGE_CODE_MAP[up]
        # Unknown code — if it looks like a valid short exchange code, keep it
        if up and len(up) <= 6 and up.isalpha():
            return up
    if symbol:
        s = str(symbol).upper()
        if s.endswith(".NS"):
            return "NSE"
        if s.endswith(".BO"):
            return "BSE"
    return "NSE"


# Banking/financial sector detection.
# yfinance's sector/industry strings vary:
#   sector: "Financial Services"
#   industry: "Banks - Regional", "Banks—Diversified", "Banks - Private Sector", etc.
# Indian banks sometimes come back as sector="Financial Services" with
# industry containing "Bank". We look at both.
_BANKING_INDUSTRY_MARKERS = (
    "bank",          # Banks – Regional / Diversified / Private Sector
    "banks",
)

_NBFC_INDUSTRY_MARKERS = (
    "credit services",
    "financial services",   # plain "Financial Services" industry on NBFCs
    "capital markets",
    "nbfc",
)

_INSURANCE_INDUSTRY_MARKERS = (
    "insurance",
)


def _industry_contains(industry: Optional[str], markers: tuple) -> bool:
    if not industry:
        return False
    lower = str(industry).strip().lower()
    return any(m in lower for m in markers)


def is_banking_sector(sector: Optional[str], industry: Optional[str] = None) -> bool:
    """Return True for traditional banks (where EBITDA/FCF/Gross Margin don't apply).

    A stock is classified as a bank when its `industry` explicitly mentions
    "bank". NBFCs, insurers, and asset managers are *not* banks — use
    `is_financial_sector()` if you want the broader group.
    """
    return _industry_contains(industry, _BANKING_INDUSTRY_MARKERS)


def is_financial_sector(sector: Optional[str], industry: Optional[str] = None) -> bool:
    """Return True for the broader finance bucket: banks, NBFCs, insurers, AMCs.

    These companies all share the property that traditional industrial metrics
    (EBITDA, Gross Margin, FCF as computed for manufacturers) are either
    meaningless or heavily distorted.
    """
    if is_banking_sector(sector, industry):
        return True
    if _industry_contains(industry, _NBFC_INDUSTRY_MARKERS):
        return True
    if _industry_contains(industry, _INSURANCE_INDUSTRY_MARKERS):
        return True
    # Fallback: sector == "Financial Services" with no industry
    if sector and "financial" in str(sector).lower() and not industry:
        return True
    return False


def is_insurance_sector(sector: Optional[str], industry: Optional[str] = None) -> bool:
    return _industry_contains(industry, _INSURANCE_INDUSTRY_MARKERS)


def sector_inapplicability_note(sector: Optional[str], industry: Optional[str] = None) -> Optional[str]:
    """Return a short user-facing explanation for why some industrial metrics
    are missing/hidden for this sector. None if no special handling needed.
    """
    if is_banking_sector(sector, industry):
        return "Not applicable for banking sector — see Banking Metrics below."
    if is_insurance_sector(sector, industry):
        return "Not applicable for insurance sector."
    if is_financial_sector(sector, industry):
        return "Not typically reported for financial services."
    return None
