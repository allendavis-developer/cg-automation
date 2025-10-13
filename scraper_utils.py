# scraper_utils.py
import statistics
import sys, os, asyncio

import playwright_manager

IS_HEADLESS = False

SCRAPER_CONFIGS = {
    "CashConverters": {
        "base_url": "https://www.cashconverters.co.uk",
        "url": (
            "https://www.cashconverters.co.uk/search-results?"
            "Sort=price&page=1"
            "&f%5Bcategory%5D%5B0%5D=all&f%5Blocations%5D%5B0%5D=all"
            "&query={query}"
        ),
        "price_class": ".product-item__price",
        "url_selector": ".product-item__title, .product-item__image a",
        "title_class": ".product-item__title__description",
        "shop_class": ".product-item__title__location",
        "detail_selectors": {
            "description_class": ".product-details__description",
        }
    },

    "CashGenerator": {
        "base_url": "https://cashgenerator.co.uk",
        "url": (
            "https://cashgenerator.co.uk/pages/search-results-page?"
            "q={query}&tab=products&sort_by=price&sort_order=asc&page=1"
        ),
        "url_selector": ".snize-view-link",
        "price_class": ".snize-price.money",
        "title_class": ".snize-title",
        "shop_class": ".snize-attribute",
        "detail_selectors": {
            "description_class": ".condition-box",
        }
    },

    "CEX": {
        "base_url": "https://uk.webuy.com",
        "url": "https://uk.webuy.com/search?stext={query}&Grade=B",
        "price_class": ".product-main-price",
        "title_class": ".card-title",
        "url_selector": ".card-title a",
        "detail_selectors": {
            "description_class": ".item-description",
            "title_class": ".vendor-name"
        }
    },

    "eBay": {
        "base_url": "https://ebay.co.uk",
        "url": ("https://www.ebay.co.uk/sch/i.html?"
            "_nkw={query}&_sacat=0&_from=R40"
            "&LH_ItemCondition=3000&LH_PrefLoc=1"
            "&LH_Sold=1&LH_Complete=1"),
        "price_class": ".s-card__price, .su-styled-text.primary.bold.large-1.s-card__price",
        "title_class": ".s-card__title",
        "url_selector": ".su-card-container__content > a",
    }
}


async def setup_page_optimization(page):
    """
    Optimize page loading by blocking unnecessary resources
    """
    # Block images, stylesheets, fonts, and other non-essential resources
    await page.route("**/*", lambda route: (
        route.abort() if route.request.resource_type in ["image", "stylesheet", "font", "media"]
        else route.continue_()
    ))

    # Set a custom user agent to avoid bot detection
    await page.set_extra_http_headers({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })


def parse_query_string(query_string):
    """
    Parse a specially formatted query string like:
    "Model: iPhone 15 Pro Max, Storage: 256GB, Color: Black"

    Returns:
        model (str): The model string
        filters (dict): Dictionary of filters {key: value}
        search_string (str): Combined search string for the query
    """
    # Check if this is a structured query (contains "Model:")
    if "Model:" not in query_string:
        # Not structured, treat as regular search string
        return query_string, {}, query_string

    # Parse structured format
    parts = [p.strip() for p in query_string.split(',')]

    model = None
    filters = {}

    for part in parts:
        if ':' in part:
            key, value = part.split(':', 1)
            key = key.strip()
            value = value.strip()

            if key.lower() == 'model':
                model = value
            else:
                filters[key] = value

    # Build search string from model + filter values
    if model:
        search_parts = [model]
        search_parts.extend(filters.values())
        search_string = ', '.join(search_parts)
    else:
        search_string = query_string

    return model or query_string, filters, search_string


