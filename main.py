import os
import io
import re
import json
import html
import asyncio
import unicodedata

from datetime import datetime, timezone

import discord
from discord.ext import commands
from discord import app_commands
import asyncpg


# =========================================================
# 1. CONFIGURAÇÕES GERAIS
# =========================================================

TOKEN = os.getenv("DISCORD_TOKEN")
DB_PASSWORD = os.getenv("SUPABASE_DB_PASSWORD")

PREFIX = "!"
EMBED_COLOR = discord.Colour.from_rgb(128, 128, 128)

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True
intents.moderation = True

db_pool = None

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN não configurado.")

if not DB_PASSWORD:
    raise RuntimeError("SUPABASE_DB_PASSWORD não configurado.")


# =========================================================
# 2. TIPOS DE TICKETS
# =========================================================

TICKET_TYPES = [
    ("🚨 Denunciar membro", "denuncia"),
    ("👥 Entrar em contato com a equipe", "equipe"),
    ("🤝 Solicitar parceria", "parceria"),
    ("⚖️ Solicitar revisão de punição", "revisao"),
    ("❓ Dúvidas", "duvidas"),
    ("🛠️ Suporte geral", "suporte"),
    ("🐛 Relatar bug ou erro", "bug"),
]


# =========================================================
# 3. CARGOS DO SISTEMA
# =========================================================

ROLE_GROUPS = {
    "direcao": {
        "label": "Direção",
        "roles": [
            "Diretor Geral",
            "Server Manager",
            "Bot Manager",
        ],
    },
    "administracao": {
        "label": "Administração",
        "roles": [
            "Admin",
            "Admin Jr",
        ],
    },
    "moderacao": {
        "label": "Moderação",
        "roles": [
            "Mod",
            "Mod Jr",
        ],
    },
    "suporte": {
        "label": "Suporte",
        "roles": [
            "Suporte",
            "Suporte Jr",
        ],
    },
    "criacao": {
        "label": "Equipe criativa",
        "roles": [
            "Criador de Eventos",
            "Designer",
        ],
    },
    "membros": {
        "label": "Membros",
        "roles": [
            "Super Ativo",
            "Iniciante",
            "VIP",
            "Parceiro",
            "Apoiador",
            "Membro Antigo",
            "Verificado",
        ],
    },
}

ROLE_COLORS = {
    "Diretor Geral": discord.Colour.from_rgb(180, 40, 40),
    "Server Manager": discord.Colour.from_rgb(190, 90, 40),
    "Bot Manager": discord.Colour.from_rgb(90, 80, 190),
    "Admin": discord.Colour.from_rgb(200, 50, 50),
    "Admin Jr": discord.Colour.from_rgb(210, 100, 100),
    "Mod": discord.Colour.from_rgb(40, 110, 210),
    "Mod Jr": discord.Colour.from_rgb(80, 150, 220),
    "Suporte": discord.Colour.from_rgb(40, 160, 130),
    "Suporte Jr": discord.Colour.from_rgb(80, 190, 160),
    "Criador de Eventos": discord.Colour.from_rgb(180, 100, 220),
    "Designer": discord.Colour.from_rgb(230, 120, 180),
    "Super Ativo": discord.Colour.from_rgb(230, 190, 50),
    "Iniciante": discord.Colour.from_rgb(140, 140, 140),
    "VIP": discord.Colour.from_rgb(240, 190, 50),
    "Parceiro": discord.Colour.from_rgb(80, 170, 220),
    "Apoiador": discord.Colour.from_rgb(70, 190, 120),
    "Membro Antigo": discord.Colour.from_rgb(150, 120, 80),
    "Verificado": discord.Colour.from_rgb(80, 180, 100),
}


# =========================================================
# 4. CONFIGURAÇÕES PADRÃO
# =========================================================

DEFAULT_CONFIG = {
    # Tickets
    "ticket_category_id": None,
    "transcript_channel_id": None,
    "staff_role_id": None,
    "ticket_panel_channel_id": None,
    "log_ticket_channel_id": None,

    # Parcerias
    "partnership_category_id": None,
    "partnership_channel_id": None,
    "partnership_role_id": None,
    "log_partnership_channel_id": None,

    # Staff
    "staff_chat_channel_id": None,
    "staff_announcements_channel_id": None,
    "staff_information_channel_id": None,
    "staff_proofs_channel_id": None,
    "staff_meetings_channel_id": None,
    "staff_support_channel_id": None,
    "staff_changelog_channel_id": None,
    "staff_punishment_channel_id": None,
    "staff_list_channel_id": None,

    # Administração
    "admin_owner_chat_channel_id": None,
    "admin_director_chat_channel_id": None,
    "admin_announcements_channel_id": None,
    "admin_planning_channel_id": None,
    "admin_team_channel_id": None,
    "admin_appeals_channel_id": None,
    "admin_settings_channel_id": None,
    "admin_reports_channel_id": None,

    # Logs separados
    "log_server_channel_id": None,
    "log_member_channel_id": None,
    "log_role_channel_id": None,
    "log_punishment_channel_id": None,
    "log_bot_channel_id": None,
    "log_moderation_channel_id": None,
    "log_staff_channel_id": None,
    "log_admin_channel_id": None,

    # Autorole
    "bot_autorole_id": None,

    # Lista Staff
    "staff_list_message_id": None,

    # Cargos
    "admin_role_id": None,
    "director_role_id": None,
    "moderator_role_id": None,
    "support_role_id": None,

    # Outros
    "welcome_channel_id": None,
    "leave_channel_id": None,
}


# =========================================================
# 5. GRUPOS DE CONFIGURAÇÃO
# =========================================================

CONFIG_GROUPS = {
    "tickets": {
        "label": "🎫 Tickets",
        "keys": [
            "ticket_category_id",
            "transcript_channel_id",
            "staff_role_id",
            "ticket_panel_channel_id",
            "log_ticket_channel_id",
        ],
    },

    "partnerships": {
        "label": "🤝 Parcerias",
        "keys": [
            "partnership_category_id",
            "partnership_channel_id",
            "partnership_role_id",
            "log_partnership_channel_id",
        ],
    },

    "staff": {
        "label": "🛡️ Staff",
        "keys": [
            "staff_chat_channel_id",
            "staff_announcements_channel_id",
            "staff_information_channel_id",
            "staff_proofs_channel_id",
            "staff_meetings_channel_id",
            "staff_support_channel_id",
            "staff_changelog_channel_id",
            "staff_punishment_channel_id",
            "staff_list_channel_id",
            "moderator_role_id",
            "support_role_id",
        ],
    },

    "administration": {
        "label": "⚙️ Administração",
        "keys": [
            "admin_owner_chat_channel_id",
            "admin_director_chat_channel_id",
            "admin_announcements_channel_id",
            "admin_planning_channel_id",
            "admin_team_channel_id",
            "admin_appeals_channel_id",
            "admin_settings_channel_id",
            "admin_reports_channel_id",
            "admin_role_id",
            "director_role_id",
        ],
    },

    "logs": {
        "label": "📁 Logs",
        "keys": [
            "log_server_channel_id",
            "log_member_channel_id",
            "log_role_channel_id",
            "log_punishment_channel_id",
            "log_bot_channel_id",
            "log_ticket_channel_id",
            "log_partnership_channel_id",
            "log_moderation_channel_id",
            "log_staff_channel_id",
            "log_admin_channel_id",
        ],
    },

    "automation": {
        "label": "🤖 Automação",
        "keys": [
            "bot_autorole_id",
            "welcome_channel_id",
            "leave_channel_id",
        ],
    },
}


