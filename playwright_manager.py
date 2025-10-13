import asyncio
import os
import aiohttp
import subprocess
from pathlib import Path
from playwright.async_api import async_playwright

playwright_instance = None
browser_instance = None
context_instance = None
_shutdown_flag = False

# Persistent user data path
USER_DATA_DIR = Path(__file__).parent / "playwright_user_data"
REMOTE_DEBUGGING_PORT = 9222

def get_chromium_path():
    """Dynamically detect Chromium path like the batch file."""
    browsers_path = Path(__file__).parent / "python/local-browsers"
    chromium_dirs = list(browsers_path.glob("chromium-*"))
    if not chromium_dirs:
        raise FileNotFoundError(f"No chromium-* folder found in {browsers_path}")
    chromium_dir = chromium_dirs[0]  # take the first found
    chrome_exe = chromium_dir / "chrome-win" / "chrome.exe"
    if not chrome_exe.exists():
        raise FileNotFoundError(f"chrome.exe not found in {chrome_exe}")
    return str(chrome_exe)


async def connect_chromium():
    """Connect to a running Chromium via CDP, or launch a new one if needed."""
    global playwright_instance, browser_instance, context_instance

    if playwright_instance and context_instance:
        return context_instance

    playwright_instance = await async_playwright().start()

    # Try connecting to existing Chromium first
    try:
        browser_instance = await playwright_instance.chromium.connect_over_cdp(f"http://localhost:{REMOTE_DEBUGGING_PORT}")
        context_instance = browser_instance.contexts[0] if browser_instance.contexts else await browser_instance.new_context()
        print("✅ Connected to running Chromium via CDP.")
        asyncio.create_task(_watch_chromium_cdp())
        return context_instance
    except Exception:
        print("⚠️ No running Chromium found, launching a new instance...")

    # Launch Chromium dynamically
    chromium_path = get_chromium_path()
    subprocess.Popen([
        chromium_path,
        f"--remote-debugging-port={REMOTE_DEBUGGING_PORT}",
        f"--user-data-dir={USER_DATA_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-maximized",
        "--enable-gpu",
        "--enable-webgl",
        "--ignore-gpu-blocklist",
        "--enable-features=UseOzonePlatform",
        "--use-gl=desktop",
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
        "--process-per-site"
    ])
    await asyncio.sleep(3)  # give Chromium time to start

    # Try connecting again
    try:
        browser_instance = await playwright_instance.chromium.connect_over_cdp(f"http://localhost:{REMOTE_DEBUGGING_PORT}")
        context_instance = browser_instance.contexts[0] if browser_instance.contexts else await browser_instance.new_context()
        print("✅ Launched and connected to new Chromium instance.")
        asyncio.create_task(_watch_chromium_cdp())
        return context_instance
    except Exception as e:
        print(f"❌ Failed to launch/connect Chromium: {e}")
        raise


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
