#!/usr/bin/env python3
"""
Definitive eBay search → Telegram scraper
(JS-evaluated extraction for headless CI)
"""

import os
import sys
import asyncio
from datetime import datetime, timezone

from playwright.async_api import async_playwright
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Export TELEGRAM_BOT_TOKEN first")


class EbaySearchScraper:
    def __init__(self, token: str):
        self.bot = Bot(token)

    async def _edit(self, chat_id, msg_id, text, buttons=None):
        try:
            await self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=text,
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
            )
        except Exception as e:
            print(f"[WARN] edit fail: {e}")

    @staticmethod
    def _esc(text: str) -> str:
        text = text.replace("\\", "\\\\")
        for ch in r"_[]()*~`>#+=|{}.!-":
            text = text.replace(ch, "\\" + ch)
        return text

    async def scrape_search(self, keyword: str, chat_id: int):
        msg = await self.bot.send_message(
            chat_id,
            "⏳ *Booting eBay scraper…*",
            parse_mode="MarkdownV2",
        )

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )

            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/123.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 720},
            )

            page = await ctx.new_page()

            # 1. Load
            await self._edit(chat_id, msg.message_id, "⏳ *Loading eBay…* \\[1/4\\]")
            url = f"https://www.ebay.com/sch/i.html?_nkw={keyword.replace(' ', '+')}&_sop=12"
            await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            await asyncio.sleep(5)

            # 2. Scroll
            await self._edit(chat_id, msg.message_id, "⏳ *Rendering products…* \\[2/4\\]")
            for _ in range(6):
                await page.evaluate("window.scrollBy(0, 1200)")
                await asyncio.sleep(1.2)

            # 3. JS extraction (CRITICAL FIX)
            await self._edit(chat_id, msg.message_id, "⏳ *Extracting products…* \\[3/4\\]")

            products = await page.evaluate(
                """
                () => {
                  const items = [];
                  document.querySelectorAll('a[href*="/itm/"]').forEach(a => {
                    const root = a.closest('li, div');
                    if (!root) return;

                    const title =
                      root.querySelector('h3')?.innerText ||
                      root.querySelector('.s-item__title')?.innerText;

                    const price =
                      root.querySelector('.s-item__price')?.innerText;

                    if (!title || !price) return;
                    if (title.toLowerCase().includes('shop on ebay')) return;

                    items.push({
                      id: a.href.split('/').pop().split('?')[0],
                      title: title.trim(),
                      price: price.trim(),
                      ship: root.querySelector('.s-item__shipping')?.innerText || ''
                    });
                  });
                  return items;
                }
                """
            )

            print(f"[INFO] JS extracted: {len(products)} items")

            if not products:
                ss = await page.screenshot(
                    clip={"x": 0, "y": 0, "width": 1280, "height": 720}
                )
                await self.bot.send_photo(
                    chat_id,
                    photo=ss,
                    caption="Rendered visually but JS extraction returned empty",
                    parse_mode=None,
                )
                await browser.close()
                return

            # 4. Screenshot
            ss = await page.screenshot(
                clip={"x": 0, "y": 0, "width": 1280, "height": 720}
            )
            await self.bot.send_photo(
                chat_id,
                photo=ss,
                caption=f"📸 *eBay results for* `{self._esc(keyword)}`",
                parse_mode="MarkdownV2",
            )

            # 5. Text report
            text = f"🔍 *eBay search:* `{self._esc(keyword)}`\n\n"
            buttons = []

            for i, p in enumerate(products[:10], 1):
                text += (
                    f"{i}\\. **{self._esc(p['title'][:80])}**\n"
                    f"   💰 ||{self._esc(p['price'])}||"
                )
                if p["ship"]:
                    text += f" 🚚 *{self._esc(p['ship'])}*"
                text += "\n\n"

                buttons.append(
                    [InlineKeyboardButton(f"📦 View {i}", url=f"https://www.ebay.com/itm/{p['id']}")]
                )

            utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            text += f"⏱ _Last updated:_ `{utc}`"

            await self._edit(chat_id, msg.message_id, text, buttons)
            await browser.close()


async def main():
    if len(sys.argv) != 3:
        print("Usage: python scraper/search_scraper.py <keyword> <chat_id>")
        sys.exit(1)

    scraper = EbaySearchScraper(BOT_TOKEN)
    await scraper.scrape_search(sys.argv[1], int(sys.argv[2]))


if __name__ == "__main__":
    asyncio.run(main())
