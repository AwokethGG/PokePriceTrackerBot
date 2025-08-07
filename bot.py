import os
import time
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import requests
from xml.etree import ElementTree
from datetime import datetime

# Load env vars from Railway or local .env
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
EBAY_APP_ID = os.getenv("EBAY_APP_ID")

LOGO_URL = "https://yourdomain.com/logo.png"  # Replace with your logo URL
TARGET_CHANNEL_ID = 1402461253691113584       # Your alert channel ID
PRICE_CHECK_CHANNEL_ID = 1402495298655490088  # Your price check channel ID

ALERT_COOLDOWN = 180      # 3 minutes between any alerts
CARD_COOLDOWN = 86400     # 24 hours cooldown per card

last_alert_time = 0
last_alerted_cards = {}

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# PSA prices for cards (update as you want)
PSA_PRICE_DATA = {
    "Charizard Base Set": {"psa10": 215.00, "psa9": 120.00},
    "Pikachu Jungle": {"psa10": 90.00, "psa9": 50.00},
}

EBAY_FINDING_ENDPOINT = "https://svcs.ebay.com/services/search/FindingService/v1"

def fetch_ebay_average_price(card_name: str, entries_per_page=10):
    """
    Uses eBay Finding API to get average sold price of used cards for `card_name`.
    """
    params = {
        "OPERATION-NAME": "findCompletedItems",
        "SERVICE-VERSION": "1.0.0",
        "SECURITY-APPNAME": EBAY_APP_ID,
        "RESPONSE-DATA-FORMAT": "XML",
        "REST-PAYLOAD": "",
        "keywords": card_name,
        "itemFilter(0).name": "SoldItemsOnly",
        "itemFilter(0).value": "true",
        "itemFilter(1).name": "Condition",
        "itemFilter(1).value": "3000",  # Used condition
        "paginationInput.entriesPerPage": str(entries_per_page),
        "sortOrder": "PricePlusShippingLowest"
    }

    try:
        response = requests.get(EBAY_FINDING_ENDPOINT, params=params)
        response.raise_for_status()

        root = ElementTree.fromstring(response.content)

        prices = []
        # Namespace for eBay Finding API XML
        ns = {'ebay': 'http://www.ebay.com/marketplace/search/v1/services'}

        for item in root.findall('.//{http://www.ebay.com/marketplace/search/v1/services}item'):
            selling_status = item.find('{http://www.ebay.com/marketplace/search/v1/services}sellingStatus')
            if selling_status is None:
                continue

            current_price = selling_status.find('{http://www.ebay.com/marketplace/search/v1/services}currentPrice')
            if current_price is not None and current_price.text:
                prices.append(float(current_price.text))

        if prices:
            avg_price = sum(prices) / len(prices)
            return avg_price
        else:
            return None

    except Exception as e:
        print(f"Error fetching eBay data: {e}")
        return None


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


@tasks.loop(minutes=5)
async def check_card_prices():
    global last_alert_time, last_alerted_cards

    current_time = time.time()
    if current_time - last_alert_time < ALERT_COOLDOWN:
        return

    channel = bot.get_channel(TARGET_CHANNEL_ID)
    if channel is None:
        print(f"⚠️ Channel ID {TARGET_CHANNEL_ID} not found.")
        return

    for card_name, psa_prices in PSA_PRICE_DATA.items():
        raw_price = fetch_ebay_average_price(card_name)
        if raw_price is None:
            print(f"Could not fetch price for {card_name}")
            continue

        psa10_price = psa_prices["psa10"]
        psa9_price = psa_prices["psa9"]
        profit = psa10_price - raw_price - 40  # $40 grading fee assumed

        last_card_alert = last_alerted_cards.get(card_name, 0)
        if current_time - last_card_alert < CARD_COOLDOWN:
            continue

        if profit >= 50:
            embed = generate_card_embed(card_name, raw_price, psa10_price, psa9_price, LOGO_URL, title="🔥 Buy Alert!")
            role = discord.utils.get(channel.guild.roles, name="Grading Alerts")

            if role:
                try:
                    msg = await channel.send(content=f"{role.mention} 📢", embed=embed)
                except discord.Forbidden:
                    msg = await channel.send(embed=embed)
            else:
                msg = await channel.send(embed=embed)

            await msg.add_reaction("👍")
            await msg.add_reaction("❌")

            last_alert_time = current_time
            last_alerted_cards[card_name] = current_time
            break


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

    if role:
        try:
            msg = await ctx.send(content=f"{role.mention} 📢", embed=embed)
        except discord.Forbidden:
            msg = await ctx.send(embed=embed)
    else:
        msg = await ctx.send(embed=embed)

    await msg.add_reaction("👍")
    await msg.add_reaction("❌")

    last_alert_time = current_time


@bot.command(name="price")
async def price_command(ctx, *, card_name: str):
    """Check prices for a specific card and post in the price-check channel."""
    psa_prices = PSA_PRICE_DATA.get(card_name)
    if not psa_prices:
        await ctx.send(f"❌ Sorry, no PSA price data found for '{card_name}'.")
        return

    raw_price = fetch_ebay_average_price(card_name)
    if raw_price is None:
        await ctx.send(f"❌ Could not fetch raw price for '{card_name}' from eBay.")
        return

    embed = generate_card_embed(card_name, raw_price, psa_prices["psa10"], psa_prices["psa9"], LOGO_URL, title="📊 Price Check")

    price_channel = bot.get_channel(PRICE_CHECK_CHANNEL_ID)
    if not price_channel:
        await ctx.send(f"❌ Could not find the price-check channel.")
        return

    await price_channel.send(embed=embed)


@bot.event
async def on_ready():
    print(f"✅ Bot is online as {bot.user}")
    check_card_prices.start()


bot.run(TOKEN)