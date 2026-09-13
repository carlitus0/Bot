import os
import discord
from discord.ext import commands
from datetime import timedelta

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)

# =========================================================
# CONFIGURAÇÕES
# =========================================================

log_channels = {}
slowmode_channels = set()


# =========================================================
# EVENTOS
# =========================================================

@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")


@bot.event
async def on_message(message):

    if message.author.bot:
        return

    if bot.user in message.mentions:
        await message.channel.send("que")

    await bot.process_commands(message)


# =========================================================
# PING
# =========================================================

@bot.command()
async def ping(ctx):
    ms = round(bot.latency * 1000)
    await ctx.send(f"🏓 Pong! `{ms}ms`")


# =========================================================
# WARN
# =========================================================

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


# =========================================================
# WARNS
# =========================================================

@bot.command()
@commands.has_permissions(manage_messages=True)
async def warns(ctx, member: discord.Member):

    await ctx.send(
        f"📋 **Warns de {member}**\n"
        f"⚠️ O sistema de histórico será adicionado ao banco de dados."
    )


# =========================================================
# UNWARN
# =========================================================

@bot.command()
@commands.has_permissions(manage_messages=True)
async def unwarn(ctx, member: discord.Member):

    await ctx.send(
        f"✅ Um warn de {member.mention} foi removido."
    )


# =========================================================
# MUTE / TIMEOUT
# =========================================================

@bot.command()
@commands.has_permissions(moderate_members=True)
async def mute(
    ctx,
    member: discord.Member,
    minutos: int,
    *,
    motivo="Nenhum motivo informado"
):

    if minutos <= 0:
        return await ctx.send("❌ Informe um tempo válido.")

    if minutos > 40320:
        return await ctx.send(
            "❌ O máximo permitido é 28 dias."
        )

    if member == ctx.author:
        return await ctx.send(
            "❌ Você não pode aplicar timeout em si mesmo."
        )

    if member.top_role >= ctx.author.top_role:
        return await ctx.send(
            "❌ Você não pode punir alguém com cargo igual ou superior ao seu."
        )

    if member.top_role >= ctx.guild.me.top_role:
        return await ctx.send(
            "❌ Meu cargo precisa estar acima do usuário."
        )

    try:
        await member.timeout(
            timedelta(minutes=minutos),
            reason=motivo
        )

        try:
            await member.send(
                f"🔇 Você recebeu um timeout em **{ctx.guild.name}**.\n"
                f"⏱️ Duração: `{minutos} minutos`\n"
                f"📝 Motivo: {motivo}"
            )
        except discord.Forbidden:
            pass

        await ctx.send(
            f"🔇 {member.mention} recebeu timeout por "
            f"`{minutos} minutos`.\n"
            f"📝 Motivo: `{motivo}`"
        )

    except discord.Forbidden:
        await ctx.send(
            "❌ Não tenho permissão para aplicar timeout nesse usuário."
        )


# =========================================================
# UNMUTE
# =========================================================

@bot.command()
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):

    try:
        await member.timeout(None)

        await ctx.send(
            f"🔊 O timeout de {member.mention} foi removido."
        )

    except discord.Forbidden:
        await ctx.send(
            "❌ Não tenho permissão para remover o timeout."
        )


# =========================================================
# BAN
# =========================================================

@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(
    ctx,
    member: discord.Member,
    *,
    motivo="Nenhum motivo informado"
):

    if member == ctx.author:
        return await ctx.send(
            "❌ Você não pode banir a si mesmo."
        )

    if member == ctx.guild.owner:
        return await ctx.send(
            "❌ Você não pode banir o dono do servidor."
        )

    if member.top_role >= ctx.author.top_role:
        return await ctx.send(
            "❌ Você não pode banir alguém com cargo igual ou superior ao seu."
        )

    if member.top_role >= ctx.guild.me.top_role:
        return await ctx.send(
            "❌ Meu cargo precisa estar acima do usuário."
        )

    try:
        await member.send(
            f"🔨 Você foi banido do servidor **{ctx.guild.name}**.\n"
            f"📝 Motivo: {motivo}"
        )
    except discord.Forbidden:
        pass

    await member.ban(reason=motivo)

    await ctx.send(
        f"🔨 {member.mention} foi banido.\n"
        f"📝 Motivo: `{motivo}`"
    )


# =========================================================
# UNBAN
# =========================================================

@bot.command()
@commands.has_permissions(ban_members=True)
async def unban(ctx, user_id: int):

    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user)

        await ctx.send(
            f"🔓 Banimento de `{user}` removido."
        )

    except discord.NotFound:
        await ctx.send(
            "❌ Usuário não está banido ou não foi encontrado."
        )

    except discord.Forbidden:
        await ctx.send(
            "❌ Não tenho permissão para desbanir."
        )


# =========================================================
# KICK
# =========================================================

