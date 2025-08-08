import os
import discord
import requests
from discord.ext import commands
from datetime import datetime, timedelta

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
EBAY_CLIENT_ID = os.getenv("EBAY_CLIENT_ID")
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET")
EBAY_SCOPE = "https://api.ebay.com/oauth/api_scope"  # Use Browse API scope

eg_token_data = {"access_token": None, "expires_at": None}

def get_ebay_access_token():
    credentials = f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}"
    encoded_credentials = requests.utils.quote(credentials)
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {encoded_credentials}"
    }
    data = {
        "grant_type": "client_credentials",
        "scope": EBAY_SCOPE
    }
    response = requests.post("https://api.ebay.com/identity/v1/oauth2/token", headers=headers, data=data, auth=(EBAY_CLIENT_ID, EBAY_CLIENT_SECRET))
    response.raise_for_status()
    token_info = response.json()
    eg_token_data["access_token"] = token_info["access_token"]
    eg_token_data["expires_at"] = datetime.utcnow() + timedelta(seconds=token_info["expires_in"])

def ensure_token():
    if not eg_token_data["access_token"] or datetime.utcnow() >= eg_token_data["expires_at"]:
        get_ebay_access_token()

def search_ebay_listings(query, limit=50):
    ensure_token()
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    headers = {
        "Authorization": f"Bearer {eg_token_data['access_token']}"
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
        data = res.json()
        return data.get("itemSummaries", [])
    except Exception as e:
        print(f"Error fetching eBay listings for '{query}':", e)
        return []

def get_average_price(items):
    prices = [float(i["price"]["value"]) for i in items if "price" in i and "value" in i["price"]]
    return round(sum(prices) / len(prices), 2) if prices else 0.0

def filter_by_condition(items, keyword):
    return [item for item in items if keyword.lower() in item["title"].lower()]

def format_items(items):
    return "\n".join([
        f"[{item['title']}]({item['itemWebUrl']}) - ${item['price']['value']}" for item in items
    ])

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

@bot.command()
async def price(ctx, *, card_name):
    await ctx.send(f"Searching eBay for '{card_name}'...")

    raw_listings = search_ebay_listings(card_name)
    raw_filtered = [item for item in raw_listings if all(x not in item['title'].upper() for x in ["PSA", "BGS", "CGC", "TAG", "ACE"])]
    psa9_filtered = filter_by_condition(raw_listings, "PSA 9")
    psa10_filtered = filter_by_condition(raw_listings, "PSA 10")

    avg_raw = get_average_price(raw_filtered[:3])
    avg_psa9 = get_average_price(psa9_filtered[:3])
    avg_psa10 = get_average_price(psa10_filtered[:3])

    embed = discord.Embed(title=f"eBay Price Check: {card_name}", color=0x00ff00)
    embed.set_footer(text="Data from eBay Buy API")

    if raw_filtered:
        embed.add_field(name="Raw Listings (avg)", value=f"${avg_raw}\n{format_items(raw_filtered[:3])}", inline=False)
        if "thumbnailImages" in raw_filtered[0]:
            embed.set_thumbnail(url=raw_filtered[0]["thumbnailImages"][0]["imageUrl"])

    if psa9_filtered:
        profit9 = round(avg_psa9 - avg_raw - 20, 2)
        embed.add_field(name="PSA 9 Listings (avg)", value=f"${avg_psa9}\nEstimated Profit: ${profit9}\n{format_items(psa9_filtered[:3])}", inline=False)

    if psa10_filtered:
        profit10 = round(avg_psa10 - avg_raw - 20, 2)
        embed.add_field(name="PSA 10 Listings (avg)", value=f"${avg_psa10}\nEstimated Profit: ${profit10}\n{format_items(psa10_filtered[:3])}", inline=False)

    if not raw_filtered and not psa9_filtered and not psa10_filtered:
        await ctx.send("No results found.")
    else:
        await ctx.send(embed=embed)

bot.run(TOKEN)
