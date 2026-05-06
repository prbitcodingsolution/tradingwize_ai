# -*- coding: utf-8 -*-
"""
FinRobot — Plain English Formatter
===================================
Re-renders an existing `FinRobotReport` in a beginner-friendly "Plain
English View" that mirrors the spec in
`drawing_instruction/FINROBOT_PLAIN_ENGLISH_FORMAT.md`.

Golden rule (from the brief):
    Do NOT replace the existing expert format. Add the Plain English View
    as a toggleable second mode — this module is the generator for that
    second mode. Both views read from the SAME data object.

Entry point:
    format_plain_english_report(report, company_data, symbol, name) -> str

The returned string is HTML-flavoured markdown (uses `<div>` / `<span>`
so the colour-coded callouts & badges from the spec actually render).
Callers must pass `unsafe_allow_html=True` to `st.markdown(...)`.

All numerical extractions are best-effort — if a field is missing the
formatter falls back to a sensible default rather than crashing.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, List, Optional, Tuple

# ─────────────────────────────────────────────────────────────────────
#  Utility helpers (Section 3, 4, 5, 7 of the spec)
# ─────────────────────────────────────────────────────────────────────
def to_letter_grade(score: Optional[float]) -> Tuple[str, str]:
    """Pine-style numeric score → letter grade + colour.

    Mirrors the `toLetterGrade(score)` JS helper in the spec.
    """
    try:
        s = float(score) if score is not None else 0.0
    except Exception:
        s = 0.0
    if s >= 80:
        return ("A", "#2e7d32")
    if s >= 70:
        return ("B+", "#388e3c")
    if s >= 60:
        return ("B", "#f9a825")
    if s >= 50:
        return ("C", "#e65100")
    return ("D", "#c62828")


def format_inr(value: Optional[float]) -> str:
    """Indian numbering system formatter — ₹, lakh, crore, lakh-crore.

    Matches the `formatINR(value)` helper in the spec. Accepts numbers
    in raw rupees (i.e. absolute amounts) and scales them sensibly:

        3_130_000_000_000 → "₹3.13 lakh crore"
        484_860_000_000   → "₹48,486 crore"
        1_096.30          → "₹1,096.30"
    """
    if value is None:
        return "N/A"
    try:
        v = float(value)
    except Exception:
        return str(value)

    if v != v or v == float("inf") or v == float("-inf"):  # NaN / inf
        return "N/A"

    sign = "-" if v < 0 else ""
    v = abs(v)

    LAKH_CRORE = 1_00_00_00_00_000   # 1e12  (1 lakh crore)
    CRORE      = 1_00_00_000         # 1e7   (1 crore)
    LAKH       = 1_00_000            # 1e5   (1 lakh)

    if v >= LAKH_CRORE:
        return f"{sign}₹{v / LAKH_CRORE:.2f} lakh crore"
    if v >= CRORE:
        return f"{sign}₹{v / CRORE:,.0f} crore"
    if v >= LAKH:
        return f"{sign}₹{v / LAKH:,.1f} lakh"
    # Prices and small sums — standard Indian-grouped number
    return f"{sign}₹{_indian_group(v)}"


def _indian_group(v: float) -> str:
    """Indian thousands-grouping (2,34,567.89 style) using stdlib only."""
    neg = v < 0
    v = abs(v)
    i_part = int(v)
    frac = v - i_part
    s = str(i_part)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        # Insert a comma every 2 digits in the head, right-to-left
        chunks: list[str] = []
        while len(head) > 2:
            chunks.append(head[-2:])
            head = head[:-2]
        if head:
            chunks.append(head)
        grouped = ",".join(reversed(chunks)) + "," + tail
    else:
        grouped = s
    # Only attach decimals when the original value had a non-integer part
    # (so plain prices like 1,096 don't gain a spurious ".00").
    if frac > 1e-9:
        grouped += f".{int(round(frac * 100)):02d}"
    return ("-" if neg else "") + grouped


# ─────────────────────────────────────────────────────────────────────
#  Analogy banks  (Section 4 & 5 of the spec)
# ─────────────────────────────────────────────────────────────────────
BULL_ANALOGIES: List[Tuple[List[str], str]] = [
    (["home loan", "housing", "mortgage"],
     "If you own a lemonade stand and suddenly 15% more people show up every day, "
     "you make more money."),
    (["digital", "app", "yono", "technology", "platform", "online"],
     "It's like switching from sending letters by post (costly) to sending emails "
     "(almost free)."),
    (["dividend", "yield", "payout"],
     "Like your landlord paying YOU a small bonus every year just for living in "
     "the flat."),
    (["credit growth", "loan book", "lending"],
     "A bank that lends more earns more interest — like a shop that sells more "
     "stock every month."),
    (["margin", "profit", "efficiency", "cost-to-income"],
     "Imagine your bakery suddenly finding a flour supplier 20% cheaper. Your profit "
     "per loaf goes up without selling more bread."),
    (["institutional", "fii", "dii", "fund"],
     "When full-time fund managers — who research stocks all day — are buying, it "
     "usually means they see hidden value."),
    (["market share", "dominance", "largest", "biggest"],
     "Think of it like the only petrol station in a 50 km radius. Customers have "
     "to come to you."),
    (["earnings beat", "eps growth", "q3", "q2", "q1", "quarterly"],
     "Beating earnings expectations is like a student scoring higher than the class "
     "average — markets reward it with a higher 'grade' in price."),
]

BEAR_ANALOGIES: List[Tuple[List[str], str]] = [
    (["casa", "funding cost", "nim", "interest margin"],
     "You run a bakery. You normally get flour for ₹20/kg. Suddenly it's only "
     "available at ₹30/kg. Your profit on every loaf just shrank."),
    (["npa", "bad loan", "default", "provisioning", "asset quality"],
     "You lent ₹500 to a friend who lost his job and stopped answering your calls. "
     "You probably aren't getting that ₹500 back."),
    (["competition", "fintech", "private bank", "nbfc", "new entrant"],
     "A shiny new gym opened next door with a smoothie bar. The old gym still has "
     "the weights, but the new one looks cooler."),
    (["leverage", "debt", "d/e", "equity ratio", "borrowing"],
     "Borrowing money to invest can double your gains — but it can also double "
     "your losses if things go wrong."),
    (["regulatory", "rbi", "basel", "capital norm", "compliance"],
     "The government changes the rules of the game mid-match. The team that was "
     "winning might now be penalised."),
    (["macro", "gdp", "slowdown", "recession", "inflation", "economy"],
     "When the whole economy catches a cold, even healthy businesses start sneezing."),
    (["dilution", "share count", "equity dilution", "issued shares"],
     "Splitting a pizza into more slices doesn't make the pizza bigger — each slice "
     "just gets a little smaller."),
]

_GENERIC_BULL = (
    "When the fundamentals of a business improve, the stock price tends to follow — "
    "like a rising tide lifting all boats."
)
_GENERIC_BEAR = (
    "Markets punish uncertainty — when a known risk starts playing out, even a good "
    "stock can fall while the story gets re-assessed."
)


def get_analogy(text: str, bank: List[Tuple[List[str], str]], fallback: str) -> str:
    """Pick the first analogy whose keyword appears in `text` (case-insensitive)."""
    if not text:
        return fallback
    lower = text.lower()
    for keywords, analogy in bank:
        if any(k in lower for k in keywords):
            return analogy
    return fallback


# ─────────────────────────────────────────────────────────────────────
#  Sector-based peer defaults (Section 3 fallback)
# ─────────────────────────────────────────────────────────────────────
# Used when the fundamental agent's `peer_comparison` text doesn't expose
# numeric peer multiples. These are rough Indian-market medians — accurate
# enough for a relatable "shirt-shop" analogy.
SECTOR_PEER_DEFAULTS: List[Tuple[List[str], Tuple[float, float]]] = [
    (["bank", "financial services", "nbfc"], (17.5, 2.2)),
    (["insurance"],                          (22.0, 2.5)),
    (["information technology", "it ", "software", "technology"], (28.0, 5.5)),
    (["pharma", "healthcare", "drug"],       (30.0, 4.5)),
    (["fmcg", "consumer goods"],             (45.0, 8.0)),
    (["consumer", "retail"],                 (40.0, 6.0)),
    (["auto", "automobile"],                 (22.0, 3.5)),
    (["energy", "oil", "gas", "petroleum"],  (12.0, 1.5)),
    (["power", "utilities"],                 (18.0, 2.0)),
    (["metal", "steel", "mining"],           (10.0, 1.5)),
    (["telecom"],                            (25.0, 4.0)),
    (["cement", "construction"],             (22.0, 3.0)),
    (["real estate", "realty"],              (25.0, 2.0)),
    (["chemical"],                           (25.0, 3.5)),
    (["media", "entertainment"],             (22.0, 3.0)),
]

_DEFAULT_PEER_PE = 22.0
_DEFAULT_PEER_PB = 3.0


def _peer_multiples_from_text(text: str) -> Tuple[Optional[float], Optional[float]]:
    """Extract peer-average P/E and P/B from the fundamental agent's
    free-form `peer_comparison` / `valuation_commentary` text.

    Grabs the first "peer"/"average"/"median" context line containing a
    plausible multiple. Returns (peer_pe, peer_pb) — either may be None
    if parsing fails.
    """
    if not text:
        return (None, None)
    lower = text.lower()

    peer_pe: Optional[float] = None
    peer_pb: Optional[float] = None

    # Look for something like "peer average ~17.6" or "peer median pe 17.6"
    # or "peers pe 17.57". Numbers under 100 are accepted as multiples.
    m_pe = re.search(
        r"(?:peer|industry|sector|average|median)[^.]{0,60}?p\s*/?\s*e[^.]{0,40}?"
        r"(\d{1,2}(?:\.\d+)?)", lower)
    if m_pe:
        v = float(m_pe.group(1))
        if 3.0 <= v <= 80.0:
            peer_pe = v

    m_pb = re.search(
        r"(?:peer|industry|sector|average|median)[^.]{0,60}?p\s*/?\s*b[^.]{0,40}?"
        r"(\d{1,2}(?:\.\d+)?)", lower)
    if m_pb:
        v = float(m_pb.group(1))
        if 0.3 <= v <= 15.0:
            peer_pb = v

    return (peer_pe, peer_pb)


def _peer_multiples_for_sector(sector: str) -> Tuple[float, float]:
    if not sector:
        return (_DEFAULT_PEER_PE, _DEFAULT_PEER_PB)
    low = sector.lower()
    for keywords, (pe, pb) in SECTOR_PEER_DEFAULTS:
        if any(k in low for k in keywords):
            return (pe, pb)
    return (_DEFAULT_PEER_PE, _DEFAULT_PEER_PB)


# ─────────────────────────────────────────────────────────────────────
#  Field extraction (handles missing / malformed inputs gracefully)
# ─────────────────────────────────────────────────────────────────────
def _safe_getattr(obj: Any, *names: str, default: Any = None) -> Any:
    """Walk a dotted chain of attributes — short-circuit on None."""
    cur = obj
    for n in names:
        if cur is None:
            return default
        cur = getattr(cur, n, None)
    return cur if cur is not None else default


def _float_or_none(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except Exception:
        return None


def _extract_target_upside(snapshot_text: str) -> Tuple[Optional[float], Optional[float]]:
    """Pull (target_price, upside_pct) from the sentiment agent's
    `target_price_snapshot` — typically something like
    '₹1,200 target, ~8% upside from current ₹1,096.30'."""
    if not snapshot_text:
        return (None, None)
    # Accept both "1,200" and "1200" and plain "1200.5"
    t = re.search(r"₹\s*([\d,]+(?:\.\d+)?)\s*(?:target|tp|target price)", snapshot_text, re.I)
    target = None
    if t:
        try:
            target = float(t.group(1).replace(",", ""))
        except Exception:
            target = None
    u = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%\s*upside", snapshot_text, re.I)
    upside = None
    if u:
        try:
            upside = float(u.group(1))
        except Exception:
            upside = None
    return (target, upside)


def _extract_support_level(price_levels_text: str) -> Optional[float]:
    """Find a numeric support level in the reasoning agent's `price_levels`
    free-form paragraph — e.g. 'near-term support at ~₹1,030 (~5% downside)'.
    """
    if not price_levels_text:
        return None
    m = re.search(r"support[^.]{0,40}?₹\s*([\d,]+(?:\.\d+)?)", price_levels_text, re.I)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except Exception:
            return None
    return None


_COMPANY_ABBREVIATION_OVERRIDES = {
    "state bank of india": "SBI",
    "oil and natural gas corporation": "ONGC",
    "housing development finance corporation": "HDFC",
    "industrial credit and investment corporation of india": "ICICI",
    "life insurance corporation of india": "LIC",
    "national thermal power corporation": "NTPC",
    "bharat heavy electricals": "BHEL",
    "gas authority of india": "GAIL",
    "hindustan petroleum corporation": "HPCL",
    "bharat petroleum corporation": "BPCL",
    "indian oil corporation": "IOC",
    "mahindra and mahindra": "M&M",
    "tata consultancy services": "TCS",
}

_CORPORATE_SUFFIX_WORDS = {
    "limited", "ltd", "ltd.", "corporation", "corp", "corp.",
    "company", "co", "co.", "plc", "incorporated", "inc", "inc.",
    "pvt", "private",
}

_NAME_STOPWORDS = {"of", "and", "the", "for", "&"}


def _short_display_name(name: str, symbol: str) -> str:
    """Derive a concise, professional short form of the company.

    Rules (first match wins):
      1. A curated override table for well-known Indian conglomerates
         where the brand abbreviation differs from the NSE ticker
         (SBIN.NS → SBI, ONGC.NS → ONGC).
      2. Acronym built from the capitalised words of the company name
         — used when the acronym is 2–5 letters (covers SBI, TCS, HDFC,
         ICICI). "Limited / Corporation / Ltd" and stop-words like
         "of / and / the" are dropped before assembling the acronym.
      3. Fallback: the symbol with any '.NS' / '.BO' / '.BSE' suffix
         stripped — e.g. 'RELIANCE.NS' → 'RELIANCE'. Already-short
         tickers stay readable.
    """
    # 1. Override table — first try the full lower-cased name, then
    #    progressively-shorter prefixes (handles "... Limited").
    low_name = (name or "").lower().strip()
    if low_name:
        for key, short in _COMPANY_ABBREVIATION_OVERRIDES.items():
            if low_name.startswith(key):
                return short

    # 2. Acronym from capitalised words.
    if name:
        words = [w for w in re.split(r"\s+", name.strip()) if w]
        acronym_parts: list[str] = []
        for w in words:
            low = w.lower().strip(".,")
            if low in _NAME_STOPWORDS:
                continue
            if low in _CORPORATE_SUFFIX_WORDS:
                continue
            if w[:1].isalpha():
                acronym_parts.append(w[:1].upper())
        acronym = "".join(acronym_parts)
        if 2 <= len(acronym) <= 5:
            return acronym

    # 3. Fallback: strip exchange suffix from ticker.
    sym = (symbol or "").strip()
    for suffix in (".NS", ".BO", ".BSE", ".NSE"):
        if sym.upper().endswith(suffix):
            return sym[: -len(suffix)]
    return sym or name or ""


def _country_from_ticker(ticker: str) -> str:
    if not ticker:
        return "the country"
    t = ticker.upper()
    if t.endswith(".NS") or t.endswith(".BO"):
        return "India"
    if t.endswith(".L") or t.endswith(".LSE"):
        return "the UK"
    if "." not in t:
        return "the US"   # US tickers generally don't carry a suffix
    return "the country"


def _portfolio_allocation(beta: Optional[float]) -> Tuple[int, int]:
    """Return (min_rupees, max_rupees) per ₹1,00,000 based on the beta bucket."""
    if beta is None:
        return (4000, 6000)
    if beta > 1.0:
        return (3000, 5000)
    if beta < 0.5:
        return (5000, 7000)
    return (4000, 6000)


# ─────────────────────────────────────────────────────────────────────
#  Main entry point
# ─────────────────────────────────────────────────────────────────────
def format_plain_english_report(
    report,                  # FinRobotReport (typed loosely to avoid circular import)
    company_data,            # models.CompanyData
    symbol: str,
    name: str,
    short_name: Optional[str] = None,
) -> str:
    """Build the Plain English View as HTML-flavoured markdown.

    `short_name` is the concise ticker-style handle reused after the
    first full-name mention (e.g. 'SBI' for State Bank of India). When
    omitted it is derived via `_short_display_name`.
    """
    reasoning = getattr(report, "reasoning", None)
    fundamental = getattr(report, "fundamental", None)
    sentiment = getattr(report, "sentiment", None)

    # Short handle reused after the first full-name mention. Keeping one
    # concise label everywhere avoids the "State Bank of India" / "SBI"
    # /"SBIN.NS" flip-flop that reads as inconsistent in a research note.
    short = (short_name or "").strip() or _short_display_name(name, symbol)

    # ──── Pull all primitives with safe defaults ────
    recommendation = (getattr(reasoning, "recommendation", "") or "Hold").strip() or "Hold"
    confidence     = (getattr(reasoning, "confidence", "") or "Medium").strip() or "Medium"
    time_horizon   = (getattr(reasoning, "time_horizon", "") or "Medium-term").strip()

    # --- Financials ---
    pe_ratio        = _float_or_none(_safe_getattr(company_data, "financials", "pe_ratio"))
    pb_ratio        = _float_or_none(_safe_getattr(company_data, "financials", "pb_ratio"))
    cash_balance    = _float_or_none(_safe_getattr(company_data, "financials", "cash_balance"))
    total_debt      = _float_or_none(_safe_getattr(company_data, "financials", "total_debt"))
    dividend_yield  = _float_or_none(_safe_getattr(company_data, "financials", "dividend_yield"))
    eps             = _float_or_none(_safe_getattr(company_data, "financials", "eps"))
    beta            = _float_or_none(_safe_getattr(company_data, "market_data", "beta"))
    current_price   = _float_or_none(_safe_getattr(company_data, "market_data", "current_price"))
    sector          = _safe_getattr(company_data, "snapshot", "sector", default="") or ""

    # --- Peer comparables (for Section 3 table) ---
    peer_pe_parsed, peer_pb_parsed = _peer_multiples_from_text(
        (getattr(fundamental, "peer_comparison", "") or "")
        + " "
        + (getattr(fundamental, "valuation_commentary", "") or "")
    )
    sector_pe, sector_pb = _peer_multiples_for_sector(sector)
    peer_pe = peer_pe_parsed if peer_pe_parsed is not None else sector_pe
    peer_pb = peer_pb_parsed if peer_pb_parsed is not None else sector_pb

    # --- Scores ---
    val_score = _float_or_none(getattr(fundamental, "valuation_score", None)) or 0.0
    fh_score  = _float_or_none(getattr(fundamental, "financial_health_score", None)) or 0.0
    gr_score  = _float_or_none(getattr(fundamental, "growth_score", None)) or 0.0
    overall   = _float_or_none(getattr(reasoning, "final_score", None)) or 0.0

    # --- Price targets ---
    target_price, upside_pct = _extract_target_upside(
        getattr(sentiment, "target_price_snapshot", "") or ""
    )
    support_level = _extract_support_level(
        getattr(reasoning, "price_levels", "") or ""
    )
    # Fallback: 5% below current for support
    if support_level is None and current_price is not None:
        support_level = round(current_price * 0.95, 0)
    # Fallback: +10% above current for target if the agent didn't emit one
    if target_price is None and current_price is not None:
        target_price = round(current_price * 1.10, 0)
    if upside_pct is None and target_price is not None and current_price:
        upside_pct = (target_price - current_price) / current_price * 100.0

    # --- Bull / bear arrays ---
    bull_points = list(getattr(reasoning, "bull_case", []) or [])[:3]
    bear_points = list(getattr(reasoning, "bear_case", []) or [])[:3]
    if not bear_points:
        bear_points = list(getattr(fundamental, "key_risks", []) or [])[:3]

    # ──── Now build the markdown ────
    out: list[str] = []

    out.append(_section_header_banner(name, short))
    out.append(_section_1_one_minute(recommendation, confidence, time_horizon))
    out.append(_section_2_what_is_this(name, short, company_data, fundamental, reasoning))
    out.append(_section_3_good_deal(
        short, current_price, eps,
        pe_ratio, peer_pe, pb_ratio, peer_pb,
        cash_balance, total_debt,
    ))
    out.append(_section_4_bull(bull_points))
    out.append(_section_5_bear(bear_points))
    out.append(_section_6_who_should_buy(
        short, dividend_yield, _country_from_ticker(symbol)
    ))
    out.append(_section_7_scorecard(val_score, fh_score, gr_score, beta, bear_points))
    out.append(_section_8_verdict_and_tip(
        recommendation, current_price, target_price, upside_pct,
        time_horizon, dividend_yield, beta, support_level, short,
    ))
    out.append(_section_9_data_sources(company_data, fundamental, sentiment))

    return "\n\n".join(out)


# ─────────────────────────────────────────────────────────────────────
#  Sections
# ─────────────────────────────────────────────────────────────────────
def _section_header_banner(name: str, short: str) -> str:
    # First-and-only full-name mention; every section after this uses the
    # short handle for professional consistency.
    return (
        f"## 🏦 Should You Buy {name} ({short}) Stock? "
        f"<span style='font-size:0.9rem;color:#666'>(Plain English Version)</span>"
    )


def _section_1_one_minute(recommendation: str, confidence: str, time_horizon: str) -> str:
    """Pastel-green / teal / orange / red callout with DARK text.

    Cascade-hardening trick: every text element carries both `color` and
    `-webkit-text-fill-color` with `!important`. Streamlit's dark-theme
    stylesheet overrides `color` on most elements but doesn't touch
    `-webkit-text-fill-color`, so the dark fill "leaks through" and the
    text stays legible in both themes.
    """
    rec_norm = recommendation.lower().strip()
    if "strong buy" in rec_norm:
        answer = ("Probably <b>yes</b>, if you are patient and don't need the money "
                  "for at least a year. It's not a get-rich-quick lottery ticket — "
                  "think of it as buying a sturdy, reliable bicycle when everyone "
                  "else is overpaying for flashy sports cars.")
        bg, border = "#d7eedd", "#1b5e20"     # light green 100-ish / green 900 border
        badge_bg, badge_fg = "#1b5e20", "#ffffff"
        text_color = "#0d3a12"                 # deep forest green (reads on green bg)
        badge_label = "STRONG BUY"
    elif "buy" in rec_norm:
        answer = ("Probably <b>yes</b>, especially if you have a medium-term horizon. "
                  "The stock looks fairly priced and has solid growth drivers, but "
                  "don't expect overnight fireworks.")
        bg, border = "#d6ece9", "#004d40"     # light teal / teal 900 border
        badge_bg, badge_fg = "#004d40", "#ffffff"
        text_color = "#0a2e2a"
        badge_label = "BUY"
    elif "sell" in rec_norm:
        answer = ("The current data suggests the <b>risks outweigh the rewards</b> at "
                  "today's price. Consider other options unless you have a very "
                  "specific reason to hold.")
        bg, border = "#fadbd8", "#8e0000"     # light red / deep red border
        badge_bg, badge_fg = "#8e0000", "#ffffff"
        text_color = "#3a0a0a"
        badge_label = "SELL"
    else:
        answer = ("<b>Wait and watch.</b> The stock isn't screaming cheap or expensive "
                  "right now. If you already own it, sit tight. If you don't, there's "
                  "no urgent rush to buy today.")
        bg, border = "#fce8d5", "#bf360c"     # light orange / deep-orange border
        badge_bg, badge_fg = "#bf360c", "#ffffff"
        text_color = "#3a1a05"
        badge_label = "HOLD"

    # Build the per-text-element style once so every span is identical.
    # Using BOTH `color` and `-webkit-text-fill-color` with `!important`
    # wins the cascade even when Streamlit's dark-theme CSS forces white
    # on `.stMarkdown p` — because `-webkit-text-fill-color` is a
    # separate property most theme stylesheets don't touch.
    txt_css   = f"color:{text_color} !important;-webkit-text-fill-color:{text_color} !important"
    label_css = f"color:{text_color}cc !important;-webkit-text-fill-color:{text_color}cc !important"

    badge = (
        f"<span style='background:{badge_bg};color:{badge_fg} !important;"
        f"-webkit-text-fill-color:{badge_fg} !important;"
        f"padding:4px 12px;border-radius:20px;font-weight:800;"
        f"font-size:0.85rem;letter-spacing:0.4px;"
        f"box-shadow:0 1px 2px rgba(0,0,0,0.15)'>{badge_label}</span>"
    )
    meta = (
        f"<span style='{label_css}'>&nbsp;&nbsp;Confidence: "
        f"<b style='{txt_css}'>{confidence}</b></span>"
        f"<span style='{label_css}'>&nbsp;&nbsp;Horizon: "
        f"<b style='{txt_css}'>{time_horizon}</b></span>"
    )

    callout = (
        f"<div style='background:{bg} !important;border-left:6px solid {border};"
        f"padding:18px 22px;border-radius:8px;margin:0.8rem 0;line-height:1.65;"
        f"{txt_css};"
        f"box-shadow:0 1px 3px rgba(0,0,0,0.08)'>"
        f"<div style='margin-bottom:10px;{label_css};font-weight:600;font-size:0.95rem'>"
        f"<span style='{label_css}'>Recommendation:</span> {badge} {meta}"
        f"</div>"
        f"<div style='font-size:1.05rem;{txt_css};font-weight:500'>"
        f"<span style='{txt_css}'>⏱️ <b style='{txt_css}'>The One-Minute Answer:</b> "
        f"{answer}</span>"
        f"</div>"
        f"</div>"
    )
    return callout


def _section_2_what_is_this(name, short, company_data, fundamental, reasoning) -> str:
    """Simplified company description from moat_assessment + summary,
    wrapped in a light-blue info callout so the section stands out from
    the plain-text body of the report.
    """
    sector = _safe_getattr(company_data, "snapshot", "sector", default="") or "diversified"
    industry = _safe_getattr(company_data, "snapshot", "industry", default="") or ""
    moat = (getattr(fundamental, "moat_assessment", "") or "").strip()
    summary = (getattr(reasoning, "summary", "") or "").strip()

    description = moat or summary
    if description:
        sentences = re.split(r"(?<=[.!?])\s+", description)
        description = " ".join(sentences[:3]).strip()
    else:
        description = (
            f"{name} is a {industry or sector} company listed in India. "
            f"It's a well-known name in its sector and has been publicly traded "
            f"for years. Detailed company context isn't available in this report."
        )

    # Light-blue callout, same cascade-hardening trick as Section 1.
    text_color = "#0a2e5c"   # deep navy — readable on light blue
    txt_css = f"color:{text_color} !important;-webkit-text-fill-color:{text_color} !important"

    head = f"### 📋 What Exactly Is {short}?"
    body = (
        f"<div style='background:#e3f2fd !important;border-left:5px solid #0d47a1;"
        f"padding:14px 18px;border-radius:6px;margin:0.4rem 0 0.8rem 0;line-height:1.6;"
        f"{txt_css};"
        f"box-shadow:0 1px 3px rgba(0,0,0,0.06)'>"
        f"<span style='{txt_css};font-size:1rem'>{description}</span>"
        f"</div>"
    )
    return head + "\n\n" + body


def _section_3_good_deal(
    short: str,
    current_price: Optional[float],
    eps: Optional[float],
    pe_ratio: Optional[float],
    peer_pe: float,
    pb_ratio: Optional[float],
    peer_pb: float,
    cash_balance: Optional[float],
    total_debt: Optional[float],
) -> str:
    # Shirt-shop analogy: peer-implied price vs current-implied price.
    analogy_line = ""
    if eps and pe_ratio and current_price:
        current_implied = eps * pe_ratio
        peer_implied = eps * peer_pe
        analogy_line = (
            f"> Imagine you are shopping for a branded shirt. You see the exact "
            f"same quality shirt being sold in two shops next to each other. "
            f"One shop is selling it for {format_inr(peer_implied)}. The other "
            f"shop is selling it for {format_inr(current_implied)}.\n"
            f"> \n"
            f"> That's basically **{short}** right now.\n"
        )
    elif pe_ratio and peer_pe:
        analogy_line = (
            f"> Compared to peers, {short} trades at a P/E of **{pe_ratio:.1f}** "
            f"while others in its space trade around **{peer_pe:.1f}**. "
            f"You're getting the same kind of profits at a cheaper price.\n"
        )

    # Cash-to-debt coverage
    cash_cov = None
    if cash_balance is not None and total_debt and total_debt > 0:
        cash_cov = min(100, round((cash_balance / total_debt) * 100 / 5) * 5)  # round to nearest 5%
    cash_cov_txt = f"{cash_cov}%" if cash_cov is not None else "a healthy portion"

    # Table rows
    discount_cell = (
        f"You are paying <b>₹{pe_ratio:.2f}</b> for every ₹1 of profit "
        f"{short} makes. For comparable companies, people are paying "
        f"<b>₹{peer_pe:.2f}</b> for the same ₹1 of profit. "
        f"You are getting the profit cheaper."
        if pe_ratio else
        "P/E ratio not available for comparison."
    )
    price_tag_cell = (
        f"If the company was broken up and sold off today, each share "
        f"would be worth about <b>₹{pb_ratio:.2f}</b> in assets. You are "
        f"paying close to that breakup value. Peers trade at <b>₹{peer_pb:.2f}</b>. "
        f"You aren't overpaying."
        if pb_ratio else
        "P/B ratio not available."
    )
    cash_cell = (
        f"{short} has <b>{format_inr(cash_balance)}</b> in pure cash. "
        f"That's enough to pay off nearly <b>{cash_cov_txt}</b> of what it owes. "
        f"A serious safety net."
        if cash_balance else
        "Cash balance data not available."
    )

    table = (
        "| Concept | Fancy Finance Term | What It Actually Means |\n"
        "|---|---|---|\n"
        f"| 🎯 The \"Discount\" | P/E Ratio (Price to Earnings) | {discount_cell} |\n"
        f"| 🏷️ The \"Price Tag\" | P/B Ratio (Price to Book) | {price_tag_cell} |\n"
        f"| 💰 The \"Emergency Fund\" | Cash Balance | {cash_cell} |"
    )

    head = "### 💰 Why Is This Stock a \"Good Deal\" Right Now?"
    return head + "\n\n" + (analogy_line or "") + "\n" + table


def _section_4_bull(bull_points: List[str]) -> str:
    out = ["### 📈 Why Might the Price Go Up? (The Good Stuff)"]
    if not bull_points:
        out.append("_No bullish drivers were emitted by the reasoning agent._")
        return "\n\n".join(out)
    for i, pt in enumerate(bull_points, 1):
        headline = _first_clause(pt)
        analogy = get_analogy(pt, BULL_ANALOGIES, _GENERIC_BULL)
        out.append(_analogy_card(i, headline, pt, analogy, is_bull=True))
    return "\n\n".join(out)


def _section_5_bear(bear_points: List[str]) -> str:
    out = ["### ⚠️ What Could Go Wrong? (The Scary Stuff You Need to Know)"]
    if not bear_points:
        out.append("_No significant risks were flagged by the reasoning agent._")
        return "\n\n".join(out)
    for i, pt in enumerate(bear_points, 1):
        headline = _first_clause(pt)
        analogy = get_analogy(pt, BEAR_ANALOGIES, _GENERIC_BEAR)
        out.append(_analogy_card(i, headline, pt, analogy, is_bull=False))
    return "\n\n".join(out)


def _analogy_card(idx: int, headline: str, full_point: str, analogy: str, is_bull: bool) -> str:
    emoji = "💡" if is_bull else "🧠"
    # Light pastel green for bull cards, light pastel red for bear cards.
    if is_bull:
        bg, border = "#e8f5e9", "#2e7d32"      # green 50 / green 800
        text_color = "#0d3a12"
    else:
        bg, border = "#fdecea", "#c62828"      # red 50 / red 700
        text_color = "#3a0a0a"
    # Cascade-hardening: both `color` and `-webkit-text-fill-color` pinned.
    txt_css = (
        f"color:{text_color} !important;"
        f"-webkit-text-fill-color:{text_color} !important"
    )
    return (
        f"**{idx}. {headline}**  \n"
        f"{full_point.strip()}  \n"
        f"<div style='background:{bg} !important;border-left:4px solid {border};"
        f"padding:10px 14px;margin:6px 0;font-style:italic;font-size:0.95rem;"
        f"border-radius:0 6px 6px 0;{txt_css};"
        f"box-shadow:0 1px 2px rgba(0,0,0,0.05)'>"
        f"<span style='{txt_css}'>{emoji} "
        f"<b style='{txt_css}'>Analogy:</b> {analogy}</span></div>"
    )


def _first_clause(text: str, max_words: int = 10) -> str:
    """Pick the first sentence / clause as a compact headline.

    Skips decimal points (e.g. "22.5%") so the headline doesn't get cut
    mid-number; only real sentence-ending punctuation (period followed
    by whitespace + capital, exclamation, or question mark) breaks it.
    """
    if not text:
        return ""
    t = text.strip()
    # Real sentence boundary = [.!?] followed by whitespace-then-uppercase
    # or end-of-string. This tolerates "22.5%" / "Rs.1,096.30" without
    # mistaking them for sentence ends.
    m = re.match(r"(.+?[.!?])(?:\s+[A-Z]|$)", t)
    if m:
        cand = m.group(1).rstrip(".!?").strip()
    else:
        # Fallback: first comma past ~6 words, else the whole string.
        parts = t.split(",")
        cand = parts[0].strip()
        if len(cand.split()) < 6 and len(parts) > 1:
            cand = (cand + "," + parts[1]).strip()
    # Hard cap on length so the headline stays a headline.
    words = cand.split()
    if len(words) > max_words:
        cand = " ".join(words[:max_words]) + "…"
    # Only upper-case the first letter (preserve internal acronyms).
    return cand[:1].upper() + cand[1:] if cand else t


def _section_6_who_should_buy(short: str, dividend_yield: Optional[float],
                              country: str) -> str:
    div_txt = f"{dividend_yield:.1f}%" if dividend_yield else "a small"
    return (
        "### 🤔 Who Should Buy This Stock?\n\n"
        f"| You SHOULD buy {short} if... | You should NOT buy {short} if... |\n"
        "|---|---|\n"
        f"| ✅ You want a safe, reliable stock for the long term. | ❌ You want to double your money in a month. |\n"
        f"| ✅ You believe {country}'s economy will keep growing. | ❌ You need this money back in less than 6 months. |\n"
        f"| ✅ You like earning a {div_txt} dividend every year. | ❌ You panic when stock prices drop 10% temporarily. |"
    )


def _section_7_scorecard(val: float, health: float, growth: float,
                         beta: Optional[float], bear_points: List[str]) -> str:
    val_g, _ = to_letter_grade(val)
    h_g, _   = to_letter_grade(health)
    gr_g, _  = to_letter_grade(growth)

    def _val_txt(g):
        if g in ("A", "B+"): return "Yes, it's on sale compared to peers."
        if g == "B":         return "Fairly priced — not cheap, not expensive."
        return "A bit pricey right now."

    def _h_txt(g):
        if g in ("A", "B+"): return "Strong balance sheet and solid cash reserves."
        if g == "B":         return "Decent financial health, some debt to keep an eye on."
        return "Higher financial risk — tread carefully." 

    def _gr_txt(g):
        if g in ("A",):        return "Growing fast — strong upside ahead."
        if g in ("B+", "B"):   return "Steady, reliable growth. Not explosive."
        return "Growth is slow — be patient."

    # Risk band from beta
    if beta is None:
        risk_level = "Medium"
    elif beta < 0.5:
        risk_level = "Low–Medium"
    elif beta <= 1.0:
        risk_level = "Medium"
    else:
        risk_level = "Medium–High"

    # Keep original casing on the top-risk phrase — acronyms like CASA /
    # NIM / NPA must stay upper-case for the line to read correctly.
    top_risk_phrase = _first_clause(bear_points[0], max_words=8) if bear_points else "general market conditions"
    # Drop a trailing period if _first_clause included one (rare) — we add
    # our own after the clause.
    top_risk_phrase = top_risk_phrase.rstrip(".").rstrip("…")
    risk_explanation = f"Main risk: {top_risk_phrase}. Monitor the quarterly results."

    return (
        "### 📊 The Final \"Normal Human\" Scorecard\n\n"
        "| What We Looked At | Simple Grade | Explanation |\n"
        "|---|---|---|\n"
        f"| Current Price (Is it cheap?) | **{val_g}** | {_val_txt(val_g)} |\n"
        f"| Safety (Will it vanish?) | **{h_g}** | {_h_txt(h_g)} |\n"
        f"| Growth (Will it get bigger?) | **{gr_g}** | {_gr_txt(gr_g)} |\n"
        f"| Risk (What can hurt me?) | **{risk_level}** | {risk_explanation} |"
    )


def _section_9_data_sources(company_data, fundamental, sentiment) -> str:
    """Compact 'Data Sources' footer.

    Institutional readers expect every number to be traceable. We list
    the real pipelines this report draws from (yfinance, screener.in,
    Tavily news search, etc.) plus a generated-on timestamp. This is a
    transparency signal, not a bibliography — keep it discreet.
    """
    from datetime import datetime

    sources: list[str] = [
        "Market & financial data: <b>yfinance</b> (NSE/BSE feed)",
        "Fundamentals & peer comparables: <b>screener.in</b>",
        "News & future-outlook context: <b>Tavily</b> web search + LLM summarisation",
    ]

    # Surface sentiment inputs only if the report actually carried them.
    sent_snapshot = (getattr(sentiment, "target_price_snapshot", "") or "").strip()
    if sent_snapshot:
        sources.append("Analyst target / upside snapshot: future-outlook agent (Tavily-backed)")

    if getattr(fundamental, "peer_comparison", ""):
        sources.append("Peer multiples: fundamental agent (sector-cohort benchmarks)")

    # FII/DII flow block is wired into the reasoning agent input — hint at
    # that only when we can see the institutional-holding fields populated.
    mkt = _safe_getattr(company_data, "market_data")
    if (_float_or_none(getattr(mkt, "fii_holding", None)) is not None or
            _float_or_none(getattr(mkt, "dii_holding", None)) is not None):
        sources.append("Institutional flow (FII / DII holdings): NSE disclosure feed")

    stamp = datetime.now().strftime("%d %b %Y")

    text_color = "#444444"
    accent     = "#555555"
    txt_css = f"color:{text_color} !important;-webkit-text-fill-color:{text_color} !important"

    bullets = "".join(
        f"<li style='{txt_css};margin-bottom:2px'>{s}</li>" for s in sources
    )

    return (
        f"### 📚 Data Sources\n\n"
        f"<div style='background:#f5f5f5 !important;border-left:3px solid {accent};"
        f"padding:10px 14px;border-radius:4px;margin:0.5rem 0;font-size:0.88rem;"
        f"line-height:1.5;{txt_css}'>"
        f"<ul style='margin:0 0 4px 18px;padding:0;{txt_css}'>{bullets}</ul>"
        f"<div style='margin-top:6px;font-size:0.82rem;{txt_css};opacity:0.85'>"
        f"Report generated {stamp}. Figures are point-in-time; verify against "
        f"the primary source before trading."
        f"</div></div>"
    )


def _risk_reward_line(
    current_price: Optional[float],
    upside_pct: Optional[float],
    stop_loss: Optional[float],
) -> Optional[str]:
    """Build a one-line Risk-Reward summary: '≈1.1:1 (8% upside vs 7% downside)'.

    Returns None when we lack the inputs to compute it — the caller
    simply omits the line rather than printing a placeholder.
    """
    if current_price is None or upside_pct is None or stop_loss is None:
        return None
    if current_price <= 0 or stop_loss <= 0 or stop_loss >= current_price:
        # Stop-loss above / at current price means there's no measurable
        # downside from this level — skip rather than print a negative ratio.
        return None
    downside_pct = (current_price - stop_loss) / current_price * 100.0
    if downside_pct <= 0.1:
        return None
    ratio = upside_pct / downside_pct
    return (
        f"**Risk-Reward Ratio:** ~{ratio:.1f}:1 "
        f"(base-case upside {upside_pct:.1f}% vs support-level downside "
        f"~{downside_pct:.1f}%)."
    )


def _section_8_verdict_and_tip(
    recommendation: str,
    current_price: Optional[float],
    target_price: Optional[float],
    upside_pct: Optional[float],
    time_horizon: str,
    dividend_yield: Optional[float],
    beta: Optional[float],
    stop_loss: Optional[float],
    short: str,
) -> str:
    investor_type = {
        "strong buy": "Patient Long-Term",
        "buy":        "Growth-Oriented",
        "hold":       "Conservative",
        "sell":       "Risk-Averse",
    }
    type_label = investor_type.get(recommendation.lower().strip(), "Balanced")

    # Verdict block
    verdict_lines = [f"### ✅ Verdict\n",
                     f"**{recommendation} for {type_label} Investors.**\n"]
    if current_price is not None and target_price is not None:
        upside_txt = f" (~{upside_pct:.0f}% gain)" if upside_pct is not None else ""
        div_txt = (
            f", plus you earn the **{dividend_yield:.1f}%** dividend along the way."
            if dividend_yield else "."
        )
        verdict_lines.append(
            f"Expected Result: Price moves from **{format_inr(current_price)}** → "
            f"**{format_inr(target_price)}** in the next **{time_horizon}**"
            f"{upside_txt}{div_txt}"
        )

    # Risk-Reward Ratio — derived from the same upside and the
    # downside implied by the support/stop-loss level. Institutional
    # readers expect this explicit ratio, not just the two sides.
    rr_line = _risk_reward_line(current_price, upside_pct, stop_loss)
    if rr_line:
        verdict_lines.append(rr_line)

    # Pro-tip box — light blue pastel with deep-navy text, using the
    # same `color` + `-webkit-text-fill-color` cascade-hardening trick
    # so dark themes can't over-paint the body text to white.
    mn, mx = _portfolio_allocation(beta)
    stop_txt = format_inr(stop_loss) if stop_loss else "the support level"
    text_color = "#0a2e5c"      # deep navy, readable on light blue
    heading_color = "#0d3c61"   # slightly deeper blue for the heading accent
    txt_css  = f"color:{text_color} !important;-webkit-text-fill-color:{text_color} !important"
    head_css = f"color:{heading_color} !important;-webkit-text-fill-color:{heading_color} !important"
    tip = (
        f"<div style='background:#e3f2fd !important;border-left:5px solid #0d47a1;"
        f"padding:16px 20px;border-radius:6px;margin:1rem 0;{txt_css};"
        f"box-shadow:0 1px 3px rgba(0,0,0,0.06)'>"
        f"<div style='font-size:1.05rem;font-weight:800;margin-bottom:6px;{head_css}'>"
        f"<span style='{head_css}'>💡 Pro Tip for Normal Humans</span></div>"
        f"<div style='line-height:1.6;{txt_css};font-weight:500'>"
        f"<span style='{txt_css}'>Don't put all your eggs in one basket. If your "
        f"total portfolio is <b style='{txt_css}'>₹1,00,000</b>, putting "
        f"<b style='{txt_css}'>₹{mn:,}–₹{mx:,}</b> in "
        f"<b style='{txt_css}'>{short}</b> is a smart, balanced move."
        f"<br><br>⚠️ <b style='{txt_css}'>Stop-Loss Warning:</b> "
        f"If the price drops below <b style='{txt_css}'>{stop_txt}</b>, "
        f"something may have gone seriously wrong. That's the time to "
        f"reconsider — not panic, but definitely review."
        f"</span></div></div>"
    )

    return "\n".join(verdict_lines) + "\n\n" + tip


# ─────────────────────────────────────────────────────────────────────
#  CLI smoke test
# ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Minimal mock objects so we can eyeball the output without DB access.
    class _Obj:
        def __init__(self, **kw): self.__dict__.update(kw)

    company = _Obj(
        name="State Bank of India", symbol="SBIN.NS",
        snapshot=_Obj(sector="Financial Services", industry="Banks"),
        financials=_Obj(
            pe_ratio=12.4, pb_ratio=1.71, eps=91.9,
            cash_balance=3_130_000_000_000, total_debt=6_850_000_000_000,
            dividend_yield=1.43,
        ),
        market_data=_Obj(current_price=1096.30, beta=0.46),
    )
    report = _Obj(
        reasoning=_Obj(
            recommendation="Strong Buy", confidence="High", time_horizon="12–18 months",
            final_score=70.3,
            summary="SBI is the largest Indian bank with extensive reach...",
            bull_case=[
                "Retail home-loan book expanding 15% YoY in FY25-26, adding interest-earning assets.",
                "YONO digital platform reaches 90 million users, lowering cost-to-income ratio.",
                "Net-profit margin projected to expand from 22.5% to 29.5% by FY 2029.",
            ],
            bear_case=[
                "CASA ratio decline may raise funding costs and compress net interest margin.",
                "Asset-quality deterioration in MSME and unsecured retail segments could increase provisioning.",
                "Intensifying competition from NBFCs and fintechs could erode loan-growth rates.",
            ],
            price_levels="near-term support at ~₹1,030 with resistance at ₹1,150",
        ),
        fundamental=_Obj(
            valuation_score=85.0, financial_health_score=65.0, growth_score=60.0,
            overall_fundamental_score=70.5,
            moat_assessment="SBI benefits from an extensive branch network, "
                            "a dominant brand, and government-backed ownership.",
            peer_comparison="Peer P/E around 17.6, peer P/B around 2.2.",
            valuation_commentary="",
            key_risks=["High debt-to-equity ratio"],
        ),
        sentiment=_Obj(
            target_price_snapshot="₹1,200 target, ~8% upside from current ₹1,096.30"
        ),
    )
    md = format_plain_english_report(report, company, "SBIN.NS", "State Bank of India")
    print(md)
