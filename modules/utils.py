import discord
from discord.ext import commands

# =========================
# STORAGE LOCAL DO MODULE
# =========================

log_channels = {}
automod_words = {}
loop_tasks = {}

# =========================
# LOG SYSTEM
# =========================

async def send_log(guild, msg):
    cid = log_channels.get(guild.id)
    if not cid:
        return
    channel = guild.get_channel(cid)
    if channel:
        await channel.send(msg)


class Utils(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # =========================
    # LOG COMMANDS
    # =========================

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def logcmd(self, ctx, channel: discord.TextChannel):
        log_channels[ctx.guild.id] = channel.id
        await ctx.send("Logs ativados")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def unsetlogcmd(self, ctx):
        log_channels.pop(ctx.guild.id, None)
        await ctx.send("Logs desativados")

    # =========================
    # AUTOMOD
    # =========================

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def automod_add(self, ctx, word):
        automod_words.setdefault(ctx.guild.id, set()).add(word.lower())
        await ctx.send("Palavra adicionada")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def automod_remove(self, ctx, word):
        g = automod_words.get(ctx.guild.id)
        if g:
            g.discard(word.lower())
        await ctx.send("Removido")

    # =========================
    # MODERAÇÃO
    # =========================

    @commands.command()
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, member: discord.Member, *, reason=None):
        await member.ban(reason=reason)
        await ctx.send(f"{member} banido")
        await send_log(ctx.guild, f"BAN | {member}")

    @commands.command()
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason=None):
        await member.kick(reason=reason)
        await ctx.send(f"{member} kickado")
        await send_log(ctx.guild, f"KICK | {member}")

    # =========================
    # UTIL
    # =========================

    @commands.command()
    async def ping(self, ctx):
        await ctx.send(f"{round(self.bot.latency * 1000)}ms")

    @commands.command()
    async def status(self, ctx):
        g = ctx.guild
        await ctx.send(f"Membros: {g.member_count} | Canais: {len(g.channels)}")


# =========================
# SETUP OBRIGATÓRIO
# =========================

async def setup(bot):
    await bot.add_cog(Utils(bot))
