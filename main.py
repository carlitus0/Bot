import discord
from discord.ext import commands
import os

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ===== CONFIG =====
log_channel_id = None
commands_enabled = True
warns = {}  # {user_id: [warnings]}

# ===== UTIL =====
async def send_log(guild, text):
    if log_channel_id:
        channel = guild.get_channel(log_channel_id)
        if channel:
            await channel.send(text)

def is_admin():
    async def predicate(ctx):
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)

# ===== EVENTS =====
@bot.event
async def on_ready():
    print(f"Logado como {bot.user}")

@bot.event
async def on_message(message):
    global commands_enabled
    if not commands_enabled:
        return
    await bot.process_commands(message)

# ===== BASIC =====
@bot.command()
async def ping(ctx):
    await ctx.send("Pong!")

# ===== MODERATION =====
@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason=None):
    await member.kick(reason=reason)
    await ctx.send(f"{member} expulso.")
    await send_log(ctx.guild, f"KICK: {member} | {reason}")

@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason=None):
    await member.ban(reason=reason)
    await ctx.send(f"{member} banido.")
    await send_log(ctx.guild, f"BAN: {member} | {reason}")

@bot.command()
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, minutes: int):
    await member.timeout(discord.utils.utcnow() + discord.timedelta(minutes=minutes))
    await ctx.send(f"{member} mutado por {minutes} min.")

@bot.command()
async def warn(ctx, member: discord.Member, *, reason="sem motivo"):
    warns.setdefault(member.id, []).append(reason)
    await member.send(f"Você recebeu warn: {reason}")
    await ctx.send("Warn aplicado.")

# ===== ROLES =====
@bot.command()
@commands.has_permissions(manage_roles=True)
async def createrole(ctx, *, name):
    role = await ctx.guild.create_role(name=name)
    await ctx.send(f"Cargo criado: {role.name}")

@bot.command()
@commands.has_permissions(manage_roles=True)
async def giverole(ctx, member: discord.Member, role: discord.Role):
    await member.add_roles(role)
    await ctx.send(f"{member} recebeu {role.name}")

@bot.command()
@commands.has_permissions(manage_roles=True)
async def removerole(ctx, member: discord.Member, role: discord.Role):
    await member.remove_roles(role)
    await ctx.send(f"{member} perdeu {role.name}")

# ===== CHANNELS =====
@bot.command()
@commands.has_permissions(manage_channels=True)
async def createchannel(ctx, *, name):
    ch = await ctx.guild.create_text_channel(name)
    await ctx.send(f"Canal criado: {ch.name}")

@bot.command()
@commands.has_permissions(manage_channels=True)
async def renamechannel(ctx, channel: discord.TextChannel, *, name):
    await channel.edit(name=name)
    await ctx.send("Canal renomeado.")

# ===== LOG SYSTEM =====
@bot.command()
@commands.has_permissions(administrator=True)
async def setlog(ctx, channel: discord.TextChannel):
    global log_channel_id
    log_channel_id = channel.id
    await ctx.send(f"Log setado em {channel.name}")

# ===== TOGGLE =====
@bot.command()
@commands.has_permissions(administrator=True)
async def toggle(ctx):
    global commands_enabled
    commands_enabled = not commands_enabled
    await ctx.send(f"Comandos: {'ON' if commands_enabled else 'OFF'}")

# ===== RUN =====
bot.run(os.getenv("TOKEN"))
