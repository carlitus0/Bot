import os
import io
import html
import re
import unicodedata
import asyncio
from datetime import datetime, timezone

import discord
from discord.ext import commands
from discord import app_commands
import asyncpg


# ==========================================
# CONFIGURAÇÕES GERAIS
# ==========================================

TOKEN = os.getenv("DISCORD_TOKEN")
DB_PASSWORD = os.getenv("SUPABASE_DB_PASSWORD")

PREFIX = "!"

EMBED_COLOR = discord.Colour.from_rgb(128, 128, 128)

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

db_pool = None


# ==========================================
# TIPOS DE TICKETS
# ==========================================

TICKET_TYPES = [
    ("🚨 Denunciar membro", "denuncia"),
    ("👥 Entrar em contato com a equipe", "equipe"),
    ("🤝 Solicitar parceria", "parceria"),
    ("⚖️ Solicitar revisão de punição", "revisao"),
    ("❓ Dúvidas", "duvidas"),
    ("🛠️ Suporte geral", "suporte"),
    ("🐛 Relatar bug ou erro", "bug"),
]


# ==========================================
# CONFIGURAÇÕES PADRÃO DO PAINEL
# ==========================================

DEFAULT_CONFIG = {
    "ticket_category_id": None,
    "transcript_channel_id": None,
    "staff_role_id": None,
    "ticket_panel_channel_id": None,

    "partnership_category_id": None,
    "partnership_channel_id": None,

    "staff_chat_channel_id": None,
    "staff_announcements_channel_id": None,
    "staff_information_channel_id": None,
    "staff_proofs_channel_id": None,
    "staff_meetings_channel_id": None,
    "staff_support_channel_id": None,
    "staff_changelog_channel_id": None,
    "staff_punishment_channel_id": None,
    "staff_list_channel_id": None,

    "admin_owner_chat_channel_id": None,
    "admin_director_chat_channel_id": None,
    "admin_announcements_channel_id": None,
    "admin_planning_channel_id": None,
    "admin_team_channel_id": None,
    "admin_appeals_channel_id": None,
    "admin_settings_channel_id": None,
    "admin_reports_channel_id": None,

    "log_ticket_channel_id": None,
    "log_partnership_channel_id": None,
    "log_moderation_channel_id": None,
    "log_staff_channel_id": None,
    "log_admin_channel_id": None,

    "admin_role_id": None,
    "director_role_id": None,
    "moderator_role_id": None,
    "support_role_id": None,
    "partnership_role_id": None,
}


# ==========================================
# BANCO DE DADOS
# ==========================================

async def connect_database():
    global db_pool

    if not DB_PASSWORD:
        raise RuntimeError(
            "A variável SUPABASE_DB_PASSWORD não foi configurada."
        )

    db_pool = await asyncpg.create_pool(
        host="aws-0-us-west-2.pooler.supabase.com",
        port=5432,
        database="postgres",
        user="postgres.sdtivbtxtujgdizxyhed",
        password=DB_PASSWORD,
        ssl="require",
        min_size=1,
        max_size=5
    )

    async with db_pool.acquire() as conn:

        # Configurações por servidor
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_config (
                guild_id BIGINT PRIMARY KEY,
                settings JSONB NOT NULL DEFAULT '{}'::jsonb,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # Contador de tickets
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ticket_counter (
                id INTEGER PRIMARY KEY,
                last_number BIGINT NOT NULL DEFAULT 0
            )
        """)

        await conn.execute("""
            INSERT INTO ticket_counter (id, last_number)
            VALUES (1, 0)
            ON CONFLICT (id) DO NOTHING
        """)

        # Tickets existentes
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
                status TEXT NOT NULL DEFAULT 'open'
            )
        """)

        # Responsáveis pelos tickets
        await conn.execute("""
            ALTER TABLE tickets
            ADD COLUMN IF NOT EXISTS claimed_by BIGINT
        """)

        await conn.execute("""
            ALTER TABLE tickets
            ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ
        """)

        # Histórico de ações
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

        # Parcerias
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
                reviewed_at TIMESTAMPTZ
            )
        """)

    print("Conexão com Supabase estabelecida.", flush=True)


# ==========================================
# CONFIGURAÇÕES DO SERVIDOR
# ==========================================

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
            import json
            saved = json.loads(saved)

        settings.update(saved)

    return settings


async def set_config(guild_id, key, value):
    import json

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


async def registrar_log(guild_id, actor_id, action, details=None):
    import json

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
            json.dumps(details or {}, ensure_ascii=False)
        )


# ==========================================
# FUNÇÕES AUXILIARES
# ==========================================

def gerar_nome_ticket(categoria, numero):
    nome = unicodedata.normalize("NFKD", categoria)
    nome = nome.encode("ascii", "ignore").decode("ascii")
    nome = nome.lower()
    nome = re.sub(r"[^a-z0-9]+", "-", nome).strip("-")

    return f"{nome}-{numero:04d}"


def is_admin(member):
    return member.guild_permissions.administrator


async def next_ticket_number():
    async with db_pool.acquire() as conn:
        return await conn.fetchval("""
            UPDATE ticket_counter
            SET last_number = last_number + 1
            WHERE id = 1
            RETURNING last_number
        """)


async def save_ticket(
    number,
    guild_id,
    channel_id,
    opener_id,
    category
):
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
            VALUES ($1, $2, $3, $4, $5, $6, 'open')
        """,
            number,
            guild_id,
            channel_id,
            opener_id,
            category,
            datetime.now(timezone.utc)
        )


