"""
Dynamic Stock Symbol Resolver
Automatically finds ticker symbols for company names using Tavily search
No static mappings - fully dynamic
"""

import os
import re
import time
import yfinance as yf
from typing import Optional, Dict, List
from dotenv import load_dotenv
import requests

load_dotenv()
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")


class StockSymbolResolver:
    """
    Resolves company names to ticker symbols using Tavily search and yfinance validation
    """
    
    def __init__(self):
        self.cache = {}  # Cache resolved symbols
        
    def _search_with_tavily(self, query: str) -> tuple:
        """
        Search using Tavily API
        
        Returns:
            (results_list, answer_string)
        """
        try:
            url = "https://api.tavily.com/search"
            headers = {"Content-Type": "application/json; charset=utf-8"}
            payload = {
                "api_key": TAVILY_API_KEY,
                "query": query,
                "search_depth": "advanced",
                "max_results": 5,
                "include_answer": True,
                "include_domains": ["nseindia.com", "bseindia.com", "screener.in", "moneycontrol.com"]
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                results = data.get('results', [])
                answer = data.get('answer', '')
                return results, answer
            else:
                return [], ''
                
        except Exception as e:
            print(f"Tavily search error: {e}")
            return [], ''
    
    def _extract_symbols_from_text(self, text: str) -> List[str]:
        """
        Extract potential ticker symbols from text
        
        Args:
            text: Text to search for symbols
            
        Returns:
            List of potential symbols
        """
        symbols = []
        
        # Pattern 1: Explicit ticker mentions like "ticker: RELIANCE" or "symbol: TCS.NS"
        ticker_patterns = [
            r'ticker\s*(?:symbol)?[:\s]+([A-Z]{2,15}(?:\.[A-Z]{2,3})?)',
            r'symbol[:\s]+([A-Z]{2,15}(?:\.[A-Z]{2,3})?)',
            r'NSE[:\s]+([A-Z]{2,15})',
            r'BSE[:\s]+([A-Z]{2,15})',
        ]
        
        for pattern in ticker_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            symbols.extend(matches)
        
        # Pattern 2: Exchange-qualified symbols (e.g., "RELIANCE.NS", "TCS.BO")
        qualified_symbols = re.findall(r'\b([A-Z]{2,15}\.[A-Z]{2,3})\b', text)
        symbols.extend(qualified_symbols)
        
        # Pattern 3: Symbols in URLs (e.g., /quote/RELIANCE.NS)
        url_symbols = re.findall(r'/(?:quote|symbol|company|stock)/([A-Z0-9\-]+(?:\.[A-Z]{2,3})?)', text)
        symbols.extend(url_symbols)
        
        return symbols
    
    def _validate_symbol(self, symbol: str) -> Optional[str]:
        """
        Validate if a symbol is valid using yfinance
        
        Args:
            symbol: Symbol to validate
            
        Returns:
            Valid symbol or None
        """
        try:
            # Ensure symbol has exchange suffix
            if '.' not in symbol:
                # Try NSE first, then BSE
                for suffix in ['.NS', '.BO']:
                    test_symbol = f"{symbol}{suffix}"
                    ticker = yf.Ticker(test_symbol)
                    info = ticker.info
                    
                    if info and 'symbol' in info and info.get('longName'):
                        return test_symbol
            else:
                # Symbol already has suffix
                ticker = yf.Ticker(symbol)
                info = ticker.info
                
                if info and 'symbol' in info and info.get('longName'):
                    return symbol
            
            return None
            
        except Exception as e:
            return None
    
    def resolve_company_name(self, company_name: str) -> Dict:
        """
        Resolve a company name to its ticker symbol
        
        Args:
            company_name: Company name (e.g., "Reliance Industries")
            
        Returns:
            Dictionary with resolution result
        """
        # Check cache first
        cache_key = company_name.upper().strip()
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        print(f"🔍 Searching for: {company_name}")
        
        # Build search queries
        search_queries = [
            f"{company_name} NSE ticker symbol India stock",
            f"{company_name} BSE stock symbol screener.in",
            f'"{company_name}" stock ticker NSE BSE India',
        ]
        
        all_potential_symbols = []
        
        # Search with Tavily
        for query in search_queries:
            results, answer = self._search_with_tavily(query)
            
            # Extract symbols from answer
            if answer:
                symbols = self._extract_symbols_from_text(answer)
                all_potential_symbols.extend(symbols)
            
            # Extract symbols from search results
            for result in results:
                title = result.get('title', '')
                content = result.get('content', '')
                url = result.get('url', '')
                
                combined_text = f"{title} {content} {url}"
                symbols = self._extract_symbols_from_text(combined_text)
                all_potential_symbols.extend(symbols)
            
            # If we found symbols, no need to continue searching
            if all_potential_symbols:
                break
            
            time.sleep(0.5)  # Small delay between searches
        
        # Remove duplicates while preserving order
        unique_symbols = list(dict.fromkeys(all_potential_symbols))
        
        # Validate each symbol
        for symbol in unique_symbols:
            validated = self._validate_symbol(symbol)
            if validated:
                # Get company name from yfinance
                try:
                    ticker = yf.Ticker(validated)
                    info = ticker.info
                    verified_name = info.get('longName') or info.get('shortName') or company_name
                    
                    result = {
                        'success': True,
                        'original_name': company_name,
                        'symbol': validated,
                        'verified_name': verified_name,
                        'exchange': 'NSE' if '.NS' in validated else 'BSE'
                    }
                    
                    # Cache the result
                    self.cache[cache_key] = result
                    
                    print(f"✅ Found: {validated} ({verified_name})")
                    return result
                    
                except Exception as e:
                    continue
        
        # No valid symbol found
        result = {
            'success': False,
            'original_name': company_name,
            'symbol': None,
            'error': 'Could not find valid ticker symbol'
        }
        
        self.cache[cache_key] = result
        print(f"❌ Not found: {company_name}")
        
        return result
    
    def resolve_file(self, input_file: str, output_file: str = None) -> Dict:
        """
        Resolve all company names in a file to ticker symbols
        
        Args:
            input_file: Path to file with company names (one per line)
            output_file: Path to output file (optional)
            
        Returns:
            Dictionary with resolution statistics
        """
        if output_file is None:
            output_file = input_file.replace('.txt', '_resolved.txt')
        
        print(f"\n{'='*60}")
        print(f"STOCK SYMBOL RESOLVER")
        print(f"{'='*60}")
        print(f"📖 Reading from: {input_file}")
        print(f"💾 Writing to: {output_file}\n")
        
        # Read company names
        with open(input_file, 'r', encoding='utf-8') as f:
            company_names = [line.strip() for line in f if line.strip()]
        
        print(f"Found {len(company_names)} company names")
        print(f"Starting resolution...\n")
        
        resolved_symbols = []
        failed_names = []
        results_detail = []
        
        for i, name in enumerate(company_names, 1):
            print(f"[{i}/{len(company_names)}] ", end="")
            
            result = self.resolve_company_name(name)
            results_detail.append(result)
            
            if result['success']:
                resolved_symbols.append(result['symbol'])
            else:
                failed_names.append(name)
            
            # Small delay to avoid rate limiting
            if i % 5 == 0:
                time.sleep(1)
        
        # Remove duplicates
        original_count = len(resolved_symbols)
        resolved_symbols = list(dict.fromkeys(resolved_symbols))
        duplicates_removed = original_count - len(resolved_symbols)
        
        # Write output file
        with open(output_file, 'w', encoding='utf-8') as f:
            for symbol in resolved_symbols:
                f.write(f"{symbol}\n")
        
        # Print summary
        print(f"\n{'='*60}")
        print(f"RESOLUTION SUMMARY")
        print(f"{'='*60}")
        print(f"Total names: {len(company_names)}")
        print(f"Resolved: {len(resolved_symbols)}")
        print(f"Failed: {len(failed_names)}")
        print(f"Duplicates removed: {duplicates_removed}")
        print(f"Success rate: {(len(resolved_symbols)/len(company_names)*100):.1f}%")
        print(f"\nOutput saved to: {output_file}")
        
        if failed_names:
            print(f"\n❌ Failed to resolve {len(failed_names)} names:")
            for name in failed_names[:10]:
                print(f"  - {name}")
            if len(failed_names) > 10:
                print(f"  ... and {len(failed_names)-10} more")
        
        print(f"{'='*60}\n")
        
        return {
            'total': len(company_names),
            'resolved': len(resolved_symbols),
            'failed': len(failed_names),
            'duplicates_removed': duplicates_removed,
            'success_rate': (len(resolved_symbols)/len(company_names)*100),
            'failed_names': failed_names,
            'resolved_symbols': resolved_symbols,
            'results_detail': results_detail,
            'output_file': output_file
        }
    
    def resolve_list(self, company_names: List[str]) -> Dict:
        """
        Resolve a list of company names to ticker symbols
        
        Args:
            company_names: List of company names
            
        Returns:
            Dictionary with resolution results
        """
        print(f"\n🔍 Resolving {len(company_names)} company names...\n")
        
        resolved_symbols = []
        failed_names = []
        results_detail = []
        
        for i, name in enumerate(company_names, 1):
            print(f"[{i}/{len(company_names)}] ", end="")
            
            result = self.resolve_company_name(name)
            results_detail.append(result)
            
            if result['success']:
                resolved_symbols.append(result['symbol'])
            else:
                failed_names.append(name)
            
            # Small delay
            if i % 5 == 0:
                time.sleep(1)
        
        # Remove duplicates
        resolved_symbols = list(dict.fromkeys(resolved_symbols))
        
        return {
            'total': len(company_names),
            'resolved': len(resolved_symbols),
            'failed': len(failed_names),
            'success_rate': (len(resolved_symbols)/len(company_names)*100) if company_names else 0,
            'failed_names': failed_names,
            'resolved_symbols': resolved_symbols,
            'results_detail': results_detail
        }


def main():
    """Main function for command-line usage"""
    import sys
    
    if len(sys.argv) > 1:
        # File mode
        input_file = sys.argv[1]
        output_file = sys.argv[2] if len(sys.argv) > 2 else None
        
        resolver = StockSymbolResolver()
        resolver.resolve_file(input_file, output_file)
    else:
        # Interactive mode
        print("="*60)
        print("STOCK SYMBOL RESOLVER - Interactive Mode")
        print("="*60)
        print("\nEnter company names (one per line)")
        print("Press Enter twice when done\n")
        
        names = []
        while True:
            line = input("> ").strip()
            if not line:
                if names:
                    break
                else:
                    continue
            names.append(line)
        
        resolver = StockSymbolResolver()
        results = resolver.resolve_list(names)
        
        print(f"\n✅ Resolved {results['resolved']}/{results['total']} names")
        print(f"Success rate: {results['success_rate']:.1f}%")
        
        if results['resolved_symbols']:
            print("\n📊 Resolved Symbols:")
            for symbol in results['resolved_symbols']:
                print(f"  {symbol}")
        
        # Save option
        if results['resolved_symbols']:
            save = input("\nSave to file? (y/n): ").lower()
            if save == 'y':
                filename = input("Filename (default: resolved_symbols.txt): ").strip()
                if not filename:
                    filename = "resolved_symbols.txt"
                
                with open(filename, 'w') as f:
                    for symbol in results['resolved_symbols']:
                        f.write(f"{symbol}\n")
                
                print(f"💾 Saved to {filename}")


if __name__ == "__main__":
    main()
