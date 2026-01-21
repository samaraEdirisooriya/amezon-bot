#!/usr/bin/env python3
"""
Modern eBay-search → Telegram scraper
Playwright 1.40+  | python-telegram-bot 20+
"""

import os
import sys
import asyncio
from datetime import datetime, timezone

from playwright.async_api import async_playwright
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

# ---------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Export TELEGRAM_BOT_TOKEN first")

# ---------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------
class EbaySearchScraper:
    def __init__(self, token: str) -> None:
        self.bot = Bot(token)

    # -----------------------------------------------------------------
    # Safe message editor
    # -----------------------------------------------------------------
    async def _edit(
        self, chat_id: int, msg_id: int, text: str, buttons=None
    ) -> None:
        try:
            await self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=text,
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
            )
        except Exception as exc:
            print(f"[WARN] edit fail: {exc}")

    # -----------------------------------------------------------------
    # Markdown-V2 escaper (complete)
    # -----------------------------------------------------------------
    @staticmethod
    def _esc(text: str) -> str:
        for ch in r"_[]()*~`>#+=|{}.!-":
            text = text.replace(ch, "\\" + ch)
        return text.replace("\\", "\\\\")  # keep last

    # -----------------------------------------------------------------
    # Core
    # -----------------------------------------------------------------
    async def scrape_search(self, keyword: str, chat_id: int) -> None:
        # 0. boot message
        msg = await self.bot.send_message(
            chat_id=chat_id,
            text="⏳ *Booting eBay scraper…*",
            parse_mode="MarkdownV2",
        )

        async with async_playwright() as pw:
            # 1. stealth browser
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-web-security",
                    "--disable-features=VizDisplayCompositor",
                ],
            )
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/123.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 720},
            )
            await ctx.add_init_script(
                """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = {runtime: {}};
                """
            )
            page = await ctx.new_page()

            # 2. load eBay  (FIX: no space after _nkw=)
            await self._edit(chat_id, msg.message_id, "⏳ *Loading eBay search…* \\[1/4]")
            url = f"https://www.ebay.com/sch/i.html?_nkw={keyword.replace(' ', '+')}&_sop=12"
            await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            await asyncio.sleep(2)

            # 3. captcha check  (FIX:  NO await)
            await self._edit(chat_id, msg.message_id, "⏳ *Bot\\-wall check…* \\[2/4]")
            if any(x in page.title().lower() for x in ("captcha", "robot")):
                await self._edit(chat_id, msg.message_id, "❌ eBay CAPTCHA – try later.")
                await browser.close()
                return

            # 4. scroll for lazy images
            await self._edit(chat_id, msg.message_id, "⏳ *Scrolling items…* \\[3/4]")
            for i in range(3):
                await page.evaluate("window.scrollBy(0, 800)")
                await asyncio.sleep(1.5)

            # 5. grab items
            await self._edit(chat_id, msg.message_id, "⏳ *Collecting products…* \\[4/4]")
            selectors = ["li.s-item", "div.s-item__wrapper"]
            items = []
            for sel in selectors:
                items = await page.locator(sel).all()  # NO timeout
                if len(items) > 2:
                    print(f"[INFO] {len(items)} items via {sel}")
                    break

            if not items:
                ss = await page.screenshot(full_page=True)
                await self.bot.send_photo(chat_id, photo=ss, caption="❌ No items found")
                return

            # 6. extract
            products = []
            for idx, li in enumerate(items[:6], 1):
                try:
                    title = (
                        await li.locator("h3.s-item__title, .s-item__title span")
                        .first.inner_text(timeout=3_000)
                    ).replace("\n", " ")[:70]
                    price = (
                        await li.locator("span.s-item__price").first.inner_text(timeout=3_000)
                    ).strip()
                    ship = (
                        await li.locator("span.s-item__shipping").first.inner_text(timeout=3_000)
                    ).strip() or ""
                    href = await li.locator("a.s-item__link").first.get_attribute("href")
                    item_id = href.split("/")[-1].split("?")[0] if href else f"id{idx}"
                    products.append({"id": item_id, "title": title, "price": price, "ship": ship})
                except Exception as exc:
                    print(f"[WARN] skip item {idx}: {exc}")

            if not products:
                await self._edit(chat_id, msg.message_id, "❌ Could not extract data.")
                return

            # 7. carousel screenshot (Telegram safe)
            ss = await page.screenshot(clip={"x": 0, "y": 0, "width": 1280, "height": 720})
            await self.bot.send_photo(
                chat_id=chat_id,
                photo=ss,
                caption=f"📸 *eBay results for* `{self._esc(keyword)}`",
                parse_mode="MarkdownV2",
            )

            # 8. pretty message  (FIX: no space in URL)
            text = f"🔍 *eBay search:* `{self._esc(keyword)}`\n\n"
            buttons = []
            for idx, p in enumerate(products, 1):
                text += f"{idx}\\. **{self._esc(p['title'])}**\n   💰 ||{self._esc(p['price'])}||"
                if p["ship"]:
                    text += f" 🚚 *{self._esc(p['ship'])}*"
                text += "\n\n"

                buttons.append(
                    [
                        InlineKeyboardButton(
                            text=f"📦 View {idx}",
                            url=f"https://www.ebay.com/itm/{p['id']}",  # NO space
                        )
                    ]
                )
            utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            text += f"⏱ _Last updated:_ `{utc}`"
            await self._edit(chat_id, msg.message_id, text, buttons)


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
async def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python scraper/search_scraper.py <keyword> <chat_id>")
        sys.exit(1)

    keyword = sys.argv[1]
    chat_id = int(sys.argv[2])

    scraper = EbaySearchScraper(BOT_TOKEN)
    await scraper.scrape_search(keyword, chat_id)


if __name__ == "__main__":
    asyncio.run(main())