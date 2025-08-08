import os
import time
import requests
import discord
from discord.ext import commands
from dotenv import load_dotenv
import base64
import re

load_dotenv()

# Load environment variables
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))
EBAY_CLIENT_ID = os.getenv("EBAY_CLIENT_ID")
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET")
GRADING_FEE = float(os.getenv("GRADING_FEE", 18.0))
PROFIT_THRESHOLD = float(os.getenv("PROFIT_THRESHOLD", 50.0))

# Globals for eBay OAuth token
ebay_access_token = None
token_expiration = 0

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

def get_ebay_token():
    global ebay_access_token, token_expiration
    print("🔄 Fetching new eBay token...")
    credentials = f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}"
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

def search_ebay_listings(query, limit=20):
    ensure_token()
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    headers = {
        "Authorization": f"Bearer {ebay_access_token}"
    }
    params = {
        "q": query,
        "limit": str(limit),
        "filter": "priceCurrency:USD",
        "sort": "-newlyListed"
    }
    try:
        res = requests.get(url, headers=headers, params=params)
        res.raise_for_status()
        return res.json().get("itemSummaries", [])
    except Exception as e:
        print(f"Error fetching eBay listings for '{query}':", e)
        return []

def filter_sales(listings, query, category):
    query_lower = query.lower()
    if category == "raw":
        # Include listings with card name but exclude any with grading acronyms
        return [
            l for l in listings
            if query_lower in l["title"].lower()
            and not re.search(r"\b(PSA|BGC|CGC|TAG|ACE)\b", l["title"], re.IGNORECASE)
        ]
    elif category == "psa9":
        # Include listings with card name and PSA 9 pattern
        return [
            l for l in listings
            if query_lower in l["title"].lower()
            and re.search(r"\bpsa[-\s]?9\b", l["title"], re.IGNORECASE)
        ]
    elif category == "psa10":
        # Include listings with card name and PSA 10 pattern
        return [
            l for l in listings
            if query_lower in l["title"].lower()
            and re.search(r"\bpsa[-\s]?10\b", l["title"], re.IGNORECASE)
        ]
    else:
        return []

def avg_price(listings):
    prices = []
    for l in listings:
        try:
            prices.append(float(l["price"]["value"]))
        except Exception:
            continue
    return sum(prices) / len(prices) if prices else 0.0

def format_sales(listings, max_count=3):
    lines = []
    for l in listings[:max_count]:
        title = l["title"]
        if len(title) > 50:
            title = title[:47] + "..."
        price = float(l["price"]["value"])
        url = l.get("itemWebUrl", "")
        lines.append(f"[{title}]({url}) - ${price:.2f}")
    if not lines:
        lines = ["No recent sales found."]
    return "\n".join(lines)

def generate_embed(card_name, card_url, image_url, raw_avg, psa9_avg, psa10_avg, raw_sales, psa9_sales, psa10_sales):
    embed = discord.Embed(
        title=f"Price Check: {card_name}",
        url=card_url,
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )
    if image_url:
        embed.set_thumbnail(url=image_url)

    embed.add_field(name="Average Raw Price", value=f"${raw_avg:.2f}", inline=True)
    embed.add_field(name="Average PSA 9 Price", value=f"${psa9_avg:.2f}", inline=True)
    embed.add_field(name="Average PSA 10 Price", value=f"${psa10_avg:.2f}", inline=True)

    profit_psa9 = psa9_avg - raw_avg - GRADING_FEE if psa9_avg > 0 else 0
    profit_psa10 = psa10_avg - raw_avg - GRADING_FEE if psa10_avg > 0 else 0

    embed.add_field(name="Estimated PSA 9 Profit", value=f"${profit_psa9:.2f}", inline=True)
    embed.add_field(name="Estimated PSA 10 Profit", value=f"${profit_psa10:.2f}", inline=True)

    embed.add_field(name="Recent Raw Sales", value=format_sales(raw_sales), inline=False)
    embed.add_field(name="Recent PSA 9 Sales", value=format_sales(psa9_sales), inline=False)
    embed.add_field(name="Recent PSA 10 Sales", value=format_sales(psa10_sales), inline=False)

    embed.set_footer(text="PokePriceTrackerBot — Smarter Investing in Pokémon")

    return embed

@bot.command()
async def price(ctx, *, card_name: str):
    listings = search_ebay_listings(card_name, limit=50)
    if not listings:
        await ctx.send("❌ No listings found on eBay.")
        return

    # Filter and collect listings by category
    raw_sales = filter_sales(listings, card_name, "raw")
    psa9_sales = filter_sales(listings, card_name, "psa9")
    psa10_sales = filter_sales(listings, card_name, "psa10")

    # Calculate average prices
    raw_avg = avg_price(raw_sales)
    psa9_avg = avg_price(psa9_sales)
    psa10_avg = avg_price(psa10_sales)

    # Use first matching listing as main card reference for image and URL
    first_listing = listings[0]
    card_url = first_listing.get("itemWebUrl", "")
    image_url = first_listing.get("image", {}).get("imageUrl", "")

    embed = generate_embed(card_name, card_url, image_url, raw_avg, psa9_avg, psa10_avg, raw_sales, psa9_sales, psa10_sales)

    await ctx.send(embed=embed)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

bot.run(DISCORD_TOKEN)
