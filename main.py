print("V67")

import os
import discord

from dotenv import load_dotenv
from discord.ext import commands

import db
import config

from panel import PanelView
from tickets import TicketView

load_dotenv()

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.all()

bot = commands.Bot(
    command_prefix=config.PREFIX,
    intents=intents
)


@bot.event
async def on_ready():

    await db.init()

    print(f"Logado como {bot.user}")

async def send_log(guild,msg):

    channel_id = await db.get_log_channel(
        guild.id
    )

    if not channel_id:
        channel_id = config.LOG_CHANNEL_ID

    channel = guild.get_channel(
        channel_id
    )

    if channel:
        await channel.send(msg)


@bot.command()
async def ping(ctx):

    await ctx.send(
        f"Pong! {round(bot.latency*1000)}ms"
    )


@bot.command()
@commands.has_permissions(
    ban_members=True
)
async def ban(
    ctx,
    member: discord.Member,
    *,
    reason="Sem motivo"
):

    await member.ban(reason=reason)

    await ctx.send(
        f"{member} foi banido."
    )

    await send_log(
        ctx.guild,
        f"BAN | {member} | {reason}"
    )


@bot.command()
@commands.has_permissions(
    kick_members=True
)
async def kick(
    ctx,
    member: discord.Member,
    *,
    reason="Sem motivo"
):

    await member.kick(reason=reason)

    await ctx.send(
        f"{member} expulso."
    )

    await send_log(
        ctx.guild,
        f"KICK | {member} | {reason}"
    )


@bot.command()
async def warn(
    ctx,
    member: discord.Member,
    *,
    reason="Sem motivo"
):

    await db.add_warn(
        ctx.guild.id,
        member.id,
        reason
    )

    try:

        await member.send(
            f"Você recebeu warn: {reason}"
        )

    except:
        pass

    await ctx.send(
        "Warn aplicado."
    )


@bot.command()
async def warns(
    ctx,
    member: discord.Member
):

    warns = await db.get_warns(
        ctx.guild.id,
        member.id
    )

    await ctx.send(
        f"{member} possui {len(warns)} warns."
    )


@bot.command()
@commands.has_permissions(
    administrator=True
)
async def panel(ctx):

    await ctx.send(
        "Painel Staff",
        view=PanelView()
    )


@bot.command()
@commands.has_permissions(
    administrator=True
)
async def setticket(ctx):

    channel = bot.get_channel(
        config.TICKET_CHANNEL_ID
    )

    await channel.send(
        "Clique para abrir ticket",
        view=TicketView()
    )

    await ctx.send(
        "Painel enviado."
    )


@bot.command()
@commands.has_permissions(
    manage_roles=True
)
async def addrole(
    ctx,
    member: discord.Member,
    role: discord.Role
):

    await member.add_roles(role)

    await ctx.send(
        "Cargo adicionado."
    )


@bot.command()
@commands.has_permissions(
    manage_roles=True
)
async def removerole(
    ctx,
    member: discord.Member,
    role: discord.Role
):

    await member.remove_roles(role)

    await ctx.send(
        "Cargo removido."
    )


@bot.command()
@commands.has_permissions(
    manage_channels=True
)
async def lock(ctx):

    await ctx.channel.set_permissions(
        ctx.guild.default_role,
        send_messages=False
    )

    await ctx.send(
        "Canal bloqueado."
    )


@bot.command()
@commands.has_permissions(
    manage_channels=True
)
async def unlock(ctx):

    await ctx.channel.set_permissions(
        ctx.guild.default_role,
        send_messages=True
    )

    await ctx.send(
        "Canal desbloqueado."
    )


@bot.command()
@commands.has_permissions(
    manage_messages=True
)
async def clear(
    ctx,
    quantidade: int
):

    await ctx.channel.purge(
        limit=quantidade+1
    )


@bot.event
async def on_command_error(
    ctx,
    error
):

    if isinstance(
        error,
        commands.CommandNotFound
    ):
        return

    if isinstance(
        error,
        commands.MissingPermissions
    ):

        await ctx.send(
            "Sem permissão."
        )
from logs import LogSystem

bot.run(TOKEN)
