import os
import time
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import requests
from xml.etree import ElementTree
from datetime import datetime

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
EBAY_APP_ID = os.getenv("EBAY_APP_ID")

LOGO_URL = "https://yourdomain.com/logo.png"  # Replace with your actual logo URL
TARGET_CHANNEL_ID = 1402461253691113584       # Your alert channel ID
PRICE_CHECK_CHANNEL_ID = 1402495298655490088  # Your price check channel ID

ALERT_COOLDOWN = 180      # 3 minutes between alerts
CARD_COOLDOWN = 86400     # 24 hours cooldown per card

last_alert_time = 0
last_alerted_cards = {}

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

EBAY_FINDING_ENDPOINT = "https://svcs.ebay.com/services/search/FindingService/v1"

# Cards you want to track - you can expand this dictionary or replace it with your own source
PSA_PRICE_DATA = {
    "Charizard Base Set": {},
    "Pikachu Jungle": {},
    # Add more cards here if needed
}


def fetch_ebay_average_price(card_name: str, condition: str, keyword_filter: str = "", entries_per_page=10):
    """
    Fetch average sold price from eBay Finding API for given card_name, condition, and optional keyword_filter.
    condition = eBay condition code (string), e.g. "3000" = used, "1000" = new.
    keyword_filter = additional keywords to refine search (like 'PSA 10').
    """
    keywords = card_name
    if keyword_filter:
        keywords += " " + keyword_filter

    params = {
        "OPERATION-NAME": "findCompletedItems",
        "SERVICE-VERSION": "1.0.0",
        "SECURITY-APPNAME": EBAY_APP_ID,
        "RESPONSE-DATA-FORMAT": "XML",
        "REST-PAYLOAD": "",
        "keywords": keywords,
        "itemFilter(0).name": "SoldItemsOnly",
        "itemFilter(0).value": "true",
        "itemFilter(1).name": "Condition",
        "itemFilter(1).value": condition,
        "paginationInput.entriesPerPage": str(entries_per_page),
        "sortOrder": "PricePlusShippingLowest"
    }

    try:
        response = requests.get(EBAY_FINDING_ENDPOINT, params=params)
        response.raise_for_status()

        root = ElementTree.fromstring(response.content)

        prices = []
        for item in root.findall('.//{http://www.ebay.com/marketplace/search/v1/services}item'):
            selling_status = item.find('{http://www.ebay.com/marketplace/search/v1/services}sellingStatus')
            if selling_status is None:
                continue

            current_price = selling_status.find('{http://www.ebay.com/marketplace/search/v1/services}currentPrice')
            if current_price is not None and current_price.text:
                prices.append(float(current_price.text))

        if prices:
            avg_price = sum(prices) / len(prices)
            print(f"[DEBUG] Avg price for '{keywords}' (condition {condition}): ${avg_price:.2f}")
            return avg_price
        else:
            print(f"[DEBUG] No prices found for '{keywords}' (condition {condition})")
            return None

    except Exception as e:
        print(f"Error fetching eBay data for '{keywords}': {e}")
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

    for card_name in PSA_PRICE_DATA.keys():
        # Fetch prices
        raw_price = fetch_ebay_average_price(card_name, condition="3000", keyword_filter="")
        psa10_price = fetch_ebay_average_price(card_name, condition="1000", keyword_filter="PSA 10")
        psa9_price = fetch_ebay_average_price(card_name, condition="1000", keyword_filter="PSA 9")

        if raw_price is None or psa10_price is None or psa9_price is None:
            print(f"[WARN] Missing price data for '{card_name}': raw={raw_price}, PSA10={psa10_price}, PSA9={psa9_price}")
            continue

        profit = psa10_price - raw_price - 40  # Grading fee assumed $40

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
    """
    Check prices for a specific card and post in the price-check channel.
    Fetches raw, PSA 10, and PSA 9 prices live from eBay.
    """
    channel = bot.get_channel(PRICE_CHECK_CHANNEL_ID)
    if channel is None:
        await ctx.send(f"❌ Price-check channel not found.")
        return

    # Fetch live prices
    raw_price = fetch_ebay_average_price(card_name, condition="3000", keyword_filter="")
    psa10_price = fetch_ebay_average_price(card_name, condition="1000", keyword_filter="PSA 10")
    psa9_price = fetch_ebay_average_price(card_name, condition="1000", keyword_filter="PSA 9")

    if raw_price is None or psa10_price is None or psa9_price is None:
        await ctx.send(f"❌ Could not fetch complete pricing data for '{card_name}'. Try again later or check the card name.")
        return

    embed = generate_card_embed(card_name, raw_price, psa10_price, psa9_price, LOGO_URL, title="📊 Price Check")
    await channel.send(embed=embed)


@bot.event
async def on_ready():
    print(f"✅ Bot is online as {bot.user}")
    check_card_prices.start()


bot.run(TOKEN)
