"""
PostgreSQL Database Integration for Stock Analysis
Stores analyzed stock data with technical metrics and sentiment analysis
"""

import psycopg2
from psycopg2.extras import Json
from typing import Optional, Dict, Any
import os
from dotenv import load_dotenv
import json
from datetime import datetime

load_dotenv()

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
        """Create the stock_analysis table if it doesn't exist"""
        try:
            create_table_query = """
            CREATE TABLE IF NOT EXISTS stock_analysis (
                id SERIAL PRIMARY KEY,
                stock_name VARCHAR(255) NOT NULL,
                stock_symbol VARCHAR(50) NOT NULL,
                analyzed_response TEXT NOT NULL,
                tech_analysis JSONB NOT NULL,
                selection BOOLEAN NOT NULL,
                market_senti TEXT,
                current_market_senti_status VARCHAR(50),
                future_senti TEXT,
                future_senti_status VARCHAR(50),
                analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(stock_symbol, analyzed_at)
            );
            
            CREATE INDEX IF NOT EXISTS idx_stock_symbol ON stock_analysis(stock_symbol);
            CREATE INDEX IF NOT EXISTS idx_selection ON stock_analysis(selection);
            CREATE INDEX IF NOT EXISTS idx_analyzed_at ON stock_analysis(analyzed_at);
            """
            
            self.cursor.execute(create_table_query)
            self.conn.commit()
            print("✅ Table created/verified successfully")
            return True
        except Exception as e:
            print(f"❌ Table creation failed: {e}")
            self.conn.rollback()
            return False
    
    def save_analysis(
        self,
        stock_name: str,
        stock_symbol: str,
        analyzed_response: str,
        tech_analysis: Dict[str, Any],
        selection: bool,
        market_senti: Optional[str] = None,
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
            market_senti: Current market sentiment content
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
                market_senti,
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
                    market_senti,
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
