import os
import discord
import io
import traceback

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


# ================= CONSOLE PRO =================

class ExecModal(discord.ui.Modal, title="Python Console"):

    code = discord.ui.TextInput(
        label="Código Python",
        style=discord.TextStyle.paragraph,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):

        if interaction.user.id != OWNER_ID:
            return await interaction.response.send_message("Sem permissão.", ephemeral=True)

        buffer = io.StringIO()

        try:
            exec(
                str(self.code),
                {
                    "bot": bot,
                    "ctx": None,
                    "__import__": __import__,
                    "print": lambda *args, **kwargs: print(*args, file=buffer, **kwargs)
                }
            )

        except Exception:
            buffer.write(traceback.format_exc())

        output = buffer.getvalue().strip()

        if not output:
            output = "SEM OUTPUT"

        await interaction.response.send_message(
            f"```py\n{output[:1900]}```",
            ephemeral=True
        )


class ConsoleView(discord.ui.View):

    @discord.ui.button(label="Abrir Console", style=discord.ButtonStyle.primary)
    async def open_console(self, interaction: discord.Interaction, button: discord.ui.Button):

        if interaction.user.id != OWNER_ID:
            return await interaction.response.send_message("Sem permissão.", ephemeral=True)

        await interaction.response.send_modal(ExecModal())

# =================================================


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
async def console(ctx):

    if ctx.author.id != OWNER_ID:
        return await ctx.send("Sem permissão.")

    await ctx.send("Console de desenvolvimento:", view=ConsoleView())


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
@commands.has_permissions(manage_roles=True)
async def addrole(ctx, member: discord.Member, role: discord.Role):
    await member.add_roles(role)
    await ctx.send("Cargo adicionado.")


@bot.command()
@commands.has_permissions(manage_roles=True)
async def removerole(ctx, member: discord.Member, role: discord.Role):
    await member.remove_roles(role)
    await ctx.send("Cargo removido.")


@bot.command()
@commands.has_permissions(manage_channels=True)
async def lock(ctx):
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False)
    await ctx.send("Canal bloqueado.")


@bot.command()
@commands.has_permissions(manage_channels=True)
async def unlock(ctx):
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=True)
    await ctx.send("Canal desbloqueado.")


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


@bot.command()
@commands.has_permissions(administrator=True)
async def setlogch(ctx, channel: discord.TextChannel):
    await db.set_log_channel(ctx.guild.id, channel.id)
    await ctx.send(f"Logs configurados para {channel.mention}")


@bot.command()
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, minutos: int, *, motivo="Sem motivo"):
    import datetime

    await member.timeout(datetime.timedelta(minutes=minutos), reason=motivo)

    await ctx.send(f"{member.mention} mutado por {minutos} minutos.")
    await send_log(ctx.guild, f"MUTE | {member} | {minutos}min | {motivo}")


@bot.command()
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):
    await member.timeout(None)
    await ctx.send(f"{member.mention} desmutado.")
    await send_log(ctx.guild, f"UNMUTE | {member}")


bot.run(TOKEN)
