import os
import sys
import asyncio
from playwright.async_api import async_playwright
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

class AmazonProductScraper:
    def __init__(self, token):
        self.bot = Bot(token=token)
    
    async def edit_message(self, chat_id, message_id, text, buttons=None):
        """Edit existing message"""
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
            # If edit fails, send new message
            await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(buttons) if buttons else None
            )
    
    async def scrape_product(self, asin, chat_id, edit_message_id=None):
        # Loading message
        msg = None
        if edit_message_id:
            await self.edit_message(
                chat_id, int(edit_message_id),
                "⏳ **Loading product details...**"
            )
        else:
            msg = await self.bot.send_message(
                chat_id=chat_id,
                text="⏳ **Fetching product details...**"
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
            
            url = f"https://www.amazon.com/dp/{asin}"
            await page.goto(url, wait_until='domcontentloaded')
            
            # Extract details
            title = await page.locator('#productTitle').inner_text(timeout=3000) or "N/A"
            title = title.strip()
            
            # Price
            price = "N/A"
            try:
                price = await page.locator('.a-price.a-text-price.a-size-medium.apexPriceToPay .a-offscreen').inner_text(timeout=2000)
            except:
                try:
                    price = await page.locator('.a-price .a-offscreen').first.inner_text(timeout=2000)
                except:
                    price = "Price not available"
            
            # Rating
            rating = "No rating"
            try:
                rating = await page.locator('span.a-icon-alt').first.inner_text(timeout=2000)
                rating = rating.split()[0]
            except:
                pass
            
            # Availability
            try:
                availability = await page.locator('#availability span').inner_text(timeout=2000)
                availability = availability.strip()
            except:
                availability = "Unknown"
            
            # Features
            features = []
            try:
                feature_items = await page.locator('#feature-bullets ul li span').all()
                for feature in feature_items[:5]:
                    text = await feature.inner_text(timeout=500)
                    if text.strip():
                        features.append(f"• {text.strip()}")
            except:
                features = ["No features listed"]
            
            # Prime
            is_prime = await page.locator('#primePopoverFeatures').count() > 0
            
            await browser.close()
            
            # Format message
            prime_status = "✅ Prime eligible" if is_prime else "❌ Not Prime"
            
            message = f"""
📦 **Product Details**

**{title}**

💰 **Price:** {price}
⭐ **Rating:** {rating}
📦 **Availability:** {availability}
{prime_status}

**Features:**
{'\n'.join(features)}

🆔 **ASIN:** `{asin}`

🔗 [View on Amazon]({url})
"""
            
            # Buttons
            buttons = [[
                InlineKeyboardButton(text="🔄 Refresh", callback_data=f"details:{asin}"),
                InlineKeyboardButton(text="🏠 Search More", callback_data="search_again")
            ]]
            
            # Edit or send message
            if edit_message_id:
                await self.edit_message(
                    chat_id, int(edit_message_id),
                    message,
                    buttons=buttons
                )
            elif msg:
                await self.edit_message(
                    chat_id, msg.message_id,
                    message,
                    buttons=buttons
                )
            else:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(buttons)
                )

async def main():
    if len(sys.argv) < 3:
        print("Usage: python product_scraper.py <asin> <chat_id> [edit_message_id]")
        sys.exit(1)
    
    asin = sys.argv[1]
    chat_id = int(sys.argv[2])
    edit_message_id = sys.argv[3] if len(sys.argv) > 3 else None
    
    scraper = AmazonProductScraper(os.getenv('TELEGRAM_BOT_TOKEN'))
    await scraper.scrape_product(asin, chat_id, edit_message_id)

if __name__ == "__main__":
    asyncio.run(main())