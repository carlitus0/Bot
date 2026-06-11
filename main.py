import discord
from discord.ext import commands
import os
import asyncio
from datetime import timedelta

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# storage simples em memória
troll_users = set()

@bot.event
async def on_ready():
    print(f"Logado como {bot.user}")

# -------------------
# BAN
# -------------------
@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, user: discord.Member, *, reason="Sem motivo"):
    await user.ban(reason=reason)
    await ctx.send(f"🔨 {user} foi banido. Motivo: {reason}")

# -------------------
# MUTE (timeout moderno)
# -------------------
@bot.command()
@commands.has_permissions(moderate_members=True)
async def mute(ctx, user: discord.Member, minutes: int, *, reason="Sem motivo"):
    duration = timedelta(minutes=minutes)
    await user.timeout(duration, reason=reason)
    await ctx.send(f"🔇 {user} mutado por {minutes} minutos. Motivo: {reason}")

# -------------------
# UNMUTE
# -------------------
@bot.command()
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, user: discord.Member):
    await user.timeout(None)
    await ctx.send(f"🔊 {user} foi desmutado")

# -------------------
# TOGGLE TROLL (modo seguro)
# -------------------
@bot.command()
@commands.has_permissions(manage_messages=True)
async def troll(ctx, user: discord.Member):
    if user.id in troll_users:
        troll_users.remove(user.id)
        await ctx.send(f"❌ Troll desativado para {user.name}")
    else:
        troll_users.add(user.id)
        await ctx.send(f"⚠️ Troll ativado para {user.name}")

# resposta do troll (SEM insulto)
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.author.id in troll_users:
        await message.channel.send(f"{message.author.mention} tá sendo monitorado 👀")

    await bot.process_commands(message)

# -------------------
# RUN
# -------------------
bot.run(os.getenv("TOKEN"))
