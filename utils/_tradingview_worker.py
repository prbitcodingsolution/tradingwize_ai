"""
TradingView scraper worker — runs in a subprocess with a clean event loop.
Usage: python _tradingview_worker.py SYMBOL EXCHANGE MAX_IDEAS
Outputs JSON array of ideas to stdout.
"""

import sys
import json


def scrape(symbol: str, exchange: str, max_ideas: int):
    from playwright.sync_api import sync_playwright

    url = f"https://www.tradingview.com/symbols/{exchange}-{symbol}/ideas/"
    ideas = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Wait for article cards to load
            try:
                page.wait_for_selector('article', timeout=15000)
            except Exception:
                try:
                    page.wait_for_selector('[class*="card-"]', timeout=10000)
                except Exception:
                    pass

            # Scroll to trigger lazy-loaded images
            for _ in range(4):
                page.evaluate("window.scrollBy(0, 600)")
                page.wait_for_timeout(800)

            # Scroll back to top to ensure all images are loaded
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(500)

            # Extract ideas from article cards
            ideas = page.evaluate("""() => {
                const results = [];
                const MAX = """ + str(max_ideas) + """;

                // Target article elements (each is one idea card)
                const articles = document.querySelectorAll('article');
                const seen = new Set();

                for (const article of articles) {
                    if (results.length >= MAX) break;

                    // --- IMAGE (CRITICAL) ---
                    // Strategy 1: <picture> > <source srcset="..."> (webp, best quality)
                    // Strategy 2: <picture> > <img src="..."> (png fallback)
                    // Strategy 3: <img> with s3.tradingview.com src
                    let imageUrl = '';

                    const picture = article.querySelector('picture');
                    if (picture) {
                        const source = picture.querySelector('source[srcset]');
                        if (source) {
                            imageUrl = source.getAttribute('srcset') || '';
                        }
                        if (!imageUrl || !imageUrl.includes('tradingview.com')) {
                            const img = picture.querySelector('img');
                            if (img) {
                                imageUrl = img.getAttribute('src') || img.getAttribute('data-src') || '';
                            }
                        }
                    }

                    // Fallback: any img with s3.tradingview.com in src
                    if (!imageUrl || !imageUrl.includes('tradingview.com')) {
                        const imgs = article.querySelectorAll('img');
                        for (const img of imgs) {
                            const src = img.getAttribute('src') || img.getAttribute('data-src') || '';
                            if (src.includes('s3.tradingview.com')) {
                                imageUrl = src;
                                break;
                            }
                        }
                    }

                    // Skip if image is a logo/avatar (typically very small or contains specific paths)
                    if (imageUrl && (imageUrl.includes('/avatars/') || imageUrl.includes('/userpic/'))) {
                        imageUrl = '';
                    }

                    // Ensure absolute URL
                    if (imageUrl && !imageUrl.startsWith('http')) {
                        imageUrl = 'https:' + imageUrl;
                    }

                    // --- TITLE ---
                    const titleEl = article.querySelector(
                        '[class*="title"], h2, h3, h4'
                    );
                    const title = titleEl ? titleEl.textContent.trim() : '';
                    if (!title || title.length < 5 || seen.has(title)) continue;
                    seen.add(title);

                    // --- LINK ---
                    // The main idea link has data-qa-id="ui-lib-card-link-image" or href containing /chart/
                    const linkEl = article.querySelector(
                        'a[data-qa-id="ui-lib-card-link-image"], a[href*="/chart/"]'
                    );
                    let ideaUrl = linkEl ? linkEl.href : '';
                    if (!ideaUrl) {
                        // Fallback: first <a> with a real href
                        const anyLink = article.querySelector('a[href*="tradingview.com"]');
                        ideaUrl = anyLink ? anyLink.href : '';
                    }

                    // --- AUTHOR ---
                    const authorEl = article.querySelector(
                        'a[href*="/u/"], [class*="username"], [class*="author"]'
                    );
                    let author = authorEl ? authorEl.textContent.trim() : '';
                    // Clean "by " prefix
                    author = author.replace(/^by\\s+/i, '');

                    // --- LIKES / BOOSTS ---
                    const likesEl = article.querySelector(
                        '[class*="boost"], [class*="like"], button[class*="count"]'
                    );
                    const likes = likesEl ? likesEl.textContent.trim().replace(/[^0-9]/g, '') || '0' : '0';

                    // --- TIME ---
                    const timeEl = article.querySelector('time');
                    let timePosted = '';
                    if (timeEl) {
                        timePosted = timeEl.getAttribute('datetime') || timeEl.textContent.trim();
                    }

                    // --- DESCRIPTION ---
                    const descEl = article.querySelector(
                        '[class*="paragraph"], [class*="description"], p'
                    );
                    const description = descEl ? descEl.textContent.trim().slice(0, 200) : '';

                    results.push({
                        title: title.slice(0, 120),
                        author: author.slice(0, 50),
                        likes: likes,
                        time_posted: timePosted,
                        description: description,
                        image_url: imageUrl,
                        idea_url: ideaUrl
                    });
                }

                return results;
            }""")

        except Exception as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
        finally:
            browser.close()

    return ideas


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else "TCS"
    exchange = sys.argv[2] if len(sys.argv) > 2 else "NSE"
    max_ideas = int(sys.argv[3]) if len(sys.argv) > 3 else 9

    results = scrape(symbol, exchange, max_ideas)
    print(json.dumps(results))
