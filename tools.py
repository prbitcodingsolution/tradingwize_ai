import yfinance as yf
import requests
from typing import Dict, List, Optional
from models import (
    StockValidation, CompanyData, FinancialData, 
    MarketData, CompanyReport, ScenarioAnalysis, Summary,
    CompanySnapshot, BusinessOverview, SWOTAnalysis
)
from datetime import datetime, timedelta
import json
import os
from dotenv import load_dotenv
import time
from api_logger import api_logger, log_api_call, should_wait_for_rate_limit
from utils.model_config import get_model, get_client
from pydantic_ai import Agent
from pydantic import BaseModel, Field

client = get_client()

load_dotenv()
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

# Check if Tavily API key is valid
if not TAVILY_API_KEY or TAVILY_API_KEY.strip() == "":
    print("⚠️ WARNING: TAVILY_API_KEY not found in .env file")
    print("⚠️ Tavily search will be disabled. Using screener.in and yfinance only.")
    TAVILY_ENABLED = False
else:
    TAVILY_ENABLED = True
    print(f"✅ Tavily API key loaded: {TAVILY_API_KEY[:10]}...")


class StockTools:
    """Collection of tools for stock analysis"""
    
    @staticmethod
    def _search_with_tavily(query: str, domain: Optional[List[str]] = None) -> tuple:
        """
        Use Tavily API to search for stock information
        Returns: (results_list, answer_string)
        """
        # Check if Tavily is enabled
        if not TAVILY_ENABLED:
            print("⚠️ Tavily search skipped (API key not configured)")
            return [], ''
        
        # Check if API key is valid
        if not TAVILY_API_KEY or TAVILY_API_KEY.strip() == "":
            print("⚠️ Tavily search skipped (API key empty)")
            return [], ''
        
        # Check rate limits before making request
        should_wait, wait_time = should_wait_for_rate_limit('tavily')
        if should_wait:
            api_logger.logger.warning(f"⏳ Tavily rate limit reached, waiting {wait_time} seconds")
            time.sleep(min(wait_time, 60))  # Cap wait time at 60 seconds
        
        start_time = time.time()
        error = None
        response_status = None
        request_size = 0
        response_size = 0
        
        try:
            url = "https://api.tavily.com/search"
            headers = {
                "Content-Type": "application/json; charset=utf-8"
            }
            payload = {
                "api_key": TAVILY_API_KEY,
                "query": query,
                "search_depth": "advanced",
                "max_results": 5,
                "include_answer": True,
                "include_domains": domain 
            }
            
            # Calculate request size
            import json
            request_size = len(json.dumps(payload).encode('utf-8'))
            
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            response.encoding = 'utf-8'
            response_status = response.status_code
            response_size = len(response.content)
            
            if response.status_code == 200:
                data = response.json()
                results = data.get('results', [])
                answer = data.get('answer', '')
                
                # Clean answer to remove problematic characters
                if answer:
                    answer = answer.encode('ascii', 'ignore').decode('ascii')
                
                # Log successful request
                api_logger.log_request(
                    api_name='tavily',
                    endpoint='/search',
                    method='POST',
                    response_status=response_status,
                    response_time=time.time() - start_time,
                    request_size=request_size,
                    response_size=response_size
                )
                
                return results, answer
            elif response.status_code == 401:
                # Unauthorized - API key is invalid or expired
                error = f"HTTP 401: Unauthorized - Tavily API key is invalid or expired"
                print(f"❌ {error}")
                print(f"⚠️ Please check your TAVILY_API_KEY in .env file")
                print(f"⚠️ Continuing without Tavily search (using screener.in and yfinance only)")
                # Disable Tavily for the rest of the session
                globals()['TAVILY_ENABLED'] = False
                return [], ''
            else:
                error = f"HTTP {response.status_code}: {response.text[:200]}"
                raise Exception(error)
                
        except Exception as e:
            error = str(e)
            
            # Check if it's an authentication error
            if "401" in error or "Unauthorized" in error:
                print(f"❌ Tavily API authentication failed")
                print(f"⚠️ Disabling Tavily for this session")
                globals()['TAVILY_ENABLED'] = False
            
            api_logger.log_request(
                api_name='tavily',
                endpoint='/search',
                method='POST',
                response_status=response_status,
                response_time=time.time() - start_time,
                request_size=request_size,
                response_size=response_size,
                error=error
            )
            print(f"Tavily search error: {e}")
            return [], ''
    
    @staticmethod
    def _fetch_fresh_data_from_tavily(company_name: str, stock_symbol: str, current_data: Dict) -> Dict:
        """
        Fetch fresh stock data from Tavily web search when yfinance data is stale
        
        Args:
            company_name: Name of the company
            stock_symbol: Stock ticker symbol
            current_data: Current data from yfinance (for comparison)
            
        Returns:
            Dict with 'success', 'data', and 'updated_fields' keys
        """
        import json as json_module  # Import with alias to avoid shadowing
        
        try:
            print(f"\n🌐 Fetching fresh data for {company_name} ({stock_symbol}) from web...")
            
            # Search for latest financial data
            search_queries = [
                f"{company_name} {stock_symbol} latest financial results revenue profit 2024 2025 2026",
                f"{company_name} stock latest quarterly results earnings",
                f"{company_name} {stock_symbol} PE ratio market cap latest",
                f"{company_name} balance sheet total debt liabilities latest"
            ]
            
            all_results = []
            all_answers = []
            
            for query in search_queries:
                results, answer = StockTools._search_with_tavily(
                    query,
                    domain=["screener.in", "moneycontrol.com", "nseindia.com", "bseindia.com"]
                )
                all_results.extend(results)
                if answer:
                    all_answers.append(answer)
            
            if not all_results and not all_answers:
                print(f"⚠️ No results from Tavily search")
                return {'success': False, 'data': {}, 'updated_fields': []}
            
            # Combine all content for LLM analysis
            combined_content = "\n\n".join(all_answers)
            for result in all_results[:5]:  # Top 5 results
                combined_content += f"\n\n{result.get('title', '')}\n{result.get('content', '')}"
            
            # Use LLM to extract structured financial data
            print(f"🤖 Analyzing web data with LLM...")
            
            extraction_prompt = f"""You are a financial data extraction expert. Extract the LATEST financial data for {company_name} ({stock_symbol}) from the following web search results.

Web Search Results:
{combined_content[:8000]}

Extract and return ONLY the following data in JSON format:
{{
    "revenue": <latest annual/TTM revenue in actual currency value, not in crores/millions>,
    "net_profit": <latest net profit in actual currency value>,
    "total_debt": <latest total debt in actual currency value>,
    "total_liabilities": <latest total liabilities in actual currency value>,
    "pe_ratio": <latest PE ratio as a number>,
    "pb_ratio": <latest PB ratio as a number>,
    "eps": <latest EPS as a number>,
    "market_cap": <latest market cap in actual currency value>,
    "current_price": <latest stock price>,
    "ceo": "<CEO name>",
    "data_date": "<date of this data in YYYY-MM-DD format>"
}}

CRITICAL RULES:
1. Extract ONLY from the provided web search results
2. Use the MOST RECENT data available
3. Convert all Indian Rupee values from Crores to actual values (multiply by 10,000,000)
4. If a field is not found, use null
5. Return ONLY valid JSON, no explanations
6. Ensure Total Liabilities >= Total Debt (if both present)
7. Verify PE ratio is reasonable (typically 0-100 for most stocks)

Return JSON:"""

            try:
                # Use the model name string directly for OpenAI client
                model_name = "openai/gpt-4o-mini"  # Use a reliable model for extraction
                
                response = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": "You are a financial data extraction expert. Extract data accurately and return valid JSON only."},
                        {"role": "user", "content": extraction_prompt}
                    ],
                    temperature=0.1,
                    max_tokens=1000
                )
                
                response_text = response.choices[0].message.content.strip()
                
                # Parse JSON from response
                if "```json" in response_text:
                    response_text = response_text.split("```json")[1].split("```")[0].strip()
                elif "```" in response_text:
                    response_text = response_text.split("```")[1].split("```")[0].strip()
                
                extracted_data = json_module.loads(response_text)
                
                # Map extracted data to yfinance field names
                fresh_data = {}
                updated_fields = []
                
                if extracted_data.get('revenue') is not None:
                    fresh_data['totalRevenue'] = extracted_data['revenue']
                    updated_fields.append('revenue')
                
                if extracted_data.get('net_profit') is not None:
                    fresh_data['netIncome'] = extracted_data['net_profit']
                    updated_fields.append('net_profit')
                
                if extracted_data.get('total_debt') is not None:
                    fresh_data['totalDebt'] = extracted_data['total_debt']
                    updated_fields.append('total_debt')
                
                if extracted_data.get('total_liabilities') is not None:
                    fresh_data['totalLiabilities'] = extracted_data['total_liabilities']
                    updated_fields.append('total_liabilities')
                
                if extracted_data.get('pe_ratio') is not None:
                    fresh_data['trailingPE'] = extracted_data['pe_ratio']
                    updated_fields.append('pe_ratio')
                
                if extracted_data.get('pb_ratio') is not None:
                    fresh_data['priceToBook'] = extracted_data['pb_ratio']
                    updated_fields.append('pb_ratio')
                
                if extracted_data.get('eps') is not None:
                    fresh_data['trailingEps'] = extracted_data['eps']
                    updated_fields.append('eps')
                
                if extracted_data.get('market_cap') is not None:
                    fresh_data['marketCap'] = extracted_data['market_cap']
                    updated_fields.append('market_cap')
                
                if extracted_data.get('current_price') is not None:
                    fresh_data['currentPrice'] = extracted_data['current_price']
                    updated_fields.append('current_price')
                
                print(f"✅ Extracted {len(updated_fields)} fields from web data:")
                for field in updated_fields:
                    print(f"   • {field}")
                
                return {
                    'success': True,
                    'data': fresh_data,
                    'updated_fields': updated_fields,
                    'source': 'tavily_web_search',
                    'data_date': extracted_data.get('data_date', 'unknown')
                }
                
            except json_module.JSONDecodeError as e:
                print(f"❌ Failed to parse LLM response as JSON: {e}")
                print(f"Response was: {response_text[:200]}")
                return {'success': False, 'data': {}, 'updated_fields': []}
            
        except Exception as e:
            print(f"❌ Error fetching fresh data from Tavily: {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'data': {}, 'updated_fields': []}
    
    @staticmethod
    def validate_stock(stock_name: str) -> StockValidation:
        """
        Tool 0: Validate stock name using Tavily web search and check for variants
        Enhanced with smart auto-selection for popular companies
        """
        try:
            stock_name_clean = stock_name.strip()
            
            # Apply typo correction FIRST before any processing
            stock_name_upper = stock_name_clean.upper()
            
            # Handle common typos for major companies
            typo_mappings = {
                'RELIENCE': 'RELIANCE',  # Common typo: missing 'a'
                'RELIENC': 'RELIANCE',   # Common typo: missing 'a' and 'e'
                'RELIACE': 'RELIANCE',   # Common typo: missing 'n'
                'RELIANC': 'RELIANCE',   # Common typo: missing 'e'
                'ADNAI': 'ADANI',        # Common typo: swapped letters
                'ADNANI': 'ADANI',       # Common typo: extra 'n'
                'TAAT': 'TATA',          # Common typo: swapped letters
                'TATAA': 'TATA',         # Common typo: extra 'a'
            }
            
            # Step 1: Use Tavily to search for the stock (restricted to screener.in)
            # Try multiple search variations for better results
            search_queries = [
                f"{stock_name_clean} screener.in stock symbol ticker NSE BSE",
                f"{stock_name_clean} NSE BSE stock ticker symbol",
                f"{stock_name_clean} share price screener.in",
                f'"{stock_name_clean}" stock symbol India NSE'
            ]
            
            search_results = []
            answer = ""
            
            # Try each search query until we get good results
            for query in search_queries:
                results, ans = StockTools._search_with_tavily(query)
                search_results.extend(results)
                if ans:
                    answer += ans + "\n"
                # If we got good results, we can stop
                if len(results) >= 2:
                    break
            
            # Step 2: Smart extraction of stock symbols
            import re
            stock_name_upper = stock_name_clean.upper()
            
            # Priority list - try these first
            priority_symbols = [
                f"{stock_name_upper}.NS",  # NSE (India) - highest priority
                f"{stock_name_upper}.BO",  # BSE (India)
                stock_name_upper,          # Direct symbol (US stocks)
            ]
            
            # Manual mappings removed - relying on Tavily search results

            
            # Extract symbols from Tavily answer (most reliable)
            extracted_symbols = []
            if answer:
                # Look for explicit ticker mentions like "ticker symbol ONGC" or "symbol: ONGC.NS"
                ticker_mentions = re.findall(
                    r'(?:ticker symbol|symbol|trades under)\s+(?:is\s+)?([A-Z]{2,15}(?:\.[A-Z]{2,3})?)',
                    answer.upper()
                )
                extracted_symbols.extend(ticker_mentions)
                
                # Look for exchange-qualified symbols (e.g., "ONGC.NS", "RELIANCE.NS", "AAPL")
                qualified_symbols = re.findall(r'\b([A-Z]{2,15}\.[A-Z]{2,3})\b', answer.upper())
                extracted_symbols.extend(qualified_symbols)
            
            # Extract from search result titles and URLs (very reliable)
            for result in search_results[:3]:  # Top 3 results only
                title = result.get('title', '').upper()
                url = result.get('url', '').upper()
                content = result.get('content', '').upper()
                
                # Look for symbols in title like "NSE:ONGC" or "(RELIANCE.NS)"
                title_symbols = re.findall(r'(?:NSE:|BSE:|\()([A-Z]{2,15}(?:\.[A-Z]{2,3})?)', title)
                extracted_symbols.extend(title_symbols)
                
                # Look for symbols in URL like "/quote/RELIANCE.NS" or "/company/PHYSICS"
                url_symbols = re.findall(r'/(?:quote|symbol|equities|company)/([A-Z]{2,15}(?:\.[A-Z]{2,3})?)', url)
                extracted_symbols.extend(url_symbols)
                
                # Special handling for screener.in URLs
                if 'SCREENER.IN' in url:
                    # Extract company symbols from screener URLs
                    screener_symbols = re.findall(r'SCREENER\.IN/COMPANY/([A-Z0-9]+)', url)
                    for symbol in screener_symbols:
                        extracted_symbols.append(f"{symbol}.NS")
                        extracted_symbols.append(f"{symbol}.BO")
                
                # Look for "Ticker Symbol RELIANCE" in content
                content_symbols = re.findall(
                    r'(?:ticker symbol|stock symbol|symbol)\s+(?:is\s+)?([A-Z]{2,15}(?:\.[A-Z]{2,3})?)',
                    content
                )
                extracted_symbols.extend(content_symbols)
            
            # Add intelligent fallback patterns for common company name variations
            fallback_patterns = []
            
            # Fallback logic removed - relying on Tavily search results
            
            if len(stock_name_clean.split()) >= 1:
                # For compound words or single words, try finding generic matches if search failed
                # But prefer search results
                pass
            
            # Add fallback patterns to extracted symbols
            extracted_symbols.extend(fallback_patterns)
            
            # Combine: extracted symbols first (most reliable), then priority symbols
            search_terms = []
            
            # Add extracted symbols first (deduplicated)
            for symbol in extracted_symbols:
                clean_symbol = symbol.strip()
                if clean_symbol and clean_symbol not in search_terms:
                    # Filter out common words that aren't stock symbols
                    if clean_symbol not in ['STOCK', 'PRICE', 'UNDER', 'INDIA', 'EXCHANGE', 
                                           'NATIONAL', 'BOMBAY', 'MARKET', 'CORP', 'LTD',
                                           'LIMITED', 'INC', 'COMPANY', 'THE', 'AND', 'FOR']:
                        search_terms.append(clean_symbol)
            
            # Add priority symbols if not already present
            for symbol in priority_symbols:
                if symbol not in search_terms:
                    search_terms.append(symbol)
            
            # Step 3: Validate each potential symbol with yfinance
            variants = []
            for term in search_terms[:50]:  # Limit to first 50 to find more variants
                try:
                    # Check rate limits before making request
                    should_wait, wait_time = should_wait_for_rate_limit('yfinance')
                    if should_wait:
                        api_logger.logger.warning(f"⏳ YFinance rate limit reached, waiting {wait_time} seconds")
                        time.sleep(min(wait_time, 30))  # Cap wait time at 30 seconds
                    start_time = time.time()
                    ticker = yf.Ticker(term)
                    info = ticker.info
                    
                    # Log the request
                    api_logger.log_request(
                        api_name='yfinance',
                        endpoint=f'/ticker/{term}/info',
                        method='GET',
                        response_status=200 if info else 404,
                        response_time=time.time() - start_time
                    )
                    
                    # Check if this is a valid stock
                    if info and 'symbol' in info and info.get('symbol'):
                        # Verify it has actual data
                        if info.get('longName') or info.get('shortName'):
                            symbol = info.get('symbol')
                            name = info.get('longName') or info.get('shortName', term)
                            
                            # Avoid duplicates
                            if not any(v['symbol'] == symbol for v in variants):
                                variants.append({
                                    'symbol': symbol,
                                    'name': name,
                                    'exchange': info.get('exchange', 'Unknown')
                                })
                except Exception as e:
                    # Log the error
                    api_logger.log_request(
                        api_name='yfinance',
                        endpoint=f'/ticker/{term}/info',
                        method='GET',
                        response_status=500,
                        response_time=time.time() - start_time if 'start_time' in locals() else None,
                        error=str(e)
                    )
                    continue
            
            # Step 4: Smart variant selection - Always ask user for multiple different companies
            if not variants:
                return StockValidation(
                    is_valid=False,
                    message=f"❌ Stock '{stock_name}' not found in the market.\n\nThis could mean:\n• The company is not publicly traded\n• The stock symbol might be incorrect\n• The company might be private or unlisted\n\nPlease try:\n• A different stock name or symbol\n• Check if the company is publicly listed\n• Verify the correct ticker symbol"
                )
            
            if len(variants) == 1:
                # Single match found
                return StockValidation(
                    is_valid=True,
                    stock_symbol=variants[0]['symbol'],
                    stock_name=variants[0]['name'],
                    variants=variants,
                    needs_clarification=False,
                    message=f"Found stock: {variants[0]['name']} ({variants[0]['symbol']})"
                )
            
            
            # Multiple variants found - logic removed to always ask user for clarification
            
            # Fallback - multiple variants, ask user to choose
            print(f"🔄 Fallback: Asking user to choose from {len(variants)} variants")
            return StockValidation(
                is_valid=False,
                stock_symbol=None,
                stock_name=None,
                variants=variants,
                needs_clarification=True,
                message=f"Found {len(variants)} different stocks matching '{stock_name}'. Please specify which one you want to analyze."
            )
            
        except Exception as e:
            return StockValidation(
                is_valid=False,
                message=f"Error validating stock: {str(e)}"
            )

    
    @staticmethod
    def _extract_financial_data_from_web(stock_symbol: str, search_results: List[Dict], answer: str) -> Dict:
        """
        Extract financial insights from Tavily search results (screener.in focused)
        """
        insights = {
            'revenue_info': '',
            'profit_info': '',
            'market_analysis': '',
            'sector_info': '',
            'competitors': [],
            'recent_developments': [],
            'peer_comparison': []  # New field for screener.in peer data
        }
        
        # Combine all content for analysis
        all_content = answer + "\n"
        for result in search_results:
            all_content += result.get('content', '') + "\n"
        
        # Extract key information patterns
        content_lower = all_content.lower()
        
        # Look for revenue mentions
        if 'revenue' in content_lower or 'sales' in content_lower:
            for result in search_results:
                if 'revenue' in result.get('content', '').lower():
                    insights['revenue_info'] = result.get('content', '')[:300]
                    break
        
        # Look for profit/earnings mentions
        if 'profit' in content_lower or 'earnings' in content_lower or 'net income' in content_lower:
            for result in search_results:
                if any(word in result.get('content', '').lower() for word in ['profit', 'earnings', 'net income']):
                    insights['profit_info'] = result.get('content', '')[:300]
                    break
        
        # Extract sector information
        if 'sector' in content_lower or 'industry' in content_lower:
            for result in search_results:
                if 'sector' in result.get('content', '').lower() or 'industry' in result.get('content', '').lower():
                    insights['sector_info'] = result.get('content', '')[:200]
                    break
        
        # Enhanced competitor extraction for screener.in data
        import re
        
        # Look for screener.in peer comparison data
        for result in search_results:
            url = result.get('url', '')
            content = result.get('content', '')
            title = result.get('title', '')
            
            # Check if this is a screener.in result
            if 'screener.in' in url:
                # Look for peer comparison indicators
                if any(keyword in content.lower() for keyword in ['peer', 'comparison', 'similar companies', 'competitors']):
                    insights['peer_comparison'].append({
                        'source': 'screener.in',
                        'content': content,
                        'url': url,
                        'title': title
                    })
                
                # Extract company names from screener.in content
                # Look for patterns like "Company Name Ltd" or "Company Corp"
                company_patterns = [
                    r'([A-Z][a-zA-Z\s&]+(?:Ltd|Limited|Corp|Corporation|Inc|Company))',
                    r'([A-Z][a-zA-Z\s&]+(?:Bank|Industries|Motors|Steel|Oil|Gas|Power|Energy))',
                ]
                
                for pattern in company_patterns:
                    matches = re.findall(pattern, content)
                    for match in matches:
                        if len(match.strip()) > 3 and match.strip() not in insights['competitors']:
                            insights['competitors'].append(match.strip())
        
        # If we have screener.in peer data, extract structured competitor info
        if insights['peer_comparison']:
            insights['competitors'] = StockTools._extract_screener_peers(insights['peer_comparison'])
        
        # Fallback: Look for competitor mentions in general content
        if not insights['competitors']:
            competitor_patterns = ['competitor', 'rival', 'vs', 'compared to']
            for result in search_results:
                content = result.get('content', '')
                if any(pattern in content.lower() for pattern in competitor_patterns):
                    # Extract company names (simple heuristic)
                    words = content.split()
                    for i, word in enumerate(words):
                        if word in ['Inc.', 'Ltd.', 'Corp.', 'Corporation', 'Limited']:
                            if i > 0:
                                company_name = ' '.join(words[max(0, i-2):i+1])
                                if company_name not in insights['competitors']:
                                    insights['competitors'].append(company_name)
        
        return insights
    
    @staticmethod
    def _extract_screener_peers(peer_data: List[Dict]) -> List[str]:
        """
        Extract peer companies from screener.in comparison data with advanced parsing
        """
        peers = []
        
        for data in peer_data:
            content = data.get('content', '')
            url = data.get('url', '')
            
            # Check if this is specifically a screener.in peer comparison page
            if 'screener.in' in url and ('peer' in url.lower() or 'comparison' in content.lower()):
                
                # Method 1: Extract from structured peer comparison table
                peers_from_table = StockTools._parse_screener_peer_table(content)
                peers.extend(peers_from_table)
                
                # Method 2: Extract company names from content
                import re
                
                # Look for Indian company patterns specifically
                indian_company_patterns = [
                    # Pattern for "Company Name Ltd" or "Company Name Limited"
                    r'([A-Z][a-zA-Z\s&\(\)]+(?:Ltd|Limited|Corporation|Corp)\.?)',
                    # Pattern for "Company Name" followed by stock-related keywords
                    r'([A-Z][a-zA-Z\s&]+(?:Oil|Gas|Petroleum|Industries|Motors|Steel|Bank|Power|Energy|Chemicals|Pharma))',
                    # Pattern for company names in peer comparison context
                    r'(?:compared to|vs|versus|peer)\s+([A-Z][a-zA-Z\s&]+(?:Ltd|Limited|Corp|Corporation))',
                ]
                
                for pattern in indian_company_patterns:
                    matches = re.findall(pattern, content, re.IGNORECASE)
                    for match in matches:
                        clean_name = match.strip().rstrip('.')
                        # Filter out common false positives
                        if (len(clean_name) > 5 and 
                            clean_name not in peers and
                            not any(word in clean_name.lower() for word in 
                                   ['screener', 'website', 'company', 'limited company', 'the company', 'this company'])):
                            peers.append(clean_name)
        
        # Remove duplicates while preserving order
        unique_peers = []
        seen = set()
        for peer in peers:
            if peer.lower() not in seen:
                unique_peers.append(peer)
                seen.add(peer.lower())
        
        return unique_peers[:6]  # Return top 6 peers
    
    @staticmethod
    def _parse_screener_peer_table(content: str) -> List[str]:
        """
        Parse screener.in peer comparison table to extract company names
        """
        peers = []
        
        # Split content into lines for analysis
        lines = content.split('\n')
        
        # Look for table-like structures
        for i, line in enumerate(lines):
            line = line.strip()
            
            # Skip empty lines
            if not line:
                continue
                
            # Look for lines that might contain company names in a table
            # Screener.in typically has company names followed by metrics
            
            # Pattern 1: Lines with company names followed by numbers (table rows)
            import re
            
            # Look for patterns like "Company Name    123.45    67.89    ..."
            table_row_pattern = r'^([A-Z][a-zA-Z\s\&\(\)]+(?:Ltd|Limited|Corp|Corporation|Oil|Gas|Petroleum|Industries|Bank|Power))\s+[\d\.,\s\-\%]+$'
            match = re.match(table_row_pattern, line, re.IGNORECASE)
            if match:
                company_name = match.group(1).strip()
                if len(company_name) > 3:
                    peers.append(company_name)
            
            # Pattern 2: Look for company names in peer comparison sections
            if any(keyword in line.lower() for keyword in ['peer', 'comparison', 'similar', 'competitor']):
                # Extract company names from this section
                company_matches = re.findall(r'([A-Z][a-zA-Z\s\&]+(?:Ltd|Limited|Corp|Corporation|Industries|Oil|Gas|Petroleum|Bank))', line)
                for match in company_matches:
                    clean_name = match.strip()
                    if len(clean_name) > 5:
                        peers.append(clean_name)
        
        return peers
    
    @staticmethod
    def _get_competitors_with_perplexity(company_name: str, sector: str) -> List[Dict]:
        """
        Use Perplexity to dynamically find competitor companies and their ticker symbols
        
        Args:
            company_name: Name of the company to find competitors for
            sector: Sector/industry of the company
            
        Returns:
            List of dicts with 'name' and 'symbol' keys for each competitor
        """
        from utils.model_config import get_client
        import json
        
        try:
            # Get the OpenAI client (configured for OpenRouter)
            client = get_client()
            
            # Create the prompt for Perplexity
            system_prompt = f"""You are a financial research expert specializing in competitive analysis.

Your task is to find the top 3-5 direct competitors for {company_name} in the {sector} sector.

CRITICAL REQUIREMENTS:
1. Find ONLY publicly listed competitors in India (NSE/BSE)
2. Return the EXACT Yahoo Finance ticker symbols (e.g., RELIANCE.NS, TCS.NS, INFY.NS)
3. Prioritize .NS (NSE) symbols over .BO (BSE) symbols
4. Only include real, verifiable competitors - DO NOT make up companies
5. Ensure ticker symbols are accurate and currently traded

Return your response as a JSON object with this exact structure:
{{
  "competitors": [
    {{"name": "Full Company Name", "symbol": "TICKER.NS"}},
    {{"name": "Another Company", "symbol": "SYMBOL.NS"}}
  ]
}}

Return ONLY valid JSON, no additional text."""

            query = f"Find the top 3-5 direct competitors of {company_name} in the {sector} sector in India. Provide their full company names and exact Yahoo Finance ticker symbols."
            
            print(f"🤖 Asking Perplexity for competitors of {company_name}...")
            
            # Call Perplexity using the client
            response = client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query}
                ],
                temperature=0.1,
                max_tokens=1000
            )
            
            # Extract the response
            response_text = response.choices[0].message.content.strip()
            
            # Parse JSON from response
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            try:
                result_data = json.loads(response_text)
                competitors_data = []
                
                if 'competitors' in result_data:
                    for comp in result_data['competitors']:
                        if 'name' in comp and 'symbol' in comp:
                            competitors_data.append({
                                'name': comp['name'],
                                'symbol': comp['symbol']
                            })
                    print(f"✅ Perplexity found {len(competitors_data)} competitors")
                else:
                    print("⚠️ Perplexity response missing 'competitors' key")
                
                return competitors_data
                
            except json.JSONDecodeError as e:
                print(f"❌ Failed to parse Perplexity JSON response: {e}")
                print(f"Response was: {response_text[:200]}")
                return []
            
        except Exception as e:
            print(f"❌ Error using Perplexity for competitor discovery: {e}")
            import traceback
            traceback.print_exc()
            return []

    
    @staticmethod
    def _check_and_backfill_missing_data(company_data: CompanyData, stock_symbol: str) -> CompanyData:
        """
        Check for missing fields in CompanyData and backfill them using screener.in first, then Tavily search
        """
        import json
        import os
        from utils.model_config import get_client
        
        # Helper function to check if a value is missing
        def is_missing_value(value):
            """Check if a value is None, empty, 'N/A', or the string 'null'"""
            if value is None:
                return True
            if isinstance(value, str) and value.strip() in ["", "N/A", "null"]:
                return True
            if isinstance(value, list) and len(value) == 0:
                return True
            if isinstance(value, dict) and len(value) == 0:
                return True
            return False

        # ===== STEP 1: Try to get accurate data from screener.in first =====
        print(f"\n{'='*60}")
        print(f"🌐 STEP 1: Fetching accurate financial data from screener.in")
        print(f"{'='*60}")
        
        try:
            from utils.screener_scraper import get_screener_financial_data
            
            screener_data = get_screener_financial_data(stock_symbol)
            
            if screener_data and screener_data.get('success'):
                print(f"✅ Successfully fetched data from screener.in!")
                
                # Update financial metrics with accurate screener.in data
                # CRITICAL: Always override with screener.in data (more accurate than yfinance)
                # These fields from yfinance are often incorrect, so we force-update them
                if screener_data.get('dividend_yield') is not None:
                    company_data.financials.dividend_yield = screener_data['dividend_yield'] / 100  # Convert to decimal
                    print(f"  ✓ Dividend Yield: {screener_data['dividend_yield']}% (OVERRIDING yfinance)")
                
                if screener_data.get('dividend_payout') is not None:
                    company_data.financials.payout_ratio = screener_data['dividend_payout'] / 100  # Convert to decimal
                    print(f"  ✓ Payout Ratio: {screener_data['dividend_payout']}% (OVERRIDING yfinance)")
                
                if screener_data.get('debt_to_equity') is not None:
                    company_data.financials.debt_to_equity = screener_data['debt_to_equity']
                    print(f"  ✓ Debt-to-Equity: {screener_data['debt_to_equity']} (OVERRIDING yfinance)")
                
                if screener_data.get('operating_margin') is not None:
                    company_data.financials.operating_margin = screener_data['operating_margin'] / 100  # Convert to decimal
                    print(f"  ✓ Operating Margin: {screener_data['operating_margin']}% (OVERRIDING yfinance)")
                
                if screener_data.get('profit_margin') is not None:
                    company_data.financials.profit_margin = screener_data['profit_margin'] / 100  # Convert to decimal
                    print(f"  ✓ Profit Margin: {screener_data['profit_margin']}% (OVERRIDING yfinance)")
                
                if screener_data.get('fii_holding') is not None:
                    company_data.market_data.fii_holding = screener_data['fii_holding']
                    print(f"  ✓ FII Holding: {screener_data['fii_holding']}% (OVERRIDING yfinance)")
                
                if screener_data.get('promoter_holding') is not None:
                    company_data.market_data.promoter_holding = screener_data['promoter_holding']
                    print(f"  ✓ Promoter Holding: {screener_data['promoter_holding']}% (OVERRIDING yfinance)")
                
                if screener_data.get('dii_holding') is not None:
                    company_data.market_data.dii_holding = screener_data['dii_holding']
                    print(f"  ✓ DII Holding: {screener_data['dii_holding']}% (OVERRIDING yfinance)")
                
                # Other metrics - only update if missing
                if screener_data.get('market_cap'):
                    company_data.market_data.market_cap = screener_data['market_cap']
                    print(f"  ✓ Market Cap: ₹{screener_data['market_cap']/10000000:.2f} Cr")
                
                if screener_data.get('current_price'):
                    company_data.market_data.current_price = screener_data['current_price']
                    print(f"  ✓ Current Price: ₹{screener_data['current_price']}")
                
                if screener_data.get('pe_ratio'):
                    company_data.financials.pe_ratio = screener_data['pe_ratio']
                    print(f"  ✓ PE Ratio: {screener_data['pe_ratio']}")
                
                if screener_data.get('enterprise_value'):
                    company_data.financials.enterprise_value = screener_data['enterprise_value']
                    print(f"  ✓ Enterprise Value: ₹{screener_data['enterprise_value']/10000000:.2f} Cr")
                
                if screener_data.get('ev_ebitda'):
                    company_data.financials.ev_ebitda = screener_data['ev_ebitda']
                    print(f"  ✓ EV/EBITDA: {screener_data['ev_ebitda']}")
                
                if screener_data.get('opm'):
                    company_data.financials.operating_margin = screener_data['opm'] / 100
                    print(f"  ✓ OPM: {screener_data['opm']}%")
                
                if screener_data.get('gpm_latest_quarter'):
                    company_data.financials.gross_margin = screener_data['gpm_latest_quarter'] / 100
                    print(f"  ✓ Gross Margin: {screener_data['gpm_latest_quarter']}%")
                
                if screener_data.get('total_assets'):
                    company_data.financials.total_assets = screener_data['total_assets']
                    print(f"  ✓ Total Assets: ₹{screener_data['total_assets']/10000000:.2f} Cr")
                
                if screener_data.get('total_debt'):
                    company_data.financials.total_debt = screener_data['total_debt']
                    print(f"  ✓ Total Debt: ₹{screener_data['total_debt']/10000000:.2f} Cr")
                
                if screener_data.get('roce'):
                    company_data.financials.roce = screener_data['roce']
                    print(f"  ✓ ROCE: {screener_data['roce']}%")
                
                if screener_data.get('roe'):
                    company_data.financials.roe = screener_data['roe']
                    print(f"  ✓ ROE: {screener_data['roe']}%")
                
                if screener_data.get('peg_ratio'):
                    company_data.financials.peg_ratio = screener_data['peg_ratio']
                    print(f"  ✓ PEG Ratio: {screener_data['peg_ratio']}")
                
                if screener_data.get('high_52week'):
                    company_data.market_data.overall_high = screener_data['high_52week']
                    print(f"  ✓ 52-Week High: ₹{screener_data['high_52week']}")
                
                if screener_data.get('low_52week'):
                    company_data.market_data.overall_low = screener_data['low_52week']
                    print(f"  ✓ 52-Week Low: ₹{screener_data['low_52week']}")
                
                if screener_data.get('book_value'):
                    company_data.financials.book_value = screener_data['book_value']
                    print(f"  ✓ Book Value: ₹{screener_data['book_value']}")
                
                if screener_data.get('free_cash_flow'):
                    company_data.financials.free_cash_flow = screener_data['free_cash_flow']
                    print(f"  ✓ Free Cash Flow: ₹{screener_data['free_cash_flow']/10000000:.2f} Cr")
                
                print(f"\n✅ Updated company data with accurate screener.in metrics!")
                
        except Exception as e:
            print(f"⚠️ Failed to fetch from screener.in: {e}")
            print("   Falling back to Tavily search...")
        
        # ===== STEP 2: Use Tavily search for remaining missing fields =====
        print(f"\n{'='*60}")
        print(f"🔍 STEP 2: Checking for remaining missing fields")
        print(f"{'='*60}")
        
        # Define domains to iterate through
        search_domains = ["screener.in", "nseindia.com", "bseindia.com"]
        
        # Initialize OpenAI client
        client = get_client()

        for domain in search_domains:
            print(f"\n🔍 Checking for missing data fields (Source: {domain})...")
            
            # Track missing fields
            missing_fields = []
            
            # Check CompanySnapshot fields
            snapshot_dict = company_data.snapshot.model_dump()
            for field, value in snapshot_dict.items():
                if is_missing_value(value):
                    missing_fields.append(f"snapshot.{field}")
            
            # Check BusinessOverview fields
            business_dict = company_data.business_overview.model_dump()
            for field, value in business_dict.items():
                if is_missing_value(value):
                    missing_fields.append(f"business_overview.{field}")
            
            # Check FinancialData fields (only critical ones)
            financials_dict = company_data.financials.model_dump()
            critical_financial_fields = [
                'revenue', 'net_profit', 'ebitda', 'pe_ratio', 
                'debt_to_equity', 'total_assets', 'total_liabilities', 'peg_ratio'
            ]
            for field in critical_financial_fields:
                if field in financials_dict and is_missing_value(financials_dict[field]):
                    missing_fields.append(f"financials.{field}")
            
            # Check MarketData fields (only critical ones)
            market_dict = company_data.market_data.model_dump()
            critical_market_fields = [
                'current_price', 'market_cap', 'dii_holding', 'year_5_cagr'
            ]
            for field in critical_market_fields:
                if field in market_dict and is_missing_value(market_dict[field]):
                    missing_fields.append(f"market_data.{field}")
            
            # Check for competitors with N/A values
            has_incomplete_competitors = False
            if company_data.market_data.competitors:
                for comp in company_data.market_data.competitors:
                    if not comp.get('is_main_company', False):  # Skip main company
                        if (comp.get('symbol') in ['N/A', None, ''] or 
                            comp.get('market_cap') in ['N/A', None, ''] or
                            comp.get('pe_ratio') in ['N/A', None, ''] or
                            comp.get('revenue') in ['N/A', None, '']):
                            has_incomplete_competitors = True
                            break
            else:
                has_incomplete_competitors = True
            
            if has_incomplete_competitors:
                missing_fields.append('competitor_data')
            print(missing_fields)
            if not missing_fields:
                print("✅ All fields are populated!")
                break
            
            print(f"⚠️ Found {len(missing_fields)} missing fields: {', '.join(str(field) for field in missing_fields)}")
            
            # Search for missing data using Tavily
            scalar_fields = [f for f in missing_fields if f != 'competitor_data']
            
            if scalar_fields:
                # Clean field names for query
                field_names = [f.split('.')[-1] for f in scalar_fields]
                search_query = f"{company_data.name} {stock_symbol} {' '.join(field_names)} financial data"
                print(f"🔎 Searching for missing data on {domain}: {search_query}")
                
                try:
                    search_results, answer = StockTools._search_with_tavily(search_query, domain=[domain])
                    
                    # Retry with broader query if no results found - fixes empty content issue
                    if not search_results and not answer:
                        print(f"⚠️ No results found on {domain} with specific query. Retrying with broader query...")
                        fallback_query = f"{company_data.name} {stock_symbol} financial results data"
                        search_results, answer = StockTools._search_with_tavily(fallback_query, domain=[domain])
                    
                    # Combine all search content - safely handle None answer
                    all_content = (answer if answer else "") + "\n\n"
                    for result in search_results[:5]:
                        all_content += f"Title: {result.get('title', '')}\n"
                        all_content += f"Content: {result.get('content', '')}\n\n"
                    # print("All content from tavily search:- ", all_content)
                    if all_content.strip():
                        # Use LLM to extract missing data
                        extraction_prompt = f"""Extract the following missing fields for {company_data.name} ({stock_symbol}) from the search results.

Missing Fields: {json.dumps(field_names, indent=2)}

Search Results:
{all_content[:10000]}

CRITICAL INSTRUCTIONS:
1. Return ONLY valid JSON - no markdown, no explanations
2. Extract ONLY the fields listed above
3. For founded_year: return a 4-digit number (e.g., 1967) or null
4. For numeric fields: return numbers without commas (e.g., 45000000000.0)
5. For list fields (main_products, revenue_sources, growth_segments): return arrays of strings
6. For text fields: return clean strings
7. If a field cannot be found, use null
8. Be precise and factual

OUTPUT FORMAT (JSON only):
{{
  "field_name": value,
  "another_field": value
}}"""
                        
                        print("🤖 Using LLM to extract missing data...")
                        response = client.chat.completions.create(
                            model="openai/gpt-oss-120b",  # Free model
                            messages=[
                                {"role": "system", "content": "You are a financial data extraction expert. Extract specific company information and return ONLY valid JSON with no additional text."},
                                {"role": "user", "content": extraction_prompt}
                            ],
                            temperature=0.1,
                            max_tokens=1000
                        )
                        
                        extracted_text = response.choices[0].message.content.strip()
                        print(extracted_text)
                        
                        # Try to parse JSON from the response
                        if "```json" in extracted_text:
                            extracted_text = extracted_text.split("```json")[1].split("```")[0].strip()
                        elif "```" in extracted_text:
                            extracted_text = extracted_text.split("```")[1].split("```")[0].strip()
                        
                        try:
                            extracted_data = json.loads(extracted_text)
                            print(f"✅ Successfully extracted fields: {list(extracted_data.keys())}")
                            
                            # Update CompanyData with extracted values
                            snap_fields = company_data.snapshot.model_dump().keys()
                            bus_fields = company_data.business_overview.model_dump().keys()
                            fin_fields = company_data.financials.model_dump().keys()
                            mkt_fields = company_data.market_data.model_dump().keys()
                            
                            for k, v in extracted_data.items():
                                print("key :- " , k)
                                print("value :- ", v)
                                if v in [None, "null", "N/A", ""]: continue
                                
                                if k in snap_fields:
                                    # Special handling for founded_year
                                    if k == 'founded_year':
                                        try:
                                            # Convert to integer if it's a valid year
                                            if isinstance(v, str):
                                                year = int(v.strip())
                                                if 1800 <= year <= 2030:  # Reasonable year range
                                                    setattr(company_data.snapshot, k, year)
                                                    print(f"✅ Updated snapshot.{k}: {year}")
                                                else:
                                                    print(f"⚠️ Invalid year value: {v}")
                                            elif isinstance(v, (int, float)):
                                                year = int(v)
                                                if 1800 <= year <= 2030:
                                                    setattr(company_data.snapshot, k, year)
                                                    print(f"✅ Updated snapshot.{k}: {year}")
                                        except:
                                            print(f"⚠️ Could not parse year: {v}")
                                    else:
                                        setattr(company_data.snapshot, k, v)
                                        print(f"✅ Updated snapshot.{k}: {v}")
                                elif k in bus_fields:
                                    setattr(company_data.business_overview, k, v)
                                elif k in fin_fields:
                                    try:
                                        # Clean and convert numeric values
                                        val_str = str(v).replace(',', '').replace('₹', '').replace('$', '').strip()
                                        
                                        # Handle suffixes
                                        multiplier = 1.0
                                        if val_str.lower().endswith('cr'):
                                            multiplier = 10000000.0
                                            val_str = val_str.lower().replace('cr', '').strip()
                                        elif val_str.lower().endswith('l'):
                                            multiplier = 100000.0
                                            val_str = val_str.lower().replace('l', '').strip()
                                        elif val_str.lower().endswith('b'):
                                            multiplier = 1000000000.0
                                            val_str = val_str.lower().replace('b', '').strip()
                                        elif val_str.lower().endswith('m'):
                                            multiplier = 1000000.0
                                            val_str = val_str.lower().replace('m', '').strip()
                                            
                                        # Extract first valid number if there's extra text
                                        import re
                                        number_match = re.search(r'-?\d*\.?\d+', val_str)
                                        if number_match:
                                            clean_val = float(number_match.group()) * multiplier
                                            setattr(company_data.financials, k, clean_val)
                                            print(f"✅ Updated financials.{k}: {clean_val}")
                                        else:
                                            print(f"⚠️ Could not parse numeric value for financials.{k}: {v}")
                                    except Exception as e:
                                        print(f"❌ Failed to update financials.{k} with value '{v}': {e}")
                                elif k in mkt_fields:
                                    try:
                                        # Clean and convert numeric values
                                        val_str = str(v).replace(',', '').replace('₹', '').replace('$', '').strip()
                                        
                                        # Handle suffixes
                                        multiplier = 1.0
                                        if val_str.lower().endswith('cr'):
                                            multiplier = 10000000.0
                                            val_str = val_str.lower().replace('cr', '').strip()
                                        elif val_str.lower().endswith('l'):
                                            multiplier = 100000.0
                                            val_str = val_str.lower().replace('l', '').strip()
                                        elif val_str.lower().endswith('b'):
                                            multiplier = 1000000000.0
                                            val_str = val_str.lower().replace('b', '').strip()
                                        elif val_str.lower().endswith('m'):
                                            multiplier = 1000000.0
                                            val_str = val_str.lower().replace('m', '').strip()
                                            
                                        # Extract first valid number if there's extra text
                                        import re
                                        number_match = re.search(r'-?\d*\.?\d+', val_str)
                                        if number_match:
                                            clean_val = float(number_match.group()) * multiplier
                                            setattr(company_data.market_data, k, clean_val)
                                            print(f"✅ Updated market_data.{k}: {clean_val}")
                                        else:
                                            print(f"⚠️ Could not parse numeric value for market_data.{k}: {v}")
                                    except Exception as e:
                                        print(f"❌ Failed to update market_data.{k} with value '{v}': {e}")
                        except json.JSONDecodeError:
                             print("❌ Failed to parse LLM JSON response")
                except Exception as e:
                     print(f"❌ Error searching/extracting on {domain}: {e}")

            # Backfill Competitor Data using Perplexity
            if 'competitor_data' in missing_fields:
                print(f"🔎 Searching for competitor data using Perplexity...")
                try:
                    # Get competitor data dynamically using Perplexity
                    competitors_data = StockTools._get_competitors_with_perplexity(
                        company_data.name, 
                        company_data.snapshot.sector or "finance"
                    )
                    
                    if competitors_data:
                        # Preserve the main company data
                        new_competitors = []
                        for comp in company_data.market_data.competitors:
                            if comp.get('is_main_company', False):
                                new_competitors.append(comp)
                                break
                        
                        # Add competitor data from Perplexity + yfinance
                        import yfinance as yf
                        for comp_data in competitors_data[:5]:  # Limit to 5 competitors
                            comp_name = comp_data.get('name')
                            comp_symbol = comp_data.get('symbol')
                            
                            if comp_name and comp_symbol:
                                try:
                                    # Fetch real financial data from yfinance
                                    comp_ticker = yf.Ticker(comp_symbol)
                                    comp_info = comp_ticker.info
                                    
                                    if comp_info and comp_info.get('symbol'):
                                        new_competitors.append({
                                            'name': comp_info.get('longName', comp_name),
                                            'symbol': comp_symbol,
                                            'market_cap': comp_info.get('marketCap'),
                                            'pe_ratio': comp_info.get('trailingPE'),
                                            'pb_ratio': comp_info.get('priceToBook'),
                                            'revenue': comp_info.get('totalRevenue'),
                                            'profit_margin': comp_info.get('profitMargins'),
                                            'roe': comp_info.get('returnOnEquity'),
                                            'debt_to_equity': comp_info.get('debtToEquity'),
                                            'source': 'perplexity_yfinance',
                                            'is_main_company': False
                                        })
                                        print(f"✅ Found data for competitor: {comp_name} ({comp_symbol})")
                                    else:
                                        print(f"⚠️ No yfinance data for {comp_name} ({comp_symbol})")
                                except Exception as e:
                                    print(f"❌ Error fetching yfinance data for {comp_name}: {e}")
                        
                        if len(new_competitors) > 1:
                            company_data.market_data.competitors = new_competitors
                            print(f"✅ Updated competitors list with {len(new_competitors)-1} real competitors")
                        else:
                            print("⚠️ No valid competitor data found")
                    else:
                        print("⚠️ Perplexity returned no competitor data")
                        
                except Exception as e:
                    print(f"❌ Error getting competitors via Perplexity: {e}")
        
        return company_data
    
    @staticmethod
    def _build_screener_competitor_table(peer_data: List[Dict], company_name: str, stock_symbol: str, company_info: Dict) -> List[Dict]:
        """
        Build competitor comparison table from screener.in peer data with real financial data
        """
        competitors = []
        
        # Add the main company first
        main_company = {
            'name': company_name,
            'symbol': stock_symbol,
            'market_cap': company_info.get('marketCap', 'N/A'),
            'pe_ratio': company_info.get('trailingPE', 'N/A'),
            'pb_ratio': company_info.get('priceToBook', 'N/A'),
            'revenue': company_info.get('totalRevenue', 'N/A'),
            'profit_margin': company_info.get('profitMargins', 'N/A'),
            'roe': company_info.get('returnOnEquity', 'N/A'),
            'debt_to_equity': company_info.get('debtToEquity', 'N/A'),
            'is_main_company': True
        }
        competitors.append(main_company)
        
        # Extract peer companies from screener.in content
        peer_companies = StockTools._extract_screener_peers(peer_data)
        
        # Use Perplexity to get ticker symbols for peer companies dynamically
        print(f"🔎 Using Perplexity to find ticker symbols for {len(peer_companies)} peer companies...")
        
        # Try to get real financial data for peer companies using Perplexity
        for peer_name in peer_companies[:5]:  # Limit to 5 peers
            try:
                # Use Perplexity to find the ticker symbol for this company
                perplexity_client = get_client()

                                
                system_prompt="""You are a financial data expert. Find the exact Yahoo Finance ticker symbol for the given Indian company.
                    
Output Format:-
[
    {
        'verified_name': <company name>, 
        'symbol': <ticker symbol>
    },
    ...,
    {
        'verified_name': <company name>, 
        'symbol': <ticker symbol>
    }
]


CRITICAL REQUIREMENTS:
1. Return ONLY the exact Yahoo Finance ticker symbol (e.g., RELIANCE.NS, TCS.NS)
2. Prioritize .NS (NSE) over .BO (BSE) symbols
3. Return the official full company name as listed on the exchange
4. Ensure the ticker is currently active and traded"""
                
                
                ticker_response = perplexity_client.chat.completions.create(
                    model="openai/gpt-oss-120b",
                    messages = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Find the Yahoo Finance ticker symbol for {peer_name}"}
                    ]
                )
                
                # Extract the content from the response
                ticker_result = ticker_response.choices[0].message.content.strip()
                print("in the screener competitor table ticker_result:- ", ticker_result )
                
                if "```json" in ticker_result:
                    ticker_result = ticker_result.replace("```json", "").replace("```", "")
                elif "```" in ticker_result:
                    ticker_result = ticker_result.replace("```", "")
                
                try:
                    ticker_data = json.loads(ticker_result)
                    
                    if ticker_data and isinstance(ticker_data, dict):
                        peer_ticker = ticker_data.get('symbol')
                        verified_name = ticker_data.get('verified_name', peer_name)
                        
                        if peer_ticker:
                            # Fetch financial data from yfinance
                            import yfinance as yf
                            peer_ticker_obj = yf.Ticker(peer_ticker)
                            peer_info = peer_ticker_obj.info
                            
                            if peer_info and peer_info.get('symbol'):
                                competitors.append({
                                    'name': peer_info.get('longName', verified_name),
                                    'symbol': peer_ticker,
                                    'market_cap': peer_info.get('marketCap', 'N/A'),
                                    'pe_ratio': peer_info.get('trailingPE', 'N/A'),
                                    'pb_ratio': peer_info.get('priceToBook', 'N/A'),
                                    'revenue': peer_info.get('totalRevenue', 'N/A'),
                                    'profit_margin': peer_info.get('profitMargins', 'N/A'),
                                    'roe': peer_info.get('returnOnEquity', 'N/A'),
                                    'debt_to_equity': peer_info.get('debtToEquity', 'N/A'),
                                    'source': 'perplexity_yfinance',
                                    'is_main_company': False
                                })
                                print(f"✅ Found ticker for {peer_name}: {peer_ticker}")
                            else:
                                print(f"⚠️ Invalid ticker data for {peer_name}: {peer_ticker}")
                        else:
                            print(f"⚠️ No ticker symbol found for {peer_name}")
                    else:
                        print(f"⚠️ Invalid JSON response for {peer_name}")
                        
                except json.JSONDecodeError as e:
                    print(f"❌ JSON decode error for {peer_name}: {e}")
                except Exception as e:
                    print(f"❌ Error processing {peer_name}: {e}")
                    
            except Exception as e:
                print(f"❌ Error processing {peer_name}: {e}")
        
        # If we still don't have enough peers, use Perplexity to find more competitors
        if len(competitors) < 4:  # Main company + at least 3 peers
            print(f"🔎 Need more competitors, using Perplexity to find additional ones...")
            sector = company_info.get('sector', 'finance')
            additional_competitors = StockTools._get_competitors_with_perplexity(company_name, sector)
            
            # Add the additional competitors from Perplexity
            import yfinance as yf
            for comp_data in additional_competitors:
                if len(competitors) >= 6:  # Main + 5 peers max
                    break
                
                comp_name = comp_data.get('name')
                comp_symbol = comp_data.get('symbol')
                
                # Check if already added
                if not any(comp.get('symbol') == comp_symbol for comp in competitors):
                    try:
                        peer_ticker_obj = yf.Ticker(comp_symbol)
                        peer_info = peer_ticker_obj.info
                        
                        if peer_info and peer_info.get('symbol'):
                            competitors.append({
                                'name': peer_info.get('longName', comp_name),
                                'symbol': comp_symbol,
                                'market_cap': peer_info.get('marketCap', 'N/A'),
                                'pe_ratio': peer_info.get('trailingPE', 'N/A'),
                                'pb_ratio': peer_info.get('priceToBook', 'N/A'),
                                'revenue': peer_info.get('totalRevenue', 'N/A'),
                                'profit_margin': peer_info.get('profitMargins', 'N/A'),
                                'roe': peer_info.get('returnOnEquity', 'N/A'),
                                'debt_to_equity': peer_info.get('debtToEquity', 'N/A'),
                                'source': 'perplexity_fallback',
                                'is_main_company': False
                            })
                            print(f"✅ Added fallback competitor: {comp_name} ({comp_symbol})")
                    except Exception as e:
                        print(f"❌ Error adding fallback competitor {comp_name}: {e}")
        
        return competitors

    
    @staticmethod
    def get_realtime_data(stock_symbol: str) -> CompanyData:
        """
        Tool 1: Gather comprehensive real-time data using Tavily + yfinance
        
        Strategy:
        1. Use Tavily to get latest news, analysis, and market sentiment
        2. Use yfinance for structured financial data (price, ratios, etc.)
        3. Combine both for comprehensive analysis
        """
        
        # Helper function to safely get values from info dict
        def safe_get(info_dict, key, default='N/A', value_type=str):
            """
            Safely get value from info dict, handling None values
            
            Args:
                info_dict: Dictionary to get value from
                key: Key to retrieve
                default: Default value if key is missing or None
                value_type: Expected type (str, int, float)
            
            Returns:
                Value from dict or default, ensuring proper type
            """
            value = info_dict.get(key)
            
            # If value is None or empty, return default
            if value is None:
                return default
            
            # For string type, ensure we don't have None
            if value_type == str:
                return str(value) if value else default
            
            # For numeric types, return the value as-is if valid, else default
            if value_type in (int, float):
                try:
                    return value_type(value) if value is not None else None
                except (ValueError, TypeError):
                    return None
            
            return value
        
        try:
            # Check rate limits before making request
            should_wait, wait_time = should_wait_for_rate_limit('yfinance')
            if should_wait:
                api_logger.logger.warning(f"⏳ YFinance rate limit reached, waiting {wait_time} seconds")
                time.sleep(min(wait_time, 30))
            
            # Step 1: Get structured data from yfinance
            start_time = time.time()
            ticker = yf.Ticker(stock_symbol)
            
            # Suppress yfinance warnings and errors
            import warnings
            warnings.filterwarnings('ignore')
            
            info = ticker.info
            
            # Check if we got valid data - if info is empty or has no symbol, the stock doesn't exist
            if not info or 'symbol' not in info or info.get('symbol') is None:
                # Log the failed request
                api_logger.log_request(
                    api_name='yfinance',
                    endpoint=f'/ticker/{stock_symbol}/info',
                    method='GET',
                    response_status=404,
                    response_time=time.time() - start_time,
                    error=f"Stock {stock_symbol} not found or delisted"
                )
                
                # Try to find if stock was merged or renamed
                company_name = stock_symbol.replace('.NS', '').replace('.BO', '')
                search_results, answer = StockTools._search_with_tavily(
                    f"{company_name} stock merged delisted renamed ticker symbol India NSE BSE"
                )
                
                error_msg = f"❌ **Stock Not Found: {stock_symbol}**\n\n"
                error_msg += f"The ticker symbol **{stock_symbol}** is not available on Yahoo Finance. This could mean:\n\n"
                error_msg += "• The stock has been **delisted**\n"
                error_msg += "• The stock has been **merged** with another company\n"
                error_msg += "• The ticker symbol is **incorrect**\n\n"
                
                if answer:
                    error_msg += f"**Latest Information:**\n{answer}\n\n"
                
                error_msg += "**What you can do:**\n"
                error_msg += "• Try searching for the company name instead of the ticker\n"
                error_msg += "• Check if the company has been merged with another entity\n"
                error_msg += "• Verify the correct ticker symbol from screener.in or moneycontrol.com\n"
                
                raise Exception(error_msg)
            
            # Log the info request
            api_logger.log_request(
                api_name='yfinance',
                endpoint=f'/ticker/{stock_symbol}/info',
                method='GET',
                response_status=200 if info else 404,
                response_time=time.time() - start_time
            )
            
            # Try to get history, but don't fail if it errors
            try:
                hist_start_time = time.time()
                hist = ticker.history(period="5y")  # Get 5 years for CAGR calculation
                
                # Log the history request
                api_logger.log_request(
                    api_name='yfinance',
                    endpoint=f'/ticker/{stock_symbol}/history/5y',
                    method='GET',
                    response_status=200 if not hist.empty else 404,
                    response_time=time.time() - hist_start_time
                )
                
            except Exception as hist_error:
                api_logger.log_request(
                    api_name='yfinance',
                    endpoint=f'/ticker/{stock_symbol}/history/5y',
                    method='GET',
                    response_status=500,
                    response_time=time.time() - hist_start_time if 'hist_start_time' in locals() else None,
                    error=str(hist_error)
                )
                
                print(f"⚠️ Warning: Could not fetch full history: {hist_error}")
                # Try shorter period
                try:
                    hist_start_time = time.time()
                    hist = ticker.history(period="1y")
                    api_logger.log_request(
                        api_name='yfinance',
                        endpoint=f'/ticker/{stock_symbol}/history/1y',
                        method='GET',
                        response_status=200 if not hist.empty else 404,
                        response_time=time.time() - hist_start_time
                    )
                except:
                    hist_start_time = time.time()
                    hist = ticker.history(period="1mo")
                    api_logger.log_request(
                        api_name='yfinance',
                        endpoint=f'/ticker/{stock_symbol}/history/1mo',
                        method='GET',
                        response_status=200 if not hist.empty else 404,
                        response_time=time.time() - hist_start_time
                    )
        except Exception as e:
            api_logger.log_request(
                api_name='yfinance',
                endpoint=f'/ticker/{stock_symbol}/info',
                method='GET',
                response_status=500,
                response_time=time.time() - start_time if 'start_time' in locals() else None,
                error=str(e)
            )
            print(f"❌ Error fetching data for {stock_symbol}: {e}")
            raise Exception(f"Could not fetch data for {stock_symbol}. Please verify the symbol and try again.")
        
        company_name = safe_get(info, 'longName', stock_symbol, str)
        
        # Step 2: Build Company Snapshot with safe value extraction
        # Build headquarters string safely
        city = safe_get(info, 'city', '', str)
        country = safe_get(info, 'country', '', str)
        headquarters = f"{city}, {country}".strip(', ') if city or country else 'N/A'
        
        # Safely get CEO name - will be updated from web search later
        ceo = 'N/A'
        # Don't use yfinance CEO - it's often outdated
        # We'll fetch accurate CEO from web search in Step 13.7
        
        snapshot = CompanySnapshot(
            company_name=company_name,
            ticker_symbol=stock_symbol,
            exchange=safe_get(info, 'exchange', 'N/A', str),
            sector=safe_get(info, 'sector', 'N/A', str),
            industry=safe_get(info, 'industry', 'N/A', str),
            headquarters=headquarters,
            founded_year=safe_get(info, 'founded', 'N/A', str),
            ceo=ceo,
            employees=safe_get(info, 'fullTimeEmployees', None, int),
            website=safe_get(info, 'website', 'N/A', str)
        )
        
        # Step 3: Build Business Overview with safe value extraction
        business_overview = BusinessOverview(
            description=safe_get(info, 'longBusinessSummary', 'N/A', str),
            main_products=[],  # Will be extracted from description
            revenue_sources=[],  # Will be extracted from web search
            geographic_presence=safe_get(info, 'country', 'N/A', str),
            growth_segments=[]  # Will be extracted from web search
        )
        
        # Step 4: Use Tavily to get latest market insights and news (restricted to screener.in)
        search_queries = [
            f"{company_name} {stock_symbol} screener.in financial results revenue profit EBITDA",
            f"{company_name} {stock_symbol} screener.in stock analysis ratios",
            f"site:screener.in {stock_symbol} peer comparison",  # Direct screener.in peer page
            f"site:screener.in {company_name} competitors similar companies",  # Alternative peer search
            f"{company_name} {stock_symbol} screener.in SWOT analysis business overview",
            f"{company_name} {stock_symbol} screener.in business segments revenue sources"
        ]
        
        all_search_results = []
        tavily_answer = ""
        
        for query in search_queries:
            results, answer = StockTools._search_with_tavily(query)
            all_search_results.extend(results)
            if answer:
                tavily_answer += answer + "\n"
        
        # Step 5: Extract insights from web search
        web_insights = StockTools._extract_financial_data_from_web(
            stock_symbol, all_search_results, tavily_answer
        )
        
        # Step 6: Calculate price performance
        price_history = {}
        day_change = None
        week_change = None
        month_change = None
        month_6_change = None
        year_change = None
        year_5_cagr = None
        
        if not hist.empty:
            # Store price history
            for date, row in hist.tail(365).iterrows():  # Last year
                price_history[date.strftime('%Y-%m-%d')] = float(row['Close'])
            
            current_price = hist['Close'].iloc[-1]
            
            # Calculate returns
            if len(hist) >= 2:
                day_change = ((current_price - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100
            if len(hist) >= 7:
                week_change = ((current_price - hist['Close'].iloc[-7]) / hist['Close'].iloc[-7]) * 100
            if len(hist) >= 30:
                month_change = ((current_price - hist['Close'].iloc[-30]) / hist['Close'].iloc[-30]) * 100
            if len(hist) >= 180:
                month_6_change = ((current_price - hist['Close'].iloc[-180]) / hist['Close'].iloc[-180]) * 100
            if len(hist) >= 252:
                year_change = ((current_price - hist['Close'].iloc[-252]) / hist['Close'].iloc[-252]) * 100
            if len(hist) >= 1260:  # 5 years
                year_5_cagr = (((current_price / hist['Close'].iloc[0]) ** (1/5)) - 1) * 100
        
        # Step 7: Build comprehensive Financial data
        financials = FinancialData(
            # Income Statement
            revenue=info.get('totalRevenue'),
            net_profit=info.get('netIncomeToCommon'),
            ebitda=info.get('ebitda'),
            eps=info.get('trailingEps'),
            dividend_yield=info.get('dividendYield'),
            payout_ratio=info.get('payoutRatio'),
            
            # Balance Sheet
            total_assets=info.get('totalAssets'),
            total_liabilities=info.get('totalLiabilities'),
            debt_to_equity=info.get('debtToEquity'),
            cash_balance=info.get('totalCash'),
            total_debt=info.get('totalDebt'),
            
            # Cash Flow
            operating_cash_flow=info.get('operatingCashflow'),
            free_cash_flow=info.get('freeCashflow'),
            
            # Valuation
            pe_ratio=info.get('trailingPE'),
            pb_ratio=info.get('priceToBook'),
            peg_ratio=info.get('pegRatio'),
            enterprise_value=info.get('enterpriseValue'),
            ev_ebitda=info.get('enterpriseToEbitda'),
            
            # Margins
            profit_margin=info.get('profitMargins'),
            operating_margin=info.get('operatingMargins'),
            gross_margin=info.get('grossMargins')
        )
        
        # Step 8: Build competitor comparison from screener.in data
        competitors_data = []
        
        # Check if we have peer comparison data from screener.in
        if web_insights.get('peer_comparison'):
            competitors_data = StockTools._build_screener_competitor_table(
                web_insights['peer_comparison'], 
                company_name, 
                stock_symbol,
                info
            )
        
        # Fallback: Try to get basic competitor info if no screener data
        if not competitors_data and web_insights['competitors']:
            competitor_symbols = web_insights['competitors'][:5]  # Top 5 competitors
            
            # Map common company names to their likely ticker symbols
            company_ticker_map = {
                'tcs': 'TCS.NS', 'tata consultancy': 'TCS.NS', 'tata consultancy services': 'TCS.NS',
                'wipro': 'WIPRO.NS', 'wipro limited': 'WIPRO.NS',
                'hcl technologies': 'HCLTECH.NS', 'hcl tech': 'HCLTECH.NS', 'hcl': 'HCLTECH.NS',
                'tech mahindra': 'TECHM.NS', 'tech mahindra limited': 'TECHM.NS',
                'infosys': 'INFY.NS', 'reliance': 'RELIANCE.NS', 'kotak': 'KOTAKBANK.NS',
                'hdfc': 'HDFCBANK.NS', 'icici': 'ICICIBANK.NS', 'axis': 'AXISBANK.NS',
                'sbi': 'SBIN.NS', 'bajaj finance': 'BAJFINANCE.NS', 'itc': 'ITC.NS', 
                'hindustan unilever': 'HUL.NS',
                'oil india': 'OIL.NS', 'hindustan petroleum': 'HINDPETRO.NS', 'bharat petroleum': 'BPCL.NS',
                'gail': 'GAIL.NS', 'mahanagar gas': 'MGL.NS', 'petronet': 'PETRONET.NS',
                'zomato': 'ZOMATO.NS', 'paytm': 'PAYTM.NS', 'nykaa': 'NYKAA.NS',
                'tata motors': 'TATAMOTORS.NS', 'maruti': 'MARUTI.NS', 'm&m': 'M&M.NS',
                'sun pharma': 'SUNPHARMA.NS', 'asian paints': 'ASIANPAINT.NS',
                'titan': 'TITAN.NS', 'bharti airtel': 'BHARTIARTL.NS'
            }
            
            for comp_name in competitor_symbols:
                try:
                    ticker = None
                    comp_name_lower = comp_name.lower().strip()
                    
                    # 1. Check direct map
                    if comp_name_lower in company_ticker_map:
                        ticker = company_ticker_map[comp_name_lower]
                    else:
                        # 2. Partial match in map
                        for key, val in company_ticker_map.items():
                            if key in comp_name_lower or comp_name_lower in key:
                                ticker = val
                                break
                    
                    # 3. Heuristics if not found
                    if not ticker:
                        # Try adding .NS to cleaned name
                        clean_name = comp_name_lower.replace('limited', '').replace('ltd', '').replace('india', '').strip()
                        ticker = f"{clean_name.upper().replace(' ', '')}.NS"
                    
                    # Try to find ticker symbol for competitor
                    comp_ticker = yf.Ticker(ticker)
                    
                    # Suppress errors for this check and try getting info
                    try:
                        comp_info = comp_ticker.info
                        # Check if we got valid data (sometimes yf returns empty info without error)
                        if not comp_info or 'symbol' not in comp_info:
                            # Try without .NS if we added it
                            if ticker.endswith('.NS'):
                                comp_ticker = yf.Ticker(ticker.replace('.NS', ''))
                                comp_info = comp_ticker.info
                    except:
                        # If failed, try searching blindly with original name as fallback
                        comp_ticker = yf.Ticker(comp_name)
                        comp_info = comp_ticker.info

                    if comp_info and comp_info.get('symbol'):
                        competitors_data.append({
                            'name': comp_info.get('longName', comp_name),
                            'symbol': comp_info.get('symbol'),
                            'revenue': comp_info.get('totalRevenue'),
                            'market_cap': comp_info.get('marketCap'),
                            'pe_ratio': comp_info.get('trailingPE'),
                            'profit_margin': comp_info.get('profitMargins'),
                            'source': 'yfinance'
                        })
                    else:
                         raise Exception("No symbol found")

                except Exception:
                    # If yfinance fails, add basic info from screener.in name only
                    competitors_data.append({
                        'name': comp_name,
                        'symbol': 'N/A',
                        'revenue': 'N/A',
                        'market_cap': 'N/A',
                        'pe_ratio': 'N/A',
                        'profit_margin': 'N/A',
                        'source': 'screener.in'
                    })
        
        # Calculate overall high and low from price history
        overall_high = None
        overall_low = None
        percentage_change_from_high = None
        max_drop_after_high = None  # New field to track maximum drop after reaching high
        
        if price_history and len(price_history) > 0:
            all_prices = list(price_history.values())
            all_dates = list(price_history.keys())
            overall_high = max(all_prices)
            overall_low = min(all_prices)
            
            # Calculate percentage change from overall high to current price
            current_price = info.get('currentPrice')
            if current_price and overall_high and overall_high > 0:
                percentage_change_from_high = ((current_price - overall_high) / overall_high) * 100
            
            # NEW LOGIC: Find the maximum drop AFTER reaching the overall high
            # This checks if stock ever dropped 25% or more after hitting its peak
            if overall_high and len(all_prices) > 1:
                # Find the index where overall_high occurred
                high_index = all_prices.index(overall_high)
                
                # Get all prices AFTER the high
                prices_after_high = all_prices[high_index:]
                
                if len(prices_after_high) > 1:
                    # Find the minimum price after the high
                    min_price_after_high = min(prices_after_high)
                    
                    # Calculate the maximum drop percentage
                    max_drop_after_high = ((min_price_after_high - overall_high) / overall_high) * 100
                    
                    print(f"📊 Drop Analysis:")
                    print(f"   Overall High: {overall_high:.2f}")
                    print(f"   Min Price After High: {min_price_after_high:.2f}")
                    print(f"   Max Drop After High: {max_drop_after_high:.2f}%")
                    print(f"   Selected: {max_drop_after_high <= -25}")

        
        # Step 9: Build comprehensive Market data
        market_data = MarketData(
            current_price=info.get('currentPrice'),
            week_52_high=info.get('fiftyTwoWeekHigh'),
            week_52_low=info.get('fiftyTwoWeekLow'),
            overall_high=overall_high,
            overall_low=overall_low,
            percentage_change_from_high=percentage_change_from_high,
            max_drop_after_high=max_drop_after_high,
            market_cap=info.get('marketCap'),
            volume=info.get('volume'),
            avg_volume=info.get('averageVolume'),
            beta=info.get('beta'),
            
            # Holdings
            promoter_holding=info.get('heldPercentInsiders'),
            fii_holding=info.get('heldPercentInstitutions'),
            dii_holding=None,  # Not available in yfinance
            
            # Price History
            price_history=price_history,
            
            # Performance
            day_change=day_change,
            week_change=week_change,
            month_change=month_change,
            month_6_change=month_6_change,
            year_change=year_change,
            year_5_cagr=year_5_cagr,
            
            # Sector
            sector=info.get('sector'),
            sector_performance=info.get('sectorKey'),
            
            # Competitors
            competitors=competitors_data
        )
        
        # Step 10: Build SWOT Analysis (from web insights + financial analysis)
        # Build lists first, filter None values, then create SWOTAnalysis
        sector = safe_get(info, 'sector', 'N/A', str)
        
        strengths_list = [
            f"Strong market cap of ${info.get('marketCap', 0):,.0f}" if info.get('marketCap') else None,
            f"Healthy profit margin of {info.get('profitMargins', 0)*100:.2f}%" if info.get('profitMargins') and info.get('profitMargins') > 0.1 else None,
            f"Positive free cash flow of ${info.get('freeCashflow', 0):,.0f}" if info.get('freeCashflow') and info.get('freeCashflow') > 0 else None,
            "Established market presence" if info.get('marketCap', 0) > 1e9 else None
        ]
        weaknesses_list = [
            f"High debt-to-equity ratio of {info.get('debtToEquity', 0):.2f}" if info.get('debtToEquity') and info.get('debtToEquity') > 2 else None,
            f"Low profit margin of {info.get('profitMargins', 0)*100:.2f}%" if info.get('profitMargins') and info.get('profitMargins') < 0.05 else None,
            "High PE ratio indicating overvaluation" if info.get('trailingPE') and info.get('trailingPE') > 30 else None
        ]
        opportunities_list = [
            f"Growing sector: {sector}" if sector and sector != 'N/A' else None,
            "Market expansion potential",
            "Digital transformation opportunities"
        ]
        threats_list = [
            "Market volatility and economic uncertainty",
            "Competitive pressure from industry peers",
            f"Regulatory challenges in {sector} sector" if sector and sector != 'N/A' else None
        ]
        
        # Filter out None values and ensure non-empty lists BEFORE creating SWOTAnalysis
        strengths_filtered = [s for s in strengths_list if s] or ["Established market presence"]
        weaknesses_filtered = [w for w in weaknesses_list if w] or ["Market competition"]
        opportunities_filtered = [o for o in opportunities_list if o] or ["Market expansion potential"]
        threats_filtered = [t for t in threats_list if t] or ["Market volatility"]
        
        # Now create SWOTAnalysis with clean lists (no None values)
        swot = SWOTAnalysis(
            strengths=strengths_filtered,
            weaknesses=weaknesses_filtered,
            opportunities=opportunities_filtered,
            threats=threats_filtered
        )
        
        # Step 11: Enhanced News from Tavily search results (prioritize Tavily, filter empty items)
        news = []
        
        # First, add news from Tavily search results (higher quality, more relevant)
        for result in all_search_results[:5]:
            title = result.get('title', '').strip()
            url = result.get('url', '').strip()
            content = result.get('content', '').strip()[:200]
            
            # Only add if we have valid title and URL
            if title and url and len(title) > 5:
                # Avoid duplicates
                if not any(n['title'] == title for n in news):
                    news.append({
                        'title': title,
                        'publisher': url.split('/')[2] if '/' in url else 'Web',
                        'link': url,
                        'summary': content if content else 'No summary available',
                        'source': 'tavily'
                    })
        
        # Then, add news from yfinance only if we have fewer than 3 news items and they're valid
        if len(news) < 3:
            try:
                news_data = ticker.news[:3] if hasattr(ticker, 'news') else []
                for item in news_data:
                    title = item.get('title', '').strip()
                    publisher = item.get('publisher', '').strip()
                    link = item.get('link', '').strip()
                    
                    # Only add if we have valid title, publisher, and link
                    if title and publisher and link and len(title) > 5:
                        # Avoid duplicates
                        if not any(n['title'] == title for n in news):
                            news.append({
                                'title': title,
                                'publisher': publisher,
                                'link': link,
                                'source': 'yfinance'
                            })
            except Exception as e:
                print(f"Warning: Could not fetch yfinance news: {e}")
                pass
        
        # Step 12: Extract announcements from web insights
        announcements = []
        if web_insights['recent_developments']:
            announcements = web_insights['recent_developments'][:3]
        
        # Step 13: Create initial CompanyData object
        company_data = CompanyData(
            symbol=stock_symbol,
            name=company_name,
            snapshot=snapshot,
            business_overview=business_overview,
            financials=financials,
            market_data=market_data,
            swot=swot,
            news=news[:8],  # Limit to 8 most relevant news items
            announcements=announcements
        )
        
        # Step 13.5: ALWAYS fetch PE/PB and CEO from screener.in for Indian stocks (more accurate than yfinance)
        is_indian_stock = stock_symbol.endswith('.NS') or stock_symbol.endswith('.BO')
        
        if is_indian_stock:
            print(f"\n🇮🇳 Indian stock detected - fetching accurate data from screener.in...")
            try:
                from utils.screener_scraper import get_screener_financial_data
                
                screener_data = get_screener_financial_data(stock_symbol)
                
                if screener_data and screener_data.get('success'):
                    print(f"✅ Screener.in data retrieved successfully!")
                    
                    # ALWAYS override PE ratio from screener.in (more accurate)
                    if screener_data.get('pe_ratio') is not None:
                        old_pe = info.get('trailingPE')
                        info['trailingPE'] = screener_data['pe_ratio']
                        print(f"   ✓ PE Ratio: {old_pe} → {screener_data['pe_ratio']} (from screener.in)")
                    
                    # ALWAYS override PB ratio from screener.in
                    if screener_data.get('book_value') is not None and screener_data.get('current_price') is not None:
                        old_pb = info.get('priceToBook')
                        pb_ratio = screener_data['current_price'] / screener_data['book_value'] if screener_data['book_value'] > 0 else None
                        if pb_ratio:
                            info['priceToBook'] = pb_ratio
                            print(f"   ✓ PB Ratio: {old_pb} → {pb_ratio:.2f} (from screener.in)")
                    
                    # Override other key metrics
                    if screener_data.get('debt_to_equity') is not None:
                        info['debtToEquity'] = screener_data['debt_to_equity']
                        print(f"   ✓ Debt to Equity: {screener_data['debt_to_equity']}")
                    
                    if screener_data.get('promoter_holding') is not None:
                        info['heldPercentInsiders'] = screener_data['promoter_holding'] / 100
                        print(f"   ✓ Promoter Holding: {screener_data['promoter_holding']}%")
                    
                    if screener_data.get('fii_holding') is not None:
                        info['heldPercentInstitutions'] = screener_data['fii_holding'] / 100
                        print(f"   ✓ FII Holding: {screener_data['fii_holding']}%")
                    
                    print(f"✅ Key metrics updated from screener.in")
                    
                else:
                    print(f"⚠️ Screener.in data not available, using yfinance")
                    
            except Exception as e:
                print(f"⚠️ Error fetching from screener.in: {e}")
        
        # Step 13.6: Fetch CEO from web search (yfinance CEO is often outdated)
        print(f"\n👤 Fetching current CEO information from web...")
        ceo_found = False
        
        try:
            # Try multiple search queries for better results
            ceo_queries = [
                f"{company_name} CEO managing director 2024 2025 2026",
                f"{company_name} current CEO chairman",
                f"{stock_symbol} company CEO managing director"
            ]
            
            all_ceo_content = []
            
            for query in ceo_queries:
                try:
                    ceo_results, ceo_answer = StockTools._search_with_tavily(
                        query,
                        domain=["moneycontrol.com", "economictimes.com", "bseindia.com", "nseindia.com", "screener.in"]
                    )
                    
                    if ceo_answer:
                        all_ceo_content.append(ceo_answer)
                    
                    # Also add content from results
                    for result in ceo_results[:3]:
                        content = result.get('content', '')
                        if content:
                            all_ceo_content.append(content)
                    
                    if len(all_ceo_content) >= 3:
                        break  # Got enough content
                        
                except Exception as e:
                    print(f"⚠️ Search query failed: {e}")
                    continue
            
            if all_ceo_content:
                # Combine all content
                combined_ceo_content = "\n\n".join(all_ceo_content)[:4000]
                
                # Extract CEO name using LLM
                import json as json_module
                
                ceo_prompt = f"""Extract the CURRENT CEO, Managing Director, or Chairman name for {company_name} ({stock_symbol}) from the following information.

Information:
{combined_ceo_content}

Look for:
- CEO (Chief Executive Officer)
- Managing Director (MD)
- Chairman & Managing Director
- Executive Chairman

Return ONLY the person's full name in this JSON format:
{{"ceo_name": "Full Name", "title": "CEO/MD/Chairman"}}

If multiple people are mentioned, return the CEO or Managing Director (not independent directors or board members).
If not found, return: {{"ceo_name": null, "title": null}}

IMPORTANT: Return ONLY valid JSON, no explanations.

Return JSON:"""
                
                try:
                    model_name = "openai/gpt-4o-mini"
                    response = client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": "You are a data extraction expert. Extract CEO/MD names accurately from corporate information. Return only valid JSON."},
                            {"role": "user", "content": ceo_prompt}
                        ],
                        temperature=0.1,
                        max_tokens=150
                    )
                    
                    response_text = response.choices[0].message.content.strip()
                    
                    # Clean up response
                    if "```json" in response_text:
                        response_text = response_text.split("```json")[1].split("```")[0].strip()
                    elif "```" in response_text:
                        response_text = response_text.split("```")[1].split("```")[0].strip()
                    
                    # Remove any non-JSON text
                    if not response_text.startswith('{'):
                        # Find the first { and last }
                        start = response_text.find('{')
                        end = response_text.rfind('}')
                        if start != -1 and end != -1:
                            response_text = response_text[start:end+1]
                    
                    ceo_data = json_module.loads(response_text)
                    
                    if ceo_data.get('ceo_name') and ceo_data['ceo_name'] not in [None, 'null', 'N/A', '']:
                        ceo_name = ceo_data['ceo_name'].strip()
                        title = ceo_data.get('title', 'CEO')
                        
                        # Validate CEO name (should have at least 2 words)
                        if len(ceo_name.split()) >= 2:
                            snapshot.ceo = ceo_name
                            ceo_found = True
                            print(f"✅ CEO updated: {snapshot.ceo} ({title}) - from web search")
                        else:
                            print(f"⚠️ CEO name too short: '{ceo_name}' - might be invalid")
                    else:
                        print(f"⚠️ CEO not found in web search results")
                        
                except json_module.JSONDecodeError as e:
                    print(f"⚠️ Error parsing CEO JSON: {e}")
                    print(f"   Response was: {response_text[:200]}")
                except Exception as e:
                    print(f"⚠️ Error extracting CEO with LLM: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                print(f"⚠️ No CEO information found in web search")
                
        except Exception as e:
            print(f"⚠️ Error fetching CEO from web: {e}")
            import traceback
            traceback.print_exc()
        
        # Fallback: Try yfinance CEO if web search failed
        if not ceo_found:
            print(f"\n🔄 Trying yfinance CEO as fallback...")
            try:
                if info.get('companyOfficers') and len(info.get('companyOfficers', [])) > 0:
                    yf_ceo = info.get('companyOfficers')[0].get('name', 'N/A')
                    if yf_ceo and yf_ceo != 'N/A' and len(yf_ceo.split()) >= 2:
                        snapshot.ceo = yf_ceo
                        print(f"✅ CEO from yfinance: {snapshot.ceo} (may be outdated)")
                    else:
                        print(f"⚠️ No valid CEO in yfinance either")
                else:
                    print(f"⚠️ No company officers in yfinance")
            except Exception as e:
                print(f"⚠️ Error getting yfinance CEO: {e}")
        
        # Step 13.7: Validate data quality and add warnings
        print(f"\n🔍 Validating data quality for {company_name}...")
        try:
            from utils.data_validator import validate_stock_data
            
            # Prepare data for validation
            validation_data = {
                'pe_ratio': info.get('trailingPE'),
                'pb_ratio': info.get('priceToBook'),
                'debt_to_equity': info.get('debtToEquity'),
                'profit_margin': info.get('profitMargins') * 100 if info.get('profitMargins') else None,
                'total_liabilities': info.get('totalLiabilities'),
                'total_debt': info.get('totalDebt'),
                'eps': info.get('trailingEps'),
                'revenue': info.get('totalRevenue'),
                'promoter_holding': info.get('heldPercentInsiders') * 100 if info.get('heldPercentInsiders') else None,
                'fii_holding': info.get('heldPercentInstitutions') * 100 if info.get('heldPercentInstitutions') else None,
                'dii_holding': None,  # Not available in yfinance
                'current_price': info.get('currentPrice'),
                'high_52w': info.get('fiftyTwoWeekHigh'),
                'low_52w': info.get('fiftyTwoWeekLow'),
                'ceo': snapshot.ceo,
                'last_fiscal_year_end': info.get('lastFiscalYearEnd')
            }
            
            # Run validation
            validated_data, quality_report = validate_stock_data(validation_data)
            
            # Check if data is stale or has critical issues
            data_is_stale = validated_data.get('data_freshness') in ['stale', 'very_stale']
            has_critical_issues = "Critical Issues" in quality_report
            
            # Step 13.8: Additional fallback if still have issues after screener.in override
            if data_is_stale or has_critical_issues:
                print(f"\n⚠️ YFinance data quality issues detected:")
                if data_is_stale:
                    print(f"   • Data is {validated_data.get('data_freshness')} (>90 days old)")
                if has_critical_issues:
                    print(f"   • Critical data inconsistencies found")
                
                print(f"\n🔄 Attempting to fetch fresh data from screener.in...")
                
                try:
                    # Try screener.in first (most accurate for Indian stocks)
                    from utils.screener_scraper import get_screener_financial_data
                    
                    screener_data = get_screener_financial_data(stock_symbol)
                    
                    if screener_data and screener_data.get('success'):
                        print(f"✅ Fresh data retrieved from screener.in!")
                        
                        # Map screener.in data to yfinance field names
                        updated_fields = []
                        
                        if screener_data.get('market_cap') is not None:
                            info['marketCap'] = screener_data['market_cap']
                            updated_fields.append('market_cap')
                        
                        if screener_data.get('current_price') is not None:
                            info['currentPrice'] = screener_data['current_price']
                            updated_fields.append('current_price')
                        
                        if screener_data.get('pe_ratio') is not None:
                            info['trailingPE'] = screener_data['pe_ratio']
                            updated_fields.append('pe_ratio')
                        
                        if screener_data.get('book_value') is not None:
                            # Calculate PB ratio if we have market cap and book value
                            if screener_data.get('market_cap'):
                                # PB = Market Cap / (Book Value * Shares Outstanding)
                                # Or use direct calculation if available
                                info['priceToBook'] = screener_data.get('current_price', 0) / screener_data['book_value'] if screener_data['book_value'] > 0 else None
                                if info.get('priceToBook'):
                                    updated_fields.append('pb_ratio')
                        
                        if screener_data.get('debt_to_equity') is not None:
                            info['debtToEquity'] = screener_data['debt_to_equity']
                            updated_fields.append('debt_to_equity')
                        
                        if screener_data.get('total_debt') is not None:
                            info['totalDebt'] = screener_data['total_debt']
                            updated_fields.append('total_debt')
                        
                        if screener_data.get('total_assets') is not None:
                            info['totalAssets'] = screener_data['total_assets']
                            updated_fields.append('total_assets')
                        
                        if screener_data.get('operating_margin') is not None:
                            info['operatingMargins'] = screener_data['operating_margin'] / 100  # Convert % to decimal
                            updated_fields.append('operating_margin')
                        
                        if screener_data.get('profit_margin') is not None:
                            info['profitMargins'] = screener_data['profit_margin'] / 100  # Convert % to decimal
                            updated_fields.append('profit_margin')
                        
                        if screener_data.get('dividend_yield') is not None:
                            info['dividendYield'] = screener_data['dividend_yield'] / 100  # Convert % to decimal
                            updated_fields.append('dividend_yield')
                        
                        if screener_data.get('promoter_holding') is not None:
                            info['heldPercentInsiders'] = screener_data['promoter_holding'] / 100  # Convert % to decimal
                            updated_fields.append('promoter_holding')
                        
                        if screener_data.get('fii_holding') is not None:
                            info['heldPercentInstitutions'] = screener_data['fii_holding'] / 100  # Convert % to decimal
                            updated_fields.append('fii_holding')
                        
                        if screener_data.get('high_52week') is not None:
                            info['fiftyTwoWeekHigh'] = screener_data['high_52week']
                            updated_fields.append('52w_high')
                        
                        if screener_data.get('low_52week') is not None:
                            info['fiftyTwoWeekLow'] = screener_data['low_52week']
                            updated_fields.append('52w_low')
                        
                        if screener_data.get('enterprise_value') is not None:
                            info['enterpriseValue'] = screener_data['enterprise_value']
                            updated_fields.append('enterprise_value')
                        
                        if screener_data.get('ev_ebitda') is not None:
                            info['enterpriseToEbitda'] = screener_data['ev_ebitda']
                            updated_fields.append('ev_ebitda')
                        
                        if screener_data.get('roe') is not None:
                            info['returnOnEquity'] = screener_data['roe'] / 100  # Convert % to decimal
                            updated_fields.append('roe')
                        
                        if screener_data.get('roce') is not None:
                            info['returnOnAssets'] = screener_data['roce'] / 100  # Convert % to decimal (using as proxy)
                            updated_fields.append('roce')
                        
                        print(f"   • Updated {len(updated_fields)} fields from screener.in")
                        for field in updated_fields:
                            print(f"     - {field}")
                        
                        # Re-validate with fresh data
                        validation_data_updated = {
                            'pe_ratio': info.get('trailingPE'),
                            'pb_ratio': info.get('priceToBook'),
                            'debt_to_equity': info.get('debtToEquity'),
                            'profit_margin': info.get('profitMargins') * 100 if info.get('profitMargins') else None,
                            'total_liabilities': info.get('totalLiabilities'),
                            'total_debt': info.get('totalDebt'),
                            'eps': info.get('trailingEps'),
                            'revenue': info.get('totalRevenue'),
                            'promoter_holding': info.get('heldPercentInsiders') * 100 if info.get('heldPercentInsiders') else None,
                            'fii_holding': info.get('heldPercentInstitutions') * 100 if info.get('heldPercentInstitutions') else None,
                            'dii_holding': None,
                            'current_price': info.get('currentPrice'),
                            'high_52w': info.get('fiftyTwoWeekHigh'),
                            'low_52w': info.get('fiftyTwoWeekLow'),
                            'ceo': snapshot.ceo,
                            'last_fiscal_year_end': int(time.time())  # Mark as fresh
                        }
                        
                        validated_data, quality_report = validate_stock_data(validation_data_updated)
                        
                        # Add note about data source
                        quality_report = f"ℹ️ **Data Source Update**: Fresh data retrieved from screener.in due to stale yfinance data.\n\n{quality_report}"
                        
                    else:
                        # Fallback to Tavily if screener.in fails
                        print(f"⚠️ Screener.in data not available, trying Tavily web search...")
                        
                        fresh_data = StockTools._fetch_fresh_data_from_tavily(
                            company_name=company_name,
                            stock_symbol=stock_symbol,
                            current_data=info
                        )
                        
                        if fresh_data and fresh_data.get('success'):
                            print(f"✅ Fresh data retrieved from Tavily!")
                            print(f"   • Updated {len(fresh_data.get('updated_fields', []))} fields")
                            
                            # Update info with fresh data
                            for field, value in fresh_data.get('data', {}).items():
                                if value is not None:
                                    info[field] = value
                            
                            # Re-validate with fresh data
                            validation_data_updated = {
                                'pe_ratio': info.get('trailingPE'),
                                'pb_ratio': info.get('priceToBook'),
                                'debt_to_equity': info.get('debtToEquity'),
                                'profit_margin': info.get('profitMargins') * 100 if info.get('profitMargins') else None,
                                'total_liabilities': info.get('totalLiabilities'),
                                'total_debt': info.get('totalDebt'),
                                'eps': info.get('trailingEps'),
                                'revenue': info.get('totalRevenue'),
                                'promoter_holding': info.get('heldPercentInsiders') * 100 if info.get('heldPercentInsiders') else None,
                                'fii_holding': info.get('heldPercentInstitutions') * 100 if info.get('heldPercentInstitutions') else None,
                                'dii_holding': None,
                                'current_price': info.get('currentPrice'),
                                'high_52w': info.get('fiftyTwoWeekHigh'),
                                'low_52w': info.get('fiftyTwoWeekLow'),
                                'ceo': snapshot.ceo,
                                'last_fiscal_year_end': int(time.time())  # Mark as fresh
                            }
                            
                            validated_data, quality_report = validate_stock_data(validation_data_updated)
                            
                            # Add note about data source
                            quality_report = f"ℹ️ **Data Source Update**: Fresh data retrieved from Tavily web search due to stale yfinance data.\n\n{quality_report}"
                        else:
                            print(f"⚠️ Could not retrieve fresh data from Tavily either, using yfinance data with warnings")
                        
                except Exception as fallback_error:
                    print(f"⚠️ Data fallback failed: {fallback_error}")
                    import traceback
                    traceback.print_exc()
                    print(f"   Using yfinance data with validation warnings")
            
            # Store validation results in company_data for later use
            company_data._validation_report = quality_report
            company_data._validated_data = validated_data
            
            print(f"✅ Data validation complete")
            if "Critical Issues" in quality_report or "Warnings" in quality_report:
                print(f"⚠️ Data quality issues detected - will be shown in report")
            else:
                print(f"✅ All data passed validation checks")
                
        except Exception as validation_error:
            print(f"⚠️ Data validation error: {validation_error}")
            # Continue without validation if it fails
            company_data._validation_report = None
            company_data._validated_data = None
        
        # Step 14: Check for missing fields and backfill using Tavily search
        # DISABLED: This was causing infinite loops and multiple function calls
        company_data = StockTools._check_and_backfill_missing_data(company_data, stock_symbol)

        # Optional: Save data to test directory for debugging (create directory if it doesn't exist)
        try:
            import os
            os.makedirs("test", exist_ok=True)
            with open(f"test/{company_name}.json", "w") as f:
                json.dump(company_data.model_dump(mode='json'), f, indent=4)
            print(f"✅ Saved debug data to test/{company_name}.json")
        except Exception as e:
            print(f"⚠️ Could not save debug data: {str(e)}")
        
        return company_data
    
    @staticmethod
    def format_data_for_report(company_data: CompanyData) -> str:
        """Helper to format comprehensive company data for display"""
        
        # Detect if this is an Indian stock (ends with .NS or .BO)
        is_indian_stock = company_data.symbol.endswith('.NS') or company_data.symbol.endswith('.BO')
        currency_symbol = '₹' if is_indian_stock else '$'
        
        # Helper function to format currency (Indian Rupees in Lakhs/Crores or USD in M/B)
        def fmt_currency(value):
            if value is None or value == 'N/A' or not isinstance(value, (int, float)):
                return 'N/A'
            
            if is_indian_stock:
                # Indian format: Lakhs and Crores
                if value >= 1e7:  # 1 Crore = 10 Million
                    return f"₹{value/1e7:.2f} Cr"
                elif value >= 1e5:  # 1 Lakh = 100 Thousand
                    return f"₹{value/1e5:.2f} L"
                else:
                    return f"₹{value:,.0f}"
            else:
                # US format: Millions, Billions, Trillions
                if value >= 1e12:
                    return f"${value/1e12:.2f}T"
                elif value >= 1e9:
                    return f"${value/1e9:.2f}B"
                elif value >= 1e6:
                    return f"${value/1e6:.2f}M"
                else:
                    return f"${value:,.0f}"
        
        # Helper function to format percentage
        def fmt_pct(value):
            if value is None or value == 'N/A' or not isinstance(value, (int, float)):
                return 'N/A'
            return f"{value:.2f}%"
        
        # Helper function to format ratio
        def fmt_ratio(value):
            if value is None or value == 'N/A' or not isinstance(value, (int, float)):
                return 'N/A'
            return f"{value:.2f}"
        
        # Helper function to format number
        def fmt_num(value):
            if value is None or value == 'N/A' or not isinstance(value, (int, float)):
                return 'N/A'
            if is_indian_stock and value >= 1e5:
                # Format large numbers in Lakhs/Crores
                if value >= 1e7:
                    return f"{value/1e7:.2f} Cr"
                else:
                    return f"{value/1e5:.2f} L"
            return f"{value:,.0f}"
        
        # 1. COMPANY SNAPSHOT - Skip N/A values, ensure proper line breaks
        snapshot_lines = ["🏢 **COMPANY SNAPSHOT**"]
        
        if company_data.snapshot.company_name and company_data.snapshot.company_name != 'N/A':
            snapshot_lines.append(f"• **Company Name:** {company_data.snapshot.company_name}")
        if company_data.snapshot.ticker_symbol and company_data.snapshot.ticker_symbol != 'N/A':
            snapshot_lines.append(f"• **Ticker Symbol:** {company_data.snapshot.ticker_symbol}")
        if company_data.snapshot.exchange and company_data.snapshot.exchange != 'N/A':
            snapshot_lines.append(f"• **Exchange:** {company_data.snapshot.exchange}")
        if company_data.snapshot.sector and company_data.snapshot.sector != 'N/A':
            snapshot_lines.append(f"• **Sector:** {company_data.snapshot.sector}")
        if company_data.snapshot.industry and company_data.snapshot.industry != 'N/A':
            snapshot_lines.append(f"• **Industry:** {company_data.snapshot.industry}")
        if company_data.snapshot.headquarters and company_data.snapshot.headquarters != 'N/A':
            snapshot_lines.append(f"• **Headquarters:** {company_data.snapshot.headquarters}")
        if company_data.snapshot.founded_year and company_data.snapshot.founded_year != 'N/A':
            snapshot_lines.append(f"• **Founded:** {company_data.snapshot.founded_year}")
        if company_data.snapshot.ceo and company_data.snapshot.ceo != 'N/A':
            snapshot_lines.append(f"• **CEO:** {company_data.snapshot.ceo}")
        if company_data.snapshot.employees:
            emp_formatted = fmt_num(company_data.snapshot.employees)
            if emp_formatted != 'N/A':
                snapshot_lines.append(f"• **Employees:** {emp_formatted}")
        if company_data.snapshot.website and company_data.snapshot.website != 'N/A':
            snapshot_lines.append(f"• **Website:** {company_data.snapshot.website}")
        
        # Join with single newlines for compact display
        snapshot_section = "\n".join(snapshot_lines)
        
        # 2. BUSINESS OVERVIEW - Skip N/A values, ensure proper line breaks
        business_lines = ["📋 **BUSINESS OVERVIEW**"]
        
        if company_data.business_overview.description and company_data.business_overview.description != 'N/A':
            business_lines.append(f"{company_data.business_overview.description[:1000]}...")
        
        if company_data.business_overview.geographic_presence and company_data.business_overview.geographic_presence != 'N/A':
            business_lines.append(f"• **Geographic Presence:** {company_data.business_overview.geographic_presence}")
        
        business_section = "\n".join(business_lines)
        
        # 3. FINANCIAL METRICS
        eps_val = f"{currency_symbol}{company_data.financials.eps:.2f}" if company_data.financials.eps else 'N/A'
        div_yield = fmt_pct(company_data.financials.dividend_yield * 100) if company_data.financials.dividend_yield else 'N/A'
        payout = fmt_pct(company_data.financials.payout_ratio * 100) if company_data.financials.payout_ratio else 'N/A'
        debt_eq = f"{company_data.financials.debt_to_equity:.2f}" if company_data.financials.debt_to_equity else 'N/A'
        pe_val = f"{company_data.financials.pe_ratio:.2f}" if company_data.financials.pe_ratio else 'N/A'
        pb_val = f"{company_data.financials.pb_ratio:.2f}" if company_data.financials.pb_ratio else 'N/A'
        peg_val = f"{company_data.financials.peg_ratio:.2f}" if company_data.financials.peg_ratio else 'N/A'
        ev_ebitda = f"{company_data.financials.ev_ebitda:.2f}" if company_data.financials.ev_ebitda else 'N/A'
        profit_margin = fmt_pct(company_data.financials.profit_margin * 100) if company_data.financials.profit_margin else 'N/A'
        op_margin = fmt_pct(company_data.financials.operating_margin * 100) if company_data.financials.operating_margin else 'N/A'
        gross_margin = fmt_pct(company_data.financials.gross_margin * 100) if company_data.financials.gross_margin else 'N/A'
        
        # Build financial section dynamically, skipping N/A values, ensure proper line breaks
        financial_lines = ["💰 **FINANCIAL METRICS (Real-Time)**"]  
        
        # Income Statement
        income_items = []
        if company_data.financials.revenue: income_items.append(f"- Revenue (TTM): {fmt_currency(company_data.financials.revenue)}")
        if company_data.financials.net_profit: income_items.append(f"- Net Profit (TTM): {fmt_currency(company_data.financials.net_profit)}")
        if company_data.financials.ebitda: income_items.append(f"- EBITDA: {fmt_currency(company_data.financials.ebitda)}")
        if company_data.financials.eps: income_items.append(f"- EPS: {eps_val}")
        if company_data.financials.dividend_yield: income_items.append(f"- Dividend Yield: {div_yield}")
        if company_data.financials.payout_ratio: income_items.append(f"- Payout Ratio: {payout}")
        
        if income_items:
            financial_lines.append("**Income Statement:**")
            financial_lines.extend(income_items)
            # financial_lines.append("")  # Add empty line after section
        
        # Balance Sheet
        balance_items = []
        if company_data.financials.total_assets: balance_items.append(f"- Total Assets: {fmt_currency(company_data.financials.total_assets)}")
        if company_data.financials.total_liabilities: balance_items.append(f"- Total Liabilities: {fmt_currency(company_data.financials.total_liabilities)}")
        if company_data.financials.total_debt: balance_items.append(f"- Total Debt: {fmt_currency(company_data.financials.total_debt)}")
        if company_data.financials.cash_balance: balance_items.append(f"- Cash Balance: {fmt_currency(company_data.financials.cash_balance)}")
        if company_data.financials.debt_to_equity: balance_items.append(f"- Debt-to-Equity Ratio: {debt_eq}")
        
        if balance_items:
            financial_lines.append("**Balance Sheet:**")
            financial_lines.extend(balance_items)
            # financial_lines.append("")  # Add empty line after section
        
        # Cash Flow
        cashflow_items = []
        if company_data.financials.operating_cash_flow: cashflow_items.append(f"- Operating Cash Flow: {fmt_currency(company_data.financials.operating_cash_flow)}")
        if company_data.financials.free_cash_flow: cashflow_items.append(f"- Free Cash Flow: {fmt_currency(company_data.financials.free_cash_flow)}")
        
        if cashflow_items:
            financial_lines.append("**Cash Flow:**")
            financial_lines.extend(cashflow_items)
            # financial_lines.append("")  # Add empty line after section
        
        # Valuation Metrics
        valuation_items = []
        if company_data.financials.pe_ratio: valuation_items.append(f"- PE Ratio: {pe_val}")
        if company_data.financials.pb_ratio: valuation_items.append(f"- PB Ratio: {pb_val}")
        if company_data.financials.peg_ratio: valuation_items.append(f"- PEG Ratio: {peg_val}")
        if company_data.financials.enterprise_value: valuation_items.append(f"- Enterprise Value: {fmt_currency(company_data.financials.enterprise_value)}")
        if company_data.financials.ev_ebitda: valuation_items.append(f"- EV/EBITDA: {ev_ebitda}")
        
        if valuation_items:
            financial_lines.append("**Valuation Metrics:**")
            financial_lines.extend(valuation_items)
            # financial_lines.append("")  # Add empty line after section
        
        # Profitability Margins
        margin_items = []
        if company_data.financials.profit_margin: margin_items.append(f"- Profit Margin: {profit_margin}")
        if company_data.financials.operating_margin: margin_items.append(f"- Operating Margin: {op_margin}")
        if company_data.financials.gross_margin: margin_items.append(f"- Gross Margin: {gross_margin}")
        
        if margin_items:
            financial_lines.append("\n**Profitability Margins:**")
            financial_lines.extend(margin_items)
        
        financial_section = "\n".join(financial_lines)
        
        # 3.5. DATA QUALITY REPORT (if validation was performed)
        data_quality_section = ""
        if hasattr(company_data, '_validation_report') and company_data._validation_report:
            # Only include if there are warnings or issues
            if "Critical Issues" in company_data._validation_report or "Warnings" in company_data._validation_report:
                data_quality_section = f"\n\n🔍 **DATA QUALITY ASSESSMENT**\n\n{company_data._validation_report}"
        
        # 4. STOCK INFORMATION & MARKET DATA
        curr_price = f"{currency_symbol}{company_data.market_data.current_price:.2f}" if company_data.market_data.current_price else 'N/A'
        week_high = f"{currency_symbol}{company_data.market_data.week_52_high:.2f}" if company_data.market_data.week_52_high else 'N/A'
        week_low = f"{currency_symbol}{company_data.market_data.week_52_low:.2f}" if company_data.market_data.week_52_low else 'N/A'
        beta_val = f"{company_data.market_data.beta:.2f}" if company_data.market_data.beta else 'N/A'
        
        # Smart holdings formatting - detect if value is decimal (< 1) or percentage (> 1)
        # YFinance returns decimals (0.7177), screener.in returns percentages (71.77)
        def format_holding(value):
            if value is None:
                return 'N/A'
            # If value is less than 1, it's in decimal format (0.7177 = 71.77%)
            if value < 1:
                return fmt_pct(value * 100)
            # If value is >= 1, it's already in percentage format (71.77 = 71.77%)
            else:
                return fmt_pct(value)
        
        promoter = format_holding(company_data.market_data.promoter_holding)
        fii = format_holding(company_data.market_data.fii_holding)
        dii = format_holding(company_data.market_data.dii_holding)
        
        # Build market section dynamically, skipping N/A values
        market_lines = ["📈 **STOCK INFORMATION & MARKET DATA**"]
        
        if company_data.market_data.current_price: market_lines.append(f"• Current Share Price: {curr_price}")
        if company_data.market_data.week_52_high: market_lines.append(f"• 52-Week High: {week_high}")
        if company_data.market_data.week_52_low: market_lines.append(f"• 52-Week Low: {week_low}")
        if company_data.market_data.market_cap: market_lines.append(f"• Market Capitalization: {fmt_currency(company_data.market_data.market_cap)}")
        if company_data.market_data.volume: market_lines.append(f"• Volume: {fmt_num(company_data.market_data.volume)}")
        if company_data.market_data.avg_volume: market_lines.append(f"• Average Volume: {fmt_num(company_data.market_data.avg_volume)}")
        if company_data.market_data.beta: market_lines.append(f"• Beta (Volatility): {beta_val}")
        
        # Holdings
        holding_items = []
        if company_data.market_data.promoter_holding: holding_items.append(f"• Promoter Holding: {promoter}")
        if company_data.market_data.fii_holding: holding_items.append(f"• FII Holding: {fii}")
        if company_data.market_data.dii_holding: holding_items.append(f"• DII Holding: {dii}")
        
        if holding_items:
            market_lines.append("**Holdings:**")
            market_lines.extend(holding_items)
        
        market_section = "\n".join(market_lines) 
        
        # 5. PRICE PERFORMANCE - Skip N/A values
        performance_lines = ["📊 **PRICE PERFORMANCE**"]
        
        if company_data.market_data.day_change is not None:
            day_ind = '📈' if company_data.market_data.day_change > 0 else '📉'
            performance_lines.append(f"• 1 Day Change: {fmt_pct(company_data.market_data.day_change)} {day_ind}")
        if company_data.market_data.week_change is not None:
            week_ind = '📈' if company_data.market_data.week_change > 0 else '📉'
            performance_lines.append(f"• 1 Week Change: {fmt_pct(company_data.market_data.week_change)} {week_ind}")
        if company_data.market_data.month_change is not None:
            month_ind = '📈' if company_data.market_data.month_change > 0 else '📉'
            performance_lines.append(f"• 1 Month Change: {fmt_pct(company_data.market_data.month_change)} {month_ind}")
        if company_data.market_data.month_6_change is not None:
            month6_ind = '📈' if company_data.market_data.month_6_change > 0 else '📉'
            performance_lines.append(f"• 6 Month Change: {fmt_pct(company_data.market_data.month_6_change)} {month6_ind}")
        if company_data.market_data.year_change is not None:
            year_ind = '📈' if company_data.market_data.year_change > 0 else '📉'
            performance_lines.append(f"• 1 Year Change: {fmt_pct(company_data.market_data.year_change)} {year_ind}")
        if company_data.market_data.year_5_cagr is not None:
            year5_ind = '📈' if company_data.market_data.year_5_cagr > 0 else '📉'
            performance_lines.append(f"• 5 Year CAGR: {fmt_pct(company_data.market_data.year_5_cagr)} {year5_ind}")
        
        performance_section = "\n".join(performance_lines)
        
        # Add price history if available
        if company_data.market_data.price_history:
            performance_section += "\n**Recent Price History (Last 7 Days):**"
        
        # Add last 7 days price history - each day on separate line
        if company_data.market_data.price_history:
            recent_prices = list(company_data.market_data.price_history.items())[-7:]
            for i, (date, price) in enumerate(recent_prices):
                if i > 0:
                    prev_price = recent_prices[i-1][1]
                    change = ((price - prev_price) / prev_price) * 100
                    performance_section += f"\n• {date}: {currency_symbol}{price:.2f} ({change:+.2f}%) {'📈' if change > 0 else '📉'}"
                else:
                    performance_section += f"\n• {date}: {currency_symbol}{price:.2f}"
        
        # 6. COMPETITOR COMPARISON
        competitor_section = "\n\n🏆 **COMPETITOR COMPARISON**\n\n"
        
        if company_data.market_data.competitors:
            # Check if we have real competitor data (not just placeholder)
            has_real_data = any(
                comp.get('source') in ['yfinance', 'sector_default', 'screener.in'] and 
                not comp.get('is_main_company') and
                comp.get('symbol') != 'N/A'
                for comp in company_data.market_data.competitors
            )
            
            if has_real_data:
                # Clean table format without vertical lines
                competitor_section += "**Peer Comparison (Sector Analysis)**\n\n"
                
                # Show main company first
                main_comp = next((comp for comp in company_data.market_data.competitors if comp.get('is_main_company')), None)
                if main_comp:
                    name = main_comp['name'][:30]
                    symbol = main_comp.get('symbol', 'N/A')
                    mcap = fmt_currency(main_comp.get('market_cap')) if main_comp.get('market_cap') != 'N/A' else 'N/A'
                    pe = fmt_ratio(main_comp.get('pe_ratio'))
                    pm = fmt_pct(main_comp.get('profit_margin') * 100) if isinstance(main_comp.get('profit_margin'), (int, float)) else 'N/A'
                    
                    competitor_section += f"**{name}** ({symbol})\n"
                    competitor_section += f"• Market Cap: {mcap}\n"
                    competitor_section += f"• PE Ratio: {pe}\n"
                    competitor_section += f"• Profit Margin: {pm}\n\n"
                
                # Show peer companies
                competitor_section += "**Key Competitors:**\n"
                peer_count = 0
                for comp in company_data.market_data.competitors:
                    if not comp.get('is_main_company') and peer_count < 4:
                        name = comp['name'][:30]
                        symbol = comp.get('symbol', 'N/A')
                        mcap = fmt_currency(comp.get('market_cap')) if comp.get('market_cap') != 'N/A' else 'N/A'
                        pe = fmt_ratio(comp.get('pe_ratio'))
                        pm = fmt_pct(comp.get('profit_margin') * 100) if isinstance(comp.get('profit_margin'), (int, float)) else 'N/A'
                        
                        competitor_section += f"\n**{name}** ({symbol})\n"
                        competitor_section += f"• Market Cap: {mcap}\n"
                        competitor_section += f"• PE Ratio: {pe}\n"
                        competitor_section += f"• Profit Margin: {pm}\n"
                        peer_count += 1
                
            else:
                # Simple comparison format for basic data
                competitor_section += "**Financial Metrics Comparison**\n"
                
                # Get up to 4 competitors (including main company)
                main_company = next((comp for comp in company_data.market_data.competitors if comp.get('is_main_company')), None)
                peer_companies = [comp for comp in company_data.market_data.competitors if not comp.get('is_main_company')][:3]
                
                if main_company:
                    all_companies = [main_company] + peer_companies
                else:
                    all_companies = peer_companies[:4]
                
                if all_companies:
                    for i, comp in enumerate(all_companies):
                        company_name = comp.get('name', 'Unknown')[:25]
                        if comp.get('is_main_company'):
                            company_name += " (Current Company)"
                        
                        competitor_section += f"**{i+1}. {company_name}**\n"
                        
                        # Revenue
                        if comp.get('is_main_company'):
                            revenue = fmt_currency(company_data.financials.revenue)
                        else:
                            revenue = fmt_currency(comp.get('revenue'))
                        competitor_section += f"• Revenue: {revenue}\n"
                        
                        # PE Ratio
                        if comp.get('is_main_company'):
                            pe = fmt_ratio(company_data.financials.pe_ratio)
                        else:
                            pe = fmt_ratio(comp.get('pe_ratio'))
                        competitor_section += f"• PE Ratio: {pe}\n"
                        
                        # Market Cap
                        if comp.get('is_main_company'):
                            mcap = fmt_currency(company_data.market_data.market_cap)
                        else:
                            mcap = fmt_currency(comp.get('market_cap'))
                        competitor_section += f"• Market Cap: {mcap}\n"
                        
                        # Profit Margin
                        if comp.get('is_main_company'):
                            pm = fmt_pct(company_data.financials.profit_margin * 100) if isinstance(company_data.financials.profit_margin, (int, float)) else 'N/A'
                        else:
                            pm = fmt_pct(comp.get('profit_margin') * 100) if isinstance(comp.get('profit_margin'), (int, float)) else 'N/A'
                        competitor_section += f"• Profit Margin: {pm}\n\n"
                else:
                    competitor_section += "• No competitor data available for comparison\n"
        else:
            competitor_section += "• No competitor data available\n"
        
        # 7. SWOT ANALYSIS - Skip empty sections, ensure proper line breaks
        swot_lines = ["🎯 **SWOT ANALYSIS**\n"]  
        
        if company_data.swot.strengths:
            swot_lines.append("**Strengths:**")
            swot_lines.extend([f"• {s}" for s in company_data.swot.strengths])
            swot_lines.append("")  # Add empty line after section
        
        if company_data.swot.weaknesses:
            swot_lines.append("**Weaknesses:**")
            swot_lines.extend([f"• {w}" for w in company_data.swot.weaknesses])
            swot_lines.append("")  # Add empty line after section
        
        if company_data.swot.opportunities:
            swot_lines.append("**Opportunities:**")
            swot_lines.extend([f"• {o}" for o in company_data.swot.opportunities])
            swot_lines.append("")  # Add empty line after section
        
        if company_data.swot.threats:
            swot_lines.append("**Threats:**")
            swot_lines.extend([f"• {t}" for t in company_data.swot.threats])
        
        # If no SWOT data at all, show message
        if len(swot_lines) == 2:  # Only header and empty line
            swot_lines.append("• SWOT analysis data not available")
        
        swot_section = "\n".join(swot_lines) 
        
        # 8. NEWS & ANNOUNCEMENTS - Skip empty sections, ensure proper line breaks
        news_lines = ["📰 **NEWS & ANNOUNCEMENTS**"]  
        
        if company_data.news:
            news_lines.append("**Recent News:**")
            news_lines.extend([f"• {n['title']}" for n in company_data.news[:5]])
            news_lines.append("")  # Add empty line after section
        
        if company_data.announcements:
            news_lines.append("**Company Announcements:**")
            news_lines.extend([f"• {a}" for a in company_data.announcements[:3]])
        
        # If no news or announcements, show message
        if len(news_lines) == 2:  # Only header and empty line
            news_lines.append("• No recent news or announcements available")
        
        news_section = "\n".join(news_lines) 
        
        # 9. EXPERT OPINION - Generate using latest news and current data
        expert_opinion_section = "👨‍💼 **EXPERT OPINION**\n"
        
        try:
            # Generate expert opinion using Tavily + LLM
            expert_opinion_text = StockTools.generate_expert_opinion(company_data)
            expert_opinion_section += expert_opinion_text + "\n\n"
        except Exception as e:
            print(f"Warning: Could not generate expert opinion: {e}")
            expert_opinion_section += "Expert analysis temporarily unavailable.\n\n"
        
        # Combine all sections with proper spacing - ensure each section is properly separated
        full_report = f"""📊 **COMPREHENSIVE STOCK ANALYSIS** - *{company_data.name}*

{snapshot_section.rstrip()}

{business_section.rstrip()}

{financial_section.rstrip()}{data_quality_section}

{market_section.rstrip()}

{performance_section.rstrip()}

{competitor_section.rstrip()}

{swot_section.rstrip()}

{news_section.rstrip()}

{expert_opinion_section.rstrip()}"""
        
        # Ensure consistent formatting and remove excessive newlines
        full_report = full_report.replace('\n\n\n\n', '\n\n')  # Remove quadruple newlines
        full_report = full_report.replace('\n\n\n', '\n\n')    # Remove triple newlines
        
        return full_report
    
    @staticmethod
    def generate_expert_opinion(company_data: CompanyData) -> str:
        """
        Generate expert opinion on the stock using latest news and current data
        Uses Tavily API to search for latest news and LLM for opinion generation
        """
        try:
            # Search for latest news about the stock using Tavily
            stock_name = company_data.name
            symbol = company_data.symbol
            
            # Prepare search query for latest news
            news_query = f"{stock_name} {symbol} latest news analysis"
            
            # Use Tavily to search for latest news
            search_results, answer = StockTools._search_with_tavily(news_query)
            
            # Prepare data summary for LLM
            is_indian_stock = symbol.endswith('.NS') or symbol.endswith('.BO')
            currency_symbol = '₹' if is_indian_stock else '$'
            
            # Format key metrics
            def fmt_currency(value):
                if value is None or not isinstance(value, (int, float)):
                    return 'N/A'
                if is_indian_stock:
                    if value >= 1e7:
                        return f"₹{value/1e7:.2f} Cr"
                    elif value >= 1e5:
                        return f"₹{value/1e5:.2f} L"
                    else:
                        return f"₹{value:,.0f}"
                else:
                    if value >= 1e9:
                        return f"${value/1e9:.2f}B"
                    elif value >= 1e6:
                        return f"${value/1e6:.2f}M"
                    else:
                        return f"${value:,.0f}"
            
            # Build comprehensive data context
            current_price = f"{currency_symbol}{company_data.market_data.current_price:.2f}" if company_data.market_data.current_price else 'N/A'
            market_cap = fmt_currency(company_data.market_data.market_cap) if company_data.market_data.market_cap else 'N/A'
            pe_ratio = f"{company_data.financials.pe_ratio:.2f}" if company_data.financials.pe_ratio else 'N/A'
            revenue = fmt_currency(company_data.financials.revenue) if company_data.financials.revenue else 'N/A'
            profit_margin = f"{company_data.financials.profit_margin*100:.2f}%" if company_data.financials.profit_margin else 'N/A'
            
            # Get recent performance
            day_change = f"{company_data.market_data.day_change:.2f}%" if company_data.market_data.day_change is not None else 'N/A'
            year_change = f"{company_data.market_data.year_change:.2f}%" if company_data.market_data.year_change is not None else 'N/A'
            
            # Extract latest news headlines
            latest_news = []
            if search_results:
                for result in search_results[:5]:
                    title = result.get('title', '')
                    if title:
                        latest_news.append(title)
            
            news_summary = "\n".join([f"• {news}" for news in latest_news]) if latest_news else "No recent news available"
            
            
            model = get_model()
            
            # Create prompt for expert opinion
            prompt = f"""You are a seasoned financial analyst with expertise in stock market analysis. Generate a comprehensive expert opinion on {stock_name} ({symbol}) based on current data and latest news.

CURRENT STOCK DATA:
- Current Price: {current_price}
- Market Cap: {market_cap}
- PE Ratio: {pe_ratio}
- Revenue: {revenue}
- Profit Margin: {profit_margin}
- Day Change: {day_change}
- Year Change: {year_change}
- Sector: {company_data.market_data.sector or 'Not specified'}

LATEST NEWS & DEVELOPMENTS:
{news_summary}

SWOT HIGHLIGHTS:
Strengths: {', '.join(company_data.swot.strengths[:3]) if company_data.swot.strengths else 'Not available'}
Weaknesses: {', '.join(company_data.swot.weaknesses[:3]) if company_data.swot.weaknesses else 'Not available'}

Generate a detailed expert opinion (3-4 paragraphs) covering:
1. Current market position and recent performance analysis
2. Assessment based on latest news and market developments
3. Key considerations for investors (both bullish and bearish factors)
4. Overall outlook and recommendation considerations

Write in a professional, balanced tone. Be specific with data points. Do NOT use bullet points - write in flowing paragraphs.
Do NOT start with "Expert Opinion:" or any heading - just provide the analysis directly."""

            # Generate expert opinion using LLM
            completion = client.chat.completions.create(
                model="openai/gpt-oss-120b",  # Free model
                messages=[
                    {"role": "system", "content": "You are a professional financial analyst providing expert stock analysis."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=4000
            )
            
            expert_opinion = completion.choices[0].message.content.strip()
            
            return expert_opinion
            
        except Exception as e:
            print(f"Error generating expert opinion: {e}")
            import traceback
            traceback.print_exc()
            return f"Expert Opinion: Unable to generate detailed analysis at this time. Error: {str(e)}"
    
    @staticmethod
    def generate_shark_tank_pitch(company_data: CompanyData) -> str:
        """
        Generate an actual Shark Tank pitch using LLM instead of just returning the prompt
        """
        try:
            from utils.model_config import get_client
            
            # Get the prompt from the existing function
            prompt = StockTools.generate_shark_tank_pitch_prompt(company_data)
            
            # Use the LLM to generate the actual pitch
            client = get_client()
            
            print(f"🤖 Generating Shark Tank pitch using LLM...")
            
            response = client.chat.completions.create(
                model="openai/gpt-oss-120b",  # Free model
                messages=[
                    {"role": "system", "content": "You are a CEO/CFO presenting to Shark Tank investors. Generate a VERY CONCISE pitch (MAXIMUM 3000 characters total). Focus on the most critical points only. Write in first person as the company, speaking directly to the Sharks. Be brief and impactful - every word must count. NO structural elements, numbered points, or section headers."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,  # Slightly creative but consistent
                max_tokens=900,  # Further reduced to generate ~4000-5000 character pitch (including formatting)
                timeout=30.0      # 30 second timeout to prevent hanging
            )
            
            # Extract the generated pitch
            generated_pitch = response.choices[0].message.content.strip()
            
            print(f"✅ Successfully generated Shark Tank pitch ({len(generated_pitch)} characters)")
            
            # Add proper formatting for display
            formatted_pitch = f"""🦈 **SHARK TANK PITCH PRESENTATION**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{generated_pitch}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
            
            return formatted_pitch
            
        except Exception as e:
            print(f"⚠️ Error generating Shark Tank pitch with LLM: {e}")
            print(f"🔄 Falling back to static pitch generation...")
            # Fallback to static pitch if LLM fails
            return StockTools._generate_static_pitch(company_data)

    @staticmethod
    def generate_shark_tank_pitch_prompt(company_data: CompanyData) -> str:
        """
        Generate a compact prompt for the orchestrator agent to create a Shark Tank pitch
        This returns a prompt, not the pitch itself - the agent will generate it
        """
        # Extract key data points only (not the full formatted report)
        # Determine currency and formatting
        is_indian = company_data.symbol.endswith('.NS') or company_data.symbol.endswith('.BO')
        currency_sym = "₹" if is_indian else "$"
        
        def fmt(val):
            if not val: return "N/A"
            if is_indian:
                if val >= 1e7: return f"{currency_sym}{val/1e7:.2f} Cr"
                elif val >= 1e5: return f"{currency_sym}{val/1e5:.2f} L"
                else: return f"{currency_sym}{val:,.0f}"
            else:
                 return f"{currency_sym}{val/1e9:.2f}B"

        # Extract key data points only (not the full formatted report)
        revenue = fmt(company_data.financials.revenue)
        profit = fmt(company_data.financials.net_profit)
        margin = f"{company_data.financials.profit_margin*100:.1f}%" if company_data.financials.profit_margin else "N/A"
        pe = f"{company_data.financials.pe_ratio:.1f}" if company_data.financials.pe_ratio else "N/A"
        price = f"{currency_sym}{company_data.market_data.current_price:.2f}" if company_data.market_data.current_price else "N/A"
        mcap = fmt(company_data.market_data.market_cap)
        
        # Handle competitors properly (they might be dicts or strings)
        competitors = []
        if company_data.market_data.competitors:
            for comp in company_data.market_data.competitors[:4]:
                if isinstance(comp, dict):
                    competitors.append(comp.get('name', str(comp)))
                elif isinstance(comp, str):
                    competitors.append(comp)
                else:
                    competitors.append(str(comp))
        
        competitors_str = ', '.join(competitors) if competitors else 'Various market participants'
        
        # Create a compact prompt for the LLM
        prompt = f"""
You are the CEO/CFO of {company_data.name}. Generate a CONCISE Shark Tank-style investment pitch.

COMPANY DATA:
- Company: {company_data.name}
- Symbol: {company_data.symbol}
- Sector: {company_data.market_data.sector or 'Market'}
- Current Price: {price}
- Market Cap: {mcap}
- Revenue: {revenue}
- Profit: {profit}
- Profit Margin: {margin}
- PE Ratio: {pe}
- Competitors: {competitors_str}

GENERATE A CONCISE SHARK TANK PITCH (MAX 2500 CHARACTERS):

Cover these key points in a flowing narrative:

1. INTRODUCTION (2-3 sentences)
"Hello Sharks! I am CEO of {company_data.name}, and I'm here to pitch our stock as a compelling investment opportunity..."
Brief intro to sector and what makes you exciting.

2. BUSINESS & FINANCIALS (3-4 sentences)
What you do, key numbers (revenue, profit, margins), market position.
"Our business generates {revenue} in revenue with {margin} profit margins..."

3. INVESTMENT CASE (3-4 sentences)
Why invest? Key strengths, competitive advantages, growth potential.
"Here's why you should invest, Sharks..."

4. RISKS & TRANSPARENCY (2-3 sentences)
Be honest about key risks and challenges.
"Let me be transparent about the risks..."

5. CLOSING (2 sentences)
Strong call to action.
"So, Sharks, are you ready to invest in a company that combines stability with growth potential?"

CRITICAL REQUIREMENTS:
- MAXIMUM 2500 characters total
- Write in FIRST PERSON as the company
- Use CONVERSATIONAL NARRATIVE style
- NO numbered points, section titles, or headers in the output
- NO bullet points - just continuous flowing text
- Include the actual numbers from the data
- Be brief, persuasive, and realistic
- Each topic flows naturally into the next

Generate the COMPLETE pitch now as one continuous narrative:
"""
        
        return prompt
    
    @staticmethod
    def _generate_static_pitch(company_data: CompanyData) -> str:
        """Fallback static pitch template if LLM generation fails"""
        # Extract data
        revenue = company_data.financials.revenue
        profit = company_data.financials.net_profit
        pe = company_data.financials.pe_ratio
        debt = company_data.financials.total_debt
        cashflow = company_data.financials.free_cash_flow
        profit_margin = company_data.financials.profit_margin
        operating_margin = company_data.financials.operating_margin
        price = company_data.market_data.current_price
        mcap = company_data.market_data.market_cap
        sector = company_data.market_data.sector
        competitors = []
        for comp in company_data.market_data.competitors[:4]:
            if isinstance(comp, dict):
                competitors.append(comp.get('name', 'Unknown'))
            elif isinstance(comp, str):
                competitors.append(comp)
            else:
                competitors.append(str(comp))
        
        # Format numbers
        # Determine currency and formatting
        is_indian = company_data.symbol.endswith('.NS') or company_data.symbol.endswith('.BO')
        currency_sym = "₹" if is_indian else "$"
        
        def fmt(val):
            if not val: return "N/A"
            if is_indian:
                if val >= 1e7: return f"{currency_sym}{val/1e7:.2f} Cr"
                elif val >= 1e5: return f"{currency_sym}{val/1e5:.2f} L"
                else: return f"{currency_sym}{val:,.0f}"
            else:
                 return f"{currency_sym}{val/1e9:.2f}B"

        # Format numbers
        revenue_b = fmt(revenue)
        profit_b = fmt(profit)
        debt_b = fmt(debt)
        cashflow_b = fmt(cashflow)
        mcap_b = fmt(mcap)
        price_str = f"{currency_sym}{price:.2f}" if price else "N/A"
        pe_str = f"{pe:.2f}" if pe else "N/A"
        margin_str = f"{profit_margin*100:.2f}%" if profit_margin else "N/A"
        
        pitch = f"""🦈 **SHARK TANK PITCH PRESENTATION**

**1. FOUNDER-STYLE INTRODUCTION**

Hello Sharks! I am {company_data.name}, and I'm here today to pitch my stock as a compelling investment opportunity. We operate in the {sector or 'diversified'} sector, and I'm excited to share why we represent a strong addition to your portfolio.

**2. COMPANY SNAPSHOT**

Let me give you a quick overview of who we are. We trade under the ticker symbol {company_data.symbol}, and we're a major player in the {sector or 'market'} industry. Our current market capitalization stands at {mcap_b}, which reflects the confidence investors have placed in our business model and growth trajectory.

**3. BUSINESS OVERVIEW**

Our business is built on a solid foundation. We generate revenue through multiple streams in the {sector or 'market'} sector, serving both domestic and international markets. Our core operations focus on delivering value to our customers while maintaining strong operational efficiency. We've established ourselves as a reliable player in our industry, and we continue to explore growth opportunities in emerging segments.

**4. FINANCIAL PERFORMANCE**

Now, let's talk numbers - because that's what really matters to you, Sharks.

Our revenue stands at {revenue_b}, demonstrating our ability to generate substantial top-line growth. We've managed to convert this into a net profit of {profit_b}, which shows our operational efficiency and cost management capabilities.

Looking at profitability metrics, our profit margin is {margin_str}, which indicates healthy pricing power and operational leverage. We're generating {cashflow_b} in free cash flow, giving us the flexibility to invest in growth, return capital to shareholders, or strengthen our balance sheet.

Our PE ratio of {pe_str} reflects how the market values our earnings potential. We're carrying {debt_b} in total debt, which we manage carefully to maintain financial flexibility while leveraging opportunities for growth.

**5. STOCK INFORMATION & MARKET DATA**

Our shares are currently trading at {price_str}, with a market capitalization of {mcap_b}. This valuation reflects our strong fundamentals and growth prospects. We've seen consistent trading volume, indicating healthy liquidity for investors who want to enter or exit positions.

**6. PRICE PERFORMANCE**

Our stock has demonstrated resilience and growth potential over various time horizons. We've navigated market volatility while maintaining our strategic focus on long-term value creation. Our price performance reflects both our operational execution and the market's recognition of our competitive position.

**7. COMPETITOR LANDSCAPE**

In our industry, we compete with several notable players including {', '.join(competitors) if competitors else 'various market participants'}. What sets us apart is our operational efficiency, market positioning, and strategic approach to growth. While competition is healthy and keeps us sharp, we believe our unique value proposition gives us a sustainable competitive advantage.

**8. SWOT ANALYSIS**

Let me be transparent about our position, Sharks.

Our **strengths** include strong cash generation, established market presence, and operational efficiency. We have a proven business model that has weathered various market conditions.

On the **weaknesses** side, like any company, we face challenges such as market volatility, regulatory considerations, and the need for continuous innovation to stay competitive.

The **opportunities** ahead of us are exciting. We see potential for market expansion, operational improvements, and strategic initiatives that can drive future growth.

As for **threats**, we're mindful of competitive pressures, economic cycles, and industry-specific risks. However, we have strategies in place to mitigate these challenges.

**9. INVESTMENT RATIONALE**

So why should you invest in us, Sharks? Here's the compelling case:

First, we offer strong cash flow generation with {cashflow_b} in free cash flow, providing financial stability and flexibility. Second, our valuation metrics, including a PE ratio of {pe_str}, suggest we're reasonably priced relative to our earnings power. Third, we operate in the {sector or 'market'} sector, which has long-term growth potential. Finally, our profit margin of {margin_str} demonstrates our ability to convert revenue into bottom-line results.

**10. KEY RISKS**

I believe in transparency, so let me address the risks head-on. We face market volatility that can impact our stock price in the short term. Industry-specific challenges require constant adaptation and strategic agility. Our debt level of {debt_b} needs careful management to maintain financial health. Additionally, competitive pressures mean we must continuously innovate and improve to maintain our market position.

**11. FUTURE GROWTH PLAN**

Looking ahead, Sharks, we have a clear roadmap for growth. We're focused on expanding our market presence, improving operational efficiency, and exploring strategic opportunities that align with our core competencies. We're investing in innovation and technology to stay ahead of industry trends. Our goal is to deliver sustainable, long-term value to our shareholders while maintaining financial discipline.

**12. SUMMARY FOR SHARKS**

Sharks, let me bring this all together for you. {company_data.name} represents a solid investment opportunity in the {sector or 'market'} sector. We're generating {revenue_b} in revenue and {profit_b} in profit, with strong cash flow of {cashflow_b}. Our PE ratio of {pe_str} and profit margin of {margin_str} demonstrate our financial strength and operational efficiency.

We're not promising overnight riches, but we are offering a stable, well-managed company with growth potential and financial discipline. Our market cap of {mcap_b} reflects a business that has proven its value, and we're committed to continuing that trajectory.

I'm here today because I believe in our story, our numbers, and our future. We have the fundamentals, the strategy, and the execution capability to deliver returns to investors who believe in our vision.

So, Sharks, are you ready to invest in a company that combines stability with growth potential? I'm ready to answer any questions you have about our operations, strategy, or financial outlook.

**13. VOICE PITCH SCRIPT (Optional)**

**20-Second Intro:**
"Hello Sharks! I'm {company_data.name}, a {sector or 'market'} leader with {mcap_b} market cap. We're generating {revenue_b} in revenue and {profit_b} in profit. Today, I'm here to show you why we're a smart investment."

**20-Second Financial Summary:**
"Our numbers speak for themselves: PE ratio of {pe_str}, profit margin of {margin_str}, and strong cash flow of {cashflow_b}. We're financially stable, operationally efficient, and positioned for growth."

**20-Second Closing Pitch:**
"Sharks, we offer stability, growth potential, and proven execution. Our track record demonstrates our ability to deliver value. I'm confident that investing in us will be a decision you'll be proud of. So, who's ready to join us on this journey?"

**14. Q&A MODE - READY FOR YOUR QUESTIONS**

Sharks, I'm now ready to answer any questions you have. Feel free to ask me about:
• Why should I invest in your company?
• What is your growth rate and future projections?
• Are you undervalued compared to competitors?
• What are your biggest risks and how do you mitigate them?
• Who is your competition and how do you differentiate?
• What's your strategy for the next 3-5 years?

I'm here as your CEO/CFO, ready to provide transparent, data-driven answers to help you make an informed investment decision."""
        return pitch
    
    @staticmethod
    def get_stock_news_analysis(stock_name: str, max_articles: int = 10) -> Dict:
        """
        Tool: Get comprehensive stock news analysis with sentiment
        Uses Tavily search with specific domains, extracts content, and analyzes with LLM
        
        Args:
            stock_name: Name or ticker of the stock
            max_articles: Maximum number of articles to analyze
            
        Returns:
            Dictionary with news analysis and sentiment
        """
        from utils.stock_news_analyzer import analyze_stock_news
        
        print(f"📰 Fetching news analysis for {stock_name}...")
        result = analyze_stock_news(stock_name, max_articles, extract_full_content=True)
        return result