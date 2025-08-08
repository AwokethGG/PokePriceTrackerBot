import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import aiohttp
import asyncio
from datetime import datetime, timedelta

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))
MENTION_ROLE_ID = int(os.getenv("GRADING_ALERT_ROLE_ID"))

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

recent_alerts = {}  # Prevent duplicates within 24h
HEADERS = {
    "Authorization": f"Bearer {os.getenv('EBAY_OAUTH_TOKEN')}"
}


async def fetch_ebay_data(query, filter_keywords=None):
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    params = {
        "q": query,
        "filter": "price:[10..150000],conditionIds:{1000|3000|4000}",
        "limit": "50",
        "sort": "newlyListed"
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=HEADERS, params=params) as resp:
            data = await resp.json()
            items = data.get("itemSummaries", [])
            if filter_keywords:
                items = [item for item in items if not any(kw in item['title'].lower() for kw in filter_keywords)]
            return items[:3]


def average_prices(items):
    prices = [float(item['price']['value']) for item in items if float(item['price']['value']) < 150000]
    return round(sum(prices) / len(prices), 2) if prices else 0.0


@bot.command(name="pricecheck")
async def price_check(ctx, *, card_name):
    raw_items = await fetch_ebay_data(card_name, filter_keywords=["psa", "ace", "tag", "cgc", "beckett"])
    psa9_items = await fetch_ebay_data(card_name + " PSA 9")
    psa10_items = await fetch_ebay_data(card_name + " PSA 10")

    avg_raw = average_prices(raw_items)
    avg_9 = average_prices(psa9_items)
    avg_10 = average_prices(psa10_items)

    embed = discord.Embed(
        title=f"eBay Price Check: {card_name}",
        description=f"Current average sale prices based on last 3 listings.",
        color=discord.Color.blue()
    )
    embed.add_field(name="Raw Avg.", value=f"${avg_raw:.2f}", inline=True)
    embed.add_field(name="PSA 9 Avg.", value=f"${avg_9:.2f}", inline=True)
    embed.add_field(name="PSA 10 Avg.", value=f"${avg_10:.2f}", inline=True)

    if raw_items:
        embed.set_thumbnail(url=raw_items[0].get("image", {}).get("imageUrl", ""))

    embed.add_field(name="Recent Raw Sales", value="\n".join([f"[{i['title']}]({i['itemWebUrl']}) - ${i['price']['value']}" for i in raw_items]), inline=False)
    embed.add_field(name="Recent PSA 9 Sales", value="\n".join([f"[{i['title']}]({i['itemWebUrl']}) - ${i['price']['value']}" for i in psa9_items]), inline=False)
    embed.add_field(name="Recent PSA 10 Sales", value="\n".join([f"[{i['title']}]({i['itemWebUrl']}) - ${i['price']['value']}" for i in psa10_items]), inline=False)

    await ctx.send(embed=embed)


async def grading_alert_loop():
    await bot.wait_until_ready()
    channel = bot.get_channel(CHANNEL_ID)

    while not bot.is_closed():
        sample_cards = ["Charizard SIR", "Pikachu SAR", "Umbreon Alt Art"]  # replace with dynamic query logic
        for card in sample_cards:
            raw_items = await fetch_ebay_data(card, filter_keywords=["psa", "ace", "tag", "cgc", "beckett"])
            psa10_items = await fetch_ebay_data(card + " PSA 10")

            avg_raw = average_prices(raw_items)
            avg_10 = average_prices(psa10_items)

            if avg_raw == 0 or avg_10 == 0:
                continue

            profit = avg_10 - avg_raw - 20  # $20 grading fee estimate

            if profit > 50:
                now = datetime.utcnow()
                if card in recent_alerts and now - recent_alerts[card] < timedelta(hours=24):
                    continue  # skip duplicate alert

                embed = discord.Embed(
                    title=f"💰 Grading Alert: {card}",
                    description=f"Potential profit detected!",
                    color=discord.Color.green()
                )
                embed.add_field(name="Raw Avg.", value=f"${avg_raw:.2f}", inline=True)
                embed.add_field(name="PSA 10 Avg.", value=f"${avg_10:.2f}", inline=True)
                embed.add_field(name="Est. Profit", value=f"${profit:.2f}", inline=True)
                embed.add_field(name="Recent PSA 10 Sales", value="\n".join([f"[{i['title']}]({i['itemWebUrl']}) - ${i['price']['value']}" for i in psa10_items]), inline=False)

                if raw_items:
                    embed.set_thumbnail(url=raw_items[0].get("image", {}).get("imageUrl", ""))

                await channel.send(f"<@&{MENTION_ROLE_ID}>", embed=embed)
                recent_alerts[card] = now

        await asyncio.sleep(300)  # wait 5 min before next scan


bot.loop.create_task(grading_alert_loop())
bot.run(TOKEN)
