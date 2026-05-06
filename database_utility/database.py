"""
PostgreSQL Database Integration for Stock Analysis
Stores analyzed stock data with technical metrics and sentiment analysis.

Schema ownership
────────────────
DDL (CREATE TABLE, ADD COLUMN, indexes, etc.) lives in Alembic
migrations under ``alembic/versions/``. This module owns runtime DML
only (INSERT / UPDATE / SELECT). Calling ``StockDatabase.create_table``
now runs ``alembic upgrade head`` programmatically so callers don't
need to know about the migration tool explicitly.
"""

import os
from typing import Any, Dict, Optional

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import Json

load_dotenv()


# ─────────────────────────────────────────────────────────
# Alembic migration runner
# ─────────────────────────────────────────────────────────

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ALEMBIC_INI = os.path.join(_PROJECT_ROOT, "alembic.ini")

# Process-wide guard so we don't re-run migrations on every DB connect.
# Streamlit reruns the whole script on every interaction — if we didn't
# memoise this, `alembic upgrade head` would fire several times per
# user click (each time doing a `SELECT version_num FROM alembic_version`
# round-trip). Once per process is enough.
_MIGRATIONS_APPLIED = False


def run_migrations() -> bool:
    """Run ``alembic upgrade head`` against the configured database.

    Safe to call repeatedly — memoised per process and Alembic itself
    is idempotent (it skips revisions already in ``alembic_version``).
    Returns True on success, False if Alembic isn't installed or the
    upgrade raised. Errors are logged but never propagated so callers
    can treat this as best-effort.
    """
    global _MIGRATIONS_APPLIED
    if _MIGRATIONS_APPLIED:
        return True
    try:
        from alembic import command
        from alembic.config import Config
    except ImportError:
        print("⚠️ alembic not installed — skipping migrations. "
              "Run `pip install alembic` to enable schema migrations.")
        return False
    try:
        if not os.path.exists(_ALEMBIC_INI):
            print(f"⚠️ alembic.ini not found at {_ALEMBIC_INI}")
            return False
        cfg = Config(_ALEMBIC_INI)
        # Ensure the script location is absolute even when the caller's
        # cwd isn't the project root (Streamlit can be launched from
        # anywhere).
        cfg.set_main_option(
            "script_location",
            os.path.join(_PROJECT_ROOT, "alembic"),
        )
        command.upgrade(cfg, "head")
        _MIGRATIONS_APPLIED = True
        print("✅ Alembic migrations applied (upgrade head)")
        return True
    except Exception as e:
        print(f"❌ Alembic upgrade failed: {e}")
        return False

