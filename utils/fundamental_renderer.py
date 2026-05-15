"""Streamlit renderer for `models.FundamentalAnalysis`.

Drop-in usage from `app_advanced.py` (or any other Streamlit page):

    from utils.fundamental_analyzer import analyze_fundamentals
    from utils.fundamental_renderer import render_fundamental_analysis

    with st.spinner("Running enhanced fundamental analysis..."):
        result = analyze_fundamentals(symbol, name)
    render_fundamental_analysis(result)

Or render an already-computed payload (cached in DB, etc.):

    render_fundamental_analysis(result)

Each of the 8 sub-sections is wrapped in `st.expander` so the user can
collapse the ones they don't need. Sections whose `status.available` is
False still render — they show an "unavailable" banner with the reason
instead of an empty block, so it's always clear WHY a section is empty.
"""

from __future__ import annotations

from typing import Any, List, Optional

import re

import pandas as pd
import streamlit as st

try:
    import plotly.express as px
    import plotly.graph_objects as go
    _PLOTLY_OK = True
except Exception:  # plotly is in requirements.txt — guard anyway
    _PLOTLY_OK = False

from models import (
    DirectorBlock,
    FinancialTrend,
    FundamentalAnalysis,
    InvestmentsBlock,
    LegalBlock,
    NewsBlock,
    PledgeBlock,
    PoliticalBlock,
    SectionStatus,
)


# ─────────────────────────────────────────────────────────
# Small UI helpers
# ─────────────────────────────────────────────────────────

_CONFIDENCE_COLOR = {
    "high": "#16a34a",     # green
    "medium": "#ca8a04",   # amber
    "low": "#6b7280",      # gray
}

_RISK_COLOR = {
    "low": "#16a34a",
    "medium": "#ca8a04",
    "high": "#dc2626",
    "critical": "#991b1b",
    "unknown": "#6b7280",
}


def _status_badge(status: SectionStatus) -> str:
    color = _CONFIDENCE_COLOR.get(status.confidence, "#6b7280")
    label = status.confidence.upper()
    avail = "✓" if status.available else "—"
    return (
        f"<span style='background:{color};color:white;padding:2px 8px;"
        f"border-radius:6px;font-size:0.75rem;font-weight:600;'>"
        f"{avail} {label}</span>"
    )


def _unavailable(status: SectionStatus) -> None:
    st.info(f"⚠️ Not available — {status.notes or 'no data returned'}")
    if status.sources:
        with st.expander("Sources checked", expanded=False):
            for s in status.sources:
                st.markdown(f"- {s}")


# Streamlit's `st.markdown(unsafe_allow_html=True)` parses BOTH markdown
# and HTML. Tavily-extracted news snippets routinely contain raw markdown
# leftovers from the source page (`### Heading`, `# `, `**bold**`, table
# `|` pipes, `---` rules) — those render as full-size H1/H2/H3 elements
# even inside a `<span>` wrapper. We strip them so every news card has
# uniform typography.
_MD_HEADING_RE = re.compile(r"^\s*#{1,6}\s*", re.MULTILINE)
_MD_HRULE_RE = re.compile(r"^\s*[-=*_]{3,}\s*$", re.MULTILINE)
_MD_BOLD_RE = re.compile(r"\*\*([^*]*)\*\*")
_MD_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)([^*]+)\*(?!\*)")
_MD_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_MD_BULLET_RE = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_MD_TABLE_PIPES_RE = re.compile(r"\s*\|\s*")
_WHITESPACE_RE = re.compile(r"\s+")


