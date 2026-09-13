import os
import re
import sqlite3
import random
import ast
import operator
import asyncio
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput

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

# ============================================================
# DATABASE
# ============================================================

def db():
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db()
    cur = con.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS guild_config (
        guild_id INTEGER PRIMARY KEY,
        log_channel INTEGER,
        punishment_log INTEGER,
        welcome_channel INTEGER,
        leave_channel INTEGER,
        auto_role INTEGER,
        staff_role INTEGER,
        ticket_category INTEGER,
        ticket_panel_title TEXT DEFAULT 'Central de Atendimento',
        ticket_panel_description TEXT DEFAULT 'Clique no botão abaixo para abrir um atendimento.',
        ticket_panel_color INTEGER DEFAULT 5793266,
        ticket_support_role INTEGER,
        automod INTEGER DEFAULT 0,
        anti_link INTEGER DEFAULT 0,
        anti_invite INTEGER DEFAULT 0,
        anti_spam INTEGER DEFAULT 0,
        anti_flood INTEGER DEFAULT 0,
        anti_mention INTEGER DEFAULT 0,
        anti_caps INTEGER DEFAULT 0,
        repeat_messages INTEGER DEFAULT 0,
        automod_action TEXT DEFAULT 'delete',
        show_moderator INTEGER DEFAULT 1,
        warn_limit INTEGER DEFAULT 4
    );

    CREATE TABLE IF NOT EXISTS punishments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        moderator_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        reason TEXT NOT NULL,
        duration TEXT,
        created_at TEXT NOT NULL,
        active INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS badwords (
        guild_id INTEGER NOT NULL,
        word TEXT NOT NULL,
        UNIQUE(guild_id, word)
    );

    CREATE TABLE IF NOT EXISTS whitelist (
        guild_id INTEGER NOT NULL,
        target_id INTEGER NOT NULL,
        target_type TEXT NOT NULL,
        UNIQUE(guild_id, target_id, target_type)
    );

    CREATE TABLE IF NOT EXISTS tickets (
        channel_id INTEGER PRIMARY KEY,
        guild_id INTEGER NOT NULL,
        opener_id INTEGER NOT NULL,
        opened_at TEXT NOT NULL,
        closed_at TEXT,
        closed_by INTEGER
    );

    CREATE TABLE IF NOT EXISTS staff (
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        added_by INTEGER NOT NULL,
        added_at TEXT NOT NULL,
        UNIQUE(guild_id, user_id)
    );

    CREATE TABLE IF NOT EXISTS deleted_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER,
        channel_id INTEGER,
        user_id INTEGER,
        content TEXT,
        attachments TEXT,
        created_at TEXT
    );
    """)

    con.commit()
    con.close()


def ensure_guild(guild_id):
    con = db()
    con.execute(
        "INSERT OR IGNORE INTO guild_config (guild_id) VALUES (?)",
        (guild_id,)
    )
    con.commit()
    con.close()


def cfg(guild_id, key, default=None):
    ensure_guild(guild_id)

    con = db()
    row = con.execute(
        f"SELECT {key} FROM guild_config WHERE guild_id=?",
        (guild_id,)
    ).fetchone()

    con.close()

    if row and row[0] is not None:
        return row[0]

    return default


def set_cfg(guild_id, key, value):
    ensure_guild(guild_id)

    con = db()
    con.execute(
        f"UPDATE guild_config SET {key}=? WHERE guild_id=?",
        (value, guild_id)
    )
    con.commit()
    con.close()


# ============================================================
# HELPERS
# ============================================================

def now():
    return datetime.now(timezone.utc)


def stamp(dt=None):
    return (dt or now()).strftime("%d/%m/%Y %H:%M UTC")


def bot_color():
    return discord.Color.blurple()


def clean_reason(reason):
    if not reason:
        return "Nenhum motivo informado."

    return reason.strip()[:500]


def human_duration(seconds):
    seconds = int(seconds)
    parts = []

    for amount, name in (
        (86400, "dia"),
        (3600, "hora"),
        (60, "minuto")
    ):
        n, seconds = divmod(seconds, amount)

        if n:
            parts.append(
                f"{n} {name}{'s' if n != 1 else ''}"
            )

    if seconds:
        parts.append(
            f"{seconds} segundo{'s' if seconds != 1 else ''}"
        )

    return ", ".join(parts) or "0 segundos"


def parse_duration(text):
    if not text:
        return None

    match = re.fullmatch(
        r"\s*(\d+)\s*([smhd])\s*",
        text.lower()
    )

    if not match:
        return None

    number = int(match.group(1))
    unit = match.group(2)

    return number * {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400
    }[unit]


def get_channel(guild, channel_id):
    if not channel_id:
        return None

    return guild.get_channel(int(channel_id))


def member_is_staff(member):
    if member.guild_permissions.administrator:
        return True

    if member.guild_permissions.manage_guild:
        return True

    staff_role_id = cfg(
        member.guild.id,
        "staff_role"
    )

    if staff_role_id:
        if any(
            role.id == staff_role_id
            for role in member.roles
        ):
            return True

    con = db()

    row = con.execute(
        """
        SELECT 1
        FROM staff
        WHERE guild_id=? AND user_id=?
        """,
        (member.guild.id, member.id)
    ).fetchone()

    con.close()

    return bool(row)


def hierarchy_ok(actor, target):
    if actor.guild_permissions.administrator:
        return True

    if actor == target:
        return False

    return actor.top_role > target.top_role


def punishment_count(guild_id, user_id, punishment_type=None):
    con = db()

    if punishment_type:
        row = con.execute(
            """
            SELECT COUNT(*) AS total
            FROM punishments
            WHERE guild_id=? AND user_id=? AND type=?
            """,
            (guild_id, user_id, punishment_type)
        ).fetchone()
    else:
        row = con.execute(
            """
            SELECT COUNT(*) AS total
            FROM punishments
            WHERE guild_id=? AND user_id=?
            """,
            (guild_id, user_id)
        ).fetchone()

    con.close()

    return row["total"]


def save_punishment(
    guild_id,
    user_id,
    moderator_id,
    punishment_type,
    reason,
    duration=None
):
    con = db()

    cur = con.cursor()

    cur.execute(
        """
        INSERT INTO punishments
        (
            guild_id,
            user_id,
            moderator_id,
            type,
            reason,
            duration,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            guild_id,
            user_id,
            moderator_id,
            punishment_type,
            reason,
            duration,
            now().isoformat()
        )
    )

    punishment_id = cur.lastrowid

    con.commit()
    con.close()

    return punishment_id


