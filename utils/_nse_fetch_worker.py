"""
Standalone worker script for fetching NSE option chain data via Playwright.

This script is invoked as a subprocess by option_chain_analyzer.py to avoid
asyncio event loop conflicts with Streamlit on Windows + Python 3.14.

Usage:
    python -m utils._nse_fetch_worker <SYMBOL> <is_index:0|1>

Output:
    Prints JSON to stdout on success, or error message prefixed with "ERROR:" on failure.
"""

import sys
import json


def fetch(nse_sym: str, is_index: bool) -> dict:
    from playwright.sync_api import sync_playwright

    NSE_BASE = "https://www.nseindia.com"
    oc_data = {}

    def handle_response(response):
        url = response.url
        if "option-chain" in url and "/api/" in url and response.status == 200:
            try:
                body = response.json()
                if body and body.get("records", {}).get("data"):
                    if nse_sym in url or not oc_data.get("data"):
                        oc_data["data"] = body
            except Exception:
                pass

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--window-position=-2400,-2400",
                "--window-size=1,1",
            ],
        )
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()
        page.add_init_script(
            'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
        )
        page.on("response", handle_response)

        # Step 1: Load NSE option chain page (solves Akamai JS challenge)
        try:
            page.goto(
                f"{NSE_BASE}/option-chain",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            page.wait_for_timeout(5000)
        except Exception:
            pass

        # Step 2: Navigate to target symbol
        if is_index:
            if nse_sym != "NIFTY" or not oc_data.get("data"):
                oc_data.clear()
                try:
                    page.select_option("#equity_optionchain_select", nse_sym)
                    page.wait_for_timeout(6000)
                except Exception:
                    pass
        else:
            # For equities: click "Equity Stock" tab, then select symbol
            oc_data.clear()
            try:
                page.click("#equityChain")
                page.wait_for_timeout(2000)
                page.select_option("#select_symbol", nse_sym)
                page.wait_for_timeout(6000)
            except Exception:
                pass

        browser.close()

    return oc_data.get("data", {})


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("ERROR:Usage: python -m utils._nse_fetch_worker SYMBOL is_index", flush=True)
        sys.exit(1)

    symbol = sys.argv[1]
    is_idx = sys.argv[2] == "1"

    try:
        data = fetch(symbol, is_idx)
        print(json.dumps(data), flush=True)
    except Exception as e:
        print(f"ERROR:{e}", flush=True)
        sys.exit(1)
