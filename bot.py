import os
import time
import re
import requests
import discord
from discord.ext import commands
from dotenv import load_dotenv
import base64

load_dotenv()

# Environment variables
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))
GRADING_FEE = float(os.getenv("GRADING_FEE", 18.0))
PROFIT_THRESHOLD = float(os.getenv("PROFIT_THRESHOLD", 50.0))

# Globals for eBay token
ebay_access_token = None
token_expiration = 0

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

def get_ebay_token():
    global ebay_access_token, token_expiration
    print("🔄 Fetching new eBay token...")
    credentials = f"{os.getenv('EBAY_CLIENT_ID')}:{os.getenv('EBAY_CLIENT_SECRET')}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {encoded_credentials}"
    }
    data = {
        "grant_type": "client_credentials",
        "scope": "https://api.ebay.com/oauth/api_scope"
    }
    response = requests.post("https://api.ebay.com/identity/v1/oauth2/token", headers=headers, data=data)
    response.raise_for_status()
    token_data = response.json()
    ebay_access_token = token_data["access_token"]
    token_expiration = time.time() + token_data["expires_in"]
    print("✅ eBay token acquired.")

def ensure_token():
    if not ebay_access_token or time.time() >= token_expiration:
        get_ebay_token()

def search_ebay_listings(query, limit=50):
    ensure_token()
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    headers = {
        "Authorization": f"Bearer {ebay_access_token}"
    }
    params = {
        "q": query,
        "limit": str(limit),
        "filter": "priceCurrency:USD",
        "category_ids": "2601",  # Pokémon Cards category
        "sort": "-newlyListed"
    }
    try:
        res = requests.get(url, headers=headers, params=params)
        res.raise_for_status()
        return res.json().get("itemSummaries", [])
    except Exception as e:
        print(f"Error fetching eBay listings for '{query}':", e)
        return []

def filter_sales(sales, include_pattern=None, exclude_patterns=None):
    filtered = []
    for s in sales:
        title = s["title"].lower()
        if exclude_patterns and any(pat in title for pat in exclude_patterns):
            continue
        if include_pattern and not re.search(include_pattern, title, re.IGNORECASE):
            continue
        filtered.append(s)
    return filtered

def get_recent_sales(query, condition=None):
    listings = search_ebay_listings(query)
    if condition == "raw":
        # Exclude PSA/CGC/TAG/ACE/Beckett in title
        exclude = ["psa", "cgc", "tag", "ace", "beckett"]
        filtered = filter_sales(listings, exclude_patterns=exclude)
    elif condition == "psa9":
        # Include PSA 9 (with optional space/dash)
        filtered = filter_sales(listings, include_pattern=r"psa[\s-]?9")
    elif condition == "psa10":
        filtered = filter_sales(listings, include_pattern=r"psa[\s-]?10")
    else:
        filtered = listings
    # Return top 3 most recent sales
    return filtered[:3]

def avg(prices):
    return sum(prices) / len(prices) if prices else 0.0

def format_sales(sales):
    lines = []
    for sale in sales:
        title = sale['title'][:50] + ("..." if len(sale['title']) > 50 else "")
        price = f"${sale['price']['value']}"
        url = sale.get("itemWebUrl") or sale.get("itemUrl") or ""
        lines.append(f"[{title}]({url}) - {price}")
    return lines if lines else ["No recent sales found."]

def generate_card_embed(card_name, card_url, card_image_url, raw_avg, psa9_avg, psa10_avg, raw_sales, psa9_sales, psa10_sales):
    profit9 = psa9_avg - raw_avg - GRADING_FEE
    profit10 = psa10_avg - raw_avg - GRADING_FEE

    embed = discord.Embed(
        title=f"Price Check: {card_name}",
        url=card_url,
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )
    embed.set_thumbnail(url=card_image_url)
    embed.add_field(name="Average Raw Price", value=f"${raw_avg:.2f}", inline=True)
    embed.add_field(name="Average PSA 9 Price", value=f"${psa9_avg:.2f}", inline=True)
    embed.add_field(name="Average PSA 10 Price", value=f"${psa10_avg:.2f}", inline=True)
    embed.add_field(name="Estimated PSA 9 Profit", value=f"${profit9:.2f}", inline=True)
    embed.add_field(name="Estimated PSA 10 Profit", value=f"${profit10:.2f}", inline=True)
    embed.add_field(name="Recent Raw Sales", value="\n".join(format_sales(raw_sales)), inline=False)
    embed.add_field(name="Recent PSA 9 Sales", value="\n".join(format_sales(psa9_sales)), inline=False)
    embed.add_field(name="Recent PSA 10 Sales", value="\n".join(format_sales(psa10_sales)), inline=False)
    embed.set_footer(text="PokePriceTrackerBot — Smarter Investing in Pokémon")
    return embed

@bot.command(name="price")
async def price_check(ctx, *, card_name: str):
    # Search for main card listing to get URL and image
    listings = search_ebay_listings(card_name, limit=10)
    if not listings:
        await ctx.send("❌ No listings found for that card.")
        return

    # Use first listing as main reference
    main_listing = listings[0]
    card_url = main_listing.get("itemWebUrl")
    card_image_url = main_listing.get("image", {}).get("imageUrl") or main_listing.get("imageUrl") or ""

    # Get recent sales data
    raw_sales = get_recent_sales(card_name, condition="raw")
    psa9_sales = get_recent_sales(card_name, condition="psa9")
    psa10_sales = get_recent_sales(card_name, condition="psa10")

    raw_avg = avg([float(s["price"]["value"]) for s in raw_sales])
    psa9_avg = avg([float(s["price"]["value"]) for s in psa9_sales])
    psa10_avg = avg([float(s["price"]["value"]) for s in psa10_sales])

    embed = generate_card_embed(
        card_name, card_url, card_image_url,
        raw_avg, psa9_avg, psa10_avg,
        raw_sales, psa9_sales, psa10_sales
    )
    await ctx.send(embed=embed)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

bot.run(DISCORD_TOKEN)

