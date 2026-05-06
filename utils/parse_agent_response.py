"""Parse the formatted agent response text into a structured dict.

The agent returns a long formatted string assembled by
`tools.py::format_data_for_report` plus the expert opinion and screener
summary injected by `agent1.py::analyze_stock_request`. The dashboard
already has most of this data in a structured `CompanyData` object, so
this parser focuses on the pieces that are ONLY available in the raw
text: the "Selected:" line, the expert opinion and the Screener.in
quarterly summary. It also provides full section extraction for
components that want to render directly from text.
"""

from __future__ import annotations

import re
from typing import Any


# Section markers in the order they appear in the formatted report.
# Each tuple is (key, regex pattern that matches the start of the section).
# Patterns use MULTILINE so ^ matches start of line.
_SECTION_MARKERS: list[tuple[str, re.Pattern[str]]] = [
    ("selected", re.compile(r"^✅\s*\*\*Selected:", re.MULTILINE)),
    ("header", re.compile(r"^📊\s*\*\*COMPREHENSIVE STOCK ANALYSIS\*\*", re.MULTILINE)),
    ("snapshot", re.compile(r"^🏢\s*\*\*COMPANY SNAPSHOT\*\*", re.MULTILINE)),
    ("business", re.compile(r"^📋\s*\*\*BUSINESS OVERVIEW\*\*", re.MULTILINE)),
    ("financials", re.compile(r"^💰\s*\*\*FINANCIAL METRICS", re.MULTILINE)),
    ("market", re.compile(r"^📈\s*\*\*STOCK INFORMATION & MARKET DATA\*\*", re.MULTILINE)),
    ("performance", re.compile(r"^📊\s*\*\*PRICE PERFORMANCE\*\*", re.MULTILINE)),
    ("competitors", re.compile(r"^🏆\s*\*\*COMPETITOR COMPARISON\*\*", re.MULTILINE)),
    ("swot", re.compile(r"^🎯\s*\*\*SWOT ANALYSIS\*\*", re.MULTILINE)),
    ("news", re.compile(r"^📰\s*\*\*NEWS & ANNOUNCEMENTS\*\*", re.MULTILINE)),
    # New unified marker (current format — single merged insight).
    ("unified", re.compile(r"^🧠\s*\*\*UNIFIED INVESTMENT INSIGHT\*\*", re.MULTILINE)),
    # Legacy markers — still recognised so cached DB analyses written before
    # the unified-insight rollout continue to parse correctly. When only the
    # legacy markers are present we populate `expertOpinion` / `screenerSummary`
    # and the caller can fall back to rendering them as before.
    ("expert", re.compile(r"^👨‍💼\s*\*\*EXPERT OPINION\*\*", re.MULTILINE)),
    ("screener", re.compile(r"^\*\*📊\s*Screener\.in Quarterly Reports Summary\*\*", re.MULTILINE)),
]


def _strip_md(s: str) -> str:
    """Remove markdown bold/italic markers from a short label string."""
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"\*(.+?)\*", r"\1", s)
    return s.strip()


def _split_sections(raw: str) -> dict[str, str]:
    """Find the start offset of every known section and return the raw
    text between each marker and the next one.
    """
    hits: list[tuple[int, str]] = []
    for key, pat in _SECTION_MARKERS:
        m = pat.search(raw)
        if m:
            hits.append((m.start(), key))
    hits.sort()

    out: dict[str, str] = {}
    for i, (start, key) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else len(raw)
        out[key] = raw[start:end].strip()
    return out


def is_multi_stock_response(raw: str) -> bool:
    """Detect whether the raw agent output is a multi-stock selection list
    rather than a full analysis. The stock-validation tool produces this
    when multiple tickers match the user's query.
    """
    if not raw:
        return False
    lowered = raw.lower()
    if "different stocks matching" in lowered:
        return True
    if "please specify which one" in lowered:
        return True
    if "select which one to analyze" in lowered:
        return True
    # Heuristic: short response with numbered list and no COMPREHENSIVE header
    if "comprehensive stock analysis" not in lowered and re.search(r"^\s*\d+\.\s", raw, re.MULTILINE):
        if len(raw) < 4000:
            return True
    return False


