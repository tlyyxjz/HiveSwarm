"""Playwright 切 9 个 Tab 截图（精确 selector + force click）"""
import asyncio, os
os.environ['NO_PROXY'] = '*'
from playwright.async_api import async_playwright

URL = "http://127.0.0.1:7860/"
OUT_DIR = r"C:\Users\Lenovo\Desktop\hiveswarm-tabs"
os.makedirs(OUT_DIR, exist_ok=True)

TABS = ["Health", "Submit", "Tasks", "Events", "Skills", "Brain", "Repair", "Memory", "Inspect"]


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-proxy-server"])
        ctx = await browser.new_context(viewport={"width": 1600, "height": 900})
        page = await ctx.new_page()
        await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)

        for idx, label in enumerate(TABS, 1):
            try:
                # role=tab 精确匹配（Gradio 6 用 role="tab"）
                btn = page.locator(f'div[role="tablist"] button[role="tab"]:has-text("{label}")').first
                await btn.scroll_into_view_if_needed()
                await btn.click(force=True, timeout=8000)
                await page.wait_for_timeout(2500)
                out = os.path.join(OUT_DIR, f"{idx:02d}_{label}.png")
                await page.screenshot(path=out, full_page=False)
                print(f"  [OK] {idx:02d}_{label}.png")
            except Exception as e:
                print(f"  [FAIL] {label}: {e}")

        await browser.close()
        print(f"\nDone.")


asyncio.run(main())