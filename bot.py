import os
import discord
import aiohttp
import asyncio
import logging
from discord.ext import commands
from datetime import datetime, timezone
from statistics import mean
from dotenv import load_dotenv
import json

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
EBAY_CLIENT_ID = os.getenv("EBAY_CLIENT_ID")  # Now using Client ID for Browse API
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET")  # Client Secret for OAuth
EBAY_ENVIRONMENT = os.getenv("EBAY_ENVIRONMENT", "PRODUCTION")  # SANDBOX or PRODUCTION
PRICE_CHECK_CHANNEL_ID = os.getenv("PRICE_CHECK_CHANNEL_ID")

if not TOKEN or not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
    raise ValueError("Missing required environment variables: DISCORD_BOT_TOKEN, EBAY_CLIENT_ID, and EBAY_CLIENT_SECRET")

PRICE_CHECK_CHANNEL_ID = int(PRICE_CHECK_CHANNEL_ID) if PRICE_CHECK_CHANNEL_ID else None

description = "Pokémon Card Price Checker"
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", description=description, intents=intents)

# eBay Browse API endpoints - environment dependent
if EBAY_ENVIRONMENT.upper() == "SANDBOX":
    EBAY_OAUTH_URL = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
    EBAY_BROWSE_URL = "https://api.sandbox.ebay.com/buy/browse/v1/item_summary/search"
else:
    EBAY_OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
    EBAY_BROWSE_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"

# Global variable to store OAuth token
oauth_token = None
token_expires = None

async def get_oauth_token():
    """Get OAuth token for eBay Browse API"""
    global oauth_token, token_expires
    
    # Check if we have a valid token
    if oauth_token and token_expires and datetime.now() < token_expires:
        return oauth_token
    
    try:
        # Convert credentials to base64 for basic auth
        import base64
        auth_string = base64.b64encode(f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode()).decode()
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Authorization': f'Basic {auth_string}'
        }
        
        # URL encode the scope as required by eBay
        import urllib.parse
        scope_encoded = urllib.parse.quote('https://api.ebay.com/oauth/api_scope')
        
        data = f'grant_type=client_credentials&scope={scope_encoded}'
        
        logger.info(f"Attempting OAuth with Client ID: {EBAY_CLIENT_ID[:8]}...")
        
        async with aiohttp.ClientSession() as session:
            async with session.post(EBAY_OAUTH_URL, headers=headers, data=data, timeout=15) as resp:
                response_text = await resp.text()
                
                if resp.status == 200:
                    try:
                        token_data = json.loads(response_text)
                        oauth_token = token_data['access_token']
                        expires_in = token_data.get('expires_in', 3600)
                        from datetime import timedelta
                        token_expires = datetime.now() + timedelta(seconds=expires_in - 60)
                        logger.info("Successfully obtained OAuth token")
                        return oauth_token
                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid JSON in OAuth response: {e}")
                        return None
                else:
                    logger.error(f"OAuth failed - Status: {resp.status}")
                    logger.error(f"Response: {response_text}")
                    
                    # Try to parse error details
                    try:
                        error_data = json.loads(response_text)
                        error_msg = error_data.get('error_description', error_data.get('error', 'Unknown error'))
                        logger.error(f"OAuth error details: {error_msg}")
                    except:
                        pass
                    
                    return None
                    
    except Exception as e:
        logger.error(f"Exception getting OAuth token: {e}")
        return None

def build_query(card_name, condition):
    """Build search query for different card conditions"""
    card_name = card_name.replace('"', '').strip()
    
    if condition == "raw":
        # For raw cards, exclude grading terms - simplified for sandbox
        return f"{card_name} -psa -cgc -bgs -graded"
    else:
        # For graded cards, include the grade
        return f"{card_name} {condition}"

