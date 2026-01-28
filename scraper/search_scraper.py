#!/usr/bin/env python3
"""
Definitive eBay search → Telegram scraper
CI-safe, MarkdownV2-safe, edit-message aware
"""

import os
import sys
import asyncio
from datetime import datetime, timezone
from typing import Optional

from playwright.async_api import async_playwright
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup


BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN not set")


def esc(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\\", "\\\\")
    for ch in r"_[]()*~`>#+=|{}.!-":
        text = text.replace(ch, "\\" + ch)
    return text


class EbaySearchScraper:
    def __init__(self, token: str):
        self.bot = Bot(token)

    async def send_or_edit(
        self,
        chat_id: int,
        text: str,
        message_id: Optional[int] = None,
        buttons=None,
    ):
        try:
            if message_id:
                await self.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode="MarkdownV2",
                    reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
                )
            else:
                msg = await self.bot.send_message(
                    chat_id,
                    text,
                    parse_mode="MarkdownV2",
                    reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
                )
                return msg.message_id
        except Exception as e:
            print(f"[WARN] Telegram update failed: {e}")

    async def scrape(self, keyword: str, chat_id: int, edit_message_id: Optional[int]):
        msg_id = edit_message_id or await self.send_or_edit(
            chat_id, "⏳ *Starting eBay search…*"
        )

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )

            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/123 Safari/537.36"
                ),
            )

            page = await ctx.new_page()

            await self.send_or_edit(
                chat_id, "⏳ *Loading eBay…* \\[1/4\\]", msg_id
            )

            url = f"https://www.ebay.com/sch/i.html?_nkw={keyword.replace(' ', '+')}&_sop=12"
            await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            await asyncio.sleep(4)

            await self.send_or_edit(
                chat_id, "⏳ *Rendering products…* \\[2/4\\]", msg_id
            )

            for _ in range(6):
                await page.evaluate("window.scrollBy(0, 1400)")
                await asyncio.sleep(1)

            await self.send_or_edit(
                chat_id, "⏳ *Extracting products…* \\[3/4\\]", msg_id
            )

            products = await page.evaluate("""
() => {
  const out = [];
  const seen = new Set();

  document.querySelectorAll('a[href*="/itm/"]').forEach(a => {
    const href = a.getAttribute('href') || '';
    const id = href.split('/').pop().split('?')[0];
    if (!id || seen.has(id)) return;

    let root = a.closest('li') || a.closest('div');
    if (!root) return;

    let title = root.querySelector('h3')?.innerText || a.innerText;
    let price = root.querySelector('[class*="price"]')?.innerText;

    if (!title || !price) return;

    let ship =
      root.querySelector('[class*="shipping"]')?.innerText || '';

    out.push({
      id,
      title: title.trim().slice(0, 100),
      price: price.trim().slice(0, 50),
      ship: ship.trim().slice(0, 50)
    });

    seen.add(id);
  });

  return out;
}
""")

            await self.send_or_edit(
                chat_id, "⏳ *Finalizing…* \\[4/4\\]", msg_id
            )

            if not products:
                await self.send_or_edit(
                    chat_id,
                    "❌ *No products found.* Try another keyword.",
                    msg_id,
                )
                await browser.close()
                return

            # Screenshot proof
            ss = await page.screenshot(full_page=False)
            await self.bot.send_photo(
                chat_id,
                ss,
                caption=f"📸 *Results for* `{esc(keyword)}`",
                parse_mode="MarkdownV2",
            )

            text = f"🔍 *eBay Search:* `{esc(keyword)}`\n\n"
            buttons = []

            for i, p in enumerate(products[:10], 1):
                text += (
                    f"{i}\\. **{esc(p['title'])}**\n"
                    f"   💰 `{esc(p['price'])}`"
                )
                if p["ship"]:
                    text += f" 🚚 _{esc(p['ship'])}_"
                text += "\n\n"

                buttons.append(
                    [InlineKeyboardButton(
                        f"📦 View {i}",
                        url=f"https://www.ebay.com/itm/{p['id']}"
                    )]
                )

            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            text += f"⏱ _Updated:_ `{ts}`"

            await self.send_or_edit(chat_id, text, msg_id, buttons)
            await browser.close()


async def main():
    if len(sys.argv) < 3:
        print("Usage: search_scraper.py <keyword> <chat_id> [edit_message_id]")
        sys.exit(1)

    keyword = sys.argv[1]
    chat_id = int(sys.argv[2])
    edit_id = int(sys.argv[3]) if len(sys.argv) == 4 and sys.argv[3] else None

    scraper = EbaySearchScraper(BOT_TOKEN)
    await scraper.scrape(keyword, chat_id, edit_id)


if __name__ == "__main__":
    asyncio.run(main())
