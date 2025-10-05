# automation/scrape_nospos.py
import argparse
import asyncio
import sys
import random
from pathlib import Path
from playwright.async_api import async_playwright

USER_DATA_DIR = Path(__file__).parent / "playwright_user_data"

async def scrape_barcodes(barcodes):
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            headless=False,
            user_data_dir=str(USER_DATA_DIR),
        )
        page = await browser.new_page()

        try:
            await page.goto("https://nospos.com/stock/search")
            await page.wait_for_load_state("networkidle")

            # Step 2: Wait for login if needed
            if "login" in page.url:
                print("[INFO] Please log in manually...")
                try:
                    await page.wait_for_url("**/nospos.com/**", timeout=0)  # Wait until login finishes
                except Exception as e:
                    print(f"[ERROR] Page was closed during login: {e}")
                    await browser.close()
                    sys.exit(1)

            # Step 3: Wait until we reach the main landing page (or /stock/search)
            print("[INFO] Waiting for intermediate pages to finish...")
            try:
                max_checks = 60  # Maximum 60 seconds of waiting
                checks = 0
                
                while checks < max_checks:
                    # Check if page is still available
                    if page.is_closed():
                        print("[ERROR] Page was closed by user during intermediate page wait")
                        await browser.close()
                        sys.exit(1)
                        
                    current_url = page.url.rstrip("/")
                    # If we reach the main landing page
                    if current_url == "https://nospos.com":
                        print("[INFO] Intermediate page done, redirecting to /stock/search...")
                        await page.goto("https://nospos.com/stock/search")
                        await page.wait_for_load_state("networkidle")
                        break
                    # If we somehow are already on /stock/search
                    elif "/stock/search" in current_url:
                        print("[INFO] Already on /stock/search, ready to start scraping")
                        break
                    else:
                        # Still on some intermediate page; wait a bit and check again
                        await asyncio.sleep(1)
                        checks += 1
                else:
                    print("[ERROR] Timeout waiting for intermediate pages to finish")
                    await browser.close()
                    sys.exit(1)
                    
            except Exception as e:
                print(f"[ERROR] Page was closed or became unavailable: {e}")
                await browser.close()
                sys.exit(1)

            print(f"[INFO] Processing {len(barcodes)} barcodes: {barcodes}")

            for i, barcode in enumerate(barcodes):
                # Check if page is still available before each operation
                if page.is_closed():
                    print("[ERROR] Page was closed by user during scraping")
                    await browser.close()
                    sys.exit(1)
                    
                search_code = barcode[-4:] if len(barcode) > 4 else barcode
                print(f"[INFO] [{i + 1}/{len(barcodes)}] Searching for barcode: {barcode} -> using {search_code}")

                # Navigate to search page first (ensure clean state)
                await page.goto("https://nospos.com/stock/search")
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(1)

                # Fill the barcode in search input
                await page.fill("input#stocksearchandfilter-query", search_code)

                try:
                    async with page.expect_navigation(timeout=10000) as navigation_info:
                        await page.press("input#stocksearchandfilter-query", "Enter")

                    response = await navigation_info.value
                    await page.wait_for_load_state("networkidle")
                    await asyncio.sleep(2)

                except Exception as e:
                    print(f"[DEBUG] Navigation timeout/error for {barcode}: {e}")
                    await page.wait_for_load_state("networkidle")
                    await asyncio.sleep(2)

                # ✅ SAFER: Check URL first, then conditionally check for elements
                current_url = page.url
                print(f"[DEBUG] Current URL after search: {current_url}")

                is_edit_page = False
                if "/stock/" in current_url and "/edit" in current_url:
                    is_edit_page = True
                elif "/stock/" in current_url:
                    try:
                        await page.wait_for_selector("#stock-name, .detail-view", timeout=3000)
                        is_edit_page = True
                    except Exception:
                        is_edit_page = False

                if is_edit_page:
                    print(f"[INFO] Found edit page for {barcode}")

                    try:
                        # Wait for both main selectors in parallel
                        await asyncio.gather(
                            page.wait_for_selector("#stock-name", timeout=5000),
                            page.wait_for_selector(".detail-view", timeout=5000),
                        )

                        # Extract values in parallel
                        name, description, cost_price, retail_price = await asyncio.gather(
                            get_input_value(page, '#stock-name'),
                            get_input_value(page, '#stock-description'),
                            get_input_value(page, '#stock-cost_price'),
                            get_input_value(page, '#stock-retail_price'),
                        )

                        created_at, total_quantity, barserial, stock_type = await asyncio.gather(
                            get_summary_detail(page, 'Created'),
                            get_summary_detail(page, 'Total Quantity'),
                            get_summary_detail(page, 'Barserial'),
                            get_summary_detail(page, 'Type'),
                        )

                        # Print the key information

                        results.append({
                            "barcode": barcode,
                            "barserial": barserial,
                            "name": name,
                            "description": description,
                            "cost_price": cost_price,
                            "retail_price": retail_price,
                            "created_at": created_at,
                            "quantity": total_quantity,
                            "type": stock_type
                        })

                        print(f"Search Barcode: {barcode}")
                        print(f"  Barserial: {barserial}")
                        print(f"  Name: {name}")
                        print(f"  Description: {description}")
                        print(f"  Cost Price: {cost_price}")
                        print(f"  Retail Price: {retail_price}")
                        print(f"  Created At: {created_at}")
                        print(f"  Quantity: {total_quantity}")
                        print(f"  Type: {stock_type}")
                        print("-" * 50)

                    except Exception as e:
                        print(f"[ERROR] Failed to extract data for {barcode}: {e}")
                        await page.screenshot(path=f"debug_{barcode}.png")
                else:
                    print(f"[WARN] Unexpected page for {barcode}. URL: {page.url}")
                    if "search" in page.url or "query" in page.url:
                        print(f"[INFO] Appears to be search results page - no exact match for {barcode}")

                # Delay between barcodes
                if i < len(barcodes) - 1:
                    delay = random.uniform(1, 2)
                    print(f"[INFO] Waiting {delay:.1f}s before next search...")
                    await asyncio.sleep(delay)

            print("[INFO] Closing NOSPOS...", flush=True)
            await browser.close()
            return results


        except Exception as e:
            print(f"Error scraping barcodes: {e}", file=sys.stderr)
            await page.screenshot(path="debug_fatal_error.png")
            await browser.close()
            sys.exit(1)

