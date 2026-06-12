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


import asyncio

loops = {}
loop_last_msg = {}


@bot.command()
@commands.has_permissions(administrator=True)
async def loop(ctx, command_name: str, seconds: int = 60):

    guild_id = ctx.guild.id

    if guild_id not in loops:
        loops[guild_id] = {}

    if command_name in loops[guild_id]:
        return await ctx.send("Loop já ativo.")

    async def task():

        await ctx.send(f"🔁 Loop iniciado: {command_name}")

        while command_name in loops.get(guild_id, {}):

            cmd = bot.get_command(command_name)

            if not cmd:
                await ctx.send("Comando não existe.")
                break

            try:
                # executa comando
                msg = await ctx.invoke(cmd)

                # tenta guardar mensagem retornada
                if msg:
                    loop_last_msg[(guild_id, command_name)] = msg

                # apaga anterior
                key = (guild_id, command_name)
                if key in loop_last_msg:
                    try:
                        await loop_last_msg[key].delete()
                    except:
                        pass

            except Exception as e:
                await ctx.send(f"Erro no loop: {e}")

            await asyncio.sleep(seconds)

    loops[guild_id][command_name] = asyncio.create_task(task())


@bot.command()
@commands.has_permissions(administrator=True)
async def stoploop(ctx, command_name: str = None):

    guild_id = ctx.guild.id

    if guild_id not in loops:
        return await ctx.send("Nenhum loop ativo.")

    if command_name is None:

        for t in loops[guild_id].values():
            t.cancel()

        loops[guild_id].clear()
        return await ctx.send("Todos loops parados.")

    if command_name in loops[guild_id]:

        loops[guild_id][command_name].cancel()
        del loops[guild_id][command_name]

        key = (guild_id, command_name)

        if key in loop_last_msg:
            try:
                await loop_last_msg[key].delete()
            except:
                pass

            del loop_last_msg[key]

        await ctx.send(f"Loop {command_name} parado.")


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

import discord
import sqlite3
import asyncio
from discord.ext import commands

# =========================
# DB
# =========================
db = sqlite3.connect("enterprise.db")
cur = db.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS automsg (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    guild_id INTEGER,
    channel_id INTEGER,
    message TEXT,
    interval INTEGER,
    active INTEGER DEFAULT 1
)
""")

db.commit()


# =========================
# MEMORY
# =========================
embed_cache = {}
auto_tasks = {}


# =========================
# AUTO MESSAGE LOOP ENGINE
# =========================
async def auto_runner(row):
    msg_id, user_id, guild_id, channel_id, message, interval, active = row

    channel = bot.get_channel(channel_id)
    if not channel:
        return

    while True:
        cur.execute("SELECT active FROM automsg WHERE id=?", (msg_id,))
        status = cur.fetchone()

        if not status or status[0] == 0:
            break

        try:
            await channel.send(message)
        except:
            pass

        await asyncio.sleep(interval)


async def load_autos():
    cur.execute("SELECT * FROM automsg WHERE active=1")
    rows = cur.fetchall()

    for row in rows:
        asyncio.create_task(auto_runner(row))


@bot.event
async def on_ready():
    print("ENTERPRISE SYSTEM ONLINE")
    await load_autos()


import discord
import sqlite3
import asyncio
from discord.ext import commands

# =========================
# DB
# =========================
db = sqlite3.connect("system.db")
cur = db.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS automsg (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER,
    message TEXT,
    interval INTEGER,
    active INTEGER DEFAULT 1
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS autodel (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER,
    delay INTEGER,
    active INTEGER DEFAULT 1
)
""")

db.commit()

# =========================
# ENGINE CACHE
# =========================
running_tasks = {}


# =========================
# AUTO MESSAGE ENGINE
# =========================
async def auto_message(channel_id, message, interval):

    channel = bot.get_channel(channel_id)
    if not channel:
        return

    while True:
        await channel.send(message)
        await asyncio.sleep(interval)


# =========================
# AUTO DELETE ENGINE
# =========================
async def auto_delete(channel_id, delay):

    channel = bot.get_channel(channel_id)
    if not channel:
        return

    while True:
        await asyncio.sleep(delay)

        try:
            async for msg in channel.history(limit=30):
                await msg.delete()
        except:
            pass


# =========================
# MODAL - EMBED
# =========================
class EmbedModal(discord.ui.Modal, title="Embed Builder"):

    title_input = discord.ui.TextInput(label="Título")
    desc_input = discord.ui.TextInput(label="Descrição", style=discord.TextStyle.paragraph)
    color_input = discord.ui.TextInput(label="Cor HEX (opcional)", required=False)

    def __init__(self, channel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):

        color = self.color_input.value or "3498db"

        embed = discord.Embed(
            title=self.title_input.value,
            description=self.desc_input.value,
            color=int(color, 16)
        )

        await self.channel.send(embed=embed)
        await interaction.response.send_message("✔ Embed enviada", ephemeral=True)


# =========================
# MODAL - AUTO MESSAGE
# =========================
class AutoMsgModal(discord.ui.Modal, title="Auto Message"):

    channel_id = discord.ui.TextInput(label="Channel ID")
    message = discord.ui.TextInput(label="Mensagem", style=discord.TextStyle.paragraph)
    interval = discord.ui.TextInput(label="Intervalo (segundos)")

    async def on_submit(self, interaction: discord.Interaction):

        cid = int(self.channel_id.value)

        msg = self.message.value
        interval = int(self.interval.value)

        cur.execute("""
        INSERT INTO automsg (channel_id,message,interval,active)
        VALUES (?,?,?,1)
        """, (cid, msg, interval))

        db.commit()

        asyncio.create_task(auto_message(cid, msg, interval))

        await interaction.response.send_message("✔ Auto message ativa", ephemeral=True)


# =========================
# MODAL - AUTO DELETE
# =========================
class AutoDelModal(discord.ui.Modal, title="Auto Delete"):

    channel_id = discord.ui.TextInput(label="Channel ID")
    delay = discord.ui.TextInput(label="Delay (segundos)")

    async def on_submit(self, interaction: discord.Interaction):

        cid = int(self.channel_id.value)
        delay = int(self.delay.value)

        cur.execute("""
        INSERT INTO autodel (channel_id,delay,active)
        VALUES (?,?,1)
        """, (cid, delay))

        db.commit()

        asyncio.create_task(auto_delete(cid, delay))

        await interaction.response.send_message("✔ Auto delete ativo", ephemeral=True)


# =========================
# DASHBOARD
# =========================
class Dashboard(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="📊 Embed", style=discord.ButtonStyle.primary)
    async def embed(self, interaction, button):
        await interaction.response.send_modal(EmbedModal(interaction.channel))

    @discord.ui.button(label="🔁 Auto Msg", style=discord.ButtonStyle.success)
    async def auto(self, interaction, button):
        await interaction.response.send_modal(AutoMsgModal())

    @discord.ui.button(label="🗑 Auto Delete", style=discord.ButtonStyle.danger)
    async def delete(self, interaction, button):
        await interaction.response.send_modal(AutoDelModal())


# =========================
# COMMAND
# =========================
@bot.command()
async def dashboard(ctx):
    await ctx.send("📊 CONTROL PANEL", view=Dashboard())


bot.run(TOKEN)