class StockDatabase:
    """Handle PostgreSQL database operations for stock analysis"""
    
    def __init__(self):
        """Initialize database connection"""
        self.conn_params = {
            'host': os.getenv('DB_HOST', 'localhost'),
            'port': os.getenv('DB_PORT', '5432'),
            'database': os.getenv('DB_NAME', 'stock_analysis'),
            'user': os.getenv('DB_USER', 'postgres'),
            'password': os.getenv('DB_PASSWORD', '')
        }
        self.conn = None
        self.cursor = None
    
    def connect(self):
        """Establish database connection"""
        try:
            self.conn = psycopg2.connect(**self.conn_params)
            self.cursor = self.conn.cursor()
            print("✅ Database connected successfully")
            return True
        except Exception as e:
            print(f"❌ Database connection failed: {e}")
            return False
    
    def disconnect(self):
        """Close database connection"""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        print("🔌 Database disconnected")
    
    def create_table(self):
        """Ensure the stock_analysis schema is up to date.

        Retained for backward compatibility with existing callers
        (agent1.py, app_advanced.py, bulk utilities). Schema DDL now
        lives entirely in Alembic migrations under ``alembic/versions/``
        — this method just runs ``alembic upgrade head``.
        """
        return run_migrations()
    
    def save_analysis(
        self,
        stock_name: str,
        stock_symbol: str,
        analyzed_response: str,
        tech_analysis: Dict[str, Any],
        selection: bool,
        fii_dii_analysis: Optional[str] = None,
        current_market_senti_status: Optional[str] = None,
        future_senti: Optional[str] = None,
        future_senti_status: Optional[str] = None
    ) -> bool:
        """
        Save stock analysis to database

        Args:
            stock_name: Name of the stock
            stock_symbol: Stock ticker symbol
            analyzed_response: Complete formatted analysis report
            tech_analysis: Technical analysis metrics as dict
            selection: Boolean indicating if stock is selected (% change <= -25%)
            fii_dii_analysis: FII/DII institutional shareholding analysis text
            current_market_senti_status: Status (positive/negative/neutral)
            future_senti: Future outlook sentiment content
            future_senti_status: Status (positive/negative/neutral)

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            insert_query = """
            INSERT INTO stock_analysis (
                stock_name,
                stock_symbol,
                analyzed_response,
                tech_analysis,
                selection,
                fii_dii_analysis,
                current_market_senti_status,
                future_senti,
                future_senti_status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """

            # Convert tech_analysis dict to JSON
            tech_analysis_json = Json(tech_analysis)

            self.cursor.execute(
                insert_query,
                (
                    stock_name,
                    stock_symbol,
                    analyzed_response,
                    tech_analysis_json,
                    selection,
                    fii_dii_analysis,
                    current_market_senti_status,
                    future_senti,
                    future_senti_status
                )
            )
            
            self.conn.commit()
            print(f"✅ Analysis saved for {stock_name} ({stock_symbol})")
            return True
            
        except Exception as e:
            print(f"❌ Failed to save analysis: {e}")
            self.conn.rollback()
            return False
    
    def update_sentiment_columns(
        self,
        stock_symbol: str,
        current_market_senti_status: Optional[str] = None,
        future_senti: Optional[str] = None,
        future_senti_status: Optional[str] = None,
    ) -> bool:
        """Update the sentiment-related columns on the LATEST stock_analysis
        row for a given symbol.

        Called by the background-task pipeline after future-outlook
        analysis completes. Only non-None arguments are written — the
        others are left untouched — so concurrent updates from different
        pipelines don't clobber each other's values.

        Note: the FII/DII institutional analysis has its own dedicated
        method (``update_fii_dii_analysis``) because its column was
        repurposed from the old ``market_senti`` slot.

        Returns True if a row was updated, False otherwise.
        """
        try:
            if not stock_symbol:
                print("⚠️ update_sentiment_columns: stock_symbol is required")
                return False

            # Build SET clause dynamically from only the non-None fields so
            # repeated calls can update just one sub-set.
            _sets: list[str] = []
            _vals: list[Any] = []
            if current_market_senti_status is not None:
                _sets.append("current_market_senti_status = %s")
                _vals.append(current_market_senti_status)
            if future_senti is not None:
                _sets.append("future_senti = %s")
                _vals.append(future_senti)
            if future_senti_status is not None:
                _sets.append("future_senti_status = %s")
                _vals.append(future_senti_status)

            if not _sets:
                print("⚠️ update_sentiment_columns: nothing to update")
                return False

            _vals.append(stock_symbol)  # for WHERE clause

            query = f"""
            UPDATE stock_analysis
            SET {', '.join(_sets)}
            WHERE id = (
                SELECT id FROM stock_analysis
                WHERE stock_symbol = %s
                ORDER BY analyzed_at DESC
                LIMIT 1
            )
            """
            self.cursor.execute(query, tuple(_vals))
            _affected = self.cursor.rowcount
            self.conn.commit()
            if _affected:
                print(f"✅ Sentiment columns updated for {stock_symbol}")
                return True
            print(f"⚠️ No stock_analysis row found for {stock_symbol} — nothing updated")
            return False
        except Exception as e:
            print(f"❌ update_sentiment_columns failed for {stock_symbol}: {e}")
            self.conn.rollback()
            return False

    def update_fii_dii_analysis(
        self,
        stock_symbol: str,
        fii_dii_analysis: str,
    ) -> bool:
        """Update the ``fii_dii_analysis`` column on the LATEST
        stock_analysis row for a given symbol.

        Called after the FII/DII institutional sentiment has been computed
        on the Data Dashboard so the formatted analysis block is persisted
        alongside the fundamental analysis. FinRobot then reads this
        column to factor institutional flow into its reasoning memo.

        Returns True if a row was updated, False otherwise.
        """
        try:
            if not stock_symbol:
                print("⚠️ update_fii_dii_analysis: stock_symbol is required")
                return False
            if fii_dii_analysis is None:
                print("⚠️ update_fii_dii_analysis: fii_dii_analysis text is required")
                return False

            query = """
            UPDATE stock_analysis
            SET fii_dii_analysis = %s
            WHERE id = (
                SELECT id FROM stock_analysis
                WHERE stock_symbol = %s
                ORDER BY analyzed_at DESC
                LIMIT 1
            )
            """
            self.cursor.execute(query, (fii_dii_analysis, stock_symbol))
            _affected = self.cursor.rowcount
            self.conn.commit()
            if _affected:
                print(f"✅ FII/DII analysis updated for {stock_symbol}")
                return True
            print(f"⚠️ No stock_analysis row found for {stock_symbol} — FII/DII not persisted")
            return False
        except Exception as e:
            print(f"❌ update_fii_dii_analysis failed for {stock_symbol}: {e}")
            self.conn.rollback()
            return False

    def update_finrobot_columns(
        self,
        stock_symbol: str,
        finrobot_response: Optional[str] = None,
        finrobot_recommendation: Optional[str] = None,
        finrobot_score: Optional[float] = None,
    ) -> bool:
        """Update the FinRobot columns on the LATEST stock_analysis row
        for a given symbol. Called after a successful FinRobot deep
        analysis run so the full markdown report + recommendation +
        score are persisted alongside the fundamental analysis.

        Only non-None arguments are written — this keeps the method
        safe to call even when one of the three fields is unavailable.

        Returns True if a row was updated, False otherwise.
        """
        try:
            if not stock_symbol:
                print("⚠️ update_finrobot_columns: stock_symbol is required")
                return False

            _sets: list[str] = []
            _vals: list[Any] = []
            if finrobot_response is not None:
                _sets.append("finrobot_response = %s")
                _vals.append(finrobot_response)
            if finrobot_recommendation is not None:
                _sets.append("finrobot_recommendation = %s")
                _vals.append(finrobot_recommendation)
            if finrobot_score is not None:
                _sets.append("finrobot_score = %s")
                _vals.append(finrobot_score)

            if not _sets:
                print("⚠️ update_finrobot_columns: nothing to update")
                return False

            _vals.append(stock_symbol)

            query = f"""
            UPDATE stock_analysis
            SET {', '.join(_sets)}
            WHERE id = (
                SELECT id FROM stock_analysis
                WHERE stock_symbol = %s
                ORDER BY analyzed_at DESC
                LIMIT 1
            )
            """
            self.cursor.execute(query, tuple(_vals))
            _affected = self.cursor.rowcount
            self.conn.commit()
            if _affected:
                print(f"✅ FinRobot columns updated for {stock_symbol}")
                return True
            print(f"⚠️ No stock_analysis row found for {stock_symbol} — FinRobot not persisted")
            return False
        except Exception as e:
            print(f"❌ update_finrobot_columns failed for {stock_symbol}: {e}")
            self.conn.rollback()
            return False

    def get_latest_analysis(self, stock_symbol: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get the most recent analysis for a stock or overall latest"""
        try:
            if stock_symbol:
                query = """
                SELECT *, analyzed_response as formatted_report FROM stock_analysis
                WHERE stock_symbol = %s
                ORDER BY analyzed_at DESC
                LIMIT 1
                """
                self.cursor.execute(query, (stock_symbol,))
            else:
                # Get the most recent analysis overall
                query = """
                SELECT *, analyzed_response as formatted_report FROM stock_analysis
                ORDER BY analyzed_at DESC
                LIMIT 1
                """
                self.cursor.execute(query)
            
            result = self.cursor.fetchone()
            
            if result:
                columns = [desc[0] for desc in self.cursor.description]
                return dict(zip(columns, result))
            return None
            
        except Exception as e:
            print(f"❌ Failed to retrieve analysis: {e}")
            return None
    
    def get_cached_analysis(self, stock_symbol: str, max_age_hours: int = 6) -> Optional[Dict[str, Any]]:
        """
        Return a recent analysis if it exists and is fresh enough.
        Used to serve instant responses when another user already analyzed
        the same stock recently.

        Args:
            stock_symbol: Ticker (e.g. 'RELIANCE.NS')
            max_age_hours: Maximum age in hours to consider the cache valid.

        Returns:
            Dict with 'analyzed_response' key, or None if stale/missing.
        """
        try:
            query = """
            SELECT stock_name, stock_symbol, analyzed_response,
                   analyzed_at, tech_analysis, selection
            FROM stock_analysis
            WHERE stock_symbol = %s
              AND analyzed_at > NOW() - INTERVAL '%s hours'
            ORDER BY analyzed_at DESC
            LIMIT 1
            """
            self.cursor.execute(query, (stock_symbol, max_age_hours))
            result = self.cursor.fetchone()

            if result:
                columns = [desc[0] for desc in self.cursor.description]
                row = dict(zip(columns, result))
                print(f"⚡ DB cache hit for {stock_symbol} "
                      f"(analyzed {row['analyzed_at']})")
                return row
            return None

        except Exception as e:
            print(f"⚠️ DB cache lookup failed: {e}")
            return None

    def get_selected_stocks(self) -> list:
        """Get all stocks marked as selected (% change <= -25%)"""
        try:
            query = """
            SELECT DISTINCT ON (stock_symbol) *
            FROM stock_analysis
            WHERE selection = TRUE
            ORDER BY stock_symbol, analyzed_at DESC
            """
            
            self.cursor.execute(query)
            results = self.cursor.fetchall()
            
            columns = [desc[0] for desc in self.cursor.description]
            return [dict(zip(columns, row)) for row in results]
            
        except Exception as e:
            print(f"❌ Failed to retrieve selected stocks: {e}")
            return []


    def create_news_table(self):
        """Ensure the stock_news table exists.

        Backward-compat shim: DDL now lives in Alembic migrations, so
        this just delegates to ``run_migrations()`` to apply any pending
        revisions. The ``try/except`` block below remains only so
        legacy error paths that depended on the return value continue
        to work identically.
        """
        try:
            return run_migrations()
        except Exception as e:
            print(f"❌ News table creation failed: {e}")
            self.conn.rollback()
            return False

    def save_news(self, stock_symbol: str, stock_name: str, news_list: list) -> bool:
        """
        Batch insert news items for a stock. Skips duplicates by title+symbol.

        Args:
            stock_symbol: e.g. 'TCS.NS'
            stock_name: e.g. 'Tata Consultancy Services Limited'
            news_list: List of dicts with keys: title, publisher, link, summary, source
        """
        if not news_list:
            return True
        try:
            inserted = 0
            for item in news_list:
                title = (item.get('title') or '').strip()
                if not title:
                    continue
                # Skip if this exact title already exists for this symbol (within 24h)
                self.cursor.execute(
                    "SELECT 1 FROM stock_news WHERE stock_symbol = %s AND title = %s "
                    "AND fetched_at > NOW() - INTERVAL '24 hours' LIMIT 1",
                    (stock_symbol, title)
                )
                if self.cursor.fetchone():
                    continue
                self.cursor.execute(
                    "INSERT INTO stock_news (stock_symbol, stock_name, title, publisher, link, summary, source) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (
                        stock_symbol,
                        stock_name,
                        title,
                        item.get('publisher', ''),
                        item.get('link', ''),
                        item.get('summary', ''),
                        item.get('source', 'tavily'),
                    )
                )
                inserted += 1
            self.conn.commit()
            if inserted:
                print(f"✅ Saved {inserted} news items to DB for {stock_symbol}")
            return True
        except Exception as e:
            print(f"❌ Failed to save news: {e}")
            self.conn.rollback()
            return False

    def get_news(self, stock_symbol: str, limit: int = 20, max_age_hours: int = 72) -> list:
        """
        Get recent news for a stock symbol.

        Returns:
            List of dicts with title, publisher, link, summary, source, fetched_at
        """
        try:
            self.cursor.execute(
                "SELECT title, publisher, link, summary, source, fetched_at "
                "FROM stock_news "
                "WHERE stock_symbol = %s AND fetched_at > NOW() - INTERVAL '%s hours' "
                "ORDER BY fetched_at DESC LIMIT %s",
                (stock_symbol, max_age_hours, limit)
            )
            rows = self.cursor.fetchall()
            columns = [desc[0] for desc in self.cursor.description]
            return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            print(f"❌ Failed to get news: {e}")
            return []