def parse_multi_stock_options(raw: str) -> list[dict[str, str]]:
    """Extract numbered stock options from a multi-stock validation
    response. Returns list of {number, name, ticker}.
    """
    options: list[dict[str, str]] = []
    # Common patterns:  "1. Company Name (TICKER.NS)" or "1) Company Name - TICKER"
    for m in re.finditer(
        r"^\s*(\d+)[\.\)]\s*(.+?)\s*[\(\-]\s*([A-Z0-9\.\-]+)\s*\)?\s*$",
        raw,
        re.MULTILINE,
    ):
        options.append(
            {
                "number": m.group(1),
                "name": _strip_md(m.group(2)),
                "ticker": m.group(3).strip(),
            }
        )
    return options


def _parse_selected(section: str) -> dict[str, str]:
    # e.g. "✅ **Selected: Tata Consultancy Services Limited (TCS.NS)**"
    m = re.search(r"Selected:\s*(.+?)\s*\(([^)]+)\)", section)
    if not m:
        return {"name": "", "ticker": ""}
    return {"name": m.group(1).strip(), "ticker": m.group(2).strip()}


def _parse_kv_bullets(section: str) -> dict[str, str]:
    """Parse lines like '• **Key:** value' or '• Key: value' into a dict."""
    out: dict[str, str] = {}
    for line in section.splitlines():
        line = line.strip()
        if not line or line.startswith("🏢") or line.startswith("📈"):
            continue
        # Remove leading bullet
        line = re.sub(r"^[•\-\*]\s*", "", line)
        m = re.match(r"\*\*([^:]+):\*\*\s*(.+)$", line)
        if not m:
            m = re.match(r"([^:]+):\s*(.+)$", line)
        if m:
            key = _strip_md(m.group(1)).strip().lower()
            value = _strip_md(m.group(2)).strip()
            if key and value:
                out[key] = value
    return out


def _parse_snapshot(section: str) -> dict[str, str]:
    kv = _parse_kv_bullets(section)
    mapping = {
        "company name": "companyName",
        "ticker symbol": "tickerSymbol",
        "exchange": "exchange",
        "sector": "sector",
        "industry": "industry",
        "headquarters": "headquarters",
        "founded": "founded",
        "ceo": "ceo",
        "employees": "employees",
        "website": "website",
    }
    out = {v: "" for v in mapping.values()}
    for k, v in kv.items():
        if k in mapping:
            out[mapping[k]] = v
    return out


def _parse_business_overview(section: str) -> str:
    # Drop the header line, keep the rest as one paragraph.
    lines = section.splitlines()
    body: list[str] = []
    for line in lines[1:]:  # skip the "📋 **BUSINESS OVERVIEW**" line
        s = line.strip()
        if not s:
            continue
        # Skip the "Geographic Presence" metadata bullet if present.
        if re.match(r"^[•\-\*]?\s*\*\*Geographic Presence:?\*\*", s):
            continue
        body.append(s)
    text = " ".join(body).strip()
    # Trim trailing "..." placeholder used by the formatter.
    text = re.sub(r"\.\.\.$", "", text).strip()
    return text


def _parse_financials(section: str) -> dict[str, dict[str, str]]:
    """Split Financial Metrics into its five sub-blocks."""
    sub_labels = {
        "**Income Statement:**": "incomeStatement",
        "**Balance Sheet:**": "balanceSheet",
        "**Cash Flow:**": "cashFlow",
        "**Valuation Metrics:**": "valuation",
        "**Profitability Margins:**": "margins",
    }
    blocks: dict[str, dict[str, str]] = {v: {} for v in sub_labels.values()}
    current: str | None = None

    for line in section.splitlines():
        stripped = line.strip()
        if stripped in sub_labels:
            current = sub_labels[stripped]
            continue
        if not current or not stripped:
            continue
        # Items look like "- Label: value" or "• Label: value"
        m = re.match(r"^[\-•\*]\s*([^:]+):\s*(.+)$", stripped)
        if not m:
            continue
        key = m.group(1).strip().lower()
        value = m.group(2).strip()
        blocks[current][key] = value
    return blocks


