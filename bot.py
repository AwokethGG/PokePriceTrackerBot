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
            'OPERATION-NAME': 'findItemsAdvanced',
            'SERVICE-VERSION': '1.0.0',
            'SECURITY-APPNAME': EBAY_APP_ID,
            'RESPONSE-DATA-FORMAT': 'XML',
            'REST-PAYLOAD': '',
            'keywords': query,
            'categoryId': '183454',  # Pokemon cards category
            'itemFilter(0).name': 'ListingType',
            'itemFilter(0).value(0)': 'FixedPrice',
            'itemFilter(0).value(1)': 'Auction',
            'itemFilter(1).name': 'Condition',
            'itemFilter(1).value(0)': 'New',
            'itemFilter(1).value(1)': 'Used',
            'itemFilter(1).value(2)': 'Unspecified',
            'itemFilter(2).name': 'MinPrice',
            'itemFilter(2).value': '0.50',
            'itemFilter(2).paramName': 'Currency',
            'itemFilter(2).paramValue': 'USD',
            'itemFilter(3).name': 'MaxPrice',
            'itemFilter(3).value': '10000',
            'itemFilter(3).paramName': 'Currency',
            'itemFilter(3).paramValue': 'USD',
            'sortOrder': 'BestMatch',
            'paginationInput.entriesPerPage': str(max_entries)
        }
        
        logger.info(f"Searching eBay for active listings: {query}")
        
        async with session.get(EBAY_FINDING_URL, params=params, timeout=30) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error(f"eBay API error ({resp.status}): {text}")
                return []
            
            xml_data = await resp.text()
            logger.debug(f"eBay response preview: {xml_data[:500]}...")
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
        
        # Check for errors first
        ack = root.find('.//ebay:ack', ns)
        if ack is not None and ack.text != 'Success':
            error_msg = root.find('.//ebay:message', ns)
            error_text = error_msg.text if error_msg is not None else "Unknown error"
            logger.error(f"eBay API error: {error_text}")
            return []
        
        items = []
        search_result = root.find('.//ebay:searchResult', ns)
        
        if search_result is None:
            logger.warning("No search results found in XML")
            return []
        
        # Check if there are any items
        count_elem = search_result.get('count', '0')
        if count_elem == '0':
            logger.info("No items found for search")
            return []
        
        for item in search_result.findall('ebay:item', ns):
            try:
                title_elem = item.find('ebay:title', ns)
                title = title_elem.text if title_elem is not None else "No Title"
                
                url_elem = item.find('ebay:viewItemURL', ns)
                url = url_elem.text if url_elem is not None else ""
                
                # Try different price fields for active listings
                price_elem = item.find('.//ebay:convertedCurrentPrice', ns)
                if price_elem is None:
                    price_elem = item.find('.//ebay:currentPrice', ns)
                if price_elem is None:
                    # For auctions, might need to check startPrice
                    price_elem = item.find('.//ebay:startPrice', ns)
                
                if price_elem is None:
                    logger.warning(f"No price found for item: {title}")
                    continue
                
                try:
                    price = float(price_elem.text)
                except (ValueError, TypeError):
                    logger.warning(f"Invalid price format: {price_elem.text}")
                    continue
                
                currency = price_elem.get('currencyId', 'USD')
                
                # Get image
                image_elem = item.find('.//ebay:galleryURL', ns)
                if image_elem is None:
                    image_elem = item.find('.//ebay:imageURL', ns)
                image = image_elem.text if image_elem is not None else ""
                
                # Get listing type
                listing_type_elem = item.find('.//ebay:listingType', ns)
                listing_type = listing_type_elem.text if listing_type_elem is not None else "Unknown"
                
                # Get shipping cost if available
                shipping_elem = item.find('.//ebay:shippingServiceCost', ns)
                shipping_cost = 0
                if shipping_elem is not None:
                    try:
                        shipping_cost = float(shipping_elem.text)
                    except (ValueError, TypeError):
                        shipping_cost = 0
                
                total_price = price + shipping_cost
                
                # Only include items with reasonable prices
                if 0.50 <= total_price <= 10000:
                    items.append({
                        "title": title,
                        "url": url,
                        "price": total_price,
                        "base_price": price,
                        "shipping": shipping_cost,
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
        logger.debug(f"Problematic XML: {xml_data[:1000]}...")
        return []

def filter_items_by_condition(items, condition):
    """Filter items based on condition keywords in title"""
    filtered = []
    condition_lower = condition.lower()
    
    for item in items:
        title_lower = item["title"].lower()
        
        if condition == "raw":
            # Raw cards should NOT have grading keywords
            grading_keywords = ["psa", "cgc", "bgs", "beckett", "graded", "authenticated", "gem mint"]
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
        
        # Test eBay Finding API
        try:
            async with aiohttp.ClientSession() as session:
                test_params = {
                    'OPERATION-NAME': 'findItemsAdvanced',
                    'SERVICE-VERSION': '1.0.0',
                    'SECURITY-APPNAME': EBAY_APP_ID,
                    'RESPONSE-DATA-FORMAT': 'XML',
                    'keywords': 'pokemon charizard',
                    'categoryId': '183454',
                    'paginationInput.entriesPerPage': '5'
                }
                
                async with session.get(EBAY_FINDING_URL, params=test_params, timeout=15) as resp:
                    if resp.status == 200:
                        xml_data = await resp.text()
                        logger.debug(f"Test API response preview: {xml_data[:300]}...")
                        
                        # Try to parse to see if we got real data
                        try:
                            root = ET.fromstring(xml_data)
                            ns = {'ebay': 'http://www.ebay.com/marketplace/search/v1/services'}
                            
                            # Check for errors
                            ack = root.find('.//ebay:ack', ns)
                            if ack is not None and ack.text != 'Success':
                                error_msg = root.find('.//ebay:message', ns)
                                error_text = error_msg.text if error_msg is not None else "Unknown error"
                                api_status = f"❌ API Error: {error_text}"
                            else:
                                search_result = root.find('.//ebay:searchResult', ns)
                                if search_result is not None:
                                    count = search_result.get('count', '0')
                                    api_status = f"✅ Finding API working ({count} test items found)"
                                else:
                                    api_status = "⚠️ API connected but no search results structure"
                        except Exception as parse_error:
                            api_status = f"⚠️ API connected but parse error: {parse_error}"
                    elif resp.status == 500:
                        api_status = "❌ Server error (possible rate limit)"
                    elif resp.status == 403:
                        api_status = "❌ Access denied - check API key"
                    else:
                        text = await resp.text()
                        api_status = f"❌ HTTP {resp.status}: {text[:100]}"
                        
        except asyncio.TimeoutError:
            api_status = "❌ Connection timeout"
        except Exception as e:
            api_status = f"❌ Error: {type(e).__name__}: {str(e)[:50]}"
        
        embed.add_field(name="🔗 eBay API Status", value=api_status, inline=True)
        
        # Add separator
        embed.add_field(name="\u200b", value="\u200b", inline=False)
        
        embed.add_field(
            name="ℹ️ System Info", 
            value=f"Using eBay Finding API for active market data\nApp ID: {EBAY_APP_ID[:10]}...",
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
            has_data = False
            
            # Fetch data for each condition
            for i, condition in enumerate(conditions):
                if i > 0:  # Don't delay on first request
                    await asyncio.sleep(3.0)  # 3 second delay between requests
                    
                query = build_query(card_name, condition)
                items = await fetch_active_items(session, query, 8)
                filtered_items = filter_items_by_condition(items, condition)
                all_data[condition] = filtered_items
                
                if filtered_items:
                    has_data = True
            
            # Set thumbnail (priority: raw > psa 10 > psa 9)
            for cond in ["raw", "psa 10", "psa 9"]:
                if all_data.get(cond) and all_data[cond][0].get("image"):
                    embed.set_thumbnail(url=all_data[cond][0]["image"])
                    break
            
            # Calculate averages and add price summary
            if has_data:
                raw_prices = [x['price'] for x in all_data.get('raw', [])]
                psa9_prices = [x['price'] for x in all_data.get('psa 9', [])]
                psa10_prices = [x['price'] for x in all_data.get('psa 10', [])]
                
                # Add average price fields with better formatting
                if raw_prices:
                    avg_raw = mean(raw_prices)
                    min_raw = min(raw_prices)
                    max_raw = max(raw_prices)
                    embed.add_field(
                        name="🎴 Raw Ungraded",
                        value=f"`${avg_raw:.2f}` avg • `${min_raw:.2f}` - `${max_raw:.2f}`\n*{len(raw_prices)} listings*",
                        inline=True
                    )
                
                if psa9_prices:
                    avg_psa9 = mean(psa9_prices)
                    min_psa9 = min(psa9_prices)
                    max_psa9 = max(psa9_prices)
                    profit9 = (avg_psa9 - mean(raw_prices) - 18) if raw_prices else 0
                    profit_color = "🟢" if profit9 > 0 else "🔴"
                    embed.add_field(
                        name="🥈 PSA 9",
                        value=f"`${avg_psa9:.2f}` avg • `${min_psa9:.2f}` - `${max_psa9:.2f}`\n*{len(psa9_prices)} listings*{' • ' + profit_color + f' ${profit9:.2f} profit' if raw_prices else ''}",
                        inline=True
                    )
                
                if psa10_prices:
                    avg_psa10 = mean(psa10_prices)
                    min_psa10 = min(psa10_prices)
                    max_psa10 = max(psa10_prices)
                    profit10 = (avg_psa10 - mean(raw_prices) - 18) if raw_prices else 0
                    profit_color = "🟢" if profit10 > 0 else "🔴"
                    embed.add_field(
                        name="🥇 PSA 10",
                        value=f"`${avg_psa10:.2f}` avg • `${min_psa10:.2f}` - `${max_psa10:.2f}`\n*{len(psa10_prices)} listings*{' • ' + profit_color + f' ${profit10:.2f} profit' if raw_prices else ''}",
                        inline=True
                    )
                
                # Add separator line
                embed.add_field(name="\u200b", value="─────────────────────", inline=False)
                
                # Add individual listings with cleaner formatting
                for condition, items in all_data.items():
                    if items:
                        listings = []
                        for item in items[:3]:
                            title_short = item['title'][:35] + "..." if len(item['title']) > 35 else item['title']
                            type_indicator = "🔨" if item.get('listing_type') == 'Auction' else "💲"
                            price_display = f"${item['price']:.2f}"
                            if item.get('shipping', 0) > 0:
                                price_display += f" (+${item['shipping']:.2f} ship)"
                            listings.append(f"{type_indicator} **{price_display}**\n[{title_short}]({item['url']})")
                        
                        condition_names = {"raw": "Raw Ungraded", "psa 9": "PSA 9", "psa 10": "PSA 10"}
                        embed.add_field(
                            name=f"📋 {condition_names.get(condition, condition.upper())} Listings",
                            value="\n\n".join(listings),
                            inline=len(all_data) <= 2
                        )
            
            if not has_data:
                embed.color = 0xE74C3C
                embed.add_field(
                    name="🔍 No Results Found",
                    value="No current listings match your search.\n\n**Try these tips:**\n• Use simpler terms (e.g., `Charizard` instead of full set info)\n• Check spelling\n• Try the English card name\n• Remove extra words like 'holo' or 'rare'",
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
    embed = discord.Embed(
        title="🎴 Pokemon Card Price Bot",
        description="Get current Pokemon card prices from eBay active listings!",
        color=0xf39c12
    )
    
    embed.add_field(
        name="📋 Commands",
        value="`!price <card name>` - Check current card prices\n`!debug` - Check bot status\n`!test` - Simple bot test\n`!info` - Show this message",
        inline=False
    )
    
    embed.add_field(
        name="💡 Tips",
        value="• Use simple names (e.g., 'Charizard Base Set')\n• Shows current asking prices from active listings\n• Bot shows RAW, PSA 9, and PSA 10 prices\n• 🔨 = Auction, 💲 = Buy It Now",
        inline=False
    )
    
    embed.add_field(
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