# =========================================================
# 6. NOMES DAS CONFIGURAÇÕES
# =========================================================

CONFIG_LABELS = {
    "ticket_category_id": "Categoria dos tickets",
    "transcript_channel_id": "Canal de transcripts",
    "staff_role_id": "Cargo Staff",
    "ticket_panel_channel_id": "Canal do painel de tickets",
    "log_ticket_channel_id": "Logs de tickets",

    "partnership_category_id": "Categoria de parcerias",
    "partnership_channel_id": "Canal de parcerias",
    "partnership_role_id": "Cargo responsável por parcerias",
    "log_partnership_channel_id": "Logs de parcerias",

    "staff_chat_channel_id": "Chat Staff",
    "staff_announcements_channel_id": "Avisos Staff",
    "staff_information_channel_id": "Informações Staff",
    "staff_proofs_channel_id": "Provas de punições",
    "staff_meetings_channel_id": "Reuniões Staff",
    "staff_support_channel_id": "Atendimento Staff",
    "staff_changelog_channel_id": "Changelog",
    "staff_punishment_channel_id": "Solicitações de punição",
    "staff_list_channel_id": "Lista Staff",

    "admin_owner_chat_channel_id": "Chat do proprietário",
    "admin_director_chat_channel_id": "Chat da diretoria",
    "admin_announcements_channel_id": "Comunicados administrativos",
    "admin_planning_channel_id": "Planejamento",
    "admin_team_channel_id": "Gerenciamento de equipe",
    "admin_appeals_channel_id": "Revisão de punições",
    "admin_settings_channel_id": "Configurações administrativas",
    "admin_reports_channel_id": "Relatórios",

    "log_server_channel_id": "Logs do servidor",
    "log_member_channel_id": "Logs de membros",
    "log_role_channel_id": "Logs de cargos",
    "log_punishment_channel_id": "Logs de punições",
    "log_bot_channel_id": "Logs de bots",
    "log_moderation_channel_id": "Logs de moderação",
    "log_staff_channel_id": "Logs da equipe",
    "log_admin_channel_id": "Logs administrativos",

    "bot_autorole_id": "Cargo automático para bots",
    "welcome_channel_id": "Canal de entrada",
    "leave_channel_id": "Canal de saída",

    "admin_role_id": "Cargo Administrador",
    "director_role_id": "Cargo Diretoria",
    "moderator_role_id": "Cargo Moderador",
    "support_role_id": "Cargo Suporte",
}


# =========================================================
# 7. CONEXÃO COM SUPABASE
# =========================================================