def _parse_market_data(section: str) -> dict[str, str]:
    kv = _parse_kv_bullets(section)
    mapping = {
        "current share price": "currentPrice",
        "52-week high": "weekHigh52",
        "52-week low": "weekLow52",
        "market capitalization": "marketCap",
        "volume": "volume",
        "average volume": "avgVolume",
        "beta (volatility)": "beta",
        "dividend yield": "dividendYield",
        "promoter holding": "promoterHolding",
        "fii holding": "fiiHolding",
        "dii holding": "diiHolding",
    }
    out = {v: "" for v in mapping.values()}
    for k, v in kv.items():
        if k in mapping:
            out[mapping[k]] = v
    return out


def _parse_price_performance(section: str) -> dict[str, Any]:
    periods: list[dict[str, Any]] = []
    seven_day: list[dict[str, Any]] = []
    period_labels = {
        "1 day change": "1D",
        "1 week change": "1W",
        "1 month change": "1M",
        "6 month change": "6M",
        "1 year change": "1Y",
        "5 year cagr": "5Y CAGR",
    }
    in_history = False

    for line in section.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if "Recent Price History" in stripped:
            in_history = True
            continue

        if not in_history:
            m = re.match(r"^[•\-]\s*([^:]+):\s*([\-+]?\d[\d\.,]*)%?\s*.*$", stripped)
            if m:
                label_key = m.group(1).strip().lower()
                if label_key in period_labels:
                    value_str = m.group(2).strip()
                    try:
                        value_num = float(value_str.replace(",", ""))
                        is_pos = value_num >= 0
                    except ValueError:
                        is_pos = "+" in value_str or "📈" in stripped
                    periods.append(
                        {
                            "label": period_labels[label_key],
                            "value": f"{value_str}%",
                            "isPositive": is_pos,
                        }
                    )
        else:
            # Lines like "• 2026-04-15: ₹1234.56 (+0.55%) 📈"
            m = re.match(
                r"^[•\-]\s*([\d\-]+):\s*([^\s\(]+)(?:\s*\(([\-+]?\d[\d\.]*)%\))?.*$",
                stripped,
            )
            if m:
                change_str = m.group(3) or ""
                is_pos = change_str.startswith("+") or change_str == ""
                if change_str.startswith("-"):
                    is_pos = False
                seven_day.append(
                    {
                        "date": m.group(1),
                        "price": m.group(2),
                        "change": f"{change_str}%" if change_str else "",
                        "isPositive": is_pos,
                    }
                )
    return {"periods": periods, "sevenDayHistory": seven_day}


def _parse_swot(section: str) -> dict[str, list[str]]:
    out = {
        "strengths": [],
        "weaknesses": [],
        "opportunities": [],
        "threats": [],
    }
    labels = {
        "**Strengths:**": "strengths",
        "**Weaknesses:**": "weaknesses",
        "**Opportunities:**": "opportunities",
        "**Threats:**": "threats",
    }
    current: str | None = None
    for line in section.splitlines():
        stripped = line.strip()
        if stripped in labels:
            current = labels[stripped]
            continue
        if not current or not stripped:
            continue
        m = re.match(r"^[•\-\*]\s*(.+)$", stripped)
        if m:
            point = _strip_md(m.group(1))
            if point:
                out[current].append(point)
    return out


