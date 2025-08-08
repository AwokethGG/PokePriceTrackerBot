import os
import discord
import aiohttp
import asyncio
import logging
from discord.ext import commands
from datetime import datetime, timezone
from statistics import mean
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
EBAY_CLIENT_ID = os.getenv("EBAY_CLIENT_ID")
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET")
PRICE_CHECK_CHANNEL_ID = os.getenv("PRICE_CHECK_CHANNEL_ID")

if not TOKEN or not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
    raise ValueError("Missing required environment variables: DISCORD_BOT_TOKEN, EBAY_CLIENT_ID, EBAY_CLIENT_SECRET")

PRICE_CHECK_CHANNEL_ID = int(PRICE_CHECK_CHANNEL_ID) if PRICE_CHECK_CHANNEL_ID else None

description = "Pokémon Card Price Checker"
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", description=description, intents=intents)

# eBay Browse API endpoints (working APIs)
EBAY_OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_BROWSE_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"

async def get_ebay_token():
    """Get OAuth token for eBay Browse API"""
    try:
        async with aiohttp.ClientSession() as session:
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            data = {
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope"
            }
            auth = aiohttp.BasicAuth(EBAY_CLIENT_ID, EBAY_CLIENT_SECRET)
            
            async with session.post(EBAY_OAUTH_URL, headers=headers, data=data, auth=auth, timeout=10) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"OAuth error ({resp.status}): {text}")
                    return None
                
                resp_json = await resp.json()
                return resp_json.get("access_token")
    except Exception as e:
        logger.error(f"Error getting eBay token: {e}")
        return None

def build_query(card_name, condition):
    """Build search query for different card conditions"""
    card_name = card_name.replace('"', '').strip()
    
    if condition == "raw":
        return f"{card_name} -psa -cgc -bgs -beckett -graded -authenticated"
    else:
        return f"{card_name} {condition}"

async def fetch_browse_items(session, token, query, max_entries=10):
    """Fetch items from eBay Browse API (active listings)"""
    try:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        
        params = {
            "q": query,
            "filter": "categoryIds:{183454},conditionIds:{3000|4000|5000|6000}",  # Pokemon cards, various conditions
            "limit": str(max_entries),
            "fieldgroups": "ASPECT_REFINEMENTS,DETAILED",
            "sort": "newlyListed"  # Show newest listings first
        }
        
        logger.info(f"Searching eBay Browse API for: {query}")
        
        async with session.get(EBAY_BROWSE_URL, headers=headers, params=params, timeout=15) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error(f"Browse API error ({resp.status}): {text}")
                return []
            
            data = await resp.json()
            return parse_browse_response(data.get("itemSummaries", []))
            
    except Exception as e:
        logger.error(f"Error fetching Browse API data: {e}")
        return []

def parse_browse_response(items):
    """Parse eBay Browse API response"""
    try:
        parsed_items = []
        
        for item in items:
            try:
                title = item.get("title", "No Title")
                url = item.get("itemWebUrl", "")
                
                price_info = item.get("price", {})
                if not price_info or "value" not in price_info:
                    continue
                
                price = float(price_info["value"])
                currency = price_info.get("currency", "USD")
                
                # Get image
                image_info = item.get("image", {})
                image = image_info.get("imageUrl", "") if image_info else ""
                
                # Only include items with reasonable prices
                if 0.50 <= price <= 10000:
                    parsed_items.append({
                        "title": title,
                        "url": url,
                        "price": price,
                        "currency": currency,
                        "image": image
                    })
                    
            except (ValueError, TypeError, KeyError) as e:
                logger.warning(f"Error parsing item: {e}")
                continue
        
        logger.info(f"Parsed {len(parsed_items)} valid items from Browse API")
        return parsed_items
        
    except Exception as e:
        logger.error(f"Error parsing Browse API response: {e}")
        return []

def filter_items_by_condition(items, condition):
    """Filter items based on condition keywords in title"""
    filtered = []
    condition_lower = condition.lower()
    
    for item in items:
        title_lower = item["title"].lower()
        
        if condition == "raw":
            # Raw cards should NOT have grading keywords
            grading_keywords = ["psa", "cgc", "bgs", "beckett", "graded", "authenticated", "tag", "ace"]
            if not any(keyword in title_lower for keyword in grading_keywords):
                filtered.append(item)
        else:
            # Graded cards should have the specific condition
            if condition_lower in title_lower:
                filtered.append(item)
    
    return filtered[:5]  # Return top 5 results