async def get_input_value(page, selector):
    """Get value from input field, return 'N/A' if empty or not found"""
    try:
        await page.wait_for_selector(selector, timeout=3000)
        value = await page.input_value(selector)
        return value.strip() if value else 'N/A'
    except Exception:
        return 'N/A'

async def get_summary_detail(page, label):
    """Extract data from the summary detail view card"""
    try:
        await page.wait_for_selector('.detail-view', timeout=3000)
        detail_selector = f'.detail-view .detail:has(strong:has-text("{label}"))'
        detail_element = await page.query_selector(detail_selector)

        if not detail_element:
            return 'N/A'

        full_text = await detail_element.text_content()
        if full_text:
            text_without_label = full_text.replace(label, '').strip()
            text_without_label = text_without_label.strip(' :;-')
            return text_without_label if text_without_label else 'N/A'

        return 'N/A'
    except Exception as e:
        print(f"[DEBUG] Error getting '{label}': {e}")
        return 'N/A'

async def main():
    parser = argparse.ArgumentParser(description="Scrape NOSPOS for multiple barcodes")
    parser.add_argument('--barcodes', nargs='+', required=True, help='List of barcodes')
    args = parser.parse_args()
    await scrape_barcodes(args.barcodes)

if __name__ == "__main__":
    asyncio.run(main())