import os
import discord
from discord.ext import commands
from discord import Embed
from datetime import datetime, timedelta
from discord.utils import utcnow
import json
import asyncio
from discord.ui import View, Button
import sqlite3

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)

# =========================
# STAFF
# =========================

staff_roles = set()
staff_users = set()


def has_staff_permission(member):
    if member.guild_permissions.administrator:
        return True

    if member.id in staff_users:
        return True

    return any(role.id in staff_roles for role in member.roles)


def is_staff():
    async def predicate(ctx):
        if has_staff_permission(ctx.author):
            return True

        raise commands.CheckFailure

    return commands.check(predicate)


@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user}")


# =========================
# STAFF / UNSTAFF
# =========================

@bot.command()
@commands.has_permissions(administrator=True)
async def staff(ctx, alvo: discord.Role | discord.Member):

    if isinstance(alvo, discord.Role):
        staff_roles.add(alvo.id)

        await ctx.send(
            f"✅ O cargo {alvo.mention} agora pode usar comandos de moderação."
        )

    else:
        staff_users.add(alvo.id)

        await ctx.send(
            f"✅ {alvo.mention} agora pode usar comandos de moderação."
        )


@bot.command()
@commands.has_permissions(administrator=True)
async def unstaff(ctx, alvo: discord.Role | discord.Member):

    if isinstance(alvo, discord.Role):
        staff_roles.discard(alvo.id)

        await ctx.send(
            f"✅ O cargo {alvo.mention} perdeu acesso aos comandos de moderação."
        )

    else:
        staff_users.discard(alvo.id)

        await ctx.send(
            f"✅ {alvo.mention} perdeu acesso aos comandos de moderação."
        )


# =========================
# BAN
# =========================

@bot.command()
@is_staff()
async def ban(ctx, member: discord.Member, *, motivo="Nenhum motivo informado"):

    if member == ctx.author:
        return await ctx.send(
            "❌ Você não pode banir a si mesmo."
        )

    if member == ctx.guild.owner:
        return await ctx.send(
            "❌ Você não pode banir o dono do servidor."
        )

    if (
        member.top_role >= ctx.author.top_role
        and ctx.author != ctx.guild.owner
    ):
        return await ctx.send(
            "❌ Você não pode banir alguém com cargo igual ou superior ao seu."
        )

    if member.top_role >= ctx.guild.me.top_role:
        return await ctx.send(
            "❌ Meu cargo precisa estar acima do cargo deste usuário."
        )

    embed = Embed(
        title="🔨 Você foi banido",
        description="Você foi removido do servidor.",
        color=discord.Color.red(),
        timestamp=datetime.utcnow()
    )

    embed.add_field(
        name="Servidor",
        value=ctx.guild.name,
        inline=False
    )

    embed.add_field(
        name="Motivo",
        value=motivo,
        inline=False
    )

    embed.add_field(
        name="Moderador",
        value=str(ctx.author),
        inline=False
    )

    embed.add_field(
        name="Aviso",
        value=(
            "Se você acredita que este banimento foi aplicado incorretamente, "
            "entre em contato com a equipe do servidor."
        ),
        inline=False
    )

    embed.set_footer(text="Sistema de Moderação")

    try:
        await member.send(embed=embed)
    except:
        pass

    await member.ban(
        reason=f"{motivo} | Staff: {ctx.author}"
    )

    await ctx.send(
        f"✅ {member.mention} foi banido.\n"
        f"📝 Motivo: `{motivo}`"
    )


# =========================
# RBAN
# =========================

@bot.command()
@is_staff()
async def rban(ctx, user_id: int, *, motivo="Nenhum motivo informado"):

    try:
        user = await bot.fetch_user(user_id)

        await ctx.guild.unban(
            user,
            reason=f"{motivo} | Staff: {ctx.author}"
        )

        embed = Embed(
            title="🔓 Seu banimento foi removido",
            description="Você pode entrar novamente no servidor.",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )

        embed.add_field(
            name="Servidor",
            value=ctx.guild.name,
            inline=False
        )

        embed.add_field(
            name="Motivo",
            value=motivo,
            inline=False
        )

        embed.add_field(
            name="Moderador",
            value=str(ctx.author),
            inline=False
        )

        embed.set_footer(
            text="Sistema de Moderação"
        )

        try:
            await user.send(embed=embed)
        except:
            pass

        await ctx.send(
            f"✅ O banimento de **{user}** foi removido."
        )

    except discord.NotFound:
        await ctx.send(
            "❌ Usuário não encontrado ou não está banido."
        )

    except discord.Forbidden:
        await ctx.send(
            "❌ Não tenho permissão para remover este banimento."
        )


