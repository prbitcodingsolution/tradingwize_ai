"""
Symbol Resolver
Maps common stock names/symbols to correct NSE format
"""

import logging

logger = logging.getLogger(__name__)

# Symbol mapping dictionary
SYMBOL_MAP = {
    # Jio variants
    'JIO': 'JIOFIN.NS',
    'JIOFIN': 'JIOFIN.NS',
    'JIO.NS': 'JIOFIN.NS',
    'JIOFINANCIAL': 'JIOFIN.NS',
    
    # Reliance variants
    'RELIANCE': 'RELIANCE.NS',
    'RIL': 'RELIANCE.NS',
    
    # TCS variants
    'TCS': 'TCS.NS',
    'TATA CONSULTANCY': 'TCS.NS',
    
    # ONGC variants
    'ONGC': 'ONGC.NS',
    
    # Tata Steel variants
    'TATASTEEL': 'TATASTEEL.NS',
    'TATA STEEL': 'TATASTEEL.NS',
    
    # Infosys variants
    'INFY': 'INFY.NS',
    'INFOSYS': 'INFY.NS',
    
    # HDFC variants
    'HDFC': 'HDFCBANK.NS',
    'HDFCBANK': 'HDFCBANK.NS',
    'HDFC BANK': 'HDFCBANK.NS',
    
    # ICICI variants
    'ICICI': 'ICICIBANK.NS',
    'ICICIBANK': 'ICICIBANK.NS',
    'ICICI BANK': 'ICICIBANK.NS',
    
    # SBI variants
    'SBI': 'SBIN.NS',
    'SBIN': 'SBIN.NS',
    'STATE BANK': 'SBIN.NS',
    
    # Adani variants
    'ADANI': 'ADANIENT.NS',
    'ADANIENT': 'ADANIENT.NS',
    'ADANI ENTERPRISES': 'ADANIENT.NS',
    
    # Bajaj variants
    'BAJAJ AUTO': 'BAJAJ-AUTO.NS',
    'BAJAJAUTO': 'BAJAJ-AUTO.NS',
    'BAJAJ-AUTO': 'BAJAJ-AUTO.NS',
    
    # Bharti Airtel variants
    'AIRTEL': 'BHARTIARTL.NS',
    'BHARTI': 'BHARTIARTL.NS',
    'BHARTIARTL': 'BHARTIARTL.NS',
    
    # ITC variants
    'ITC': 'ITC.NS',
    
    # Wipro variants
    'WIPRO': 'WIPRO.NS',
    
    # HCL variants
    'HCL': 'HCLTECH.NS',
    'HCLTECH': 'HCLTECH.NS',
    'HCL TECH': 'HCLTECH.NS',
    
    # Maruti variants
    'MARUTI': 'MARUTI.NS',
    'MARUTI SUZUKI': 'MARUTI.NS',
    
    # Asian Paints variants
    'ASIAN PAINTS': 'ASIANPAINT.NS',
    'ASIANPAINT': 'ASIANPAINT.NS',
    
    # Titan variants
    'TITAN': 'TITAN.NS',
    
    # Nestle variants
    'NESTLE': 'NESTLEIND.NS',
    'NESTLEIND': 'NESTLEIND.NS',
    'NESTLE INDIA': 'NESTLEIND.NS',
    
    # Hindustan Unilever variants
    'HUL': 'HINDUNILVR.NS',
    'HINDUNILVR': 'HINDUNILVR.NS',
    'HINDUSTAN UNILEVER': 'HINDUNILVR.NS',
    
    # Coal India variants
    'COAL INDIA': 'COALINDIA.NS',
    'COALINDIA': 'COALINDIA.NS',
    
    # NTPC variants
    'NTPC': 'NTPC.NS',
    
    # Power Grid variants
    'POWERGRID': 'POWERGRID.NS',
    'POWER GRID': 'POWERGRID.NS',
    
    # Sun Pharma variants
    'SUNPHARMA': 'SUNPHARMA.NS',
    'SUN PHARMA': 'SUNPHARMA.NS',
    
    # Dr Reddy variants
    'DRREDDY': 'DRREDDY.NS',
    'DR REDDY': 'DRREDDY.NS',
    
    # Cipla variants
    'CIPLA': 'CIPLA.NS',
    
    # Axis Bank variants
    'AXIS': 'AXISBANK.NS',
    'AXISBANK': 'AXISBANK.NS',
    'AXIS BANK': 'AXISBANK.NS',
    
    # Kotak Bank variants
    'KOTAK': 'KOTAKBANK.NS',
    'KOTAKBANK': 'KOTAKBANK.NS',
    'KOTAK BANK': 'KOTAKBANK.NS',
    
    # Bajaj Finance variants
    'BAJAJFINSV': 'BAJAJFINSV.NS',
    'BAJAJ FINANCE': 'BAJFINANCE.NS',
    'BAJFINANCE': 'BAJFINANCE.NS',
    
    # Tech Mahindra variants
    'TECHM': 'TECHM.NS',
    'TECH MAHINDRA': 'TECHM.NS',
    
    # Mahindra variants
    'M&M': 'M&M.NS',
    'MAHINDRA': 'M&M.NS',
    
    # Larsen & Toubro variants
    'LT': 'LT.NS',
    'L&T': 'LT.NS',
    'LARSEN': 'LT.NS',
    
    # UltraTech variants
    'ULTRACEMCO': 'ULTRACEMCO.NS',
    'ULTRATECH': 'ULTRACEMCO.NS',
    
    # Grasim variants
    'GRASIM': 'GRASIM.NS',
    
    # JSW Steel variants
    'JSWSTEEL': 'JSWSTEEL.NS',
    'JSW STEEL': 'JSWSTEEL.NS',
    
    # Tata Motors variants
    'TATAMOTORS': 'TATAMOTORS.NS',
    'TATA MOTORS': 'TATAMOTORS.NS',
    
    # Eicher Motors variants
    'EICHERMOT': 'EICHERMOT.NS',
    'EICHER': 'EICHERMOT.NS',
    
    # Hero MotoCorp variants
    'HEROMOTOCO': 'HEROMOTOCO.NS',
    'HERO': 'HEROMOTOCO.NS',
    'HERO MOTOCORP': 'HEROMOTOCO.NS',
    
    # Britannia variants
    'BRITANNIA': 'BRITANNIA.NS',
    
    # Dabur variants
    'DABUR': 'DABUR.NS',
    
    # Godrej variants
    'GODREJCP': 'GODREJCP.NS',
    'GODREJ': 'GODREJCP.NS',
    
    # Trent variants
    'TRENT': 'TRENT.NS',
    
    # Avenue Supermarts (DMart) variants
    'DMART': 'DMART.NS',
    'AVENUE SUPERMARTS': 'DMART.NS',
}


