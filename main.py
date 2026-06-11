import discord
from discord.ext import commands
import os

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print("ONLINE")

@bot.command()
async def ping(ctx):
    await ctx.send("pong")

bot.run(os.getenv("TOKEN"))
