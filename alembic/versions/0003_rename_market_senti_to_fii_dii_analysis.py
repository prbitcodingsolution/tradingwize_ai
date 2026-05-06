"""Rename stock_analysis.market_senti -> fii_dii_analysis.

Revision ID: 0003_fii_dii_analysis
Revises: 0002_finrobot_columns
Create Date: 2026-04-21 00:00:02.000000

The legacy `market_senti` column was created to store the news/Yahoo/
Reddit/Twitter market-sentiment block, but that pipeline has been shut
off (client cost-reduction). The column is being repurposed to store
the FII/DII institutional shareholding analysis that now drives a
dedicated dashboard section AND the FinRobot reasoning agent.

Pure column rename — all existing row data is preserved, so any stale
sentiment text already in the column is harmless (will be overwritten
as soon as FII/DII runs for that symbol).

Idempotent: the rename is guarded by a DO-block that checks
information_schema first, so re-running on a freshly-renamed database
is a no-op.
"""

from __future__ import annotations

from alembic import op


revision = "0003_fii_dii_analysis"
down_revision = "0002_finrobot_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'stock_analysis'
                  AND column_name = 'market_senti'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'stock_analysis'
                  AND column_name = 'fii_dii_analysis'
            ) THEN
                ALTER TABLE stock_analysis RENAME COLUMN market_senti TO fii_dii_analysis;
            ELSIF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'stock_analysis'
                  AND column_name = 'fii_dii_analysis'
            ) THEN
                ALTER TABLE stock_analysis ADD COLUMN fii_dii_analysis TEXT;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'stock_analysis'
                  AND column_name = 'fii_dii_analysis'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'stock_analysis'
                  AND column_name = 'market_senti'
            ) THEN
                ALTER TABLE stock_analysis RENAME COLUMN fii_dii_analysis TO market_senti;
            END IF;
        END $$;
        """
    )