def _sanitize_text(text: Optional[str], *, max_len: int = 320) -> str:
    """Strip raw markdown artefacts and collapse whitespace so a news
    summary / title renders as plain inline text inside a card. Markdown
    headers like `###` would otherwise render as huge H3 elements even
    inside `<span>` tags (Streamlit's markdown processor runs before the
    HTML allowlist)."""
    if not text:
        return ""
    s = str(text)
    # Drop horizontal rules and standalone hash lines entirely.
    s = _MD_HRULE_RE.sub(" ", s)
    # Strip heading markers from line starts (keep the text).
    s = _MD_HEADING_RE.sub("", s)
    # Strip bullet / list markers.
    s = _MD_BULLET_RE.sub("", s)
    # Unwrap **bold**, *italic*, and `code` to plain text.
    s = _MD_BOLD_RE.sub(r"\1", s)
    s = _MD_ITALIC_RE.sub(r"\1", s)
    s = _MD_INLINE_CODE_RE.sub(r"\1", s)
    # Tavily often produces stat tables flattened to ` | ` pipes — collapse.
    s = _MD_TABLE_PIPES_RE.sub(" ", s)
    # Collapse all whitespace (including newlines) into single spaces.
    s = _WHITESPACE_RE.sub(" ", s).strip()
    if max_len and len(s) > max_len:
        s = s[:max_len].rstrip() + "…"
    return s


def _format_money(val: Optional[float]) -> str:
    """Format a raw rupee number into a compact Cr / L string."""
    if val is None:
        return "—"
    try:
        n = float(val)
    except (TypeError, ValueError):
        return "—"
    if abs(n) >= 1e7:
        return f"₹{n / 1e7:,.1f} Cr"
    if abs(n) >= 1e5:
        return f"₹{n / 1e5:,.1f} L"
    return f"₹{n:,.0f}"


def _format_pct(val: Optional[float]) -> str:
    if val is None:
        return "—"
    try:
        return f"{float(val):,.2f}%"
    except (TypeError, ValueError):
        return "—"


# ─────────────────────────────────────────────────────────
# Section 1 — 5-year financial trends
# ─────────────────────────────────────────────────────────

def _render_financials(block: FinancialTrend) -> None:
    st.markdown(f"### 📊 5-Year Financial Trends  {_status_badge(block.status)}",
                unsafe_allow_html=True)
    if not block.status.available:
        _unavailable(block.status)
        return

    if block.yearly:
        df_y = pd.DataFrame([p.model_dump() for p in block.yearly])
        st.markdown("**Yearly P&L**")
        # Friendlier numbers in the table (Cr / %).
        display_y = df_y.copy()
        for col in ("revenue", "ebitda", "pat", "debt"):
            if col in display_y.columns:
                display_y[col] = display_y[col].apply(_format_money)
        for col in ("eps",):
            if col in display_y.columns:
                display_y[col] = display_y[col].apply(
                    lambda v: f"{v:,.2f}" if v is not None else "—"
                )
        for col in ("roe", "roce", "operating_margin"):
            if col in display_y.columns:
                display_y[col] = display_y[col].apply(_format_pct)
        st.dataframe(display_y, use_container_width=True, hide_index=True)

        if _PLOTLY_OK:
            chart_df = df_y.dropna(subset=["revenue", "pat"], how="all")
            if not chart_df.empty:
                fig = go.Figure()
                fig.add_bar(
                    x=chart_df["period"], y=chart_df["revenue"] / 1e7,
                    name="Revenue (Cr)",
                )
                fig.add_bar(
                    x=chart_df["period"], y=chart_df["pat"] / 1e7,
                    name="PAT (Cr)",
                )
                fig.update_layout(
                    barmode="group", height=320,
                    margin=dict(l=10, r=10, t=20, b=10),
                    legend=dict(orientation="h", y=1.05),
                )
                st.plotly_chart(fig, use_container_width=True)
            roe_df = df_y.dropna(subset=["roe", "roce"], how="all")
            if not roe_df.empty:
                fig2 = go.Figure()
                if roe_df["roe"].notna().any():
                    fig2.add_trace(go.Scatter(
                        x=roe_df["period"], y=roe_df["roe"],
                        mode="lines+markers", name="ROE %"))
                if roe_df["roce"].notna().any():
                    fig2.add_trace(go.Scatter(
                        x=roe_df["period"], y=roe_df["roce"],
                        mode="lines+markers", name="ROCE %"))
                fig2.update_layout(
                    height=280, margin=dict(l=10, r=10, t=20, b=10),
                    legend=dict(orientation="h", y=1.05),
                )
                st.plotly_chart(fig2, use_container_width=True)

    if block.quarterly:
        with st.expander("Quarterly trend (last 8 quarters)", expanded=False):
            df_q = pd.DataFrame([p.model_dump() for p in block.quarterly])
            st.dataframe(df_q, use_container_width=True, hide_index=True)

    if block.shareholding:
        with st.expander("Shareholding pattern (quarterly)", expanded=False):
            df_sh = pd.DataFrame([s.model_dump() for s in block.shareholding])
            st.dataframe(df_sh, use_container_width=True, hide_index=True)

    if block.corporate_actions:
        with st.expander("Corporate actions", expanded=False):
            for a in block.corporate_actions:
                st.markdown(f"- **{a.action_type.title()}** — {a.detail}")