def resolve_symbol(symbol: str) -> str:
    """
    Resolve a symbol to its correct NSE format
    
    Args:
        symbol: Input symbol (can be short name, full name, or NSE format)
    
    Returns:
        str: Resolved NSE symbol (e.g., "JIOFIN.NS")
    
    Examples:
        >>> resolve_symbol("JIO")
        "JIOFIN.NS"
        >>> resolve_symbol("RELIANCE")
        "RELIANCE.NS"
        >>> resolve_symbol("TCS.NS")
        "TCS.NS"
    """
    if not symbol:
        return symbol
    
    # Normalize input
    symbol_upper = symbol.upper().strip()
    
    # Check if already in correct format (ends with .NS)
    if symbol_upper.endswith('.NS'):
        # Check if it needs mapping (e.g., JIO.NS -> JIOFIN.NS)
        if symbol_upper in SYMBOL_MAP:
            resolved = SYMBOL_MAP[symbol_upper]
            logger.info(f"Resolved {symbol} -> {resolved}")
            return resolved
        return symbol_upper
    
    # Check direct mapping
    if symbol_upper in SYMBOL_MAP:
        resolved = SYMBOL_MAP[symbol_upper]
        logger.info(f"Resolved {symbol} -> {resolved}")
        return resolved
    
    # Try adding .NS suffix
    with_ns = f"{symbol_upper}.NS"
    if with_ns in SYMBOL_MAP:
        resolved = SYMBOL_MAP[with_ns]
        logger.info(f"Resolved {symbol} -> {resolved}")
        return resolved
    
    # No mapping found - assume it's already correct or add .NS
    if not symbol_upper.endswith('.NS'):
        resolved = f"{symbol_upper}.NS"
        logger.info(f"No mapping found, using: {symbol} -> {resolved}")
        return resolved
    
    logger.info(f"Using symbol as-is: {symbol}")
    return symbol_upper


def add_symbol_mapping(short_name: str, nse_symbol: str):
    """
    Add a new symbol mapping dynamically
    
    Args:
        short_name: Short name or variant (e.g., "JIO")
        nse_symbol: Correct NSE symbol (e.g., "JIOFIN.NS")
    """
    SYMBOL_MAP[short_name.upper()] = nse_symbol.upper()
    logger.info(f"Added mapping: {short_name} -> {nse_symbol}")


def get_all_mappings():
    """Get all symbol mappings"""
    return SYMBOL_MAP.copy()


def search_symbol(query: str, limit: int = 10):
    """
    Search for symbols matching a query
    
    Args:
        query: Search query
        limit: Maximum results to return
    
    Returns:
        list: List of (short_name, nse_symbol) tuples
    """
    query_upper = query.upper()
    results = []
    
    for short_name, nse_symbol in SYMBOL_MAP.items():
        if query_upper in short_name or query_upper in nse_symbol:
            results.append((short_name, nse_symbol))
            if len(results) >= limit:
                break
    
    return results


# CLI testing
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        symbol = sys.argv[1]
        resolved = resolve_symbol(symbol)
        print(f"\nInput:    {symbol}")
        print(f"Resolved: {resolved}\n")
    else:
        print("\nSymbol Resolver - Test Cases:")
        print("=" * 50)
        
        test_cases = [
            "JIO",
            "JIOFIN",
            "JIO.NS",
            "RELIANCE",
            "TCS",
            "ONGC.NS",
            "HDFC",
            "SBI",
            "INVALID_SYMBOL"
        ]
        
        for symbol in test_cases:
            resolved = resolve_symbol(symbol)
            print(f"{symbol:20} -> {resolved}")
        
        print("\n" + "=" * 50)
        print(f"Total mappings: {len(SYMBOL_MAP)}")
        
        # Search example
        print("\nSearch for 'TATA':")
        results = search_symbol("TATA")
        for short, nse in results:
            print(f"  {short:20} -> {nse}")
