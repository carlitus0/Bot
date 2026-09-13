import os
import re
import sqlite3
import asyncio
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput


# =========================================================
# CONFIG
# =========================================================

TOKEN = os.getenv("TOKEN")
PREFIX = "!"
DB_FILE = "bot.db"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None
)


# =========================================================
# DATABASE
# =========================================================

def db():
    return sqlite3.connect(DB_FILE)


def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS guild_config (
            guild_id INTEGER PRIMARY KEY,
            log_channel INTEGER,
            automod_channel INTEGER,
            staff_role INTEGER,
            prison_role INTEGER,
            ticket_category INTEGER,
            ticket_log_channel INTEGER,
            blocked_words TEXT DEFAULT '',
            automod_links INTEGER DEFAULT 0,
            automod_invites INTEGER DEFAULT 0,
            automod_caps INTEGER DEFAULT 0,
            automod_spam INTEGER DEFAULT 0,
            automod_mentions INTEGER DEFAULT 0,
            automod_repeat INTEGER DEFAULT 0,
            punishment_dm INTEGER DEFAULT 1,
            show_moderator INTEGER DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS warns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            user_id INTEGER,
            moderator_id INTEGER,
            reason TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS mutes (
            guild_id INTEGER,
            user_id INTEGER,
            expires_at TEXT,
            PRIMARY KEY(guild_id, user_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS whitelist (
            guild_id INTEGER,
            target_id INTEGER,
            target_type TEXT,
            PRIMARY KEY(guild_id, target_id, target_type)
        )
    """)

    con.commit()
    con.close()


def get_config(guild_id):
    con = db()
    cur = con.cursor()

    cur.execute(
        "SELECT * FROM guild_config WHERE guild_id = ?",
        (guild_id,)
    )

    row = cur.fetchone()

    if not row:
        cur.execute(
            "INSERT INTO guild_config (guild_id) VALUES (?)",
            (guild_id,)
        )
        con.commit()

        cur.execute(
            "SELECT * FROM guild_config WHERE guild_id = ?",
            (guild_id,)
        )

        row = cur.fetchone()

    con.close()

    columns = [
        "guild_id",
        "log_channel",
        "automod_channel",
        "staff_role",
        "prison_role",
        "ticket_category",
        "ticket_log_channel",
        "blocked_words",
        "automod_links",
        "automod_invites",
        "automod_caps",
        "automod_spam",
        "automod_mentions",
        "automod_repeat",
        "punishment_dm",
        "show_moderator"
    ]

    return dict(zip(columns, row))


def set_config(guild_id, field, value):
    allowed = {
        "log_channel",
        "automod_channel",
        "staff_role",
        "prison_role",
        "ticket_category",
        "ticket_log_channel",
        "blocked_words",
        "automod_links",
        "automod_invites",
        "automod_caps",
        "automod_spam",
        "automod_mentions",
        "automod_repeat",
        "punishment_dm",
        "show_moderator"
    }

    if field not in allowed:
        return

    con = db()
    cur = con.cursor()

    cur.execute(
        f"UPDATE guild_config SET {field} = ? WHERE guild_id = ?",
        (value, guild_id)
    )

    con.commit()
    con.close()


# =========================================================
# UTILS
# =========================================================

def now():
    return datetime.now(timezone.utc)


def parse_duration(text):
    match = re.fullmatch(
        r"(\d+)\s*(s|m|h|d|w)",
        text.lower().strip()
    )

    if not match:
        return None

    value = int(match.group(1))
    unit = match.group(2)

    seconds = {
        "s": value,
        "m": value * 60,
        "h": value * 3600,
        "d": value * 86400,
        "w": value * 604800
    }[unit]

    return timedelta(seconds=seconds)


def duration_text(td):
    seconds = int(td.total_seconds())

    if seconds % 604800 == 0:
        return f"{seconds // 604800}w"

    if seconds % 86400 == 0:
        return f"{seconds // 86400}d"

    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"

    if seconds % 60 == 0:
        return f"{seconds // 60}m"

    return f"{seconds}s"


async def send_log(guild, title, description, color=discord.Color.blurple()):
    config = get_config(guild.id)

    channel_id = config["log_channel"]

    if not channel_id:
        return

    channel = guild.get_channel(channel_id)

    if not channel:
        return

    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=now()
    )

    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        pass


async def send_dm(member, title, description):
    try:
        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.red()
        )
        await member.send(embed=embed)
    except discord.HTTPException:
        pass


def is_staff(member):
    if not member.guild:
        return False

    config = get_config(member.guild.id)

    role_id = config["staff_role"]

    if role_id:
        role = member.guild.get_role(role_id)

        if role and role in member.roles:
            return True

    return member.guild_permissions.manage_guild


def is_whitelisted(guild_id, user_id=None, role_ids=None, channel_id=None):
    con = db()
    cur = con.cursor()

    ids = []

    if user_id:
        ids.append(("user", user_id))

    if role_ids:
        for role_id in role_ids:
            ids.append(("role", role_id))

    if channel_id:
        ids.append(("channel", channel_id))

    for target_type, target_id in ids:
        cur.execute(
            """
            SELECT 1 FROM whitelist
            WHERE guild_id = ? AND target_id = ? AND target_type = ?
            """,
            (guild_id, target_id, target_type)
        )

        if cur.fetchone():
            con.close()
            return True

    con.close()
    return False


# =========================================================
# EVENTS
# =========================================================

@bot.event
async def on_ready():
    init_db()

    # Views persistentes
    bot.add_view(TicketView())
    bot.add_view(StaffPanelView())

    print(
        f"Bot online: {bot.user} | "
        f"ID: {bot.user.id}"
    )


@bot.event
async def on_command_completion(ctx):
    if ctx.guild:
        await send_log(
            ctx.guild,
            "Comando executado",
            f"**Comando:** `{ctx.command}`\n"
            f"**Usuário:** {ctx.author.mention}\n"
            f"**Canal:** {ctx.channel.mention}",
            discord.Color.blue()
        )


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.MissingPermissions):
        await ctx.send("Você não possui permissão para usar esse comando.")
        return

    if isinstance(error, commands.BotMissingPermissions):
        await ctx.send("Eu não tenho as permissões necessárias.")
        return

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            f"Está faltando um argumento: `{error.param.name}`."
        )
        return

    if isinstance(error, commands.MemberNotFound):
        await ctx.send("Membro não encontrado.")
        return

    print(f"Erro: {repr(error)}")


@bot.event
async def on_member_join(member):
    await send_log(
        member.guild,
        "Membro entrou",
        f"{member.mention} entrou no servidor.",
        discord.Color.green()
    )


@bot.event
async def on_member_remove(member):
    await send_log(
        member.guild,
        "Membro saiu",
        f"**Usuário:** {member} (`{member.id}`)",
        discord.Color.orange()
    )


@bot.event
async def on_message_delete(message):
    if message.author.bot or not message.guild:
        return

    content = message.content or "*sem texto*"

    await send_log(
        message.guild,
        "Mensagem apagada",
        f"**Autor:** {message.author.mention}\n"
        f"**Canal:** {message.channel.mention}\n"
        f"**Conteúdo:** {content[:1500]}",
        discord.Color.orange()
    )


@bot.event
async def on_message_edit(before, after):
    if before.author.bot or not before.guild:
        return

    if before.content == after.content:
        return

    await send_log(
        before.guild,
        "Mensagem editada",
        f"**Autor:** {before.author.mention}\n"
        f"**Canal:** {before.channel.mention}\n\n"
        f"**Antes:** {before.content[:700]}\n"
        f"**Depois:** {after.content[:700]}",
        discord.Color.yellow()
    )


# =========================================================
# AUTOMOD
# =========================================================

spam_cache = {}
repeat_cache = {}


async def automod_message(message):
    if not message.guild or message.author.bot:
        return False

    config = get_config(message.guild.id)

    if is_whitelisted(
        message.guild.id,
        message.author.id,
        [r.id for r in message.author.roles],
        message.channel.id
    ):
        return False

    content = message.content
    lower = content.lower()

    # Palavras bloqueadas
    words = [
        x.strip().lower()
        for x in config["blocked_words"].split(",")
        if x.strip()
    ]

    for word in words:
        if word in lower:
            try:
                await message.delete()
            except discord.HTTPException:
                pass

            await send_log(
                message.guild,
                "AutoMod — palavra bloqueada",
                f"{message.author.mention} enviou uma palavra bloqueada "
                f"em {message.channel.mention}.",
                discord.Color.red()
            )

            return True

    # Links
    if config["automod_links"]:
        if re.search(r"https?://\S+|www\.\S+", lower):
            try:
                await message.delete()
            except discord.HTTPException:
                pass

            await send_log(
                message.guild,
                "AutoMod — link",
                f"{message.author.mention} enviou um link.",
                discord.Color.red()
            )

            return True

    # Convites Discord
    if config["automod_invites"]:
        if re.search(
            r"(discord\.gg/|discord\.com/invite/)",
            lower
        ):
            try:
                await message.delete()
            except discord.HTTPException:
                pass

            await send_log(
                message.guild,
                "AutoMod — convite",
                f"{message.author.mention} enviou um convite.",
                discord.Color.red()
            )

            return True

    # Muitas menções
    if config["automod_mentions"]:
        if len(message.mentions) >= 5:
            try:
                await message.delete()
            except discord.HTTPException:
                pass

            await send_log(
                message.guild,
                "AutoMod — menções",
                f"{message.author.mention} utilizou muitas menções.",
                discord.Color.red()
            )

            return True

    # Caps
    if config["automod_caps"] and len(content) >= 10:
        letters = [c for c in content if c.isalpha()]

        if letters:
            upper = sum(c.isupper() for c in letters)

            if upper / len(letters) >= 0.75:
                try:
                    await message.delete()
                except discord.HTTPException:
                    pass

                await send_log(
                    message.guild,
                    "AutoMod — CAPS",
                    f"{message.author.mention} utilizou excesso de CAPS.",
                    discord.Color.red()
                )

                return True

    # Repetição
    key = (message.guild.id, message.author.id)

    if config["automod_repeat"] and content:
        previous = repeat_cache.get(key)

        if previous == lower:
            try:
                await message.delete()
            except discord.HTTPException:
                pass

            await send_log(
                message.guild,
                "AutoMod — mensagem repetida",
                f"{message.author.mention} repetiu a mensagem.",
                discord.Color.red()
            )

            return True

        repeat_cache[key] = lower

    # Flood
    if config["automod_spam"]:
        current = now().timestamp()

        data = spam_cache.setdefault(key, [])

        data.append(current)

        data[:] = [
            x for x in data
            if current - x <= 5
        ]

        if len(data) >= 6:
            try:
                await message.delete()
            except discord.HTTPException:
                pass

            await send_log(
                message.guild,
                "AutoMod — spam",
                f"{message.author.mention} enviou mensagens em excesso.",
                discord.Color.red()
            )

            return True

    return False


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    blocked = await automod_message(message)

    if blocked:
        return

    await bot.process_commands(message)


# =========================================================
# HELP
# =========================================================

@bot.command(name="help")
async def help_command(ctx):
    embed = discord.Embed(
        title="Comandos",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="Moderação",
        value=(
            "`!ban @user motivo`\n"
            "`!kick @user motivo`\n"
            "`!warn @user motivo`\n"
            "`!warnings @user`\n"
            "`!mute @user 10m motivo`\n"
            "`!unmute @user`\n"
            "`!hackban ID motivo`"
        ),
        inline=False
    )

    embed.add_field(
        name="Servidor",
        value=(
            "`!serverinfo`\n"
            "`!userinfo @user`\n"
            "`!avatar @user`\n"
            "`!rolecreate nome`\n"
            "`!roledelete @role`\n"
            "`!setstaff @role`\n"
            "`!setlog #canal`"
        ),
        inline=False
    )

    embed.add_field(
        name="Canais",
        value=(
            "`!lock`\n"
            "`!unlock`\n"
            "`!private @user nome`\n"
            "`!channelcreate nome`\n"
            "`!channeldelete`"
        ),
        inline=False
    )

    embed.add_field(
        name="Tickets",
        value="`!ticketpanel`",
        inline=False
    )

    embed.add_field(
        name="AutoMod",
        value=(
            "`!automod`\n"
            "`!blockedadd palavra`\n"
            "`!blockedremove palavra`\n"
            "`!whitelist user @user`"
        ),
        inline=False
    )

    await ctx.send(embed=embed)


@bot.command()
async def ping(ctx):
    await ctx.send(
        f"Pong! `{round(bot.latency * 1000)}ms`"
    )


# =========================================================
# MODERAÇÃO
# =========================================================

@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="Não informado"):
    if member == ctx.author:
        return await ctx.send("Você não pode expulsar você mesmo.")

    try:
        await member.kick(reason=reason)
    except discord.HTTPException:
        return await ctx.send("Não consegui expulsar esse membro.")

    await ctx.send(
        f"{member.mention} foi expulso.\n"
        f"**Motivo:** {reason}"
    )

    await send_dm(
        member,
        "Você foi expulso",
        f"Você foi expulso do servidor **{ctx.guild.name}**.\n"
        f"**Motivo:** {reason}"
    )

    await send_log(
        ctx.guild,
        "Membro expulso",
        f"**Membro:** {member}\n"
        f"**Moderador:** {ctx.author.mention}\n"
        f"**Motivo:** {reason}",
        discord.Color.orange()
    )


@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="Não informado"):
    if member == ctx.author:
        return await ctx.send("Você não pode banir você mesmo.")

    config = get_config(ctx.guild.id)

    try:
        await member.ban(reason=reason)
    except discord.HTTPException:
        return await ctx.send("Não consegui banir esse membro.")

    if config["punishment_dm"]:
        moderator = (
            ctx.author.mention
            if config["show_moderator"]
            else "Equipe de moderação"
        )

        await send_dm(
            member,
            "Você foi banido",
            f"Você foi banido do servidor **{ctx.guild.name}**.\n\n"
            f"**Motivo:** {reason}\n"
            f"**Moderador:** {moderator}"
        )

    await ctx.send(
        f"{member.mention} foi banido.\n"
        f"**Motivo:** {reason}"
    )

    await send_log(
        ctx.guild,
        "Membro banido",
        f"**Membro:** {member}\n"
        f"**Moderador:** {ctx.author.mention}\n"
        f"**Motivo:** {reason}",
        discord.Color.red()
    )


@bot.command()
@commands.has_permissions(ban_members=True)
async def hackban(ctx, user_id: int, *, reason="Não informado"):
    try:
        await ctx.guild.ban(
            discord.Object(id=user_id),
            reason=reason
        )
    except discord.HTTPException:
        return await ctx.send("Não consegui realizar o hackban.")

    await ctx.send(
        f"Usuário `{user_id}` banido.\n"
        f"**Motivo:** {reason}"
    )

    await send_log(
        ctx.guild,
        "Hackban",
        f"**ID:** `{user_id}`\n"
        f"**Moderador:** {ctx.author.mention}\n"
        f"**Motivo:** {reason}",
        discord.Color.red()
    )


@bot.command()
@commands.has_permissions(ban_members=True)
async def unban(ctx, user_id: int):
    try:
        await ctx.guild.unban(discord.Object(id=user_id))
    except discord.HTTPException:
        return await ctx.send("Não consegui desbanir esse usuário.")

    await ctx.send(f"Usuário `{user_id}` desbanido.")

    await send_log(
        ctx.guild,
        "Usuário desbanido",
        f"**ID:** `{user_id}`\n"
        f"**Moderador:** {ctx.author.mention}",
        discord.Color.green()
    )


@bot.command()
@commands.has_permissions(moderate_members=True)
async def mute(
    ctx,
    member: discord.Member,
    duration: str,
    *,
    reason="Não informado"
):
    td = parse_duration(duration)

    if not td:
        return await ctx.send(
            "Duração inválida. Use exemplos como `10m`, `2h`, `1d`."
        )

    until = now() + td

    try:
        await member.timeout(
            until,
            reason=reason
        )
    except discord.HTTPException:
        return await ctx.send("Não consegui silenciar esse membro.")

    con = db()
    cur = con.cursor()

    cur.execute(
        """
        INSERT OR REPLACE INTO mutes
        (guild_id, user_id, expires_at)
        VALUES (?, ?, ?)
        """,
        (
            ctx.guild.id,
            member.id,
       until.isoformat()
        )
    )

    con.commit()
    con.close()

    config = get_config(ctx.guild.id)

    if config["punishment_dm"]:
        moderator = (
            ctx.author.mention
            if config["show_moderator"]
            else "Equipe de moderação"
        )

        await send_dm(
            member,
            "Você foi silenciado",
            f"Você foi silenciado no servidor **{ctx.guild.name}**.\n\n"
            f"**Duração:** {duration}\n"
            f"**Motivo:** {reason}\n"
            f"**Moderador:** {moderator}"
        )

    await ctx.send(
        f"{member.mention} foi silenciado por `{duration}`.\n"
        f"**Motivo:** {reason}"
    )

    await send_log(
        ctx.guild,
        "Membro silenciado",
        f"**Membro:** {member}\n"
        f"**Moderador:** {ctx.author.mention}\n"
        f"**Duração:** {duration}\n"
        f"**Motivo:** {reason}",
        discord.Color.orange()
    )


@bot.command()
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):
    try:
        await member.timeout(None)
    except discord.HTTPException:
        return await ctx.send("Não consegui remover o mute.")

    con = db()
    cur = con.cursor()

    cur.execute(
        "DELETE FROM mutes WHERE guild_id = ? AND user_id = ?",
        (ctx.guild.id, member.id)
    )

    con.commit()
    con.close()

    await ctx.send(f"{member.mention} não está mais mutado.")

    await send_log(
        ctx.guild,
        "Mute removido",
        f"**Membro:** {member}\n"
        f"**Moderador:** {ctx.author.mention}",
        discord.Color.green()
    )


@bot.command()
@commands.has_permissions(moderate_members=True)
async def warn(ctx, member: discord.Member, *, reason="Não informado"):
    con = db()
    cur = con.cursor()

    cur.execute(
        """
        INSERT INTO warns
        (guild_id, user_id, moderator_id, reason, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            ctx.guild.id,
            member.id,
            ctx.author.id,
            reason,
            now().isoformat()
        )
    )

    con.commit()
    con.close()

    config = get_config(ctx.guild.id)

    if config["punishment_dm"]:
        moderator = (
            ctx.author.mention
            if config["show_moderator"]
            else "Equipe de moderação"
        )

        await send_dm(
            member,
            "Você recebeu uma advertência",
            f"Você recebeu uma advertência no servidor "
            f"**{ctx.guild.name}**.\n\n"
            f"**Motivo:** {reason}\n"
            f"**Moderador:** {moderator}"
        )

    await ctx.send(
        f"{member.mention} recebeu uma advertência.\n"
        f"**Motivo:** {reason}"
    )

    await send_log(
        ctx.guild,
        "Advertência",
        f"**Membro:** {member}\n"
        f"**Moderador:** {ctx.author.mention}\n"
        f"**Motivo:** {reason}",
        discord.Color.yellow()
    )


@bot.command()
@commands.has_permissions(moderate_members=True)
async def warnings(ctx, member: discord.Member):
    con = db()
    cur = con.cursor()

    cur.execute(
        """
        SELECT id, moderator_id, reason, created_at
        FROM warns
        WHERE guild_id = ? AND user_id = ?
        ORDER BY id DESC
        """,
        (ctx.guild.id, member.id)
    )

    rows = cur.fetchall()
    con.close()

    if not rows:
        return await ctx.send(
            f"{member.mention} não possui advertências."
        )

    embed = discord.Embed(
        title=f"Advertências — {member}",
        color=discord.Color.yellow()
    )

    for warn_id, moderator_id, reason, created_at in rows[:20]:
        moderator = ctx.guild.get_member(moderator_id)

        embed.add_field(
            name=f"#{warn_id}",
            value=(
                f"**Motivo:** {reason}\n"
                f"**Moderador:** {moderator or moderator_id}\n"
                f"**Data:** {created_at[:19]}"
            ),
            inline=False
        )

    await ctx.send(embed=embed)


# =========================================================
# PRISON
# =========================================================

@bot.command()
@commands.has_permissions(manage_roles=True)
async def prison(
    ctx,
    member: discord.Member,
    duration: str,
    *,
    reason="Não informado"
):
    config = get_config(ctx.guild.id)

    role_id = config["prison_role"]

    if not role_id:
        return await ctx.send(
            "Configure o cargo de prisão primeiro com `!setprison @cargo`."
        )

    role = ctx.guild.get_role(role_id)

    if not role:
        return await ctx.send("O cargo de prisão não existe mais.")

    td = parse_duration(duration)

    if not td:
        return await ctx.send(
            "Duração inválida. Use `10m`, `1h`, `1d`, etc."
        )

    try:
        await member.add_roles(role, reason=reason)
    except discord.HTTPException:
        return await ctx.send("Não consegui colocar o cargo.")

    for channel in ctx.guild.channels:
        try:
            if isinstance(channel, discord.TextChannel):
                await channel.set_permissions(
                    member,
                    send_messages=False,
                    view_channel=True
                )

            elif isinstance(channel, discord.VoiceChannel):
                await channel.set_permissions(
                    member,
                    connect=False
                )

        except discord.HTTPException:
            pass

    await send_dm(
        member,
        "Você foi colocado na prisão",
        f"Você foi colocado na prisão do servidor "
        f"**{ctx.guild.name}**.\n\n"
        f"**Duração:** {duration}\n"
        f"**Motivo:** {reason}"
    )

    await ctx.send(
        f"{member.mention} foi colocado na prisão por `{duration}`."
    )

    await send_log(
        ctx.guild,
        "Prisão",
        f"**Membro:** {member}\n"
        f"**Moderador:** {ctx.author.mention}\n"
        f"**Duração:** {duration}\n"
        f"**Motivo:** {reason}",
        discord.Color.dark_red()
    )

    await asyncio.sleep(td.total_seconds())

    try:
        await member.remove_roles(role, reason="Tempo de prisão encerrado")

        for channel in ctx.guild.channels:
            try:
                await channel.set_permissions(
                    member,
                    overwrite=None
                )
            except discord.HTTPException:
                pass

    except (discord.HTTPException, discord.NotFound):
        pass


# =========================================================
# CONFIGURAÇÕES
# =========================================================

@bot.command()
@commands.has_permissions(manage_guild=True)
async def setlog(ctx, channel: discord.TextChannel):
    set_config(
        ctx.guild.id,
        "log_channel",
        channel.id
    )

    await ctx.send(
        f"Canal de logs definido para {channel.mention}."
    )


@bot.command()
@commands.has_permissions(manage_roles=True)
async def setstaff(ctx, role: discord.Role):
    set_config(
        ctx.guild.id,
        "staff_role",
        role.id
    )

    await ctx.send(
        f"Cargo de staff definido como {role.mention}."
    )


@bot.command()
@commands.has_permissions(manage_roles=True)
async def setprison(ctx, role: discord.Role):
    set_config(
        ctx.guild.id,
        "prison_role",
        role.id
    )

    await ctx.send(
        f"Cargo de prisão definido como {role.mention}."
    )


@bot.command()
@commands.has_permissions(manage_guild=True)
async def setpunishmentdm(ctx, option: str):
    option = option.lower()

    if option not in ("on", "off"):
        return await ctx.send("Use `on` ou `off`.")

    set_config(
        ctx.guild.id,
        "punishment_dm",
        1 if option == "on" else 0
    )

    await ctx.send(
        f"DM de punição: **{option}**."
    )


@bot.command()
@commands.has_permissions(manage_guild=True)
async def showmoderator(ctx, option: str):
    option = option.lower()

    if option not in ("on", "off"):
        return await ctx.send("Use `on` ou `off`.")

    set_config(
        ctx.guild.id,
        "show_moderator",
        1 if option == "on" else 0
    )

    await ctx.send(
        f"Nome do moderador nas DMs: **{option}**."
    )


# =========================================================
# AUTOMOD CONFIG
# =========================================================

@bot.command()
@commands.has_permissions(manage_guild=True)
async def blockedadd(ctx, *, word):
    config = get_config(ctx.guild.id)

    words = [
        x.strip()
        for x in config["blocked_words"].split(",")
        if x.strip()
    ]

    if word.lower() in [x.lower() for x in words]:
        return await ctx.send("Essa palavra já está bloqueada.")

    words.append(word)

    set_config(
        ctx.guild.id,
        "blocked_words",
        ",".join(words)
    )

    await ctx.send(
        f"Palavra `{word}` adicionada ao AutoMod."
    )


@bot.command()
@commands.has_permissions(manage_guild=True)
async def blockedremove(ctx, *, word):
    config = get_config(ctx.guild.id)

    words = [
        x.strip()
        for x in config["blocked_words"].split(",")
        if x.strip()
    ]

    words = [
        x for x in words
        if x.lower() != word.lower()
    ]

    set_config(
        ctx.guild.id,
        "blocked_words",
        ",".join(words)
    )

    await ctx.send(
        f"Palavra `{word}` removida."
    )


@bot.command()
@commands.has_permissions(manage_guild=True)
async def automod(ctx, option=None):
    config = get_config(ctx.guild.id)

    if option is None:
        embed = discord.Embed(
            title="AutoMod",
            color=discord.Color.blurple()
        )

        embed.add_field(
            name="Palavras",
            value="`!blockedadd palavra`",
            inline=False
        )

        embed.add_field(
            name="Ativar/desativar",
            value=(
                "`!automod links on/off`\n"
                "`!automod invites on/off`\n"
                "`!automod caps on/off`\n"
                "`!automod spam on/off`\n"
                "`!automod mentions on/off`\n"
                "`!automod repeat on/off`"
            ),
            inline=False
        )

        await ctx.send(embed=embed)
        return

    await ctx.send(
        "Use uma configuração específica, como "
        "`!automod links on`."
    )


@bot.command()
@commands.has_permissions(manage_guild=True)
async def automodconfig(ctx, feature: str, option: str):
    features = {
        "links": "automod_links",
        "invites": "automod_invites",
        "caps": "automod_caps",
        "spam": "automod_spam",
        "mentions": "automod_mentions",
        "repeat": "automod_repeat"
    }

    feature = feature.lower()
    option = option.lower()

    if feature not in features:
        return await ctx.send(
            "Opção inválida: links, invites, caps, spam, mentions ou repeat."
        )

    if option not in ("on", "off"):
        return await ctx.send("Use `on` ou `off`.")

    set_config(
        ctx.guild.id,
        features[feature],
        1 if option == "on" else 0
    )

    await ctx.send(
        f"AutoMod `{feature}`: **{option}**."
    )


# =========================================================
# WHITELIST
# =========================================================

@bot.command()
@commands.has_permissions(manage_guild=True)
async def whitelist(ctx, target_type: str, target):
    target_type = target_type.lower()

    if target_type == "user":
        if not isinstance(target, discord.Member):
            return await ctx.send("Usuário inválido.")

        target_id = target.id

    elif target_type == "role":
        if not isinstance(target, discord.Role):
            return await ctx.send("Cargo inválido.")

        target_id = target.id

    elif target_type == "channel":
        if not isinstance(target, discord.TextChannel):
            return await ctx.send("Canal inválido.")

        target_id = target.id

    else:
        return await ctx.send(
            "Tipo inválido. Use `user`, `role` ou `channel`."
        )

    con = db()
    cur = con.cursor()

    cur.execute(
        """
        INSERT OR IGNORE INTO whitelist
        (guild_id, target_id, target_type)
        VALUES (?, ?, ?)
        """,
        (ctx.guild.id, target_id, target_type)
    )

    con.commit()
    con.close()

    await ctx.send("Adicionado à whitelist.")


# =========================================================
# SERVER INFO
# =========================================================

@bot.command()
async def serverinfo(ctx):
    guild = ctx.guild

    embed = discord.Embed(
        title=guild.name,
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="Dono",
        value=str(guild.owner),
        inline=True
    )

    embed.add_field(
        name="Membros",
        value=str(guild.member_count),
        inline=True
    )

    embed.add_field(
        name="Canais",
        value=str(len(guild.channels)),
        inline=True
    )

    embed.add_field(
        name="Cargos",
        value=str(len(guild.roles)),
        inline=True
    )

    embed.add_field(
        name="ID",
        value=str(guild.id),
        inline=True
    )

    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    await ctx.send(embed=embed)


@bot.command()
async def userinfo(ctx, member: discord.Member = None):
    member = member or ctx.author

    embed = discord.Embed(
        title=f"Informações — {member}",
        color=member.color
    )

    embed.add_field(
        name="ID",
        value=str(member.id),
        inline=False
    )

    embed.add_field(
        name="Conta criada",
        value=member.created_at.strftime("%d/%m/%Y"),
        inline=True
    )

    if member.joined_at:
        embed.add_field(
            name="Entrou no servidor",
            value=member.joined_at.strftime("%d/%m/%Y"),
            inline=True
        )

    embed.add_field(
        name="Cargos",
        value=", ".join(
            role.mention
            for role in member.roles[1:]
        ) or "Nenhum",
        inline=False
    )

    embed.set_thumbnail(url=member.display_avatar.url)

    await ctx.send(embed=embed)


@bot.command()
async def avatar(ctx, member: discord.Member = None):
    member = member or ctx.author

    embed = discord.Embed(
        title=f"Avatar de {member}",
        color=discord.Color.blurple()
    )

    embed.set_image(url=member.display_avatar.url)

    await ctx.send(embed=embed)
# =========================================================
# ROLES
# =========================================================

@bot.command()
@commands.has_permissions(manage_roles=True)
async def rolecreate(ctx, *, name):
    try:
        role = await ctx.guild.create_role(
            name=name,
            reason=f"Criado por {ctx.author}"
        )
    except discord.HTTPException:
        return await ctx.send("Não consegui criar o cargo.")

    await ctx.send(
        f"Cargo criado: {role.mention}"
    )


@bot.command()
@commands.has_permissions(manage_roles=True)
async def roledelete(ctx, role: discord.Role):
    if role >= ctx.guild.me.top_role:
        return await ctx.send(
            "Não consigo excluir um cargo acima do meu cargo."
        )

    try:
        await role.delete(
            reason=f"Excluído por {ctx.author}"
        )
    except discord.HTTPException:
        return await ctx.send("Não consegui excluir o cargo.")

    await ctx.send("Cargo excluído.")


@bot.command()
@commands.has_permissions(manage_roles=True)
async def roleadd(ctx, member: discord.Member, role: discord.Role):
    try:
        await member.add_roles(role)
    except discord.HTTPException:
        return await ctx.send("Não consegui adicionar o cargo.")

    await ctx.send(
        f"{role.mention} adicionado a {member.mention}."
    )


@bot.command()
@commands.has_permissions(manage_roles=True)
async def roleremove(ctx, member: discord.Member, role: discord.Role):
    try:
        await member.remove_roles(role)
    except discord.HTTPException:
        return await ctx.send("Não consegui remover o cargo.")

    await ctx.send(
        f"{role.mention} removido de {member.mention}."
    )


# =========================================================
# CHANNELS
# =========================================================

@bot.command()
@commands.has_permissions(manage_channels=True)
async def channelcreate(ctx, *, name):
    try:
        channel = await ctx.guild.create_text_channel(name)
    except discord.HTTPException:
        return await ctx.send("Não consegui criar o canal.")

    await ctx.send(
        f"Canal criado: {channel.mention}"
    )


@bot.command()
@commands.has_permissions(manage_channels=True)
async def channeldelete(ctx):
    channel = ctx.channel

    try:
        await channel.delete(
            reason=f"Excluído por {ctx.author}"
        )
    except discord.HTTPException:
        pass


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

    await ctx.send("Canal bloqueado.")


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

    await ctx.send("Canal desbloqueado.")


@bot.command()
@commands.has_permissions(manage_channels=True)
async def private(
    ctx,
    member: discord.Member,
    *,
    name="privado"
):
    overwrites = {
        ctx.guild.default_role: discord.PermissionOverwrite(
            view_channel=False
        ),
        member: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True
        ),
        ctx.guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_channels=True
        )
    }

    try:
        channel = await ctx.guild.create_text_channel(
            name,
            overwrites=overwrites
        )
    except discord.HTTPException:
        return await ctx.send(
            "Não consegui criar o canal privado."
        )

    await ctx.send(
        f"Canal privado criado: {channel.mention}"
    )


