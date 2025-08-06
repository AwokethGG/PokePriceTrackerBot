import os
import time
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from datetime import datetime

# Load .env variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# 👇 Replace with your actual hosted logo URL
LOGO_URL = "https://yourdomain.com/logo.png"

# 👇 Replace with your actual target Discord channel ID
TARGET_CHANNEL_ID = 1402461253691113584

# Cooldown timer (in seconds)
ALERT_COOLDOWN = 180  # 3 minutes
last_alert_time = 0

# Set up bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# 🔧 Function to create standardized embed
def generate_card_alert_embed(card_name, raw_price, graded_price, profit, logo_url):
    embed = discord.Embed(
        title="🔥 Buy Alert!",
        description=f"**{card_name}** is showing great potential for grading and resale!",
        color=discord.Color.orange(),
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="🪙 Raw Price", value=f"${raw_price:.2f}", inline=True)
    embed.add_field(name="💎 Graded Price (PSA 10)", value=f"${graded_price:.2f}", inline=True)
    embed.add_field(name="📈 Estimated Profit", value=f"${profit:.2f}", inline=False)
    embed.set_thumbnail(url=logo_url)
    embed.set_footer(text="PokePriceTrackerBot — Smarter Investing in Pokémon", icon_url=logo_url)
    return embed

# 🚀 Background task to auto-check card prices
@tasks.loop(minutes=5)
async def check_card_prices():
    global last_alert_time

    current_time = time.time()
    if current_time - last_alert_time < ALERT_COOLDOWN:
        return  # ⛔ Don't alert if within cooldown window

    # 🔁 Replace this list with dynamic API results later
    mock_cards = [
        {"name": "Charizard Base Set", "raw": 65.00, "graded": 215.00},
        {"name": "Pikachu Jungle", "raw": 15.00, "graded": 90.00},
    ]

    for card in mock_cards:
        profit = card["graded"] - card["raw"] - 40  # assume $40 grading fee
        if profit >= 50:  # threshold to trigger alert
            embed = generate_card_alert_embed(card["name"], card["raw"], card["graded"], profit, LOGO_URL)
            channel = bot.get_channel(TARGET_CHANNEL_ID)
            if channel:
                await channel.send(embed=embed)
                last_alert_time = current_time
            break  # ✅ Only one alert every loop

# ✅ Manual command to trigger test
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
    graded_price = 190.0
    profit = 90.0

    embed = generate_card_alert_embed(card_name, raw_price, graded_price, profit, LOGO_URL)
    await ctx.send(embed=embed)
    last_alert_time = current_time

# 🔁 Start auto-checker on bot ready
@bot.event
async def on_ready():
    print(f"✅ Bot is online as {bot.user}")
    check_card_prices.start()

bot.run(TOKEN)
