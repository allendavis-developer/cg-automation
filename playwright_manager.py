import asyncio
import os
import aiohttp
from playwright.async_api import async_playwright

playwright_instance = None
browser_instance = None
context_instance = None
_shutdown_flag = False


async def connect_chromium():
    """Connect to a running Chromium instance via CDP."""
    global playwright_instance, browser_instance, context_instance

    if playwright_instance and context_instance:
        return context_instance

    playwright_instance = await async_playwright().start()

    try:
        browser_instance = await playwright_instance.chromium.connect_over_cdp("http://localhost:9222")
        context_instance = browser_instance.contexts[0] if browser_instance.contexts else await browser_instance.new_context()
        print("✅ Connected to running Chromium via CDP.")

        # Start background task to detect browser closure
        asyncio.create_task(_watch_chromium_cdp())
    except Exception as e:
        print(f"❌ Could not connect to running browser: {e}")
        raise

    return context_instance


async def _watch_chromium_cdp():
    """Monitor Chromium via CDP WebSocket; shut down FastAPI if it closes."""
    global _shutdown_flag
    cdp_url = "http://localhost:9222/json/version"
    while not _shutdown_flag:
        await asyncio.sleep(2)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(cdp_url) as resp:
                    if resp.status != 200:
                        raise Exception("CDP endpoint unreachable")
        except Exception:
            print("⚠️ Chromium closed or CDP endpoint unavailable — shutting down FastAPI.")
            os._exit(0)  # immediately close console + FastAPI
    print("🧹 Chromium watcher stopped.")


async def shutdown_chromium():
    """Cleanly close Chromium and Playwright."""
    global browser_instance, playwright_instance, _shutdown_flag
    _shutdown_flag = True
    try:
        if browser_instance:
            await browser_instance.close()
        if playwright_instance:
            await playwright_instance.stop()
        print("🧹 Chromium connection closed.")
    except Exception as e:
        print(f"[WARN] Error closing Chromium: {e}")
