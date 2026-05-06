"""
TradingView scraper worker — runs in a subprocess with a clean event loop.
Usage: python _tradingview_worker.py SYMBOL EXCHANGE MAX_IDEAS
  EXCHANGE can be "" (empty) for forex/crypto symbols like XAUUSD, BTCUSD.
Outputs JSON array of ideas to stdout.
"""

import sys
import json


def _dismiss_overlays(page) -> None:
    """Dismiss TradingView's cookie banner / region popup / login dialog
    if any of them are blocking the article list. Silently ignore misses
    — we only need to succeed once, and if none are present the scrape
    proceeds normally.
    """
    # Pre-seed the cookie TradingView looks at so the consent banner
    # doesn't render at all. Safer than trying to click a Shadow-DOM
    # button after the page has already attached event listeners.
    try:
        page.context.add_cookies([
            {
                "name": "cookies_policy",
                "value": "accepted",
                "domain": ".tradingview.com",
                "path": "/",
            }
        ])
    except Exception:
        pass

    # Try the visible consent / close buttons in order. Each selector is
    # wrapped in its own try/except so one miss doesn't kill the chain.
    _selectors = [
        'button[aria-label*="Accept" i]',
        'button:has-text("Accept all")',
        'button:has-text("I accept")',
        'button:has-text("Got it")',
        'button[aria-label*="close" i]',
        '[class*="closeButton"]',
    ]
    for sel in _selectors:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click(timeout=2000)
                page.wait_for_timeout(400)
        except Exception:
            pass


def scrape(symbol: str, exchange: str, max_ideas: int):
    from playwright.sync_api import sync_playwright

    # Stocks: /symbols/NSE-TCS/ideas/  |  Forex/Crypto: /symbols/XAUUSD/ideas/
    tv_path = f"{exchange}-{symbol}" if exchange else symbol
    url = f"https://www.tradingview.com/symbols/{tv_path}/ideas/"
    ideas = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            extra_http_headers={
                "Accept-Language": "en-IN,en;q=0.9",
            },
        )
        page = context.new_page()

        try:
            # `networkidle` lets TradingView's client-side render finish
            # (its article list is React-hydrated). `domcontentloaded`
            # fired too early and frequently yielded an empty article
            # list on slower CI-like boxes.
            try:
                page.goto(url, wait_until="networkidle", timeout=45000)
            except Exception:
                # Fall back to domcontentloaded — some CDNs keep long-
                # poll connections open forever, never hitting idle.
                page.goto(url, wait_until="domcontentloaded", timeout=30000)

            _dismiss_overlays(page)

            # Wait for article cards to load. Longer timeout than before
            # (25s vs 15s) because the bg-thread path was hitting timeouts.
            _saw_articles = False
            for _attempt in range(2):
                try:
                    page.wait_for_selector('article', timeout=25000)
                    _saw_articles = True
                    break
                except Exception:
                    # No articles yet — nudge the page (scroll, dismiss
                    # overlays again) and retry once.
                    print(
                        f"worker: article selector missed on attempt "
                        f"{_attempt + 1}, retrying after nudge",
                        file=sys.stderr,
                    )
                    _dismiss_overlays(page)
                    page.evaluate("window.scrollBy(0, 600)")
                    page.wait_for_timeout(1500)

            if not _saw_articles:
                # Last-ditch: broader selector. If even this misses, the
                # scroll+extract step will just return [] and we'll surface
                # the miss to the caller.
                try:
                    page.wait_for_selector('[class*="card-"]', timeout=10000)
                except Exception:
                    print(
                        "worker: no article/card selector ever matched — "
                        "page likely region-blocked or rate-limited",
                        file=sys.stderr,
                    )

            # Scroll to trigger lazy-loaded images AND to pull more idea
            # cards into the DOM. The wrapper now asks for ~3x the user's
            # requested count so it can sort by time, so we need enough
            # scrolling to reveal that many cards (≈300px per card).
            for _ in range(8):
                page.evaluate("window.scrollBy(0, 800)")
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
            # Before closing, if we got nothing, dump a short diagnostic
            # to stderr: DOM size + whether any <article> elements ever
            # appeared + whether a consent / region-block banner is on
            # screen. This is what shows up in the Streamlit console
            # when the bg task reports "No ideas found" so the operator
            # can see WHY the page didn't render cards.
            try:
                if not ideas:
                    diag = page.evaluate("""() => ({
                        articles: document.querySelectorAll('article').length,
                        cards: document.querySelectorAll('[class*="card-"]').length,
                        bodyLen: (document.body && document.body.innerText || '').length,
                        title: document.title,
                        url: location.href,
                        hasConsent: !!document.querySelector(
                            '[class*="consent"], [class*="cookie"], [id*="consent"]'
                        ),
                    })""")
                    print(
                        "worker: empty scrape diagnostics -> "
                        + json.dumps(diag),
                        file=sys.stderr,
                    )
            except Exception:
                pass
            browser.close()

    return ideas


