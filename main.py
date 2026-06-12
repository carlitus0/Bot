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


import datetime
import discord
from discord.ext import commands


@bot.command()
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, minutes: int, *, reason="Sem motivo"):

    if minutes <= 0:
        return await ctx.send("Tempo inválido.")

    try:
        duration = datetime.timedelta(minutes=minutes)

        await member.timeout(duration, reason=reason)

        await ctx.send(
            f"🔇 {member.mention} mutado por {minutes} minuto(s). Motivo: {reason}"
        )

    except discord.Forbidden:
        await ctx.send("Sem permissão pra mutar esse usuário.")

    except Exception as e:
        await ctx.send(f"Erro: {e}")


@bot.command()
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):

    try:
        await member.timeout(None)

        await ctx.send(f"🔊 {member.mention} desmutado.")

    except discord.Forbidden:
        await ctx.send("Sem permissão.")

    except Exception as e:
        await ctx.send(f"Erro: {e}")

import discord
from discord.ext import commands


# =========================
# CRIAR CARGO
# =========================
@bot.command()
@commands.has_permissions(manage_roles=True)
async def criarcargo(ctx, nome: str, cor: str = "default"):

    try:
        color = discord.Color.default()

        # cores básicas aceitas
        cores = {
            "vermelho": discord.Color.red(),
            "azul": discord.Color.blue(),
            "verde": discord.Color.green(),
            "amarelo": discord.Color.gold(),
            "roxo": discord.Color.purple(),
            "cinza": discord.Color.greyple(),
            "preto": discord.Color.dark_grey()
        }

        if cor.lower() in cores:
            color = cores[cor.lower()]

        role = await ctx.guild.create_role(
            name=nome,
            color=color,
            reason=f"Criado por {ctx.author}"
        )

        await ctx.send(f"Cargo criado: {role.mention}")

    except discord.Forbidden:
        await ctx.send("Sem permissão pra criar cargo.")

    except Exception as e:
        await ctx.send(f"Erro: {e}")


# =========================
# DELETAR CARGO
# =========================
@bot.command()
@commands.has_permissions(manage_roles=True)
async def delcargo(ctx, *, role_identifier: str):

    try:
        role = None

        # tenta por ID
        if role_identifier.isdigit():
            role = ctx.guild.get_role(int(role_identifier))

        # tenta por nome
        if role is None:
            role = discord.utils.get(ctx.guild.roles, name=role_identifier)

        if role is None:
            return await ctx.send("Cargo não encontrado.")

        await role.delete(reason=f"Deletado por {ctx.author}")

        await ctx.send(f"Cargo `{role.name}` deletado.")

    except discord.Forbidden:
        await ctx.send("Sem permissão pra deletar cargo.")

    except Exception as e:
        await ctx.send(f"Erro: {e}")


# =========================
# SETAR CARGO EM MEMBRO
# =========================
@bot.command()
@commands.has_permissions(manage_roles=True)
async def setar(ctx, member: discord.Member, *, role: discord.Role):

    try:
        await member.add_roles(role, reason=f"Setado por {ctx.author}")
        await ctx.send(f"{member.mention} recebeu o cargo {role.mention}")

    except discord.Forbidden:
        await ctx.send("Sem permissão pra adicionar cargo.")

    except Exception as e:
        await ctx.send(f"Erro: {e}")


import asyncio

# guild_id -> {command_name: task}
loops = {}


@bot.command()
@commands.has_permissions(administrator=True)
async def loop(ctx, command_name: str, seconds: int = 60):

    guild_id = ctx.guild.id

    if seconds < 5:
        return await ctx.send("Intervalo mínimo é 5 segundos.")

    if guild_id not in loops:
        loops[guild_id] = {}

    if command_name in loops[guild_id]:
        return await ctx.send("Esse loop já está ativo.")

    async def loop_task():

        await ctx.send(f"🔁 Loop iniciado: `{command_name}` ({seconds}s)")

        while True:

            # se foi removido, para loop
            if guild_id not in loops or command_name not in loops[guild_id]:
                break

            cmd = bot.get_command(command_name)

            if not cmd:
                await ctx.send(f"Comando `{command_name}` não existe.")
                break

            try:
                await ctx.invoke(cmd)
            except Exception as e:
                await ctx.send(f"Erro no loop: {e}")

            await asyncio.sleep(seconds)

    task = asyncio.create_task(loop_task())
    loops[guild_id][command_name] = task