async def generic_scraper(
        url: str,
        competitor: str,
        model: str,
        price_class: str,
        title_class: str,
        shop_class: str = None,
        exclude=None,
        filter_listings=None,
        summarise_prices=None,
        browser_context=None
):
    """
    Generic scraper for competitor websites.
    Returns (prices, titles, store_names, urls, summary).
    """
    page = await browser_context.new_page()
    await setup_page_optimization(page)

    try:
        print("Attempting to go to ", url)
        await page.goto(url, wait_until='domcontentloaded')
        await page.wait_for_selector(price_class, timeout=15000)
    except Exception as e:
        print(f"Warning: prices not found for {competitor} within timeout: {e}")

    prices, titles, store_names, urls = [], [], [], []

    # --- Determine element selectors from config ---
    config = SCRAPER_CONFIGS.get(competitor, {})
    base_url = config.get("base_url", "")
    url_selector = config.get("url_selector")
    shop_class = shop_class or config.get("shop_class")

    # --- Special case: CashConverters requires per-card scraping ---
    if competitor == "CashConverters":
        product_cards = await page.query_selector_all(".product-item-wrapper")
        print(f"Found {len(product_cards)} product cards for CashConverters")

        for card in product_cards:
            try:
                # Title
                title_node = await card.query_selector(title_class)
                title = (await title_node.inner_text()).strip() if title_node else None

                # Price
                price_node = await card.query_selector(price_class)
                price_text = (await price_node.inner_text()).strip() if price_node else None
                price = parse_price(price_text) if price_text else None

                # Store
                store_node = await card.query_selector(shop_class) if shop_class else None
                store = (await store_node.inner_text()).strip() if store_node else None

                # URL
                url_node = await card.query_selector("a")
                href = await url_node.get_attribute("href") if url_node else None
                if href and href.startswith("/"):
                    href = base_url.rstrip("/") + href

                if title and price:
                    titles.append(title)
                    prices.append(price)
                    store_names.append(store)
                    urls.append(href)

            except Exception as e:
                print(f"⚠️ Error parsing CashConverters card: {e}")
                continue

    else:
        # --- Default generic scraping ---
        titles = await page.eval_on_selector_all(
            title_class,
            "els => els.map(e => e.innerText.trim())"
        )

        prices_text = await page.eval_on_selector_all(
            price_class,
            "els => els.map(e => e.innerText.trim())"
        )
        prices = [parse_price(p) for p in prices_text if parse_price(p) is not None]

        title_elements = await page.query_selector_all(title_class)

        # Store names extraction
        store_names = []
        if shop_class:
            for t_elem in title_elements:
                try:
                    # First, try direct child
                    shop_elem = await t_elem.query_selector(shop_class)
                    store_text = (await shop_elem.inner_text()).strip() if shop_elem else None

                    # If nothing, look in the parent container
                    if not store_text:
                        store_text = await t_elem.evaluate(f'''
                            (el, sel) => {{
                                let container = el.closest('.snize-overhidden, .product-item-wrapper, .card, article');
                                if (!container) container = el.parentElement;
                                const shop = container ? container.querySelector(sel) : null;
                                return shop ? shop.innerText.replace(/\\s+/g, ' ').trim() : null;
                            }}
                        ''', shop_class)

                    # Final clean-up: remove empty spans or whitespace
                    if store_text:
                        store_text = store_text.replace('\n', ' ').strip()
                except Exception:
                    store_text = None
                store_names.append(store_text)
        else:
            store_names = [None] * len(titles)

        # URL extraction
        urls = []
        if url_selector:
            for t_elem in title_elements:
                href = await t_elem.get_attribute('href')
                if not href:
                    a = await t_elem.query_selector('a')
                    href = await a.get_attribute('href') if a else None
                if not href:
                    try:
                        href = await t_elem.evaluate(
                            '(el, sel) => { const q = el.querySelector(sel); if (q) return q.getAttribute("href"); const c = el.closest(sel); return c ? c.getAttribute("href") : null }',
                            url_selector
                        )
                    except Exception:
                        href = None

                # Handle relative URLs
                if href and href.startswith("/") and base_url:
                    href = base_url.rstrip("/") + href
                elif href and not href.startswith("http") and base_url:
                    href = base_url.rstrip("/") + '/' + href

                urls.append(href)

            while len(urls) < len(titles):
                urls.append(None)
        else:
            urls = [None] * len(titles)

    # --- Filtering ---
    if filter_listings:
        filtered_prices, filtered_titles, filtered_stores, filtered_urls = [], [], [], []
        for price, title, store, u in zip(prices, titles, store_names, urls):
            title_lower = title.lower()
            if model.lower() in title_lower:
                if not exclude or not any(term.lower() in title_lower for term in exclude):
                    filtered_prices.append(price)
                    filtered_titles.append(title)
                    filtered_stores.append(store)
                    filtered_urls.append(u)
        prices, titles, store_names, urls = filtered_prices, filtered_titles, filtered_stores, filtered_urls

    # --- Summary ---
    summary = summarise_prices(prices) if summarise_prices else {
        "Low": min(prices) if prices else None,
        "Mid": statistics.median(prices) if prices else None,
        "High": max(prices) if prices else None,
    }

    try:
        await page.close()
    except Exception:
        pass

    return prices, titles, store_names, urls, summary