def scrape_minds(symbol: str, exchange: str, max_minds: int):
    """Scrape minds/insights from TradingView — only those with chart images."""
    from playwright.sync_api import sync_playwright

    tv_path = f"{exchange}-{symbol}" if exchange else symbol
    url = f"https://www.tradingview.com/symbols/{tv_path}/minds/"
    minds = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Wait for mind posts to load
            try:
                page.wait_for_selector('[class*="mind"], [class*="post"], article', timeout=15000)
            except Exception:
                pass

            # Adaptive scroll: keep scrolling to the bottom until either
            # (a) we have at least 2x the requested number of cards in
            #     the DOM (enough buffer for the Python-side recency
            #     filter to find fresh minds), or
            # (b) the page height stops growing for two consecutive
            #     scrolls (we hit the end of the list), or
            # (c) we hit the hard cap of 25 scroll attempts (~25 seconds)
            #     so we never hang.
            #
            # A fixed-iteration scroll loop was the old approach — it
            # only revealed ~10-15 cards which wasn't enough to survive
            # the last-30-days filter for stocks with a mix of recent
            # and old community posts.
            target_cards = max(max_minds * 2, 30)
            prev_height = 0
            stable_streak = 0
            for _ in range(25):
                cards_now = page.evaluate("document.querySelectorAll('article').length")
                if cards_now >= target_cards:
                    break
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(900)
                new_height = page.evaluate("document.body.scrollHeight")
                if new_height == prev_height:
                    stable_streak += 1
                    if stable_streak >= 2:
                        break
                else:
                    stable_streak = 0
                prev_height = new_height

            # Scroll back to top so <picture> elements near the top
            # re-enter the viewport and finish resolving their srcset
            # URLs before we harvest them.
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(600)

            minds = page.evaluate("""() => {
                const results = [];
                const MAX = """ + str(max_minds) + """;

                // Minds are rendered as individual post cards/articles
                // Try multiple selectors to find mind post containers
                let posts = document.querySelectorAll('article');
                if (posts.length === 0) {
                    posts = document.querySelectorAll('[class*="mind"], [class*="post-"], [class*="card"]');
                }

                for (const post of posts) {
                    if (results.length >= MAX) break;

                    // --- IMAGE (REQUIRED — skip posts without chart images) ---
                    let imageUrl = '';

                    // Strategy 1: <picture> with <source> (webp)
                    const picture = post.querySelector('picture');
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

                    // Strategy 2: img with tradingview.com src (chart snapshots)
                    if (!imageUrl || !imageUrl.includes('tradingview.com')) {
                        const imgs = post.querySelectorAll('img');
                        for (const img of imgs) {
                            const src = img.getAttribute('src') || img.getAttribute('data-src') || '';
                            if (src.includes('s3.tradingview.com') || src.includes('tradingview.com/x/')) {
                                imageUrl = src;
                                break;
                            }
                        }
                    }

                    // Skip avatars/logos
                    if (imageUrl && (imageUrl.includes('/avatars/') || imageUrl.includes('/userpic/'))) {
                        imageUrl = '';
                    }

                    // SKIP posts without chart images — this is the key filter
                    if (!imageUrl) continue;

                    // Ensure absolute URL
                    if (!imageUrl.startsWith('http')) {
                        imageUrl = 'https:' + imageUrl;
                    }

                    // --- AUTHOR ---
                    const authorEl = post.querySelector(
                        'a[href*="/u/"], [class*="username"], [class*="author"]'
                    );
                    let author = authorEl ? authorEl.textContent.trim() : '';
                    author = author.replace(/^by\\s+/i, '');

                    // --- TEXT CONTENT ---
                    // Minds have short text content (not full articles)
                    const textEls = post.querySelectorAll(
                        '[class*="content"], [class*="text"], [class*="paragraph"], [class*="body"], p, span'
                    );
                    let content = '';
                    for (const el of textEls) {
                        const txt = el.textContent.trim();
                        // Skip very short text (likely UI elements) and author names
                        if (txt.length > 10 && txt !== author && !txt.match(/^\\d+$/)) {
                            content = txt.slice(0, 500);
                            break;
                        }
                    }

                    // --- TIME ---
                    const timeEl = post.querySelector('time');
                    let timePosted = '';
                    if (timeEl) {
                        timePosted = timeEl.getAttribute('datetime') || timeEl.textContent.trim();
                    }

                    // --- LIKES / BOOSTS ---
                    const likesEl = post.querySelector(
                        '[class*="boost"], [class*="like"], button[class*="count"]'
                    );
                    const likes = likesEl ? likesEl.textContent.trim().replace(/[^0-9]/g, '') || '0' : '0';

                    // --- COMMENTS COUNT ---
                    const commentsEl = post.querySelector(
                        '[class*="comment"], [class*="reply"]'
                    );
                    const comments = commentsEl ? commentsEl.textContent.trim().replace(/[^0-9]/g, '') || '0' : '0';

                    // --- LINK to the mind post ---
                    const linkEl = post.querySelector('a[href*="tradingview.com"]');
                    const mindUrl = linkEl ? linkEl.href : '';

                    results.push({
                        author: author.slice(0, 50),
                        content: content,
                        time_posted: timePosted,
                        likes: likes,
                        comments: comments,
                        image_url: imageUrl,
                        mind_url: mindUrl
                    });
                }

                return results;
            }""")

        except Exception as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
        finally:
            browser.close()

    return minds


if __name__ == "__main__":
    # Usage:
    #   python _tradingview_worker.py SYMBOL EXCHANGE MAX [ideas|minds]
    symbol = sys.argv[1] if len(sys.argv) > 1 else "TCS"
    exchange = sys.argv[2] if len(sys.argv) > 2 else "NSE"
    max_items = int(sys.argv[3]) if len(sys.argv) > 3 else 9
    mode = sys.argv[4] if len(sys.argv) > 4 else "ideas"

    if mode == "minds":
        results = scrape_minds(symbol, exchange, max_items)
    else:
        results = scrape(symbol, exchange, max_items)
    print(json.dumps(results))