@bot.event
async def on_ready():
    logger.info(f'{bot.user} has connected to Discord!')
    print(f'Bot is ready! Logged in as {bot.user}')

@bot.command(name='test')
async def simple_test(ctx):
    """Simple test command"""
    await ctx.send("✅ Bot is working! Ready to check card prices.")

@bot.command(name='debug')
async def debug_command(ctx):
    """Debug command to check bot status"""
    try:
        embed = discord.Embed(
            title="🔧 Bot Debug Status",
            color=0x00ff00,
            timestamp=datetime.now(timezone.utc)
        )
        
        # Environment variables check
        embed.add_field(
            name="Environment Variables",
            value=f"Discord Token: {'✅' if TOKEN else '❌'}\n"
                  f"eBay Client ID: {'✅' if EBAY_CLIENT_ID else '❌'}\n"
                  f"eBay Client Secret: {'✅' if EBAY_CLIENT_SECRET else '❌'}\n"
                  f"Channel ID: {'✅' if PRICE_CHECK_CHANNEL_ID else 'Not Set'}",
            inline=False
        )
        
        # Test eBay OAuth and Browse API
        try:
            token = await get_ebay_token()
            if not token:
                api_status = "❌ OAuth authentication failed"
            else:
                # Test browse API with a simple search
                async with aiohttp.ClientSession() as session:
                    test_items = await fetch_browse_items(session, token, "pokemon", 1)
                    if test_items:
                        api_status = f"✅ Browse API working ({len(test_items)} test items)"
                    else:
                        api_status = "⚠️ Browse API connected but no results"
                        
        except Exception as e:
            api_status = f"❌ Error: {type(e).__name__}"
        
        embed.add_field(name="eBay Browse API Status", value=api_status, inline=False)
        
        # Add note about API limitations
        embed.add_field(
            name="ℹ️ Important Note", 
            value="Now using Browse API (active listings) since Finding API was discontinued.\nPrices shown are current asking prices, not sold prices.",
            inline=False
        )
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(f"❌ Debug failed: {str(e)}")
        logger.error(f"Debug command error: {e}")