def get_punishment(punishment_id, guild_id):
    con = db()

    row = con.execute(
        """
        SELECT *
        FROM punishments
        WHERE id=? AND guild_id=?
        """,
        (punishment_id, guild_id)
    ).fetchone()

    con.close()

    return row


async def safe_dm(user, embed):
    try:
        await user.send(embed=embed)
        return True

    except (
        discord.Forbidden,
        discord.HTTPException
    ):
        return False


# ============================================================
# PROFESSIONAL PUNISHMENT EMBEDS
# ============================================================

PUNISHMENT_NAMES = {
    "WARN": "Advertência",
    "MUTE": "Silenciamento",
    "KICK": "Expulsão",
    "BAN": "Banimento",
    "HACKBAN": "Banimento por ID",
    "UNBAN": "Remoção de banimento"
}


def punishment_embed(
    guild,
    user,
    punishment_type,
    reason,
    moderator,
    punishment_id,
    duration=None
):
    name = PUNISHMENT_NAMES.get(
        punishment_type,
        punishment_type
    )

    embed = discord.Embed(
        title=f"⚖️ {name} aplicada",
        color=discord.Color.orange(),
        timestamp=now()
    )

    embed.description = (
        f"Olá, **{user.display_name}**.\n\n"
        f"Uma ação de moderação foi aplicada à "
        f"sua conta no servidor **{guild.name}**."
    )

    embed.add_field(
        name="📌 Medida aplicada",
        value=f"**{name}**",
        inline=True
    )

    embed.add_field(
        name="🆔 ID da ação",
        value=f"`#{punishment_id}`",
        inline=True
    )

    embed.add_field(
        name="📅 Data",
        value=stamp(),
        inline=True
    )

    embed.add_field(
        name="📝 Motivo",
        value=reason,
        inline=False
    )

    if duration:
        embed.add_field(
            name="⏱️ Duração",
            value=duration,
            inline=True
        )

    if cfg(guild.id, "show_moderator", 1):
        embed.add_field(
            name="👮 Responsável",
            value=(
                f"{moderator}\n"
                f"`{moderator.id}`"
            ),
            inline=True
        )

    embed.add_field(
        name="ℹ️ Informações",
        value=(
            "Se você acredita que essa ação foi aplicada "
            "por engano, entre em contato com a equipe "
            "de moderação do servidor."
        ),
        inline=False
    )

    embed.set_footer(
        text=f"{guild.name} • Sistema de Moderação"
    )

    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    return embed


