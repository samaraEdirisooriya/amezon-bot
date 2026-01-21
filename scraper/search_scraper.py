import os
import sys
import asyncio
from playwright.async_api import async_playwright
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from datetime import datetime


class EbaySearchScraper:
    def __init__(self, token: str):
        self.bot = Bot(token=token)

    # ------------------------------------------------------------------
    # Helper: edit message safely
    # ------------------------------------------------------------------
    async def edit_message(self, chat_id, message_id, text, buttons=None):
        try:
            await self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
            )
        except Exception as exc:
            print(f"[WARN] Edit failed: {exc}")

    # ------------------------------------------------------------------
    # Core: scrape eBay search
    # ------------------------------------------------------------------
    async def scrape_search(self, keyword: str, chat_id: int):
        # 0. send “please wait”
        msg = await self.bot.send_message(
            chat_id=chat_id,
            text="⏳ *Booting eBay scraper …*",
            parse_mode="Markdown",
        )

        async with async_playwright() as p:
            # 1. stealth browser
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--disable-accelerated-2d-canvas",
                    "--no-first-run",
                    "--no-zygote",
                    "--disable-gpu",
                    "--disable-web-security",
                    "--disable-features=VizDisplayCompositor",
                ],
            )

            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
            )

            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                window.chrome = {runtime: {}};
                delete navigator.__proto__.connection;
                Object.defineProperty(document, 'hidden', {get: () => false});
            """)

            page = await context.new_page()

            # 2. build eBay search URL
            search_url = (
                "https://www.ebay.com/sch/i.html?"
                f"_nkw={keyword.replace(' ', '+')}&_sop=12"
            )
            print(f"[INFO] Loading {search_url}")

            await self.edit_message(
                chat_id, msg.message_id, "⏳ *Loading eBay search …* [1/4]"
            )
            await page.goto(search_url, wait_until="domcontentloaded", timeout=60_000)
            await asyncio.sleep(3)

            # 3. quick captcha check
            await self.edit_message(
                chat_id, msg.message_id, "⏳ *Checking for bot wall …* [2/4]"
            )
            title = await page.title()
            if any(x in title.lower() for x in ("captcha", "robot", "verify")):
                await self.edit_message(
                    chat_id,
                    msg.message_id,
                    "❌ eBay asked for CAPTCHA – please try again later.",
                )
                await browser.close()
                return

            # 4. scroll to trigger lazy images
            await self.edit_message(
                chat_id, msg.message_id, "⏳ *Scrolling for items …* [3/4]"
            )
            for i in range(3):
                await page.evaluate("window.scrollBy(0, 1000)")
                await asyncio.sleep(2)
                print(f"[INFO] Scroll {i+1}/3")

            # 5. pick best selector
            await self.edit_message(
                chat_id, msg.message_id, "⏳ *Collecting products …* [4/4]"
            )
            selectors = [
                "li.s-item",                    # modern desktop
                "div.s-item__wrapper",          # fallback
                "[data-view='mi:1686|iid:1']",  # occasional
            ]
            items = []
            for sel in selectors:
                try:
                    items = await page.locator(sel).all(timeout=15_000)
                    if len(items) > 2:
                        print(f"[INFO] Using selector {sel} – {len(items)} items")
                        break
                except Exception as e:
                    print(f"[WARN] Selector {sel} failed: {e}")
                    continue

            if not items:
                await self.edit_message(
                    chat_id,
                    msg.message_id,
                    "❌ No products found – sending debug screenshot …",
                )
                ss = await page.screenshot(full_page=True)
                await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=ss,
                    caption=f"Debug:\nTitle: {title}\nURL: {search_url}",
                )
                await browser.close()
                return

            # 6. extract data (limit 5)
            products = []
            for idx, li in enumerate(items[:5], 1):
                try:
                    # title
                    title_sel = li.locator(
                        "h3.s-item__title, .s-item__title span, a.s-item__link span"
                    )
                    title_txt = (
                        await title_sel.inner_text(timeout=3_000)
                        if await title_sel.count()
                        else "N/A"
                    )
                    title_txt = (
                        (title_txt[:60] + "…") if len(title_txt) > 60 else title_txt
                    )

                    # price
                    price_sel = li.locator(
                        "span.s-item__price, .s-item__price .notranslate"
                    )
                    price_txt = (
                        await price_sel.inner_text(timeout=3_000)
                        if await price_sel.count()
                        else "N/A"
                    )

                    # itemId (eBay’s ASIN)
                    link_sel = li.locator("a.s-item__link")
                    href = (
                        await link_sel.get_attribute("href")
                        if await link_sel.count()
                        else ""
                    )
                    item_id = href.split("/")[-1].split("?")[0] if href else f"id_{idx}"

                    # shipping
                    ship_sel = li.locator("span.s-item__shipping, .s-item__logisticsCost")
                    ship_txt = (
                        await ship_sel.inner_text(timeout=3_000)
                        if await ship_sel.count()
                        else ""
                    )

                    products.append(
                        {
                            "id": item_id,
                            "title": title_txt,
                            "price": price_txt,
                            "ship": ship_txt,
                        }
                    )
                    print(f"[INFO] {idx}) {title_txt[:40]} – {price_txt}")
                except Exception as e:
                    print(f"[WARN] Item {idx} skipped: {e}")
                    continue

            await browser.close()

            if not products:
                await self.edit_message(
                    chat_id, msg.message_id, "❌ Could not extract any product data."
                )
                return

            # 7. send screenshot
            ss = await page.screenshot(full_page=False, size={"width": 1200, "height": 800})
            await self.bot.send_photo(
                chat_id=chat_id,
                photo=ss,
                caption=f"📸 eBay search results for *{keyword}*",
                parse_mode="Markdown",
            )

            # 8. format message
            text = f"🔍 *eBay search: “{keyword}”*\n\n"
            buttons = []
            for idx, p in enumerate(products, 1):
                text += f"{idx}. **{p['title']}**\n"
                text += f"   💰 {p['price']}"
                text += f"   🚚 {p['ship']}\n\n" if p["ship"] else "\n\n"

                buttons.append(
                    [
                        InlineKeyboardButton(
                            text=f"📦 View item {idx}",
                            url=f"https://www.ebay.com/itm/{p['id']}",
                        )
                    ]
                )

            text += f"⏱ _Generated {datetime.now():%Y-%m-%d %H:%M}_"
            await self.edit_message(chat_id, msg.message_id, text, buttons=buttons)


# ----------------------------------------------------------------------
# CLI entry
# ----------------------------------------------------------------------
async def main():
    if len(sys.argv) != 3:
        print("Usage: python ebay_search_scraper.py <keyword> <chat_id>")
        sys.exit(1)

    keyword = sys.argv[1]
    chat_id = int(sys.argv[2])

    scraper = EbaySearchScraper(os.getenv("TELEGRAM_BOT_TOKEN"))
    await scraper.scrape_search(keyword, chat_id)


if __name__ == "__main__":
    asyncio.run(main())