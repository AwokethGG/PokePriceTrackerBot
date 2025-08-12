import os
import discord
import aiohttp
import asyncio
import logging
import json
import base64
from discord.ext import commands
from datetime import datetime, timezone, timedelta
from statistics import mean
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Required environment variables
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
EBAY_CLIENT_ID = os.getenv("EBAY_CLIENT_ID")
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET")
EBAY_ENVIRONMENT = os.getenv("EBAY_ENVIRONMENT", "PRODUCTION").upper()

# Optional
PRICE_CHECK_CHANNEL_ID = os.getenv("PRICE_CHECK_CHANNEL_ID")
if PRICE_CHECK_CHANNEL_ID:
    PRICE_CHECK_CHANNEL_ID = int(PRICE_CHECK_CHANNEL_ID)

# Validate required variables
if not all([TOKEN, EBAY_CLIENT_ID, EBAY_CLIENT_SECRET]):
    raise ValueError("Missing required environment variables!")

# eBay API URLs based on environment
if EBAY_ENVIRONMENT == "SANDBOX":
    EBAY_OAUTH_URL = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
    EBAY_BROWSE_URL = "https://api.sandbox.ebay.com/buy/browse/v1/item_summary/search"
    print("🧪 Running in SANDBOX mode")
else:
    EBAY_OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
    EBAY_BROWSE_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    print("🚀 Running in PRODUCTION mode")

# Discord bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Global OAuth token storage
oauth_token = None
token_expires_at = None

async def get_oauth_token():
    """Get OAuth 2.0 token from eBay"""
    global oauth_token, token_expires_at
    
    # Return existing token if still valid
    if oauth_token and token_expires_at and datetime.now() < token_expires_at:
        return oauth_token
    
    try:
        # Prepare authentication
        credentials = f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Authorization': f'Basic {encoded_credentials}'
        }
        
        data = 'grant_type=client_credentials&scope=https%3A%2F%2Fapi.ebay.com%2Foauth%2Fapi_scope'
        
        async with aiohttp.ClientSession() as session:
            async with session.post(EBAY_OAUTH_URL, headers=headers, data=data, timeout=10) as response:
                if response.status == 200:
                    token_data = await response.json()
                    oauth_token = token_data['access_token']
                    expires_in = token_data.get('expires_in', 7200)
                    token_expires_at = datetime.now() + timedelta(seconds=expires_in - 300)  # 5 min buffer
                    logger.info(f"✅ OAuth token obtained for {EBAY_ENVIRONMENT}")
                    return oauth_token
                else:
                    error_text = await response.text()
                    logger.error(f"❌ OAuth failed ({response.status}): {error_text}")
                    return None
                    
    except Exception as e:
        logger.error(f"❌ OAuth error: {e}")
        return None

async def search_ebay(query, max_items=10):
    """Search eBay for items"""
    token = await get_oauth_token()
    if not token:
        return []
    
    headers = {
        'Authorization': f'Bearer {token}',
        'X-EBAY-C-MARKETPLACE-ID': 'EBAY_US'
    }
    
    # Basic search parameters
    params = {
        'q': query,
        'limit': str(max_items),
        'sort': 'newlyListed'
    }
    
    # Add category for Pokemon cards (Production only)
    if EBAY_ENVIRONMENT == "PRODUCTION":
        params['category_ids'] = '183454'  # Pokemon Trading Cards category
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(EBAY_BROWSE_URL, headers=headers, params=params, timeout=15) as response:
                if response.status == 200:
                    data = await response.json()
                    return parse_search_results(data)
                else:
                    error_text = await response.text()
                    logger.error(f"❌ Search failed ({response.status}): {error_text[:200]}")
                    return []
                    
    except Exception as e:
        logger.error(f"❌ Search error: {e}")
        return []

def parse_search_results(data):
    """Parse eBay search results"""
    items = []
    
    for item in data.get('itemSummaries', []):
        try:
            # Get basic info
            title = item.get('title', 'No Title')
            url = item.get('itemWebUrl', '')
            
            # Get price
            price_info = item.get('price', {})
            if not price_info:
                continue
                
            price = float(price_info.get('value', 0))
            currency = price_info.get('currency', 'USD')
            
            # Get shipping cost
            shipping_cost = 0
            shipping_options = item.get('shippingOptions', [])
            if shipping_options:
                shipping_info = shipping_options[0].get('shippingCost', {})
                if shipping_info:
                    shipping_cost = float(shipping_info.get('value', 0))
            
            total_price = price + shipping_cost
            
            # Get image
            image = item.get('image', {}).get('imageUrl', '')
            
            # Get condition and buying options
            condition = item.get('condition', 'Unknown')
            buying_options = item.get('buyingOptions', [])
            is_auction = 'AUCTION' in buying_options
            
            # Filter reasonable prices
            if 0.50 <= total_price <= 10000:
                items.append({
                    'title': title,
                    'url': url,
                    'price': total_price,
                    'base_price': price,
                    'shipping': shipping_cost,
                    'currency': currency,
                    'image': image,
                    'condition': condition,
                    'is_auction': is_auction
                })
                
        except (ValueError, TypeError, KeyError) as e:
            continue  # Skip invalid items
    
    logger.info(f"📊 Parsed {len(items)} valid items")
    return items