def _parse_news(section: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("📰") or stripped.startswith("**"):
            continue
        m = re.match(r"^[•\-\*]\s*(.+)$", stripped)
        if not m:
            continue
        headline = _strip_md(m.group(1))
        if not headline:
            continue
        items.append({"headline": headline, "source": "", "date": "", "url": ""})
    return items


def _parse_competitors(section: str) -> list[dict[str, str]]:
    """Parse the competitor comparison section into a list of dicts.
    The formatter produces blocks like:

        **Company Name** (SYMBOL)
        • Market Cap: ₹X Cr
        • PE Ratio: X
        • Profit Margin: X%
    """
    comps: list[dict[str, str]] = []
    current: dict[str, str] | None = None

    for line in section.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Header line with name + optional symbol in parens
        m = re.match(r"^\*\*([^*]+)\*\*\s*(?:\(([^)]+)\))?\s*$", stripped)
        if m and "Comparison" not in m.group(1) and "Competitors" not in m.group(1):
            if current:
                comps.append(current)
            current = {"name": _strip_md(m.group(1)), "ticker": (m.group(2) or "").strip()}
            continue
        # Metric line
        m2 = re.match(r"^[•\-\*]\s*([^:]+):\s*(.+)$", stripped)
        if m2 and current is not None:
            key = m2.group(1).strip().lower().replace(" ", "_")
            current[key] = m2.group(2).strip()
    if current:
        comps.append(current)
    return comps


def _parse_plain_paragraph(section: str) -> str:
    # Drop the header line, keep the rest joined.
    lines = section.splitlines()[1:]
    body = [line.strip() for line in lines if line.strip()]
    return "\n".join(body).strip()


def parse_agent_response(raw: str) -> dict[str, Any]:
    """Parse a formatted agent analysis response into a structured dict.

    Missing sections return empty strings / empty lists. Sections that
    the dashboard can source directly from `company_data` are included
    for completeness but may be ignored by the caller.
    """
    if not raw:
        return _empty_result()

    sections = _split_sections(raw)

    result: dict[str, Any] = _empty_result()

    if "selected" in sections:
        result["selected"] = _parse_selected(sections["selected"])
    if "snapshot" in sections:
        result["snapshot"] = _parse_snapshot(sections["snapshot"])
    if "business" in sections:
        result["businessOverview"] = _parse_business_overview(sections["business"])
    if "financials" in sections:
        result["financials"] = _parse_financials(sections["financials"])
    if "market" in sections:
        result["marketData"] = _parse_market_data(sections["market"])
    if "performance" in sections:
        result["pricePerformance"] = _parse_price_performance(sections["performance"])
    if "competitors" in sections:
        result["competitors"] = _parse_competitors(sections["competitors"])
    if "swot" in sections:
        result["swot"] = _parse_swot(sections["swot"])
    if "news" in sections:
        result["news"] = _parse_news(sections["news"])
    # Unified insight (new format). We strip the subtitle line
    # ("*Synthesized from expert market analysis…*") so the caller only gets
    # the prose body.
    if "unified" in sections:
        unified_body = _parse_plain_paragraph(sections["unified"])
        # Drop the italic subtitle line if present; it's decorative.
        _sub_re = re.compile(r"^\*[^*]+\*\s*\n?", re.MULTILINE)
        unified_body = _sub_re.sub("", unified_body, count=1).strip()
        result["unifiedInsight"] = unified_body

    # Legacy — only populated for analyses cached before the unified rollout.
    if "expert" in sections:
        result["expertOpinion"] = _parse_plain_paragraph(sections["expert"])
    if "screener" in sections:
        result["screenerSummary"] = _parse_plain_paragraph(sections["screener"])

    return result


def _empty_result() -> dict[str, Any]:
    return {
        "selected": {"name": "", "ticker": ""},
        "snapshot": {
            "companyName": "",
            "tickerSymbol": "",
            "exchange": "",
            "sector": "",
            "industry": "",
            "headquarters": "",
            "founded": "",
            "ceo": "",
            "employees": "",
            "website": "",
        },
        "businessOverview": "",
        "financials": {
            "incomeStatement": {},
            "balanceSheet": {},
            "cashFlow": {},
            "valuation": {},
            "margins": {},
        },
        "marketData": {},
        "pricePerformance": {"periods": [], "sevenDayHistory": []},
        "competitors": [],
        "swot": {"strengths": [], "weaknesses": [], "opportunities": [], "threats": []},
        "news": [],
        "unifiedInsight": "",
        "expertOpinion": "",
        "screenerSummary": "",
    }
