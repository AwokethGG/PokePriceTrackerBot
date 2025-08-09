import os
import discord
import aiohttp
import asyncio
import logging
from discord.ext import commands
from datetime import datetime, timezone
from statistics import mean
from dotenv import load_dotenv
import xml.etree.ElementTree as ET

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
EBAY_APP_ID = os.getenv("EBAY_APP_ID")  # Using App ID for Finding API
PRICE_CHECK_CHANNEL_ID = os.getenv("PRICE_CHECK_CHANNEL_ID")

if not TOKEN or not EBAY_APP_ID:
    raise ValueError("Missing required environment variables: DISCORD_BOT_TOKEN and EBAY_APP_ID")

PRICE_CHECK_CHANNEL_ID = int(PRICE_CHECK_CHANNEL_ID) if PRICE_CHECK_CHANNEL_ID else None

description = "Pokémon Card Price Checker"
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", description=description, intents=intents)

# eBay Finding API endpoint for ACTIVE listings
EBAY_FINDING_URL = "https://svcs.ebay.com/services/search/FindingService/v1"

def build_query(card_name, condition):
    """Build search query for different card conditions"""
    card_name = card_name.replace('"', '').strip()
    
    if condition == "raw":
        return f'"{card_name}" -psa -cgc -bgs -beckett -graded -authenticated'
    else:
        return f'"{card_name}" "{condition}"'