# =========================================================
# TICKET SYSTEM
# =========================================================

class CloseTicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Fechar ticket",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="ticket_close"
    )
    async def close(
        self,
        interaction: discord.Interaction,
        button: Button
    ):
        channel = interaction.channel

        await interaction.response.send_message(
            "Ticket sendo fechado...",
            ephemeral=True
        )

        await asyncio.sleep(2)

        try:
            await channel.delete(
                reason=f"Ticket fechado por {interaction.user}"
            )
        except discord.HTTPException:
            pass


class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Abrir ticket",
        style=discord.ButtonStyle.primary,
        emoji="🎫",
        custom_id="ticket_open"
    )
    async def open_ticket(
        self,
        interaction: discord.Interaction,
        button: Button
    ):
        guild = interaction.guild

        if not guild:
            return

        config = get_config(guild.id)

        category = None

        if config["ticket_category"]:
            category = guild.get_channel(
                config["ticket_category"]
            )

        existing = discord.utils.get(
            guild.text_channels,
            name=f"ticket-{interaction.user.id}"
        )

        if existing:
            return await interaction.response.send_message(
                f"Você já possui um ticket: {existing.mention}",
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
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True
            )
        }

        staff_role_id = config["staff_role"]

        if staff_role_id:
            role = guild.get_role(staff_role_id)

            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True
                )

        try:
            channel = await guild.create_text_channel(
                f"ticket-{interaction.user.id}",
                category=category,
                overwrites=overwrites,
                reason="Ticket aberto"
            )
        except discord.HTTPException:
            return await interaction.response.send_message(
                "Não consegui criar o ticket.",
                ephemeral=True
            )

        embed = discord.Embed(
            title="Ticket",
            description=(
                f"Olá {interaction.user.mention}.\n"
                "Explique seu problema e aguarde a equipe."
            ),
            color=discord.Color.blurple()
        )

        await channel.send(
            embed=embed,
            view=CloseTicketView()
        )

        await interaction.response.send_message(
            f"Ticket criado: {channel.mention}",
            ephemeral=True
        )


