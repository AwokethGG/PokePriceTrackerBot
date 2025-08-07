import os
import time
import requests
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import base64
from datetime import datetime

load_dotenv()

# Load environment variables with checks
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise ValueError("Missing DISCORD_TOKEN environment variable.")

channel_id_str = os.getenv("DISCORD_CHANNEL_ID")
if not channel_id_str:
    raise ValueError("Missing DISCORD_CHANNEL_ID environment variable.")
CHANNEL_ID = int(channel_id_str)

EBAY_CLIENT_ID = os.getenv("EBAY_CLIENT_ID")
if not EBAY_CLIENT_ID:
    raise ValueError("Missing EBAY_CLIENT_ID environment variable.")

EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET")
if not EBAY_CLIENT_SECRET:
    raise ValueError("Missing EBAY_CLIENT_SECRET environment variable.")

GRADING_FEE = float(os.getenv("GRADING_FEE", 18.0))  # Default PSA grading fee
PROFIT_THRESHOLD = float(os.getenv("PROFIT_THRESHOLD", 50.0))  # Min profit to alert

ALERT_COOLDOWN = 300       # 5 minutes between alerts globally
CARD_COOLDOWN = 86400      # 24 hours cooldown per card

# Globals
ebay_access_token = None
token_expiration = 0
last_alert_time = 0
last_alerted_cards = {}

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

    try:
        response = requests.post("https://api.ebay.com/identity/v1/oauth2/token", headers=headers, data=data)
        response.raise_for_status()
        token_data = response.json()
        ebay_access_token = token_data["access_token"]
        token_expiration = time.time() + token_data["expires_in"]
        print("✅ eBay token acquired.")
    except requests.exceptions.RequestException as e:
        print("❌ Failed to fetch eBay token:", e)
        ebay_access_token = None


def ensure_token():
    if not ebay_access_token or time.time() >= token_expiration:
        get_ebay_token()


def fetch_price(query):
    ensure_token()
    if not ebay_access_token:
        print("❌ No valid eBay token available to fetch price.")
        return None

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
        prices = []
        for i in items:
            if "price" in i:
                price_val = float(i["price"]["value"])
                if price_val < 150000:  # Exclude unrealistic/very high prices
                    prices.append(price_val)
        return sum(prices) / len(prices) if prices else None
    except Exception as e:
        print(f"Error fetching eBay data for '{query}':", e)
        return None


def fetch_popular_pokemon_cards():
    ensure_token()
    if not ebay_access_token:
        print("❌ No valid eBay token available to fetch popular cards.")
        return []

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
        titles = [item["title"] for item in data.get("itemSummaries", []) if "title" in item]
        return titles
    except Exception as e:
        print("❌ Failed to fetch trending cards:", e)
        return []


def generate_card_embed(card_name, raw_price, psa10_price, grading_fee, profit):
    embed = discord.Embed(
        title="🔥 Buy Alert! Profitable Pokémon Card Found",
        description=f"**{card_name}** looks profitable for PSA 10 grading!",
        color=discord.Color.gold(),
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="🪙 Raw Price", value=f"${raw_price:.2f}", inline=True)
    embed.add_field(name="💎 PSA 10 Price", value=f"${psa10_price:.2f}", inline=True)
    embed.add_field(name="💰 Grading Fee", value=f"${grading_fee:.2f}", inline=True)
    embed.add_field(name="📈 Estimated Profit", value=f"${profit:.2f}", inline=False)
    embed.set_footer(text="PokePriceTrackerBot — Smarter Investing in Pokémon")
    return embed


@tasks.loop(minutes=1)
async def check_card_prices():
    global last_alert_time, last_alerted_cards
    print("🔍 Checking card prices...")
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print("⚠️ Channel not found.")
        return

    current_time = time.time()
    if current_time - last_alert_time < ALERT_COOLDOWN:
        # Still cooling down globally, skip this run
        return

    cards = fetch_popular_pokemon_cards()
    if not cards:
        try:
            await channel.send("❌ Failed to fetch Pokémon card data from eBay.")
        except Exception as e:
            print("❌ Could not send error message to Discord channel:", e)
        return

    for card in cards:
        # Skip cards alerted recently
        last_card_alert = last_alerted_cards.get(card, 0)
        if current_time - last_card_alert < CARD_COOLDOWN:
            continue

        raw_price = fetch_price(card)
        psa10_price = fetch_price(f"{card} PSA 10")

        if raw_price and psa10_price:
            profit = psa10_price - raw_price - GRADING_FEE
            if profit >= PROFIT_THRESHOLD:
                embed = generate_card_embed(card, raw_price, psa10_price, GRADING_FEE, profit)
                try:
                    msg = await channel.send(embed=embed)
                    await msg.add_reaction("👍")
                    await msg.add_reaction("❌")
                    # Update cooldown trackers
                    last_alert_time = current_time
                    last_alerted_cards[card] = current_time
                    break  # Only one alert per run
                except Exception as e:
                    print("❌ Failed to send alert message to Discord channel:", e)


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    check_card_prices.start()


bot.run(DISCORD_TOKEN)