async def send_punishment_log(guild, embed):
    channel_id = cfg(
        guild.id,
        "punishment_log"
    )

    channel = get_channel(
        guild,
        channel_id
    )

    if channel:
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass


async def send_normal_log(guild, embed):
    channel_id = cfg(
        guild.id,
        "log_channel"
    )

    channel = get_channel(
        guild,
        channel_id
    )

    if channel:
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass


# ============================================================
# EVENTS
# ============================================================

@bot.event
async def on_ready():
    init_db()

    bot.add_view(TicketView())
    bot.add_view(CloseTicketView())
    bot.add_view(StaffPanelView())
    bot.add_view(ConsoleView())

    print(
        f"Bot online: {bot.user} | "
        f"ID: {bot.user.id}"
    )


@bot.event
async def on_member_join(member):
    auto_role_id = cfg(
        member.guild.id,
        "auto_role"
    )

    if auto_role_id:
        role = member.guild.get_role(
            auto_role_id
        )

        if role:
            try:
                await member.add_roles(
                    role,
                    reason="Cargo automático"
                )
            except discord.HTTPException:
                pass

    welcome_channel = get_channel(
        member.guild,
        cfg(
            member.guild.id,
            "welcome_channel"
        )
    )

    if welcome_channel:
        embed = discord.Embed(
            title="👋 Novo membro",
            description=(
                f"Bem-vindo(a), {member.mention}!\n\n"
                "Esperamos que aproveite o servidor."
            ),
            color=discord.Color.green(),
            timestamp=now()
        )

        embed.set_thumbnail(
            url=member.display_avatar.url
        )

        await welcome_channel.send(
            embed=embed
        )

    await send_normal_log(
        member.guild,
        discord.Embed(
            title="📥 Membro entrou",
            description=(
                f"Usuário: {member.mention}\n"
                f"ID: `{member.id}`"
            ),
            color=discord.Color.green(),
            timestamp=now()
        )
    )


@bot.event
async def on_member_remove(member):
    leave_channel = get_channel(
        member.guild,
        cfg(
            member.guild.id,
            "leave_channel"
        )
    )

    if leave_channel:
        embed = discord.Embed(
            title="📤 Membro saiu",
            description=(
                f"**{member}** deixou o servidor."
            ),
            color=discord.Color.red(),
            timestamp=now()
        )

        await leave_channel.send(
            embed=embed
        )

    await send_normal_log(
        member.guild,
        discord.Embed(
            title="📤 Membro saiu",
            description=(
                f"Usuário: **{member}**\n"
                f"ID: `{member.id}`"
            ),
            color=discord.Color.red(),
            timestamp=now()
        )
    )


