import os
import time
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

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

def generate_card_embed(card_name, raw_price, graded_price_10, graded_price_9, profit, logo_url, title="Card Info"):
    embed = discord.Embed(
        title=title,
        description=f"Here is the price breakdown for **{card_name}**:",
        color=discord.Color.blue(),
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="🪙 Raw Price", value=f"${raw_price:.2f}", inline=True)
    embed.add_field(name="💎 PSA 10 Price", value=f"${graded_price_10:.2f}", inline=True)
    embed.add_field(name="🥈 PSA 9 Price", value=f"${graded_price_9:.2f}", inline=True)
    embed.add_field(name="📈 Estimated Profit (PSA 10)", value=f"${profit:.2f}", inline=False)
    embed.set_thumbnail(url=logo_url)
    embed.set_footer(text="PokePriceTrackerBot — Smarter Investing in Pokémon", icon_url=logo_url)
    return embed

@tasks.loop(minutes=5)
async def check_card_prices():
    global last_alert_time, last_alerted_cards

    current_time = time.time()
    if current_time - last_alert_time < ALERT_COOLDOWN:
        return

    # Mock cards, replace with real API calls
    mock_cards = [
        {"name": "Charizard Base Set", "raw": 65.00, "psa10": 215.00, "psa9": 130.00},
        {"name": "Pikachu Jungle", "raw": 15.00, "psa10": 90.00, "psa9": 50.00},
    ]

    channel = bot.get_channel(TARGET_CHANNEL_ID)
    if channel is None:
        print(f"⚠️ Channel ID {TARGET_CHANNEL_ID} not found.")
        return

    for card in mock_cards:
        card_name = card["name"]
        raw = card["raw"]
        psa10 = card["psa10"]
        psa9 = card["psa9"]
        profit = psa10 - raw - 40  # Example grading fee

        last_card_alert = last_alerted_cards.get(card_name, 0)
        if current_time - last_card_alert < CARD_COOLDOWN:
            continue

        if profit >= 50:
            embed = generate_card_embed(card_name, raw, psa10, psa9, profit, LOGO_URL, title="🔥 Buy Alert!")
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
    raw = 60.0
    psa10 = 190.0
    psa9 = 125.00
    profit = psa10 - raw - 40

    embed = generate_card_embed(card_name, raw, psa10, psa9, profit, LOGO_URL, title="🔥 Buy Alert!")
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
    mock_data = {
        "Charizard Base Set": {"raw": 65.00, "psa10": 215.00, "psa9": 130.00},
        "Pikachu Jungle": {"raw": 15.00, "psa10": 90.00, "psa9": 50.00},
    }

    data = mock_data.get(card_name)
    if not data:
        await ctx.send(f"❌ Sorry, no price data found for '{card_name}'.")
        return

    raw = data["raw"]
    psa10 = data["psa10"]
    psa9 = data["psa9"]
    profit = psa10 - raw - 40  # grading fee example

    embed = generate_card_embed(card_name, raw, psa10, psa9, profit, LOGO_URL, title="📊 Price Check")

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
