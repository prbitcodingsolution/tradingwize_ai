import requests
from bs4 import BeautifulSoup
import re
import os
import time
from urllib.parse import urljoin, urlparse
import json

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

def search_stock_on_screener(stock_name: str):
    """
    Search for a stock on screener.in and return the company URL
    """
    print(f"🔍 Searching for stock: {stock_name}")
    
    # Try direct company URL first
    direct_url = f"{BASE_URL}/company/{stock_name.upper()}/"
    
    try:
        resp = requests.get(direct_url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            print(f"✅ Found direct URL: {direct_url}")
            return direct_url, stock_name.upper()
    except Exception as e:
        print(f"⚠️ Direct URL failed: {e}")
    
    # Try search API if direct URL fails
    search_url = f"{BASE_URL}/api/company/search/?q={stock_name}"
    
    try:
        resp = requests.get(search_url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data and len(data) > 0:
                # Get the first result
                first_result = data[0]
                company_url = first_result.get('url', '')
                if company_url:
                    full_url = urljoin(BASE_URL, company_url)
                    symbol = company_url.split('/')[-2] if company_url.endswith('/') else company_url.split('/')[-1]
                    print(f"✅ Found via search API: {full_url}")
                    return full_url, symbol
    except Exception as e:
        print(f"⚠️ Search API failed: {e}")
    
    # Fallback: try common variations
    variations = [
        stock_name.upper(),
        stock_name.lower(),
        stock_name.replace(' ', ''),
        stock_name.replace(' ', '-'),
    ]
    
    for variation in variations:
        try:
            test_url = f"{BASE_URL}/company/{variation}/"
            resp = requests.get(test_url, headers=HEADERS, timeout=5)
            if resp.status_code == 200:
                print(f"✅ Found via variation: {test_url}")
                return test_url, variation
        except:
            continue
    
    raise ValueError(f"Stock '{stock_name}' not found on Screener.in")

def find_pdf_links(soup, base_url):
    """
    Find all quarterly PDF links on the page, ordered from newest to oldest
    """
    pdf_links = []
    
    # Look for the quarterly results section specifically
    # Screener.in has a specific structure for quarterly results
    quarters_section = soup.find('section', {'id': 'quarters'})
    
    if quarters_section:
        # Find all PDF links in the quarters section
        for a in quarters_section.find_all("a", href=True):
            href = a["href"]
            
            # Check if it's a quarterly PDF link
            if "/company/source/quarter/" in href or "quarterly" in href.lower():
                full_url = urljoin(base_url, href)
                link_text = a.get_text(strip=True)
                
                # Extract date/quarter info from the link or surrounding context
                # Try to find the quarter column header
                parent_td = a.find_parent('td')
                quarter_info = ""
                
                if parent_td:
                    # Look for the header of this column
                    table = parent_td.find_parent('table')
                    if table:
                        # Find the column index
                        row = parent_td.find_parent('tr')
                        col_index = list(row.find_all('td')).index(parent_td)
                        
                        # Get the header for this column
                        thead = table.find('thead')
                        if thead:
                            header_row = thead.find('tr')
                            if header_row:
                                headers = header_row.find_all('th')
                                if col_index < len(headers):
                                    quarter_info = headers[col_index].get_text(strip=True)
                
                pdf_links.append({
                    "url": full_url,
                    "text": link_text,
                    "quarter": quarter_info,
                    "type": "direct"
                })
    
    # If no quarters section found, use the old method
    if not pdf_links:
        # Common patterns for PDF links on screener.in
        pdf_patterns = [
            r"/company/source/quarter/",
            r"/company/source/annual/",
            r"\.pdf$",
        ]
        
        # Look for direct PDF links
        for a in soup.find_all("a", href=True):
            href = a["href"]
            
            # Check if it's a PDF link
            for pattern in pdf_patterns:
                if re.search(pattern, href, re.IGNORECASE):
                    full_url = urljoin(base_url, href)
                    link_text = a.get_text(strip=True)
                    pdf_links.append({
                        "url": full_url,
                        "text": link_text,
                        "quarter": "",
                        "type": "direct"
                    })
                    break
    
    # Reverse the list so newest PDFs are first
    # (Screener.in typically shows oldest to newest left to right)
    pdf_links = list(reversed(pdf_links))
    
    return pdf_links

def download_pdf_from_url(pdf_url: str, filename: str, max_retries=3):
    """
    Download PDF from URL with retry logic
    """
    for attempt in range(max_retries):
        try:
            print(f"📥 Downloading PDF (attempt {attempt + 1}/{max_retries}): {pdf_url}")
            
            # Add specific headers for PDF download
            pdf_headers = HEADERS.copy()
            pdf_headers["Accept"] = "application/pdf,application/octet-stream,*/*"
            
            resp = requests.get(pdf_url, headers=pdf_headers, timeout=30, stream=True)
            resp.raise_for_status()
            
            # Check if response is actually a PDF
            content_type = resp.headers.get('content-type', '').lower()
            if 'pdf' not in content_type and 'octet-stream' not in content_type:
                # Try to detect PDF by content
                first_bytes = resp.content[:10]
                if not first_bytes.startswith(b'%PDF'):
                    print(f"⚠️ Response doesn't appear to be a PDF. Content-Type: {content_type}")
                    if attempt < max_retries - 1:
                        time.sleep(2)
                        continue
            
            # Save the PDF
            with open(filename, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            # Verify file was created and has content
            if os.path.exists(filename) and os.path.getsize(filename) > 0:
                print(f"✅ PDF downloaded successfully: {filename}")
                return True
            else:
                print(f"❌ Downloaded file is empty or doesn't exist")
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                    
        except Exception as e:
            print(f"❌ Download attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
    
    return False

def download_quarterly_pdf(stock_name: str, save_dir="downloads", num_pdfs=4):
    """
    Enhanced function to download the last N quarterly PDFs from screener.in
    
    Args:
        stock_name: Stock symbol or name
        save_dir: Directory to save the PDF
        num_pdfs: Number of latest PDFs to download (default: 4)
        
    Returns:
        dict: Information about the downloaded PDFs including file paths
    """
    # Create save directory
    os.makedirs(save_dir, exist_ok=True)
    
    try:
        # Step 1: Find the stock on screener.in
        company_url, symbol = search_stock_on_screener(stock_name)
        
        # Step 2: Get the company page
        print(f"📄 Fetching company page: {company_url}")
        resp = requests.get(company_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Step 3: Look for PDF links
        pdf_links = find_pdf_links(soup, company_url)
        
        if not pdf_links:
            # Try the quarters/results page
            quarters_url = company_url.rstrip('/') + '/consolidated/#quarters'
            print(f"📊 Trying quarters page: {quarters_url}")
            
            resp = requests.get(quarters_url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            
            soup = BeautifulSoup(resp.text, "html.parser")
            pdf_links = find_pdf_links(soup, quarters_url)
        
        if not pdf_links:
            raise ValueError(f"No PDF links found for {stock_name}")
        
        print(f"🔗 Found {len(pdf_links)} potential PDF links")
        for i, link in enumerate(pdf_links[:10]):  # Show first 10
            quarter_text = f" [{link['quarter']}]" if link.get('quarter') else ""
            print(f"  {i+1}. {link['text']}{quarter_text} - {link['url']}")
        
        # Step 4: Download the latest N PDFs (they're already ordered newest first)
        links_to_download = pdf_links[:num_pdfs]
        
        downloaded_pdfs = []
        timestamp = int(time.time())
        
        for i, link in enumerate(links_to_download):
            pdf_url = link['url']
            
            # Generate filename
            pdf_filename = os.path.join(save_dir, f"{symbol}_quarterly_{timestamp}_{i+1}.pdf")
            
            # Try to download
            print(f"\n📥 Downloading PDF {i+1}/{len(links_to_download)}...")
            if download_pdf_from_url(pdf_url, pdf_filename):
                downloaded_pdfs.append({
                    "pdf_url": pdf_url,
                    "file_path": os.path.abspath(pdf_filename),
                    "link_text": link['text'],
                    "index": i + 1
                })
                print(f"✅ Successfully downloaded PDF {i+1}")
            else:
                print(f"⚠️ Failed to download PDF {i+1}")
        
        # Return results
        if downloaded_pdfs:
            return {
                "success": True,
                "stock": stock_name,
                "symbol": symbol,
                "company_url": company_url,
                "total_downloaded": len(downloaded_pdfs),
                "pdfs": downloaded_pdfs
            }
        else:
            raise ValueError("Failed to download any PDF files")
        
    except Exception as e:
        print(f"❌ Error downloading PDF for {stock_name}: {e}")
        return {
            "success": False,
            "stock": stock_name,
            "error": str(e),
            "pdfs": []
        }

def download_stock_pdf(stock_name: str, save_dir="downloads", pdf_type="quarterly", num_pdfs=4):
    """
    Simple function to download stock PDFs from screener.in
    
    Args:
        stock_name: Stock symbol (e.g., "CUPID", "RELIANCE")
        save_dir: Directory to save PDF (default: "downloads")
        pdf_type: Type of PDF to download (default: "quarterly")
        num_pdfs: Number of latest PDFs to download (default: 4)
        
    Returns:
        list: List of full paths to downloaded PDF files, or empty list if failed
    """
    try:
        result = download_quarterly_pdf(stock_name, save_dir, num_pdfs)
        
        if result.get("success"):
            pdf_paths = [pdf['file_path'] for pdf in result['pdfs']]
            print(f"\n✅ Successfully downloaded {len(pdf_paths)} PDFs:")
            for i, path in enumerate(pdf_paths, 1):
                print(f"  {i}. {path}")
            return pdf_paths
        else:
            print(f"❌ Failed to download PDFs: {result.get('error')}")
            return []
            
    except Exception as e:
        print(f"❌ Error downloading PDFs for {stock_name}: {e}")
        return []

# Test the function
if __name__ == "__main__":
    print("🧪 Testing PDF download...")
    
    # Test with different stocks
    test_stocks = ["CUPID"]
    
    for stock in test_stocks:
        print(f"\n{'='*50}")
        print(f"Testing: {stock}")
        print('='*50)
        
        # Download the last 4 quarterly PDFs
        pdf_paths = download_stock_pdf("RELIANCE", num_pdfs=4)
        
        if pdf_paths:
            print(f"\n✅ SUCCESS: Downloaded {len(pdf_paths)} PDFs")
            for i, path in enumerate(pdf_paths, 1):
                print(f"  PDF {i}: {path}")
            break
        else:
            print(f"❌ FAILED to download PDFs for {stock}")
    
    print("\n🏁 Testing complete!")