async def connect_database():
    global db_pool

    db_pool = await asyncpg.create_pool(
        host="aws-0-us-west-2.pooler.supabase.com",
        port=5432,
        database="postgres",
        user="postgres.sdtivbtxtujgdizxyhed",
        password=DB_PASSWORD,
        ssl="require",
        min_size=1,
        max_size=5,
        command_timeout=60,
    )

    async with db_pool.acquire() as conn:

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_config (
                guild_id BIGINT PRIMARY KEY,
                settings JSONB NOT NULL DEFAULT '{}'::jsonb,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ticket_counters (
                guild_id BIGINT PRIMARY KEY,
                last_number BIGINT NOT NULL DEFAULT 0
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_number BIGINT PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                channel_id BIGINT NOT NULL UNIQUE,
                opener_id BIGINT NOT NULL,
                category TEXT NOT NULL,
                opened_at TIMESTAMPTZ NOT NULL,
                closed_at TIMESTAMPTZ,
                closer_id BIGINT,
                close_reason TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                claimed_by BIGINT,
                claimed_at TIMESTAMPTZ
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS partnerships (
                id BIGSERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                applicant_id BIGINT NOT NULL,
                server_name TEXT NOT NULL,
                invite_link TEXT NOT NULL,
                description TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                reviewed_by BIGINT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                reviewed_at TIMESTAMPTZ,
                published_message_id BIGINT
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_logs (
                id BIGSERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                actor_id BIGINT,
                action TEXT NOT NULL,
                details JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS moderation_history (
                id BIGSERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                moderator_id BIGINT NOT NULL,
                target_id BIGINT NOT NULL,
                action TEXT NOT NULL,
                reason TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS staff_activity (
                id BIGSERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                staff_id BIGINT NOT NULL,
                action TEXT NOT NULL,
                details JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS role_creation_history (
                id BIGSERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                role_id BIGINT NOT NULL,
                role_name TEXT NOT NULL,
                created_by BIGINT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # Compatibilidade com instalações anteriores
        await conn.execute("""
            ALTER TABLE tickets
            ADD COLUMN IF NOT EXISTS claimed_by BIGINT
        """)

        await conn.execute("""
            ALTER TABLE tickets
            ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ
        """)

        await conn.execute("""
            ALTER TABLE partnerships
            ADD COLUMN IF NOT EXISTS published_message_id BIGINT
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tickets_guild_status
            ON tickets(guild_id, status)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_partnerships_guild_status
            ON partnerships(guild_id, status)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_bot_logs_guild
            ON bot_logs(guild_id, created_at DESC)
        """)

    print("Supabase conectado e tabelas verificadas.", flush=True)


# =========================================================
# 8. CONFIGURAÇÕES DO SERVIDOR
# =========================================================

async def get_config(guild_id):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT settings
            FROM bot_config
            WHERE guild_id = $1
        """, guild_id)

    settings = dict(DEFAULT_CONFIG)

    if row:
        saved = row["settings"]

        if isinstance(saved, str):
            saved = json.loads(saved)

        if saved:
            settings.update(saved)

    return settings


async def set_config(guild_id, key, value):
    if key not in DEFAULT_CONFIG:
        raise ValueError("Configuração desconhecida.")

    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO bot_config (
                guild_id,
                settings,
                updated_at
            )
            VALUES ($1, $2::jsonb, NOW())
            ON CONFLICT (guild_id)
            DO UPDATE SET
                settings = bot_config.settings || EXCLUDED.settings,
                updated_at = NOW()
        """,
            guild_id,
            json.dumps({key: value})
        )


async def set_configs(guild_id, values):
    invalid = set(values) - set(DEFAULT_CONFIG)

    if invalid:
        raise ValueError(f"Configurações inválidas: {invalid}")

    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO bot_config (
                guild_id,
                settings,
                updated_at
            )
            VALUES ($1, $2::jsonb, NOW())
            ON CONFLICT (guild_id)
            DO UPDATE SET
                settings = bot_config.settings || EXCLUDED.settings,
                updated_at = NOW()
        """,
            guild_id,
            json.dumps(values)
        )


# =========================================================
# 9. SISTEMA DE LOGS NO BANCO
# =========================================================

async def registrar_log(
    guild_id,
    actor_id,
    action,
    details=None
):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO bot_logs (
                guild_id,
                actor_id,
                action,
                details
            )
            VALUES ($1, $2, $3, $4::jsonb)
        """,
            guild_id,
            actor_id,
            action,
            json.dumps(
                details or {},
                ensure_ascii=False,
                default=str
            )
        )


async def registrar_atividade_staff(
    guild_id,
    staff_id,
    action,
    details=None
):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO staff_activity (
                guild_id,
                staff_id,
                action,
                details
            )
            VALUES ($1, $2, $3, $4::jsonb)
        """,
            guild_id,
            staff_id,
            action,
            json.dumps(
                details or {},
                ensure_ascii=False,
                default=str
            )
        )


# =========================================================
# 10. FUNÇÕES AUXILIARES
# =========================================================

def gerar_nome_ticket(categoria, numero):
    nome = unicodedata.normalize("NFKD", categoria)
    nome = nome.encode("ascii", "ignore").decode("ascii")
    nome = nome.lower()
    nome = re.sub(r"[^a-z0-9]+", "-", nome).strip("-")

    return f"{nome}-{numero:04d}"


def is_admin(member):
    return (
        isinstance(member, discord.Member)
        and member.guild_permissions.administrator
    )


def check_admin(interaction):
    return (
        interaction.guild is not None
        and isinstance(interaction.user, discord.Member)
        and interaction.user.guild_permissions.administrator
    )


def criar_embed(titulo, descricao=None):
    embed = discord.Embed(
        title=titulo,
        description=descricao,
        colour=EMBED_COLOR,
        timestamp=datetime.now(timezone.utc)
    )
    return embed


async def get_configured_channel(guild, key):
    config = await get_config(guild.id)
    channel_id = config.get(key)

    if not channel_id:
        return None

    channel = guild.get_channel(int(channel_id))

    if channel is None:
        try:
            channel = await guild.fetch_channel(int(channel_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    return channel


async def get_configured_role(guild, key):
    config = await get_config(guild.id)
    role_id = config.get(key)

    if not role_id:
        return None

    return guild.get_role(int(role_id))


async def enviar_log(
    guild,
    config_key,
    titulo,
    descricao,
    actor=None
):
    channel = await get_configured_channel(guild, config_key)

    if channel is None:
        return

    embed = criar_embed(titulo, descricao)

    if actor:
        embed.set_footer(
            text=f"Responsável: {actor}",
            icon_url=actor.display_avatar.url
        )

    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        pass

# =========================================================
# 11. NUMERAÇÃO DOS TICKETS
# =========================================================

async def next_ticket_number(guild_id):
    async with db_pool.acquire() as conn:
        number = await conn.fetchval("""
            INSERT INTO ticket_counters (
                guild_id,
                last_number
            )
            VALUES ($1, 1)
            ON CONFLICT (guild_id)
            DO UPDATE SET
                last_number = ticket_counters.last_number + 1
            RETURNING last_number
        """, guild_id)

    return number


# =========================================================
# 12. CONTROLE DE EQUIPE
# =========================================================

def membro_tem_cargo(member, role_id):
    if not role_id:
        return False

    return any(
        role.id == int(role_id)
        for role in member.roles
    )


async def membro_equipe(member):
    config = await get_config(member.guild.id)

    staff_keys = [
        "staff_role_id",
        "admin_role_id",
        "director_role_id",
        "moderator_role_id",
        "support_role_id",
        "partnership_role_id",
    ]

    if member.guild_permissions.administrator:
        return True

    return any(
        config.get(key)
        and membro_tem_cargo(member, config[key])
        for key in staff_keys
    )


# =========================================================
# 13. SELEÇÃO DE CANAIS
# =========================================================

class ConfigChannelSelect(discord.ui.ChannelSelect):

    def __init__(self, config_key):
        self.config_key = config_key

        if config_key.endswith("category_id"):
            channel_types = [discord.ChannelType.category]
        else:
            channel_types = [discord.ChannelType.text]

        super().__init__(
            placeholder="Selecione o canal ou categoria...",
            min_values=1,
            max_values=1,
            channel_types=channel_types
        )

    async def callback(self, interaction):
        if not check_admin(interaction):
            return await interaction.response.send_message(
                "Você precisa ser administrador para alterar configurações.",
                ephemeral=True
            )

        selected = self.values[0]

        await set_config(
            interaction.guild.id,
            self.config_key,
            selected.id
        )

        await registrar_log(
            interaction.guild.id,
            interaction.user.id,
            "config_channel_updated",
            {
                "setting": self.config_key,
                "channel_id": selected.id
            }
        )

        await interaction.response.send_message(
            f"Configuração atualizada!\n"
            f"**{CONFIG_LABELS[self.config_key]}:** {selected.mention}",
            ephemeral=True
        )


# =========================================================
# 14. SELEÇÃO DE CARGOS
# =========================================================

class ConfigRoleSelect(discord.ui.RoleSelect):

    def __init__(self, config_key):
        self.config_key = config_key

        super().__init__(
            placeholder="Selecione o cargo...",
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction):
        if not check_admin(interaction):
            return await interaction.response.send_message(
                "Você precisa ser administrador para alterar configurações.",
                ephemeral=True
            )

        selected = self.values[0]

        await set_config(
            interaction.guild.id,
            self.config_key,
            selected.id
        )

        await registrar_log(
            interaction.guild.id,
            interaction.user.id,
            "config_role_updated",
            {
                "setting": self.config_key,
                "role_id": selected.id
            }
        )

        await interaction.response.send_message(
            f"Configuração atualizada!\n"
            f"**{CONFIG_LABELS[self.config_key]}:** {selected.mention}",
            ephemeral=True
        )


# =========================================================
# 15. SELEÇÃO DO ITEM PARA CONFIGURAR
# =========================================================

class ConfigKeySelect(discord.ui.Select):

    def __init__(self, group_key):
        self.group_key = group_key

        keys = CONFIG_GROUPS[group_key]["keys"]

        options = [
            discord.SelectOption(
                label=CONFIG_LABELS[key],
                value=key,
                description="Clique para selecionar o item."
            )
            for key in keys
        ]

        super().__init__(
            placeholder="O que deseja configurar?",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction):
        if not check_admin(interaction):
            return await interaction.response.send_message(
                "Apenas administradores podem configurar o bot.",
                ephemeral=True
            )

        key = self.values[0]

        view = discord.ui.View(timeout=300)

        if key.endswith("_role_id"):
            view.add_item(ConfigRoleSelect(key))
        else:
            view.add_item(ConfigChannelSelect(key))

        await interaction.response.send_message(
            f"**Configurar: {CONFIG_LABELS[key]}**\n"
            "Selecione a opção abaixo.",
            view=view,
            ephemeral=True
        )


# =========================================================
# 16. SELEÇÃO DA CATEGORIA DE CONFIGURAÇÃO
# =========================================================

class ConfigGroupSelect(discord.ui.Select):

    def __init__(self):
        options = [
            discord.SelectOption(
                label=data["label"],
                value=key
            )
            for key, data in CONFIG_GROUPS.items()
        ]

        super().__init__(
            placeholder="Selecione uma categoria de configuração...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction):
        if not check_admin(interaction):
            return await interaction.response.send_message(
                "Apenas administradores podem configurar o bot.",
                ephemeral=True
            )

        group_key = self.values[0]

        view = discord.ui.View(timeout=300)
        view.add_item(ConfigKeySelect(group_key))

        await interaction.response.send_message(
            f"**{CONFIG_GROUPS[group_key]['label']}**\n"
            "Selecione o item que deseja configurar.",
            view=view,
            ephemeral=True
        )


# =========================================================
# 17. PAINEL DE CONFIGURAÇÃO
# =========================================================

class ConfigPanelView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(ConfigGroupSelect())

# =========================================================
# 18. ABERTURA E CONTROLE DE TICKETS
# =========================================================

async def criar_ticket(guild, member, category):
    config = await get_config(guild.id)

    category_id = config.get("ticket_category_id")
    category_channel = guild.get_channel(int(category_id)) if category_id else None

    if not isinstance(category_channel, discord.CategoryChannel):
        raise ValueError("A categoria de tickets não está configurada corretamente.")

    async with db_pool.acquire() as conn:
        existing = await conn.fetchrow("""
            SELECT channel_id
            FROM tickets
            WHERE guild_id = $1
              AND opener_id = $2
              AND status = 'open'
        """, guild.id, member.id)

    if existing:
        existing_channel = guild.get_channel(existing["channel_id"])
        if existing_channel:
            raise ValueError(
                f"Você já possui um ticket aberto: {existing_channel.mention}"
            )

    number = await next_ticket_number(guild.id)
    ticket_name = gerar_nome_ticket(category, number)

    staff_role_id = config.get("staff_role_id")
    staff_role = guild.get_role(int(staff_role_id)) if staff_role_id else None

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False
        ),
        member: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True
        )
    }

    if staff_role:
        overwrites[staff_role] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_messages=True
        )

    channel = await guild.create_text_channel(
        name=ticket_name,
        category=category_channel,
        overwrites=overwrites,
        reason=f"Ticket aberto por {member}"
    )

    try:
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO tickets (
                    ticket_number,
                    guild_id,
                    channel_id,
                    opener_id,
                    category,
                    opened_at,
                    status
                )
                VALUES ($1, $2, $3, $4, $5, NOW(), 'open')
            """, number, guild.id, channel.id, member.id, category)

    except Exception:
        await channel.delete(reason="Falha ao registrar ticket no banco.")
        raise

    embed = criar_embed(
        f"Ticket #{number:04d}",
        f"Olá {member.mention}!\n\n"
        f"**Categoria:** {category}\n"
        "Explique detalhadamente como a equipe pode ajudar."
    )

    embed.add_field(
        name="Responsável",
        value="Aguardando atendimento",
        inline=False
    )

    await channel.send(
        content=member.mention,
        embed=embed,
        view=TicketControlView()
    )

    await enviar_log(
        guild,
        "log_ticket_channel_id",
        "Ticket aberto",
        f"**Canal:** {channel.mention}\n"
        f"**Membro:** {member.mention}\n"
        f"**Número:** #{number:04d}"
    )

    return channel


# =========================================================
# 19. PAINEL DE ABERTURA DE TICKETS
# =========================================================

class TicketTypeSelect(discord.ui.Select):

    def __init__(self):
        options = [
            discord.SelectOption(
                label=label,
                value=value
            )
            for label, value in TICKET_TYPES
        ]

        super().__init__(
            placeholder="Selecione o motivo do atendimento...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction):
        if interaction.guild is None:
            return await interaction.response.send_message(
                "Este painel só funciona dentro de um servidor.",
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        try:
            channel = await criar_ticket(
                interaction.guild,
                interaction.user,
                self.values[0]
            )

            await interaction.followup.send(
                f"Ticket criado: {channel.mention}",
                ephemeral=True
            )

        except ValueError as error:
            await interaction.followup.send(
                str(error),
                ephemeral=True
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "Não tenho permissão para criar o canal. Verifique minhas permissões e a posição dos cargos.",
                ephemeral=True
            )

        except Exception:
            await interaction.followup.send(
                "Não foi possível criar seu ticket. Tente novamente mais tarde.",
                ephemeral=True
            )
            raise


class TicketPanelView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketTypeSelect())


# =========================================================
# 20. TRANSCRIPT DO TICKET
# =========================================================

async def gerar_transcript(channel):
    messages = []

    async for message in channel.history(
        limit=None,
        oldest_first=True
    ):
        timestamp = message.created_at.strftime("%d/%m/%Y %H:%M:%S")

        content = message.clean_content or "[Sem texto]"

        if message.attachments:
            content += "\nAnexos: " + ", ".join(
                attachment.url for attachment in message.attachments
            )

        if message.embeds:
            content += "\n[Mensagem contém embed]"

        messages.append(
            f"[{timestamp}] {message.author} ({message.author.id}):\n{content}"
        )

    transcript = "\n\n".join(messages)

    return discord.File(
        io.BytesIO(transcript.encode("utf-8")),
        filename=f"transcript-{channel.id}.txt"
    )


# =========================================================
# 21. FECHAMENTO DE TICKETS
# =========================================================

async def fechar_ticket(channel, closer, reason="Sem motivo informado"):
    async with db_pool.acquire() as conn:
        ticket = await conn.fetchrow("""
            SELECT *
            FROM tickets
            WHERE channel_id = $1
              AND guild_id = $2
              AND status = 'open'
        """, channel.id, channel.guild.id)

    if not ticket:
        raise ValueError("Este canal não possui um ticket aberto registrado.")

    transcript_file = await gerar_transcript(channel)

    config = await get_config(channel.guild.id)

    transcript_channel_id = config.get("transcript_channel_id")
    transcript_channel = (
        channel.guild.get_channel(int(transcript_channel_id))
        if transcript_channel_id else None
    )

    if transcript_channel:
        try:
            await transcript_channel.send(
                content=(
                    f"Transcript do ticket **#{ticket['ticket_number']:04d}**\n"
                    f"**Autor:** <@{ticket['opener_id']}>\n"
                    f"**Fechado por:** {closer.mention}\n"
                    f"**Motivo:** {reason}"
                ),
                file=transcript_file
            )
        except discord.HTTPException:
            pass

    async with db_pool.acquire() as conn:
        await conn.execute("""
            UPDATE tickets
            SET status = 'closed',
                closed_at = NOW(),
                closer_id = $1,
                close_reason = $2
            WHERE channel_id = $3
              AND guild_id = $4
        """, closer.id, reason, channel.id, channel.guild.id)

    await enviar_log(
        channel.guild,
        "log_ticket_channel_id",
        "Ticket fechado",
        f"**Número:** #{ticket['ticket_number']:04d}\n"
        f"**Autor:** <@{ticket['opener_id']}>\n"
        f"**Responsável:** {closer.mention}\n"
        f"**Motivo:** {reason}"
    )

    await channel.delete(
        reason=f"Ticket fechado por {closer}: {reason}"
    )


# =========================================================
# 22. BOTÕES DE CONTROLE DOS TICKETS
# =========================================================

class TicketCloseModal(discord.ui.Modal, title="Fechar ticket"):

    reason = discord.ui.TextInput(
        label="Motivo do fechamento",
        placeholder="Informe o motivo...",
        required=True,
        max_length=500
    )

    async def on_submit(self, interaction):
        if not await membro_equipe(interaction.user):
            return await interaction.response.send_message(
                "Somente a equipe pode fechar este ticket.",
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        try:
            await fechar_ticket(
                interaction.channel,
                interaction.user,
                str(self.reason)
            )
            await interaction.followup.send(
                "Ticket fechado.",
                ephemeral=True
            )
        except Exception:
            await interaction.followup.send(
                "Não foi possível fechar o ticket.",
                ephemeral=True
            )
            raise


class TicketControlView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Assumir",
        emoji="🙋",
        style=discord.ButtonStyle.primary,
        custom_id="ticket:claim"
    )
    async def claim(self, interaction, button):
        if not await membro_equipe(interaction.user):
            return await interaction.response.send_message(
                "Você não faz parte da equipe.",
                ephemeral=True
            )

        async with db_pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE tickets
                SET claimed_by = $1,
                    claimed_at = NOW()
                WHERE channel_id = $2
                  AND guild_id = $3
                  AND status = 'open'
                  AND claimed_by IS NULL
            """, interaction.user.id, interaction.channel.id, interaction.guild.id)

        if result.endswith("0"):
            return await interaction.response.send_message(
                "Este ticket já foi assumido ou não está registrado.",
                ephemeral=True
            )

        await registrar_atividade_staff(
            interaction.guild.id,
            interaction.user.id,
            "ticket_claimed",
            {"channel_id": interaction.channel.id}
        )

        await interaction.response.send_message(
            f"Ticket assumido por {interaction.user.mention}."
        )

    @discord.ui.button(
        label="Liberar",
        emoji="🔓",
        style=discord.ButtonStyle.secondary,
        custom_id="ticket:release"
    )
    async def release(self, interaction, button):
        if not await membro_equipe(interaction.user):
            return await interaction.response.send_message(
                "Você não faz parte da equipe.",
                ephemeral=True
            )

        async with db_pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE tickets
                SET claimed_by = NULL,
                    claimed_at = NULL
                WHERE channel_id = $1
                  AND guild_id = $2
                  AND status = 'open'
                  AND claimed_by = $3
            """, interaction.channel.id, interaction.guild.id, interaction.user.id)

        if result.endswith("0"):
            return await interaction.response.send_message(
                "Você não assumiu este ticket.",
                ephemeral=True
            )

        await interaction.response.send_message(
            "Ticket liberado."
        )

    @discord.ui.button(
        label="Fechar",
        emoji="🔒",
        style=discord.ButtonStyle.danger,
        custom_id="ticket:close"
    )
    async def close(self, interaction, button):
        if not await membro_equipe(interaction.user):
            return await interaction.response.send_message(
                "Somente a equipe pode fechar tickets.",
                ephemeral=True
            )

        await interaction.response.send_modal(TicketCloseModal())


# =========================================================
# 23. SISTEMA DE PARCERIAS
# =========================================================

def validar_convite(link):
    link = link.strip()

    padrao = r"^(https?://)?(www\.)?(discord\.gg|discord\.com/invite)/[A-Za-z0-9-]+/?$"

    return bool(re.match(padrao, link, re.IGNORECASE))


async def solicitar_parceria(
    guild,
    applicant,
    server_name,
    invite_link,
    description
):
    if not validar_convite(invite_link):
        raise ValueError("O convite informado não parece ser válido.")

    async with db_pool.acquire() as conn:
        existing = await conn.fetchrow("""
            SELECT id
            FROM partnerships
            WHERE guild_id = $1
              AND applicant_id = $2
              AND status = 'pending'
        """, guild.id, applicant.id)

        if existing:
            raise ValueError("Você já possui uma parceria aguardando análise.")

        partnership_id = await conn.fetchval("""
            INSERT INTO partnerships (
                guild_id,
                applicant_id,
                server_name,
                invite_link,
                description,
                status
            )
            VALUES ($1, $2, $3, $4, $5, 'pending')
            RETURNING id
        """,
            guild.id,
            applicant.id,
            server_name,
            invite_link,
            description
        )

    config = await get_config(guild.id)

    category_id = config.get("partnership_category_id")
    category = guild.get_channel(int(category_id)) if category_id else None

    if not isinstance(category, discord.CategoryChannel):
        raise ValueError("A categoria de parcerias não está configurada.")

    staff_role_id = config.get("partnership_role_id") or config.get("staff_role_id")
    staff_role = guild.get_role(int(staff_role_id)) if staff_role_id else None

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        applicant: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True
        )
    }

    if staff_role:
        overwrites[staff_role] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True
        )

    channel = await guild.create_text_channel(
        name=f"parceria-{partnership_id}",
        category=category,
        overwrites=overwrites
    )

    embed = criar_embed(
        f"Solicitação de parceria #{partnership_id}",
        f"**Servidor:** {server_name}\n"
        f"**Convite:** {invite_link}\n"
        f"**Descrição:** {description or 'Não informada'}\n"
        f"**Solicitante:** {applicant.mention}"
    )

    await channel.send(
        content=staff_role.mention if staff_role else None,
        embed=embed,
        view=PartnershipReviewView(partnership_id)
    )

    return channel


class PartnershipReviewView(discord.ui.View):

    def __init__(self, partnership_id):
        super().__init__(timeout=None)
        self.partnership_id = partnership_id

        self.add_item(PartnershipReviewButton(
            partnership_id,
            "approve"
        ))
        self.add_item(PartnershipReviewButton(
            partnership_id,
            "deny"
        ))


class PartnershipReviewButton(discord.ui.Button):

    def __init__(self, partnership_id, action):
        self.partnership_id = partnership_id
        self.action = action

        if action == "approve":
            label = "Aprovar"
            style = discord.ButtonStyle.success
            emoji = "✅"
        else:
            label = "Recusar"
            style = discord.ButtonStyle.danger
            emoji = "❌"

        super().__init__(
            label=label,
            style=style,
            emoji=emoji,
            custom_id=f"partnership:{action}:{partnership_id}"
        )

    async def callback(self, interaction):
        if not await membro_equipe(interaction.user):
            return await interaction.response.send_message(
                "Você não tem permissão para analisar parcerias.",
                ephemeral=True
            )

        async with db_pool.acquire() as conn:
            partnership = await conn.fetchrow("""
                SELECT *
                FROM partnerships
                WHERE id = $1
                  AND guild_id = $2
                  AND status = 'pending'
            """, self.partnership_id, interaction.guild.id)

        if not partnership:
            return await interaction.response.send_message(
                "Esta solicitação já foi analisada ou não existe.",
                ephemeral=True
            )

        if self.action == "approve":
            config = await get_config(interaction.guild.id)
            destination_id = config.get("partnership_channel_id")
            destination = (
                interaction.guild.get_channel(int(destination_id))
                if destination_id else None
            )

            if destination is None:
                return await interaction.response.send_message(
                    "Configure primeiro o canal de publicação de parcerias.",
                    ephemeral=True
                )

            embed = criar_embed(
                f"🤝 {partnership['server_name']}",
                f"{partnership['description'] or 'Nova parceria!'}\n\n"
                f"**Convite:** {partnership['invite_link']}"
            )

            message = await destination.send(embed=embed)

            published_message_id = message.id
            new_status = "approved"

        else:
            published_message_id = None
            new_status = "denied"

        async with db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE partnerships
                SET status = $1,
                    reviewed_by = $2,
                    reviewed_at = NOW(),
                    published_message_id = $3
                WHERE id = $4
                  AND guild_id = $5
                  AND status = 'pending'
            """,
                new_status,
                interaction.user.id,
                published_message_id,
                self.partnership_id,
                interaction.guild.id
            )

        await interaction.response.send_message(
            f"Solicitação {('aprovada' if self.action == 'approve' else 'recusada')}."
        )

        await registrar_log(
            interaction.guild.id,
            interaction.user.id,
            "partnership_reviewed",
            {
                "partnership_id": self.partnership_id,
                "status": new_status
            }
        )


# =========================================================
# 24. CRIAÇÃO DOS CARGOS DO SISTEMA
# =========================================================

async def cria
r_cargo_sistema(guild, role_name):
    existing = discord.utils.get(guild.roles, name=role_name)

    if existing:
        return existing, False

    colour = ROLE_COLORS.get(
        role_name,
        discord.Colour.default()
    )

    role = await guild.create_role(
        name=role_name,
        colour=colour,
        permissions=discord.Permissions.none(),
        reason="Criação dos cargos do sistema"
    )

    return role, True


async def criar_grupo_cargos(guild, group_key):
    if group_key not in ROLE_GROUPS:
        raise ValueError("Grupo de cargos inválido.")

    created = []
    existing = []

    for role_name in ROLE_GROUPS[group_key]["roles"]:
        role, was_created = await criar_cargo_sistema(
            guild,
            role_name
        )

        if was_created:
            created.append(role)
        else:
            existing.append(role)

        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO role_creation_history (
                    guild_id,
                    role_id,
                    role_name,
                    created_by
                )
                VALUES ($1, $2, $3, NULL)
            """, guild.id, role.id, role.name)

    return created, existing


