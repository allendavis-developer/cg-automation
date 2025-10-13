from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
import asyncio
from scraper_utils import save_prices
from scrape_nospos import scrape_barcodes

import os, sys
import playwright_manager
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

from playwright_manager import connect_chromium, shutdown_chromium

@app.on_event("startup")
async def startup_event():
    print("🔗 Connecting to running Chromium instance...", flush=True)
    await connect_chromium()


@app.on_event("shutdown")
async def shutdown_event():
    print("Closing Playwright Chromium instance...", flush=True)
    await shutdown_chromium()


@app.post("/scrape-prices")
async def scrape_prices(data: dict = Body(...)):
    query = data.get("query")
    competitors = data.get("competitors", ["CEX", "eBay"])
    if not query:
        return {"success": False, "error": "Missing query"}

    try:
        listings = await save_prices(competitors, query)
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
        print("DEBUG: results=", results)  # check that specifications are included

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

USER_DATA_DIR = Path(__file__).parent / "playwright_user_data"


@app.post("/launch-playwright-listing")
async def launch_playwright_listing_persistent(data: dict = Body(...)):
    """
    Launch Playwright automation using the persistent Chromium context
    """
    item_name = data.get("item_name", "").strip()
    description = data.get("description", "").strip()
    price = data.get("price", "").strip()
    serial_number = data.get("serial_number", "").strip()

    if not all([item_name, description, price]):
        print("Missing required fields")
        return {"success": False, "error": "Missing required fields"}

    if not playwright_manager.context_instance:
        print("Persistent browser context not initialized")
        return {"success": False, "error": "Persistent browser context not initialized"}

    try:
        # Reuse persistent context
        page = await playwright_manager.context_instance.new_page()
        await page.set_extra_http_headers({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/120.0.0.0 Safari/537.36'
        })

        print(f"🚀 Starting WebEpos automation for item: {item_name}", flush=True)

        await page.goto("https://webepos.cashgenerator.co.uk")
        await page.wait_for_load_state("networkidle")

        if "login" in page.url.lower():
            print("[INFO] User not logged in — waiting for manual login...", flush=True)
            await page.wait_for_function(
                """() => !window.location.href.includes('/login')""",
                timeout=0
            )
            print("[OK] Login detected — proceeding to product page...", flush=True)
            await asyncio.sleep(2)

        await page.goto("https://webepos.cashgenerator.co.uk/products/new")
        await page.wait_for_load_state("networkidle")

        # Normal switch toggle
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

        # Fill product details
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
        print("[READY] Waiting for user to finish — page will close after navigation away from 'New Product' page.",
              flush=True)
        try:
            # Wait until the user navigates away from the 'new product' URL
            await page.wait_for_function(
                """() => !window.location.href.includes('/products/new')""",
                timeout=0  # wait indefinitely until user leaves the page
            )
            print("[OK] Detected navigation away from product creation page.", flush=True)
        except Exception as e:
            print(f"[WARN] Timeout or navigation issue: {e}", flush=True)

        await asyncio.sleep(2)
        await page.close()

        return {"success": True, "message": "User navigated away — automation finished successfully."}

    except Exception as e:
        print(f"[ERROR] {e}", flush=True)
        try:
            await page.screenshot(path="debug_listing_error.png")
        except:
            pass
        return {"success": False, "error": str(e)}