async def fetch_browse_items(session, query, max_entries=15):
    """Fetch items from eBay Browse API"""
    try:
        token = await get_oauth_token()
        if not token:
            logger.error("No valid OAuth token available")
            return []
        
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'X-EBAY-C-MARKETPLACE-ID': 'EBAY_US'
        }
        
        params = {
            'q': query,
            'limit': str(max_entries),
            'sort': 'newlyListed',  # Sort by newest listings
            'filter': 'buyingOptions:{FIXED_PRICE|AUCTION},price:[0.50..5000]'  # Reduced max price for sandbox
        }
        
        # Add category filter only if not in sandbox (sandbox may have different categories)
        if EBAY_ENVIRONMENT.upper() != "SANDBOX":
            params['category_ids'] = '183454'  # Pokemon cards category
        
        logger.info(f"Searching eBay Browse API: {query}")
        
        async with session.get(EBAY_BROWSE_URL, headers=headers, params=params, timeout=30) as resp:
            if resp.status == 200:
                data = await resp.json()
                return parse_browse_response(data)
            else:
                error_text = await resp.text()
                logger.error(f"eBay Browse API error ({resp.status}): {error_text}")
                return []
                
    except Exception as e:
        logger.error(f"Error fetching eBay Browse data: {e}")
        return []

def parse_browse_response(data):
    """Parse eBay Browse API JSON response"""
    try:
        items = []
        item_summaries = data.get('itemSummaries', [])
        
        if not item_summaries:
            logger.info("No items found in Browse API response")
            return []
        
        for item in item_summaries:
            try:
                title = item.get('title', 'No Title')
                item_web_url = item.get('itemWebUrl', '')
                
                # Get price information
                price_info = item.get('price', {})
                price_value = price_info.get('value')
                currency = price_info.get('currency', 'USD')
                
                if not price_value:
                    continue
                
                try:
                    price = float(price_value)
                except (ValueError, TypeError):
                    continue
                
                # Get shipping cost if available
                shipping_info = item.get('shippingOptions', [])
                shipping_cost = 0
                if shipping_info:
                    shipping_cost_info = shipping_info[0].get('shippingCost', {})
                    if shipping_cost_info:
                        try:
                            shipping_cost = float(shipping_cost_info.get('value', 0))
                        except (ValueError, TypeError):
                            shipping_cost = 0
                
                total_price = price + shipping_cost
                
                # Get image
                image_url = ""
                if 'image' in item:
                    image_url = item['image'].get('imageUrl', '')
                
                # Get buying options
                buying_options = item.get('buyingOptions', [])
                listing_type = 'FixedPrice'
                if 'AUCTION' in buying_options:
                    listing_type = 'Auction'
                
                # Get condition
                condition = item.get('condition', 'Unknown')
                
                # Only include items with reasonable prices (relaxed for sandbox)
                max_price = 5000 if EBAY_ENVIRONMENT.upper() == "SANDBOX" else 10000
                if 0.50 <= total_price <= max_price:
                    items.append({
                        "title": title,
                        "url": item_web_url,
                        "price": total_price,
                        "base_price": price,
                        "shipping": shipping_cost,
                        "currency": currency,
                        "image": image_url,
                        "listing_type": listing_type,
                        "condition": condition
                    })
                    
            except Exception as e:
                logger.warning(f"Error parsing Browse API item: {e}")
                continue
        
        logger.info(f"Parsed {len(items)} valid items from eBay Browse API")
        return items
        
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
            grading_keywords = ["psa", "cgc", "bgs", "beckett", "graded", "authenticated", "gem mint", "grade"]
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
    
    # Test OAuth token on startup
    token = await get_oauth_token()
    if token:
        print("✅ Successfully connected to eBay Browse API")
    else:
        print("❌ Failed to connect to eBay Browse API")

@bot.command(name='test')
async def simple_test(ctx):
    """Simple test command"""
    await ctx.send("✅ Bot is working! Ready to check card prices.")

