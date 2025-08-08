import os
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("SERVER_INFO_CHANNEL_ID"))
ROLE_ID = int(os.getenv("AUTO_ROLE_ID"))

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.guild_messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Admin bot logged in as {bot.user}")
    await send_server_info()
    assign_roles_loop.start()  # Start the background task

async def send_server_info():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print("⚠️ Could not find the server info channel.")
        return

    embed = discord.Embed(
        title="📢 Welcome to PokeBrief TCG!",
        description="Your trusted hub for **Pokémon TCG news, restocks, deals, and card openings**.",
        color=discord.Color.blue()
    )
    embed.add_field(name="🔎 What We Offer", value="- Restock alerts\n- Market price checks\n- Product deals\n- Collector tools", inline=False)
    embed.add_field(name="🛠 Tools & Bots", value="Our custom bots help you:\n- Track prices\n- Get grading profit alerts\n- Monitor new listings", inline=False)
    embed.set_footer(text="Enjoy your stay and happy collecting!")
    embed.set_thumbnail(url="https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items/poke-ball.png")  # Optional icon

    await channel.send(embed=embed)

@tasks.loop(seconds=15)
async def assign_roles_loop():
    for guild in bot.guilds:
        role = guild.get_role(ROLE_ID)
        if not role:
            print(f"⚠️ Could not find @Collectors role in {guild.name}")
            continue

        for member in guild.members:
            if not member.bot and role not in member.roles:
                try:
                    await member.add_roles(role)
                    print(f"✅ Assigned @Collectors to {member.name}")
                except Exception as e:
                    print(f"⚠️ Failed to assign role to {member.name}: {e}")

bot.run(TOKEN)
