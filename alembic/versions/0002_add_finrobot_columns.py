"""Add FinRobot deep-analysis columns to stock_analysis.

Revision ID: 0002_finrobot_columns
Revises: 0001_initial
Create Date: 2026-04-21 00:00:01.000000

Adds three columns that the FinRobot "Run Deep Analysis" flow writes
on every run:

    finrobot_response        TEXT          — full markdown memo
    finrobot_recommendation  VARCHAR(50)   — Strong Buy / Buy / Hold / Sell / Strong Sell
    finrobot_score           NUMERIC(5,2)  — 0–100 final score

`ADD COLUMN IF NOT EXISTS` keeps the migration idempotent for databases
where the columns were already added inline by the previous
`create_table()` version.
"""

from __future__ import annotations

from alembic import op


revision = "0002_finrobot_columns"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE stock_analysis "
        "ADD COLUMN IF NOT EXISTS finrobot_response TEXT;"
    )
    op.execute(
        "ALTER TABLE stock_analysis "
        "ADD COLUMN IF NOT EXISTS finrobot_recommendation VARCHAR(50);"
    )
    op.execute(
        "ALTER TABLE stock_analysis "
        "ADD COLUMN IF NOT EXISTS finrobot_score NUMERIC(5,2);"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE stock_analysis DROP COLUMN IF EXISTS finrobot_score;")
    op.execute("ALTER TABLE stock_analysis DROP COLUMN IF EXISTS finrobot_recommendation;")
    op.execute("ALTER TABLE stock_analysis DROP COLUMN IF EXISTS finrobot_response;")
