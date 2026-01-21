#!/usr/bin/env python3
"""
Modern eBay search → Telegram scraper
Playwright 1.40+ | python-telegram-bot 20+
"""

import os
import sys
import asyncio
from datetime import datetime, timezone

from playwright.async_api import async_playwright, TimeoutError as PWTimeout
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
    async def _edit(self, chat_id: int, msg_id: int, text: str, buttons=None) -> None:
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
    @staticmethod
    def _esc(text: str) -> str:
        text = text.replace("\\", "\\\\")
        for ch in r"_[]()*~`>#+=|{}.!-":
            text = text.replace(ch, "\\" + ch)
        return text

    # -----------------------------------------------------------------
    async def scrape_search(self, keyword: str, chat_id: int) -> None:
        msg = await self.bot.send_message(
            chat_id=chat_id,
            text="⏳ *Booting eBay scraper…*",
            parse_mode="MarkdownV2",
        )

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
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
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )

            page = await ctx.new_page()

            # 1. Load
            await self._edit(chat_id, msg.message_id, "⏳ *Loading eBay search…* \\[1/4\\]")
            url = f"https://www.ebay.com/sch/i.html?_nkw={keyword.replace(' ', '+')}&_sop=12"
            await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            await asyncio.sleep(3)

            # 2. CAPTCHA check
            await self._edit(chat_id, msg.message_id, "⏳ *Bot\\-wall check…* \\[2/4\\]")
            title = (await page.title()).lower()
            if any(x in title for x in ("captcha", "robot")):
                await self._edit(chat_id, msg.message_id, "❌ eBay CAPTCHA – try later.")
                await browser.close()
                return

            # 3. Scroll
            await self._edit(chat_id, msg.message_id, "⏳ *Scrolling items…* \\[3/4\\]")
            for _ in range(4):
                await page.evaluate("window.scrollBy(0, 1000)")
                await asyncio.sleep(1.5)

            # 4. Wait ONLY for containers (SAFE)
            await self._edit(chat_id, msg.message_id, "⏳ *Collecting products…* \\[4/4\\]")

            try:
                await page.wait_for_selector("li.s-item", timeout=30_000)
            except PWTimeout:
                ss = await page.screenshot(
                    clip={"x": 0, "y": 0, "width": 1280, "height": 720}
                )
                await self.bot.send_photo(
                    chat_id,
                    photo=ss,
                    caption="eBay loaded but no result containers",
                    parse_mode=None,
                )
                await browser.close()
                return

            raw_items = page.locator("li.s-item")
            total = await raw_items.count()
            print(f"[INFO] Raw items: {total}")

            products = []

            for i in range(total):
                li = raw_items.nth(i)

                try:
                    title_el = li.locator("h3.s-item__title, span.s-item__title")
                    if await title_el.count() == 0:
                        continue

                    title = (await title_el.first.inner_text()).strip()
                    if not title or "shop on ebay" in title.lower():
                        continue

                    price_el = li.locator("span.s-item__price")
                    if await price_el.count() == 0:
                        continue
                    price = (await price_el.first.inner_text()).strip()

                    ship_el = li.locator("span.s-item__shipping")
                    ship = (await ship_el.first.inner_text()).strip() if await ship_el.count() else ""

                    link_el = li.locator("a.s-item__link")
                    href = await link_el.get_attribute("href")
                    if not href:
                        continue

                    item_id = href.split("/")[-1].split("?")[0]

                    products.append(
                        {
                            "id": item_id,
                            "title": title[:80],
                            "price": price,
                            "ship": ship,
                        }
                    )

                except Exception as exc:
                    print(f"[WARN] skip item: {exc}")

            print(f"[INFO] Extracted products: {len(products)}")

            if not products:
                ss = await page.screenshot(
                    clip={"x": 0, "y": 0, "width": 1280, "height": 720}
                )
                await self.bot.send_photo(
                    chat_id,
                    photo=ss,
                    caption="Products visible but extraction returned empty",
                    parse_mode=None,
                )
                await browser.close()
                return

            # Screenshot
            ss = await page.screenshot(
                clip={"x": 0, "y": 0, "width": 1280, "height": 720}
            )
            await self.bot.send_photo(
                chat_id,
                photo=ss,
                caption=f"📸 *eBay results for* `{self._esc(keyword)}`",
                parse_mode="MarkdownV2",
            )

            # Text report
            text = f"🔍 *eBay search:* `{self._esc(keyword)}`\n\n"
            buttons = []

            for idx, p in enumerate(products, 1):
                text += (
                    f"{idx}\\. **{self._esc(p['title'])}**\n"
                    f"   💰 ||{self._esc(p['price'])}||"
                )
                if p["ship"]:
                    text += f" 🚚 *{self._esc(p['ship'])}*"
                text += "\n\n"

                buttons.append(
                    [
                        InlineKeyboardButton(
                            text=f"📦 View {idx}",
                            url=f"https://www.ebay.com/itm/{p['id']}",
                        )
                    ]
                )

            utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            text += f"⏱ _Last updated:_ `{utc}`"

            await self._edit(chat_id, msg.message_id, text, buttons)
            await browser.close()


# ----------------------------------------------------------------------
async def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python scraper/search_scraper.py <keyword> <chat_id>")
        sys.exit(1)

    scraper = EbaySearchScraper(os.environ["TELEGRAM_BOT_TOKEN"])
    await scraper.scrape_search(sys.argv[1], int(sys.argv[2]))


if __name__ == "__main__":
    asyncio.run(main())
