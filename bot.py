import os
import discord
import aiohttp
import asyncio
import logging
from discord.ext import commands
from datetime import datetime
from statistics import mean
from dotenv import load_dotenv
import xml.etree.ElementTree as ET

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
EBAY_APP_ID = os.getenv("EBAY_APP_ID")  # Changed from CLIENT_ID
PRICE_CHECK_CHANNEL_ID = os.getenv("PRICE_CHECK_CHANNEL_ID")

if not TOKEN or not EBAY_APP_ID:
    raise ValueError("Missing required environment variables: DISCORD_BOT_TOKEN and EBAY_APP_ID")

PRICE_CHECK_CHANNEL_ID = int(PRICE_CHECK_CHANNEL_ID) if PRICE_CHECK_CHANNEL_ID else None

description = "Pokémon Card Price Checker"
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", description=description, intents=intents)

# eBay Finding API endpoint for SOLD listings
EBAY_FINDING_URL = "https://svcs.ebay.com/services/search/FindingService/v1"

def build_query(card_name, condition):
    """Build search query for different card conditions"""
    card_name = card_name.replace('"', '').strip()
    
    if condition == "raw":
        return f'"{card_name}" -psa -cgc -bgs -beckett -graded -authenticated'
    else:
        return f'"{card_name}" "{condition}"'

