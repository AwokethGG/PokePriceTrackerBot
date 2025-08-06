import os
import time
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables from .env file
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Replace with your actual logo URL (hosted online)
LOGO_URL = "https://yourdomain.com/logo.png"

# Replace with your actual Discord channel ID for alerts (integer)
TARGET_CHANNEL_ID = 1402461253691113584

# Cooldown time in seconds
ALERT_COOLDOWN = 180  # 3 minutes cooldown
last_alert_time = 0

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


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


@tasks.loop(minutes=5)
async def check_card_prices():
    global last_alert_time

    current_time = time.time()
    if current_time - last_alert_time < ALERT_COOLDOWN:
        return  # Cooldown active, skip alert

    # TODO: Replace with your real price-checking logic & API calls
    mock_cards = [
        {"name": "Charizard Base Set", "raw": 65.00, "graded": 215.00},
        {"name": "Pikachu Jungle", "raw": 15.00, "graded": 90.00},
    ]

    channel = bot.get_channel(TARGET_CHANNEL_ID)
    if channel is None:
        print(f"⚠️ Channel ID {TARGET_CHANNEL_ID} not found.")
        return

    for card in mock_cards:
        profit = card["graded"] - card["raw"] - 40  # Example grading fee
        if profit >= 50:  # Alert threshold
            embed = generate_card_alert_embed(card["name"], card["raw"], card["graded"], profit, LOGO_URL)
            role = discord.utils.get(channel.guild.roles, name="Grading Alerts")

            if role:
                try:
                    await channel.send(content=f"{role.mention} 📢", embed=embed)
                except discord.Forbidden:
                    # Bot lacks permission to mention role
                    await channel.send(embed=embed)
            else:
                await channel.send(embed=embed)

            last_alert_time = current_time
            break  # Send only one alert per loop


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
    role = discord.utils.get(ctx.guild.roles, name="Grading Alerts")

    if role:
        try:
            await ctx.send(content=f"{role.mention} 📢", embed=embed)
        except discord.Forbidden:
            await ctx.send(embed=embed)
    else:
        await ctx.send(embed=embed)

    last_alert_time = current_time


@bot.event
async def on_ready():
    print(f"✅ Bot is online as {bot.user}")
    check_card_prices.start()


bot.run(TOKEN)