@bot.command(name='sandbox')
async def test_sandbox(ctx):
    """Test with Sandbox environment to verify credentials work there"""
    try:
        embed = discord.Embed(
            title="🧪 Sandbox Environment Test",
            description="Testing authentication with Sandbox environment",
            color=0xF39C12,
            timestamp=datetime.now(timezone.utc)
        )
        
        # Test with sandbox URLs
        sandbox_oauth_url = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
        
        import base64
        auth_string = base64.b64encode(f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode()).decode()
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Authorization': f'Basic {auth_string}'
        }
        
        import urllib.parse
        scope_encoded = urllib.parse.quote('https://api.ebay.com/oauth/api_scope')
        data = f'grant_type=client_credentials&scope={scope_encoded}'
        
        embed.add_field(
            name="📋 Test Details",
            value=f"**URL**: `{sandbox_oauth_url}`\n**Environment**: `SANDBOX`\n**Purpose**: Check if credentials work in Sandbox",
            inline=False
        )
        
        async with aiohttp.ClientSession() as session:
            async with session.post(sandbox_oauth_url, headers=headers, data=data, timeout=15) as resp:
                response_text = await resp.text()
                
                if resp.status == 200:
                    embed.add_field(
                        name="✅ Sandbox Success",
                        value="Your credentials work in Sandbox! This suggests:\n• Your credentials are Sandbox credentials\n• You need Production credentials for Production API\n• Check eBay Developer Console for Production keys",
                        inline=False
                    )
                    embed.color = 0x1F8B4C
                else:
                    embed.add_field(
                        name="❌ Sandbox Failed Too",
                        value=f"Status: {resp.status}\nThis suggests your credentials may be:\n• Invalid/expired\n• From a different eBay account\n• Incorrectly copied",
                        inline=False
                    )
                    embed.color = 0xE74C3C
                    
                    # Show error details
                    embed.add_field(
                        name="Error Response",
                        value=f"```{response_text[:400]}```",
                        inline=False
                    )
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(f"❌ Sandbox test failed: {str(e)}")

@bot.command(name='appstatus')
async def check_app_status(ctx):
    """Instructions for checking app status in eBay Developer Console"""
    embed = discord.Embed(
        title="🔍 Check Your eBay App Status",
        description="Common causes of `invalid_client` error and how to fix them",
        color=0x2C2F33,
        timestamp=datetime.now(timezone.utc)
    )
    
    embed.add_field(
        name="🚨 Most Common Causes",
        value="1. **Wrong Environment**: Using Sandbox credentials with Production API\n2. **App Not Approved**: Production app needs approval\n3. **Missing API Access**: App doesn't have Browse API enabled\n4. **Expired Credentials**: Credentials may have been regenerated",
        inline=False
    )
    
    embed.add_field(
        name="📝 Step-by-Step Fix",
        value="1. Go to https://developer.ebay.com/my/keys\n2. Check if you have **both** Sandbox AND Production sections\n3. Verify your **Production** app status shows 'Active'\n4. Ensure 'Browse API' is listed under enabled APIs\n5. Copy the **Production** credentials (not Sandbox)",
        inline=False
    )
    
    embed.add_field(
        name="⚠️ Production App Requirements",
        value="Production apps often require:\n• Business verification\n• API usage justification\n• App review process\n\nIf your Production section is empty or shows 'Pending', your app isn't approved yet.",
        inline=False
    )
    
    embed.add_field(
        name="🧪 Test First",
        value="Run `!sandbox` to test if your credentials work in Sandbox environment. This will tell us if the issue is environment mismatch.",
        inline=False
    )
    
    await ctx.send(embed=embed)

