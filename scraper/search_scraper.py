import os
import sys
import asyncio
from playwright.async_api import async_playwright
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from datetime import datetime

class AmazonSearchScraper:
    def __init__(self, token):
        self.bot = Bot(token=token)
    
    async def edit_message(self, chat_id, message_id, text, buttons=None):
        """Edit message with loading states"""
        try:
            await self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(buttons) if buttons else None
            )
        except Exception as e:
            print(f"Edit failed: {e}")
    
    async def scrape_search(self, keyword, chat_id):
        # Send initial message with loading
        msg = await self.bot.send_message(
            chat_id=chat_id,
            text="⏳ **Initializing search...**",
            parse_mode='Markdown'
        )
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = await context.new_page()
            
            # Step 1: Load Amazon search
            await self.edit_message(
                chat_id, msg.message_id,
                "⏳ **Loading Amazon search page...** [1/4]"
            )
            
            search_url = f"https://www.amazon.com/s?k={keyword.replace(' ', '+')}"
            await page.goto(search_url, wait_until='domcontentloaded')
            
            # Step 2: Wait for results
            await self.edit_message(
                chat_id, msg.message_id,
                "⏳ **Waiting for results...** [2/4]"
            )
            await page.wait_for_selector('[data-component-type="s-search-result"]', timeout=10000)
            
            # Step 3: Take screenshot
            await self.edit_message(
                chat_id, msg.message_id,
                "⏳ **Taking screenshot...** [3/4]"
            )
            
            # Scroll to load images
            await page.evaluate('window.scrollBy(0, 800)')
            await asyncio.sleep(2)
            
            screenshot = await page.screenshot(full_page=False, size={'width': 1200, 'height': 800})
            
            # Step 4: Extract product data
            await self.edit_message(
                chat_id, msg.message_id,
                "⏳ **Extracting product data...** [4/4]"
            )
            
            products = []
            items = await page.locator('[data-component-type="s-search-result"]').all()[:5]
            
            for i, item in enumerate(items):
                try:
                    # Product ASIN
                    asin = await item.get_attribute('data-asin')
                    
                    # Title
                    title_locator = item.locator('h2 a span, .s-title-instructions h2 a span')
                    title = await title_locator.inner_text(timeout=1000) if await title_locator.count() > 0 else "N/A"
                    title = title[:60] + "..." if len(title) > 60 else title
                    
                    # Price
                    price_locator = item.locator('.a-price-whole, .a-offscreen')
                    price = await price_locator.inner_text(timeout=1000) if await price_locator.count() > 0 else "N/A"
                    
                    # Rating
                    rating_locator = item.locator('.a-icon-alt')
                    rating = await rating_locator.inner_text(timeout=500) if await rating_locator.count() > 0 else "No rating"
                    if rating != "No rating":
                        rating = rating.split()[0]
                    
                    products.append({
                        'asin': asin,
                        'title': title,
                        'price': price,
                        'rating': rating
                    })
                except Exception as e:
                    print(f"Error extracting item {i}: {e}")
                    continue
            
            await browser.close()
            
            # Send screenshot
            await self.bot.send_photo(
                chat_id=chat_id,
                photo=screenshot,
                caption=f"📸 Search results for '{keyword}'"
            )
            
            # Format results with buttons
            results_text = f"🔍 **Search Results: '{keyword}'**\n\n"
            buttons = []
            
            for idx, product in enumerate(products, 1):
                results_text += f"{idx}. **{product['title']}**\n"
                results_text += f"   💰 Price: {product['price']}\n"
                results_text += f"   ⭐ Rating: {product['rating']}\n"
                results_text += f"   🆔 ASIN: `{product['asin']}`\n\n"
                
                # Button for each product
                buttons.append([InlineKeyboardButton(
                    text=f"📦 View Product {idx}",
                    callback_data=f"details:{product['asin']}"
                )])
            
            results_text += f"⏰ Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            
            # Edit original message with results
            await self.edit_message(
                chat_id, msg.message_id,
                results_text,
                buttons=buttons
            )

async def main():
    if len(sys.argv) != 3:
        print("Usage: python search_scraper.py <keyword> <chat_id>")
        sys.exit(1)
    
    keyword = sys.argv[1]
    chat_id = int(sys.argv[2])
    
    scraper = AmazonSearchScraper(os.getenv('TELEGRAM_BOT_TOKEN'))
    await scraper.scrape_search(keyword, chat_id)

if __name__ == "__main__":
    asyncio.run(main())