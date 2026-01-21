import os
import sys
import asyncio
from datetime import datetime, timezone
from playwright.async_api import async_playwright
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

class EbayProductScraper:
    def __init__(self, token):
        self.bot = Bot(token=token)
    
    @staticmethod
    def _esc(text: str) -> str:
        """Escape special characters for MarkdownV2"""
        text = text.replace("\\", "\\\\")
        for ch in r"_[]()*~`>#+=|{}.!-":
            text = text.replace(ch, "\\" + ch)
        return text
    
    async def edit_message(self, chat_id, message_id, text, buttons=None):
        """Edit existing message"""
        try:
            await self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup(buttons) if buttons else None
            )
        except Exception as e:
            print(f"Edit failed: {e}")
            await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup(buttons) if buttons else None
            )
    
    async def scrape_product(self, product_name, chat_id, edit_message_id=None):
        """Scrape eBay products like search_scraper.py"""
        msg = None
        if edit_message_id and edit_message_id != "undefined":
            await self.edit_message(
                chat_id, int(edit_message_id),
                "⏳ *Loading eBay products…*"
            )
        else:
            msg = await self.bot.send_message(
                chat_id=chat_id,
                text="⏳ *Searching eBay…*",
                parse_mode="MarkdownV2"
            )
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/123.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 720}
            )
            
            page = await context.new_page()
            
            # Load eBay search page
            if edit_message_id and edit_message_id != "undefined":
                await self.edit_message(chat_id, int(edit_message_id), "⏳ *Loading eBay…* \\[1/4\\]")
            
            url = f"https://www.ebay.com/sch/i.html?_nkw={product_name.replace(' ', '+')}&_sop=12"
            await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            await asyncio.sleep(5)
            
            # Scroll to render lazy-loaded items
            if edit_message_id and edit_message_id != "undefined":
                await self.edit_message(chat_id, int(edit_message_id), "⏳ *Rendering products…* \\[2/4\\]")
            
            for _ in range(6):
                await page.evaluate("window.scrollBy(0, 1200)")
                await asyncio.sleep(1.2)
            
            # JS extraction with robust selectors
            if edit_message_id and edit_message_id != "undefined":
                await self.edit_message(chat_id, int(edit_message_id), "⏳ *Extracting products…* \\[3/4\\]")
            
            try:
                await page.wait_for_selector("ul.srp-results, div.s-item__wrapper", timeout=15_000)
            except Exception:
                print("[WARN] Product container not found, continuing anyway…")
            
            products = await page.evaluate("""
() => {
    const items = [];
    const seen = new Set();
    
    document.querySelectorAll('a[href*="/itm/"]').forEach(a => {
        const href = a.getAttribute('href') || '';
        const id = href.split('/').pop().split('?')[0];
        if (!id || seen.has(id)) return;
        
        let root = a.closest('li') || a.closest('div[role="option"]') || 
                   a.closest('div[class*="item"]') || a.closest('article') || 
                   a.closest('div');
        if (!root) return;
        
        let title = '';
        [
            root.querySelector('h3'),
            root.querySelector('[class*="title"]'),
            root.querySelector('span[role="heading"]'),
            a
        ].forEach(el => {
            if (!title && el) title = el.innerText || el.textContent || '';
        });
        
        title = title.trim();
        if (!title || title.toLowerCase().includes('shop on ebay') || title.length < 3) return;
        
        let price = '';
        [
            root.querySelector('[class*="price"]'),
            root.querySelector('span[class*="BOLD"]'),
            root.querySelector('[data-test-component="LISTING_PRICE"]')
        ].forEach(el => {
            if (!price && el) price = el.innerText || el.textContent || '';
        });
        
        price = price.trim();
        if (!price) return;
        
        let ship = '';
        const shippingEl = root.querySelector('[class*="shipping"]') || 
                          root.querySelector('[class*="SHIPPING"]');
        if (shippingEl) ship = shippingEl.innerText || shippingEl.textContent || '';
        
        items.push({
            id: id,
            title: title.substring(0, 100),
            price: price.substring(0, 50),
            ship: ship.trim().substring(0, 50)
        });
        seen.add(id);
    });
    
    return items;
}
""")
            
            print(f"[INFO] JS extracted: {len(products)} items")
            
            # Take screenshot
            ss = await page.screenshot(
                clip={"x": 0, "y": 0, "width": 1280, "height": 720}
            )
            
            await browser.close()
            
            # Send screenshot
            await self.bot.send_photo(
                chat_id,
                photo=ss,
                caption=f"📸 *eBay results for* `{self._esc(product_name)}`",
                parse_mode="MarkdownV2"
            )
            
            if not products:
                await self.bot.send_message(
                    chat_id,
                    "Rendered visually but JS extraction returned empty",
                    parse_mode=None,
                )
                return
            
            # Text report + buttons
            text = f"🔍 *eBay search:* `{self._esc(product_name)}`\n\n"
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
            
            # Edit or send message
            if edit_message_id and edit_message_id != "undefined":
                await self.edit_message(chat_id, int(edit_message_id), text, buttons=buttons)
            elif msg:
                await self.edit_message(chat_id, msg.message_id, text, buttons=buttons)
            else:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="MarkdownV2",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )

async def main():
    if len(sys.argv) < 3:
        print("Usage: python product_scraper.py <product_name> <chat_id> [edit_message_id]")
        sys.exit(1)
    
    product_name = sys.argv[1]
    chat_id = int(sys.argv[2])
    edit_message_id = sys.argv[3] if len(sys.argv) > 3 else None
    
    scraper = EbayProductScraper(os.getenv("TELEGRAM_BOT_TOKEN"))
    await scraper.scrape_product(product_name, chat_id, edit_message_id)

if __name__ == "__main__":
    asyncio.run(main())