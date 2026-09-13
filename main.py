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

intents = discord.Intents.all()

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None
)

start_time = time.time()

# Cache apenas para coisas temporárias.
# Dados importantes ficam no SQLite.
spam_cache = {}
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
    return (
        member.guild_permissions.administrator
        or member.guild_permissions.manage_guild
        or member.guild_permissions.manage_messages
        or member.guild_permissions.moderate_members
        or member.guild_permissions.ban_members
        or member.guild_permissions.kick_members
    )


def is_whitelisted(message):
    guild_id = message.guild.id
    user_id = message.author.id
    role_ids = [role.id for role in message.author.roles]
    channel_id = message.channel.id

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT 1 FROM whitelist
        WHERE guild_id = ?
        AND (
            user_id = ?
            OR role_id IN ({})
            OR channel_id = ?
        )
        LIMIT 1
    """.format(",".join("?" * len(role_ids)) if role_ids else "NULL"),
        (guild_id, user_id, *role_ids, channel_id)
    )

    result = cur.fetchone()

    conn.close()

    return result is not None


async def send_log(guild, title, description, color=discord.Color.blurple()):
    ensure_guild(guild.id)

    config = get_config(guild.id)

    if not config or not config[1]:
        return

    channel = guild.get_channel(config[1])

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
    except discord.Forbidden:
        pass


async def punishment_dm(
    member,
    punishment,
    reason,
    moderator,
    duration=None
):
    embed = discord.Embed(
        title=f"🔔 Você recebeu uma punição",
        description=(
            f"Uma ação de moderação foi aplicada à sua conta "
            f"no servidor **{member.guild.name}**."
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
    except discord.Forbidden:
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
# INICIALIZAÇÃO
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
    except:
        pass


# =========================================================
# MENÇÃO DO BOT
# =========================================================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    if bot.user and bot.user in message.mentions:
        await message.channel.send("que")

    if message.guild:

        if not is_staff(message.author) and not is_whitelisted(message):
            result = await automod_check(message)

            if result:
                await bot.process_commands(message)
                return

    await bot.process_commands(message)


# =========================================================
# AUTOMOD
# =========================================================

async def automod_check(message):

    guild = message.guild
    content = message.content
    config = get_config(guild.id)

    if not config:
        return False

    # Índices da tabela config
    automod = config[5]

    if not automod:
        return False

    reason = None

    # -----------------------------------------------------
    # ANTI LINK
    # -----------------------------------------------------

    if config[6]:

        link_pattern = r"(https?://|www\.)\S+"

        if re.search(link_pattern, content.lower()):
            reason = "Link não permitido."

    # -----------------------------------------------------
    # ANTI INVITE
    # -----------------------------------------------------

    if config[7] and reason is None:

        invite_pattern = r"(discord\.gg/|discord\.com/invite/)"

        if re.search(invite_pattern, content.lower()):
            reason = "Convite de Discord não permitido."

    # -----------------------------------------------------
    # ANTI SPAM
    # -----------------------------------------------------

    if config[8] and reason is None:

        user_id = message.author.id
        current = time.time()

        if user_id not in spam_cache:
            spam_cache[user_id] = []

        spam_cache[user_id] = [
            t for t in spam_cache[user_id]
            if current - t < 6
        ]

        spam_cache[user_id].append(current)

        if len(spam_cache[user_id]) >= 6:
            spam_cache[user_id] = []
            reason = "Spam detectado."

    # -----------------------------------------------------
    # ANTI FLOOD
    # -----------------------------------------------------

    if config[9] and reason is None:

        user_id = message.author.id
        current = time.time()

        key = f"{guild.id}:{user_id}"

        if key in repeat_cache:

            last_time = repeat_cache[key]

            if current - last_time < 0.7:
                reason = "Flood detectado."

        repeat_cache[key] = current

    # -----------------------------------------------------
    # ANTI MENTION
    # -----------------------------------------------------

    if config[10] and reason is None:

        total_mentions = (
            len(message.mentions)
            + len(message.role_mentions)
        )

        if total_mentions >= 5:
            reason = "Excesso de menções."

    # -----------------------------------------------------
    # ANTI CAPS
    # -----------------------------------------------------

    if config[11] and reason is None:

        letters = [
            c for c in content
            if c.isalpha()
        ]

        if len(letters) >= 10:

            upper = sum(
                1 for c in letters
                if c.isupper()
            )

            percentage = upper / len(letters)

            if percentage >= 0.75:
                reason = "Excesso de letras maiúsculas."

    # -----------------------------------------------------
    # MENSAGEM REPETIDA
    # -----------------------------------------------------

    if config[12] and reason is None:

        key = f"{guild.id}:{message.author.id}"

        if key in repeat_cache:

            if repeat_cache[key] == content.lower():
                reason = "Mensagem repetida."

        repeat_cache[key] = content.lower()

    # -----------------------------------------------------
    # PALAVRAS PROIBIDAS
    # -----------------------------------------------------

    if reason is None:

        conn = db()
        cur = conn.cursor()

        cur.execute(
            "SELECT word FROM badwords WHERE guild_id = ?",
            (guild.id,)
        )

        words = cur.fetchall()

        conn.close()

        for (word,) in words:

            if word.lower() in content.lower():
                reason = f"Palavra bloqueada: `{word}`"
                break

    if reason is None:
        return False

    # -----------------------------------------------------
    # AÇÃO
    # -----------------------------------------------------

    action = config[13] or "delete"

    try:
        await message.delete()
    except discord.Forbidden:
        pass

    save_punishment(
        guild.id,
        message.author.id,
        bot.user.id,
        f"AutoMod: {action}",
        reason
    )

    await send_log(
        guild,
        "🤖 AutoMod acionado",
        (
            f"**Usuário:** {message.author.mention}\n"
            f"**Canal:** {message.channel.mention}\n"
            f"**Regra:** {reason}\n"
            f"**Ação:** {action}"
        ),
        discord.Color.red()
    )

    # -----------------------------------------------------
    # WARN
    # -----------------------------------------------------

    if action == "warn":

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
            guild.id,
            message.author.id,
            bot.user.id,
            f"AutoMod: {reason}",
            now()
        ))

        conn.commit()

        cur.execute("""
            SELECT COUNT(*)
            FROM warns
            WHERE guild_id = ?
            AND user_id = ?
        """, (
            guild.id,
            message.author.id
        ))

        total = cur.fetchone()[0]

        conn.close()

        await punishment_dm(
            message.author,
            "Advertência automática",
            reason,
            bot.user
        )

        try:
            await message.channel.send(
                f"⚠️ {message.author.mention}, sua mensagem foi removida. "
                f"**Motivo:** {reason}",
                delete_after=5
            )
        except:
            pass

        if total >= 4:

            try:
                await message.author.ban(
                    reason="AutoMod: 4 advertências."
                )

                save_punishment(
                    guild.id,
                    message.author.id,
                    bot.user.id,
                    "Ban",
                    "Acúmulo de 4 advertências."
                )

                await punishment_dm(
                    message.author,
                    "Banimento automático",
                    "Você atingiu 4 advertências.",
                    bot.user
                )

            except discord.Forbidden:
                pass

    # -----------------------------------------------------
    # MUTE
    # -----------------------------------------------------

    elif action == "mute":

        try:

            duration = 10

            await message.author.timeout(
                timedelta(minutes=duration),
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
                guild.id,
                message.author.id,
                bot.user.id,
                "AutoMod Timeout",
                reason,
                f"{duration} minutos"
            )

        except discord.Forbidden:
            pass

    return True


# =========================================================
# PING
# =========================================================

@bot.command()
async def ping(ctx):

    latency = round(bot.latency * 1000)

    embed = discord.Embed(
        title="🏓 Pong!",
        description=f"Latência: **{latency}ms**",
        color=discord.Color.green()
    )

    await ctx.send(embed=embed)


# =========================================================
# WARN
# =========================================================

@bot.command()
@commands.has_permissions(manage_messages=True)
async def warn(
    ctx,
    member: discord.Member,
    *,
    motivo="Nenhum motivo informado"
):

    if member == ctx.author:
        return await ctx.send(
            "❌ Você não pode advertir a si mesmo."
        )

    if member == ctx.guild.owner:
        return await ctx.send(
            "❌ Você não pode advertir o dono do servidor."
        )

    if member.top_role >= ctx.author.top_role:
        return await ctx.send(
            "❌ O cargo do usuário é igual ou superior ao seu."
        )

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
        ctx.guild.id,
        member.id,
        ctx.author.id,
        motivo,
        now()
    ))

    conn.commit()

    cur.execute("""
        SELECT COUNT(*)
        FROM warns
        WHERE guild_id = ?
        AND user_id = ?
    """, (
        ctx.guild.id,
        member.id
    ))

    total = cur.fetchone()[0]

    conn.close()

    await punishment_dm(
        member,
        "Advertência",
        motivo,
        ctx.author
    )

    save_punishment(
        ctx.guild.id,
        member.id,
        ctx.author.id,
        "Warn",
        motivo
    )

    embed = discord.Embed(
        title="⚠️ Advertência aplicada",
        color=discord.Color.orange(),
        timestamp=datetime.now()
    )

    embed.add_field(
        name="👤 Usuário",
        value=f"{member.mention}\n`{member.id}`",
        inline=True
    )

    embed.add_field(
        name="⚠️ Total",
        value=f"`{total}/4`",
        inline=True
    )

    embed.add_field(
        name="👮 Moderador",
        value=ctx.author.mention,
        inline=True
    )

    embed.add_field(
        name="📝 Motivo",
        value=motivo,
        inline=False
    )

    await ctx.send(embed=embed)

    await send_log(
        ctx.guild,
        "⚠️ Warn aplicado",
        (
            f"**Usuário:** {member.mention}\n"
            f"**Moderador:** {ctx.author.mention}\n"
            f"**Motivo:** {motivo}\n"
            f"**Total:** {total}/4"
        ),
        discord.Color.orange()
    )

    if total >= 4:

        try:
            await member.ban(
                reason="4 advertências acumuladas."
            )

            await punishment_dm(
                member,
                "Banimento automático",
                "Você atingiu 4 advertências.",
                ctx.author
            )

            save_punishment(
                ctx.guild.id,
                member.id,
                ctx.author.id,
                "Ban",
                "4 advertências acumuladas."
            )

            await ctx.send(
                f"🔨 {member.mention} foi banido automaticamente "
                f"por atingir 4 advertências."
            )

        except discord.Forbidden:
            await ctx.send(
                "❌ Não consegui aplicar o banimento automático."
            )


# =========================================================
# WARNS
# =========================================================

@bot.command()
@commands.has_permissions(manage_messages=True)
async def warns(ctx, member: discord.Member):

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT moderator_id, reason, created_at
        FROM warns
        WHERE guild_i