@bot.command(name='credcheck')
async def credential_check(ctx):
    """Check credential format and environment matching"""
    try:
        embed = discord.Embed(
            title="🔑 Credential Validation",
            description="Checking credential format and environment settings",
            color=0x2C2F33,
            timestamp=datetime.now(timezone.utc)
        )
        
        # Check credential format
        client_id_format = "✅ Looks correct" if EBAY_CLIENT_ID and len(EBAY_CLIENT_ID) > 10 else "❌ Too short or missing"
        client_secret_format = "✅ Looks correct" if EBAY_CLIENT_SECRET and len(EBAY_CLIENT_SECRET) > 10 else "❌ Too short or missing"
        
        embed.add_field(
            name="📋 Credential Format Check",
            value=f"**Client ID Length**: {len(EBAY_CLIENT_ID) if EBAY_CLIENT_ID else 0} chars - {client_id_format}\n**Client Secret Length**: {len(EBAY_CLIENT_SECRET) if EBAY_CLIENT_SECRET else 0} chars - {client_secret_format}",
            inline=False
        )
        
        # Environment check
        embed.add_field(
            name="🌐 Environment Settings",
            value=f"**Current Environment**: `{EBAY_ENVIRONMENT}`\n**OAuth URL**: `{EBAY_OAUTH_URL}`\n**Browse URL**: `{EBAY_BROWSE_URL}`",
            inline=False
        )
        
        # Base64 encoding test
        import base64
        try:
            auth_string = base64.b64encode(f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode()).decode()
            b64_status = f"✅ Success - Length: {len(auth_string)}"
        except Exception as e:
            b64_status = f"❌ Error: {str(e)}"
        
        embed.add_field(
            name="🔐 Base64 Encoding Test",
            value=b64_status,
            inline=False
        )
        
        # Instructions
        embed.add_field(
            name="📝 Quick Checklist",
            value="1. Go to https://developer.ebay.com/my/keys\n2. Select the right environment (Sandbox/Production)\n3. Copy 'App ID (Client ID)' to EBAY_CLIENT_ID\n4. Copy 'Cert ID (Client Secret)' to EBAY_CLIENT_SECRET\n5. Set EBAY_ENVIRONMENT=PRODUCTION (or SANDBOX)",
            inline=False
        )
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(f"❌ Credential check failed: {str(e)}")

@bot.command(name='testauth')
async def test_auth_detailed(ctx):
    """Detailed OAuth test with inline error reporting"""
    try:
        # Test OAuth and capture detailed response
        import base64
        auth_string = base64.b64encode(f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode()).decode()
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Authorization': f'Basic {auth_string}'
        }
        
        import urllib.parse
        scope_encoded = urllib.parse.quote('https://api.ebay.com/oauth/api_scope')
        data = f'grant_type=client_credentials&scope={scope_encoded}'
        
        embed = discord.Embed(
            title="🔍 Detailed OAuth Test",
            color=0x2C2F33,
            timestamp=datetime.now(timezone.utc)
        )
        
        embed.add_field(
            name="📋 Request Details",
            value=f"**URL**: `{EBAY_OAUTH_URL}`\n**Scope**: `https://api.ebay.com/oauth/api_scope`\n**Grant Type**: `client_credentials`",
            inline=False
        )
        
        async with aiohttp.ClientSession() as session:
            async with session.post(EBAY_OAUTH_URL, headers=headers, data=data, timeout=15) as resp:
                response_text = await resp.text()
                
                embed.add_field(
                    name="📊 Response Details",
                    value=f"**Status Code**: `{resp.status}`\n**Content-Type**: `{resp.headers.get('content-type', 'N/A')}`",
                    inline=False
                )
                
                if resp.status == 200:
                    try:
                        token_data = json.loads(response_text)
                        token_preview = token_data['access_token'][:30] + "..."
                        embed.add_field(
                            name="✅ Success",
                            value=f"Token: `{token_preview}`\nExpires: `{token_data.get('expires_in')} seconds`",
                            inline=False
                        )
                        embed.color = 0x1F8B4C
                    except json.JSONDecodeError:
                        embed.add_field(
                            name="⚠️ Parse Error",
                            value=f"Response: ```{response_text[:500]}```",
                            inline=False
                        )
                        embed.color = 0xF39C12
                else:
                    # Show the actual error response
                    embed.add_field(
                        name="❌ Error Response",
                        value=f"```json\n{response_text[:800]}```",
                        inline=False
                    )
                    embed.color = 0xE74C3C
                    
                    # Try to parse and explain common errors
                    try:
                        error_data = json.loads(response_text)
                        error_type = error_data.get('error', 'unknown')
                        error_desc = error_data.get('error_description', 'No description')
                        
                        common_fixes = {
                            'invalid_client': '• Check your Client ID and Client Secret\n• Ensure credentials match the environment (Sandbox vs Production)',
                            'invalid_scope': '• Your app may not have Browse API access\n• Check your app permissions in Developer Console',
                            'unauthorized_client': '• Your app may not be approved for this environment\n• Check app status in Developer Console'
                        }
                        
                        if error_type in common_fixes:
                            embed.add_field(
                                name="💡 Likely Fix",
                                value=common_fixes[error_type],
                                inline=False
                            )
                    except:
                        pass
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(f"❌ Test failed: {str(e)}")

