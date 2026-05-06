"""Initial schema — stock_analysis + stock_news.

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-21 00:00:00.000000

This baseline mirrors the tables that the legacy
`StockDatabase.create_table()` / `StockDatabase.create_news_table()`
used to build inline. The statements are all `IF NOT EXISTS` so existing
databases that already have these tables (created before Alembic was
wired in) upgrade cleanly without conflict — you can safely
`alembic stamp 0001_initial` on a pre-existing database and move on.
"""

from __future__ import annotations

from alembic import op


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # stock_analysis — core table.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_analysis (
            id                          SERIAL PRIMARY KEY,
            stock_name                  VARCHAR(255) NOT NULL,
            stock_symbol                VARCHAR(50)  NOT NULL,
            analyzed_response           TEXT         NOT NULL,
            tech_analysis               JSONB        NOT NULL,
            selection                   BOOLEAN      NOT NULL,
            market_senti                TEXT,
            current_market_senti_status VARCHAR(50),
            future_senti                TEXT,
            future_senti_status         VARCHAR(50),
            analyzed_at                 TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (stock_symbol, analyzed_at)
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_stock_symbol ON stock_analysis(stock_symbol);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_selection    ON stock_analysis(selection);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_analyzed_at  ON stock_analysis(analyzed_at);")

    # stock_news — news articles cached per symbol.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_news (
            id          SERIAL PRIMARY KEY,
            stock_symbol VARCHAR(50)  NOT NULL,
            stock_name   VARCHAR(255),
            title        TEXT         NOT NULL,
            publisher    VARCHAR(255),
            link         TEXT,
            summary      TEXT,
            source       VARCHAR(50),
            fetched_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_news_symbol  ON stock_news(stock_symbol);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_news_fetched ON stock_news(fetched_at);")


def downgrade() -> None:
    # Intentionally destructive — only run in dev.
    op.execute("DROP TABLE IF EXISTS stock_news;")
    op.execute("DROP TABLE IF EXISTS stock_analysis;")
