import discord
import os
from discord.ext import commands, tasks
from dotenv import load_dotenv
from price_tracker import check_card_prices

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    price_alert.start()

@tasks.loop(minutes=60)
async def price_alert():
    channel = bot.get_channel(CHANNEL_ID)
    alerts = check_card_prices()
    for alert in alerts:
        await channel.send(alert)

bot.run(TOKEN)