async def ebay_scraper(
        url: str,
        search_string: str,
        exclude=None,
        filter_listings=None,
        summarise_prices=None,
        browser_context=None
):
    """
    Robust eBay scraper targeting the modern SRP layout (li.s-card under #srp-river-results > ul).
    Hard-coded selectors are used, but function tolerates missing elements in each card.
    Returns: prices, titles, urls, summary
    """
    page = await browser_context.new_page()
    await setup_page_optimization(page)

    # Parse structured query (keeps your existing behavior)
    model, filters, _ = parse_query_string(search_string)

    # Navigate
    await page.goto(url, wait_until='domcontentloaded')

    # Wait for the SRP list or fallback
    try:
        await page.wait_for_selector('#srp-river-results > ul', timeout=10000)
    except Exception:
        # fallback: continue even if the main container isn't found quickly
        print("Warning: '#srp-river-results > ul' not found within timeout, trying fallbacks")

    # Try main selector first, then fallbacks
    li_elements = []
    try:
        li_elements = await page.query_selector_all('#srp-river-results > ul > li')
    except Exception:
        li_elements = []

    if not li_elements:
        # fallback selectors that commonly appear on SRP pages
        li_elements = await page.query_selector_all('li.s-card, li.s-item, #srp-river-results ul li')


    prices, titles, urls = [], [], []

    for card in li_elements:
        try:
            # Evaluate a single JS snippet in the context of the card element.
            # This avoids individual eval_on_selector calls that raise when absent.
            data = await card.evaluate(
                """(el) => {
                    const pickNode = (sels) => {
                        for (const s of sels) {
                            const n = el.querySelector(s);
                            if (n) return n;
                        }
                        return null;
                    };

                    // URL: prefer the content/title anchor, fall back to image anchor or first anchor
                    const a = pickNode([
                        '.su-card-container__content a.su-link',
                        '.su-card-container__content a',
                        'a.su-link',
                        'a.image-treatment',
                        'a.s-card__link',
                        'a'
                    ]);
                    const href = a && a.href ? a.href : null;

                    // Title: various places the title might live
                    const titleNode = el.querySelector('.s-card__title .su-styled-text.primary')
                        || el.querySelector('.s-card__title')
                        || el.querySelector('[role=\"heading\"]')
                        || el.querySelector('.s-item__title')
                        || el.querySelector('.s-card__title span');
                    let title = titleNode ? titleNode.innerText.trim() : null;
                    if (title) {
                        // remove "New listing" noise
                        title = title.replace(/^New listing\\s*/i, '').trim();
                    }

                    // Price: common price selectors
                    const priceNode = pickNode([
                        '.s-card__price',
                        '.s-item__price',
                        '.notranslate',
                        '.s-card__price .su-styled-text.positive',
                        '.s-card__price span'
                    ]);
                    const price_text = priceNode ? priceNode.innerText.trim() : null;

                    // Seller (optional)
                    const sellerNode = pickNode([
                        '.su-card-container__attributes__secondary .su-styled-text.primary',
                        '.s-item__seller-info',
                        '.s-item__seller'
                    ]);
                    const seller = sellerNode ? sellerNode.innerText.trim() : null;

                    // Sold / caption (optional)
                    const soldNode = el.querySelector('.s-card__caption span') || el.querySelector('.s-item__sold-date');
                    const sold = soldNode ? soldNode.innerText.trim() : null;

                    return { href, title, price_text, seller, sold };
                }"""
            )

            # data is a dict-like object
            title = data.get('title') if isinstance(data, dict) else None
            price_text = data.get('price_text') if isinstance(data, dict) else None
            href = data.get('href') if isinstance(data, dict) else None

            # basic sanity checks
            if not title:
                # skip listings with no usable title
                continue
            if not price_text:
                # skip if no price text found
                continue

            main_price = parse_price(price_text) if price_text else None
            if main_price is None:
                # cannot parse price
                continue

            prices.append(main_price)
            titles.append(title)
            urls.append(href)

        except Exception as e:
            # log and continue with next card
            print(f"Error processing eBay card: {e}")
            continue

    # close page
    try:
        await page.close()
    except Exception:
        pass

    # Optional filtering by model/exclude (keeps your existing behavior)
    if filter_listings:
        filtered_prices, filtered_titles, filtered_urls = [], [], []
        model_lower = model.lower()
        for price, title, u in zip(prices, titles, urls):
            title_lower = title.lower()
            if model_lower in title_lower:
                if not exclude or not any(term.lower() in title_lower for term in exclude):
                    filtered_prices.append(price)
                    filtered_titles.append(title)
                    filtered_urls.append(u)
        prices, titles, urls = filtered_prices, filtered_titles, filtered_urls

    # Summary
    summary = summarise_prices(prices) if summarise_prices else {
        "Low": min(prices) if prices else None,
        "Mid": statistics.median(prices) if prices else None,
        "High": max(prices) if prices else None,
    }

    return prices, titles, urls, summary