def filter_by_condition(items, condition_type):
    """Filter items by condition type"""
    filtered = []
    condition_lower = condition_type.lower()
    
    for item in items:
        title_lower = item['title'].lower()
        
        if condition_type == "raw":
            # Raw cards - exclude grading terms
            grading_terms = ['psa', 'cgc', 'bgs', 'beckett', 'graded', 'grade']
            if not any(term in title_lower for term in grading_terms):
                filtered.append(item)
        else:
            # Graded cards - must contain the grade
            if condition_lower in title_lower:
                filtered.append(item)
    
    return filtered[:5]  # Return top 5

@bot.event
async def on_ready():
    print(f'✅ {bot.user} is online!')
    print(f'📍 Environment: {EBAY_ENVIRONMENT}')
    
    # Test OAuth on startup
    token = await get_oauth_token()
    if token:
        print('✅ eBay API connection successful')
    else:
        print('❌ eBay API connection failed')

@bot.command(name='test')
async def test_command(ctx):
    """Simple test command"""
    embed = discord.Embed(
        title="🎴 Bot Status",
        description=f"✅ Bot is online!\n📍 Environment: **{EBAY_ENVIRONMENT}**",
        color=0x00ff00
    )
    await ctx.send(embed=embed)

@bot.command(name='price')
async def price_command(ctx, *, card_name):
    """Get Pokemon card prices"""
    
    # Input validation
    if not card_name or len(card_name.strip()) < 2:
        await ctx.send("❌ Please provide a card name!")
        return
    
    # Channel restriction
    if PRICE_CHECK_CHANNEL_ID and ctx.channel.id != PRICE_CHECK_CHANNEL_ID:
        await ctx.send(f"❌ Price checks only allowed in <#{PRICE_CHECK_CHANNEL_ID}>")
        return
    
    card_name = card_name.strip()
    
    # Initial searching message
    embed = discord.Embed(
        description=f"🔍 Searching for **{card_name}**...",
        color=0xffaa00
    )
    message = await ctx.send(embed=embed)
    
    try:
        # Search for different conditions
        conditions = {
            'raw': f'{card_name} -psa -cgc -bgs -graded',
            'psa_9': f'{card_name} psa 9',
            'psa_10': f'{card_name} psa 10'
        }
        
        all_results = {}
        
        for condition, query in conditions.items():
            items = await search_ebay(query, 15)
            filtered = filter_by_condition(items, condition.replace('_', ' ').replace('psa ', 'psa '))
            all_results[condition] = filtered
            await asyncio.sleep(1)  # Rate limiting
        
        # Create results embed
        embed = discord.Embed(
            title=f"💰 {card_name.title()}",
            description="**Current eBay Prices**",
            color=0x1f8b4c,
            timestamp=datetime.now(timezone.utc)
        )
        
        # Set thumbnail from first available image
        for condition_items in all_results.values():
            if condition_items and condition_items[0].get('image'):
                embed.set_thumbnail(url=condition_items[0]['image'])
                break
        
        # Add price summaries
        has_data = False
        
        # Raw cards
        raw_items = all_results.get('raw', [])
        if raw_items:
            has_data = True
            prices = [item['price'] for item in raw_items]
            avg_price = mean(prices)
            min_price = min(prices)
            max_price = max(prices)
            
            embed.add_field(
                name="🎴 Raw/Ungraded",
                value=f"**${avg_price:.2f}** avg\n${min_price:.2f} - ${max_price:.2f}\n*{len(prices)} listings*",
                inline=True
            )
        
        # PSA 9
        psa9_items = all_results.get('psa_9', [])
        if psa9_items:
            has_data = True
            prices = [item['price'] for item in psa9_items]
            avg_price = mean(prices)
            min_price = min(prices)
            max_price = max(prices)
            
            embed.add_field(
                name="🥈 PSA 9",
                value=f"**${avg_price:.2f}** avg\n${min_price:.2f} - ${max_price:.2f}\n*{len(prices)} listings*",
                inline=True
            )
        
        # PSA 10
        psa10_items = all_results.get('psa_10', [])
        if psa10_items:
            has_data = True
            prices = [item['price'] for item in psa10_items]
            avg_price = mean(prices)
            min_price = min(prices)
            max_price = max(prices)
            
            embed.add_field(
                name="🥇 PSA 10",
                value=f"**${avg_price:.2f}** avg\n${min_price:.2f} - ${max_price:.2f}\n*{len(prices)} listings*",
                inline=True
            )
        
        if not has_data:
            embed.description = "❌ No listings found for this card"
            embed.color = 0xff0000
            
            if EBAY_ENVIRONMENT == "SANDBOX":
                embed.add_field(
                    name="💡 Note",
                    value="Running in Sandbox mode with limited test data",
                    inline=False
                )
        else:
            # Add some individual listings
            embed.add_field(name="\u200b", value="**Recent Listings:**", inline=False)
            
            for condition, items in all_results.items():
                if items:
                    condition_name = condition.replace('_', ' ').replace('psa', 'PSA').title()
                    if condition == 'raw':
                        condition_name = 'Raw'
                    
                    listings = []
                    for item in items[:2]:  # Show top 2 per condition
                        price_str = f"${item['price']:.2f}"
                        if item['shipping'] > 0:
                            price_str += f" (+${item['shipping']:.2f})"
                        
                        title_short = item['title'][:40] + "..." if len(item['title']) > 40 else item['title']
                        auction_indicator = "🔨" if item['is_auction'] else "💰"
                        
                        listings.append(f"{auction_indicator} **{price_str}** - [{title_short}]({item['url']})")
                    
                    if listings:
                        embed.add_field(
                            name=f"📋 {condition_name}",
                            value="\n".join(listings),
                            inline=False
                        )
        
        # Footer
        footer_text = f"eBay {EBAY_ENVIRONMENT.title()} • Prices include shipping"
        if EBAY_ENVIRONMENT == "SANDBOX":
            footer_text += " • Test Data Only"
        
        embed.set_footer(text=footer_text)
        
        await message.edit(embed=embed)
        
    except Exception as e:
        logger.error(f"❌ Price command error: {e}")
        
        error_embed = discord.Embed(
            title="❌ Error",
            description=f"Failed to get prices for **{card_name}**\n\nTry again in a few moments.",
            color=0xff0000
        )
        await message.edit(embed=error_embed)

