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
GRADING_FEE = float(os.getenv("GRADING_FEE", 18.0))  # Default PSA grading fee
PROFIT_THRESHOLD = float(os.getenv("PROFIT_THRESHOLD", 50.0))  # Min profit to alert

# Globals
ebay_access_token = None
token_expiration = 0
last_alert_time = 0
alert_cooldown = 120  # 2 minutes

# Forbidden words to exclude unwanted listings
FORBIDDEN_WORDS = ["every", "set", "collection", "sealed", "lot"]
GRADE_TERMS = ["psa", "cgc", "ace", "tag"]

# Bot setup
intents = discord.Intents.default()
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
        "limit": "15",
        "filter": "priceCurrency:USD",
        "sort": "-price"
    }
    try:
        res = requests.get(url, headers=headers, params=params)
        res.raise_for_status()
        data = res.json()
        titles = []
        for item in data.get("itemSummaries", []):
            title = item.get("title", "").lower()
            if any(word in title for word in FORBIDDEN_WORDS + GRADE_TERMS):
                continue
            titles.append(item["title"])
        return titles
    except Exception as e:
        print("❌ Failed to fetch trending cards:", e)
        return []

@tasks.loop(minutes=2)
async def check_card_prices():
    global last_alert_time
    print("🔍 Checking card prices...")
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print("⚠️ Channel not found.")
        return

    cards = fetch_popular_pokemon_cards()
    if not cards:
        await channel.send("❌ Failed to fetch Pokémon card data from eBay.")
        return

    for card in cards:
        raw_price = fetch_price(card)
        psa10_price = fetch_price(f"{card} PSA 10")

        if raw_price and psa10_price:
            profit = psa10_price - raw_price - GRADING_FEE
            if profit >= PROFIT_THRESHOLD and time.time() - last_alert_time > alert_cooldown:
                last_alert_time = time.time()
                message = (
                    f"💰 **{card}** looks profitable for PSA 10 grading!\n"
                    f"- Raw Price: ${raw_price:.2f}\n"
                    f"- PSA 10 Avg: ${psa10_price:.2f}\n"
                    f"- Grading Fee: ${GRADING_FEE:.2f}\n"
                    f"- **Estimated Profit: ${profit:.2f}**"
                )
                await channel.send(message)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    check_card_prices.start()

bot.run(DISCORD_TOKEN)