@bot.command(name='oauth')
async def oauth_debug(ctx):
    """Debug OAuth authentication specifically"""
    try:
        embed = discord.Embed(
            title="OAuth 2.0 Debug",
            description="Testing eBay API authentication",
            color=0x2C2F33,
            timestamp=datetime.now(timezone.utc)
        )
        
        # Check credentials
        creds_status = []
        creds_status.append(f"{'🟢' if EBAY_CLIENT_ID else '🔴'} **Client ID**: `{EBAY_CLIENT_ID[:8] if EBAY_CLIENT_ID else 'Missing'}...`")
        creds_status.append(f"{'🟢' if EBAY_CLIENT_SECRET else '🔴'} **Client Secret**: `{'✓ Set' if EBAY_CLIENT_SECRET else 'Missing'}`")
        creds_status.append(f"🌐 **Environment**: `{EBAY_ENVIRONMENT}`")
        creds_status.append(f"🔗 **OAuth URL**: `{EBAY_OAUTH_URL}`")
        
        embed.add_field(
            name="🔑 Credentials Check",
            value="\n".join(creds_status),
            inline=False
        )
        
        # Test OAuth with detailed error reporting
        token_result = await get_oauth_token()
        if token_result:
            token_preview = f"`{token_result[:20]}...`"
            oauth_status = f"✅ **Success**\nToken: {token_preview}"
        else:
            oauth_status = "❌ **Failed** - Run this command again to see detailed error info"
        
        embed.add_field(
            name="🔐 OAuth Token Test",
            value=oauth_status,
            inline=False
        )
        
        # Add troubleshooting tips
        embed.add_field(
            name="🛠️ Troubleshooting",
            value="1. Verify your eBay Developer Account is active\n2. Ensure your app has 'Browse API' access\n3. Check that credentials are for Production (not Sandbox)\n4. Make sure Client ID/Secret are correct",
            inline=False
        )
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(f"❌ OAuth debug failed: {str(e)}")
        logger.error(f"OAuth debug error: {e}")

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
        env_status.append(f"{'🟢' if EBAY_CLIENT_ID else '🔴'} **eBay Client ID**")
        env_status.append(f"{'🟢' if EBAY_CLIENT_SECRET else '🔴'} **eBay Client Secret**")
        env_status.append(f"{'🟢' if PRICE_CHECK_CHANNEL_ID else '🟡'} **Channel Restriction**")
        
        embed.add_field(
            name="📋 Configuration",
            value="\n".join(env_status),
            inline=True
        )
        
        # Test eBay Browse API
        try:
            token = await get_oauth_token()
            if token:
                # Test API call
                async with aiohttp.ClientSession() as session:
                    headers = {
                        'Authorization': f'Bearer {token}',
                        'Content-Type': 'application/json',
                        'X-EBAY-C-MARKETPLACE-ID': 'EBAY_US'
                    }
                    
                    params = {
                        'q': 'pokemon charizard',
                        'category_ids': '183454',
                        'limit': '5'
                    }
                    
                    async with session.get(EBAY_BROWSE_URL, headers=headers, params=params, timeout=15) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            item_count = len(data.get('itemSummaries', []))
                            api_status = f"✅ Browse API working ({item_count} test items)"
                        elif resp.status == 401:
                            api_status = "❌ Authentication failed - check credentials"
                        elif resp.status == 403:
                            api_status = "❌ Access denied - check API permissions"
                        else:
                            error_text = await resp.text()
                            api_status = f"❌ API Error: HTTP {resp.status} - {error_text[:50]}"
            else:
                api_status = "❌ OAuth token acquisition failed"
                        
        except asyncio.TimeoutError:
            api_status = "❌ Connection timeout"
        except Exception as e:
            api_status = f"❌ Error: {type(e).__name__}: {str(e)[:50]}"
        
        embed.add_field(name="🔗 eBay Browse API", value=api_status, inline=True)
        
        # Add separator
        embed.add_field(name="\u200b", value="\u200b", inline=False)
        
        embed.add_field(
            name="ℹ️ System Info", 
            value=f"Using eBay Browse API ({EBAY_ENVIRONMENT} environment)\nOAuth 2.0 Authentication",
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
        description=f"🔍 Analyzing market data for **{card_name.title()}**...\n*Using eBay Browse API*",
        color=0x99AAB5
    )
    searching_msg = await ctx.send(embed=searching_embed)
    
    try:
        async with aiohttp.ClientSession() as session:
            # Create main embed with professional styling
            embed = discord.Embed(
                title=card_name.title(),
                description=f"**Current Market Analysis** • {EBAY_ENVIRONMENT.title()} eBay Data",
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
                    await asyncio.sleep(2.0)  # 2 second delay between requests
                    
                query = build_query(card_name, condition)
                items = await fetch_browse_items(session, query, 12)
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
                
                # Add average price fields
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
                    profit9 = (avg_psa9 - mean(raw_prices) - 20) if raw_prices else 0
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
                    profit10 = (avg_psa10 - mean(raw_prices) - 20) if raw_prices else 0
                    profit_color = "🟢" if profit10 > 0 else "🔴"
                    embed.add_field(
                        name="🥇 PSA 10",
                        value=f"`${avg_psa10:.2f}` avg • `${min_psa10:.2f}` - `${max_psa10:.2f}`\n*{len(psa10_prices)} listings*{' • ' + profit_color + f' ${profit10:.2f} profit' if raw_prices else ''}",
                        inline=True
                    )
                
                # Add separator line
                embed.add_field(name="\u200b", value="─────────────────────", inline=False)
                
                # Add individual listings
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
                footer_text = f"PokéBrief • {EBAY_ENVIRONMENT.title()} eBay data via Browse API • Prices include shipping"
                if EBAY_ENVIRONMENT.upper() == "SANDBOX":
                    footer_text += " • Test Data Only"
                
                embed.set_footer(
                    text=footer_text,
                    icon_url="https://cdn.discordapp.com/emojis/658538492321595392.png"
                )
            
            # Edit the searching message with results
            await searching_msg.edit(content=None, embed=embed)
            
    except Exception as e:
        logger.error(f"Error in price command: {e}")
        error_embed = discord.Embed(
            title="Service Temporarily Unavailable",
            description=f"Unable to retrieve market data for **{card_name}** at this time.\n\nThis may be due to API authentication issues. Please try again in a few minutes.",
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
        description="Get current Pokemon card prices from eBay using the latest Browse API!",
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
        name="🆕 What's New",
        value=f"Updated to use eBay's Browse API\nCurrently running in **{EBAY_ENVIRONMENT.upper()}** mode" + (" (Test Data)" if EBAY_ENVIRONMENT.upper() == "SANDBOX" else ""),
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