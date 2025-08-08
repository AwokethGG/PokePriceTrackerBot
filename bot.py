import os
import discord
import aiohttp
from discord.ext import commands
from datetime import datetime
from statistics import mean
from dotenv import load_dotenv
from urllib.parse import quote_plus

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
EBAY_APP_ID = os.getenv("EBAY_APP_ID")
PRICE_CHECK_CHANNEL_ID = os.getenv("PRICE_CHECK_CHANNEL_ID")

if not TOKEN or not EBAY_APP_ID:
    raise ValueError("Missing required environment variables.")

PRICE_CHECK_CHANNEL_ID = int(PRICE_CHECK_CHANNEL_ID) if PRICE_CHECK_CHANNEL_ID else None

description = "Pokémon Card Price Checker"
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", description=description, intents=intents)

HEADERS = {
    "X-EBAY-API-APP-ID": EBAY_APP_ID,
    "Accept": "application/json"
}
FINDING_API_URL = "https://svcs.ebay.com/services/search/FindingService/v1"

def sanitize_query(query):
    return ''.join(c for c in query if c.isalnum() or c.isspace()).strip()

def ebay_payload(query, condition):
    keywords = sanitize_query(f"{query} {condition}")
    return {
        "OPERATION-NAME": "findCompletedItems",
        "SERVICE-VERSION": "1.13.0",
        "RESPONSE-DATA-FORMAT": "JSON",
        "REST-PAYLOAD": "true",
        "keywords": keywords,
        "categoryId": "183454",
        "itemFilter(0).name": "SoldItemsOnly",
        "itemFilter(0).value": "true",
        "itemFilter(1).name": "Condition",
        "itemFilter(1).value": "3000",
        "sortOrder": "EndTimeSoonest",
        "paginationInput.entriesPerPage": "10",
    }

def filter_results(data, condition):
    try:
        items = data["findCompletedItemsResponse"][0]["searchResult"][0].get("item", [])
    except Exception:
        return []

    results = []
    for item in items:
        title = item.get("title", [""])[0].lower()
        if condition == "raw" and not any(x in title for x in ["psa", "cgc", "bgs", "beckett", "tag", "ace"]):
            results.append(item)
        elif condition in ["psa 9", "psa 10"] and condition in title:
            results.append(item)
    return results[:3]

def extract_info(items):
    data = []
    for item in items:
        try:
            title = item.get("title", [""])[0]
            url = item.get("viewItemURL", [""])[0]
            price = float(item.get("sellingStatus", [{}])[0].get("currentPrice", [{}])[0].get("__value__", 0))
            image = item.get("galleryURL", [""])[0]
            data.append({"title": title, "url": url, "price": price, "image": image})
        except Exception:
            continue
    return data

@bot.command()
async def price(ctx, *, card_name):
    async with aiohttp.ClientSession() as session:
        embed = discord.Embed(
            title=f"Price Check: {card_name.title()}",
            color=0x00ff00,
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="eBay Sold Listings")

        all_data = {}
        for condition in ["raw", "psa 9", "psa 10"]:
            try:
                async with session.get(
                    FINDING_API_URL,
                    headers=HEADERS,
                    params=ebay_payload(card_name, condition)
                ) as resp:
                    try:
                        json_resp = await resp.json()
                    except aiohttp.ContentTypeError:
                        text = await resp.text()
                        print(f"eBay response (not JSON):\n{text}")
                        raise

                    filtered = filter_results(json_resp, condition)
                    extracted = extract_info(filtered)
                    all_data[condition] = extracted
            except Exception as e:
                print(f"Error fetching {condition}: {e}")
                all_data[condition] = []

        # Set thumbnail
        for key in ["raw", "psa 10", "psa 9"]:
            if all_data.get(key):
                embed.set_thumbnail(url=all_data[key][0]["image"])
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