# =========================
# MUTE
# =========================

@bot.command(
    name="mute",
    help="Aplica um timeout em um membro."
)
async def mute(
    ctx,
    member: discord.Member,
    minutos: int,
    *,
    motivo="Nenhum motivo informado"
):

    if not has_staff_permission(ctx.author):
        return await ctx.send(
            "❌ Você não possui permissão para usar este comando."
        )

    if member == ctx.author:
        return await ctx.send(
            "❌ Você não pode aplicar timeout em si mesmo."
        )

    if member == ctx.guild.owner:
        return await ctx.send(
            "❌ Você não pode aplicar timeout no dono do servidor."
        )

    if (
        member.top_role >= ctx.author.top_role
        and ctx.author != ctx.guild.owner
    ):
        return await ctx.send(
            "❌ Você não pode punir alguém com cargo igual ou superior ao seu."
        )

    bot_member = ctx.guild.get_member(bot.user.id)

    if bot_member is None:
        return await ctx.send(
            "❌ Não consegui encontrar meu próprio membro no servidor."
        )

    if not bot_member.guild_permissions.moderate_members:
        return await ctx.send(
            "❌ Eu não tenho a permissão 'Moderar membros'."
        )

    if member.top_role >= bot_member.top_role:
        return await ctx.send(
            "❌ Meu cargo precisa estar acima do cargo deste usuário."
        )

    if minutos <= 0:
        return await ctx.send(
            "❌ Informe um tempo válido em minutos."
        )

    if minutos > 40320:
        return await ctx.send(
            "❌ O tempo máximo de timeout é 28 dias (40320 minutos)."
        )

    until = utcnow() + timedelta(minutes=minutos)

    embed_dm = discord.Embed(
        title="🔇 Você recebeu um timeout",
        description=(
            "Seu acesso para enviar mensagens, participar de chamadas "
            "de voz e interagir no servidor foi temporariamente restringido."
        ),
        color=discord.Color.orange(),
        timestamp=utcnow()
    )

    embed_dm.add_field(
        name="🏠 Servidor",
        value=ctx.guild.name,
        inline=False
    )

    embed_dm.add_field(
        name="⏱️ Duração",
        value=f"{minutos} minuto(s)",
        inline=True
    )

    embed_dm.add_field(
        name="📝 Motivo",
        value=motivo,
        inline=False
    )

    embed_dm.add_field(
        name="🛡️ Moderador",
        value=str(ctx.author),
        inline=False
    )

    embed_dm.add_field(
        name="ℹ️ Informações",
        value=(
            "Após o término do tempo, suas permissões serão restauradas "
            "automaticamente.\n\n"
            "Caso considere a punição incorreta, entre em contato com a equipe."
        ),
        inline=False
    )

    embed_dm.set_footer(
        text="Sistema de Moderação"
    )

    try:
        await member.send(embed=embed_dm)
    except discord.Forbidden:
        pass

    await member.timeout(
        until,
        reason=f"{motivo} | Staff: {ctx.author}"
    )

    embed_publico = discord.Embed(
        title="🔇 Timeout aplicado",
        color=discord.Color.orange(),
        timestamp=utcnow()
    )

    embed_publico.add_field(
        name="👤 Usuário",
        value=f"{member.mention} (`{member.id}`)",
        inline=False
    )

    embed_publico.add_field(
        name="⏱️ Duração",
        value=f"{minutos} minuto(s)",
        inline=True
    )

    embed_publico.add_field(
        name="🛡️ Moderador",
        value=ctx.author.mention,
        inline=True
    )

    embed_publico.add_field(
        name="📝 Motivo",
        value=motivo,
        inline=False
    )

    await ctx.send(
        embed=embed_publico
    )


@mute.error
async def mute_error(ctx, error):

    if isinstance(error, commands.MemberNotFound):
        await ctx.send(
            "❌ Usuário não encontrado."
        )

    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            "❌ Uso correto: `!mute @usuário <minutos> <motivo>`"
        )

    elif isinstance(error, commands.BadArgument):
        await ctx.send(
            "❌ O tempo deve ser um número inteiro."
        )

    else:
        raise error


