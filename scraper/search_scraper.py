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
            # Launch with enhanced stealth mode
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--no-first-run',
                    '--no-zygote',
                    '--disable-gpu',
                    '--disable-web-security',
                    '--disable-features=VizDisplayCompositor',
                ]
            )
            
            # Add stealth script and context
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={'width': 1920, 'height': 1080}
            )
            
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                window.chrome = { runtime: {} };
                delete navigator.__proto__.connection;
                Object.defineProperty(document, 'hidden', { get: () => false });
            """)
            
            page = await context.new_page()
            
            # Step 1: Load Amazon search
            await self.edit_message(
                chat_id, msg.message_id,
                "⏳ **Loading Amazon search page...** [1/4]"
            )
            
            search_url = f"https://www.amazon.com/s?k={keyword.replace(' ', '+')}"
            print(f"Loading URL: {search_url}")  # DEBUG LOG
            
            await page.goto(search_url, wait_until='domcontentloaded', timeout=60000)
            
            # Wait for page to load
            await asyncio.sleep(5)
            
            # Step 2: Check for CAPTCHA
            await self.edit_message(
                chat_id, msg.message_id,
                "⏳ **Checking for CAPTCHA...** [2/4]"
            )
            
            page_title = await page.title()
            print(f"Page title: {page_title}")  # DEBUG LOG
            
            if "captcha" in page_title.lower() or "robot" in page_title.lower():
                await self.edit_message(
                    chat_id, msg.message_id,
                    "❌ Amazon detected bot and showing CAPTCHA. Try again later or use a proxy service."
                )
                await browser.close()
                return
            
            # Step 3: Scroll multiple times to trigger lazy loading
            await self.edit_message(
                chat_id, msg.message_id,
                "⏳ **Scrolling to load products...** [3/4]"
            )
            
            for scroll in range(3):
                await page.evaluate('window.scrollBy(0, 1000)')
                await asyncio.sleep(2)
                print(f"Scroll {scroll + 1}/3 completed")
            
            # Step 4: Try multiple selectors with longer timeout
            await self.edit_message(
                chat_id, msg.message_id,
                "⏳ **Searching for products...** [4/4]"
            )
            
            selectors = [
                '[data-component-type="s-search-result"]',
                '.s-card-container',
                '[data-cy="title-recipe-title"]',
                '.s-result-item'
            ]
            
            elements = []
            found_selector = None
            
            for selector in selectors:
                try:
                    print(f"Trying selector: {selector}")
                    elements = await page.locator(selector).all(timeout=20000)
                    if elements and len(elements) > 0:
                        found_selector = selector
                        print(f"✅ Found {len(elements)} items with {selector}")
                        break
                    else:
                        print(f"❌ No elements found with {selector}")
                except Exception as e:
                    print(f"❌ Selector failed: {selector} - {str(e)}")
                    continue
            
            if not elements:
                # Take full page screenshot for debugging
                await self.edit_message(
                    chat_id, msg.message_id,
                    "❌ No products found. Sending debug screenshot..."
                )
                
                screenshot = await page.screenshot(full_page=True)
                await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=screenshot,
                    caption=f"❌ Debug Info:\nPage title: {page_title}\nURL: {search_url}\nSelectors tried: {selectors}"
                )
                
                await self.edit_message(
                    chat_id, msg.message_id,
                    "❌ Amazon may be blocking requests. Try again later."
                )
                await browser.close()
                return
            
            # Take screenshot of loaded page
            screenshot = await page.screenshot(full_page=False, size={'width': 1200, 'height': 800})
            
            # Extract product data
            products = []
            items = elements[:5]  # Get first 5 items
            
            for i, item in enumerate(items):
                try:
                    # Product ASIN
                    asin = await item.get_attribute('data-asin')
                    
                    # Title
                    title_locator = item.locator('h2 a span, .s-title-instructions h2 a span')
                    title = await title_locator.inner_text(timeout=3000) if await title_locator.count() > 0 else "N/A"
                    title = title[:60] + "..." if len(title) > 60 else title
                    
                    # Price
                    price_locator = item.locator('.a-price-whole, .a-offscreen')
                    price = await price_locator.inner_text(timeout=3000) if await price_locator.count() > 0 else "N/A"
                    
                    # Rating
                    rating_locator = item.locator('.a-icon-alt')
                    rating = await rating_locator.inner_text(timeout=3000) if await rating_locator.count() > 0 else "No rating"
                    if rating != "No rating":
                        rating = rating.split()[0]
                    
                    if asin:  # Only add if ASIN exists
                        products.append({
                            'asin': asin,
                            'title': title,
                            'price': price,
                            'rating': rating
                        })
                        print(f"Product {i+1}: {asin} - {title[:30]}...")
                except Exception as e:
                    print(f"Error extracting item {i}: {e}")
                    continue
            
            await browser.close()
            
            if not products:
                await self.edit_message(
                    chat_id, msg.message_id,
                    "❌ No valid products found after extraction."
                )
                return
            
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