@bot.event
async def on_message_delete(message):
    if not message.guild:
        return

    if message.author.bot:
        return

    attachments = "\n".join(
        attachment.url
        for attachment in message.attachments
    )

    if not attachments:
        attachments = "Nenhum anexo."

    con = db()

    con.execute(
        """
        INSERT INTO deleted_messages
        (
            guild_id,
            channel_id,
            user_id,
            content,
            attachments,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            message.guild.id,
            message.channel.id,
            message.author.id,
            message.content[:4000],
            attachments,
            now().isoformat()
        )
    )

    con.commit()
    con.close()

    embed = discord.Embed(
        title="🗑️ Mensagem apagada",
        color=discord.Color.red(),
        timestamp=now()
    )

    embed.add_field(
        name="👤 Autor",
        value=(
            f"{message.author.mention}\n"
            f"`{message.author.id}`"
        ),
        inline=False
    )

    embed.add_field(
        name="📍 Canal",
        value=message.channel.mention,
        inline=True
    )

    embed.add_field(
        name="💬 Conteúdo",
        value=(
            message.content[:1000]
            if message.content
            else "*Sem texto*"
        ),
        inline=False
    )

    embed.add_field(
        name="🖼️ Anexos",
        value=attachments[:1000],
        inline=False
    )

    await send_normal_log(
        message.guild,
        embed
    )


@bot.event
async def on_message_edit(before, after):
    if not before.guild:
        return

    if before.author.bot:
        return

    if before.content == after.content:
        return

    embed = discord.Embed(
        title="✏️ Mensagem editada",
        color=discord.Color.gold(),
        timestamp=now()
    )

    embed.add_field(
        name="👤 Autor",
        value=(
            f"{before.author.mention}\n"
            f"`{before.author.id}`"
        ),
        inline=False
    )

    embed.add_field(
        name="📍 Canal",
        value=before.channel.mention
    )

    embed.add_field(
        name="Antes",
        value=before.content[:1000] or "*Vazio*",
        inline=False
    )

    embed.add_field(
        name="Depois",
        value=after.content[:1000] or "*Vazio*",
        inline=False
    )

    await send_normal_log(
        before.guild,
        embed
    )


# ============================================================
# AUTOMOD
# ============================================================

def is_whitelisted(message):
    con = db()

    rows = con.execute(
        """
        SELECT target_id, target_type
        FROM whitelist
        WHERE guild_id=?
        """,
        (message.guild.id,)
    ).fetchall()

    con.close()

    for row in rows:

        if (
            row["target_type"] == "user"
            and row["target_id"] == message.author.id
        ):
            return True

        if (
            row["target_type"] == "role"
            and any(
                role.id == row["target_id"]
                for role in message.author.roles
            )
        ):
            return True

        if (
            row["target_type"] == "channel"
            and row["target_id"] == message.channel.id
        ):
            return True

    return False


async def automod_message(message):
    if not message.guild:
        return False

    if message.author.bot:
        return False

    if not cfg(
        message.guild.id,
        "automod",
        0
    ):
        return False

    if is_whitelisted(message):
        return False

    content = message.content
    violations = []

    if (
        cfg(message.guild.id, "anti_link", 0)
        and re.search(
            r"https?://\S+",
            content,
            re.I
        )
    ):
        violations.append("link")

    if (
        cfg(message.guild.id, "anti_invite", 0)
        and re.search(
            r"discord(?:\.gg|\.com/invite)/\S+",
            content,
            re.I
        )
    ):
        violations.append("convite do Discord")

    if (
        cfg(message.guild.id, "anti_mention", 0)
        and len(message.mentions) >= 5
    ):
        violations.append("menções excessivas")

    letters = sum(
        character.isalpha()
        for character in content
    )

    uppercase = sum(
        character.isupper()
        for character in content
    )

    if (
        cfg(message.guild.id, "anti_caps", 0)
        and letters >= 12
        and uppercase / max(1, letters) >= 0.75
    ):
        violations.append("caps lock")

    con = db()

    words = [
        row["word"]
        for row in con.execute(
            """
            SELECT word
            FROM badwords
            WHERE guild_id=?
            """,
            (message.guild.id,)
        ).fetchall()
    ]

    con.close()

    for word in words:
        if re.search(
            r"(?<!\w)"
            + re.escape(word)
            + r"(?!\w)",
            content,
            re.I
        ):
            violations.append(
                "palavra bloqueada"
            )
            break

    if not violations:
        return False

    action = cfg(
        message.guild.id,
        "automod_action",
        "delete"
    )

    try:
        await message.delete()
    except discord.HTTPException:
        pass

    if action == "warn":
        reason = (
            "AutoMod: "
            + ", ".join(violations)
        )

        punishment_id = save_punishment(
            message.guild.id,
            message.author.id,
            bot.user.id,
            "WARN",
            reason
        )

        dm = punishment_embed(
            message.guild,
            message.author,
            "WARN",
            reason,
            bot.user,
            punishment_id
        )

        await safe_dm(
            message.author,
            dm
        )

        await send_punishment_log(
            message.guild,
            dm
        )

    elif action == "mute":
        try:
            await message.author.timeout(
                timedelta(minutes=5),
                reason="AutoMod"
            )
        except discord.HTTPException:
            pass

    embed = discord.Embed(
        title="🤖 AutoMod acionado",
        description=(
            f"**Usuário:** {message.author.mention}\n"
            f"**Motivo:** {' • '.join(violations)}"
        ),
        color=discord.Color.orange()
    )
    embed.set_footer(text=f"ID do usuário: {message.author.id}")

    await send_normal_log(message.guild, embed)


# =========================================================
# EVENTO: MEMBRO ENTROU
# =========================================================

@bot.event
async def on_member_join(member):
    config = get_config(member.guild.id)

    channel_id = config.get("welcome_channel")
    if channel_id:
        channel = member.guild.get_channel(channel_id)

        if channel:
            embed = discord.Embed(
                title="👋 Novo membro",
                description=(
                    f"Bem-vindo(a) {member.mention} ao servidor!\n\n"
                    f"Agora somos **{member.guild.member_count} membros**."
                ),
                color=discord.Color.green()
            )

            await channel.send(embed=embed)

    role_id = config.get("autorole")

    if role_id:
        role = member.guild.get_role(role_id)

        if role:
            try:
                await member.add_roles(role, reason="Autorole")
            except discord.HTTPException:
                pass

    embed = discord.Embed(
        title="📥 Membro entrou",
        description=f"{member.mention} entrou no servidor.",
        color=discord.Color.green()
    )

    embed.add_field(
        name="Usuário",
        value=f"{member} (`{member.id}`)",
        inline=False
    )

    await send_normal_log(member.guild, embed)


# =========================================================
# EVENTO: MEMBRO SAIU
# =========================================================

@bot.event
async def on_member_remove(member):
    embed = discord.Embed(
        title="📤 Membro saiu",
        description=f"**{member}** saiu do servidor.",
        color=discord.Color.red()
    )

    embed.add_field(
        name="ID",
        value=str(member.id)
    )

    await send_normal_log(member.guild, embed)


# =========================================================
# EVENTO: MENSAGEM DELETADA
# =========================================================

@bot.event
async def on_message_delete(message):
    if not message.guild:
        return

    if message.author.bot:
        return

    content = message.content or "*Sem texto*"

    save_deleted_message(
        message.guild.id,
        message.channel.id,
        message.author.id,
        content
    )

    embed = discord.Embed(
        title="🗑️ Mensagem deletada",
        color=discord.Color.red()
    )

    embed.add_field(
        name="Autor",
        value=f"{message.author.mention} (`{message.author.id}`)",
        inline=False
    )

    embed.add_field(
        name="Canal",
        value=message.channel.mention,
        inline=True
    )

    embed.add_field(
        name="Conteúdo",
        value=content[:1024],
        inline=False
    )

    if message.attachments:
        arquivos = "\n".join(
            attachment.url
            for attachment in message.attachments
        )

        embed.add_field(
            name="Anexos",
            value=arquivos[:1024],
            inline=False
        )

    await send_normal_log(message.guild, embed)


# =========================================================
# EVENTO: MENSAGEM EDITADA
# =========================================================

@bot.event
async def on_message_edit(before, after):
    if not before.guild:
        return

    if before.author.bot:
        return

    if before.content == after.content:
        return

    embed = discord.Embed(
        title="✏️ Mensagem editada",
        color=discord.Color.yellow()
    )

    embed.add_field(
        name="Autor",
        value=f"{before.author.mention} (`{before.author.id}`)",
        inline=False
    )

    embed.add_field(
        name="Canal",
        value=before.channel.mention,
        inline=True
    )

    embed.add_field(
        name="Antes",
        value=(before.content or "*Sem texto*")[:1024],
        inline=False
    )

    embed.add_field(
        name="Depois",
        value=(after.content or "*Sem texto*")[:1024],
        inline=False
    )

    await send_normal_log(before.guild, embed)


# =========================================================
# COMANDO: WARN
# =========================================================

@bot.command()
@commands.has_permissions(manage_messages=True)
async def warn(ctx, member: discord.Member, *, reason="Não informado"):
    if member == ctx.author:
        return await ctx.send("❌ Você não pode se punir.")

    if member.bot:
        return await ctx.send("❌ Não é possível punir bots.")

    if member.top_role >= ctx.author.top_role:
        return await ctx.send(
            "❌ Você não pode punir alguém com cargo igual ou superior ao seu."
        )

    punishment_id = save_punishment(
        ctx.guild.id,
        member.id,
        ctx.author.id,
        "WARN",
        reason,
        None
    )

    embed = punishment_embed(
        ctx.guild,
        member,
        "WARN",
        reason,
        ctx.author,
        punishment_id
    )

    await safe_dm(member, embed)
    await send_punishment_log(ctx.guild, embed)

    await ctx.send(
        f"⚠️ {member.mention} recebeu uma advertência.\n"
        f"ID da punição: `{punishment_id}`"
    )

    # Limite automático de warns
    config = get_config(ctx.guild.id)
    limit = config.get("warn_limit", 0)

    if limit and limit > 0:
        count = get_active_warns(
            ctx.guild.id,
            member.id
        )

        if count >= limit:
            try:
                await member.ban(
                    reason=f"Limite de advertências atingido ({count}/{limit})"
                )

                ban_id = save_punishment(
                    ctx.guild.id,
                    member.id,
                    ctx.author.id,
                    "BAN",
                    f"Limite de advertências atingido ({count}/{limit})",
                    None
                )

                ban_embed = punishment_embed(
                    ctx.guild,
                    member,
                    "BAN",
                    f"Limite de advertências atingido ({count}/{limit})",
                    ctx.author,
                    ban_id
                )

                await safe_dm(member, ban_embed)
                await send_punishment_log(ctx.guild, ban_embed)

            except discord.HTTPException:
                pass


# =========================================================
# COMANDO: WARNS
# =========================================================

@bot.command()
async def warns(ctx, member: discord.Member = None):
    member = member or ctx.author

    rows = get_warns(
        ctx.guild.id,
        member.id
    )

    embed = discord.Embed(
        title=f"⚠️ Advertências — {member}",
        color=discord.Color.orange()
    )

    if not rows:
        embed.description = "Nenhuma advertência encontrada."
        return await ctx.send(embed=embed)

    texto = ""

    for row in rows[:15]:
        texto += (
            f"**#{row['id']}** — "
            f"{row['reason']}\n"
            f"Moderador: <@{row['moderator_id']}>\n\n"
        )

    embed.description = texto[:4000]

    await ctx.send(embed=embed)


# =========================================================
# COMANDO: UNWARN
# =========================================================

@bot.command()
@commands.has_permissions(manage_messages=True)
async def unwarn(ctx, punishment_id: int):
    row = get_punishment(punishment_id)

    if not row:
        return await ctx.send("❌ Punição não encontrada.")

    if row["guild_id"] != ctx.guild.id:
        return await ctx.send("❌ Essa punição não pertence a este servidor.")

    if row["type"] != "WARN":
        return await ctx.send("❌ Esse ID não corresponde a um warn.")

    if not row["active"]:
        return await ctx.send("❌ Esse warn já foi removido.")

    deactivate_punishment(punishment_id)

    embed = discord.Embed(
        title="✅ Advertência removida",
        description=(
            f"A advertência `{punishment_id}` foi removida por "
            f"{ctx.author.mention}."
        ),
        color=discord.Color.green()
    )

    await ctx.send(embed=embed)


# =========================================================
# COMANDO: MUTE
# =========================================================

@bot.command()
@commands.has_permissions(moderate_members=True)
async def mute(
    ctx,
    member: discord.Member,
    duration: int,
    *,
    reason="Não informado"
):
    if member == ctx.author:
        return await ctx.send("❌ Você não pode se mutar.")

    if member.top_role >= ctx.author.top_role:
        return await ctx.send(
            "❌ Você não pode mutar alguém com cargo igual ou superior ao seu."
        )

    if duration <= 0:
        return await ctx.send("❌ A duração deve ser maior que zero.")

    if duration > 40320:
        return await ctx.send(
            "❌ A duração máxima permitida é de 28 dias."
        )

    try:
        await member.timeout(
            timedelta(minutes=duration),
            reason=reason
        )
    except discord.HTTPException:
        return await ctx.send(
            "❌ Não consegui aplicar o timeout nesse usuário."
        )

    punishment_id = save_punishment(
        ctx.guild.id,
        member.id,
        ctx.author.id,
        "MUTE",
        reason,
        duration
    )

    embed = punishment_embed(
        ctx.guild,
        member,
        "MUTE",
        reason,
        ctx.author,
        punishment_id,
        duration
    )

    await safe_dm(member, embed)
    await send_punishment_log(ctx.guild, embed)

    await ctx.send(
        f"🔇 {member.mention} foi silenciado por **{duration} minutos**.\n"
        f"ID da punição: `{punishment_id}`"
    )


# =========================================================
# COMANDO: UNMUTE
# =========================================================

@bot.command()
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):
    try:
        await member.timeout(None, reason=f"Unmute por {ctx.author}")
    except discord.HTTPException:
        return await ctx.send(
            "❌ Não consegui remover o timeout."
        )

    await ctx.send(
        f"🔊 O silêncio de {member.mention} foi removido."
    )


# =========================================================
# COMANDO: KICK
# =========================================================

@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="Não informado"):
    if member.top_role >= ctx.author.top_role:
        return await ctx.send(
            "❌ Você não pode expulsar alguém com cargo igual ou superior ao seu."
        )

    punishment_id = save_punishment(
        ctx.guild.id,
        member.id,
        ctx.author.id,
        "KICK",
        reason,
        None
    )

    embed = punishment_embed(
        ctx.guild,
        member,
        "KICK",
        reason,
        ctx.author,
        punishment_id
    )

    await safe_dm(member, embed)

    try:
        await member.kick(reason=reason)
    except discord.HTTPException:
        return await ctx.send(
            "❌ Não consegui expulsar esse usuário."
        )

    await send_punishment_log(ctx.guild, embed)

    await ctx.send(
        f"👢 {member} foi expulso.\n"
        f"ID da punição: `{punishment_id}`"
    )


# =========================================================
# COMANDO: BAN
# =========================================================

@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="Não informado"):
    if member.top_role >= ctx.author.top_role:
        return await ctx.send(
            "❌ Você não pode banir alguém com cargo igual ou superior ao seu."
        )

    punishment_id = save_punishment(
        ctx.guild.id,
        member.id,
        ctx.author.id,
        "BAN",
        reason,
        None
    )

    embed = punishment_embed(
        ctx.guild,
        member,
        "BAN",
        reason,
        ctx.author,
        punishment_id
    )

    await safe_dm(member, embed)

    try:
        await member.ban(reason=reason)
    except discord.HTTPException:
        return await ctx.send(
            "❌ Não consegui banir esse usuário."
        )

    await send_punishment_log(ctx.guild, embed)

    await ctx.send(
        f"🔨 {member} foi banido.\n"
        f"ID da punição: `{punishment_id}`"
    )


# =========================================================
# COMANDO: HACKBAN
# =========================================================

@bot.command()
@commands.has_permissions(ban_members=True)
async def hackban(ctx, user_id: int, *, reason="Não informado"):
    try:
        user = await bot.fetch_user(user_id)
    except discord.NotFound:
        return await ctx.send("❌ Usuário não encontrado.")

    punishment_id = save_punishment(
        ctx.guild.id,
        user.id,
        ctx.author.id,
        "HACKBAN",
        reason,
        None
    )

    try:
        await ctx.guild.ban(
            user,
            reason=reason
        )
    except discord.HTTPException:
        return await ctx.send(
            "❌ Não consegui banir esse usuário."
        )

    embed = discord.Embed(
        title="🔨 Hackban aplicado",
        description=(
            f"**Usuário:** {user} (`{user.id}`)\n"
            f"**Motivo:** {reason}\n"
            f"**Moderador:** {ctx.author.mention}\n"
            f"**ID:** `{punishment_id}`"
        ),
        color=discord.Color.red()
    )

    await send_punishment_log(ctx.guild, embed)

    await ctx.send(
        f"🔨 `{user_id}` foi banido mesmo estando fora do servidor."
    )


# =========================================================
# COMANDO: UNBAN
# =========================================================

@bot.command()
@commands.has_permissions(ban_members=True)
async def unban(ctx, user_id: int):
    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user)

    except discord.NotFound:
        return await ctx.send(
            "❌ Usuário não está banido ou não foi encontrado."
        )

    except discord.HTTPException:
        return await ctx.send(
            "❌ Não consegui remover o ban."
        )

    await ctx.send(
        f"🔓 O ban de **{user}** foi removido."
    )


# =========================================================
# COMANDO: CLEAR
# =========================================================

@bot.command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int):
    if amount <= 0:
        return await ctx.send("❌ Informe uma quantidade válida.")

    if amount > 100:
        return await ctx.send(
            "❌ O limite é de 100 mensagens por vez."
        )

    deleted = await ctx.channel.purge(
        limit=amount + 1
    )

    msg = await ctx.send(
        f"🧹 **{len(deleted) - 1} mensagens** foram apagadas."
    )

    await asyncio.sleep(3)

    try:
        await msg.delete()
    except discord.HTTPException:
        pass


# =========================================================
# COMANDO: SLOWMODE
# =========================================================

@bot.command()
@commands.has_permissions(manage_channels=True)
async def slowmode(ctx, seconds: int):
    if seconds < 0 or seconds > 21600:
        return await ctx.send(
            "❌ O valor deve estar entre 0 e 21600 segundos."
        )

    await ctx.channel.edit(
        slowmode_delay=seconds
    )

    await ctx.send(
        f"🐢 Slowmode definido para **{seconds}s**."
    )


# =========================================================
# COMANDO: LOCK
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
# COMANDO: UNLOCK
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
# COMANDO: SERVERINFO
# =========================================================

@bot.command()
async def serverinfo(ctx):
    guild = ctx.guild

    embed = discord.Embed(
        title=f"📊 {guild.name}",
        color=discord.Color.blurple()
    )

    if guild.icon:
        embed.set_thumbnail(
            url=guild.icon.url
        )

    embed.add_field(
        name="👑 Dono",
        value=guild.owner.mention if guild.owner else "Desconhecido",
        inline=True
    )

    embed.add_field(
        name="👥 Membros",
        value=str(guild.member_count),
        inline=True
    )

    embed.add_field(
        name="💬 Canais",
        value=str(len(guild.channels)),
        inline=True
    )

    embed.add_field(
        name="🎭 Cargos",
        value=str(len(guild.roles)),
        inline=True
    )

    embed.add_field(
        name="🆔 ID",
        value=str(guild.id),
        inline=True
    )

    embed.add_field(
        name="📅 Criado em",
        value=stamp(guild.created_at),
        inline=True
    )

    await ctx.send(embed=embed)


# =========================================================
# COMANDO: USERINFO
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
        name="ID",
        value=str(member.id),
        inline=False
    )

    embed.add_field(
        name="Conta criada",
        value=stamp(member.created_at),
        inline=True
    )

    embed.add_field(
        name="Entrou",
        value=stamp(member.joined_at),
        inline=True
    )

    embed.add_field(
        name="Cargo mais alto",
        value=member.top_role.mention,
        inline=False
    )

    await ctx.send(embed=embed)


# =========================================================
# COMANDO: AVATAR
# =========================================================

@bot.command(aliases=["pfp"])
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
# COMANDO: SAY
# =========================================================

@bot.command()
@commands.has_permissions(manage_messages=True)
async def say(ctx, *, text):
    try:
        await ctx.message.delete()
    except discord.HTTPException:
        pass

    await ctx.send(
        text,
        allowed_mentions=discord.AllowedMentions.none()
    )


# =====================================================