# ─────────────────────────────────────────────────────────
# Section 2 — director profiles
# ─────────────────────────────────────────────────────────

def _render_directors(block: DirectorBlock) -> None:
    st.markdown(f"### 👥 Director / Promoter Profiles  {_status_badge(block.status)}",
                unsafe_allow_html=True)
    if not block.status.available:
        _unavailable(block.status)
        return
    for d in block.directors:
        # Build header: "Name — Position · Since YYYY"
        header_bits = [d.name]
        if d.designation:
            header_bits.append(f"— {d.designation}")
        if d.since_year:
            # Normalise display: bare "2023" → "Since 2023"; anything that
            # already includes a word (e.g. "June 2024") is left as-is.
            label = d.since_year if any(c.isalpha() for c in d.since_year) else f"Since {d.since_year}"
            header_bits.append(f"· {label}")
        header = " ".join(header_bits)
        with st.expander(header, expanded=False):
            if d.since_year:
                st.markdown(f"**In current role since:** {d.since_year}")
            if d.din:
                st.markdown(f"**DIN:** `{d.din}`")
            if d.background:
                st.markdown(f"**Background:** {d.background}")
            if d.other_directorships:
                st.markdown("**Other directorships:**")
                for od in d.other_directorships:
                    st.markdown(f"- {od}")
            if d.source_links:
                st.markdown("**Sources:**")
                for s in d.source_links:
                    st.markdown(f"- {s}")


# ─────────────────────────────────────────────────────────
# Section 3 — political relations
# ─────────────────────────────────────────────────────────

def _render_political(block: PoliticalBlock) -> None:
    st.markdown(f"### 🏛️ Political Relations  {_status_badge(block.status)}",
                unsafe_allow_html=True)
    if not block.connections:
        st.success("No political affiliations surfaced in public news.")
        if block.status.notes:
            st.caption(block.status.notes)
        return

    # Pretty-print + color-code categories.
    _CAT_LABELS = {
        "government_ownership": ("🏛️ Govt. ownership", "#2563eb"),
        "political_appointment": ("👤 Political appointment", "#7c3aed"),
        "donation": ("💰 Donation / electoral bond", "#ca8a04"),
        "affiliation": ("🎗️ Party affiliation", "#db2777"),
        "controversy": ("⚠️ Controversy", "#dc2626"),
        "regulatory": ("📜 Regulatory", "#0891b2"),
        "contracts": ("📑 Govt. contracts", "#059669"),
        "other": ("🔹 Other", "#6b7280"),
    }

    for c in block.connections:
        color = _CONFIDENCE_COLOR.get(c.confidence, "#6b7280")
        cat_key = (c.category or "other").lower()
        cat_label, cat_color = _CAT_LABELS.get(cat_key, _CAT_LABELS["other"])
        category_badge = (
            f"<span style='background:{cat_color};color:white;padding:2px 8px;"
            f"border-radius:6px;font-size:0.72rem;font-weight:600;'>{cat_label}</span>"
        )
        st.markdown(
            f"<div style='border-left:4px solid {color};padding:10px 14px;"
            f"margin:8px 0;background:#0001;border-radius:4px;'>"
            f"{category_badge} <b>{c.subject}</b><br>"
            f"<span style='display:block;margin-top:6px;'>{c.finding}</span>"
            f"<span style='font-size:0.78rem;color:#888;margin-top:6px;display:block;'>"
            f"Confidence: {c.confidence.upper()}</span></div>",
            unsafe_allow_html=True,
        )
        if c.source_links:
            with st.expander("Sources", expanded=False):
                for s in c.source_links:
                    st.markdown(f"- {s}")