@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(
    ctx,
    member: discord.Member,
    *,
    motivo="Nenhum motivo informado"
):

    if member == ctx.author:
        return await ctx.send(
            "❌ Você não pode expulsar a si mesmo."
        )

    if member.top_role >= ctx.author.top_role:
        return await ctx.send(
            "❌ Você não pode expulsar alguém com cargo igual ou superior ao seu."
        )

    try:
        await member.send(
            f"👢 Você foi expulso do servidor **{ctx.guild.name}**.\n"
            f"📝 Motivo: {motivo}"
        )
    except discord.Forbidden:
        pass

    await member.kick(reason=motivo)

    await ctx.send(
        f"👢 {member.mention} foi expulso.\n"
        f"📝 Motivo: `{motivo}`"
    )


# =========================================================
# CLEAR
# =========================================================

@bot.command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx, quantidade: int):

    if quantidade <= 0:
        return await ctx.send(
            "❌ Informe uma quantidade válida."
        )

    if quantidade > 100:
        return await ctx.send(
            "❌ O máximo por vez é 100 mensagens."
        )

    apagadas = await ctx.channel.purge(limit=quantidade + 1)

    mensagem = await ctx.send(
        f"🧹 `{len(apagadas) - 1}` mensagens apagadas."
    )

    await mensagem.delete(delay=3)


# =========================================================
# SLOWMODE
# =========================================================

@bot.command()
@commands.has_permissions(manage_channels=True)
async def slowmode(ctx, segundos: int):

    if segundos < 0 or segundos > 21600:
        return await ctx.send(
            "❌ Use um valor entre 0 e 21600 segundos."
        )

    await ctx.channel.edit(
        slowmode_delay=segundos
    )

    if segundos == 0:
        await ctx.send("🐌 Slowmode desativado.")
    else:
        await ctx.send(
            f"🐌 Slowmode definido para `{segundos} segundos`."
        )


# =========================================================
# SERVERINFO
# =========================================================

@bot.command()
async def serverinfo(ctx):

    guild = ctx.guild

    embed = discord.Embed(
        title=f"📊 {guild.name}",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="👑 Dono",
        value=guild.owner.mention if guild.owner else "Desconhecido",
        inline=False
    )

    embed.add_field(
        name="👥 Membros",
        value=guild.member_count,
        inline=True
    )

    embed.add_field(
        name="💬 Canais",
        value=len(guild.channels),
        inline=True
    )

    embed.add_field(
        name="🎭 Cargos",
        value=len(guild.roles),
        inline=True
    )

    embed.add_field(
        name="🆔 ID",
        value=guild.id,
        inline=False
    )

    await ctx.send(embed=embed)


# =========================================================
# USERINFO
# =========================================================

@bot.command()
async def userinfo(ctx, member: discord.Member = None):

    member = member or ctx.author

    embed = discord.Embed(
        title=f"👤 {member}",
        color=discord.Color.blurple()
    )

    embed.set_thumbnail(
        url=member.display_avatar.url
    )

    embed.add_field(
        name="🆔 ID",
        value=member.id,
        inline=False
    )

    embed.add_field(
        name="📅 Entrou",
        value=discord.utils.format_dt(member.joined_at, "F"),
        inline=False
    )

    embed.add_field(
        name="🎭 Cargo principal",
        value=member.top_role.mention,
        inline=False
    )

    await ctx.send(embed=embed)


# =========================================================
# AVATAR
# =========================================================

@bot.command()
async def avatar(ctx, member: discord.Member = None):

    member = member or ctx.author

    embed = discord.Embed(
        title=f"🖼️ Avatar de {member}",
        color=discord.Color.blurple()
    )

    embed.set_image(
        url=member.display_avatar.url
    )

    await ctx.send(embed=embed)


# =========================================================
# ROLE
# =========================================================

@bot.command()
@commands.has_permissions(manage_roles=True)
async def role(
    ctx,
    member: discord.Member,
    *,
    nome_cargo
):

    cargo = discord.utils.find(
        lambda r: r.name.lower() == nome_cargo.lower(),
        ctx.guild.roles
    )

    if cargo is None:
        return await ctx.send(
            "❌ Cargo não encontrado."
        )

    if cargo >= ctx.guild.me.top_role:
        return await ctx.send(
            "❌ Não posso administrar esse cargo."
        )

    await member.add_roles(cargo)

    await ctx.send(
        f"✅ {cargo.mention} adicionado a {member.mention}."
    )


# =========================================================
# UNROLE
# =========================================================

@bot.command()
@commands.has_permissions(manage_roles=True)
async def unrole(
    ctx,
    member: discord.Member,
    *,
    nome_cargo
):

    cargo = discord.utils.find(
        lambda r: r.name.lower() == nome_cargo.lower(),
        ctx.guild.roles
    )

    if cargo is None:
        return await ctx.send(
            "❌ Cargo não encontrado."
        )

    if cargo >= ctx.guild.me.top_role:
        return await ctx.send(
            "❌ Não posso administrar esse cargo."
        )

    await member.remove_roles(cargo)

    await ctx.send(
        f"✅ {cargo.mention} removido de {member.mention}."
    )


# =========================================================
# LOCK
# =========================================================

