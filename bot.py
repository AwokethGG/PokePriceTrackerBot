import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import requests
import time
import base64

load_dotenv()

# Env vars
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))  # Price check channel
GRADING_FEE = float(os.getenv("GRADING_FEE", 18.0))
PROFIT_THRESHOLD = float(os.getenv("PROFIT_THRESHOLD", 50.0))
EBAY_CLIENT_ID = os.getenv("EBAY_CLIENT_ID")
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Globals for eBay OAuth
ebay_access_token = None
token_expiration = 0

def get_ebay_token():
    global ebay_access_token, token_expiration
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
    token_expiration = time.time() + token_data["expires_in"] - 60  # refresh 1 min before expiry
    print("🔄 Fetched new eBay access token")

def ensure_token():
    if not ebay_access_token or time.time() >= token_expiration:
        get_ebay_token()

def search_ebay_listings(query, limit=30):
    """Search eBay listings for the query, return list of dict with keys: title, price, url, image."""
    ensure_token()
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    headers = {"Authorization": f"Bearer {ebay_access_token}"}
    params = {
        "q": query,
        "limit": str(limit),
        "filter": "priceCurrency:USD",
        "sort": "-newlyListed"
    }
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    data = response.json()
    results = []
    for item in data.get("itemSummaries", []):
        try:
            results.append({
                "title": item["title"],
                "price": float(item["price"]["value"]),
                "url": item["itemWebUrl"],
                "image": item["image"]["imageUrl"]
            })
        except KeyError:
            continue
    return results

def filter_sales(listings, query, category):
    query_lower = query.lower()
    if category == "raw":
        # Include listings with query but exclude PSA/BGC/CGC/TAG/ACE anywhere uppercase
        return [l for l in listings
                if query_lower in l["title"].lower() and
                not any(x in l["title"].upper() for x in ["PSA", "BGC", "CGC", "TAG", "ACE"])]
    elif category == "psa9":
        return [l for l in listings
                if query_lower in l["title"].lower() and
                "PSA 9" in l["title"].upper()]
    elif category == "psa10":
        return [l for l in listings
                if query_lower in l["title"].lower() and
                "PSA 10" in l["title"].upper()]
    else:
        return []

def avg_price(sales):
    prices = [s["price"] for s in sales[:3]]
    return sum(prices) / len(prices) if prices else 0.0

def format_sales_embed_field(title, sales):
    if not sales:
        return "No recent sales found."
    lines = []
    for sale in sales[:3]:
        short_title = sale["title"][:50] + ("..." if len(sale["title"]) > 50 else "")
        price = f"${sale['price']:.2f}"
        lines.append(f"[{short_title}]({sale['url']}) - {price}")
    return "\n".join(lines)

@bot.command(name="price")
async def price_check(ctx, *, card_name):
    listings = search_ebay_listings(card_name, limit=30)

    raw_sales = filter_sales(listings, card_name, "raw")
    psa9_sales = filter_sales(listings, card_name, "psa9")
    psa10_sales = filter_sales(listings, card_name, "psa10")

    raw_avg = avg_price(raw_sales)
    psa9_avg = avg_price(psa9_sales)
    psa10_avg = avg_price(psa10_sales)

    main_listing = listings[0] if listings else None

    if not main_listing:
        await ctx.send("❌ No listings found for that card.")
        return

    profit_psa10 = psa10_avg - raw_avg - GRADING_FEE
    profit_psa9 = psa9_avg - raw_avg - GRADING_FEE

    embed = discord.Embed(
        title=f"Price Check: {main_listing['title'][:256]}",
        url=main_listing["url"],
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=main_listing["image"])

    embed.add_field(name="🪙 Raw Price (Avg of 3)", value=f"${raw_avg:.2f}", inline=True)
    embed.add_field(name="💎 PSA 10 Price (Avg of 3)", value=f"${psa10_avg:.2f}", inline=True)
    embed.add_field(name="💠 PSA 9 Price (Avg of 3)", value=f"${psa9_avg:.2f}", inline=True)

    embed.add_field(name="📈 PSA 10 Profit", value=f"${profit_psa10:.2f}", inline=True)
    embed.add_field(name="📉 PSA 9 Profit", value=f"${profit_psa9:.2f}", inline=True)

    embed.add_field(name="Recent Raw Sales", value=format_sales_embed_field("Raw", raw_sales), inline=False)
    embed.add_field(name="Recent PSA 9 Sales", value=format_sales_embed_field("PSA 9", psa9_sales), inline=False)
    embed.add_field(name="Recent PSA 10 Sales", value=format_sales_embed_field("PSA 10", psa10_sales), inline=False)

    await ctx.send(embed=embed)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

bot.run(TOKEN)
