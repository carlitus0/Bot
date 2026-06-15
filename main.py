
import os
import asyncio

import discord
from dotenv import load_dotenv
from discord.ext import commands

import config

load_dotenv()

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix=config.PREFIX,
    intents=intents
)


@bot.event
async def on_ready():
    print(f"Logado como {bot.user}")


async def load_cogs():

    if not os.path.exists("./cogs"):
        return

    for arquivo in os.listdir("./cogs"):

        if arquivo.endswith(".py"):

            await bot.load_extension(
                f"cogs.{arquivo[:-3]}"
            )


async def main():

    async with bot:

        await load_cogs()
        await bot.start(TOKEN)


asyncio.run(main())