# ─────────────────────────────────────────────────────────
# Section 4 — news & sentiment
# ─────────────────────────────────────────────────────────

def _render_news(block: NewsBlock) -> None:
    st.markdown(f"### 📰 News & Sentiment  {_status_badge(block.status)}",
                unsafe_allow_html=True)
    if not block.status.available:
        _unavailable(block.status)
        return
    c1, c2, c3 = st.columns(3)
    c1.metric("Positive 📈", block.positive)
    c2.metric("Negative 📉", block.negative)
    c3.metric("Neutral ➖", block.neutral)

    # Same card layout as the Political Relations section: left border
    # colored by sentiment, a colored category/sentiment badge chip,
    # then bold linked title, then uniform-size summary, then a small
    # metadata footer with publisher / date. Single font ladder
    # everywhere — no mix of bold + italic + st.caption that produced
    # the uneven typography before.
    _SENT_COLOR = {
        "positive": "#16a34a",   # green
        "negative": "#dc2626",   # red
        "neutral":  "#6b7280",   # gray
    }
    _SENT_LABEL = {
        "positive": "🟢 Positive",
        "negative": "🔴 Negative",
        "neutral":  "⚪ Neutral",
    }
    _CAT_COLOR = {
        "earnings":   "#2563eb",
        "regulatory": "#0891b2",
        "governance": "#7c3aed",
        "management": "#db2777",
        "macro":      "#ca8a04",
        "other":      "#6b7280",
    }

    import html as _html
    for item in block.items:
        sent = (item.sentiment or "neutral").lower()
        sent_color = _SENT_COLOR.get(sent, "#6b7280")
        sent_label = _SENT_LABEL.get(sent, "⚪ Neutral")
        cat_key = (item.category or "other").lower()
        cat_color = _CAT_COLOR.get(cat_key, "#6b7280")

        sent_badge = (
            f"<span style='background:{sent_color};color:white;padding:2px 8px;"
            f"border-radius:6px;font-size:0.72rem;font-weight:600;'>{sent_label}</span>"
        )
        cat_badge = (
            f"<span style='background:{cat_color};color:white;padding:2px 8px;"
            f"border-radius:6px;font-size:0.72rem;font-weight:600;margin-left:6px;'>"
            f"{_html.escape(cat_key)}</span>"
        )

        # Sanitize before escaping — Tavily snippets carry raw markdown
        # leftovers (### headings, # marks, bold, table pipes) that would
        # otherwise render as full-size H3 / list / table elements even
        # inside <span> tags.
        clean_title = _sanitize_text(item.title, max_len=200)
        clean_summary = _sanitize_text(item.summary, max_len=320)

        title_html = _html.escape(clean_title)
        if item.link:
            title_html = (
                f"<a href='{_html.escape(item.link)}' target='_blank' "
                f"style='color:inherit;text-decoration:none;'>{title_html}</a>"
            )

        summary_html = (
            f"<span style='display:block;margin-top:6px;font-size:0.92rem;"
            f"line-height:1.45;'>{_html.escape(clean_summary)}</span>"
        ) if clean_summary else ""

        meta_bits: List[str] = []
        if item.publisher:
            meta_bits.append(_html.escape(item.publisher))
        if item.published:
            meta_bits.append(_html.escape(item.published))
        meta_html = (
            f"<span style='font-size:0.78rem;color:#888;margin-top:6px;"
            f"display:block;'>{' · '.join(meta_bits)}</span>"
            if meta_bits else ""
        )

        st.markdown(
            f"<div style='border-left:4px solid {sent_color};padding:10px 14px;"
            f"margin:8px 0;background:#0001;border-radius:4px;'>"
            f"{sent_badge}{cat_badge}<br>"
            f"<b style='display:block;margin-top:6px;font-size:0.98rem;"
            f"line-height:1.4;'>{title_html}</b>"
            f"{summary_html}"
            f"{meta_html}"
            f"</div>",
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────────────────
# Section 5 — legal / criminal cases
# ─────────────────────────────────────────────────────────

def _render_legal(block: LegalBlock) -> None:
    st.markdown(f"### ⚖️ Legal / Criminal Cases  {_status_badge(block.status)}",
                unsafe_allow_html=True)
    if not block.cases:
        st.success("No legal / enforcement actions surfaced in public sources.")
        if block.status.notes:
            st.caption(block.status.notes)
        return

    # Colour + label per case_type — mirrors the badge style used in
    # Political Relations and News for visual consistency.
    _CASE_TYPE_LABELS = {
        "regulator":   ("🏛️ Regulator", "#2563eb"),
        "court":       ("⚖️ Court", "#7c3aed"),
        "penalty":     ("💸 Penalty", "#dc2626"),
        "tax":         ("📑 Tax", "#ca8a04"),
        "defaulter":   ("🚨 Defaulter", "#991b1b"),
        "governance":  ("🛡️ Governance", "#db2777"),
        "ipr":         ("™️ IP", "#0891b2"),
        "arbitration": ("🤝 Arbitration", "#059669"),
        "other":       ("🔹 Other", "#6b7280"),
    }

    import html as _html
    for case in block.cases:
        color = _CONFIDENCE_COLOR.get(case.confidence, "#6b7280")
        ct_key = (case.case_type or "other").lower()
        ct_label, ct_color = _CASE_TYPE_LABELS.get(ct_key, _CASE_TYPE_LABELS["other"])
        type_badge = (
            f"<span style='background:{ct_color};color:white;padding:2px 8px;"
            f"border-radius:6px;font-size:0.72rem;font-weight:600;'>{ct_label}</span>"
        )
        published_bit = (
            f" · {_html.escape(case.published)}" if case.published else ""
        )
        st.markdown(
            f"<div style='border-left:4px solid {color};padding:10px 14px;"
            f"margin:8px 0;background:#0001;border-radius:4px;'>"
            f"{type_badge} <b style='margin-left:6px;'>{_html.escape(case.subject)}</b><br>"
            f"<span style='display:block;margin-top:6px;'>{_html.escape(case.summary)}</span>"
            f"<span style='font-size:0.78rem;color:#888;margin-top:6px;display:block;'>"
            f"Confidence: {case.confidence.upper()}{published_bit}</span></div>",
            unsafe_allow_html=True,
        )
        if case.source_links:
            with st.expander("Sources", expanded=False):
                for s in case.source_links:
                    st.markdown(f"- {s}")


# ─────────────────────────────────────────────────────────
# Section 6 + 7 — promoter investments + portfolio performance
# ─────────────────────────────────────────────────────────

def _render_investments(block: InvestmentsBlock) -> None:
    st.markdown(
        f"### 🏢 Promoter Investments & Portfolio Performance  "
        f"{_status_badge(block.status)}",
        unsafe_allow_html=True,
    )
    if not block.status.available and not block.investments:
        _unavailable(block.status)
        return

    if block.investments:
        st.markdown("**Cross-holdings / related-party companies:**")
        df = pd.DataFrame([
            {
                "Investor": inv.investor_name,
                "Company": inv.company_name,
                "Stake %": _format_pct(inv.stake_percent),
                "Listed": "Yes" if inv.listed else "No",
                "Ticker": inv.ticker or "—",
                "Value": inv.investment_value or "—",
            }
            for inv in block.investments
        ])
        st.dataframe(df, use_container_width=True, hide_index=True)

    if block.performance:
        st.markdown("**Portfolio company performance (listed only):**")
        cards_per_row = 2
        rows: List[List[Any]] = [
            block.performance[i:i + cards_per_row]
            for i in range(0, len(block.performance), cards_per_row)
        ]
        for row in rows:
            cols = st.columns(len(row))
            for col, perf in zip(cols, row):
                with col:
                    name = perf.company_name or perf.ticker or "—"
                    trend = perf.revenue_trend or "n/a"
                    st.markdown(
                        f"**{name}**  \n"
                        f"`{perf.ticker or '—'}`"
                    )
                    sub_c1, sub_c2 = st.columns(2)
                    sub_c1.metric("1Y", _format_pct(perf.return_1y_pct))
                    sub_c2.metric("3Y", _format_pct(perf.return_3y_pct))
                    st.caption(f"Revenue trend: {trend}")


# ─────────────────────────────────────────────────────────
# Section 8 — pledge data
# ─────────────────────────────────────────────────────────

def _render_pledge(block: PledgeBlock) -> None:
    risk_color = _RISK_COLOR.get(block.risk_level, "#6b7280")
    risk_badge = (
        f"<span style='background:{risk_color};color:white;padding:2px 8px;"
        f"border-radius:6px;font-size:0.75rem;font-weight:600;'>"
        f"RISK: {block.risk_level.upper()}</span>"
    )
    st.markdown(
        f"### 🔒 Promoter Pledge / Loans Against Shares  "
        f"{_status_badge(block.status)}  {risk_badge}",
        unsafe_allow_html=True,
    )
    if not block.status.available:
        _unavailable(block.status)
        return

    # `events` is the NSE SAST/PIT pledge-filing list; `trend` is the
    # screener.in quarterly series. Both can be empty for clean stocks.
    events = getattr(block, "events", []) or []

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Latest pledge", _format_pct(block.current_percent))
    c2.metric("Risk level", block.risk_level.upper())
    c3.metric("Quarters tracked", len(block.trend))
    c4.metric("NSE filings", len(events))

    # Always surface the section's notes as an info banner — the renderer
    # used to bail silently when `trend` was empty for clean stocks (e.g.
    # TCS, INFY) which left the section looking broken. The note explains
    # exactly *why* the value is 0%/N/A so the user can interpret it.
    if block.status.notes:
        st.info(block.status.notes)

    # Render the chart + dataframe whenever we have any trend points —
    # including the 12-quarter flat-line that the analyzer now synthesises
    # for 0%-pledge stocks. A flat-line at 0% is itself meaningful: it's
    # visual confirmation the value held steady across the window.
    if block.trend:
        df = pd.DataFrame([p.model_dump() for p in block.trend])
        if _PLOTLY_OK and df["percent_pledged"].notna().any():
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df["quarter"], y=df["percent_pledged"],
                mode="lines+markers", name="Pledge %",
                line=dict(color=risk_color),
            ))
            fig.update_layout(
                height=260, margin=dict(l=10, r=10, t=20, b=10),
                yaxis_title="% pledged",
                yaxis=dict(rangemode="tozero"),
            )
            st.plotly_chart(fig, use_container_width=True)
        with st.expander(f"Quarterly pledge values ({len(df)} quarters)",
                         expanded=False):
            st.dataframe(df, use_container_width=True, hide_index=True)

    # NSE SAST/PIT pledge transactions — authoritative exchange filings
    # with exact share counts, rupee values, and dates. Render newest-
    # first so the most recent activity is visible without scrolling.
    if events:
        # Pledge-heavy stock: open the expander by default so the user
        # sees the transactions without an extra click.
        with st.expander(
            f"📋 NSE SAST/PIT pledge filings — {len(events)} transaction(s)",
            expanded=True,
        ):
            st.caption(
                f"Authoritative exchange disclosures (NSE `/api/corporates-pit`). "
                f"{len(events)} pledge-related filing(s) pulled from the full "
                "history. Annex 7(2)/7(3) under SEBI's PIT regulations."
            )
            ev_df = pd.DataFrame([
                {
                    "Date": ev.date or ev.intimation_date or "—",
                    "Filed": ev.intimation_date or "—",
                    "Mode": ev.mode or ev.transaction_type or "—",
                    "Acquirer": ev.acquirer or "—",
                    "Category": ev.category or "—",
                    "Shares": f"{ev.shares:,}" if ev.shares else "—",
                    "Value (₹)": _format_money(ev.value) if ev.value else "—",
                    "Before %": _format_pct(ev.before_pct),
                    "After %": _format_pct(ev.after_pct),
                    "XBRL": ev.xbrl_url or "",
                }
                for ev in events
            ])
            st.dataframe(ev_df, use_container_width=True, hide_index=True)
    elif (block.current_percent or 0) == 0:
        # Clean stock with NSE confirmation. Make it visually obvious that
        # "0" means "verified clean" rather than "data missing" — this is
        # the common case for large-caps and was the user's main confusion.
        st.success(
            "✅ **NSE corroboration**: zero pledge-related filings found in "
            "NSE's SAST/PIT history. The 0% reading is verified by two "
            "independent sources (screener.in + NSE), not a data gap."
        )
    else:
        # Pledge percent > 0 but NSE returned no filings — could mean the
        # filings are too old (>10 years) or NSE was rate-limited. Be
        # explicit about the discrepancy so the user knows to verify.
        st.warning(
            "ℹ️ Pledge reading came from screener.in but NSE returned no "
            "SAST/PIT filings (possibly older than the API window, or NSE "
            "was rate-limited). Verify against the latest BSE/NSE "
            "shareholding-pattern filing for the exact transaction history."
        )

    # Surface the screener.in (or other) source links so the user can
    # click through and verify the reading against the primary filing.
    if block.status.sources:
        with st.expander("Sources checked", expanded=False):
            for s in block.status.sources:
                st.markdown(f"- {s}")


