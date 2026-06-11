import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

import db
from panel import PanelView
import config

load_dotenv()

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=config.PREFIX, intents=intents)


# ---------------- START ----------------
@bot.event
async def on_ready():
    await db.init()
    print(f"Logado como {bot.user}")


# ---------------- LOG ----------------
async def log(guild, msg):
    channel = guild.get_channel(config.LOG_CHANNEL_ID)
    if channel:
        await channel.send(msg)


# ---------------- PING ----------------
@bot.command()
async def ping(ctx):
    await ctx.send("pong 🟢")


# ---------------- BAN ----------------
@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="sem motivo"):
    await member.ban(reason=reason)
    await ctx.send(f"{member} banido")
    await log(ctx.guild, f"BAN: {member} | {reason}")


# ---------------- KICK ----------------
@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="sem motivo"):
    await member.kick(reason=reason)
    await ctx.send(f"{member} expulso")
    await log(ctx.guild, f"KICK: {member} | {reason}")


# ---------------- WARN ----------------
@bot.command()
async def warn(ctx, member: discord.Member, *, reason="sem motivo"):
    await db.add_warn(ctx.guild.id, member.id, reason)
    await ctx.send(f"{member} recebeu warn")

    try:
        await member.send(f"Você levou warn: {reason}")
    except:
        pass

    await log(ctx.guild, f"WARN: {member} | {reason}")


# ---------------- WARNS ----------------
@bot.command()
async def warns(ctx, member: discord.Member):
    warns = await db.get_warns(ctx.guild.id, member.id)
    await ctx.send(f"{member} tem {len(warns)} warns")


# ---------------- PAINEL ----------------
@bot.command()
@commands.has_permissions(administrator=True)
async def panel(ctx):
    await ctx.send("Painel de staff:", view=PanelView())


# ---------------- ERROR ----------------
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("Sem permissão")


bot.run(TOKEN)