@bot.command()
@commands.has_permissions(manage_channels=True)
async def ticketpanel(ctx):
    embed = discord.Embed(
        title="Atendimento",
        description=(
            "Precisa de ajuda?\n"
            "Clique no botão abaixo para abrir um ticket."
        ),
        color=discord.Color.blurple()
    )

    await ctx.send(
        embed=embed,
        view=TicketView()
    )


# =========================================================
# STAFF PANEL
# =========================================================

class StaffPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Servidor",
        style=discord.ButtonStyle.secondary,
        emoji="🏠",
        custom_id="staff_server"
    )
    async def server(
        self,
        interaction: discord.Interaction,
        button: Button
    ):
        guild = interaction.guild

        if not guild:
            return

        await interaction.response.send_message(
            f"**Servidor:** {guild.name}\n"
            f"**Membros:** {guild.member_count}\n"
            f"**Canais:** {len(guild.channels)}\n"
            f"**Cargos:** {len(guild.roles)}",
            ephemeral=True
        )

    @discord.ui.button(
        label="Avatar",
        style=discord.ButtonStyle.secondary,
        emoji="🖼️",
        custom_id="staff_avatar"
    )
    async def avatar(
        self,
        interaction: discord.Interaction,
        button: Button
    ):
        embed = discord.Embed(
            title=f"Avatar de {interaction.user}",
            color=discord.Color.blurple()
        )

        embed.set_image(
            url=interaction.user.display_avatar.url
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )


@bot.command()
@commands.has_permissions(manage_guild=True)
async def staffpanel(ctx):
    embed = discord.Embed(
        title="Painel da Staff",
        description="Ferramentas rápidas da equipe.",
        color=discord.Color.blurple()
    )

    await ctx.send(
        embed=embed,
        view=StaffPanelView()
    )


# =========================================================
# CLEAR
# =========================================================

@bot.command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int):
    if amount < 1:
        return await ctx.send("Quantidade inválida.")

    if amount > 100:
        return await ctx.send(
            "O máximo por vez é 100 mensagens."
        )

    try:
        deleted = await ctx.channel.purge(
            limit=amount + 1
        )
    except discord.HTTPException:
        return await ctx.send(
            "Não consegui apagar as mensagens."
        )

    msg = await ctx.send(
        f"{len(deleted) - 1} mensagens apagadas."
    )

    await asyncio.sleep(3)

    try:
        await msg.delete()
    except discord.HTTPException:
        pass


# =========================================================
# ERROR HANDLER
# =========================================================

@bot.event
async def on_error(event, *args, **kwargs):
    import traceback
    traceback.print_exc()


# =========================================================
# START
# =========================================================

if not TOKEN:
    raise RuntimeError(
        "A variável TOKEN não foi encontrada no Railway."
    )