@bot.command(name='debug')
async def debug_command(ctx):
    """Show bot debug information"""
    embed = discord.Embed(
        title="🔧 Debug Information",
        color=0x00aaff,
        timestamp=datetime.now(timezone.utc)
    )
    
    # Environment info
    embed.add_field(
        name="🌐 Environment",
        value=f"**Mode**: {EBAY_ENVIRONMENT}\n**OAuth URL**: `{EBAY_OAUTH_URL}`\n**Browse URL**: `{EBAY_BROWSE_URL}`",
        inline=False
    )
    
    # Test OAuth
    token = await get_oauth_token()
    if token:
        token_preview = f"{token[:20]}..."
        oauth_status = f"✅ **Active**\nToken: `{token_preview}`"
    else:
        oauth_status = "❌ **Failed**"
    
    embed.add_field(
        name="🔑 OAuth Token",
        value=oauth_status,
        inline=False
    )
    
    # Test search
    try:
        test_items = await search_ebay("pokemon charizard", 3)
        search_status = f"✅ **Working** ({len(test_items)} items found)"
    except Exception as e:
        search_status = f"❌ **Error**: {str(e)[:100]}"
    
    embed.add_field(
        name="🔍 Search API",
        value=search_status,
        inline=False
    )
    
    await ctx.send(embed=embed)

@bot.command(name='info')
async def info_command(ctx):
    """Show help information"""
    embed = discord.Embed(
        title="🎴 Pokemon Card Price Bot",
        description="Get current Pokemon card prices from eBay",
        color=0x0099ff
    )
    
    embed.add_field(
        name="📋 Commands",
        value="`!price <card name>` - Check card prices\n`!test` - Test bot status\n`!debug` - Show debug info\n`!info` - Show this help",
        inline=False
    )
    
    embed.add_field(
        name="💡 Usage Tips",
        value="• Use simple card names (e.g. 'Charizard Base Set')\n• Bot shows Raw, PSA 9, and PSA 10 prices\n• 🔨 = Auction, 💰 = Buy It Now",
        inline=False
    )
    
    if EBAY_ENVIRONMENT == "SANDBOX":
        embed.add_field(
            name="🧪 Sandbox Mode",
            value="Currently running with test data only",
            inline=False
        )
    
    await ctx.send(embed=embed)

# Error handling
@price_command.error
async def price_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Please provide a card name! Example: `!price charizard`")
    else:
        logger.error(f"Price command error: {error}")
        await ctx.send("❌ An error occurred. Please try again.")

if __name__ == "__main__":
    try:
        print("🚀 Starting Pokemon Card Price Bot...")
        bot.run(TOKEN)
    except Exception as e:
        print(f"❌ Failed to start bot: {e}")