import os
import time
import requests
import discord
from discord.ext import commands
from dotenv import load_dotenv
import base64

load_dotenv()

# Environment variables
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))

EBAY_CLIENT_ID = os.getenv("EBAY_CLIENT_ID")
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET")
GRADING_FEE = float(os.getenv("GRADING_FEE", 18.0))
PROFIT_THRESHOLD = float(os.getenv("PROFIT_THRESHOLD", 50.0))

# Globals for eBay OAuth
ebay_access_token = None
token_expiration = 0

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


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
    token_expiration = time.time() + token_data["expires_in"] - 60  # Refresh 1 minute early


def ensure_token():
    if not ebay_access_token or time.time() >= token_expiration:
        get_ebay_token()


def search_ebay_listings(query, limit=20):
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
    return response.json().get("itemSummaries", [])


def filter_sales(listings, query, category):
    query_lower = query.lower()
    if category == "raw":
        return [l for l in listings
                if query_lower in l["title"].lower() and
                not any(x in l["title"].upper() for x in ["PSA", "BGC", "CGC", "TAG", "ACE"])]
    elif category == "psa9":
        return [l for l in listings
                if query_lower in l["title"].lower() and
                any(x in l["title"].upper() for x in ["PSA9", "PSA 9", "PSA-9"])]
    elif category == "psa10":
        return [l for l in listings
                if query_lower in l["title"].lower() and
                any(x in l["title"].upper() for x in ["PSA10", "PSA 10", "PSA-10"])]
    else:
        return []


def avg(prices):
    return sum(prices) / len(prices) if prices else 0.0


def format_sales(sales):
    lines = []
    for sale in sales[:3]:  # Show up to 3 most recent sales
        title = sale['title'][:50] + ("..." if len(sale['title']) > 50 else "")
        price = f"${float(sale['price']['value']):.2f}"
        url = sale.get('itemWebUrl', '#')
        lines.append(f"[{title}]({url}) - {price}")
    return "\n".join(lines) if lines else "No recent sales found."


@bot.command(name="price")
async def price_check(ctx, *, card_name):
    try:
        listings = search_ebay_listings(card_name)

        raw_listings = filter_sales(listings, card_name, "raw")
        psa9_listings = filter_sales(listings, card_name, "psa9")
        psa10_listings = filter_sales(listings, card_name, "psa10")

        raw_prices = [float(l["price"]["value"]) for l in raw_listings]
        psa9_prices = [float(l["price"]["value"]) for l in psa9_listings]
        psa10_prices = [float(l["price"]["value"]) for l in psa10_listings]

        raw_avg = avg(raw_prices)
        psa9_avg = avg(psa9_prices)
        psa10_avg = avg(psa10_prices)

        # Profit calculation
        profit_psa9 = psa9_avg - raw_avg - GRADING_FEE if psa9_avg and raw_avg else 0
        profit_psa10 = psa10_avg - raw_avg - GRADING_FEE if psa10_avg and raw_avg else 0

        # Use first raw listing for thumbnail and link fallback
        if raw_listings:
            first_listing = raw_listings[0]
        elif listings:
            first_listing = listings[0]
        else:
            await ctx.send("❌ No listings found for that card.")
            return

        embed = discord.Embed(
            title=f"Price Check: {card_name}",
            url=first_listing.get("itemWebUrl"),
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=first_listing.get("image", {}).get("imageUrl"))

        embed.add_field(name="Raw Avg Price", value=f"${raw_avg:.2f}" if raw_avg else "N/A", inline=True)
        embed.add_field(name="PSA 9 Avg Price", value=f"${psa9_avg:.2f}" if psa9_avg else "N/A", inline=True)
        embed.add_field(name="PSA 10 Avg Price", value=f"${psa10_avg:.2f}" if psa10_avg else "N/A", inline=True)

        embed.add_field(name="Profit PSA 9", value=f"${profit_psa9:.2f}" if profit_psa9 else "N/A", inline=True)
        embed.add_field(name="Profit PSA 10", value=f"${profit_psa10:.2f}" if profit_psa10 else "N/A", inline=True)

        embed.add_field(name="Recent Raw Sales", value=format_sales(raw_listings), inline=False)
        embed.add_field(name="Recent PSA 9 Sales", value=format_sales(psa9_listings), inline=False)
        embed.add_field(name="Recent PSA 10 Sales", value=format_sales(psa10_listings), inline=False)

        await ctx.send(embed=embed)

    except Exception as e:
        print(f"Error in price command: {e}")
        await ctx.send("❌ Failed to fetch price data. Please try again later.")


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")


bot.run(DISCORD_TOKEN)