async def _scrape_competitor(browser_context, competitor, search_string, exclude, filter_listings, summarise_prices):
    config = SCRAPER_CONFIGS[competitor]
    # Parse the query string to extract model and filters
    model, filters, combined_search_string = parse_query_string(search_string)

    # URL encoding for spaces
    query_str = combined_search_string.replace(" ", "+" if competitor in ["CEX", "eBay"] else "%20")
    url = config["url"].format(query=query_str, storage="")  # storage ignored for now

    if competitor == "eBay":
        prices, titles, urls, summary = await ebay_scraper(
            url=url,
            search_string=search_string,
            exclude=exclude,
            filter_listings=filter_listings,
            summarise_prices=summarise_prices,
            browser_context=browser_context,   # <-- pass browser down
        )
        store_names = [None] * len(titles)
    else:
        prices, titles, store_names, urls, summary = await generic_scraper(
            url=url,
            competitor=competitor,
            model=search_string,
            price_class=config["price_class"],
            title_class=config["title_class"],
            shop_class=config.get("shop_class"),
            exclude=exclude,
            filter_listings=filter_listings,
            summarise_prices=summarise_prices,
            browser_context=browser_context,   # <-- pass browser down
        )

    return competitor, prices, titles, store_names, urls, summary


async def save_prices(competitors, search_string, exclude=None, filter_fn=None, summarise_fn=None):
    """
    Run scraping for one or more competitors in parallel using a shared browser context.
    Returns a flat list of listings.
    """
    # always access the current value from the module
    context = playwright_manager.context_instance
    if not context:
        raise RuntimeError("No active Playwright context.")

    if isinstance(competitors, str):
        competitors = [competitors]

    async def run_all():
        tasks = [
            _scrape_competitor(context, comp, search_string, exclude, filter_fn, summarise_fn)
            for comp in competitors
        ]
        results = await asyncio.gather(*tasks)
        return results

    results = await run_all()

    all_listings = []
    for competitor, prices, titles, store_names, urls, summary in results:
        for price, title, store, url in zip(prices, titles, store_names, urls):
            all_listings.append({
                "competitor": competitor,
                "title": title,
                "price": price,
                "store": store,
                "url": url,
                "summary": summary
            })

    return all_listings

def parse_price(text):
    """
    Parse price text to extract numeric value
    Handles various formats like '£188.95', '£188.95 to £219.95', etc.
    """
    try:
        # Handle price ranges by taking the first price
        if ' to ' in text:
            text = text.split(' to ')[0]

        # Remove currency symbols and clean up
        cleaned = text.replace("£", "").replace(",", "").replace("(", "").replace(")", "").strip()

        # Extract just the numeric part (handles cases like "£188.95/Unit")
        import re
        match = re.search(r'\d+\.?\d*', cleaned)
        if match:
            return float(match.group())

        return None
    except:
        return None


def filter_listings(prices, titles, search_string="", exclude=None):
    if exclude is None:
        exclude = []
    if isinstance(exclude, str):
        exclude = [exclude]
    filtered_prices = []
    filtered_titles = []
    for price, title in zip(prices, titles):
        title_lower = title.lower()
        if search_string.lower() in title_lower:
            if not any(term.lower() in title_lower for term in exclude):
                filtered_prices.append(price)
                filtered_titles.append(title)
    return filtered_prices


def summarise_prices(prices):
    if not prices:
        return {"Low": None, "Mid": None, "High": None}
    low = min(prices)
    mid = statistics.median(prices)
    high = max(prices)
    return {"Low": low, "Mid": mid, "High": high}


async def extract_prices_and_titles(page, price_class=".product-item__price",
                                    title_class=".product-item__title__description"):
    price_elements = await page.query_selector_all(price_class)
    prices_text = [await e.inner_text() for e in price_elements]
    prices = [parse_price(p) for p in prices_text if parse_price(p) is not None]

    title_elements = await page.query_selector_all(title_class)
    titles = [await e.inner_text() for e in title_elements]

    return prices, titles