@bot.command()
@commands.has_permissions(manage_channels=True)
async def lock(ctx):

    overwrite = ctx.channel.overwrites_for(
        ctx.guild.default_role
    )

    overwrite.send_messages = False

    await ctx.channel.set_permissions(
        ctx.guild.default_role,
        overwrite=overwrite
    )

    await ctx.send("🔒 Canal bloqueado.")


# =========================================================
# UNLOCK
# =========================================================

@bot.command()
@commands.has_permissions(manage_channels=True)
async def unlock(ctx):

    overwrite = ctx.channel.overwrites_for(
        ctx.guild.default_role
    )

    overwrite.send_messages = None

    await ctx.channel.set_permissions(
        ctx.guild.default_role,
        overwrite=overwrite
    )

    await ctx.send("🔓 Canal desbloqueado.")


# =========================================================
# SETLOG
# =========================================================

@bot.command()
@commands.has_permissions(administrator=True)
async def setlog(ctx, canal: discord.TextChannel):

    log_channels[ctx.guild.id] = canal.id

    await ctx.send(
        f"📋 Canal de logs definido como {canal.mention}."
    )


# =========================================================
# SAY
# =========================================================

@bot.command()
@commands.has_permissions(manage_messages=True)
async def say(ctx, *, mensagem):

    await ctx.message.delete()
    await ctx.send(mensagem)


# =========================================================
# EMBED
# =========================================================

@bot.command()
@commands.has_permissions(manage_messages=True)
async def embed(ctx, *, mensagem):

    await ctx.message.delete()

    embed = discord.Embed(
        description=mensagem,
        color=discord.Color.blurple()
    )

    await ctx.send(embed=embed)


# =========================================================
# TICKET
# =========================================================

class TicketView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Abrir Ticket",
        emoji="🎫",
        style=discord.ButtonStyle.green,
        custom_id="abrir_ticket"
    )
    async def abrir_ticket(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        guild = interaction.guild

        existente = discord.utils.get(
            guild.text_channels,
            name=f"ticket-{interaction.user.id}"
        )

        if existente:
            return await interaction.response.send_message(
                f"❌ Você já possui um ticket: {existente.mention}",
                ephemeral=True
            )

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False
            ),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True
            )
        }

        canal = await guild.create_text_channel(
            f"ticket-{interaction.user.id}",
            overwrites=overwrites
        )

        await canal.send(
            f"🎫 Ticket de {interaction.user.mention}\n"
            f"Explique seu problema aqui."
        )

        await interaction.response.send_message(
            f"✅ Ticket criado: {canal.mention}",
            ephemeral=True
        )


@bot.command()
@commands.has_permissions(manage_channels=True)
async def ticket(ctx):

    embed = discord.Embed(
        title="🎫 Sistema de Tickets",
        description=(
            "Clique no botão abaixo para abrir um ticket."
        ),
        color=discord.Color.blurple()
    )

    await ctx.send(
        embed=embed,
        view=TicketView()
    )


# =========================================================
# HELP
# =========================================================

@bot.command(name="help")
async def help_command(ctx):

    embed = discord.Embed(
        title="📚 Comandos",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="🛡️ Moderação",
        value=(
            "`!warn @user motivo`\n"
            "`!warns @user`\n"
            "`!unwarn @user`\n"
            "`!mute @user minutos motivo`\n"
            "`!unmute @user`\n"
            "`!ban @user motivo`\n"
            "`!unban ID`\n"
            "`!kick @user motivo`\n"
            "`!clear quantidade`\n"
            "`!slowmode segundos`"
        ),
        inline=False
    )

    embed.add_field(
        name="🔧 Servidor",
        value=(
            "`!serverinfo`\n"
            "`!userinfo @user`\n"
            "`!avatar @user`\n"
            "`!role @user cargo`\n"
            "`!unrole @user cargo`\n"
            "`!lock`\n"
            "`!unlock`"
        ),
        inline=False
    )

    embed.add_field(
        name="🎫 Extras",
        value=(
            "`!setlog #canal`\n"
            "`!ticket`\n"
            "`!say mensagem`\n"
            "`!embed mensagem`\n"
            "`!ping`"
        ),
        inline=False
    )

    await ctx.send(embed=embed)


# =========================================================
# ERROS
# =========================================================

@bot.event
async def on_command_error(ctx, error):

    if isinstance(error, commands.MissingPermissions):
        await ctx.send(
            "❌ Você não tem permissão para usar esse comando."
        )

    elif isinstance(error, commands.MemberNotFound):
        await ctx.send(
            "❌ Usuário não encontrado."
        )

    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            "❌ Faltou algum argumento no comando."
        )

    elif isinstance(error, commands.BadArgument):
        await ctx.send(
            "❌ Argumento inválido."
        )

    elif isinstance(error, commands.CommandNotFound):
        pass

    else:
        print(f"Erro: {error}")


# =========================================================
# INICIAR
# =========================================================

if not TOKEN:
    print("❌ A variável TOKEN não foi encontrada no Railway.")
else:
    bot.run(TOKEN)
