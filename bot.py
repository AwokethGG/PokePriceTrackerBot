import os
import discord
from discord.ext import commands, tasks
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))
ROLE_ID = int(os.getenv("DISCORD_ROLE_ID"))
EBAY_AUTH_TOKEN = os.getenv("EBAY_AUTH_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# In-memory cache to prevent repeating alerts
alert_cache = {}

# Filters
forbidden_words = ["proxy", "custom", "altered", "Made To Order", "fake", "replica", "playtest", "play test", "test print", "ace", "cgc", "tag", "beckett", "bgs"]
keywords = ["sar", "sir", "ar", "ur", "ex", "gx", "v", "vmax", "vstar", "sv"]

HEADERS = {
    "Authorization": f"Bearer {EBAY_AUTH_TOKEN}",
    "Content-Type": "application/json",
}

def search_ebay_listings(query):
    url = f"https://api.ebay.com/buy/browse/v1/item_summary/search?q={query}&filter=priceCurrency:USD&limit=20"
    response = requests.get(url, headers=HEADERS)

    if response.status_code != 200:
        print("eBay Search Error:", response.text)
        return []

    items = response.json().get("itemSummaries", [])
    results = []
    for item in items:
        title = item.get("title", "").lower()
        if any(word in title for word in forbidden_words):
            continue
        if not any(k in title for k in keywords):
            continue
        results.append({
            "title": item.get("title", ""),
            "price": float(item["price"]["value"]),
            "url": item.get("itemWebUrl"),
            "image": item.get("image", {}).get("imageUrl")
        })
    return results

def get_recent_sales(query, condition="raw"):
    condition_query = query
    if condition == "psa9":
        condition_query += " PSA 9"
    elif condition == "psa10":
        condition_query += " PSA 10"
    else:
        # For raw: exclude all grading terms
        for term in ["PSA", "ACE", "TAG", "CGC", "Beckett", "BGS"]:
            condition_query += f" -{term}"

    url = f"https://api.ebay.com/buy/marketplace_insights/v1_beta/item_sales/search?q={condition_query}&filter=soldDate:[NOW-30DAYS..NOW],priceCurrency:USD&limit=10"
    response = requests.get(url, headers=HEADERS)

    if response.status_code != 200:
        print("eBay Sales Error:", response.text)
        return []

    sales = response.json().get("itemSales", [])
    return [{
        "title": s["itemTitle"],
        "price": float(s["price"]["value"]),
        "url": s["itemWebUrl"]
    } for s in sales if "price" in s and "value" in s["price"]]

def format_sales(sales):
    lines = []
    for sale in sales[:3]:
        title = sale['title'][:50] + ("..." if len(sale['title']) > 50 else "")
        price = f"${sale['price']:.2f}"
        lines.append(f"[{title}]({sale['url']}) - {price}")
    return lines if lines else ["No recent sales found."]

def avg(prices):
    return sum(prices) / len(prices) if prices else 0.0

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    check_new_members.start()

@tasks.loop(seconds=15)
async def check_new_members():
    guild = discord.utils.get(bot.guilds)
    role = discord.utils.get(guild.roles, id=ROLE_ID)
    for member in guild.members:
        if role not in member.roles and not member.bot:
            await member.add_roles(role)

@bot.command(name="price")
async def price_check(ctx, *, query):
    listings = search_ebay_listings(query)
    if not listings:
        await ctx.send("No valid listings found.")
        return

    top_result = listings[0]

    # Check for alert frequency
    now = datetime.utcnow()
    last_alert_time = alert_cache.get(top_result['title'])
    if last_alert_time and (now - last_alert_time) < timedelta(hours=24):
        print("Skipping alert due to cooldown.")
    else:
        alert_cache[top_result['title']] = now

    # Get sales data
    raw_sales = get_recent_sales(query, "raw")
    psa9_sales = get_recent_sales(query, "psa9")
    psa10_sales = get_recent_sales(query, "psa10")

    raw_avg = avg([s['price'] for s in raw_sales])
    psa9_avg = avg([s['price'] for s in psa9_sales])
    psa10_avg = avg([s['price'] for s in psa10_sales])

    embed = discord.Embed(title=f"Price Check: {top_result['title'][:256]}", url=top_result['url'], color=0x00ff00)
    embed.set_thumbnail(url=top_result['image'])

    embed.add_field(name="Current Lowest Listing", value=f"[${top_result['price']:.2f}]({top_result['url']})", inline=False)
    embed.add_field(name="Average Raw Price", value=f"${raw_avg:.2f}", inline=True)
    embed.add_field(name="Average PSA 9 Price", value=f"${psa9_avg:.2f}", inline=True)
    embed.add_field(name="Average PSA 10 Price", value=f"${psa10_avg:.2f}", inline=True)

    embed.add_field(name="Recent Raw Sales", value="\n".join(format_sales(raw_sales)), inline=False)
    embed.add_field(name="Recent PSA 9 Sales", value="\n".join(format_sales(psa9_sales)), inline=False)
    embed.add_field(name="Recent PSA 10 Sales", value="\n".join(format_sales(psa10_sales)), inline=False)

    await ctx.send(embed=embed)

bot.run(TOKEN)

