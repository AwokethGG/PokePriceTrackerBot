import os
import discord
from discord.ext import commands
from ebay_api import search_ebay, get_recent_sales
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))
ROLE_ID = int(os.getenv("DISCORD_ROLE_ID"))  # @Grading Alerts role

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Cache to avoid repeated alerts
last_alert_times = {}
ALERT_COOLDOWN = timedelta(hours=24)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')

@bot.command()
async def pricecheck(ctx, *, card_name):
    card_info = search_ebay(card_name)
    if not card_info:
        await ctx.send(f"❌ Could not find any listings for '{card_name}' on eBay.")
        return

    raw_sales = get_recent_sales(card_name, 'raw')
    psa9_sales = get_recent_sales(card_name, 'psa9')
    psa10_sales = get_recent_sales(card_name, 'psa10')

    def format_sales(sales):
        return '\n'.join([
            f"{sale['date']}: ${sale['price']} — {sale['title']}"
            for sale in sales[:3]
        ]) if sales else 'No data.'

    def average_price(sales):
        if not sales:
            return 'N/A'
        total = sum(float(sale['price']) for sale in sales)
        return f"${total / len(sales):.2f}"

    embed = discord.Embed(
        title=f"Price Check: {card_info['title']}",
        description=f"[{card_info['title']}]({card_info['url']})",
        color=discord.Color.gold()
    )
    embed.set_thumbnail(url=card_info['image'])
    embed.add_field(name="Average Prices", value=(
        f"**Raw:** {average_price(raw_sales)}\n"
        f"**PSA 9:** {average_price(psa9_sales)}\n"
        f"**PSA 10:** {average_price(psa10_sales)}"
    ), inline=False)

    embed.add_field(name="Recent Raw Sales", value=format_sales(raw_sales), inline=False)
    embed.add_field(name="Recent PSA 9 Sales", value=format_sales(psa9_sales), inline=False)
    embed.add_field(name="Recent PSA 10 Sales", value=format_sales(psa10_sales), inline=False)

    embed.set_footer(text=f"Requested by {ctx.author.display_name}")
    await ctx.send(embed=embed)

@bot.command()
async def alert(ctx, *, card_name):
    now = datetime.utcnow()
    if card_name in last_alert_times:
        delta = now - last_alert_times[card_name]
        if delta < ALERT_COOLDOWN:
            await ctx.send(f"⏳ Alert for '{card_name}' already sent in the past 24 hours.")
            return

    card_info = search_ebay(card_name)
    if not card_info:
        await ctx.send(f"❌ Could not find any listings for '{card_name}' on eBay.")
        return

    raw_sales = get_recent_sales(card_name, 'raw')
    psa9_sales = get_recent_sales(card_name, 'psa9')
    psa10_sales = get_recent_sales(card_name, 'psa10')

    def format_sales(sales):
        return '\n'.join([
            f"{sale['date']}: ${sale['price']} — {sale['title']}"
            for sale in sales[:3]
        ]) if sales else 'No data.'

    def average_price(sales):
        if not sales:
            return 'N/A'
        total = sum(float(sale['price']) for sale in sales)
        return f"${total / len(sales):.2f}"

    embed = discord.Embed(
        title=f"🔥 Grading Alert: {card_info['title']}",
        description=f"[{card_info['title']}]({card_info['url']})",
        color=discord.Color.red()
    )
    embed.set_thumbnail(url=card_info['image'])
    embed.add_field(name="Average Prices", value=(
        f"**Raw:** {average_price(raw_sales)}\n"
        f"**PSA 9:** {average_price(psa9_sales)}\n"
        f"**PSA 10:** {average_price(psa10_sales)}"
    ), inline=False)

    embed.add_field(name="Recent Raw Sales", value=format_sales(raw_sales), inline=False)
    embed.add_field(name="Recent PSA 9 Sales", value=format_sales(psa9_sales), inline=False)
    embed.add_field(name="Recent PSA 10 Sales", value=format_sales(psa10_sales), inline=False)

    embed.set_footer(text="PokeBrief TCG - Buy, Grade, Flip")

    channel = bot.get_channel(CHANNEL_ID)
    role_mention = f"<@&{ROLE_ID}>"
    await channel.send(content=role_mention, embed=embed)

    last_alert_times[card_name] = now

bot.run(TOKEN)

