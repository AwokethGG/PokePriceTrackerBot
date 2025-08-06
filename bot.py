import os
import time
import discord
from discord.ext import commands
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables from .env file
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Your logo URL for embed thumbnail and footer icon
LOGO_URL = "https://yourdomain.com/logo.png"  # ← Replace this with your actual logo URL

# Cooldown tracking (global alert delay)
last_alert_time = 0
ALERT_COOLDOWN = 180  # seconds (3 minutes)

# Set up bot intents
intents = discord.Intents.default()
intents.message_content = True

# Initialize bot
bot = commands.Bot(command_prefix="!", intents=intents)

# Embed generator function
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

# Bot ready event
@bot.event
async def on_ready():
    print(f"✅ Bot is online as {bot.user}")

# Sample alert test command
@bot.command(name="alerttest")
async def alert_test(ctx):
    global last_alert_time

    current_time = time.time()
    if current_time - last_alert_time < ALERT_COOLDOWN:
        remaining = int(ALERT_COOLDOWN - (current_time - last_alert_time))
        await ctx.send(f"🕒 Please wait {remaining} seconds before sending another alert.")
        return

    # Replace these with actual data later
    card_name = "Charizard Base Set"
    raw_price = 60.0
    graded_price = 190.0
    profit = 90.0

    embed = generate_card_alert_embed(card_name, raw_price, graded_price, profit, LOGO_URL)
    await ctx.send(embed=embed)

    last_alert_time = current_time

# Run the bot
bot.run(TOKEN)
