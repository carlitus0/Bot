import discord
from discord.ext import commands
import sqlite3
import os

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------- DATABASE ----------------
conn = sqlite3.connect("bot.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS warns (
    user_id INTEGER,
    guild_id INTEGER,
    count INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS settings (
    guild_id INTEGER,
    command TEXT,
    enabled INTEGER
)
""")

conn.commit()

# ---------------- HELPERS ----------------
def command_enabled(guild_id, command):
    cursor.execute("SELECT enabled FROM settings WHERE guild_id=? AND command=?", (guild_id, command))
    row = cursor.fetchone()
    return True if not row else bool(row[0])

async def log(ctx, text):
    channel = discord.utils.get(ctx.guild.text_channels, name="mod-log")
    if channel:
        await channel.send(text)

# ---------------- READY ----------------
@bot.event
async def on_ready():
    print(f"Logado como {bot.user}")

# ---------------- PING ----------------
@bot.command()
async def ping(ctx):
    if not command_enabled(ctx.guild.id, "ping"):
        return
    await ctx.send("nigga")

# ---------------- KICK ----------------
@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason=None):
    if not command_enabled(ctx.guild.id, "kick"):
        return await ctx.send("Comando desativado.")

    await member.kick(reason=reason)
    await ctx.send(f"{member} foi kickado.")
    await log(ctx, f"KICK: {member} | {reason}")

# ---------------- BAN ----------------
@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason=None):
    if not command_enabled(ctx.guild.id, "ban"):
        return await ctx.send("Comando desativado.")

    await member.ban(reason=reason)
    await ctx.send(f"{member} foi banido.")
    await log(ctx, f"BAN: {member} | {reason}")

# ---------------- MUTE ----------------
@bot.command()
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, minutes: int, *, reason=None):
    if not command_enabled(ctx.guild.id, "mute"):
        return await ctx.send("Comando desativado.")

    until = discord.utils.utcnow() + discord.timedelta(minutes=minutes)
    await member.edit(timed_out_until=until, reason=reason)

    await ctx.send(f"{member} mutado por {minutes} minutos.")
    await log(ctx, f"MUTE: {member} | {minutes} min | {reason}")

# ---------------- WARN ----------------
@bot.command()
@commands.has_permissions(kick_members=True)
async def warn(ctx, member: discord.Member, *, reason=None):
    if not command_enabled(ctx.guild.id, "warn"):
        return await ctx.send("Comando desativado.")

    cursor.execute("SELECT count FROM warns WHERE user_id=? AND guild_id=?", (member.id, ctx.guild.id))
    row = cursor.fetchone()

    if row:
        count = row[0] + 1
        cursor.execute("UPDATE warns SET count=? WHERE user_id=? AND guild_id=?", (count, member.id, ctx.guild.id))
    else:
        count = 1
        cursor.execute("INSERT INTO warns VALUES (?, ?, ?)", (member.id, ctx.guild.id, count))

    conn.commit()

    try:
        await member.send(f"Você recebeu warn em {ctx.guild.name}. Motivo: {reason}")
    except:
        pass

    await ctx.send(f"{member} recebeu warn ({count}).")
    await log(ctx, f"WARN: {member} | {reason}")

# ---------------- ENABLE / DISABLE ----------------
@bot.command()
@commands.has_permissions(administrator=True)
async def disable(ctx, command):
    cursor.execute("INSERT OR REPLACE INTO settings VALUES (?, ?, 0)", (ctx.guild.id, command))
    conn.commit()
    await ctx.send(f"Comando {command} desativado.")

@bot.command()
@commands.has_permissions(administrator=True)
async def enable(ctx, command):
    cursor.execute("INSERT OR REPLACE INTO settings VALUES (?, ?, 1)", (ctx.guild.id, command))
    conn.commit()
    await ctx.send(f"Comando {command} ativado.")

# ---------------- RUN ----------------
bot.run(os.getenv("TOKEN"))