# =========================
# WARN
# =========================

@bot.command(
    name="warn",
    help="Aplica uma advertência em um membro."
)
async def warn(
    ctx,
    member: discord.Member,
    *,
    motivo="Nenhum motivo informado"
):

    if not has_staff_permission(ctx.author):
        return await ctx.send(
            "❌ Você não possui permissão para usar este comando."
        )

    if member == ctx.author:
        return await ctx.send(
            "❌ Você não pode advertir a si mesmo."
        )

    if member == ctx.guild.owner:
        return await ctx.send(
            "❌ Você não pode advertir o dono do servidor."
        )

    if (
        member.top_role >= ctx.author.top_role
        and ctx.author != ctx.guild.owner
    ):
        return await ctx.send(
            "❌ Você não pode advertir alguém com cargo igual ou superior ao seu."
        )

    if member.top_role >= ctx.guild.me.top_role:
        return await ctx.send(
            "❌ Meu cargo precisa estar acima do cargo deste usuário."
        )

    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS warns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    data_warn = datetime.utcnow().strftime(
        "%d/%m/%Y %H:%M:%S"
    )

    cursor.execute("""
        INSERT INTO warns (
            guild_id,
            user_id,
            moderator_id,
            reason,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        ctx.guild.id,
        member.id,
        ctx.author.id,
        motivo,
        data_warn
    ))

    conn.commit()

    cursor.execute("""
        SELECT COUNT(*)
        FROM warns
        WHERE guild_id = ? AND user_id = ?
    """, (
        ctx.guild.id,
        member.id
    ))

    total_warns = cursor.fetchone()[0]

    conn.close()

    embed_dm = discord.Embed(
        title="⚠️ Você recebeu uma advertência",
        description="Esta é uma notificação oficial da equipe de moderação.",
        color=discord.Color.gold(),
        timestamp=datetime.utcnow()
    )

    embed_dm.add_field(
        name="🏠 Servidor",
        value=ctx.guild.name,
        inline=False
    )

    embed_dm.add_field(
        name="📝 Motivo",
        value=motivo,
        inline=False
    )

    embed_dm.add_field(
        name="📊 Advertências",
        value=f"{total_warns}/4",
        inline=True
    )

    embed_dm.add_field(
        name="🛡️ Moderador",
        value=str(ctx.author),
        inline=True
    )

    embed_dm.add_field(
        name="ℹ️ Aviso",
        value=(
            "Ao atingir 4 advertências, o banimento será aplicado automaticamente.\n"
            "Caso considere esta punição incorreta, entre em contato com a equipe."
        ),
        inline=False
    )

    embed_dm.set_footer(
        text="Sistema de Moderação"
    )

    try:
        await member.send(embed=embed_dm)
    except discord.Forbidden:
        pass

    embed_publico = discord.Embed(
        title="⚠️ Advertência aplicada",
        color=discord.Color.gold(),
        timestamp=datetime.utcnow()
    )

    embed_publico.add_field(
        name="👤 Usuário",
        value=f"{member.mention} (`{member.id}`)",
        inline=False
    )

    embed_publico.add_field(
        name="📊 Advertências",
        value=f"{total_warns}/4",
        inline=True
    )

    embed_publico.add_field(
        name="🛡️ Moderador",
        value=ctx.author.mention,
        inline=True
    )

    embed_publico.add_field(
        name="📝 Motivo",
        value=motivo,
        inline=False
    )

    await ctx.send(
        embed=embed_publico
    )

    if total_warns >= 4:

        embed_ban = discord.Embed(
            title="🔨 Você foi banido",
            description="Você atingiu o limite máximo de advertências permitido.",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )

        embed_ban.add_field(
            name="🏠 Servidor",
            value=ctx.guild.name,
            inline=False
        )

        embed_ban.add_field(
            name="📊 Advertências",
            value=f"{total_warns}/4",
            inline=True
        )

        embed_ban.add_field(
            name="📝 Motivo",
            value="Acúmulo de advertências.",
            inline=False
        )

        embed_ban.set_footer(
            text="Sistema de Moderação"
        )

        try:
            await member.send(embed=embed_ban)
        except discord.Forbidden:
            pass

        await member.ban(
            reason="Banimento automático: 4 advertências."
        )

        await ctx.send(
            f"🔨 {member.mention} foi banido automaticamente "
            f"por atingir 4 advertências."
        )


# =========================
# WARNS
# =========================

@bot.command(
    name="warns",
    help="Exibe as advertências de um membro."
)
async def warns(
    ctx,
    member: discord.Member = None
):

    if not has_staff_permission(ctx.author):
        return await ctx.send(
            "❌ Você não possui permissão para usar este comando."
        )

    member = member or ctx.author

    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS warns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        SELECT moderator_id, reason, created_at
        FROM warns
        WHERE guild_id = ? AND user_id = ?
        ORDER BY id DESC
    """, (
        ctx.guild.id,
        member.id
    ))

    registros = cursor.fetchall()

    conn.close()

    if not registros:
        return await ctx.send(
            f"✅ {member.mention} não possui advertências."
        )

    embed = discord.Embed(
        title=f"📋 Advertências de {member}",
        color=discord.Color.orange(),
        timestamp=datetime.utcnow()
    )

    embed.set_thumbnail(
        url=member.display_avatar.url
    )

    embed.description = (
        f"**Total de advertências:** {len(registros)}/4\n\n"
    )

    for indice, (
        moderator_id,
        reason,
        created_at
    ) in enumerate(
        registros[:10],
        start=1
    ):

        moderador = bot.get_user(
            moderator_id
        )

        embed.add_field(
            name=f"⚠️ Warn #{indice}",
            value=(
                f"**Motivo:** {reason}\n"
                f"**Moderador:** {moderador or moderator_id}\n"
                f"**Data:** {created_at}"
            ),
            inline=False
        )

    embed.set_footer(
        text="Máximo exibido: 10 advertências"
    )

    await ctx.send(
        embed=embed
    )


