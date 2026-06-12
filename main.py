import os
import discord
import io
import sys
import traceback
import asyncio
import contextlib
import time

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

OWNER_ID = 878075563984707637

exec_history = {}


# ================= IDE ENGINE =================

async def run_code(code: str):
    out = io.StringIO()
    err = io.StringIO()

    def _exec():
        try:
            with contextlib.redirect_stdout(out):
                with contextlib.redirect_stderr(err):
                    exec(code, {"__import__": __import__})
        except Exception:
            err.write(traceback.format_exc())

    await asyncio.to_thread(_exec)

    return out.getvalue(), err.getvalue()


class IDEModal(discord.ui.Modal, title="IDE Python"):

    code = discord.ui.TextInput(
        label="Código Python",
        style=discord.TextStyle.paragraph,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):

        if interaction.user.id != OWNER_ID:
            return await interaction.response.send_message("Sem permissão.", ephemeral=True)

        stdout, stderr = await run_code(str(self.code))

        exec_history[interaction.user.id] = {
            "code": str(self.code),
            "stdout": stdout,
            "stderr": stderr,
            "time": time.time()
        }

        result = ""

        if stdout:
            result += f"OUTPUT:\n{stdout}\n"

        if stderr:
            result += f"\nERROR:\n{stderr}\n"

        if not result.strip():
            result = "SEM OUTPUT"

        await interaction.response.send_message(
            f"```py\n{result[:1900]}```",
            ephemeral=True
        )


class IDEView(discord.ui.View):

    @discord.ui.button(label="Run Code", style=discord.ButtonStyle.green)
    async def run(self, interaction: discord.Interaction, button: discord.ui.Button):

        if interaction.user.id != OWNER_ID:
            return await interaction.response.send_message("Sem permissão.", ephemeral=True)

        await interaction.response.send_modal(IDEModal())

    @discord.ui.button(label="Last Run", style=discord.ButtonStyle.primary)
    async def last(self, interaction: discord.Interaction, button: discord.ui.Button):

        data = exec_history.get(interaction.user.id)

        if not data:
            return await interaction.response.send_message("Sem histórico.", ephemeral=True)

        msg = f"""
CODE:
{data['code']}

OUTPUT:
{data['stdout']}

ERROR:
{data['stderr']}
"""

        await interaction.response.send_message(f"```py\n{msg[:1900]}```", ephemeral=True)

    @discord.ui.button(label="Clear History", style=discord.ButtonStyle.red)
    async def clear(self, interaction: discord.Interaction, button: discord.ui.Button):

        if interaction.user.id != OWNER_ID:
            return await interaction.response.send_message("Sem permissão.", ephemeral=True)

        exec_history.pop(interaction.user.id, None)
        await interaction.response.send_message("Histórico limpo.", ephemeral=True)


# ================= BOT EVENTS =================

@bot.event
async def on_ready():
    await db.init()
    print(f"Logado como {bot.user}")


async def send_log(guild, msg):
    channel_id = await db.get_log_channel(guild.id)

    if not channel_id:
        channel_id = config.LOG_CHANNEL_ID

    channel = guild.get_channel(channel_id)

    if channel:
        await channel.send(msg)


# ================= COMMANDS =================

@bot.command()
async def ide(ctx):

    if ctx.author.id != OWNER_ID:
        return await ctx.send("Sem permissão.")

    await ctx.send("IDE ativa:", view=IDEView())


@bot.command()
async def console(ctx):
    if ctx.author.id != OWNER_ID:
        return await ctx.send("Sem permissão.")

    await ctx.send("IDE ativa:", view=IDEView())


@bot.command()
async def ping(ctx):
    await ctx.send(f"Pong! {round(bot.latency * 1000)}ms")


@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="Sem motivo"):
    await member.ban(reason=reason)
    await ctx.send(f"{member} foi banido.")
    await send_log(ctx.guild, f"BAN | {member} | {reason}")


@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="Sem motivo"):
    await member.kick(reason=reason)
    await ctx.send(f"{member} expulso.")
    await send_log(ctx.guild, f"KICK | {member} | {reason}")


@bot.command()
async def warn(ctx, member: discord.Member, *, reason="Sem motivo"):
    await db.add_warn(ctx.guild.id, member.id, reason)

    try:
        await member.send(f"Você recebeu warn: {reason}")
    except:
        pass

    await ctx.send("Warn aplicado.")


@bot.command()
async def warns(ctx, member: discord.Member):
    warns = await db.get_warns(ctx.guild.id, member.id)
    await ctx.send(f"{member} possui {len(warns)} warns.")


@bot.command()
@commands.has_permissions(administrator=True)
async def panel(ctx):
    await ctx.send("Painel Staff", view=PanelView())


@bot.command()
@commands.has_permissions(administrator=True)
async def setticket(ctx):
    channel = bot.get_channel(config.TICKET_CHANNEL_ID)

    await channel.send("Clique para abrir ticket", view=TicketView())
    await ctx.send("Painel enviado.")


@bot.command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx, quantidade: int):
    await ctx.channel.purge(limit=quantidade + 1)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("Sem permissão.")


# ================= RUN =================

bot.run(TOKEN)
