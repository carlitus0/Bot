import discord
from discord.ext import commands
import sqlite3

bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

def db():
    conn = sqlite3.connect("bot.db")
    return conn, conn.cursor()

def init():
    conn, cur = db()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        warns INTEGER DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS punishments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT,
        reason TEXT,
        staff_id INTEGER,
        active INTEGER DEFAULT 1
    )
    """)

    conn.commit()
    conn.close()

init()

def is_active(cur, uid, ptype):
    cur.execute("""
        SELECT id FROM punishments
        WHERE user_id=? AND type=? AND active=1
    """, (uid, ptype))
    return cur.fetchone() is not None

@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, show: bool = True, *, reason="Sem motivo"):
    conn, cur = db()

    if is_active(cur, member.id, "ban"):
        return await ctx.send("Já está banido.")

    cur.execute("""
        INSERT INTO punishments (user_id, type, reason, staff_id)
        VALUES (?, 'ban', ?, ?)
    """, (member.id, reason, ctx.author.id))

    name = member.name if show else "Usuário"

    embed = discord.Embed(
        title="BANIMENTO",
        description=f"""
Servidor: {ctx.guild.name}
Usuário: {name}
Motivo: {reason}
""",
        color=0xff0000
    )

    try:
        await member.send(embed=embed)
    except:
        pass

    await member.ban(reason=reason)

    conn.commit()
    conn.close()

@bot.command()
async def warn(ctx, member: discord.Member, *, reason="Sem motivo"):
    conn, cur = db()

    cur.execute("SELECT warns FROM users WHERE user_id=?", (member.id,))
    row = cur.fetchone()

    warns = (row[0] if row else 0) + 1

    cur.execute("""
        INSERT OR REPLACE INTO users (user_id, warns)
        VALUES (?, ?)
    """, (member.id, warns))

    cur.execute("""
        INSERT INTO punishments (user_id, type, reason, staff_id)
        VALUES (?, 'warn', ?, ?)
    """, (member.id, reason, ctx.author.id))

    embed = discord.Embed(
        title="AVISO OFICIAL",
        description=f"Motivo: {reason}\nTotal warns: {warns}",
        color=0xffa500
    )

    try:
        await member.send(embed=embed)
    except:
        pass

    conn.commit()
    conn.close()

import asyncio

@bot.command()
async def mute(ctx, member: discord.Member, minutes: int, *, reason="Sem motivo"):
    conn, cur = db()

    if is_active(cur, member.id, "mute"):
        return await ctx.send("Já mutado.")

    role = discord.utils.get(ctx.guild.roles, name="Muted")
    await member.add_roles(role)

    cur.execute("""
        INSERT INTO punishments (user_id, type, reason, staff_id)
        VALUES (?, 'mute', ?, ?)
    """, (member.id, reason, ctx.author.id))

    try:
        await member.send(f"Mutado por {minutes} min. Motivo: {reason}")
    except:
        pass

    conn.commit()

    await asyncio.sleep(minutes * 60)
    await member.remove_roles(role)

    conn.close()

@bot.command()
async def prison(ctx, member: discord.Member, minutes: int, *, reason="Sem motivo"):
    conn, cur = db()

    if is_active(cur, member.id, "prison"):
        return await ctx.send("Já em prisão.")

    role = discord.utils.get(ctx.guild.roles, name="Prison")
    await member.add_roles(role)

    cur.execute("""
        INSERT INTO punishments (user_id, type, reason, staff_id)
        VALUES (?, 'prison', ?, ?)
    """, (member.id, reason, ctx.author.id))

    try:
        await member.send(f"Preso por {minutes} min. Motivo: {reason}")
    except:
        pass

    conn.commit()

    await asyncio.sleep(minutes * 60)
    await member.remove_roles(role)

    conn.close()

@bot.command()
@commands.has_permissions(ban_members=True)
async def hackban(ctx, user_id: int, *, reason="Sem motivo"):
    conn, cur = db()

    await ctx.guild.ban(discord.Object(id=user_id), reason=reason)

    cur.execute("""
        INSERT INTO punishments (user_id, type, reason, staff_id)
        VALUES (?, 'hackban', ?, ?)
    """, (user_id, reason, ctx.author.id))

    await ctx.send(f"Usuário {user_id} banido por ID.")

    conn.commit()
    conn.close()

@bot.command()
async def warns(ctx, member: discord.Member):
    conn, cur = db()

    cur.execute("SELECT warns FROM users WHERE user_id=?", (member.id,))
    row = cur.fetchone()

    await ctx.send(f"{member} tem {row[0] if row else 0} warns")

    conn.close()
    import discord
from discord.ext import commands
import sqlite3
import datetime

# ======================
# BOT SETUP
# ======================
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# ======================
# DATABASE CORE
# ======================
def db():
    conn = sqlite3.connect("bot.db")
    return conn, conn.cursor()

def init():
    conn, cur = db()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS punishments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT,
        reason TEXT,
        staff_id INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS automod (
        word TEXT PRIMARY KEY
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS logs_config (
        type TEXT PRIMARY KEY,
        channel_id INTEGER
    )
    """)

    conn.commit()
    conn.close()

init()

