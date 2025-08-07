import os
import time
import discord
import requests
from discord.ext import commands, tasks
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
EBAY_CLIENT_ID = os.getenv("EBAY_CLIENT_ID")
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET")

LOGO_URL = "https://yourdomain.com/logo.png"
TARGET_CHANNEL_ID = 1402461253691113584
PRICE_CHECK_CHANNEL_ID = 1402495298655490088

ALERT_COOLDOWN = 180
CARD_COOLDOWN = 86400
last_alert_time = 0
last_alerted_cards = {}
ebay_access_token = None
token_expiry_time = datetime.utcnow()

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

def generate_card_embed(card_name, raw_price, psa10_price, psa9_price, logo_url, title="Card Info"):
    profit_psa10 = psa10_price - raw_price - 40
    profit_psa9 = psa9_price - raw_price - 40
    embed = discord.Embed(
        title=title,
        description=f"Here is the price breakdown for **{card_name}**:",
        color=discord.Color.blue(),
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="🪙 Raw Price", value=f"${raw_price:.2f}", inline=True)
    embed.add_field(name="💎 PSA 10 Price", value=f"${psa10_price:.2f}", inline=True)
    embed.add_field(name="💠 PSA 9 Price", value=f"${psa9_price:.2f}", inline=True)
    embed.add_field(name="📈 PSA 10 Profit", value=f"${profit_psa10:.2f}", inline=True)
    embed.add_field(name="📉 PSA 9 Profit", value=f"${profit_psa9:.2f}", inline=True)
    embed.set_thumbnail(url=logo_url)
    embed.set_footer(text="PokePriceTrackerBot — Smarter Investing in Pokémon", icon_url=logo_url)
    return embed

def refresh_ebay_token():
    global ebay_access_token, token_expiry_time

    url = "https://api.ebay.com/identity/v1/oauth2/token"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": "Basic " + base64_encode(f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}")
    }
    data = {
        "grant_type": "client_credentials",
        "scope": "https://api.ebay.com/oauth/api_scope"
    }
    response = requests.post(url, headers=headers, data=data)
    if response.status_code == 200:
        token_data = response.json()
        ebay_access_token = token_data["access_token"]
        token_expiry_time = datetime.utcnow() + timedelta(seconds=token_data["expires_in"])
        print("🔑 eBay token refreshed.")
    else:
        print("❌ Failed to refresh eBay token:", response.text)

def base64_encode(text):
    import base64
    return base64.b64encode(text.encode()).decode()

def ensure_token():
    if not ebay_access_token or datetime.utcnow() >= token_expiry_time:
        refresh_ebay_token()

def fetch_ebay_price(query):
    ensure_token()
    headers = {"Authorization": f"Bearer {ebay_access_token}"}
    params = {"q": query, "limit": "10", "filter": "priceCurrency:USD"}
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"

    try:
        res = requests.get(url, headers=headers, params=params)
        res.raise_for_status()
        data = res.json()
        prices = [
            float(item["price"]["value"])
            for item in data.get("itemSummaries", [])
            if "price" in item
        ]
        return sum(prices) / len(prices) if prices else None
    except Exception as e:
        print(f"❌ Error fetching eBay data for '{query}':", str(e))
        return None

@tasks.loop(minutes=5)
async def check_card_prices():
    global last_alert_time, last_alerted_cards

    current_time = time.time()
    if current_time - last_alert_time < ALERT_COOLDOWN:
        return

    cards = [
        "Charizard Base Set",
        "Pikachu Jungle",
        "Mew ex 232/091",
        "Lugia Neo Genesis",
    ]

    channel = bot.get_channel(TARGET_CHANNEL_ID)
    if not channel:
        print(f"⚠️ Channel ID {TARGET_CHANNEL_ID} not found.")
        return

    for name in cards:
        raw = fetch_ebay_price(name)
        psa10 = fetch_ebay_price(f"{name} PSA 10")
        psa9 = fetch_ebay_price(f"{name} PSA 9")

        if not all([raw, psa10, psa9]):
            continue

        profit = psa10 - raw - 40
        last_card_alert = last_alerted_cards.get(name, 0)
        if current_time - last_card_alert < CARD_COOLDOWN:
            continue

        if profit >= 50:
            embed = generate_card_embed(name, raw, psa10, psa9, LOGO_URL, title="🔥 Buy Alert!")
            role = discord.utils.get(channel.guild.roles, name="Grading Alerts")

            try:
                if role:
                    msg = await channel.send(content=f"{role.mention} 📢", embed=embed)
                else:
                    msg = await channel.send(embed=embed)

                await msg.add_reaction("👍")
                await msg.add_reaction("❌")
                last_alert_time = current_time
                last_alerted_cards[name] = current_time
                break
            except discord.Forbidden:
                pass

@bot.command(name="alerttest")
async def alert_test(ctx):
    card = "Charizard Base Set"
    raw = fetch_ebay_price(card)
    psa10 = fetch_ebay_price(f"{card} PSA 10")
    psa9 = fetch_ebay_price(f"{card} PSA 9")

    if not all([raw, psa10, psa9]):
        await ctx.send("❌ Could not fetch prices from eBay.")
        return

    embed = generate_card_embed(card, raw, psa10, psa9, LOGO_URL, title="🔥 Test Alert")
    role = discord.utils.get(ctx.guild.roles, name="Grading Alerts")

    try:
        if role:
            msg = await ctx.send(content=f"{role.mention} 📢", embed=embed)
        else:
            msg = await ctx.send(embed=embed)

        await msg.add_reaction("👍")
        await msg.add_reaction("❌")
    except discord.Forbidden:
        pass

@bot.command(name="price")
async def price_command(ctx, *, card: str):
    raw = fetch_ebay_price(card)
    psa10 = fetch_ebay_price(f"{card} PSA 10")
    psa9 = fetch_ebay_price(f"{card} PSA 9")

    if not all([raw, psa10, psa9]):
        await ctx.send("❌ Could not fetch prices from eBay.")
        return

    embed = generate_card_embed(card, raw, psa10, psa9, LOGO_URL, title="📊 Price Check")
    price_channel = bot.get_channel(PRICE_CHECK_CHANNEL_ID)

    if price_channel:
        await price_channel.send(embed=embed)
    else:
        await ctx.send(embed=embed)

@bot.event
async def on_ready():
    print(f"✅ Bot is online as {bot.user}")
    refresh_ebay_token()
    check_card_prices.start()

bot.run(TOKEN)