@bot.command(name='price')
@commands.cooldown(1, 45, commands.BucketType.user)
async def price_check(ctx, *, card_name):
    """Check Pokemon card prices across different conditions"""
    
    # Input validation
    if not card_name or len(card_name.strip()) < 2:
        await ctx.send("❌ Please provide a valid card name!")
        return
    
    if len(card_name) > 100:
        await ctx.send("❌ Card name too long! Please keep it under 100 characters.")
        return
    
    # Channel restriction (if set)
    if PRICE_CHECK_CHANNEL_ID and ctx.channel.id != PRICE_CHECK_CHANNEL_ID:
        await ctx.send(f"❌ Price checks can only be used in <#{PRICE_CHECK_CHANNEL_ID}>")
        return
    
    card_name = card_name.strip()
    
    # Send initial "searching" message
    searching_msg = await ctx.send(f"🔍 Searching current listings for **{card_name.title()}**...")
    
    try:
        # Get OAuth token
        token = await get_ebay_token()
        if not token:
            error_embed = discord.Embed(
                title="❌ Authentication Error",
                description="Could not authenticate with eBay API. Please try again later.",
                color=0xe74c3c
            )
            await searching_msg.edit(content=None, embed=error_embed)
            return
        
        async with aiohttp.ClientSession() as session:
            # Create main embed
            embed = discord.Embed(
                title=f"💰 Current Prices: {card_name.title()}",
                color=0x3498db,
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_footer(text="Data from eBay Active Listings • Current asking prices")
            
            all_data = {}
            conditions = ["raw", "psa 9", "psa 10"]
            
            # Fetch data for each condition
            for i, condition in enumerate(conditions):
                if i > 0:  # Don't delay on first request
                    await asyncio.sleep(1.5)  # Short delay between requests
                    
                query = build_query(card_name, condition)
                items = await fetch_browse_items(session, token, query, 8)
                filtered_items = filter_items_by_condition(items, condition)
                all_data[condition] = filtered_items
            
            # Set thumbnail (priority: raw > psa 10 > psa 9)
            for cond in ["raw", "psa 10", "psa 9"]:
                if all_data.get(cond) and all_data[cond][0].get("image"):
                    embed.set_thumbnail(url=all_data[cond][0]["image"])
                    break
            
            # Calculate averages
            raw_prices = [x['price'] for x in all_data.get('raw', [])]
            psa9_prices = [x['price'] for x in all_data.get('psa 9', [])]
            psa10_prices = [x['price'] for x in all_data.get('psa 10', [])]
            
            # Add average price fields
            if raw_prices:
                avg_raw = mean(raw_prices)
                embed.add_field(
                    name="📊 RAW Average",
                    value=f"**${avg_raw:.2f}**\n({len(raw_prices)} listings)",
                    inline=True
                )
            
            if psa9_prices:
                avg_psa9 = mean(psa9_prices)
                profit9 = (avg_psa9 - mean(raw_prices) - 18) if raw_prices else 0
                profit_text = f"\n💡 Est. profit: ${profit9:.2f}" if raw_prices else ""
                embed.add_field(
                    name="🥈 PSA 9 Average",
                    value=f"**${avg_psa9:.2f}**\n({len(psa9_prices)} listings){profit_text}",
                    inline=True
                )
            
            if psa10_prices:
                avg_psa10 = mean(psa10_prices)
                profit10 = (avg_psa10 - mean(raw_prices) - 18) if raw_prices else 0
                profit_text = f"\n💡 Est. profit: ${profit10:.2f}" if raw_prices else ""
                embed.add_field(
                    name="🥇 PSA 10 Average",
                    value=f"**${avg_psa10:.2f}**\n({len(psa10_prices)} listings){profit_text}",
                    inline=True
                )
            
            # Add individual listings
            has_data = False
            for condition, items in all_data.items():
                if items:
                    has_data = True
                    condition_emoji = {"raw": "🎴", "psa 9": "🥈", "psa 10": "🥇"}
                    
                    # Format listings
                    listings = []
                    for i, item in enumerate(items[:3], 1):
                        title_short = item['title'][:45] + "..." if len(item['title']) > 45 else item['title']
                        listings.append(f"`{i}.` [${item['price']:.2f}]({item['url']}) - {title_short}")
                    
                    embed.add_field(
                        name=f"{condition_emoji.get(condition, '🎴')} Current {condition.upper()} Listings",
                        value="\n".join(listings),
                        inline=False
                    )
            
            if not has_data:
                embed.add_field(
                    name="❌ No Results Found",
                    value=f"No current listings found for **{card_name}**.\nTry:\n• Different spelling\n• Just the Pokemon name\n• Removing set info",
                    inline=False
                )
            
            # Edit the searching message with results
            await searching_msg.edit(content=None, embed=embed)
            
    except Exception as e:
        logger.error(f"Error in price command: {e}")
        error_embed = discord.Embed(
            title="❌ Error",
            description=f"Something went wrong while searching for **{card_name}**.\nPlease try again in a moment.",
            color=0xe74c3c
        )
        await searching_msg.edit(content=None, embed=error_embed)

@price_check.error
async def price_check_error(ctx, error):
    """Handle command errors (like cooldown)"""
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏰ Please wait {error.retry_after:.0f} seconds before using this command again.")
    else:
        logger.error(f"Command error: {error}")
        await ctx.send("❌ An error occurred. Please try again.")

@bot.command(name='info')
async def info_command(ctx):
    """Show bot information and usage"""
    help_embed = discord.Embed(
        title="🎴 Pokemon Card Price Bot",
        description="Get current Pokemon card prices from eBay active listings!",
        color=0xf39c12
    )
    
    help_embed.add_field(
        name="📋 Commands",
        value="`!price <card name>` - Check current card prices\n`!debug` - Check bot status\n`!test` - Simple bot test\n`!info` - Show this message",
        inline=False
    )
    
    help_embed.add_field(
        name="💡 Tips",
        value="• Use simple names (e.g., 'Charizard Base Set')\n• Shows current asking prices (not sold prices)\n• Bot shows RAW, PSA 9, and PSA 10 prices\n• Estimated profits include $18 grading fee",
        inline=False
    )
    
    help_embed.add_field(
        name="⚠️ Important Note",
        value="Due to eBay API changes, we now show **current asking prices** instead of sold prices. This gives you an idea of market value but actual sales may vary.",
        inline=False
    )
    
    await ctx.send(embed=help_embed)

if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")