# ======================
# LOG SYSTEM
# ======================
async def send_log(guild, log_type, text):
    conn, cur = db()
    cur.execute("SELECT channel_id FROM logs_config WHERE type=?", (log_type,))
    row = cur.fetchone()
    conn.close()

    if row:
        ch = guild.get_channel(row[0])
        if ch:
            await ch.send(text)

# ======================
# AUTOMOD (EVENT CORE)
# ======================
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    conn, cur = db()
    cur.execute("SELECT word FROM automod")
    words = [w[0] for w in cur.fetchall()]
    conn.close()

    for w in words:
        if w in message.content.lower():
            await message.delete()
            return

    await bot.process_commands(message)

# ======================
# BAN
# ======================
@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, show: bool = True, *, reason="Sem motivo"):

    conn, cur = db()

    cur.execute("""
    INSERT INTO punishments (user_id, type, reason, staff_id)
    VALUES (?, 'ban', ?, ?)
    """, (member.id, reason, ctx.author.id))

    try:
        await member.send(f"🚫 Banido de {ctx.guild.name}\nMotivo: {reason}")
    except:
        pass

    await member.ban(reason=reason)

    await send_log(ctx.guild, "punish", f"BAN | {member} | {reason}")

    conn.commit()
    conn.close()

# ======================
# WARN
# ======================
@bot.command()
async def warn(ctx, member: discord.Member, *, reason="Sem motivo"):

    conn, cur = db()

    cur.execute("""
    INSERT INTO punishments (user_id, type, reason, staff_id)
    VALUES (?, 'warn', ?, ?)
    """, (member.id, reason, ctx.author.id))

    try:
        await member.send(f"⚠️ WARN\nMotivo: {reason}")
    except:
        pass

    await send_log(ctx.guild, "punish", f"WARN | {member} | {reason}")

    conn.commit()
    conn.close()

# ======================
# MUTE (TIMEOUT)
# ======================
@bot.command()
async def mute(ctx, member: discord.Member, minutes: int, *, reason="Sem motivo"):

    until = datetime.datetime.utcnow() + datetime.timedelta(minutes=minutes)
    await member.timeout(until, reason=reason)

    conn, cur = db()

    cur.execute("""
    INSERT INTO punishments (user_id, type, reason, staff_id)
    VALUES (?, 'mute', ?, ?)
    """, (member.id, reason, ctx.author.id))

    await send_log(ctx.guild, "punish", f"MUTE | {member} | {minutes}min")

    conn.commit()
    conn.close()

# ======================
# PRISON
# ======================
@bot.command()
async def prison(ctx, member: discord.Member, minutes: int, *, reason="Sem motivo"):

    until = datetime.datetime.utcnow() + datetime.timedelta(minutes=minutes)
    await member.timeout(until, reason=reason)

    conn, cur = db()

    cur.execute("""
    INSERT INTO punishments (user_id, type, reason, staff_id)
    VALUES (?, 'prison', ?, ?)
    """, (member.id, reason, ctx.author.id))

    await send_log(ctx.guild, "punish", f"PRISON | {member} | {minutes}min")

    conn.commit()
    conn.close()

# ======================
# HACKBAN (REAL ID BAN)
# ======================
@bot.command()
@commands.has_permissions(ban_members=True)
async def hackban(ctx, user_id: int, *, reason="Sem motivo"):

    await ctx.guild.ban(discord.Object(id=user_id), reason=reason)

    conn, cur = db()

    cur.execute("""
    INSERT INTO punishments (user_id, type, reason, staff_id)
    VALUES (?, 'hackban', ?, ?)
    """, (user_id, reason, ctx.author.id))

    await send_log(ctx.guild, "punish", f"HACKBAN | {user_id} | {reason}")

    conn.commit()
    conn.close()

# ======================
# AUTOMOD CONTROL
# ======================
@bot.command()
async def addword(ctx, word: str):
    conn, cur = db()
    cur.execute("INSERT OR IGNORE INTO automod VALUES (?)", (word.lower(),))
    conn.commit()
    conn.close()
    await ctx.send("Palavra adicionada.")

@bot.command()
async def removeword(ctx, word: str):
    conn, cur = db()
    cur.execute("DELETE FROM automod WHERE word=?", (word.lower(),))
    conn.commit()
    conn.close()
    await ctx.send("Palavra removida.")

# ======================
# LOG CONFIG
# ======================
@bot.command()
async def setlog(ctx, log_type: str, channel: discord.TextChannel):

    conn, cur = db()
    cur.execute("""
    INSERT OR REPLACE INTO logs_config VALUES (?, ?)
    """, (log_type, channel.id))

    conn.commit()
    conn.close()

    await ctx.send("Log configurado.")

# ======================
# WARN CHECK
# ======================
@bot.command()
async def warns(ctx, member: discord.Member):

    conn, cur = db()
    cur.execute("""
    SELECT COUNT(*) FROM punishments
    WHERE user_id=? AND type='warn'
    """, (member.id,))

    count = cur.fetchone()[0]

    await ctx.send(f"{member} tem {count} warns")

# ======================
# RUN BOT (SÓ UMA VEZ)
# ======================
("TOKEN")

import os

TOKEN = os.getenv("DISCORD_TOKEN")
bot.run(TOKEN)
