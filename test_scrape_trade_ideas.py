"""
Test script for scrape_trade_ideas with LINKUSD (Chainlink crypto).
"""

from utils.tradingview_ideas_scraper import scrape_trade_ideas, scrape_tradingview_minds
import json

if __name__ == "__main__":
    print("Testing scrape_trade_ideas for XAUUSD (crypto)...\n")

    result = scrape_trade_ideas(symbol="XAUUSD", exchange="", max_ideas=5)

    print("\n--- Result ---")
    print(json.dumps(result, indent=2, default=str))

    print(f"\nURL: {result['url']}")
    print(f"Ideas found: {result['count']}")
    print(f"Error: {result['error']}")

    if result["ideas"]:
        print("\n--- First Idea ---")
        print(json.dumps(result["ideas"][0], indent=2, default=str))

    # --- Test scrape_tradingview_minds ---
    print("\n" + "=" * 60)
    print("Testing scrape_tradingview_minds for XAUUSD (crypto)...\n")

    minds_result = scrape_tradingview_minds(symbol="XAUUSD", exchange="", max_minds=5)

    print("\n--- Minds Result ---")
    print(json.dumps(minds_result, indent=2, default=str))

    print(f"\nURL: {minds_result['url']}")
    print(f"Minds found: {minds_result['count']}")
    print(f"Error: {minds_result['error']}")

    if minds_result["minds"]:
        print("\n--- First Mind ---")
        print(json.dumps(minds_result["minds"][0], indent=2, default=str))