@warn.error
@warns.error
async def warn_error(ctx, error):

    if isinstance(error, commands.MemberNotFound):
        await ctx.send(
            "❌ Usuário não encontrado."
        )

    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            "❌ Uso correto:\n"
            "`!warn @usuário <motivo>`\n"
            "`!warns @usuário`"
        )

    else:
        raise error


# =========================
# HACKBAN
# =========================

@bot.command()
async def hackban(
    ctx,
    user_id: int,
    *,
    motivo="Nenhum motivo informado"
):

    if not has_staff_permission(ctx.author):
        return await ctx.send(
            "❌ Você não possui permissão para usar este comando."
        )

    try:
        user = await bot.fetch_user(
            user_id
        )

        embed = Embed(
            title="🔨 Você foi banido",
            description=(
                "Seu acesso a um servidor foi permanentemente revogado "
                "por descumprimento das regras."
            ),
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )

        embed.add_field(
            name="Servidor",
            value=ctx.guild.name,
            inline=False
        )

        embed.add_field(
            name="Motivo",
            value=motivo,
            inline=False
        )

        embed.add_field(
            name="Moderador",
            value=str(ctx.author),
            inline=False
        )

        embed.add_field(
            name="Tipo de punição",
            value="Banimento por ID (Hackban)",
            inline=False
        )

        embed.add_field(
            name="Aviso",
            value=(
                "Caso considere esta punição incorreta, "
                "entre em contato com a equipe responsável."
            ),
            inline=False
        )

        embed.set_footer(
            text="Sistema de Moderação"
        )

        try:
            await user.send(
                embed=embed
            )
        except:
            pass

        await ctx.guild.ban(
            user,
            reason=f"{motivo} | Staff: {ctx.author}"
        )

        await ctx.send(
            f"✅ Usuário `{user}` (`{user.id}`) foi banido por ID.\n"
            f"📝 Motivo: `{motivo}`"
        )

    except discord.NotFound:
        await ctx.send(
            "❌ Usuário não encontrado."
        )

    except discord.Forbidden:
        await ctx.send(
            "❌ Não tenho permissão para realizar este banimento."
        )

    except Exception as e:
        await ctx.send(
            f"❌ Ocorreu um erro: `{e}`"
        )


# =========================
# UNBAN
# =========================

@bot.command()
async def unban(
    ctx,
    user_id: int,
    *,
    motivo="Nenhum motivo informado"
):

    if not has_staff_permission(ctx.author):
        return await ctx.send(
            "❌ Você não possui permissão para usar este comando."
        )

    try:
        user = await bot.fetch_user(
            user_id
        )

        await ctx.guild.unban(
            user,
            reason=f"{motivo} | Staff: {ctx.author}"
        )

        embed = Embed(
            title="🔓 Seu banimento foi removido",
            description="Você pode e