async def criar_todos_cargos(guild):
    created = []
    existing = []

    for group_key in ROLE_GROUPS:
        new_roles, old_roles = await criar_grupo_cargos(
            guild,
            group_key
        )

        created.extend(new_roles)
        existing.extend(old_roles)

    return created, existing


# =========================================================
# 25. AUTOROLE PARA CONTAS DE BOT
# =========================================================

async def aplicar_autorole_bot(member):
    if not member.bot:
        return

    config = await get_config(member.guild.id)
    role_id = config.get("bot_autorole_id")

    if not role_id:
        return

    role = member.guild.get_role(int(role_id))

    if role is None or role in member.roles:
        return

    bot_member = member.guild.me

    if not bot_member.guild_permissions.manage_roles:
        return

    if role >= bot_member.top_role:
        return

    try:
        await member.add_roles(
            role,
            reason="Cargo automático para bots"
        )

        await enviar_log(
            member.guild,
            "log_bot_channel_id",
            "Cargo automático aplicado",
            f"**Bot:** {member.mention}\n"
            f"**Cargo:** {role.mention}"
        )

    except discord.HTTPException:
        pass

# =========================================================
# 26. LISTA DINÂMICA DA EQUIPE
# =========================================================

async def atualizar_lista_equipe(guild: discord.Guild):
    channel_id = await get_config(guild.id, "staff_list_channel_id")
    if not channel_id:
        return

    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, discord.TextChannel):
        return

    staff_role_ids = set()

    for key in (
        "staff_role_id",
        "admin_role_id",
        "director_role_id",
        "moderator_role_id",
        "support_role_id",
    ):
        value = await get_config(guild.id, key)
        if value:
            staff_role_ids.add(int(value))

    for group in ROLE_GROUPS.values():
        for role_name in group:
            role = discord.utils.get(guild.roles, name=role_name)
            if role and role_name in (
                "Diretor Geral", "Bot Manager", "Server Manager",
                "Admin", "Admin Jr", "Mod", "Mod Jr",
                "Suporte", "Suporte Jr", "Criador de Eventos",
                "Designer"
            ):
                staff_role_ids.add(role.id)

    membros = []

    for member in guild.members:
        cargos = [
            role.mention for role in member.roles
            if role.id in staff_role_ids
        ]

        if cargos:
            membros.append((member, cargos))

    embed = discord.Embed(
        title="Equipe do servidor",
        description="Lista atualizada automaticamente.",
        color=EMBED_COLOR
    )

    if not membros:
        embed.description = "Nenhum membro da equipe encontrado."
    else:
        for member, cargos in membros[:40]:
            embed.add_field(
                name=member.display_name,
                value=" ".join(cargos),
                inline=False
            )

    message_id = await get_config(guild.id, "staff_list_message_id")

    if message_id:
        try:
            message = await channel.fetch_message(int(message_id))
            await message.edit(embed=embed)
            return
        except discord.NotFound:
            pass
        except discord.HTTPException:
            pass

    message = await channel.send(embed=embed)
    await set_config(
        guild.id,
        "staff_list_message_id",
        str(message.id)
    )


