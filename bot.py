import os
import discord
import aiohttp
from discord.ext import commands
from datetime import datetime
from statistics import mean
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
EBAY_CLIENT_ID = os.getenv("EBAY_CLIENT_ID")
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET")
PRICE_CHECK_CHANNEL_ID = os.getenv("PRICE_CHECK_CHANNEL_ID")

if not TOKEN or not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
    raise ValueError("Missing required environment variables.")

PRICE_CHECK_CHANNEL_ID = int(PRICE_CHECK_CHANNEL_ID) if PRICE_CHECK_CHANNEL_ID else None

description = "Pokémon Card Price Checker"
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", description=description, intents=intents)

EBAY_OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_BROWSE_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"

async def get_ebay_token():
    async with aiohttp.ClientSession() as session:
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope"
        }
        auth = aiohttp.BasicAuth(EBAY_CLIENT_ID, EBAY_CLIENT_SECRET)
        async with session.post(EBAY_OAUTH_URL, headers=headers, data=data, auth=auth) as resp:
            resp.raise_for_status()
            resp_json = await resp.json()
            return resp_json.get("access_token")

def build_query(card_name, condition):
    # Build condition keywords for filtering titles
    # raw = no grading keywords; psa 9 and psa 10 = keywords in title
    if condition == "raw":
        return f"{card_name} -psa -cgc -bgs -beckett -tag -ace"
    else:
        return f"{card_name} {condition}"

async def fetch_items(session, token, query):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    params = {
        "q": query,
        "filter": "categoryIds:{183454},buyingOptions:{BUY_IT_NOW}",
        "limit": "10",
        "fieldgroups": "ASPECT_REFINEMENTS,DETAILED",
    }
    async with session.get(EBAY_BROWSE_URL, headers=headers, params=params) as resp:
        if resp.status != 200:
            text = await resp.text()
            print(f"Browse API error ({resp.status}): {text}")
            return []
        data = await resp.json()
        return data.get("itemSummaries", [])

def filter_items(items, condition):
    filtered = []
    condition = condition.lower()
    for item in items:
        title = item.get("title", "").lower()
        # filter raw items (exclude graded keywords)
        if condition == "raw":
            if not any(x in title for x in ["psa", "cgc", "bgs", "beckett", "tag", "ace"]):
                filtered.append(item)
        else:
            # PSA 9 or PSA 10 must include exact condition in title
            if condition in title:
                filtered.append(item)
    return filtered[:3]

def extract_data(items):
    results = []
    for item in items:
        title = item.get("title", "No Title")
        url = item.get("itemWebUrl", "")
        price = item.get("price", {}).get("value")
        currency = item.get("price", {}).get("currency")
        image = item.get("image", {}).get("imageUrl", "")
        if price is None:
            continue
        price_float = float(price)
        results.append({
            "title": title,
            "url": url,
            "price": price_float,
            "currency": currency,
            "image": image
        })
    return results

@bot.command()
async def price(ctx, *, card_name):
    token = await get_ebay_token()
    async with aiohttp.ClientSession() as session:
        embed = discord.Embed(
            title=f"Price Check: {card_name.title()}",
            color=0x00ff00,
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="eBay Sold Listings (Browse API)")

        all_data = {}

        for condition in ["raw", "psa 9", "psa 10"]:
            query = build_query(card_name, condition)
            items = await fetch_items(session, token, query)
            filtered = filter_items(items, condition)
            extracted = extract_data(filtered)
            all_data[condition] = extracted

        # Thumbnail priority raw > psa 10 > psa 9
        for cond in ["raw", "psa 10", "psa 9"]:
            if all_data.get(cond):
                embed.set_thumbnail(url=all_data[cond][0]["image"])
                break

        raw_prices = [x['price'] for x in all_data.get('raw', [])]
        psa9_prices = [x['price'] for x in all_data.get('psa 9', [])]
        psa10_prices = [x['price'] for x in all_data.get('psa 10', [])]

        if raw_prices:
            embed.add_field(name="RAW Avg Price", value=f"${mean(raw_prices):.2f}", inline=True)
        if psa9_prices:
            profit9 = mean(psa9_prices) - mean(raw_prices) - 18 if raw_prices else 0
            embed.add_field(name="PSA 9 Avg Price", value=f"${mean(psa9_prices):.2f}\nProfit: ${profit9:.2f}", inline=True)
        if psa10_prices:
            profit10 = mean(psa10_prices) - mean(raw_prices) - 18 if raw_prices else 0
            embed.add_field(name="PSA 10 Avg Price", value=f"${mean(psa10_prices):.2f}\nProfit: ${profit10:.2f}", inline=True)

        for condition, items in all_data.items():
            if items:
                desc = "\n".join([f"[{x['title']}]({x['url']}) - ${x['price']:.2f}" for x in items])
                embed.add_field(name=f"Recent {condition.upper()} Sales", value=desc, inline=False)

        await ctx.send(embed=embed)

bot.run(TOKEN)