async def fetch_sold_items(session, query, max_entries=10):
    """Fetch sold items from eBay Finding API"""
    try:
        params = {
            'OPERATION-NAME': 'findCompletedItems',
            'SERVICE-VERSION': '1.0.0',
            'SECURITY-APPNAME': EBAY_APP_ID,
            'RESPONSE-DATA-FORMAT': 'XML',
            'REST-PAYLOAD': '',
            'keywords': query,
            'categoryId': '183454',  # Pokemon cards category
            'itemFilter(0).name': 'SoldItemsOnly',
            'itemFilter(0).value': 'true',
            'itemFilter(1).name': 'Condition',
            'itemFilter(1).value': 'Used',
            'sortOrder': 'EndTimeSoonest',
            'paginationInput.entriesPerPage': str(max_entries)
        }
        
        logger.info(f"Searching eBay for: {query}")
        
        async with session.get(EBAY_FINDING_URL, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error(f"eBay API error ({resp.status}): {text}")
                return []
            
            xml_data = await resp.text()
            return parse_ebay_response(xml_data)
            
    except Exception as e:
        logger.error(f"Error fetching eBay data: {e}")
        return []

def parse_ebay_response(xml_data):
    """Parse eBay XML response and extract item data"""
    try:
        root = ET.fromstring(xml_data)
        
        # Define namespace
        ns = {'ebay': 'http://www.ebay.com/marketplace/search/v1/services'}
        
        items = []
        search_result = root.find('.//ebay:searchResult', ns)
        
        if search_result is None:
            logger.warning("No search results found in XML")
            return []
        
        for item in search_result.findall('ebay:item', ns):
            try:
                title = item.find('ebay:title', ns)
                title = title.text if title is not None else "No Title"
                
                url = item.find('ebay:viewItemURL', ns)
                url = url.text if url is not None else ""
                
                price_elem = item.find('.//ebay:convertedCurrentPrice', ns)
                if price_elem is None:
                    continue
                
                price = float(price_elem.text)
                currency = price_elem.get('currencyId', 'USD')
                
                # Get image
                image_elem = item.find('.//ebay:imageURL', ns)
                image = image_elem.text if image_elem is not None else ""
                
                # Only include items with reasonable prices
                if 0.50 <= price <= 5000:
                    items.append({
                        "title": title,
                        "url": url,
                        "price": price,
                        "currency": currency,
                        "image": image
                    })
                    
            except (ValueError, TypeError, AttributeError) as e:
                logger.warning(f"Error parsing item: {e}")
                continue
        
        logger.info(f"Parsed {len(items)} valid items from eBay response")
        return items
        
    except ET.ParseError as e:
        logger.error(f"XML parsing error: {e}")
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
    
    return filtered[:3]  # Return top 3 results

@bot.event
async def on_ready():
    logger.info(f'{bot.user} has connected to Discord!')
    print(f'Bot is ready! Logged in as {bot.user}')

@bot.command(name='debug')
async def debug_command(ctx):
    """Debug command to check bot status (restrict to bot owner if needed)"""
    status_embed = discord.Embed(
        title="🔧 Bot Debug Status",
        color=0x00ff00,
        timestamp=datetime.utcnow()
    )
    
    # Check environment variables
    status_embed.add_field(
        name="Environment Variables",
        value=f"Discord Token: {'✅' if TOKEN else '❌'}\n"
              f"eBay App ID: {'✅' if EBAY_APP_ID else '❌'}\n"
              f"Channel ID: {'✅' if PRICE_CHECK_CHANNEL_ID else 'Not Set'}",
        inline=False
    )
    
    # Test eBay API
    try:
        async with aiohttp.ClientSession() as session:
            test_items = await fetch_sold_items(session, "pikachu", 1)
            ebay_status = "✅ Connected" if test_items else "⚠️ No results"
    except Exception as e:
        ebay_status = f"❌ Error: {str(e)[:50]}"
    
    status_embed.add_field(name="eBay API Test", value=ebay_status, inline=False)
    
    await ctx.send(embed=status_embed)

@bot.command(name='price')
@commands.cooldown(1, 30, commands.BucketType.user)
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
    searching_msg = await ctx.send(f"🔍 Searching for **{card_name.title()}**...")
    
    try:
        async with aiohttp.ClientSession() as session:
            # Create main embed
            embed = discord.Embed(
                title=f"💰 Price Check: {card_name.title()}",
                color=0x3498db,
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text="Data from eBay Sold Listings • Prices in USD")
            
            all_data = {}
            conditions = ["raw", "psa 9", "psa 10"]
            
            # Fetch data for each condition
            for condition in conditions:
                query = build_query(card_name, condition)
                items = await fetch_sold_items(session, query, 10)
                filtered_items = filter_items_by_condition(items, condition)
                all_data[condition] = filtered_items
                
                # Small delay to be respectful to eBay API
                await asyncio.sleep(0.5)
            
            # Set thumbnail (priority: raw > psa 10 > psa 9)
            for cond in ["raw", "psa 10", "psa 9"]:
                if all_data.get(cond) and all_data[cond][0].get("image"):
                    embed.set_thumbnail(url=all_data[cond][0]["image"])
                    break
            
            # Calculate averages and profits
            raw_prices = [x['price'] for x in all_data.get('raw', [])]
            psa9_prices = [x['price'] for x in all_data.get('psa 9', [])]
            psa10_prices = [x['price'] for x in all_data.get('psa 10', [])]
            
            # Add average price fields
            if raw_prices:
                avg_raw = mean(raw_prices)
                embed.add_field(
                    name="📊 RAW Average",
                    value=f"**${avg_raw:.2f}**\n({len(raw_prices)} sales)",
                    inline=True
                )
            
            if psa9_prices:
                avg_psa9 = mean(psa9_prices)
                profit9 = (avg_psa9 - mean(raw_prices) - 18) if raw_prices else 0
                profit_text = f"\n💡 Est. profit: ${profit9:.2f}" if raw_prices else ""
                embed.add_field(
                    name="🥈 PSA 9 Average",
                    value=f"**${avg_psa9:.2f}**\n({len(psa9_prices)} sales){profit_text}",
                    inline=True
                )
            
            if psa10_prices:
                avg_psa10 = mean(psa10_prices)
                profit10 = (avg_psa10 - mean(raw_prices) - 18) if raw_prices else 0
                profit_text = f"\n💡 Est. profit: ${profit10:.2f}" if raw_prices else ""
                embed.add_field(
                    name="🥇 PSA 10 Average",
                    value=f"**${avg_psa10:.2f}**\n({len(psa10_prices)} sales){profit_text}",
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
                        title_short = item['title'][:50] + "..." if len(item['title']) > 50 else item['title']
                        listings.append(f"`{i}.` [${item['price']:.2f}]({item['url']}) - {title_short}")
                    
                    embed.add_field(
                        name=f"{condition_emoji.get(condition, '🎴')} Recent {condition.upper()} Sales",
                        value="\n".join(listings),
                        inline=False
                    )
            
            if not has_data:
                embed.add_field(
                    name="❌ No Results Found",
                    value=f"No sold listings found for **{card_name}**.\nTry:\n• Different spelling\n• Just the Pokemon name\n• Removing set info",
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

# Custom info command (since help is reserved)
@bot.command(name='info')
async def info_command(ctx):
    """Show bot information and usage"""
    help_embed = discord.Embed(
        title="🎴 Pokemon Card Price Bot",
        description="Get real-time Pokemon card prices from eBay sold listings!",
        color=0xf39c12
    )
    
    help_embed.add_field(
        name="📋 Commands",
        value="`!price <card name>` - Check card prices\n`!debug` - Check bot status\n`!info` - Show this message",
        inline=False
    )
    
    help_embed.add_field(
        name="💡 Tips",
        value="• Use simple names (e.g., 'Charizard Base Set')\n• Bot shows RAW, PSA 9, and PSA 10 prices\n• Estimated profits include $18 grading fee",
        inline=False
    )
    
    await ctx.send(embed=help_embed)

if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")