@bot.command()
@commands.has_permissions(administrator=True)
async def stoploop(ctx, command_name: str = None):

    guild_id = ctx.guild.id

    if guild_id not in loops or not loops[guild_id]:
        return await ctx.send("Nenhum loop ativo.")

    # parar todos
    if command_name is None:

        for cmd, task in loops[guild_id].items():
            task.cancel()

        loops[guild_id].clear()

        return await ctx.send("⛔ Todos os loops foram parados.")

    # parar específico
    if command_name in loops[guild_id]:

        loops[guild_id][command_name].cancel()
        del loops[guild_id][command_name]

        await ctx.send(f"⛔ Loop `{command_name}` parado.")

    else:
        await ctx.send("Esse loop não está ativo.")

import discord
from discord.ext import commands


# =========================
# CRIAR CANAL
# =========================
@bot.command()
@commands.has_permissions(manage_channels=True)
async def criarcanal(ctx, nome: str, tipo: str = "text"):

    try:
        if tipo.lower() == "voice":
            channel = await ctx.guild.create_voice_channel(nome)
        else:
            channel = await ctx.guild.create_text_channel(nome)

        await ctx.send(f"Canal criado: {channel.mention}")

    except discord.Forbidden:
        await ctx.send("Sem permissão pra criar canal.")

    except Exception as e:
        await ctx.send(f"Erro: {e}")


# =========================
# DELETAR CANAL
# =========================
@bot.command()
@commands.has_permissions(manage_channels=True)
async def delcanal(ctx, canal: discord.TextChannel):

    try:
        nome = canal.name
        await canal.delete()
        await ctx.send(f"Canal `{nome}` deletado.")

    except discord.Forbidden:
        await ctx.send("Sem permissão pra deletar canal.")

    except Exception as e:
        await ctx.send(f"Erro: {e}")


# =========================
# RENOMEAR CANAL
# =========================
@bot.command()
@commands.has_permissions(manage_channels=True)
async def renamecanal(ctx, canal: discord.TextChannel, *, novo_nome: str):

    try:
        await canal.edit(name=novo_nome)
        await ctx.send(f"Canal renomeado para `{novo_nome}`")

    except discord.Forbidden:
        await ctx.send("Sem permissão.")

    except Exception as e:
        await ctx.send(f"Erro: {e}")


# =========================
# TRAVAR CANAL
# =========================
@bot.command()
@commands.has_permissions(manage_channels=True)
async def lock(ctx, canal: discord.TextChannel = None):

    canal = canal or ctx.channel

    try:
        await canal.set_permissions(ctx.guild.default_role, send_messages=False)
        await ctx.send(f"🔒 Canal {canal.mention} travado.")

    except discord.Forbidden:
        await ctx.send("Sem permissão.")

    except Exception as e:
        await ctx.send(f"Erro: {e}")


# =========================
# DESTRAVAR CANAL
# =========================
@bot.command()
@commands.has_permissions(manage_channels=True)
async def unlock(ctx, canal: discord.TextChannel = None):

    canal = canal or ctx.channel

    try:
        await canal.set_permissions(ctx.guild.default_role, send_messages=True)
        await ctx.send(f"🔓 Canal {canal.mention} destravado.")

    except discord.Forbidden:
        await ctx.send("Sem permissão.")

    except Exception as e:
        await ctx.send(f"Erro: {e}")
# ================= RUN =================

bot.run(TOKEN)
