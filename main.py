import discord
from discord.ext import commands
import json
import os

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ----------------------------
# BANCO DE LOGS POR SERVIDOR
# ----------------------------
LOG_FILE = "logs.json"

def load_logs():
    try:
        with open(LOG_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_logs(data):
    with open(LOG_FILE, "w") as f:
        json.dump(data, f, indent=2)

logs = load_logs()

def get_log_channel(guild_id):
    return logs.get(str(guild_id))

def set_log_channel(guild_id, channel_id):
    logs[str(guild_id)] = channel_id
    save_logs(logs)

# ----------------------------
# LOG FUNCTION
# ----------------------------
async def send_log(guild, text):
    channel_id = get_log_channel(guild.id)
    if not channel_id:
        return

    channel = guild.get_channel(int(channel_id))
    if channel:
        await channel.send(text)

# ----------------------------
# READY
# ----------------------------
@bot.event
async def on_ready():
    print(f"Logado como {bot.user}")

# ----------------------------
# SET LOG CHANNEL
# ----------------------------
@bot.command()
@commands.has_permissions(administrator=True)
async def setlog(ctx, channel: discord.TextChannel):
    set_log_channel(ctx.guild.id, channel.id)
    await ctx.send(f"📌 Canal de log definido: {channel.mention}")

# ----------------------------
# PING
# ----------------------------
@bot.command()
async def ping(ctx):
    await ctx.send("pong")

# ----------------------------
# BAN
# ----------------------------
@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="sem motivo"):
    await member.ban(reason=reason)
    await ctx.send("Usuário banido.")

    await send_log(ctx.guild, f"🔨 BAN: {member} | {reason}")

# ----------------------------
# KICK
# ----------------------------
@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="sem motivo"):
    await member.kick(reason=reason)
    await ctx.send("Usuário expulso.")

    await send_log(ctx.guild, f"👢 KICK: {member} | {reason}")

# ----------------------------
# WARN
# ----------------------------
WARN_FILE = "warns.json"

def load_warns():
    try:
        with open(WARN_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_warns(data):
    with open(WARN_FILE, "w") as f:
        json.dump(data, f, indent=2)

warns = load_warns()

@bot.command()
async def warn(ctx, member: discord.Member, *, reason="sem motivo"):
    uid = str(member.id)

    warns.setdefault(uid, []).append(reason)
    save_warns(warns)

    await ctx.send("Warn aplicado.")

    try:
        await member.send(f"⚠️ Você recebeu warn: {reason}")
    except:
        pass

    await send_log(ctx.guild, f"⚠️ WARN: {member} | {reason}")

# ----------------------------
# VER WARNS
# ----------------------------
@bot.command()
async def warns(ctx, member: discord.Member):
    uid = str(member.id)
    data = warns.get(uid, [])

    if not data:
        return await ctx.send("Sem warns.")

    await ctx.send("\n".join([f"{i+1}. {w}" for i, w in enumerate(data)]))

# ----------------------------
bot.run(TOKEN)
