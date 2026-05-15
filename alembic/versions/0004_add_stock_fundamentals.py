"""Add stock_fundamentals table for the enhanced fundamental analysis module.

Revision ID: 0004_stock_fundamentals
Revises: 0003_fii_dii_analysis
Create Date: 2026-05-11 00:00:00.000000

Stores the result of `utils.fundamental_analyzer.analyze_fundamentals` —
a JSON snapshot of the 8 sub-analyses (5Y financial trends, director
profiles, political flags, news, legal cases, promoter investments,
portfolio performance, pledge data) per symbol with a fetched_at
timestamp so callers can implement TTL-based caching.

Why one JSONB column instead of 8 normalised tables: matches the existing
`stock_analysis.tech_analysis JSONB` pattern in 0001, keeps the schema
forward-compatible (we can add/remove fields in the analyzer without
follow-up migrations), and the per-section access pattern in the
Streamlit renderer is "fetch the whole snapshot, then render" — there's
no query workload that benefits from a relational shape today.

`analysis_version` is bumped by the analyzer whenever the JSON shape
changes in a backwards-incompatible way so the renderer can decide
whether to use a cached row or refetch.
"""

from __future__ import annotations

from alembic import op


revision = "0004_stock_fundamentals"
down_revision = "0003_fii_dii_analysis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_fundamentals (
            id                 SERIAL PRIMARY KEY,
            stock_symbol       VARCHAR(50)  NOT NULL,
            stock_name         VARCHAR(255),
            payload            JSONB        NOT NULL,
            analysis_version   VARCHAR(20)  NOT NULL DEFAULT 'v1',
            fetched_at         TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (stock_symbol, fetched_at)
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_stock_fund_symbol "
        "ON stock_fundamentals(stock_symbol);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_stock_fund_fetched "
        "ON stock_fundamentals(fetched_at DESC);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_stock_fund_fetched;")
    op.execute("DROP INDEX IF EXISTS idx_stock_fund_symbol;")
    op.execute("DROP TABLE IF EXISTS stock_fundamentals;")
