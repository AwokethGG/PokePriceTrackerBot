import os
import discord
from discord.ext import commands
from ebay_sdk import search_ebay_listings, get_recent_sales
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))
ROLE_ID = int(os.getenv("DISCORD_ROLE_ID"))

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Filters
forbidden_words = [
    "proxy", "custom", "altered", "made to order", "fake", "replica", "playtest", "play test", "test print",
    "sealed", "lot", "psa", "cgc", "tag", "ace", "beckett"
]
keywords = ["sar", "sir", "ar", "ur", "ex", "gx", "v", "vmax", "vstar", "sv"]

# Util: Format recent sales into string
def format_sales(sales):
    lines = []
    for sale in sales:
        title = sale['title'][:50] + ("..." if len(sale['title']) > 50 else "")
        price = f"${sale['price']:.2f}"
        lines.append(f"[{title}]({sale['url']}) - {price}")
    return lines if lines else ["No recent sales found."]

# Util: Calculate average
def avg(prices):
    return sum(prices) / len(prices) if prices else 0.0

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

@bot.command(name="price")
async def price_check(ctx, *, query):
    listings = search_ebay_listings(query)

    # Filter: exclude forbidden words
    filtered = [item for item in listings if not any(word in item['title'].lower() for word in forbidden_words)]

    # Filter: must match at least one keyword
    filtered = [item for item in filtered if any(k in item['title'].lower() for k in keywords)]

    if not filtered:
        await ctx.send("No valid listings found.")
        return

    top_result = filtered[0]

    # Fetch recent sales by category
    raw_sales = get_recent_sales(query, condition="raw")
    psa9_sales = get_recent_sales(query, condition="psa9")
    psa10_sales = get_recent_sales(query, condition="psa10")

    # Clean sales data
    def clean_sales(sales, required_keyword=None, exclude_keywords=[]):
        results = []
        for s in sales:
            title = s['title'].lower()
            if required_keyword and required_keyword not in title:
                continue
            if any(bad in title for bad in exclude_keywords):
                continue
            results.append(s)
        return results

    raw_sales = clean_sales(raw_sales, exclude_keywords=["psa", "ace", "tag", "cgc", "beckett"])
    psa9_sales = clean_sales(psa9_sales, required_keyword="psa 9")
    psa10_sales = clean_sales(psa10_sales, required_keyword="psa 10")

    # Averages
    raw_avg = avg([s['price'] for s in raw_sales])
    psa9_avg = avg([s['price'] for s in psa9_sales])
    psa10_avg = avg([s['price'] for s in psa10_sales])

    # Embed message
    embed = discord.Embed(
        title=f"💳 Price Check: {top_result['title'][:256]}",
        url=top_result['url'],
        description=f"🔍 Here's a breakdown of the current eBay pricing and recent sales for **{query}**.",
        color=0xFFD700
    )
    embed.set_thumbnail(url=top_result['image'])

    embed.add_field(name="🛒 Current Lowest Listing", value=f"${top_result['price']:.2f}", inline=False)
    embed.add_field(name="📊 Average Raw Price", value=f"${raw_avg:.2f}", inline=True)
    embed.add_field(name="📊 Average PSA 9 Price", value=f"${psa9_avg:.2f}", inline=True)
    embed.add_field(name="📊 Average PSA 10 Price", value=f"${psa10_avg:.2f}", inline=True)

    embed.add_field(name="📦 Recent Raw Sales", value="\n".join(format_sales(raw_sales[:3])), inline=False)
    embed.add_field(name="💎 Recent PSA 9 Sales", value="\n".join(format_sales(psa9_sales[:3])), inline=False)
    embed.add_field(name="🏆 Recent PSA 10 Sales", value="\n".join(format_sales(psa10_sales[:3])), inline=False)

    await ctx.send(embed=embed)

@bot.event
async def on_member_join(member):
    role = member.guild.get_role(ROLE_ID)
    if role:
        await member.add_roles(role)

bot.run(TOKEN)