init_db()
# =========================================================
# 🖥️ CONSOLE PYTHON — OWNER ONLY
# =========================================================

class ConsoleModal(Modal, title="Python Console"):
    codigo = TextInput(
        label="Código Python",
        placeholder="Digite o código que deseja executar...",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=4000
    )

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != interaction.guild.owner_id:
            return await interaction.response.send_message(
                "❌ Apenas o dono do servidor pode usar o Console.",
                ephemeral=True
            )

        codigo = self.codigo.value

        ambiente = {
            "bot": bot,
            "guild": interaction.guild,
            "user": interaction.user,
            "discord": discord,
            "asyncio": asyncio
        }

        try:
            resultado = await asyncio.to_thread(
                eval,
                compile(codigo, "<console>", "eval"),
                {"__builtins__": {}},
                ambiente
            )

            resultado = str(resultado)

        except SyntaxError:
            try:
                exec(
                    compile(codigo, "<console>", "exec"),
                    {"__builtins__": {}},
                    ambiente
                )
                resultado = "Código executado com sucesso."

            except Exception as e:
                resultado = f"{type(e).__name__}: {e}"

        except Exception as e:
            resultado = f"{type(e).__name__}: {e}"

        if len(resultado) > 1900:
            resultado = resultado[:1900] + "..."

        embed = discord.Embed(
            title="🖥️ Python Console",
            color=discord.Color.blurple()
        )

        embed.add_field(
            name="Código",
            value=f"```py\n{codigo[:900]}\n```",
            inline=False
        )

        embed.add_field(
            name="Resultado",
            value=f"```py\n{resultado}\n```",
            inline=False
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )


