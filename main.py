import os
import re
import sqlite3
import time
from datetime import datetime, timedelta

import discord
from discord.ext import commands
from discord.ui import View, Button


# =========================================================
# CONFIGURAÇÃO
# =========================================================

TOKEN = os.getenv("TOKEN")
PREFIX = "!"
DB = "bot.db"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None
)

START_TIME = time.time()

spam_cache = {}
flood_cache = {}
repeat_cache = {}


# =========================================================
# BANCO DE DADOS
# =========================================================

def db():
    return sqlite3.connect(DB)


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS warns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS punishments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            punishment TEXT NOT NULL,
            reason TEXT NOT NULL,
            duration TEXT,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS config (
            guild_id INTEGER PRIMARY KEY,
            log_channel INTEGER,
            welcome_channel INTEGER,
            goodbye_channel INTEGER,
            autorole INTEGER,
            automod INTEGER DEFAULT 0,
            anti_link INTEGER DEFAULT 0,
            anti_invite INTEGER DEFAULT 0,
            anti_spam INTEGER DEFAULT 0,
            anti_flood INTEGER DEFAULT 0,
            anti_mention INTEGER DEFAULT 0,
            anti_caps INTEGER DEFAULT 0,
            repeat_messages INTEGER DEFAULT 0,
            automod_action TEXT DEFAULT 'delete'
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS badwords (
            guild_id INTEGER NOT NULL,
            word TEXT NOT NULL,
            UNIQUE(guild_id, word)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS whitelist (
            guild_id INTEGER NOT NULL,
            user_id INTEGER,
            role_id INTEGER,
            channel_id INTEGER
        )
    """)

    conn.commit()
    conn.close()


def ensure_guild(guild_id):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        "INSERT OR IGNORE INTO config (guild_id) VALUES (?)",
        (guild_id,)
    )

    conn.commit()
    conn.close()


def get_config(guild_id):
    ensure_guild(guild_id)

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM config WHERE guild_id = ?",
        (guild_id,)
    )

    row = cur.fetchone()

    conn.close()

    return row


def set_config(guild_id, column, value):
    allowed = {
        "log_channel",
        "welcome_channel",
        "goodbye_channel",
        "autorole",
        "automod",
        "anti_link",
        "anti_invite",
        "anti_spam",
        "anti_flood",
        "anti_mention",
        "anti_caps",
        "repeat_messages",
        "automod_action"
    }

    if column not in allowed:
        return

    ensure_guild(guild_id)

    conn = db()
    cur = conn.cursor()

    cur.execute(
        f"UPDATE config SET {column} = ? WHERE guild_id = ?",
        (value, guild_id)
    )

    conn.commit()
    conn.close()


# =========================================================
# UTILIDADES
# =========================================================

def now():
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


def is_staff(member):
    permissions = member.guild_permissions

    return any([
        permissions.administrator,
        permissions.manage_guild,
        permissions.manage_messages,
        permissions.moderate_members,
        permissions.ban_members,
        permissions.kick_members
    ])


def is_whitelisted(message):
    if not message.guild:
        return False

    role_ids = [
        role.id
        for role in message.author.roles
    ]

    conn = db()
    cur = conn.cursor()

    clauses = [
        "user_id = ?",
        "channel_id = ?"
    ]

    params = [
        message.author.id,
        message.channel.id
    ]

    if role_ids:
        placeholders = ",".join(
            "?" for _ in role_ids
        )

        clauses.append(
            f"role_id IN ({placeholders})"
        )

        params.extend(role_ids)

    query = f"""
        SELECT 1
        FROM whitelist
        WHERE guild_id = ?
        AND ({' OR '.join(clauses)})
        LIMIT 1
    """

    cur.execute(
        query,
        [message.guild.id, *params]
    )

    result = cur.fetchone()

    conn.close()

    return result is not None


async def send_log(
    guild,
    title,
    description,
    color=discord.Color.blurple()
):
    config = get_config(guild.id)

    channel_id = (
        config[1]
        if config
        else None
    )

    if not channel_id:
        return

    channel = guild.get_channel(channel_id)

    if not channel:
        return

    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now()
    )

    try:
        await channel.send(embed=embed)

    except (
        discord.Forbidden,
        discord.HTTPException
    ):
        pass


async def punishment_dm(
    member,
    punishment,
    reason,
    moderator,
    duration=None
):
    embed = discord.Embed(
        title="🔔 Você recebeu uma punição",
        description=(
            "Uma ação de moderação foi aplicada "
            f"à sua conta no servidor **{member.guild.name}**."
        ),
        color=discord.Color.orange(),
        timestamp=datetime.now()
    )

    embed.add_field(
        name="🛡️ Punição",
        value=punishment,
        inline=True
    )

    embed.add_field(
        name="👮 Moderador",
        value=str(moderator),
        inline=True
    )

    if duration:
        embed.add_field(
            name="⏱️ Duração",
            value=duration,
            inline=True
        )

    embed.add_field(
        name="📝 Motivo",
        value=reason,
        inline=False
    )

    embed.add_field(
        name="🏠 Servidor",
        value=member.guild.name,
        inline=False
    )

    embed.add_field(
        name="📅 Data",
        value=now(),
        inline=False
    )

    embed.set_footer(
        text="Sistema de Moderação"
    )

    try:
        await member.send(embed=embed)

    except (
        discord.Forbidden,
        discord.HTTPException
    ):
        pass


def save_punishment(
    guild_id,
    user_id,
    moderator_id,
    punishment,
    reason,
    duration=None
):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO punishments (
            guild_id,
            user_id,
            moderator_id,
            punishment,
            reason,
            duration,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        guild_id,
        user_id,
        moderator_id,
        punishment,
        reason,
        duration,
        now()
    ))

    conn.commit()
    conn.close()


# =========================================================
# AUTOMOD
# =========================================================

async def apply_auto_action(
    message,
    reason
):
    config = get_config(
        message.guild.id
    )

    action = (
        config[13]
        if config
        else "delete"
    )

    action = action or "delete"

    try:
        await message.delete()

    except (
        discord.Forbidden,
        discord.HTTPException
    ):
        pass

    # -----------------------------------------------------
    # DELETE
    # -----------------------------------------------------

    if action == "delete":

        save_punishment(
            message.guild.id,
            message.author.id,
            bot.user.id,
            "AutoMod Delete",
            reason
        )

    # -----------------------------------------------------
    # WARN
    # -----------------------------------------------------

    elif action == "warn":

        conn = db()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO warns (
                guild_id,
                user_id,
                moderator_id,
                reason,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            message.guild.id,
            message.author.id,
            bot.user.id,
            f"AutoMod: {reason}",
            now()
        ))

        cur.execute("""
            SELECT COUNT(*)
            FROM warns
            WHERE guild_id = ?
            AND user_id = ?
        """, (
            message.guild.id,
            message.author.id
        ))

        total = cur.fetchone()[0]

        conn.commit()
        conn.close()

        await punishment_dm(
            message.author,
            "Advertência automática",
            reason,
            bot.user
        )

        save_punishment(
            message.guild.id,
            message.author.id,
            bot.user.id,
            "AutoMod Warn",
            reason
        )

        if total >= 4:

            try:
                await message.guild.ban(
                    message.author,
                    reason="AutoMod: 4 advertências."
                )

                await punishment_dm(
                    message.author,
                    "Banimento automático",
                    "Você atingiu 4 advertências.",
                    bot.user
                )

                save_punishment(
                    message.guild.id,
                    message.author.id,
                    bot.user.id,
                    "AutoMod Ban",
                    "4 advertências acumuladas."
                )

            except (
                discord.Forbidden,
                discord.HTTPException
            ):
                pass

    # -----------------------------------------------------
    # MUTE
    # -----------------------------------------------------

    elif action == "mute":

        try:
            duration = 10

            await message.author.timeout(
                timedelta(
                    minutes=duration
                ),
                reason=f"AutoMod: {reason}"
            )

            await punishment_dm(
                message.author,
                "Timeout automático",
                reason,
                bot.user,
                f"{duration} minutos"
            )

            save_punishment(
                message.guild.id,
                message.author.id,
                bot.user.id,
                "AutoMod Timeout",
                reason,
                f"{duration} minutos"
            )

        except (
            discord.Forbidden,
            discord.HTTPException
        ):
            pass

    await send_log(
        message.guild,
        "🤖 AutoMod acionado",
        (
            f"**Usuário:** {message.author.mention}\n"
            f"**Canal:** {message.channel.mention}\n"
            f"**Regra:** {reason}\n"
            f"**Ação:** {action}"
        ),
        discord.Color.red()
    )

    return True


async def automod_check(message):

    if not message.guild:
        return False

    config = get_config(
        message.guild.id
    )

    if not config:
        return False

    if not config[5]:
        return False

    content = message.content or ""

    reason = None

    # -----------------------------------------------------
    # LINK
    # -----------------------------------------------------

    if config[6]:

        if re.search(
            r"(https?://|www\.)\S+",
            content,
            re.I
        ):
            reason = "Link não permitido."

    # -----------------------------------------------------
    # INVITE
    # -----------------------------------------------------

    elif config[7]:

        if re.search(
            r"(discord\.gg/|discord(?:app)?\.com/invite/)",
            content,
            re.I
        ):
            reason = (
                "Convite de Discord não permitido."
            )

    # -----------------------------------------------------
    # SPAM
    # -----------------------------------------------------

    if config[8] and reason is None:

        key = (
            message.guild.id,
            message.author.id
        )

        current = time.time()

        spam_cache.setdefault(
            key,
            []
        )

        spam_cache[key] = [
            t
            for t in spam_cache[key]
            if current - t < 6
        ]

        spam_cache[key].append(
            current
        )

        if len(spam_cache[key]) >= 6:

            spam_cache[key].clear()

            reason = "Spam detectado."

    # -----------------------------------------------------
    # FLOOD
    # -----------------------------------------------------

    if config[9] and reason is None:

        key = (
            message.guild.id,
            message.author.id
        )

        current = time.time()

        last = flood_cache.get(
            key,
            0
        )

        flood_cache[key] = current

        if current - last < 0.7:
            reason = "Flood detectado."

    # -----------------------------------------------------
    # MENÇÕES
    # -----------------------------------------------------

    if config[10] and reason is None:

        total_mentions = (
            len(message.mentions)
            + len(message.role_mentions)
        )

        if total_mentions >= 5:
            reason = "Excesso de menções."

    # -----------------------------------------------------
    # CAPS
    # -----------------------------------------------------

    if config[11] and reason is None:

        letters = [
            c
            for c in content
            if c.isalpha()
        ]

        if len(letters) >= 10:

            upper = sum(
                c.isupper()
                for c in letters
            )

            percentage = (
                upper / len(letters)
            )

            if percentage >= 0.75:
                reason = (
                    "Excesso de letras maiúsculas."
                )

    # -----------------------------------------------------
    # REPETIÇÃO
    # -----------------------------------------------------

    if config[12] and reason is None:

        key = (
            message.guild.id,
            message.author.id
        )

        normalized = (
            content.lower().strip()
        )

        if (
            repeat_cache.get(key)
            == normalized
            and normalized
        ):
            reason = "Mensagem repetida."

        repeat_cache[key] = normalized

    # -----------------------------------------------------
    # PALAVRAS PROIBIDAS
    # -----------------------------------------------------

    if reason is None:

        conn = db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT word
            FROM badwords
            WHERE guild_id = ?
            """,
            (message.guild.id,)
        )

        words = cur.fetchall()

        conn.close()

        lower = content.lower()

        for (word,) in words:

            if word.lower() in lower:

                reason = (
                    f"Palavra bloqueada: `{word}`"
                )

                break

    if reason is None:
        return False

    return await apply_auto_action(
        message,
        reason
    )


# =========================================================
# EVENTOS
# =========================================================

@bot.event
async def on_ready():

    init_db()

    print("=" * 45)
    print(f"Bot: {bot.user}")
    print(f"ID: {bot.user.id}")
    print(f"Servidores: {len(bot.guilds)}")
    print("Banco de dados: OK")
    print("=" * 45)

    try:
        await bot.change_presence(
            activity=discord.Game(
                name=f"{PREFIX}help"
            )
        )

    except discord.HTTPException:
        pass


@bot.event
async def on_message(message):

    if message.author.bot:
        return

    if bot.user and bot.user in message.mentions:

        try:
            await message.channel.send("que")

        except discord.HTTPException:
            pass

    if message.guild:

        if (
            not is_staff(message.author)
            and not is_whitelisted(message)
        ):

            if await automod_check(message):
                return

    await bot.process_commands(message)


@bot.event
async def on_member_join(member):

    config = get_config(
        member.guild.id
    )

    channel = None

    if config and config[2]:
        channel = member.guild.get_channel(
            config[2]
        )

    if channel:

        embed = discord.Embed(
            title="👋 Novo membro",
            description=(
                f"Bem-vindo(a), {member.mention}!"
            ),
            color=discord.Color.green()
        )

        embed.set_thumbnail(
            url=member.display_avatar.url
        )

        try:
            await channel.send(
                embed=embed
            )

        except discord.HTTPException:
            pass

    if config and config[4]:

        role = member.guild.get_role(
            config[4]
        )

        if role:

            try:
                await member.add_roles(
                    role,
                    reason="Autorole"
                )

            except discord.Forbidden:
                pass


@bot.event
async def on_member_remove(member):

    config = get_config(
        member.guild.id
    )

    channel = None

    if config and config[3]:
        channel = member.guild.get_channel(
            config[3]
        )

    if channel:

        try:
            await channel.send(
                f"👋 **{member}** saiu do servidor."
            )

        except discord.HTTPException:
            pass


@bot.event
async def on_message_delete(message):

    if not message.guild:
        return

    if message.author.bot:
        return

    text = message.content or "[sem texto]"

    await send_log(
        message.guild,
        "🗑️ Mensagem apagada",
        (
            f"**Autor:** {message.author.mention}\n"
            f"**Canal:** {message.channel.mention}\n"
            f"**Conteúdo:** {text[:1500]}"
        ),
        discord.Color.red()
    )


@bot.event
async def on_message_edit(
    before,
    after
):

    if not before.guild:
        return

    if before.author.bot:
        return

    if before.content == after.content:
        return

    await send_log(
        before.guild,
        "✏️ Mensagem editada",
        (
            f"**Autor:** {before.author.mention}\n"
            f"**Canal:** {before.channel.mention}\n"
            f"**Antes:** {before.content[:700]}\n"
            f"**Depois:** {after.content[:700]}"
        ),
        discord.Color.orange()
    )


# =========================================================
# PING
# =========================================================

@bot.command()
async def ping(ctx):

    latency = round(
        bot.latency * 1000
    )

    embed = discord.Embed(
        title="🏓 Pong!",
        description=f"Latência: **{latency}ms**",
        color=discord.Color.green()
    )

    await ctx.send(
        embed=embed
    )


# =============================
