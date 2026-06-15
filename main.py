import os
import asyncio
import discord

from discord.ext import commands
from config import TOKEN, PREFIX


intents = discord.Intents.default()
intents.message_content = True
intents.members = True


bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None
)


@bot.event
async def on_ready():
    print(f"{bot.user} está online!")


async def load_cogs():
    for file in os.listdir("./cogs"):
        if file.endswith(".py") and not file.startswith("__"):
            await bot.load_extension(f"cogs.{file[:-3]}")
            print(f"Cog carregada: {file}")

import database.database

async def main():
    async with bot:
        await load_cogs()
        await bot.start(TOKEN)


asyncio.run(main())
