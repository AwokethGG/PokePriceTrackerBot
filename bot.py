import os
import time
import requests
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import base64

load_dotenv()

# Load environment variables
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))
EBAY_CLIENT_ID = os.getenv("EBAY_CLIENT_ID")
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET")
GRADING_FEE = float(os.getenv("GRADING_FEE", 18.0))
PROFIT_THRESHOLD = float(os.getenv("PROFIT_THRESHOLD", 50.0))

# Globals
ebay_access_token = None
token_expiration = 0
last_alert_time = 0
alert_cooldown = 600  # 10 minutes
last_alerted_cards = {}  # card_name: timestamp

# Forbidden words to exclude unwanted listings
FORBIDDEN_WORDS = ["every", "set", "collection", "sealed", "lot", "cards", "custom", "madetoorder"]
FORBIDDEN_GRADES = ["psa", "cgc", "tag", "ace"]

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


def fetch_price(query):
    ensure_token()
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    headers = {
        "Authorization": f"Bearer {ebay_access_token}"
    }
    params = {
        "q": query,
        "limit": "5",
        "filter": "priceCurrency:USD"
    }
    try:
        res = requests.get(url, headers=headers, params=params)
        res.raise_for_status()
        items = res.json().get("itemSummaries", [])
        prices = [float(i["price"]["value"]) for i in items if "price" in i and float(i["price"]["value"]) <= 150000]
        return sum(prices) / len(prices) if prices else None
    except Exception as e:
        print(f"Error fetching eBay data for '{query}':", e)
        return None


def fetch_popular_pokemon_cards():
    ensure_token()
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    headers = {"Authorization": f"Bearer {ebay_access_token}"}
    params = {
        "q": "pokemon card",
        "limit": "20",
        "filter": "priceCurrency:USD",
        "sort": "-newlyListed"
    }
    try:
        res = requests.get(url, headers=headers, params=params)
        res.raise_for_status()
        data = res.json()
        cards = []
        for item in data.get("itemSummaries", []):
            title = item.get("title", "").lower()
            if any(word in title for word in FORBIDDEN_WORDS):
                continue
            if any(grade in title for grade in FORBIDDEN_GRADES):
                continue
            cards.append({
                "title": item["title"],
                "url": item.get("itemWebUrl")
            })
        return cards
    except Exception as e:
        print("❌ Failed to fetch trending cards:", e)
        return []


def fetch_first_item_url(query):
    """Helper to fetch the URL of the first eBay listing for a query."""
    ensure_token()
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    headers = {"Authorization": f"Bearer {ebay_access_token}"}
    params = {
        "q": query,
        "limit": "1",
        "filter": "priceCurrency:USD"
    }
    try:
        res = requests.get(url, headers=headers, params=params)
        res.raise_for_status()
        items = res.json().get("itemSummaries", [])
        if items:
            return items[0].get("itemWebUrl")
    except Exception as e:
        print(f"Error fetching URL for '{query}':", e)
    return None


def generate_card_embed(card_name, raw_price, psa10_price, psa9_price, url=None):
    profit10 = psa10_price - raw_price - GRADING_FEE
    profit9 = psa9_price - raw_price - GRADING_FEE if psa9_price else None

    embed = discord.Embed(
        title=f"🔥 Buy Alert: {card_name}",
        url=url,
        description="Potentially profitable Pokémon card for PSA grading!",
        color=discord.Color.gold(),
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="🪙 Raw Price", value=f"${raw_price:.2f}", inline=True)
    embed.add_field(name="💎 PSA 10 Price", value=f"${psa10_price:.2f}", inline=True)
    embed.add_field(name="💠 PSA 9 Price", value=f"${psa9_price:.2f}" if psa9_price else "N/A", inline=True)

    embed.add_field(name="📈 PSA 10 Profit", value=f"${profit10:.2f}", inline=True)
    embed.add_field(name="📉 PSA 9 Profit", value=f"${profit9:.2f}" if profit9 is not None else "N/A", inline=True)

    embed.set_footer(text="PokePriceTrackerBot — Smarter Investing in Pokémon")
    embed.set_thumbnail(url="https://yourdomain.com/logo.png")  # Replace with your logo URL

    return embed


@tasks.loop(minutes=2)
async def check_card_prices():
    global last_alert_time, last_alerted_cards
    print("🔍 Checking card prices...")
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print("⚠️ Channel not found.")
        return

    cards = fetch_popular_pokemon_cards()
    if not cards:
        await channel.send("❌ Failed to fetch Pokémon card data from eBay.")
        return

    guild = channel.guild
    role = discord.utils.get(guild.roles, name="Grading Alerts")

    for card in cards:
        card_name = card["title"]
        card_url = card.get("url")

        # Check 24h cooldown per card
        last_card_alert = last_alerted_cards.get(card_name, 0)
        if time.time() - last_card_alert < 86400:  # 24 hours
            continue

        raw_price = fetch_price(card_name)
        psa10_price = fetch_price(f"{card_name} PSA 10")
        psa9_price = fetch_price(f"{card_name} PSA 9")

        if raw_price and psa10_price:
            profit10 = psa10_price - raw_price - GRADING_FEE
            if profit10 >= PROFIT_THRESHOLD and time.time() - last_alert_time > alert_cooldown:
                last_alert_time = time.time()
                last_alerted_cards[card_name] = time.time()
                embed = generate_card_embed(card_name, raw_price, psa10_price, psa9_price, url=card_url)
                if role:
                    await channel.send(content=role.mention, embed=embed)
                else:
                    await channel.send(embed=embed)


@bot.command()
async def price(ctx, *, card_name: str):
    raw_price = fetch_price(card_name)
    psa10_price = fetch_price(f"{card_name} PSA 10")
    psa9_price = fetch_price(f"{card_name} PSA 9")
    url = fetch_first_item_url(card_name)

    if raw_price and psa10_price:
        embed = generate_card_embed(card_name, raw_price, psa10_price, psa9_price, url=url)
        await ctx.send(embed=embed)
    else:
        await ctx.send("❌ Could not fetch prices for that card.")


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    check_card_prices.start()


bot.run(DISCORD_TOKEN)