def extract_tech_analysis_json(company_data) -> Dict[str, Any]:
    """
    Extract technical analysis data from CompanyData object
    
    Args:
        company_data: CompanyData object from analysis
    
    Returns:
        Dict with technical analysis metrics
    """
    # Determine currency symbol
    is_indian = company_data.symbol.endswith('.NS') or company_data.symbol.endswith('.BO')
    currency_symbol = "₹" if is_indian else "$"
    
    # Helper function to format currency values
    def format_currency(value, is_indian=True):
        if value is None:
            return "N/A"
        if is_indian:
            if value >= 1e7:
                return f"₹{value/1e7:.2f} Cr"
            elif value >= 1e5:
                return f"₹{value/1e5:.2f} L"
            else:
                return f"₹{value:.2f}"
        else:
            if value >= 1e9:
                return f"${value/1e9:.2f} B"
            elif value >= 1e6:
                return f"${value/1e6:.2f} M"
            else:
                return f"${value:.2f}"
    
    # Build tech analysis JSON
    tech_analysis = {
        "Current Price": f"{currency_symbol}{company_data.market_data.current_price:.2f}" if company_data.market_data.current_price else "N/A",
        "PE Ratio": f"{company_data.financials.pe_ratio:.2f}" if company_data.financials.pe_ratio else "N/A",
        "Profit Margin": f"{company_data.financials.profit_margin*100:.2f}%" if company_data.financials.profit_margin else "N/A",
        "Market Cap": format_currency(company_data.market_data.market_cap, is_indian),
        "EBITDA": format_currency(company_data.financials.ebitda, is_indian) if company_data.financials.ebitda else "N/A",
        "EPS": f"{company_data.financials.eps:.2f}" if company_data.financials.eps else "N/A",
        "Debt / Equity": f"{company_data.financials.debt_to_equity:.2f}" if company_data.financials.debt_to_equity else "N/A",
        "Overall High": f"{currency_symbol}{company_data.market_data.overall_high:.2f}" if company_data.market_data.overall_high else "N/A",
        "Overall Low": f"{currency_symbol}{company_data.market_data.overall_low:.2f}" if company_data.market_data.overall_low else "N/A",
        "Percentage Change": f"{company_data.market_data.percentage_change_from_high:.2f}%" if company_data.market_data.percentage_change_from_high is not None else "N/A"
    }
    
    # Add max_drop_after_high if available (backward compatibility)
    max_drop = getattr(company_data.market_data, 'max_drop_after_high', None)
    if max_drop is not None:
        tech_analysis["Max Drop After High"] = f"{max_drop:.2f}%"
    
    return tech_analysis


def calculate_selection_status(company_data) -> bool:
    """
    Calculate if stock should be selected based on maximum drop after overall high
    
    Args:
        company_data: CompanyData object
    
    Returns:
        bool: True if max_drop_after_high <= -25%, False otherwise
    """
    # Use max_drop_after_high if available (checks if stock ever dropped 25% after peak)
    max_drop = getattr(company_data.market_data, 'max_drop_after_high', None)
    if max_drop is not None:
        return max_drop <= -25.0
    
    # Fallback to percentage_change_from_high (current price vs high)
    if company_data.market_data.percentage_change_from_high is not None:
        return company_data.market_data.percentage_change_from_high <= -25.0
    
    return False


# Example usage
if __name__ == "__main__":
    # Test database connection
    db = StockDatabase()
    if db.connect():
        db.create_table()
        db.disconnect()
