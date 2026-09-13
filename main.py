import os
import discord
from discord.ext import commands

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)


@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")


# =========================
# PING
# =========================

@bot.command()
async def ping(ctx):
    await ctx.send(f"🏓 Pong! `{round(bot.latency * 1000)}ms`")


# =========================
# WARN
# =========================

@bot.command()
@commands.has_permissions(manage_messages=True)
async def warn(ctx, member: discord.Member, *, motivo="Nenhum motivo informado"):

    if member == ctx.author:
        return await ctx.send("❌ Você não pode dar warn em si mesmo.")

    try:
        await member.send(
            f"⚠️ Você recebeu um warn no servidor **{ctx.guild.name}**.\n"
            f"📝 Motivo: {motivo}"
        )
    except discord.Forbidden:
        pass

    await ctx.send(
        f"⚠️ {member.mention} recebeu um warn.\n"
        f"📝 Motivo: `{motivo}`"
    )


@warn.error
async def warn_error(ctx, error):

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Use: `!warn @usuário motivo`")

    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Usuário não encontrado.")

    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Você não tem permissão para usar esse comando.")


# =========================
# INICIAR
# =========================

if not TOKEN:
    print("❌ TOKEN não encontrado.")
else:
    bot.run(TOKEN)
