import os
import asyncio

import discord
from discord.ext import commands
from dotenv import load_dotenv

import config

load_dotenv()

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.all()

bot = commands.Bot(
    command_prefix=config.PREFIX,
    intents=intents,
    help_command=None
)


async def load_cogs():
    for arquivo in os.listdir("./cogs"):
        if arquivo.endswith(".py"):
            await bot.load_extension(
                f"cogs.{arquivo[:-3]}"
            )


@bot.event
async def on_ready():
    print(f"Logado como {bot.user}")


async def main():
    async with bot:
        await load_cogs()
        await bot.start(TOKEN)


asyncio.run(main())
