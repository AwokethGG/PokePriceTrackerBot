import os
import time
import discord
import requests
from discord.ext import commands, tasks
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
EBAY_TOKEN = os.getenv("EBAY_APP_TOKEN")

LOGO_URL = "https://yourdomain.com/logo.png"
TARGET_CHANNEL_ID = 1402461253691113584
PRICE_CHECK_CHANNEL_ID = 1402495298655490088

ALERT_COOLDOWN = 180      # 3 minutes
CARD_COOLDOWN = 86400     # 24 hours

last_alert_time = 0
last_alerted_cards = {}

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

def fetch_ebay_price(query):
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    headers = {
        "Authorization": f"Bearer {EBAY_TOKEN}",
        "Content-Type": "application/json"
    }
    params = {
        "q": query,
        "filter": "priceCurrency:USD",
        "limit": "10",
        "sort": "price"
    }

    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        items = data.get("itemSummaries", [])
        if not items:
            return None
        prices = [float(item["price"]["value"]) for item in items if "price" in item]
        if not prices:
            return None
        return sum(prices) / len(prices)
    except Exception as e:
        print(f"Error fetching eBay data for '{query}': {e}")
        return None

@tasks.loop(minutes=5)
async def check_card_prices():
    global last_alert_time, last_alerted_cards

    current_time = time.time()
    if current_time - last_alert_time < ALERT_COOLDOWN:
        return

    # You can change or expand this list dynamically later
    card_list = [
        {"name": "Mew ex 232/091"},
        {"name": "Charizard Base Set"},
        {"name": "Pikachu Jungle"}
    ]

    channel = bot.get_channel(TARGET_CHANNEL_ID)
    if channel is None:
        print(f"⚠️ Channel ID {TARGET_CHANNEL_ID} not found.")
        return

    for card in card_list:
        name = card["name"]

        raw_price = fetch_ebay_price(f"{name} raw")
        psa10_price = fetch_ebay_price(f"{name} PSA 10")
        psa9_price = fetch_ebay_price(f"{name} PSA 9")

        if not raw_price or not psa10_price or not psa9_price:
            print(f"❌ Could not retrieve full price data for {name}")
            continue

        profit = psa10_price - raw_price - 40
        if profit < 50:
            continue

        last_card_alert = last_alerted_cards.get(name, 0)
        if current_time - last_card_alert < CARD_COOLDOWN:
            continue

        embed = generate_card_embed(name, raw_price, psa10_price, psa9_price, LOGO_URL, title="🔥 Buy Alert!")
        role = discord.utils.get(channel.guild.roles, name="Grading Alerts")

        try:
            msg = await channel.send(content=f"{role.mention} 📢" if role else "", embed=embed)
            await msg.add_reaction("👍")
            await msg.add_reaction("❌")
        except discord.Forbidden:
            await channel.send(embed=embed)

        last_alert_time = current_time
        last_alerted_cards[name] = current_time
        break

@bot.command(name="price")
async def price_command(ctx, *, card_name: str):
    raw = fetch_ebay_price(f"{card_name} raw")
    psa10 = fetch_ebay_price(f"{card_name} PSA 10")
    psa9 = fetch_ebay_price(f"{card_name} PSA 9")

    if not raw or not psa10 or not psa9:
        await ctx.send(f"❌ Could not get full price data for {card_name}")
        return

    embed = generate_card_embed(card_name, raw, psa10, psa9, LOGO_URL, title="📊 Price Check")
    price_channel = bot.get_channel(PRICE_CHECK_CHANNEL_ID)
    if price_channel:
        await price_channel.send(embed=embed)
    else:
        await ctx.send(embed=embed)

@bot.command(name="alerttest")
async def alert_test(ctx):
    global last_alert_time

    current_time = time.time()
    if current_time - last_alert_time < ALERT_COOLDOWN:
        remaining = int(ALERT_COOLDOWN - (current_time - last_alert_time))
        await ctx.send(f"🕒 Please wait {remaining} seconds before sending another alert.")
        return

    card_name = "Charizard Base Set"
    raw_price = 60.0
    psa10_price = 190.0
    psa9_price = 110.0

    embed = generate_card_embed(card_name, raw_price, psa10_price, psa9_price, LOGO_URL, title="🔥 Buy Alert!")
    role = discord.utils.get(ctx.guild.roles, name="Grading Alerts")

    try:
        msg = await ctx.send(content=f"{role.mention} 📢" if role else "", embed=embed)
        await msg.add_reaction("👍")
        await msg.add_reaction("❌")
    except discord.Forbidden:
        await ctx.send(embed=embed)

    last_alert_time = current_time

@bot.event
async def on_ready():
    print(f"✅ Bot is online as {bot.user}")
    check_card_prices.start()

bot.run(TOKEN)
