import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

# Environment variables
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("SERVER_INFO_CHANNEL_ID"))
ROLE_ID = int(os.getenv("AUTO_ROLE_ID"))

# Bot setup with minimal required intents
intents = discord.Intents.default()
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Track if server info has been sent to avoid duplicates
server_info_sent = False

@bot.event
async def on_ready():
    """Bot startup event - only runs once per session"""
    print(f"✅ PokeBrief TCG Bot logged in as {bot.user}")
    print(f"📊 Serving {len(bot.guilds)} server(s) with {len(bot.users)} users")
    
    # Send server info only once per bot session
    global server_info_sent
    if not server_info_sent:
        await send_server_info()
        server_info_sent = True

@bot.event
async def on_member_join(member):
    """Efficiently assign role when new members join - no loops needed"""
    if member.bot:
        return
    
    role = member.guild.get_role(ROLE_ID)
    if not role:
        print(f"⚠️ Auto-role not found in {member.guild.name}")
        return
    
    try:
        await member.add_roles(role, reason="Auto-role assignment")
        print(f"✅ Assigned @{role.name} to {member.display_name}")
    except discord.Forbidden:
        print(f"❌ Missing permissions to assign role to {member.display_name}")
    except discord.HTTPException as e:
        print(f"⚠️ Failed to assign role to {member.display_name}: {e}")

async def send_server_info():
    """Send a beautiful server info embed"""
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print("⚠️ Server info channel not found")
        return
    
    # Create a stunning embed with modern design
    embed = discord.Embed(
        title="🎴 Welcome to PokeBrief TCG!",
        description="*Your premier destination for Pokémon TCG news, deals, and market insights*",
        color=0x3498db  # Beautiful blue color
    )
    
    # Add fields with emojis and clean formatting
    embed.add_field(
        name="🔍 **What We Offer**",
        value=(
            "• 📦 **Restock Alerts** - Never miss a drop\n"
            "• 💰 **Price Tracking** - Live market data\n"
            "• 🛒 **Deal Notifications** - Best prices found\n"
            "• 📈 **Market Analysis** - Trends & insights"
        ),
        inline=False
    )
    
    embed.add_field(
        name="🤖 **Smart Tools & Bots**",
        value=(
            "• 📊 Real-time price monitoring\n"
            "• 💎 Grading profit calculators\n"
            "• 🔔 Custom alert systems\n"
            "• 📋 Collection management"
        ),
        inline=False
    )
    
    embed.add_field(
        name="🌟 **Community Features**",
        value=(
            "• 💬 Active trading discussions\n"
            "• 📸 Card showcase channels\n"
            "• 🎯 Expert advice & tips\n"
            "• 🏆 Exclusive member perks"
        ),
        inline=False
    )
    
    # Enhanced footer and visual elements
    embed.set_footer(
        text="🚀 Ready to level up your TCG game? Let's collect! 🚀",
        icon_url="https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items/master-ball.png"
    )
    
    embed.set_thumbnail(url="https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items/ultra-ball.png")
    
    # Add a subtle timestamp
    embed.timestamp = discord.utils.utcnow()
    
    try:
        await channel.send(embed=embed)
        print("✅ Server info embed sent successfully")
    except discord.Forbidden:
        print("❌ Missing permissions to send message to server info channel")
    except discord.HTTPException as e:
        print(f"⚠️ Failed to send server info: {e}")

@bot.command(name="serverinfo")
@commands.has_permissions(administrator=True)
async def manual_server_info(ctx):
    """Manual command to resend server info (admin only)"""
    await send_server_info()
    await ctx.send("✅ Server info updated!", delete_after=5)

@bot.command(name="assignroles")
@commands.has_permissions(administrator=True)
async def bulk_assign_roles(ctx):
    """One-time bulk role assignment for existing members (admin only)"""
    role = ctx.guild.get_role(ROLE_ID)
    if not role:
        await ctx.send("❌ Auto-role not found!")
        return
    
    assigned = 0
    skipped = 0
    
    # Show progress message
    progress_msg = await ctx.send("🔄 Assigning roles to existing members...")
    
    for member in ctx.guild.members:
        if member.bot or role in member.roles:
            skipped += 1
            continue
        
        try:
            await member.add_roles(role, reason="Bulk role assignment")
            assigned += 1
        except discord.HTTPException:
            skipped += 1
            continue
    
    # Update progress message with results
    embed = discord.Embed(
        title="✅ Bulk Role Assignment Complete",
        color=0x2ecc71
    )
    embed.add_field(name="Assigned", value=str(assigned), inline=True)
    embed.add_field(name="Skipped", value=str(skipped), inline=True)
    embed.add_field(name="Total Members", value=str(len(ctx.guild.members)), inline=True)
    
    await progress_msg.edit(content="", embed=embed)

@bot.event
async def on_command_error(ctx, error):
    """Handle command errors gracefully"""
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command.", delete_after=5)
    elif isinstance(error, commands.CommandNotFound):
        pass  # Ignore unknown commands
    else:
        print(f"Command error: {error}")

if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except discord.LoginFailure:
        print("❌ Invalid token - check your DISCORD_TOKEN in .env file")
    except Exception as e:
        print(f"❌ Bot startup failed: {e}")