class ConsoleView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Python Console",
        emoji="🐍",
        style=discord.ButtonStyle.primary,
        custom_id="console_python"
    )
    async def console(
        self,
        interaction: discord.Interaction,
        button: Button
    ):
        if not interaction.guild:
            return

        if interaction.user.id != interaction.guild.owner_id:
            return await interaction.response.send_message(
                "❌ Apenas o dono do servidor pode usar o Console.",
                ephemeral=True
            )

        await interaction.response.send_modal(
            ConsoleModal()
        )


@bot.command()
@commands.is_owner()
async def console(ctx):
    embed = discord.Embed(
        title="🖥️ Python Console",
        description=(
            "Console administrativo do bot.\n\n"
            "🐍 Execute código Python diretamente pelo painel.\n"
            "🔒 Acesso exclusivo ao dono do bot."
        ),
        color=discord.Color.blurple()
    )

    embed.set_footer(
        text=f"Solicitado por {ctx.author}"
    )

    await ctx.send(
        embed=embed,
        view=ConsoleView()
    )


# =========================================================
# ✨ NOVOS COMANDOS
# =========================================================

@bot.command()
@commands.has_permissions(manage_messages=True)
async def slowmode(ctx, seconds: int):
    if seconds < 0 or seconds > 21600:
        return await ctx.send(
            "❌ O tempo deve estar entre `0` e `21600` segundos."
        )

    await ctx.channel.edit(
        slowmode_delay=seconds
    )

    if seconds == 0:
        await ctx.send("✅ Slowmode desativado.")
    else:
        await ctx.send(
            f"✅ Slowmode definido para `{seconds}s`."
        )