async def fetch_active_items(session, query, max_entries=10):
    """Fetch active items from eBay Finding API using findItemsAdvanced"""
    try:
        params = {
            'OPERATION-NAME': 'findItemsAdvanced',  # Changed from findCompletedItems
            'SERVICE-VERSION': '1.0.0',
            'SECURITY-APPNAME': EBAY_APP_ID,
            'RESPONSE-DATA-FORMAT': 'XML',
            'REST-PAYLOAD': '',
            'keywords': query,
            'categoryId': '183454',  # Pokemon cards category
            'itemFilter(0).name': 'ListingType',
            'itemFilter(0).value(0)': 'FixedPrice',  # Buy It Now listings
            'itemFilter(0).value(1)': 'Auction',     # Auction listings
            'itemFilter(1).name': 'Condition',
            'itemFilter(1).value(0)': 'New',
            'itemFilter(1).value(1)': 'Used',
            'itemFilter(1).value(2)': 'Unspecified',
            'sortOrder': 'BestMatch',
            'paginationInput.entriesPerPage': str(max_entries)
        }
        
        logger.info(f"Searching eBay for active listings: {query}")
        
        async with session.get(EBAY_FINDING_URL, params=params, timeout=15) as resp:
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
                
                # Try different price fields for active listings
                price_elem = item.find('.//ebay:convertedCurrentPrice', ns)
                if price_elem is None:
                    price_elem = item.find('.//ebay:currentPrice', ns)
                
                if price_elem is None:
                    continue
                
                price = float(price_elem.text)
                currency = price_elem.get('currencyId', 'USD')
                
                # Get image
                image_elem = item.find('.//ebay:galleryURL', ns)
                if image_elem is None:
                    image_elem = item.find('.//ebay:imageURL', ns)
                image = image_elem.text if image_elem is not None else ""
                
                # Get listing type (auction vs buy it now)
                listing_type_elem = item.find('.//ebay:listingType', ns)
                listing_type = listing_type_elem.text if listing_type_elem is not None else "Unknown"
                
                # Only include items with reasonable prices
                if 0.50 <= price <= 10000:
                    items.append({
                        "title": title,
                        "url": url,
                        "price": price,
                        "currency": currency,
                        "image": image,
                        "listing_type": listing_type
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
            title="System Diagnostics",
            description="Bot configuration and API connectivity status",
            color=0x2C2F33,
            timestamp=datetime.now(timezone.utc)
        )
        
        # Environment variables check
        env_status = []
        env_status.append(f"{'🟢' if TOKEN else '🔴'} **Discord Token**")
        env_status.append(f"{'🟢' if EBAY_APP_ID else '🔴'} **eBay App ID**")
        env_status.append(f"{'🟢' if PRICE_CHECK_CHANNEL_ID else '🟡'} **Channel Restriction**")
        
        embed.add_field(
            name="📋 Configuration",
            value="\n".join(env_status),
            inline=True
        )
        
        # Test eBay Finding API with findItemsAdvanced
        try:
            async with aiohttp.ClientSession() as session:
                test_params = {
                    'OPERATION-NAME': 'findItemsAdvanced',
                    'SERVICE-VERSION': '1.0.0',
                    'SECURITY-APPNAME': EBAY_APP_ID,
                    'RESPONSE-DATA-FORMAT': 'XML',
                    'keywords': 'pokemon',
                    'categoryId': '183454',
                    'paginationInput.entriesPerPage': '1'
                }
                
                async with session.get(EBAY_FINDING_URL, params=test_params, timeout=10) as resp:
                    if resp.status == 200:
                        xml_data = await resp.text()
                        # Try to parse to see if we got real data
                        try:
                            root = ET.fromstring(xml_data)
                            ns = {'ebay': 'http://www.ebay.com/marketplace/search/v1/services'}
                            search_result = root.find('.//ebay:searchResult', ns)
                            if search_result is not None:
                                items = search_result.findall('ebay:item', ns)
                                api_status = f"✅ Finding API working ({len(items)} test items)"
                            else:
                                api_status = "⚠️ API connected but no results"
                        except:
                            api_status = "⚠️ API connected but parse error"
                    elif resp.status == 500:
                        api_status = "❌ Rate limited (wait 1 hour)"
                    else:
                        api_status = f"❌ HTTP {resp.status}"
                        
        except asyncio.TimeoutError:
            api_status = "❌ Connection timeout"
        except Exception as e:
            api_status = f"❌ Error: {type(e).__name__}"
        
        embed.add_field(name="🔗 eBay API Status", value=api_status, inline=True)
        
        # Add separator
        embed.add_field(name="\u200b", value="\u200b", inline=False)
        
        embed.add_field(
            name="ℹ️ System Info", 
            value="Using eBay Finding API for active market data",
            inline=False
        )
        
        embed.set_footer(text="PokéBrief • Diagnostic Report", icon_url="https://cdn.discordapp.com/emojis/658538492321595392.png")
        
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
    searching_embed = discord.Embed(
        description=f"🔍 Analyzing market data for **{card_name.title()}**...",
        color=0x99AAB5
    )
    searching_msg = await ctx.send(embed=searching_embed)
    
    try:
        async with aiohttp.ClientSession() as session:
            # Create main embed with professional styling
            embed = discord.Embed(
                title=card_name.title(),
                description="**Current Market Analysis** • Live eBay Listings",
                color=0x1F8B4C,
                timestamp=datetime.now(timezone.utc)
            )
            
            # Set author field for branding
            embed.set_author(
                name="PokéBrief Market Data", 
                icon_url="https://cdn.discordapp.com/emojis/658538492321595392.png"
            )
            
            all_data = {}
            conditions = ["raw", "psa 9", "psa 10"]
            
            # Fetch data for each condition
            for i, condition in enumerate(conditions):
                if i > 0:  # Don't delay on first request
                    await asyncio.sleep(2.0)  # 2 second delay between requests
                    
                query = build_query(card_name, condition)
                items = await fetch_active_items(session, query, 8)
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
            
            # Add price summary section
            price_summary = []
            
            # Add average price fields with better formatting
            if raw_prices:
                avg_raw = mean(raw_prices)
                min_raw = min(raw_prices)
                max_raw = max(raw_prices)
                price_summary.append(f"**Raw Ungraded**\n`${avg_raw:.2f}` avg • `${min_raw:.2f}` - `${max_raw:.2f}`\n*{len(raw_prices)} listings*")
            
            if psa9_prices:
                avg_psa9 = mean(psa9_prices)
                min_psa9 = min(psa9_prices)
                max_psa9 = max(psa9_prices)
                profit9 = (avg_psa9 - mean(raw_prices) - 18) if raw_prices else 0
                profit_color = "🟢" if profit9 > 0 else "🔴"
                price_summary.append(f"**PSA 9**\n`${avg_psa9:.2f}` avg • `${min_psa9:.2f}` - `${max_psa9:.2f}`\n*{len(psa9_prices)} listings*{' • ' + profit_color + f' ${profit9:.2f} profit' if raw_prices else ''}")
            
            if psa10_prices:
                avg_psa10 = mean(psa10_prices)
                min_psa10 = min(psa10_prices)
                max_psa10 = max(psa10_prices)
                profit10 = (avg_psa10 - mean(raw_prices) - 18) if raw_prices else 0
                profit_color = "🟢" if profit10 > 0 else "🔴"
                price_summary.append(f"**PSA 10**\n`${avg_psa10:.2f}` avg • `${min_psa10:.2f}` - `${max_psa10:.2f}`\n*{len(psa10_prices)} listings*{' • ' + profit_color + f' ${profit10:.2f} profit' if raw_prices else ''}")
            
            if price_summary:
                for i, summary in enumerate(price_summary):
                    embed.add_field(
                        name=f"{'🎴' if i == 0 else '🥈' if i == 1 else '🥇'}",
                        value=summary,
                        inline=True
                    )
            
            # Add separator line
            if has_data:
                embed.add_field(name="\u200b", value="─────────────────────", inline=False)
            
            # Add individual listings with cleaner formatting
            listing_sections = []
            for condition, items in all_data.items():
                if items:
                    has_data = True
                    
                    # Format listings with cleaner design
                    listings = []
                    for i, item in enumerate(items[:3], 1):
                        title_short = item['title'][:35] + "..." if len(item['title']) > 35 else item['title']
                        type_indicator = "Auction" if item.get('listing_type') == 'Auction' else "Buy Now"
                        listings.append(f"**${item['price']:.2f}** • {type_indicator}\n[{title_short}]({item['url']})")
                    
                    condition_names = {"raw": "Raw Ungraded", "psa 9": "PSA 9", "psa 10": "PSA 10"}
                    listing_sections.append({
                        "name": condition_names.get(condition, condition.upper()),
                        "value": "\n\n".join(listings)
                    })
            
            # Add listings in a cleaner layout
            for section in listing_sections:
                embed.add_field(
                    name=f"📋 {section['name']} Listings",
                    value=section['value'],
                    inline=len(listing_sections) <= 2  # Inline for 1-2 sections, full width for 3
                )
            
            if not has_data:
                embed.color = 0xE74C3C
                embed.add_field(
                    name="🔍 No Results Found",
                    value="No current listings match your search.\n\n**Try these tips:**\n• Use simpler terms (e.g., `Charizard` instead of full set info)\n• Check spelling\n• Try the English card name",
                    inline=False
                )
            else:
                # Add professional footer
                embed.set_footer(
                    text="PokéBrief • Live market data from eBay • Prices include shipping",
                    icon_url="https://cdn.discordapp.com/emojis/658538492321595392.png"
                )
            
            # Edit the searching message with results
            await searching_msg.edit(content=None, embed=embed)
            
    except Exception as e:
        logger.error(f"Error in price command: {e}")
        error_embed = discord.Embed(
            title="Service Temporarily Unavailable",
            description=f"Unable to retrieve market data for **{card_name}** at this time.\n\nThis may be due to API rate limiting. Please try again in a few minutes.",
            color=0xE74C3C,
            timestamp=datetime.now(timezone.utc)
        )
        error_embed.set_footer(text="PokéBrief • Error Report")
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
        value="• Use simple names (e.g., 'Charizard Base Set')\n• Shows current asking prices from active listings\n• Bot shows RAW, PSA 9, and PSA 10 prices\n• 🔨 = Auction, 💲 = Buy It Now",
        inline=False
    )
    
    help_embed.add_field(
        name="⚠️ Important Note",
        value="Shows **current asking prices** from active listings. These are what sellers are asking, not necessarily what cards are selling for.",
        inline=False
    )
    
    await ctx.send(embed=embed)

if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")