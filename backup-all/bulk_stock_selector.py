"""
Bulk Stock Selection System
Processes 200+ stocks to find those that have fallen 25%+ from their 52-week high
Uses Yahoo Finance (yfinance) for price data
"""

import yfinance as yf
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import time
import json
from dataclasses import dataclass, asdict


@dataclass
class StockResult:
    """Data structure for stock analysis result"""
    stock_symbol: str
    stock_name: str
    current_price: float
    overall_high: float
    overall_low: float
    percent_change_from_high: float
    selection: bool
    error: Optional[str] = None
    last_updated: str = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return asdict(self)


class BulkStockSelector:
    """
    Bulk processor for stock selection based on % drop from high
    """
    
    def __init__(self, max_workers: int = 10, timeout: int = 10):
        """
        Initialize the bulk processor
        
        Args:
            max_workers: Number of concurrent threads for processing
            timeout: Timeout in seconds for each stock fetch
        """
        self.max_workers = max_workers
        self.timeout = timeout
        self.results = []
        self.errors = []
    
    def calculate_stock_selection(self, symbol: str, retry_count: int = 3) -> StockResult:
        """
        Calculate selection status for a single stock
        
        Args:
            symbol: Stock symbol (e.g., 'RELIANCE.NS')
            retry_count: Number of retries on failure
            
        Returns:
            StockResult object with analysis data
        """
        for attempt in range(retry_count):
            try:
                # Fetch stock data
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period="1y")
                
                # Validate data
                if hist.empty:
                    raise ValueError(f"No historical data available for {symbol}")
                
                # Get stock info for name
                info = ticker.info
                stock_name = info.get('longName') or info.get('shortName') or symbol
                
                # Calculate required values
                overall_high = float(hist['High'].max())
                overall_low = float(hist['Low'].min())
                current_price = float(hist['Close'].iloc[-1])
                
                # Handle edge cases
                if overall_high == 0:
                    raise ValueError(f"Invalid high price (0) for {symbol}")
                
                # Calculate % change from high
                percent_change = ((current_price - overall_high) / overall_high) * 100
                percent_change = round(percent_change, 2)
                
                # Determine selection status
                selection = percent_change <= -25.0
                
                # Create result
                result = StockResult(
                    stock_symbol=symbol,
                    stock_name=stock_name,
                    current_price=round(current_price, 2),
                    overall_high=round(overall_high, 2),
                    overall_low=round(overall_low, 2),
                    percent_change_from_high=percent_change,
                    selection=selection,
                    last_updated=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                )
                
                print(f"✅ {symbol}: {percent_change:.2f}% from high {'[SELECTED]' if selection else ''}")
                return result
                
            except Exception as e:
                if attempt < retry_count - 1:
                    print(f"⚠️ {symbol}: Retry {attempt + 1}/{retry_count} - {str(e)}")
                    time.sleep(1)  # Wait before retry
                    continue
                else:
                    # Final failure
                    error_msg = f"Failed after {retry_count} attempts: {str(e)}"
                    print(f"❌ {symbol}: {error_msg}")
                    
                    return StockResult(
                        stock_symbol=symbol,
                        stock_name=symbol,
                        current_price=0.0,
                        overall_high=0.0,
                        overall_low=0.0,
                        percent_change_from_high=0.0,
                        selection=False,
                        error=error_msg,
                        last_updated=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    )
    
    def process_bulk_stocks(self, stock_list: List[str]) -> Dict:
        """
        Process multiple stocks concurrently
        
        Args:
            stock_list: List of stock symbols to process
            
        Returns:
            Dictionary with results and statistics
        """
        print(f"\n🚀 Starting bulk processing of {len(stock_list)} stocks...")
        print(f"⚙️ Using {self.max_workers} concurrent workers\n")
        
        start_time = time.time()
        all_results = []
        successful_count = 0
        error_count = 0
        
        # Process stocks concurrently
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            future_to_symbol = {
                executor.submit(self.calculate_stock_selection, symbol): symbol 
                for symbol in stock_list
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                try:
                    result = future.result(timeout=self.timeout)
                    all_results.append(result)
                    
                    if result.error:
                        error_count += 1
                    else:
                        successful_count += 1
                        
                except Exception as e:
                    error_count += 1
                    print(f"❌ {symbol}: Execution error - {str(e)}")
                    all_results.append(StockResult(
                        stock_symbol=symbol,
                        stock_name=symbol,
                        current_price=0.0,
                        overall_high=0.0,
                        overall_low=0.0,
                        percent_change_from_high=0.0,
                        selection=False,
                        error=f"Execution error: {str(e)}",
                        last_updated=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    ))
        
        # Filter selected stocks (only successful ones)
        selected_stocks = [
            result for result in all_results 
            if result.selection and not result.error
        ]
        
        # Calculate statistics
        elapsed_time = time.time() - start_time
        
        result_summary = {
            "total_stocks_processed": len(stock_list),
            "successful_count": successful_count,
            "error_count": error_count,
            "selected_count": len(selected_stocks),
            "processing_time_seconds": round(elapsed_time, 2),
            "selected_stocks": [stock.to_dict() for stock in selected_stocks],
            "all_results": [stock.to_dict() for stock in all_results],
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # Print summary
        print(f"\n{'='*60}")
        print(f"📊 PROCESSING COMPLETE")
        print(f"{'='*60}")
        print(f"Total Stocks: {len(stock_list)}")
        print(f"Successful: {successful_count}")
        print(f"Errors: {error_count}")
        print(f"Selected (≥25% drop): {len(selected_stocks)}")
        print(f"Processing Time: {elapsed_time:.2f}s")
        print(f"{'='*60}\n")
        
        return result_summary
    
    def save_results(self, results: Dict, filename: str = "stock_selection_results.json"):
        """
        Save results to JSON file
        
        Args:
            results: Results dictionary from process_bulk_stocks
            filename: Output filename
        """
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            print(f"💾 Results saved to {filename}")
        except Exception as e:
            print(f"❌ Error saving results: {e}")


# Sample Indian stock list (NSE)
SAMPLE_INDIAN_STOCKS = [
    # Nifty 50 stocks
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "HINDUNILVR.NS",
    "ICICIBANK.NS", "KOTAKBANK.NS", "SBIN.NS", "BHARTIARTL.NS", "BAJFINANCE.NS",
    "ITC.NS", "ASIANPAINT.NS", "AXISBANK.NS", "LT.NS", "MARUTI.NS",
    "SUNPHARMA.NS", "TITAN.NS", "ULTRACEMCO.NS", "NESTLEIND.NS", "WIPRO.NS",
    "HCLTECH.NS", "TECHM.NS", "POWERGRID.NS", "NTPC.NS", "ONGC.NS",
    "TATASTEEL.NS", "BAJAJFINSV.NS", "M&M.NS", "ADANIPORTS.NS", "COALINDIA.NS",
    
    # Additional popular stocks
    "TATAMOTORS.NS", "ADANIENT.NS", "JSWSTEEL.NS", "INDUSINDBK.NS", "DRREDDY.NS",
    "CIPLA.NS", "DIVISLAB.NS", "EICHERMOT.NS", "GRASIM.NS", "HEROMOTOCO.NS",
    "HINDALCO.NS", "BRITANNIA.NS", "APOLLOHOSP.NS", "BPCL.NS", "SHREECEM.NS",
    "TATACONSUM.NS", "UPL.NS", "BAJAJ-AUTO.NS", "VEDL.NS", "ADANIGREEN.NS",
    
    # Mid-cap stocks
    "GODREJCP.NS", "HAVELLS.NS", "PIDILITIND.NS", "BERGEPAINT.NS", "DABUR.NS",
    "MARICO.NS", "COLPAL.NS", "MCDOWELL-N.NS", "TATAPOWER.NS", "SAIL.NS",
    "NMDC.NS", "GAIL.NS", "IOC.NS", "BANKBARODA.NS", "PNB.NS",
    "CANBK.NS", "UNIONBANK.NS", "IDEA.NS", "ZEEL.NS", "DLF.NS",
    
    # Small-cap stocks
    "TRENT.NS", "VOLTAS.NS", "JUBLFOOD.NS", "TATATECH.NS", "JIOFIN.NS",
    "NETWORK18.NS", "RPOWER.NS", "CUPID.NS", "CONCORDBIO.NS", "HINDCOPPER.NS",
]


def main():
    """
    Main execution function - demonstrates usage
    """
    print("="*60)
    print("BULK STOCK SELECTION SYSTEM")
    print("="*60)
    
    # Initialize processor
    processor = BulkStockSelector(max_workers=10, timeout=15)
    
    # Process stocks
    results = processor.process_bulk_stocks(SAMPLE_INDIAN_STOCKS)
    
    # Save results
    processor.save_results(results)
    
    # Display selected stocks
    if results['selected_stocks']:
        print("\n🎯 SELECTED STOCKS (≥25% drop from high):")
        print("-" * 60)
        for stock in results['selected_stocks']:
            print(f"{stock['stock_symbol']:15} | "
                  f"₹{stock['current_price']:8.2f} | "
                  f"High: ₹{stock['overall_high']:8.2f} | "
                  f"Drop: {stock['percent_change_from_high']:6.2f}%")
    else:
        print("\n⚠️ No stocks met the selection criteria (≥25% drop)")


if __name__ == "__main__":
    main()