# =========================================================
# 27. COMANDOS DE CONFIGURAÇÃO
# =========================================================

@bot.tree.command(
    name="configurar",
    description="Abre o painel de configuração do bot."
)
@app_commands.guild_only()
async def configurar(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_guild:
        return await interaction.response.send_message(
            "Você precisa da permissão Gerenciar servidor.",
            ephemeral=True
        )

    await interaction.response.send_message(
        "Painel de configuração:",
        view=ConfigPanelView(),
        ephemeral=True
    )


@bot.tree.command(
    name="painel-tickets",
    description="Publica o painel de abertura de tickets."
)
@app_commands.guild_only()
async def painel_tickets(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_guild:
        return await interaction.response.send_message(
            "Você precisa da permissão Gerenciar servidor.",
            ephemeral=True
        )

    await interaction.response.send_message(
        "Painel de tickets publicado.",
        ephemeral=True
    )

    await interaction.channel.send(
        embed=discord.Embed(
            title="Central de atendimento",
            description="Selecione abaixo o assunto do seu atendimento.",
            color=EMBED_COLOR
        ),
        view=TicketPanelView()
    )

    await set_config(
        interaction.guild.id,
        "ticket_panel_channel_id",
        str(interaction.channel.id)
    )


# =========================================================
# 28. CONFIGURAÇÃO E CRIAÇÃO DE CARGOS
# =========================================================

@bot.tree.command(
    name="configurar-cargos",
    description="Cria os cargos padrão do servidor."
)
@app_commands.guild_only()
@app_commands.describe(
    grupo="Escolha quais cargos deseja criar."
)
@app_commands.choices(grupo=[
    app_commands.Choice(name="Todos os cargos", value="todos"),
    app_commands.Choice(name="Direção e gerenciamento", value="direcao"),
    app_commands.Choice(name="Administração", value="administracao"),
    app_commands.Choice(name="Moderação", value="moderacao"),
    app_commands.Choice(name="Suporte", value="suporte"),
    app_commands.Choice(name="Criatividade", value="criatividade"),
    app_commands.Choice(name="Membros e comunidade", value="membros"),
])
async def configurar_cargos(
    interaction: discord.Interaction,
    grupo: app_commands.Choice[str]
):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message(
            "Você precisa da permissão Gerenciar cargos.",
            ephemeral=True
        )

    await interaction.response.defer(ephemeral=True)

    grupos = {
        "direcao": ["Diretor Geral", "Bot Manager", "Server Manager"],
        "administracao": ["Admin", "Admin Jr"],
        "moderacao": ["Mod", "Mod Jr"],
        "suporte": ["Suporte", "Suporte Jr"],
        "criatividade": ["Criador de Eventos", "Designer"],
        "membros": [
            "Super ativo", "Iniciante", "Vip", "Parceiro",
            "Apoiador", "Membro Antigo", "Verificado"
        ]
    }

    if grupo.value == "todos":
        criados = await criar_todos_cargos(interaction.guild)
    else:
        criados = await criar_grupo_cargos(
            interaction.guild,
            grupos[grupo.value]
        )

    await interaction.followup.send(
        f"Processo concluído. {criados} cargo(s) criado(s).",
        ephemeral=True
    )


# =========================================================
# 29. COMANDO PARA SOLICITAR PARCERIA
# =========================================================

@bot.tree.command(
    name="solicitar-parceria",
    description="Envia uma solicitação de parceria para a equipe."
)
@app_commands.guild_only()
@app_commands.describe(
    nome="Nome do servidor",
    convite="Convite permanente do Discord",
    descricao="Descrição breve do servidor"
)
async def comando_solicitar_parceria(
    interaction: discord.Interaction,
    nome: str,
    convite: str,
    descricao: str
):
    await interaction.response.defer(ephemeral=True)

    resultado = await solicitar_parceria(
        interaction.guild,
        interaction.user,
        nome,
        convite,
        descricao
    )

    await interaction.followup.send(
        resultado,
        ephemeral=True
    )


# =========================================================
# 30. COMANDOS DE MODERAÇÃO
# =========================================================

async def registrar_punicao(
    guild_id: int,
    user_id: int,
    moderator_id: int,
    action: str,
    reason: str
):
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO moderation_history
            (guild_id, user_id, moderator_id, action, reason, created_at)
            VALUES ($1, $2, $3, $4, $5, NOW())
            """,
            guild_id,
            user_id,
            moderator_id,
            action,
            reason
        )


@bot.tree.command(name="expulsar", description="Expulsa um membro.")
@app_commands.guild_only()
@app_commands.checks.has_permissions(kick_members=True)
async def expulsar(
    interaction: discord.Interaction,
    membro: discord.Member,
    motivo: str = "Não informado"
):
    if membro.top_role >= interaction.user.top_role:
        return await interaction.response.send_message(
            "Você não pode expulsar alguém com cargo igual ou superior ao seu.",
            ephemeral=True
        )

    await membro.kick(reason=motivo)

    await registrar_punicao(
        interaction.guild.id,
        membro.id,
        interaction.user.id,
        "kick",
        motivo
    )

    await enviar_log(
        interaction.guild,
        "log_punishments_channel_id",
        f"**Expulsão:** {membro.mention}\n"
        f"**Responsável:** {interaction.user.mention}\n"
        f"**Motivo:** {motivo}"
    )

    await interaction.response.send_message(
        f"{membro.mention} foi expulso.",
        ephemeral=True
    )


@bot.tree.command(name="banir", description="Bane um membro.")
@app_commands.guild_only()
@app_commands.checks.has_permissions(ban_members=True)
async def banir(
    interaction: discord.Interaction,
    membro: discord.Member,
    motivo: str = "Não informado"
):
    if membro.top_role >= interaction.user.top_role:
        return await interaction.response.send_message(
            "Você não pode banir alguém com cargo igual ou superior ao seu.",
            ephemeral=True
        )

    await membro.ban(reason=motivo)

    await registrar_punicao(
        interaction.guild.id,
        membro.id,
        interaction.user.id,
        "ban",
        motivo
    )

    await enviar_log(
        interaction.guild,
        "log_punishments_channel_id",
        f"**Banimento:** {membro.mention}\n"
        f"**Responsável:** {interaction.user.mention}\n"
        f"**Motivo:** {motivo}"
    )

    await interaction.response.send_message(
        f"{membro.mention} foi banido.",
        ephemeral=True
    )


@bot.tree.command(name="timeout", description="Aplica um timeout.")
@app_commands.guild_only()
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.describe(
    membro="Membro que receberá o timeout",
    minutos="Duração em minutos",
    motivo="Motivo da punição"
)
async def timeout(
    interaction: discord.Interaction,
    membro: discord.Member,
    minutos: app_commands.Range[int, 1, 40320],
    motivo: str = "Não informado"
):
    if membro.top_role >= interaction.user.top_role:
        return await interaction.response.send_message(
            "Você não pode aplicar timeout em alguém com cargo igual ou superior ao seu.",
            ephemeral=True
        )

    duracao = discord.utils.utcnow() + discord.timedelta(minutes=minutos)
    await membro.timeout(duracao, reason=motivo)

    await registrar_punicao(
        interaction.guild.id,
        membro.id,
        interaction.user.id,
        "timeout",
        motivo
    )

    await enviar_log(
        interaction.guild,
        "log_punishments_channel_id",
        f"**Timeout:** {membro.mention}\n"
        f"**Duração:** {minutos} minuto(s)\n"
        f"**Responsável:** {interaction.user.mention}\n"
        f"**Motivo:** {motivo}"
    )

    await interaction.response.send_message(
        f"Timeout aplicado em {membro.mention} por {minutos} minuto(s).",
        ephemeral=True
    )


@bot.tree.command(name="avisar", description="Registra uma advertência.")
@app_commands.guild_only()
@app_commands.checks.has_permissions(moderate_members=True)
async def avisar(
    interaction: discord.Interaction,
    membro: discord.Member,
    motivo: str
):
    await registrar_punicao(
        interaction.guild.id,
        membro.id,
        interaction.user.id,
        "advertencia",
        motivo
    )

    await enviar_log(
        interaction.guild,
        "log_punishments_channel_id",
        f"**Advertência:** {membro.mention}\n"
        f"**Responsável:** {interaction.user.mention}\n"
        f"**Motivo:** {motivo}"
    )

    await interaction.response.send_message(
        f"Advertência registrada para {membro.mention}.",
        ephemeral=True
    )


@bot.tree.command(
    name="historico-punicoes",
    description="Consulta o histórico de punições de um membro."
)
@app_commands.guild_only()
@app_commands.checks.has_permissions(moderate_members=True)
async def historico_punicoes(
    interaction: discord.Interaction,
    membro: discord.User
):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT action, reason, moderator_id, created_at
            FROM moderation_history
            WHERE guild_id = $1 AND user_id = $2
            ORDER BY created_at DESC
            LIMIT 10
            """,
            interaction.guild.id,
            membro.id
        )

    embed = discord.Embed(
        title=f"Histórico de {membro}",
        color=EMBED_COLOR
    )

    if not rows:
        embed.description = "Nenhuma punição encontrada."
    else:
        for row in rows:
            embed.add_field(
                name=row["action"].upper(),
                value=(
                    f"**Motivo:** {row['reason']}\n"
                    f"**Responsável:** <@{row['moderator_id']}>\n"
                    f"**Data:** {row['created_at'].strftime('%d/%m/%Y %H:%M')}"
                ),
                inline=False
            )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# =========================================================
# 31. EVENTOS DO SERVIDOR
# =========================================================

@bot.event
async def on_member_join(member: discord.Member):
    if member.bot:
        await aplicar_autorole_bot(member)

        await enviar_log(
            member.guild,
            "log_bots_channel_id",
            f"Bot entrou no servidor: {member.mention}"
        )
    else:
        await enviar_log(
            member.guild,
            "log_members_channel_id",
            f"Membro entrou: {member.mention}"
        )

    await atualizar_lista_equipe(member.guild)


@bot.event
async def on_member_remove(member: discord.Member):
    chave = (
        "log_bots_channel_id"
        if member.bot
        else "log_members_channel_id"
    )

    tipo = "Bot saiu" if member.bot else "Membro saiu"

    await enviar_log(
        member.guild,
        chave,
        f"{tipo}: **{member}** (`{member.id}`)"
    )

    await atualizar_lista_equipe(member.guild)


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if before.nick != after.nick:
        await enviar_log(
            after.guild,
            "log_members_channel_id",
            f"**Apelido alterado:** {after.mention}\n"
            f"Antes: `{before.nick or before.name}`\n"
            f"Depois: `{after.nick or after.name}`"
        )

    antes = {role.id for role in before.roles}
    depois = {role.id for role in after.roles}

    adicionados = depois - antes
    removidos = antes - depois

    if adicionados or removidos:
        texto = []

        for role_id in adicionados:
            role = after.guild.get_role(role_id)
            if role:
                texto.append(f"Cargo adicionado: {role.mention}")

        for role_id in removidos:
            role = after.guild.get_role(role_id)
            if role:
                texto.append(f"Cargo removido: {role.name}")

        await enviar_log(
            after.guild,
            "log_roles_channel_id",
            f"**Alteração de cargos em {after.mention}**\n"
            + "\n".join(texto)
        )

        await atualizar_lista_equipe(after.guild)


@bot.event
async def on_guild_role_create(role: discord.Role):
    await enviar_log(
        role.guild,
        "log_roles_channel_id",
        f"Cargo criado: {role.mention}"
    )


@bot.event
async def on_guild_role_delete(role: discord.Role):
    await enviar_log(
        role.guild,
        "log_roles_channel_id",
        f"Cargo excluído: **{role.name}**"
    )


@bot.event
async def on_guild_role_update(before: discord.Role, after: discord.Role):
    if before.name != after.name or before.permissions != after.permissions:
        await enviar_log(
            after.guild,
            "log_roles_channel_id",
            f"Cargo atualizado: {before.name} → {after.name}"
        )


@bot.event
async def on_guild_channel_create(channel):
    if channel.guild:
        await enviar_log(
            channel.guild,
            "log_server_channel_id",
            f"Canal criado: {channel.mention}"
        )


@bot.event
async def on_guild_channel_delete(channel):
    if channel.guild:
        await enviar_log(
            channel.guild,
            "log_server_channel_id",
            f"Canal excluído: **{channel.name}**"
        )


# =========================================================
# 32. TRATAMENTO DE ERROS DOS COMANDOS
# =========================================================

@bot.tree.error
async def tratar_erro_comando(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):
    if isinstance(error, app_commands.MissingPermissions):
        mensagem = "Você não possui permissão para usar esse comando."
    elif isinstance(error, app_commands.BotMissingPermissions):
        mensagem = "O bot não possui as permissões necessárias."
    elif isinstance(error, app_commands.CommandOnCooldown):
        mensagem = "Aguarde um pouco antes de usar esse comando novamente."
    else:
        print(f"Erro em comando slash: {repr(error)}")
        mensagem = "Ocorreu um erro ao executar o comando."

    if interaction.response.is_done():
        await interaction.followup.send(
            mensagem,
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            mensagem,
            ephemeral=True
        )


# =========================================================
# 33. BOT E INICIALIZAÇÃO
# =========================================================

class TicketBot(commands.Bot):
    async def setup_hook(self):
        await connect_database()

        # Views persistentes
        self.add_view(TicketControlView())
        self.add_view(TicketPanelView())

        # Recupera os painéis de análise de parceria pendentes
        async with db_pool.acquire() as conn:
            pendentes = await conn.fetch(
                "SELECT id FROM partnerships WHERE status = 'pending'"
            )

        for parceria in pendentes:
            self.add_view(
                PartnershipReviewView(parceria["id"])
            )

        await self.tree.sync()

        print("Banco de dados conectado.")
        print("Views persistentes carregadas.")
        print("Comandos slash sincronizados.")

    async def close(self):
        global db_pool

        if db_pool is not None:
            await db_pool.close()
            db_pool = None

        await super().close()


bot = TicketBot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None
)


@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")

    for guild in bot.guilds:
        try:
            await atualizar_lista_equipe(guild)
        except Exception as error:
            print(
                f"Erro ao atualizar equipe de {guild.name}: {error}"
            )


# =========================================================
# 34. EXECUÇÃO
# =========================================================

if __name__ == "__main__":
    bot.run(TOKEN)
        
