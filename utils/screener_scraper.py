"""
Screener.in Web Scraper for Accurate Financial Data
Fetches real-time financial metrics directly from screener.in
"""

import requests
from bs4 import BeautifulSoup
import re
from typing import Dict, Optional, Any
import time

BASE_URL = "https://www.screener.in"

# Enhanced headers to mimic a real browser
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0"
}


def search_stock_on_screener(stock_symbol: str) -> Optional[str]:
    """
    Search for a stock on screener.in and return the company URL
    
    Args:
        stock_symbol: Stock symbol (e.g., 'TATASTEEL', 'RELIANCE')
    
    Returns:
        str: Full URL to the company page or None if not found
    """
    print(f"🔍 Searching for stock on screener.in: {stock_symbol}")
    
    # Remove .NS or .BO suffix if present
    clean_symbol = stock_symbol.replace('.NS', '').replace('.BO', '').upper()
    
    # Try direct company URL first (consolidated view)
    direct_url = f"{BASE_URL}/company/{clean_symbol}/consolidated/"
    
    try:
        resp = requests.get(direct_url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            print(f"✅ Found direct URL: {direct_url}")
            return direct_url
    except Exception as e:
        print(f"⚠️ Direct URL failed: {e}")
    
    # Try without consolidated
    direct_url_simple = f"{BASE_URL}/company/{clean_symbol}/"
    try:
        resp = requests.get(direct_url_simple, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            print(f"✅ Found URL: {direct_url_simple}")
            return direct_url_simple
    except Exception as e:
        print(f"⚠️ Simple URL failed: {e}")
    
    # Try search API
    search_url = f"{BASE_URL}/api/company/search/?q={clean_symbol}"
    
    try:
        resp = requests.get(search_url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data and len(data) > 0:
                first_result = data[0]
                company_url = first_result.get('url', '')
                if company_url:
                    full_url = f"{BASE_URL}{company_url}"
                    print(f"✅ Found via search API: {full_url}")
                    return full_url
    except Exception as e:
        print(f"⚠️ Search API failed: {e}")
    
    print(f"❌ Stock '{stock_symbol}' not found on screener.in")
    return None


def parse_number(value_str: str) -> Optional[float]:
    """
    Parse number from screener.in format
    Examples: '2,61,232 Cr.' -> 261232.0, '26.8' -> 26.8, '1.76 %' -> 1.76
    
    Args:
        value_str: String value from screener.in
    
    Returns:
        float: Parsed number or None if parsing fails
    """
    if not value_str or value_str.strip() in ['', '-', 'N/A']:
        return None
    
    try:
        # Remove commas, spaces, and common suffixes
        clean_str = value_str.strip()
        clean_str = clean_str.replace(',', '')
        clean_str = clean_str.replace(' ', '')
        clean_str = clean_str.replace('%', '')
        clean_str = clean_str.replace('₹', '')
        
        # Handle Cr. (Crores) - multiply by 10,000,000
        if 'Cr' in clean_str or 'cr' in clean_str:
            clean_str = clean_str.replace('Cr.', '').replace('Cr', '').replace('cr', '')
            return float(clean_str) * 10000000
        
        # Handle L (Lakhs) - multiply by 100,000
        if 'L' in clean_str or 'l' in clean_str:
            clean_str = clean_str.replace('L', '').replace('l', '')
            return float(clean_str) * 100000
        
        # Regular number
        return float(clean_str)
    
    except Exception as e:
        print(f"⚠️ Failed to parse number '{value_str}': {e}")
        return None


def scrape_screener_financials(stock_symbol: str) -> Dict[str, Any]:
    """
    Scrape financial data from screener.in
    
    Args:
        stock_symbol: Stock symbol (e.g., 'TATASTEEL', 'RELIANCE')
    
    Returns:
        Dict with financial metrics
    """
    print(f"\n{'='*60}")
    print(f"🌐 Scraping screener.in for {stock_symbol}")
    print(f"{'='*60}\n")
    
    # Find the company URL
    company_url = search_stock_on_screener(stock_symbol)
    if not company_url:
        return {"success": False, "error": "Stock not found on screener.in"}
    
    try:
        # Fetch the page
        print(f"📄 Fetching page: {company_url}")
        resp = requests.get(company_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Initialize data dictionary
        data = {
            "success": True,
            "source_url": company_url,
            "stock_symbol": stock_symbol
        }
        
        print("📊 Parsing financial metrics from screener.in...")
        
        # CORRECT METHOD: Parse using actual HTML structure
        # Screener.in uses: <li class="flex flex-space-between">
        #                     <span class="name">Metric Name</span>
        #                     <span class="value">₹ <span class="number">123</span> Cr.</span>
        #                   </li>
        
        # Field mapping for all metrics we want to extract
        field_mapping = {
            'Market Cap': 'market_cap',
            'Current Price': 'current_price',
            'High / Low': 'high_low',
            'Stock P/E': 'pe_ratio',
            'Book Value': 'book_value',
            'Dividend Yield': 'dividend_yield',
            'ROCE': 'roce',
            'ROE': 'roe',
            'Face Value': 'face_value',
            'Promoter holding': 'promoter_holding',
            'Promoter Holding': 'promoter_holding',
            'FII holding': 'fii_holding',
            'FII Holding': 'fii_holding',
            'DII holding': 'dii_holding',
            'DII Holding': 'dii_holding',
            'Debt to equity': 'debt_to_equity',
            'Debt to Equity': 'debt_to_equity',
            'Free Cash Flow': 'free_cash_flow',
            'PEG Ratio': 'peg_ratio',
            'OPM': 'operating_margin',
            'EV/EBITDA': 'ev_ebitda',
            'EV / EBITDA': 'ev_ebitda',
            'Enterprise Value': 'enterprise_value',
            'Volume': 'volume',
            'Dividend Payout': 'dividend_payout',
            'Payout Ratio': 'dividend_payout'
        }
        
        # Parse all <li> elements with class "flex flex-space-between"
        all_list_items = soup.find_all('li', class_='flex')
        
        for li in all_list_items:
            # Find name and value spans
            name_span = li.find('span', class_='name')
            
            if name_span:
                name = name_span.get_text(strip=True)
                
                # Get the value - it's in a span with class "value" or directly in "number" span
                value_span = li.find('span', class_='value')
                if value_span:
                    # Get full text including the number span inside
                    full_value = value_span.get_text(strip=True)
                else:
                    # Try to get number span directly
                    number_span = li.find('span', class_='number')
                    if number_span:
                        full_value = number_span.get_text(strip=True)
                    else:
                        continue
                
                # Check if this metric is in our mapping
                if name in field_mapping:
                    field_name = field_mapping[name]
                    
                    # Special handling for High / Low (contains two values)
                    if name == 'High / Low':
                        # Extract both numbers
                        numbers = li.find_all('span', class_='number')
                        if len(numbers) >= 2:
                            data['high_52week'] = parse_number(numbers[0].get_text(strip=True))
                            data['low_52week'] = parse_number(numbers[1].get_text(strip=True))
                            print(f"  ✓ High: {numbers[0].get_text(strip=True)} / Low: {numbers[1].get_text(strip=True)}")
                    else:
                        # Parse the value
                        parsed_value = parse_number(full_value)
                        if parsed_value is not None:
                            data[field_name] = parsed_value
                            print(f"  ✓ {name}: {full_value}")
        
        # Parse balance sheet for Total Assets and Debt
        print("\n💰 Parsing balance sheet data...")
        balance_sheet = soup.find('section', {'id': 'balance-sheet'})
        if balance_sheet:
            table = balance_sheet.find('table')
            if table:
                tbody = table.find('tbody')
                if tbody:
                    rows = tbody.find_all('tr')
                    equity_capital = None
                    reserves = None
                    
                    for row in rows:
                        cells = row.find_all('td')
                        if cells and len(cells) >= 2:
                            name = cells[0].get_text(strip=True)
                            value = cells[1].get_text(strip=True)
                            
                            # Map balance sheet items
                            if 'Total Assets' in name and 'total_assets' not in data:
                                # Value is in Crores
                                parsed = parse_number(value + ' Cr')
                                if parsed:
                                    data['total_assets'] = parsed
                                    print(f"  ✓ Total Assets: {value} Cr")
                            
                            elif 'Borrowings' in name and 'total_debt' not in data:
                                # Borrowings = Debt
                                parsed = parse_number(value + ' Cr')
                                if parsed:
                                    data['total_debt'] = parsed
                                    print(f"  ✓ Total Debt (Borrowings): {value} Cr")
                            
                            elif 'Equity Capital' in name:
                                equity_capital = parse_number(value + ' Cr')
                            
                            elif 'Reserves' in name:
                                reserves = parse_number(value + ' Cr')
                    
                    # Calculate Debt to Equity if we have the data
                    if data.get('total_debt') and equity_capital and reserves:
                        total_equity = equity_capital + reserves
                        debt_to_equity = data['total_debt'] / total_equity
                        data['debt_to_equity'] = debt_to_equity
                        print(f"  ✓ Debt to Equity (calculated): {debt_to_equity:.2f}")
        
        # Parse annual profit-loss for better margin data and dividend payout
        print("\n� Parsing annual profit & loss...")
        profit_loss = soup.find('section', {'id': 'profit-loss'})
        if profit_loss:
            table = profit_loss.find('table')
            if table:
                tbody = table.find('tbody')
                if tbody:
                    rows = tbody.find_all('tr')
                    sales_value = None
                    net_profit_value = None
                    
                    for row in rows:
                        cells = row.find_all('td')
                        if cells and len(cells) >= 2:
                            row_name = cells[0].get_text(strip=True)
                            # Get TTM (last column) or second-to-last if TTM is empty
                            ttm_value = cells[-1].get_text(strip=True)
                            prev_value = cells[-2].get_text(strip=True) if len(cells) > 2 else None
                            
                            # Use TTM if available, otherwise use previous year
                            value = ttm_value if ttm_value and ttm_value != '' else prev_value
                            
                            # Map annual metrics
                            if 'OPM' in row_name and '%' in row_name:
                                parsed = parse_number(value)
                                if parsed:
                                    data['operating_margin'] = parsed
                                    print(f"  ✓ Operating Margin (OPM): {value}")
                            
                            elif 'Sales' in row_name and '+' in row_name:
                                sales_value = parse_number(value + ' Cr')
                            
                            elif 'Net Profit' in row_name and '+' in row_name:
                                net_profit_value = parse_number(value + ' Cr')
                            
                            elif 'Dividend Payout' in row_name and '%' in row_name:
                                if 'dividend_payout' not in data:
                                    parsed = parse_number(value)
                                    if parsed and parsed > 0:  # Only positive payout ratios
                                        data['dividend_payout'] = parsed
                                        print(f"  ✓ Dividend Payout: {value}")
                    
                    # Calculate profit margin if we have sales and net profit
                    if sales_value and net_profit_value and 'profit_margin' not in data:
                        profit_margin = (net_profit_value / sales_value) * 100
                        data['profit_margin'] = profit_margin
                        print(f"  ✓ Profit Margin (calculated): {profit_margin:.2f}%")
        
        # Parse shareholding pattern
        print("\n👥 Parsing shareholding pattern...")
        shareholding_section = soup.find('section', {'id': 'shareholding'})
        if shareholding_section:
            table = shareholding_section.find('table')
            if table:
                tbody = table.find('tbody')
                if tbody:
                    rows = tbody.find_all('tr')
                    for row in rows:
                        cells = row.find_all('td')
                        if cells and len(cells) >= 2:
                            # First cell has the category name
                            category_cell = cells[0]
                            category_text = category_cell.get_text(strip=True)
                            
                            # Last cell has the latest value
                            latest_value = cells[-1].get_text(strip=True)
                            
                            # Map shareholding categories
                            if 'Promoter' in category_text and 'promoter_holding' not in data:
                                parsed = parse_number(latest_value)
                                if parsed:
                                    data['promoter_holding'] = parsed
                                    print(f"  ✓ Promoter Holding: {latest_value}")
                            
                            elif 'FII' in category_text and 'fii_holding' not in data:
                                parsed = parse_number(latest_value)
                                if parsed:
                                    data['fii_holding'] = parsed
                                    print(f"  ✓ FII Holding: {latest_value}")
                            
                            elif 'DII' in category_text and 'dii_holding' not in data:
                                parsed = parse_number(latest_value)
                                if parsed:
                                    data['dii_holding'] = parsed
                                    print(f"  ✓ DII Holding: {latest_value}")
        
        # Try to get additional metrics from the analysis section
        print("\n🔬 Parsing analysis section...")
        analysis_section = soup.find('section', {'id': 'analysis'})
        if analysis_section:
            # Look for any list items with metrics
            for li in analysis_section.find_all('li', class_='flex'):
                name_span = li.find('span', class_='name')
                if name_span:
                    name = name_span.get_text(strip=True)
                    value_span = li.find('span', class_='value')
                    if value_span:
                        value = value_span.get_text(strip=True)
                        
                        # Check for missing metrics
                        if 'Debt to equity' in name or 'Debt to Equity' in name:
                            if 'debt_to_equity' not in data:
                                parsed = parse_number(value)
                                if parsed:
                                    data['debt_to_equity'] = parsed
                                    print(f"  ✓ Debt to Equity: {value}")
                        
                        elif 'Enterprise Value' in name and 'enterprise_value' not in data:
                            parsed = parse_number(value)
                            if parsed:
                                data['enterprise_value'] = parsed
                                print(f"  ✓ Enterprise Value: {value}")
                        
                        elif 'EV/EBITDA' in name or 'EV / EBITDA' in name:
                            if 'ev_ebitda' not in data:
                                parsed = parse_number(value)
                                if parsed:
                                    data['ev_ebitda'] = parsed
                                    print(f"  ✓ EV/EBITDA: {value}")
        
        # Parse company name
        company_name_elem = soup.find('h1')
        if not company_name_elem:
            company_name_elem = soup.find('h1', class_='h2')
        if company_name_elem:
            data['company_name'] = company_name_elem.get_text(strip=True)
            print(f"\n🏢 Company: {data['company_name']}")
        
        print(f"\n✅ Successfully scraped {len([k for k in data.keys() if k not in ['success', 'source_url', 'stock_symbol', 'company_name']])} financial metrics")
        
        return data
        
    except Exception as e:
        print(f"❌ Error scraping screener.in: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


def get_screener_financial_data(stock_symbol: str) -> Optional[Dict[str, Any]]:
    """
    Main function to get financial data from screener.in
    
    Args:
        stock_symbol: Stock symbol (e.g., 'TATASTEEL.NS', 'RELIANCE')
    
    Returns:
        Dict with financial data or None if failed
    """
    # Clean the symbol
    clean_symbol = stock_symbol.replace('.NS', '').replace('.BO', '').upper()
    
    # Scrape the data
    data = scrape_screener_financials(clean_symbol)
    
    if data.get('success'):
        return data
    else:
        print(f"❌ Failed to get data from screener.in: {data.get('error')}")
        return None


# Test the scraper
if __name__ == "__main__":
    print("🧪 Testing Screener.in Scraper\n")
    
    # Test with Tata Steel
    test_symbols = ["TATASTEEL", "RELIANCE", "TCS"]
    
    for symbol in test_symbols:
        print(f"\n{'='*70}")
        print(f"Testing: {symbol}")
        print('='*70)
        
        data = get_screener_financial_data(symbol)
        
        if data and data.get('success'):
            print(f"\n✅ SUCCESS! Scraped data for {symbol}:")
            print(f"\nKey Metrics:")
            
            metrics = [
                ('Market Cap', 'market_cap'),
                ('Current Price', 'current_price'),
                ('PE Ratio', 'pe_ratio'),
                ('Dividend Yield', 'dividend_yield'),
                ('Debt to Equity', 'debt_to_equity'),
                ('Enterprise Value', 'enterprise_value'),
                ('EV/EBITDA', 'ev_ebitda'),
                ('Operating Margin', 'operating_margin'),
                ('Profit Margin', 'profit_margin'),
                ('Promoter Holding', 'promoter_holding'),
                ('FII Holding', 'fii_holding'),
                ('DII Holding', 'dii_holding'),
                ('Total Assets', 'total_assets'),
                ('Total Debt', 'total_debt')
            ]
            
            for label, key in metrics:
                value = data.get(key)
                if value is not None:
                    print(f"  {label}: {value}")
        else:
            print(f"❌ FAILED to scrape data for {symbol}")
        
        time.sleep(2)  # Be nice to the server
    
    print("\n🏁 Testing complete!")
