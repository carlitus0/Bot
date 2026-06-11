import discord
from discord.ext import commands
import os
import json
from datetime import timedelta

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

TOKEN = os.getenv("TOKEN")

LOG_CHANNEL_ID = 1514512718923567254

WARN_FILE = "warns.json"
STATE_FILE = "state.json"

# ===== LOADERS =====
def load_json(file):
    try:
        with open(file, "r") as f:
            return json.load(f)
    except:
        return {}

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=2)

warns = load_json(WARN_FILE)
state = load_json(STATE_FILE)

# ===== STATE CONTROL (ENABLE/DISABLE COMMANDS) =====
def is_enabled(guild_id):
    gid = str(guild_id)
    return state.get(gid, {}).get("enabled", True)

def set_enabled(guild_id, value: bool):
    gid = str(guild_id)
    if gid not in state:
        state[gid] = {}
    state[gid]["enabled"] = value
    save_json(STATE_FILE, state)

# ===== LOG =====
async def log(guild, text):
    channel = guild.get_channel(LOG_CHANNEL_ID)
    if channel:
        await channel.send(text)

# ===== CHECK IF DISABLED =====
def check_enabled():
    async def predicate(ctx):
        if not is_enabled(ctx.guild.id):
            await ctx.send("❌ Comandos desativados neste servidor.")
            return False
        return True
    return commands.check(predicate)

# ===== READY =====
@bot.event
async def on_ready():
    print(f"Logado como {bot.user}")

# ===== PING =====
@bot.command()
@check_enabled()
async def ping(ctx):
    await ctx.send("Pong!")

# ===== BAN =====
@bot.command()
@commands.has_permissions(ban_members=True)
@check_enabled()
async def ban(ctx, member: discord.Member, *, reason="sem motivo"):
    await member.ban(reason=reason)
    await ctx.send(f"{member} banido.")
    await log(ctx.guild, f"BAN: {member} | {reason}")

# ===== KICK =====
@bot.command()
@commands.has_permissions(kick_members=True)
@check_enabled()
async def kick(ctx, member: discord.Member, *, reason="sem motivo"):
    await member.kick(reason=reason)
    await ctx.send(f"{member} expulso.")
    await log(ctx.guild, f"KICK: {member} | {reason}")

# ===== MUTE =====
@bot.command()
@commands.has_permissions(moderate_members=True)
@check_enabled()
async def mute(ctx, member: discord.Member, minutes: int, *, reason="sem motivo"):
    await member.timeout(timedelta(minutes=minutes), reason=reason)
    await ctx.send(f"{member} mutado {minutes} min.")
    await log(ctx.guild, f"MUTE: {member} | {minutes} min | {reason}")

# ===== WARN =====
@bot.command()
@check_enabled()
async def warn(ctx, member: discord.Member, *, reason="sem motivo"):
    uid = str(member.id)

    if uid not in warns:
        warns[uid] = []

    warns[uid].append(reason)
    save_json(WARN_FILE, warns)

    await ctx.send(f"{member} recebeu warn.")
    try:
        await member.send(f"⚠️ Warn: {reason}")
    except:
        pass

    await log(ctx.guild, f"WARN: {member} | {reason}")

# ===== WARN COUNT =====
@bot.command()
@check_enabled()
async def warns(ctx, member: discord.Member):
    uid = str(member.id)
    count = len(warns.get(uid, []))
    await ctx.send(f"{member} tem {count} warns.")

# ===== TOGGLE SYSTEM (TROLL MODE) =====
@bot.command()
@commands.has_permissions(administrator=True)
async def disable(ctx):
    set_enabled(ctx.guild.id, False)
    await ctx.send("❌ Comandos desativados.")

@bot.command()
@commands.has_permissions(administrator=True)
async def enable(ctx):
    set_enabled(ctx.guild.id, True)
    await ctx.send("✅ Comandos ativados.")

# ===== HELP =====
@bot.command()
async def modhelp(ctx):
    await ctx.send("""
📌 Comandos:
!ping
!ban @user motivo
!kick @user motivo
!mute @user minutos motivo
!warn @user motivo
!warns @user

⚙️ Admin:
!enable
!disable
""")

# ===== RUN =====
bot.run(TOKEN)
