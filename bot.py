import os
import time
import requests
import discord
from discord.ext import commands
from dotenv import load_dotenv
import base64

load_dotenv()

# Environment variables from Railway
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
EBAY_CLIENT_ID = os.getenv("EBAY_CLIENT_ID")
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET")
GRADING_FEE = float(os.getenv("GRADING_FEE", 18.0))

# Globals for eBay auth
ebay_access_token = None
token_expiration = 0

# Forbidden words and grades
FORBIDDEN_WORDS = ["every", "set", "collection", "sealed", "lot", "cards", "custom", "madetoorder", "choose"]
FORBIDDEN_GRADES = ["psa", "cgc", "tag", "ace"]

# Discord bot setup
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
    token_expiration = time.time() + token_data["expires_in"] - 60  # refresh 60 sec before expiry
    print("✅ eBay token acquired.")


def ensure_token():
    global ebay_access_token, token_expiration
    if not ebay_access_token or time.time() >= token_expiration:
        get_ebay_token()


def fetch_ebay_listings(query, limit=5):
    ensure_token()
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    headers = {"Authorization": f"Bearer {ebay_access_token}"}
    params = {
        "q": query,
        "limit": str(limit),
        "filter": "priceCurrency:USD",
        "sort": "-newlyListed"
    }
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        items = response.json().get("itemSummaries", [])
        # Filter forbidden words and grades (case insensitive)
        filtered = []
        for item in items:
            title_lower = item.get("title", "").lower()
            if any(word in title_lower for word in FORBIDDEN_WORDS):
                continue
            if any(grade in title_lower for grade in FORBIDDEN_GRADES):
                continue
            filtered.append(item)
        return filtered
    except Exception as e:
        print(f"❌ eBay API error for query '{query}': {e}")
        return []


def calculate_average_price(items):
    prices = []
    for item in items:
        try:
            price = float(item["price"]["value"])
            prices.append(price)
        except Exception:
            continue
    return sum(prices) / len(prices) if prices else None


def generate_embed(card_name, raw_price, psa9_price, psa10_price, recent_sales_raw, recent_sales_psa9, recent_sales_psa10, listing_url=None, image_url=None):
    profit_10 = psa10_price - raw_price - GRADING_FEE if psa10_price and raw_price else None
    profit_9 = psa9_price - raw_price - GRADING_FEE if psa9_price and raw_price else None

    embed = discord.Embed(
        title=f"Pokémon Card: {card_name}",
        url=listing_url,
        description="Price info & recent sales data",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )

    if image_url:
        embed.set_thumbnail(url=image_url)

    embed.add_field(name="🪙 Raw Price", value=f"${raw_price:.2f}" if raw_price else "N/A", inline=True)
    embed.add_field(name="💠 PSA 9 Price", value=f"${psa9_price:.2f}" if psa9_price else "N/A", inline=True)
    embed.add_field(name="💎 PSA 10 Price", value=f"${psa10_price:.2f}" if psa10_price else "N/A", inline=True)

    embed.add_field(name="📉 Estimated Profit PSA 9", value=f"${profit_9:.2f}" if profit_9 is not None else "N/A", inline=True)
    embed.add_field(name="📈 Estimated Profit PSA 10", value=f"${profit_10:.2f}" if profit_10 is not None else "N/A", inline=True)

    # Format recent sales nicely
    def format_sales(sales):
        if not sales:
            return "No recent sales found."
        lines = []
        for sale in sales[:3]:
            title = sale.get("title", "Unknown")[:50]
            price = sale.get("price", 0)
            url = sale.get("url", "")
            lines.append(f"[{title}]({url}) - ${price:.2f}")
        return "\n".join(lines)

    embed.add_field(name="Recent Raw Sales", value=format_sales(recent_sales_raw), inline=False)
    embed.add_field(name="Recent PSA 9 Sales", value=format_sales(recent_sales_psa9), inline=False)
    embed.add_field(name="Recent PSA 10 Sales", value=format_sales(recent_sales_psa10), inline=False)

    embed.set_footer(text="PokeBrief TCG Price Tracker")

    return embed


@bot.command()
async def price(ctx, *, card_name: str):
    print(f"🔍 Price check for: {card_name}")

    raw_items = fetch_ebay_listings(card_name, limit=10)
    psa9_items = fetch_ebay_listings(f"{card_name} PSA 9", limit=10)
    psa10_items = fetch_ebay_listings(f"{card_name} PSA 10", limit=10)

    raw_price = calculate_average_price(raw_items)
    psa9_price = calculate_average_price(psa9_items)
    psa10_price = calculate_average_price(psa10_items)

    if not raw_price or not psa10_price:
        await ctx.send("❌ Could not fetch sufficient pricing data for that card.")
        return

    recent_raw = [{"title": i["title"], "price": float(i["price"]["value"]), "url": i["itemWebUrl"]} for i in raw_items]
    recent_psa9 = [{"title": i["title"], "price": float(i["price"]["value"]), "url": i["itemWebUrl"]} for i in psa9_items]
    recent_psa10 = [{"title": i["title"], "price": float(i["price"]["value"]), "url": i["itemWebUrl"]} for i in psa10_items]

    image_url = raw_items[0].get("image", {}).get("imageUrl") if raw_items else None
    listing_url = raw_items[0].get("itemWebUrl") if raw_items else None

    embed = generate_embed(card_name, raw_price, psa9_price, psa10_price, recent_raw, recent_psa9, recent_psa10, listing_url, image_url)
    await ctx.send(embed=embed)


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")


bot.run(DISCORD_TOKEN)
