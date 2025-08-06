# utils/message_formatting.py
import discord
from datetime import datetime

def generate_card_alert_embed(card_name, raw_price, graded_price, profit, logo_url):
    embed = discord.Embed(
        title="🔥 Buy Alert!",
        description=f"**{card_name}** is showing great potential for grading and resale!",
        color=discord.Color.orange(),
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="🪙 Raw Price", value=f"${raw_price:.2f}", inline=True)
    embed.add_field(name="💎 Graded Price (PSA 10)", value=f"${graded_price:.2f}", inline=True)
    embed.add_field(name="📈 Estimated Profit", value=f"${profit:.2f}", inline=False)
    embed.set_thumbnail(url=logo_url)
    embed.set_footer(text="PokePriceTrackerBot — Smarter Investing in Pokémon", icon_url=logo_url)
    return embed