async def get_open_ticket(user_id, guild_id):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("""
            SELECT *
            FROM tickets
            WHERE opener_id = $1
              AND guild_id = $2
              AND status = 'open'
        """, user_id, guild_id)


async def get_ticket(channel_id):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("""
            SELECT *
            FROM tickets
            WHERE channel_id = $1
              AND status = 'open'
        """, channel_id)


async def claim_ticket_db(channel_id, staff_id):
    async with db_pool.acquire() as conn:
        return await conn.fetchval("""
            UPDATE tickets
            SET claimed_by = $1,
                claimed_at = NOW()
            WHERE channel_id = $2
              AND status = 'open'
              AND claimed_by IS NULL
            RETURNING ticket_number
        """, staff_id, channel_id)


async def release_ticket_db(channel_id):
    async with db_pool.acquire() as conn:
        return await conn.fetchval("""
            UPDATE tickets
            SET claimed_by = NULL,
                claimed_at = NULL
            WHERE channel_id = $1
              AND status = 'open'
            RETURNING ticket_number
        """, channel_id)


async def close_ticket_db(number, closer_id, reason):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            UPDATE tickets
            SET status = 'closed',
                closed_at = $1,
                closer_id = $2,
                close_reason = $3
            WHERE ticket_number = $4
        """,
            datetime.now(timezone.utc),
            closer_id,
            reason,
            number
)

# ==========================================
# GRUPOS DE CONFIGURAÇÃO
# ==========================================

CONFIG_GROUPS = {
    "tickets": {
        "label": "🎫 Tickets",
        "keys": [
            "ticket_category_id",
            "transcript_channel_id",
            "staff_role_id",
            "ticket_panel_channel_id",
            "log_ticket_channel_id",
        ]
    },
    "partnerships": {
        "label": "🤝 Parcerias",
        "keys": [
            "partnership_category_id",
            "partnership_channel_id",
            "partnership_role_id",
            "log_partnership_channel_id",
        ]
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
        ]
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
        ]
    },
    "logs": {
        "label": "📁 Logs",
        "keys": [
            "log_ticket_channel_id",
            "log_partnership_channel_id",
            "log_moderation_channel_id",
            "log_staff_channel_id",
            "log_admin_channel_id",
        ]
    }
}


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
    "admin_settings_channel_id": "Configurações",
    "admin_reports_channel_id": "Relatórios",

    "log_moderation_channel_id": "Logs de moderação",
    "log_staff_channel_id": "Logs da equipe",
    "log_admin_channel_id": "Logs administrativos",

    "admin_role_id": "Cargo Administrador",
    "director_role_id": "Cargo Diretoria",
    "moderator_role_id": "Cargo Moderador",
    "support_role_id": "Cargo Suporte",
}


# ==========================================
# VALIDAÇÃO DE CONFIGURAÇÕES
# ==========================================

async def get_configured_channel(guild, key):
    config = await get_config(guild.id)
    channel_id = config.get(key)

    if not channel_id:
        return None

    return guild.get_channel(int(channel_id))


async def get_configured_role(guild, key):
    config = await get_config(guild.id)
    role_id = config.get(key)

    if not role_id:
        return None

    return guild.get_role(int(role_id))


def check_admin(interaction):
    return (
        interaction.guild is not None
        and interaction.user.guild_permissions.administrator
    )


# ==========================================
# SELEÇÃO DE CANAIS
# ==========================================

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


# ==========================================
# SELEÇÃO DE CARGOS
# ==========================================

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


# ==========================================
# SELEÇÃO DO ITEM PARA CONFIGURAR
# ==========================================

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


# ==========================================
# SELEÇÃO DA CATEGORIA DE CONFIGURAÇÃO
# ==========================================

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
            "Escolha qual configuração deseja alterar.",
            view=view,
            ephemeral=True
        )


class ConfigMainView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(ConfigGroupSelect())


# ==========================================
# CONSULTAR CONFIGURAÇÕES
# ==========================================

class ConfigStatusView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(
        label="Ver configurações",
        emoji="📋",
        style=discord.ButtonStyle.secondary
    )
    async def show_config(self, interaction, button):
        if not check_admin(interaction):
            return await interaction.response.send_message(
                "Apenas administradores podem consultar as configurações.",
                ephemeral=True
            )

        config = await get_config(interaction.guild.id)

        embed = discord.Embed(
            title="⚙️ Configurações do servidor",
            description="Situação atual das configurações do bot.",
            color=EMBED_COLOR
        )

        for group_key, group in CONFIG_GROUPS.items():
            lines = []

            for key in group["keys"]:
                value = config.get(key)

                if value:
                    if key.endswith("_role_id"):
                        item = interaction.guild.get_role(int(value))
                    else:
                        item = interaction.guild.get_channel(int(value))

                    display = item.mention if item else "ID inválido"
                else:
                    display = "Não configurado"

                lines.append(
                    f"**{CONFIG_LABELS[key]}:** {display}"
                )

            embed.add_field(
                name=group["label"],
                value="\n".join(lines)[:1024],
                inline=False
            )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )


# ==========================================
# TRANSCRIPT HTML
# ==========================================

async def create_transcript(
    channel,
    ticket,
    opener,
    closer,
    reason
):
    messages = []

    async for message in channel.history(
        limit=None,
        oldest_first=True
    ):
        timestamp = message.created_at.strftime(
            "%d/%m/%Y %H:%M:%S"
        )

        content = html.escape(
            message.content or "[Mensagem sem texto]"
        )

        attachments = ""

        if message.attachments:
            attachments = "<br>".join(
                f'<a href="{html.escape(a.url, quote=True)}">'
                f'{html.escape(a.filename)}</a>'
                for a in message.attachments
            )

        embed_text = ""

        for embed in message.embeds:
            if embed.title:
                embed_text += (
                    f"<p><b>{html.escape(embed.title)}</b></p>"
                )

            if embed.description:
                embed_text += (
                    f"<p>{html.escape(embed.description)}</p>"
                )

        messages.append(f"""
            <div class="message">
                <b>{html.escape(str(message.author))}</b>
                <small>{timestamp}</small>
                <p>{content}</p>
                {embed_text}
                <div>{attachments}</div>
            </div>
        """)

    opened_at = ticket["opened_at"].strftime(
        "%d/%m/%Y %H:%M:%S"
    )

    closed_at = datetime.now(timezone.utc).strftime(
        "%d/%m/%Y %H:%M:%S"
    )

    page = f"""
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <title>Ticket {ticket['ticket_number']:04d}</title>
        <style>
            body {{
                background: #202225;
                color: white;
                font-family: Arial, sans-serif;
                padding: 25px;
            }}
            .info, .message {{
                background: #2f3136;
                padding: 15px;
                border-radius: 8px;
                margin-bottom: 12px;
            }}
            small {{
                color: #aaa;
                margin-left: 10px;
            }}
            a {{
                color: #a99aff;
            }}
        </style>
    </head>
    <body>
        <h2>Transcript — {html.escape(channel.name)}</h2>

        <div class="info">
            <p><b>Categoria:</b> {html.escape(ticket['category'])}</p>
            <p><b>Solicitante:</b> {html.escape(str(opener))} ({opener.id})</p>
            <p><b>Fechado por:</b> {html.escape(str(closer))} ({closer.id})</p>
            <p><b>Motivo:</b> {html.escape(reason)}</p>
            <p><b>Aberto em:</b> {opened_at}</p>
            <p><b>Fechado em:</b> {closed_at}</p>
        </div>

        {''.join(messages)}
    </body>
    </html>
    """

    return discord.File(
        io.BytesIO(page.encode("utf-8")),
        filename=f"ticket-{ticket['ticket_number']:04d}.html"
                          )

    
# ==========================================
# PARTE 3/3 — SISTEMA DE TICKETS E INICIALIZAÇÃO
# ==========================================

class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelect())


class TicketSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="Denúncia",
                value="denuncia",
                emoji="🚨",
                description="Denunciar um membro."
            ),
            discord.SelectOption(
                label="Equipe",
                value="equipe",
                emoji="👥",
                description="Assuntos relacionados à equipe."
            ),
            discord.SelectOption(
                label="Parceria",
                value="parceria",
                emoji="🤝",
                description="Solicitar uma parceria."
            ),
            discord.SelectOption(
                label="Revisão",
                value="revisao",
                emoji="⚖️",
                description="Solicitar revisão de uma punição."
            ),
            discord.SelectOption(
                label="Dúvidas",
                value="duvidas",
                emoji="❓",
                description="Tirar dúvidas."
            ),
            discord.SelectOption(
                label="Suporte",
                value="suporte",
                emoji="🛠️",
                description="Solicitar suporte."
            ),
            discord.SelectOption(
                label="Bug",
                value="bug",
                emoji="🐛",
                description="Informar um problema."
            )
        ]

        super().__init__(
            placeholder="Selecione o motivo do atendimento...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="ticket:select"
        )

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        member = interaction.user

        if guild is None:
            return await interaction.response.send_message(
                "Este painel só funciona dentro de um servidor.",
                ephemeral=True
            )

        config = await get_config(guild.id)

        category_id = config.get("ticket_category_id")
        staff_role_id = config.get("staff_role_id")

        if not category_id:
            return await interaction.response.send_message(
                "A categoria de tickets não foi configurada. "
                "Use `/configurar-bot`.",
                ephemeral=True
            )

        category = guild.get_channel(int(category_id))

        if not isinstance(category, discord.CategoryChannel):
            return await interaction.response.send_message(
                "A categoria configurada não existe ou não é uma categoria.",
                ephemeral=True
            )

        staff_role = None

        if staff_role_id:
            staff_role = guild.get_role(int(staff_role_id))

        if staff_role_id and staff_role is None:
            return await interaction.response.send_message(
                "O cargo da equipe configurado não existe mais.",
                ephemeral=True
            )

        existing = await get_open_ticket(member.id, guild.id)

        if existing:
            existing_channel = guild.get_channel(
                int(existing["channel_id"])
            )

            if existing_channel:
                return await interaction.response.send_message(
                    f"Você já possui um ticket aberto: {existing_channel.mention}",
                    ephemeral=True
                )

            # Remove registro antigo caso o canal tenha sido apagado.
            await db_pool.execute(
                "DELETE FROM tickets WHERE channel_id = $1",
                int(existing["channel_id"])
            )

        await interaction.response.defer(ephemeral=True)

        ticket_type = self.values[0]
        ticket_number = await next_ticket_number()
        channel_name = gerar_nome_ticket(ticket_type, ticket_number)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False
            ),
            member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True
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
                manage_channels=True
            )

        try:
            channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                reason=f"Ticket aberto por {member} ({member.id})"
            )

            await db_pool.execute(
                """
                INSERT INTO tickets (
                    ticket_number,
                    guild_id,
                    channel_id,
                    opener_id,
                    category,
                    opened_at,
                    status
                )
                VALUES ($1, $2, $3, $4, $5, $6, 'open')
                """,
                ticket_number,
                guild.id,
                channel.id,
                member.id,
                ticket_type,
                datetime.now(timezone.utc)
            )

            embed = discord.Embed(
                title="🎫 Atendimento aberto",
                description=(
                    f"Olá, {member.mention}!\n\n"
                    f"**Categoria:** {ticket_type.capitalize()}\n"
                    f"**Número:** #{ticket_number:04d}\n\n"
                    "Explique sua solicitação e aguarde "
                    "um membro da equipe."
                ),
                color=EMBED_COLOR
            )

            embed.set_footer(
                text=f"Ticket #{ticket_number:04d}"
            )

            await channel.send(
                content=staff_role.mention if staff_role else None,
                embed=embed,
                view=TicketControlView()
            )

            await registrar_log(
                guild.id,
                member.id,
                "ticket_aberto",
                {
                    "ticket_number": ticket_number,
                    "channel_id": channel.id,
                    "category": ticket_type
                }
            )

            await interaction.followup.send(
                f"Ticket criado: {channel.mention}",
                ephemeral=True
            )

            try:
                await member.send(
                    f"Seu ticket #{ticket_number:04d} foi aberto "
                    f"no servidor **{guild.name}**."
                )
            except discord.Forbidden:
                pass

        except Exception as error:
            print(f"Erro ao criar ticket: {error}")

            await interaction.followup.send(
                "Não foi possível criar o ticket. "
                "Confira as permissões do bot e a configuração.",
                ephemeral=True
            )


class CloseReasonModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Encerrar atendimento")

        self.reason = discord.ui.TextInput(
            label="Motivo do encerramento",
            placeholder="Informe o motivo...",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=500
        )

        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        channel = interaction.channel
        guild = interaction.guild
        member = interaction.user

        if guild is None or not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message(
                "Este comando só funciona em um canal de ticket.",
                ephemeral=True
            )

        ticket = await get_ticket(channel.id)

        if not ticket or ticket["status"] != "open":
            return await interaction.response.send_message(
                "Este canal não possui um ticket aberto.",
                ephemeral=True
            )

        config = await get_config(guild.id)
        staff_role_id = config.get("staff_role_id")

        staff_role = (
            guild.get_role(int(staff_role_id))
            if staff_role_id else None
        )

        is_staff = (
            staff_role is not None
            and staff_role in member.roles
        )

        if not is_staff and not member.guild_permissions.administrator:
            return await interaction.response.send_message(
                "Você não tem permissão para encerrar este ticket.",
                ephemeral=True
            )

        transcript_channel_id = config.get("transcript_channel_id")
        log_channel_id = config.get("log_ticket_channel_id")

        transcript_channel = (
            guild.get_channel(int(transcript_channel_id))
            if transcript_channel_id else None
        )

        log_channel = (
            guild.get_channel(int(log_channel_id))
            if log_channel_id else None
        )

        if not isinstance(transcript_channel, discord.TextChannel):
            return await interaction.response.send_message(
                "Configure um canal de transcripts em `/configurar-bot` "
                "antes de encerrar tickets.",
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        opener = guild.get_member(int(ticket["opener_id"]))

        if opener is None:
            try:
                opener = await bot.fetch_user(int(ticket["opener_id"]))
            except discord.HTTPException:
                opener = None

        reason = str(self.reason.value)

        try:
            transcript = await create_transcript(
                channel,
                ticket,
                opener,
                member,
                reason
            )

            await transcript_channel.send(
                content=(
                    f"📄 Transcript do ticket "
                    f"**#{int(ticket['ticket_number']):04d}**"
                ),
                file=transcript
            )

            await close_ticket_db(
                int(ticket["ticket_number"]),
                member.id,
                reason
            )

            await registrar_log(
                guild.id,
                member.id,
                "ticket_fechado",
                {
                    "ticket_number": int(ticket["ticket_number"]),
                    "channel_id": channel.id,
                    "reason": reason
                }
            )

            if isinstance(log_channel, discord.TextChannel):
                embed = discord.Embed(
                    title="🔒 Ticket encerrado",
                    color=EMBED_COLOR,
                    timestamp=datetime.now(timezone.utc)
                )

                embed.add_field(
                    name="Número",
                    value=f"#{int(ticket['ticket_number']):04d}",
                    inline=True
                )
                embed.add_field(
                    name="Responsável",
                    value=member.mention,
                    inline=True
                )
                embed.add_field(
                    name="Motivo",
                    value=reason[:1024],
                    inline=False
                )

                await log_channel.send(embed=embed)

            if opener:
                try:
                    await opener.send(
                        f"Seu ticket #{int(ticket['ticket_number']):04d} "
                        f"foi encerrado em **{guild.name}**.\n"
                        f"Motivo: {reason}"
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass

            await interaction.followup.send(
                "Atendimento encerrado. O transcript foi enviado aos logs.",
                ephemeral=True
            )

            await channel.delete(
                reason=f"Ticket encerrado por {member}"
            )

        except Exception as error:
            print(f"Erro ao encerrar ticket: {error}")

            await interaction.followup.send(
                "Ocorreu um erro ao encerrar o ticket. "
                "Confira os logs do Railway.",
                ephemeral=True
            )


class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def check_staff(self, interaction: discord.Interaction):
        if not interaction.guild or not interaction.user:
            return False

        config = await get_config(interaction.guild.id)
        role_id = config.get("staff_role_id")

        role = (
            interaction.guild.get_role(int(role_id))
            if role_id else None
        )

        member = interaction.user

        return (
            member.guild_permissions.administrator
            or (role is not None and role in member.roles)
        )

    @discord.ui.button(
        label="Reivindicar ticket",
        emoji="📌",
        style=discord.ButtonStyle.primary,
        custom_id="ticket:claim"
    )
    async def claim(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await self.check_staff(interaction):
            return await interaction.response.send_message(
                "Você não tem permissão para reivindicar tickets.",
                ephemeral=True
            )

        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message(
                "Canal inválido.",
                ephemeral=True
            )

        ticket = await get_ticket(interaction.channel.id)

        if not ticket or ticket["status"] != "open":
            return await interaction.response.send_message(
                "Este ticket não está aberto.",
                ephemeral=True
            )

        claimed = await claim_ticket_db(
            interaction.channel.id,
            interaction.user.id
        )

        if not claimed:
            return await interaction.response.send_message(
                "Este ticket já foi reivindicado por outro membro.",
                ephemeral=True
            )

        await registrar_log(
            interaction.guild.id,
            interaction.user.id,
            "ticket_reivindicado",
            {"channel_id": interaction.channel.id}
        )

        await interaction.response.send_message(
            f"📌 Ticket reivindicado por {interaction.user.mention}."
        )

    @discord.ui.button(
        label="Liberar ticket",
        emoji="🔓",
        style=discord.ButtonStyle.secondary,
        custom_id="ticket:release"
    )
    async def release(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await self.check_staff(interaction):
            return await interaction.response.send_message(
                "Você não tem permissão para liberar tickets.",
                ephemeral=True
            )

        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message(
                "Canal inválido.",
                ephemeral=True
            )

        ticket = await get_ticket(interaction.channel.id)

        if not ticket or ticket["status"] != "open":
            return await interaction.response.send_message(
                "Este ticket não está aberto.",
                ephemeral=True
            )

        claimed_by = ticket["claimed_by"]

        if claimed_by is None:
            return await interaction.response.send_message(
                "Este ticket não está reivindicado.",
                ephemeral=True
            )

        if (
            int(claimed_by) != interaction.user.id
            and not interaction.user.guild_permissions.administrator
        ):
            return await interaction.response.send_message(
                "Somente quem reivindicou ou um administrador "
                "pode liberar este ticket.",
                ephemeral=True
            )

        await release_ticket_db(interaction.channel.id)

        await registrar_log(
            interaction.guild.id,
            interaction.user.id,
            "ticket_liberado",
            {"channel_id": interaction.channel.id}
        )

        await interaction.response.send_message(
            f"🔓 Ticket liberado por {interaction.user.mention}."
        )

    @discord.ui.button(
        label="Encerrar ticket",
        emoji="🔒",
        style=discord.ButtonStyle.danger,
        custom_id="ticket:close"
    )
    async def close(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await self.check_staff(interaction):
            return await interaction.response.send_message(
                "Você não tem permissão para encerrar tickets.",
                ephemeral=True
            )

        await interaction.response.send_modal(CloseReasonModal())


# ==========================================
# BOT E COMANDOS
# ==========================================

class TicketBot(commands.Bot):
    async def setup_hook(self):
        await conectar_db()

        self.add_view(TicketPanelView())
        self.add_view(TicketControlView())

        await self.tree.sync()

        print("Comandos slash sincronizados.")

    async def close(self):
        if db_pool is not None:
            await db_pool.close()

        await super().close()


bot = TicketBot(
    command_prefix=PREFIX,
    intents=intents
)


@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")
    print(f"ID: {bot.user.id}")


# ==========================================
# CONFIGURAÇÃO MANUAL
# ==========================================

@bot.tree.command(
    name="configurar-bot",
    description="Configurar canais, categorias e cargos do bot."
)
@app_commands.default_permissions(administrator=True)
async def configurar_bot(interaction: discord.Interaction):
    if not await check_admin(interaction):
        return await interaction.response.send_message(
            "Você precisa ser administrador.",
            ephemeral=True
        )

    await interaction.response.send_message(
        "⚙️ **Configuração do bot**\n"
        "Selecione abaixo o grupo que deseja configurar.",
        view=ConfigMainView(),
        ephemeral=True
    )


@bot.command(name="configurar-bot")
@commands.has_permissions(administrator=True)
async def configurar_bot_prefix(ctx):
    await ctx.send(
        "⚙️ **Configuração do bot**\n"
        "Selecione abaixo o grupo que deseja configurar.",
        view=ConfigMainView()
    )


# ==========================================
# PAINEL DE TICKETS
# ==========================================

@bot.tree.command(
    name="painel-ticket",
    description="Enviar o painel de abertura de tickets."
)
@app_commands.default_permissions(administrator=True)
async def painel_ticket(interaction: discord.Interaction):
    if not await check_admin(interaction):
        return await interaction.response.send_message(
            "Você precisa ser administrador.",
            ephemeral=True
        )

        config = await get_config(interaction.guild.id)
    panel_id = config.get("ticket_panel_channel_id")

    if not panel_id:
        return await interaction.response.send_message(
            "Configure o canal do painel em `/configurar-bot`.",
            ephemeral=True
        )

    channel = interaction.guild.get_channel(int(panel_id))

    if not isinstance(channel, discord.TextChannel):
        return await interaction.response.send_message(
            "O canal do painel não existe ou não é um canal de texto.",
            ephemeral=True
        )

    embed = discord.Embed(
        title="🎫 CENTRAL DE ATENDIMENTO",
        description=(
            "Precisa de ajuda ou deseja entrar em contato com nossa equipe?\n\n"
            "Selecione uma das opções abaixo para abrir um ticket. "
            "Nossa equipe estará disponível para analisar sua solicitação "
            "e prestar o suporte necessário."
        ),
        color=EMBED_COLOR
    )

    await channel.send(
        embed=embed,
        view=TicketPanelView()
    )

    await interaction.response.send_message(
        f"Painel enviado em {channel.mention}.",
        ephemeral=True
    )


@bot.command(name="painel-ticket")
@commands.has_permissions(administrator=True)
async def painel_ticket_prefix(ctx):
    config = await get_config(ctx.guild.id)
    panel_id = config.get("ticket_panel_channel_id")

    if not panel_id:
        return await ctx.send(
            "Configure o canal do painel em `/configurar-bot`."
        )

    channel = ctx.guild.get_channel(int(panel_id))

    if not isinstance(channel, discord.TextChannel):
        return await ctx.send(
            "O canal configurado não existe ou não é um canal de texto."
        )

    embed = discord.Embed(
        title="🎫 CENTRAL DE ATENDIMENTO",
        description=(
            "Precisa de ajuda ou deseja entrar em contato com nossa equipe?\n\n"
            "Selecione uma das opções abaixo para abrir um ticket. "
            "Nossa equipe estará disponível para analisar sua solicitação "
            "e prestar o suporte necessário."
        ),
        color=EMBED_COLOR
    )

    await channel.send(
        embed=embed,
        view=TicketPanelView()
    )

    await ctx.send(
        f"Painel enviado em {channel.mention}."
    )


# ==========================================
# TRATAMENTO DE ERROS
# ==========================================

@configurar_bot_prefix.error
@painel_ticket_prefix.error
async def prefix_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("Você precisa ser administrador.")
    else:
        print(f"Erro em comando prefixado: {error}")


# ==========================================
# INICIALIZAÇÃO
# ==========================================

if not TOKEN:
    raise RuntimeError(
        "A variável DISCORD_TOKEN não foi configurada no Railway."
    )

if not DB_PASSWORD:
    raise RuntimeError(
        "A variável SUPABASE_DB_PASSWORD não foi configurada no Railway."
    )

bot.run(TOKEN)
