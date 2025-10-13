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

BRANCH_TO_STORE = {
    "Warrington": "4157a468-0220-45a4-bd51-e3dffe2ce7f0",
    "Netherton": "604d760c-7742-4861-ae64-344c3a343b07",
    "Wythenshawe": "2124b7c4-5013-424f-ad03-f49b0d2f4efa",
    "Toxteth": "289123c4-d483-4fc1-b36f-8c6534121f0d"
}


@app.post("/launch-playwright-listing")
async def launch_playwright_listing_persistent(data: dict = Body(...)):
    """
    Launch Playwright automation using the persistent Chromium context
    """
    item_name = data.get("item_name", "").strip()
    description = data.get("description", "").strip()
    price = data.get("price", "").strip()
    serial_number = data.get("serial_number", "").strip()
    branch = data.get("branch", "").strip() 

    print(branch)

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

        store_id = BRANCH_TO_STORE.get(branch, "4157a468-0220-45a4-bd51-e3dffe2ce7f0")  # fallback to Warrington
        await page.select_option("#storeId", store_id)
        print(f"[OK] Store set to {branch}", flush=True)

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

        print("[READY] Waiting for user to save product...", flush=True)

        try:
            # Coroutine to detect saving completion
            async def wait_for_save():
                await page.wait_for_selector("text=Saving...", timeout=0)  # appears after click
                await page.wait_for_selector("text=Saving...", state="detached", timeout=0)  # disappears when done
                return "saved"

            # Coroutine to detect user navigating away before saving
            async def wait_for_navigation():
                await page.wait_for_function(
                    """() => !window.location.href.includes('/products/new')""",
                    timeout=0
                )
                return "navigated_away"

            # Create tasks from the coroutines
            save_task = asyncio.create_task(wait_for_save())
            nav_task = asyncio.create_task(wait_for_navigation())

            done, pending = await asyncio.wait(
                [save_task, nav_task],
                return_when=asyncio.FIRST_COMPLETED
            )

            # Cancel whichever coroutine is still running
            for task in pending:
                task.cancel()

            result = list(done)[0].result()
            if result == "saved":
                print("[OK] Product saved successfully", flush=True)
                success = True
                message = "Listing saved successfully."
            else:
                print("[WARN] User navigated away before saving", flush=True)
                success = False
                message = "Listing failed — user navigated away before saving."

        except Exception as e:
            print(f"[ERROR] Issue detecting save or navigation: {e}", flush=True)
            success = False
            message = f"Listing failed — {e}"

        finally:
            await asyncio.sleep(2)
            await page.close()

        if serial_number and success:
            try:
                # Open a new page for NOSPOS
                nospos_page = await playwright_manager.context_instance.new_page()
                await nospos_page.goto("https://nospos.com/stock/search")
                await nospos_page.wait_for_load_state("networkidle")

                # Wait for login if needed
                if "login" in nospos_page.url.lower():
                    print("[INFO] Please log in to NOSPOS manually...")
                    try:
                        await nospos_page.wait_for_url("**/nospos.com/**", timeout=0)
                        print("[OK] NOSPOS login detected, proceeding...")
                    except Exception as e:
                        print(f"[ERROR] Login interrupted: {e}")

                # Handle intermediate landing pages before reaching /stock/search
                print("[INFO] Waiting for intermediate pages to finish...")
                max_checks = 60
                checks = 0
                while checks < max_checks:
                    if nospos_page.is_closed():
                        print("[ERROR] NOSPOS page closed by user during intermediate page wait")
                        break

                    current_url = nospos_page.url.rstrip("/")
                    if current_url == "https://nospos.com":
                        print("[INFO] Redirecting to /stock/search from main landing page...")
                        await nospos_page.goto("https://nospos.com/stock/search")
                        await nospos_page.wait_for_load_state("networkidle")
                        break
                    elif "/stock/search" in current_url:
                        print("[INFO] Already on /stock/search page, ready to proceed")
                        break
                    else:
                        await asyncio.sleep(1)
                        checks += 1
                else:
                    print("[WARN] Timeout waiting for intermediate pages; proceeding anyway")

                # Navigate to search page cleanly
                await nospos_page.goto("https://nospos.com/stock/search")
                await nospos_page.wait_for_load_state("networkidle")
                await asyncio.sleep(1)

                # Fill the barcode and press Enter
                await nospos_page.fill("input#stocksearchandfilter-query", serial_number)
                try:
                    async with nospos_page.expect_navigation(timeout=10000) as nav_info:
                        await nospos_page.press("input#stocksearchandfilter-query", "Enter")
                    await nav_info.value
                    await nospos_page.wait_for_load_state("networkidle")
                    await asyncio.sleep(2)
                except Exception as e:
                    print(f"[WARN] Navigation timeout/error for barcode {serial_number}: {e}")
                    await nospos_page.wait_for_load_state("networkidle")
                    await asyncio.sleep(2)

                # Ensure we are on the edit/item page
                current_url = nospos_page.url
                is_edit_page = False
                if "/stock/" in current_url:
                    try:
                        await asyncio.gather(
                            nospos_page.wait_for_selector("#stock-name", timeout=5000),
                            nospos_page.wait_for_selector(".detail-view", timeout=5000)
                        )
                        is_edit_page = True
                    except Exception:
                        is_edit_page = False

                if is_edit_page:
                    print(f"[OK] NOSPOS item page opened for barcode {serial_number}")
                    # Tick the "Externally Listed" checkbox
                    try:
                        checkbox_selector = "input#stock-externally_listed_at"
                        checkbox = await nospos_page.query_selector(checkbox_selector)
                        if checkbox:
                            await nospos_page.click("label[for='stock-externally_listed_at']")
                            print("[OK] 'Externally Listed' checkbox clicked via label")

                            # Click the Save button
                            save_button_selector = "button.btn.btn-blue[type='submit']"
                            await nospos_page.click(save_button_selector)
                            print("[OK] Save button clicked")
                            
                            # Optional: wait until navigation or confirmation
                            await nospos_page.wait_for_load_state("networkidle")
                            await asyncio.sleep(1)

                        else:
                            print("[WARN] Could not find 'Externally Listed' checkbox")
                    except Exception as e:
                        print(f"[ERROR] Checking 'Externally Listed': {e}")

                    # Close the NOSPOS page after ticking
                    await asyncio.sleep(1)  # optional short delay
                    await nospos_page.close()
                    print("[INFO] NOSPOS page closed after ticking checkbox")

                else:
                    print(f"[WARN] Unexpected page after search. URL: {nospos_page.url}")

            except Exception as e:
                print(f"[ERROR] Opening NOSPOS item: {e}")

        return {"success": success, "message": message}

    except Exception as e:  # outer except - ✓ correct indentation
        # handle main automation errors
        return {"success": False, "message": str(e)}

