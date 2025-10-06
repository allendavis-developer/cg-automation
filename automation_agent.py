from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
import asyncio
from scraper_utils import save_prices
from scrape_nospos import scrape_barcodes

import os, sys

app = FastAPI(title="CashGen Automation Agent")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(BASE_DIR, "python", "local-browsers")

sys.path.append(os.path.abspath(os.path.join(BASE_DIR, ".."))) 

# Allow the Render domain and local frontend JS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://cashgensuite.onrender.com",
        "http://127.0.0.1:8000",  # if you have a local frontend
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/scrape-prices")
def scrape_prices(data: dict = Body(...)):
    query = data.get("query")
    competitors = data.get("competitors", ["CEX", "eBay"])
    if not query:
        return {"success": False, "error": "Missing query"}

    try:
        listings = save_prices(competitors, query)
        return {
            "success": True,
            "results": listings,
            "competitor_count": len(listings)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/scrape-barcodes")
async def scrape_barcodes_endpoint(data: dict = Body(...)):
    barcodes = data.get("barcodes", [])
    if not barcodes:
        return {"success": False, "error": "No barcodes provided"}

    try:
        results = await scrape_barcodes(barcodes)

        # Ensure the result shape matches frontend expectations
        return {
            "success": True,
            "products": results,  # frontend looks for `products`
            "count": len(results)
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
    

# TODO: Maybe put these two in a different file like the other endpoints?
from pathlib import Path
from playwright.async_api import async_playwright

USER_DATA_DIR = Path(__file__).parent / "playwright_user_data"


@app.post("/bulk-scrape-competitors")
def bulk_scrape_competitors(data: dict = Body(...)):
    """
    Scrape competitor listings for multiple items.
    Returns a list of results with success flags per item.
    """
    items = data.get("items", [])
    if not items:
        return {"success": False, "error": "No items provided"}

    results = []
    for item in items:
        query = item.get("name") or item.get("market_item") or ""
        if not query.strip():
            results.append({
                "barcode": item.get("barcode"),
                "success": False,
                "error": "Missing name or market_item"
            })
            continue

        try:
            # TODO: This function NEEDS to be renamed so BADLY
            listings = save_prices(["CEX", "CashGenerator"], query)
            results.append({
                "barcode": item.get("barcode"),
                "success": True,
                "competitor_data": listings,
                "competitor_count": len(listings),
                "query_used": query,
            })
        except Exception as e:
            results.append({
                "barcode": item.get("barcode"),
                "success": False,
                "error": str(e)
            })

    return {"success": True, "results": results}



@app.post("/launch-playwright-listing")
async def launch_playwright_listing_local(data: dict = Body(...)):
    """
    Launch the Playwright automation locally to create a new product listing
    """
    item_name = data.get("item_name", "").strip()
    description = data.get("description", "").strip()
    price = data.get("price", "").strip()
    serial_number = data.get("serial_number", "").strip()

    if not all([item_name, description, price]):
        return {"success": False, "error": "Missing required fields"}

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch_persistent_context(
                user_data_dir=str(USER_DATA_DIR),
                headless=False,
                slow_mo=500
            )
            page = await browser.new_page()
            await page.set_extra_http_headers({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                              'AppleWebKit/537.36 (KHTML, like Gecko) '
                              'Chrome/120.0.0.0 Safari/537.36'
            })

            print(f"🚀 Starting WebEpos automation for item: {item_name}", flush=True)

            await page.goto("https://webepos.cashgenerator.co.uk")
            await page.wait_for_load_state("networkidle")
            print("[OK] Logged in or existing session detected!", flush=True)

            await page.goto("https://webepos.cashgenerator.co.uk/products/new")
            await page.wait_for_load_state("networkidle")

            await page.wait_for_selector("#normal-switch")
            await page.evaluate("""
            () => {
                const handle = document.querySelector('#normal-switch');
                const bg = handle.parentElement.querySelector('.react-switch-bg');
                const checkIcon = bg.children[0];
                const crossIcon = bg.children[1];
                if (handle.getAttribute('aria-checked') === 'true') {
                    handle.setAttribute('aria-checked', 'false');
                    handle.style.transform = 'translateX(0px)';
                    bg.style.background = '#ccc';
                    checkIcon.style.opacity = '0';
                    crossIcon.style.opacity = '1';
                }
            }
            """)

            await page.fill("#title", item_name)
            await page.select_option("#storeId", "4157a468-0220-45a4-bd51-e3dffe2ce7f0")
            await page.fill('textarea[name="intro"]', description)

            if price.replace('.', '', 1).isdigit():
                await page.fill("#price", price)
            else:
                print(f"[WARN] Invalid price value: {price}", flush=True)

            if serial_number:
                await page.fill("#barcode", serial_number)
                print("[OK] Barcode entered.", flush=True)

            await page.select_option("#fulfilmentOption", "anyfulfilment")
            await page.select_option("#condition", "used")
            await page.wait_for_selector("#grade", state="visible")
            await page.select_option("#grade", "B")

            await page.wait_for_selector("button:has-text('Save Product')")
            await asyncio.sleep(3)
            await page.click("button:has-text('Save Product')", force=True)

            print("[OK] Clicked Save Product button.", flush=True)

            print("[INFO] Browser open — close manually to finish.", flush=True)
            await browser.wait_for_event("close")

        return {"success": True, "message": "Listing automation completed successfully"}

    except Exception as e:
        print(f"[ERROR] {e}", flush=True)
        return {"success": False, "error": str(e)}