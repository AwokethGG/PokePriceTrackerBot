import os
import time
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

LOGO_URL = "https://yourdomain.com/logo.png"  # Your logo URL
TARGET_CHANNEL_ID = 1402461253691113584

ALERT_COOLDOWN = 180       # 3 minutes global cooldown (seconds)
CARD_COOLDOWN = 86400      # 24 hours per-card cooldown (seconds)

last_alert_time = 0  # For global cooldown
last_alerted_cards = {}  # Dictionary to track last alert time per card

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
    global last_alert_time, last_alerted_cards

    current_time = time.time()
    if current_time - last_alert_time < ALERT_COOLDOWN:
        return  # Global cooldown active

    mock_cards = [
        {"name": "Charizard Base Set", "raw": 65.00, "graded": 215.00},
        {"name": "Pikachu Jungle", "raw": 15.00, "graded": 90.00},
    ]

    channel = bot.get_channel(TARGET_CHANNEL_ID)
    if channel is None:
        print(f"⚠️ Channel ID {TARGET_CHANNEL_ID} not found.")
        return

    for card in mock_cards:
        card_name = card["name"]
        profit = card["graded"] - card["raw"] - 40  # grading fee example

        # Check if this card was alerted in last 24 hours
        last_card_alert = last_alerted_cards.get(card_name, 0)
        if current_time - last_card_alert < CARD_COOLDOWN:
            continue  # Skip, alerted too recently

        if profit >= 50:  # Alert threshold
            embed = generate_card_alert_embed(card_name, card["raw"], card["graded"], profit, LOGO_URL)
            role = discord.utils.get(channel.guild.roles, name="Grading Alerts")

            if role:
                try:
                    await channel.send(content=f"{role.mention} 📢", embed=embed)
                except discord.Forbidden:
                    await channel.send(embed=embed)
            else:
                await channel.send(embed=embed)

            last_alert_time = current_time
            last_alerted_cards[card_name] = current_time
            break  # Only send one alert per loop

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
