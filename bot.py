import discord
from discord.ext import commands, tasks
import asyncio
import datetime
from collections import defaultdict

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

PRICE_CHECK_CHANNEL_ID = 1402495298655490088
ALERT_CHANNEL_ID = 1402461253691113584
GRADING_ALERTS_ROLE_ID = 1402488093356982392
LOGO_URL = 'https://your-logo-url.png'      # Replace with your logo URL

intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Cache to store card check timestamps
card_check_cache = defaultdict(lambda: datetime.datetime.min)

# Simulated card database
card_database = {
    "charizard base": {
        "raw_price": 120.00,
        "psa9_price": 320.00,
        "psa10_price": 850.00
    },
    "pikachu jungle": {
        "raw_price": 12.00,
        "psa9_price": 35.00,
        "psa10_price": 75.00
    }
}


def get_card_data(card_name):
    card_name = card_name.lower().strip()
    return card_database.get(card_name)


def calculate_profit(raw, psa10):
    return round(psa10 - raw, 2)


def build_price_embed(card_name, raw, psa9, psa10):
    embed = discord.Embed(
        title=f"💳 {card_name.title()} Price Check",
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=LOGO_URL)
    embed.add_field(name="Raw Price", value=f"${raw:.2f}", inline=True)
    embed.add_field(name="PSA 9 Price", value=f"${psa9:.2f}", inline=True)
    embed.add_field(name="PSA 10 Price", value=f"${psa10:.2f}", inline=True)
    embed.add_field(name="💰 Potential Profit", value=f"${calculate_profit(raw, psa10):.2f}", inline=False)
    embed.set_footer(text="PokePrice Tracker • Powered by Cody Bloomberg")
    return embed


@bot.command()
async def price(ctx, *, card_name: str):
    card_data = get_card_data(card_name)
    if not card_data:
        await ctx.send(f"❌ Could not find data for '{card_name}'.")
        return

    channel = bot.get_channel(PRICE_CHECK_CHANNEL_ID)
    embed = build_price_embed(card_name, card_data["raw_price"], card_data["psa9_price"], card_data["psa10_price"])
    await channel.send(embed=embed)


@tasks.loop(minutes=3)
async def price_alerts():
    channel = bot.get_channel(ALERT_CHANNEL_ID)
    role = f"<@&{GRADING_ALERTS_ROLE_ID}>"

    for card_name, data in card_database.items():
        last_checked = card_check_cache[card_name]
        if (datetime.datetime.utcnow() - last_checked).total_seconds() < 86400:
            continue  # Skip if checked in last 24h

        raw = data["raw_price"]
        psa10 = data["psa10_price"]
        psa9 = data["psa9_price"]
        profit = calculate_profit(raw, psa10)

        if profit >= 100:  # Arbitrary profit threshold
            embed = build_price_embed(card_name, raw, psa9, psa10)
            message = await channel.send(content=role, embed=embed)
            await message.add_reaction("👍")
            await message.add_reaction("❌")
            card_check_cache[card_name] = datetime.datetime.utcnow()
            break  # Only send one alert per 3 minutes


@bot.event
async def on_ready():
    print(f"{bot.user} is online and monitoring prices...")
    price_alerts.start()

bot.run(TOKEN)