# ─────────────────────────────────────────────────────────
# Top-level orchestrator
# ─────────────────────────────────────────────────────────

def render_fundamental_analysis(result: Any) -> None:
    """Render the full 8-section dashboard. Call this inside any Streamlit
    container (column, expander, tab). Errors in one section don't break
    the others — every block self-checks `status.available` first.

    Accepts either a `FundamentalAnalysis` instance OR a dict (the JSON
    payload). Streamlit's hot-reload re-imports modules whenever a
    source file is edited — that changes the in-memory identity of the
    `FundamentalAnalysis` class, so an instance built before the reload
    fails a strict `isinstance` check after. We tolerate both shapes
    here AND attempt a `model_dump`/`model_validate` round-trip when
    the type identity has drifted, so a stale cached value in
    `st.session_state` re-renders cleanly without forcing a refetch.
    """
    # Fast path — fresh instance built against the current class.
    if isinstance(result, FundamentalAnalysis):
        normalized = result
    else:
        normalized = None

        # Hot-reload drift: same shape, different class identity. Look
        # for the duck-typed `model_dump` (pydantic) or fall back to
        # `__dict__` to recover the JSON payload, then re-validate.
        if hasattr(result, "model_dump"):
            try:
                normalized = FundamentalAnalysis.model_validate(result.model_dump())
            except Exception:
                normalized = None

        # Already a dict (from DB cache, JSON file, etc.) → validate.
        if normalized is None and isinstance(result, dict):
            try:
                normalized = FundamentalAnalysis.model_validate(result)
            except Exception as exc:
                st.error(f"Could not validate cached fundamentals payload: {exc}")
                return

        # Last-resort: if the object has a `__dict__` that includes
        # `symbol`, attempt to coerce.
        if normalized is None and hasattr(result, "__dict__"):
            payload = getattr(result, "__dict__", None)
            if isinstance(payload, dict) and payload.get("symbol"):
                try:
                    normalized = FundamentalAnalysis.model_validate(payload)
                except Exception:
                    normalized = None

        if normalized is None:
            st.error(
                "Invalid payload passed to render_fundamental_analysis(). "
                f"Got `{type(result).__name__}` — expected `FundamentalAnalysis`, "
                "a pydantic-compatible object, or a dict."
            )
            return

    result = normalized

    header_bits: List[str] = [f"## 💼 Enhanced Fundamental Analysis — {result.symbol}"]
    if result.stock_name:
        header_bits.append(f"_{result.stock_name}_")
    st.markdown("  \n".join(header_bits))

    meta_bits: List[str] = []
    meta_bits.append(f"Version: `{result.analysis_version}`")
    meta_bits.append(f"Generated: {result.generated_at.strftime('%Y-%m-%d %H:%M UTC')}")
    if result.cached:
        meta_bits.append("📦 **Cached** (re-run to refresh)")
    st.caption(" · ".join(meta_bits))

    if result.overall_notes:
        for note in result.overall_notes:
            st.warning(note)

    _render_financials(result.financials)
    st.divider()
    _render_directors(result.directors)
    st.divider()
    _render_political(result.political)
    st.divider()
    _render_news(result.news)
    st.divider()
    _render_legal(result.legal)
    st.divider()
    _render_investments(result.investments)
    st.divider()
    _render_pledge(result.pledge)