@bot.command()
@commands.has_permissions(manage_nicknames=True)
async def nick(ctx, member: discord.Member, *, nickname):
    try:
        await member.edit(nick=nickname)
    except discord.HTTPException:
        return await ctx.send(
            "❌ Não consegui alterar o apelido."
        )

    await ctx.send(
        f"✅ Apelido de {member.mention} alterado para **{nickname}**."
    )


@bot.command()
@commands.has_permissions(ban_members=True)
async def softban(
    ctx,
    member: discord.Member,
    *,
    reason="Não informado"
):
    try:
        await member.ban(
            reason=f"Softban: {reason}",
            delete_message_days=1
        )

        await ctx.guild.unban(
            discord.Object(id=member.id),
            reason="Softban"
        )

    except discord.HTTPException:
        return await ctx.send(
            "❌ Não consegui realizar o softban."
        )

    await ctx.send(
        f"✅ {member.mention} recebeu softban.\n"
        f"**Motivo:** {reason}"
    )

    await send_log(
        ctx.guild,
        "Softban",
        f"**Usuário:** {member}\n"
        f"**Moderador:** {ctx.author.mention}\n"
        f"**Motivo:** {reason}",
        discord.Color.orange()
    )


@bot.command()
@commands.has_permissions(manage_roles=True)
async def temprole(
    ctx,
    member: discord.Member,
    role: discord.Role,
    duration: str
):
    td = parse_duration(duration)

    if not td:
        return await ctx.send(
            "❌ Duração inválida. Exemplo: `30m`, `2h`, `1d`."
        )

    try:
        await member.add_roles(role)
    except discord.HTTPException:
        return await ctx.send(
            "❌ Não consegui adicionar o cargo."
        )

    await ctx.send(
        f"✅ {role.mention} dado para {member.mention} "
        f"por `{duration}`."
    )

    await asyncio.sleep(td.total_seconds())

    try:
        await member.remove_roles(
            role,
            reason="Tempo do cargo encerrado"
        )
    except discord.HTTPException:
        pass


