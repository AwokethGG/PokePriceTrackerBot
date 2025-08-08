import os
import discord
import aiohttp
from discord.ext import commands
from datetime import datetime
from statistics import mean

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
EBAY_APP_ID = os.getenv("EBAY_APP_ID")
PRICE_CHECK_CHANNEL_ID = int(os.getenv("PRICE_CHECK_CHANNEL_ID"))

description = "Pokémon Card Price Checker"
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", description=description, intents=intents)

HEADERS = {"X-EBAY-API-APP-ID": EBAY_APP_ID}
FINDING_API_URL = "https://svcs.ebay.com/services/search/FindingService/v1"

def ebay_payload(query, condition):
    keywords = f"{query} {condition}".strip()
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
    items = data.get("findCompletedItemsResponse", [{}])[0].get("searchResult", [{}])[0].get("item", [])
    results = []
    for item in items:
        title = item.get("title", [""])[0].lower()
        if condition == "raw" and not any(x in title for x in ["psa", "cgc", "bgs", "beckett", "tag", "ace"]):
            results.append(item)
        elif condition == "psa 9" and "psa 9" in title:
            results.append(item)
        elif condition == "psa 10" and "psa 10" in title:
            results.append(item)
    return results[:3]

def extract_info(items):
    data = []
    for item in items:
        title = item.get("title", [""])[0]
        url = item.get("viewItemURL", [""])[0]
        price = float(item.get("sellingStatus", [{}])[0].get("currentPrice", [{}])[0].get("__value__", 0))
        image = item.get("galleryURL", [""])[0]
        data.append({"title": title, "url": url, "price": price, "image": image})
    return data

@bot.command()
async def price(ctx, *, card_name):
    async with aiohttp.ClientSession() as session:
        embed = discord.Embed(title=f"Price Check: {card_name.title()}", color=0x00ff00, timestamp=datetime.utcnow())
        embed.set_footer(text="eBay Sold Listings")

        all_data = {}
        for condition in ["raw", "psa 9", "psa 10"]:
            async with session.get(FINDING_API_URL, headers=HEADERS, params=ebay_payload(card_name, condition)) as resp:
                json_resp = await resp.json()
                filtered = filter_results(json_resp, condition)
                extracted = extract_info(filtered)
                all_data[condition] = extracted

        # Add image to embed from first result
        if all_data['raw']:
            embed.set_thumbnail(url=all_data['raw'][0]['image'])
        elif all_data['psa 10']:
            embed.set_thumbnail(url=all_data['psa 10'][0]['image'])
        elif all_data['psa 9']:
            embed.set_thumbnail(url=all_data['psa 9'][0]['image'])

        raw_prices = [x['price'] for x in all_data['raw']]
        psa9_prices = [x['price'] for x in all_data['psa 9']]
        psa10_prices = [x['price'] for x in all_data['psa 10']]

        if raw_prices:
            embed.add_field(name="RAW Avg Price", value=f"${mean(raw_prices):.2f}", inline=True)
        if psa9_prices:
            profit9 = mean(psa9_prices) - mean(raw_prices) - 18 if raw_prices else "N/A"
            embed.add_field(name="PSA 9 Avg Price", value=f"${mean(psa9_prices):.2f}\nProfit: ${profit9:.2f}", inline=True)
        if psa10_prices:
            profit10 = mean(psa10_prices) - mean(raw_prices) - 18 if raw_prices else "N/A"
            embed.add_field(name="PSA 10 Avg Price", value=f"${mean(psa10_prices):.2f}\nProfit: ${profit10:.2f}", inline=True)

        for condition, items in all_data.items():
            if items:
                desc = "\n".join([f"[{x['title']}]({x['url']}) - ${x['price']:.2f}" for x in items])
                embed.add_field(name=f"Recent {condition.upper()} Sales", value=desc or "None", inline=False)

        await ctx.send(embed=embed)

bot.run(TOKEN)