@bot.command()
async def botinfo(ctx):
    embed = discord.Embed(
        title="🤖 Informações do Bot",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="Nome",
        value=str(bot.user),
        inline=True
    )

    embed.add_field(
        name="Servidores",
        value=str(len(bot.guilds)),
        inline=True
    )

    embed.add_field(
        name="Latência",
        value=f"{round(bot.latency * 1000)}ms",
        inline=True
    )

    embed.add_field(
        name="Prefixo",
        value=f"`{PREFIX}`",
        inline=True
    )

    embed.add_field(
        name="Python",
        value="Python",
        inline=True
    )

    embed.add_field(
        name="Discord.py",
        value=discord.__version__,
        inline=True
    )

    await ctx.send(embed=embed)


@bot.command()
@commands.has_permissions(manage_channels=True)
async def renamechannel(ctx, *, name):
    try:
        await ctx.channel.edit(name=name)
    except discord.HTTPException:
        return await ctx.send(
            "❌ Não consegui renomear o canal."
        )

    await ctx.send(
        f"✅ Canal renomeado para `{name}`."
    )


@bot.command()
@commands.has_permissions(manage_channels=True)
async def categorycreate(ctx, *, name):
    try:
        category = await ctx.guild.create_category(name)
    except discord.HTTPException:
        return await ctx.send(
            "❌ Não consegui criar a categoria."
        )

    await ctx.send(
        f"✅ Categoria criada: **{category.name}**."
    )


@bot.command()
@commands.has_permissions(manage_channels=True)
async def channelinfo(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel

    embed = discord.Embed(
        title="📁 Informações do Canal",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="Nome",
        value=channel.name,
        inline=True
    )

    embed.add_field(
        name="ID",
        value=str(channel.id),
        inline=True
    )

    embed.add_field(
        name="Categoria",
        value=channel.category.name if channel.category else "Nenhuma",
        inline=True
    )

    embed.add_field(
        name="Criado em",
        value=channel.created_at.strftime("%d/%m/%Y"),
        inline=True
    )

    await ctx.send(embed=embed)


@bot.command()
async def roleinfo(ctx, role: discord.Role):
    embed = discord.Embed(
        title="🏷️ Informações do Cargo",
        color=role.color
    )

    embed.add_field(
        name="Nome",
        value=role.name,
        inline=True
    )

    embed.add_field(
        name="ID",
        value=str(role.id),
        inline=True
    )

    embed.add_field(
        name="Membros",
        value=str(len(role.members)),
        inline=True
    )

    embed.add_field(
        name="Posição",
        value=str(role.position),
        inline=True
    )

    embed.add_field(
        name="Menção",
        value=role.mention,
        inline=True
    )

    await ctx.send(embed=embed)


@bot.command()
@commands.has_permissions(manage_nicknames=True)
async def resetnick(ctx, member: discord.Member):
    try:
        await member.edit(nick=None)
    except discord.HTTPException:
        return await ctx.send(
            "❌ Não consegui resetar o apelido."
        )

    await ctx.send(
        f"✅ Apelido de {member.mention} resetado."
        )
bot.run(TOKEN)
