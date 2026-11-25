# sistemas.py
# Extensão administrativa independente para discord.py 2.x / Python 3.13.
# Usa exclusivamente o pool asyncpg já criado pelo main.py ( __main__.db_pool ).

from __future__ import annotations

import asyncio
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands


# ---------------------------------------------------------------------------
# Identidade visual
# ---------------------------------------------------------------------------

PURPLE = discord.Colour.from_rgb(112, 72, 190)
DARK = discord.Colour.from_rgb(27, 25, 33)
WHITE = discord.Colour.from_rgb(245, 243, 250)
GREEN = discord.Colour.from_rgb(67, 181, 129)
RED = discord.Colour.from_rgb(220, 65, 80)
GOLD = discord.Colour.from_rgb(232, 177, 72)
FOOTER = "Central Administrativa • Sistemas"
PUNISHMENTS = {
    "advertencia": "Advertência",
    "timeout": "Timeout",
    "expulsao": "Expulsão",
    "banimento": "Banimento",
}
URL_RE = re.compile(r"^https?://", re.I)


def make_embed(title: str, description: str = "", *,
               colour: discord.Colour = PURPLE,
               timestamp: bool = True) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        colour=colour,
        timestamp=datetime.now(timezone.utc) if timestamp else None,
    )
    embed.set_footer(text=FOOTER)
    return embed


def valid_http_url(value: Optional[str]) -> bool:
    if not value:
        return True
    if len(value) > 500:
        return False
    try:
        parsed = urlparse(value)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except ValueError:
        return False


def clipped(value: object, limit: int = 1024) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def is_admin(member: discord.Member) -> bool:
    return member.guild_permissions.administrator


def can_manage_target(actor: discord.Member, target: discord.Member,
                      bot_member: discord.Member) -> tuple[bool, str]:
    if target.id == actor.id:
        return False, "Você não pode aplicar esta ação em si mesmo."
    if target.id == actor.guild.owner_id:
        return False, "Não é possível moderar o proprietário do servidor."
    if actor.id != actor.guild.owner_id and target.top_role >= actor.top_role:
        return False, "O cargo do membro é igual ou superior ao seu."
    if target.top_role >= bot_member.top_role:
        return False, "O cargo do membro é igual ou superior ao cargo do bot."
    return True, ""


async def send_ephemeral(interaction: discord.Interaction, content: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=True)
    else:
        await interaction.response.send_message(content, ephemeral=True)


# ---------------------------------------------------------------------------
# Modais e views persistentes
# ---------------------------------------------------------------------------

class PunishmentModal(discord.ui.Modal):
    def __init__(self, punishment_type: str):
        super().__init__(title=f"Solicitar {PUNISHMENTS[punishment_type]}")
        self.punishment_type = punishment_type
        self.member_id = discord.ui.TextInput(
            label="ID do membro denunciado",
            placeholder="Ex.: 123456789012345678",
            min_length=17, max_length=20,
        )
        self.reason = discord.ui.TextInput(
            label="Motivo detalhado",
            placeholder="Descreva o ocorrido com contexto suficiente...",
            style=discord.TextStyle.paragraph,
            min_length=5, max_length=1500,
        )
        self.evidence = discord.ui.TextInput(
            label="Link de evidência (opcional)",
            placeholder="https://...",
            required=False, max_length=500,
        )
        self.add_item(self.member_id)
        self.add_item(self.reason)
        self.add_item(self.evidence)

    async def on_submit(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("Sistemas")
        if cog is None:
            return await send_ephemeral(interaction, "Sistema indisponível no momento.")
        if not self.member_id.value.isdigit():
            return await send_ephemeral(interaction, "Informe um ID numérico válido.")
        evidence = self.evidence.value.strip() or None
        if not valid_http_url(evidence):
            return await send_ephemeral(interaction, "O link de evidência precisa ser uma URL HTTP ou HTTPS válida.")
        await cog.create_punishment_request(
            interaction,
            self.punishment_type,
            int(self.member_id.value),
            self.reason.value.strip(),
            evidence,
        )


class PunishmentPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Advertência", emoji="⚠️",
                       style=discord.ButtonStyle.secondary,
                       custom_id="sistemas:punir:advertencia")
    async def warn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PunishmentModal("advertencia"))

    @discord.ui.button(label="Timeout", emoji="🔇",
                       style=discord.ButtonStyle.primary,
                       custom_id="sistemas:punir:timeout")
    async def timeout(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PunishmentModal("timeout"))

    @discord.ui.button(label="Expulsão", emoji="👢",
                       style=discord.ButtonStyle.danger,
                       custom_id="sistemas:punir:expulsao")
    async def kick(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PunishmentModal("expulsao"))

    @discord.ui.button(label="Banimento", emoji="🔨",
                       style=discord.ButtonStyle.danger,
                       custom_id="sistemas:punir:banimento")
    async def ban(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PunishmentModal("banimento"))


class PunishmentDecisionView(discord.ui.View):
    """View persistente. O ID da mensagem identifica a solicitação no banco."""
    def __init__(self):
        super().__init__(timeout=None)

    async def _decide(self, interaction: discord.Interaction, approved: bool):
        cog = interaction.client.get_cog("Sistemas")
        if cog is None:
            return await send_ephemeral(interaction, "Sistema indisponível.")
        await cog.decide_punishment_request(interaction, approved)

    @discord.ui.button(label="Aprovar", emoji="✅",
                       style=discord.ButtonStyle.success,
                       custom_id="sistemas:solicitacao:aprovar")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._decide(interaction, True)

    @discord.ui.button(label="Rejeitar", emoji="❌",
                       style=discord.ButtonStyle.danger,
                       custom_id="sistemas:solicitacao:rejeitar")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._decide(interaction, False)


class EmbedBuilderModal(discord.ui.Modal, title="Criador de publicação"):
    title_input = discord.ui.TextInput(label="Título", max_length=256)
    description_input = discord.ui.TextInput(
        label="Descrição", style=discord.TextStyle.paragraph,
        max_length=4000,
    )
    color_input = discord.ui.TextInput(
        label="Cor hexadecimal", placeholder="#7048BE",
        required=False, max_length=7,
    )
    image_input = discord.ui.TextInput(label="URL da imagem", required=False, max_length=500)
    thumbnail_input = discord.ui.TextInput(label="URL da thumbnail", required=False, max_length=500)

    def __init__(self, channel: discord.TextChannel, webhook_name: str,
                 webhook_avatar: Optional[str], custom_fields: Optional[str] = None):
        super().__init__()
        self.channel = channel
        self.webhook_name = webhook_name
        self.webhook_avatar = webhook_avatar
        self.custom_fields = custom_fields

    async def on_submit(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("Sistemas")
        if cog is None:
            return await send_ephemeral(interaction, "Sistema indisponível.")
        image = self.image_input.value.strip() or None
        thumbnail = self.thumbnail_input.value.strip() or None
        if not valid_http_url(image) or not valid_http_url(thumbnail):
            return await send_ephemeral(interaction, "Imagem e thumbnail precisam usar URLs HTTP/HTTPS válidas.")
        raw_color = self.color_input.value.strip().lstrip("#") or "7048BE"
        if not re.fullmatch(r"[0-9a-fA-F]{6}", raw_color):
            return await send_ephemeral(interaction, "Cor inválida. Use o formato hexadecimal, como #7048BE.")
        embed = make_embed(self.title_input.value, self.description_input.value,
                           colour=discord.Colour(int(raw_color, 16)))
        if image:
            embed.set_image(url=image)
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        if self.custom_fields:
            lines = [line.strip() for line in self.custom_fields.splitlines() if line.strip()]
            if len(lines) > 25:
                return await send_ephemeral(interaction, "O Discord permite no máximo 25 campos por embed.")
            for line in lines:
                parts = [part.strip() for part in line.split("|", 2)]
                if len(parts) < 2 or not parts[0] or not parts[1]:
                    return await send_ephemeral(
                        interaction,
                        "Formato de campo inválido. Use uma linha por campo: Nome | Valor | inline (sim/não)."
                    )
                if len(parts[0]) > 256 or len(parts[1]) > 1024:
                    return await send_ephemeral(interaction, "Nome de campo: até 256 caracteres; valor: até 1024.")
                inline = len(parts) == 3 and parts[2].lower() in ("sim", "s", "true", "1", "inline")
                embed.add_field(name=parts[0], value=parts[1], inline=inline)
        await cog.publish_webhook_embed(
            interaction, self.channel, embed, self.webhook_name, self.webhook_avatar
        )


# ---------------------------------------------------------------------------
# Cog principal
# ---------------------------------------------------------------------------

class Sistemas(commands.Cog):
    def __init__(self, bot: commands.Bot, pool: asyncpg.Pool):
        self.bot = bot
        self.pool = pool
        self._voice_locks: dict[int, asyncio.Lock] = {}

    async def cog_load(self):
        await self.create_tables()
        # Views com custom_id fixos são registradas após o banco estar pronto.
        self.bot.add_view(PunishmentPanelView())
        self.bot.add_view(PunishmentDecisionView())
        await self.restore_persistent_requests()

    async def create_tables(self):
        statements = [
            """
            CREATE TABLE IF NOT EXISTS sistemas_config (
                guild_id BIGINT PRIMARY KEY,
                log_channel_id BIGINT,
                punishment_panel_channel_id BIGINT,
                punishment_review_channel_id BIGINT,
                reviewer_role_id BIGINT,
                staff_role_ids BIGINT[] NOT NULL DEFAULT '{}',
                temp_voice_trigger_id BIGINT,
                temp_voice_category_id BIGINT,
                afk_channel_id BIGINT,
                banner_url TEXT,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS sistemas_punishment_requests (
                id BIGSERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                requester_id BIGINT NOT NULL,
                target_id BIGINT NOT NULL,
                punishment_type TEXT NOT NULL,
                reason TEXT NOT NULL,
                evidence_url TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                reviewer_id BIGINT,
                decision_reason TEXT,
                review_channel_id BIGINT,
                review_message_id BIGINT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                decided_at TIMESTAMPTZ
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS sistemas_moderation_cases (
                id BIGSERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                moderator_id BIGINT NOT NULL,
                action TEXT NOT NULL,
                reason TEXT NOT NULL,
                expires_at TIMESTAMPTZ,
                source_request_id BIGINT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS sistemas_afk (
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                reason TEXT,
                since TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (guild_id, user_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS sistemas_temp_voice (
                channel_id BIGINT PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                owner_id BIGINT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS sistemas_staff_members (
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (guild_id, user_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS sistemas_staff_history (
                id BIGSERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                actor_id BIGINT,
                event TEXT NOT NULL,
                role_id BIGINT,
                details TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
        ]
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for statement in statements:
                    await conn.execute(statement)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS sistemas_cases_user_idx
                    ON sistemas_moderation_cases (guild_id, user_id, created_at DESC)
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS sistemas_requests_status_idx
                    ON sistemas_punishment_requests (guild_id, status)
                """)

    async def get_config(self, guild_id: int):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT * FROM sistemas_config WHERE guild_id=$1", guild_id
            )

    async def ensure_config(self, guild_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO sistemas_config (guild_id) VALUES ($1) ON CONFLICT DO NOTHING",
                guild_id,
            )

    async def set_config_value(self, guild_id: int, column: str, value):
        allowed = {
            "log_channel_id", "punishment_panel_channel_id",
            "punishment_review_channel_id", "reviewer_role_id",
            "temp_voice_trigger_id", "temp_voice_category_id",
            "afk_channel_id", "banner_url",
        }
        if column not in allowed:
            raise ValueError("Configuração não permitida.")
        await self.ensure_config(guild_id)
        # O nome da coluna vem exclusivamente da allowlist; valores seguem parametrizados.
        async with self.pool.acquire() as conn:
            await conn.execute(
                f"UPDATE sistemas_config SET {column}=$2, updated_at=NOW() WHERE guild_id=$1",
                guild_id, value,
            )

    async def log(self, guild: discord.Guild, title: str, description: str,
                  *, colour: discord.Colour = PURPLE, actor: Optional[discord.abc.User] = None):
        config = await self.get_config(guild.id)
        if not config or not config["log_channel_id"]:
            return
        channel = guild.get_channel(config["log_channel_id"])
        if not isinstance(channel, discord.TextChannel):
            return
        embed = make_embed(title, description, colour=colour)
        if actor:
            embed.add_field(name="Responsável", value=f"{actor.mention} (`{actor.id}`)", inline=False)
        try:
            await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def restore_persistent_requests(self):
        # As views possuem custom_ids estáticos; o banco localiza o registro pelo message_id.
        # Registros antigos continuam acionáveis mesmo após reinicialização.
        return

    async def cog_app_command_error(self, interaction: discord.Interaction,
                                    error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            message = "Você não possui as permissões necessárias para usar este comando."
        elif isinstance(error, app_commands.CommandOnCooldown):
            message = "Aguarde um pouco antes de utilizar este comando novamente."
        elif isinstance(error, app_commands.CheckFailure):
            message = "Você não está autorizado a utilizar este comando neste contexto."
        else:
            # Erro é tratado neste Cog; não altera o tratamento global nem outros Cogs.
            message = "Ocorreu um erro ao executar este sistema. Tente novamente ou contate a administração."
        try:
            await send_ephemeral(interaction, message)
        except discord.HTTPException:
            pass

    # -----------------------------------------------------------------------
    # Solicitações de punição
    # -----------------------------------------------------------------------

    async def create_punishment_request(self, interaction: discord.Interaction,
                                        punishment_type: str, target_id: int,
                                        reason: str, evidence: Optional[str]):
        guild = interaction.guild
        config = await self.get_config(guild.id)
        if not config or not config["punishment_review_channel_id"]:
            return await send_ephemeral(interaction, "O canal de análise ainda não foi configurado.")
        review_channel = guild.get_channel(config["punishment_review_channel_id"])
        if not isinstance(review_channel, discord.TextChannel):
            return await send_ephemeral(interaction, "O canal de análise configurado não existe ou não é textual.")
        if target_id == interaction.user.id:
            return await send_ephemeral(interaction, "Você não pode solicitar punição para si mesmo.")
        if guild.get_member(target_id) is None:
            try:
                await guild.fetch_member(target_id)
            except discord.NotFound:
                return await send_ephemeral(interaction, "O membro informado não está neste servidor.")
            except discord.HTTPException:
                return await send_ephemeral(interaction, "Não foi possível validar o membro. Tente novamente.")
        async with self.pool.acquire() as conn:
            request_id = await conn.fetchval("""
                INSERT INTO sistemas_punishment_requests
                (guild_id, requester_id, target_id, punishment_type, reason, evidence_url,
                 review_channel_id)
                VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id
            """, guild.id, interaction.user.id, target_id, punishment_type,
                reason, evidence, review_channel.id)
        embed = make_embed(
            f"📨 Solicitação #{request_id:04d} • {PUNISHMENTS[punishment_type]}",
            "Uma nova solicitação aguarda análise da equipe.",
            colour=GOLD,
        )
        embed.add_field(name="Solicitante", value=f"{interaction.user.mention}\n`{interaction.user.id}`", inline=True)
        embed.add_field(name="Membro denunciado", value=f"<@{target_id}>\n`{target_id}`", inline=True)
        embed.add_field(name="Tipo", value=PUNISHMENTS[punishment_type], inline=True)
        embed.add_field(name="Motivo", value=clipped(reason, 1024), inline=False)
        embed.add_field(name="Evidência", value=evidence or "Não informada", inline=False)
        try:
            message = await review_channel.send(embed=embed, view=PunishmentDecisionView())
        except (discord.Forbidden, discord.HTTPException):
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "UPDATE sistemas_punishment_requests SET status='delivery_failed' WHERE id=$1",
                    request_id,
                )
            return await send_ephemeral(interaction, "A solicitação foi registrada, mas não consegui publicar no canal de análise. Avise um administrador.")
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE sistemas_punishment_requests
                SET review_message_id=$2 WHERE id=$1
            """, request_id, message.id)
        await send_ephemeral(interaction, f"Solicitação **#{request_id:04d}** enviada para análise.")
        await self.log(guild, "📨 Nova solicitação de punição",
                       f"Solicitação `#{request_id}` • {PUNISHMENTS[punishment_type]} • membro `{target_id}`",
                       actor=interaction.user)

    async def decide_punishment_request(self, interaction: discord.Interaction, approved: bool):
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            return await send_ephemeral(interaction, "Esta ação só pode ser realizada dentro do servidor.")
        config = await self.get_config(guild.id)
        if not config or not config["reviewer_role_id"]:
            return await send_ephemeral(interaction, "Nenhum cargo de análise foi configurado.")
        reviewer_role = guild.get_role(config["reviewer_role_id"])
        actor = interaction.user
        if not actor.guild_permissions.administrator and (
            reviewer_role is None or reviewer_role not in actor.roles
        ):
            return await send_ephemeral(interaction, "Você não possui autorização para analisar solicitações.")
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                request = await conn.fetchrow("""
                    SELECT * FROM sistemas_punishment_requests
                    WHERE review_message_id=$1 AND guild_id=$2
                    FOR UPDATE
                """, interaction.message.id, guild.id)
                if request is None:
                    return await send_ephemeral(interaction, "Solicitação não encontrada.")
                if request["status"] != "pending":
                    return await send_ephemeral(interaction, "Esta solicitação já foi analisada.")
                if request["requester_id"] == actor.id:
                    return await send_ephemeral(interaction, "Você não pode analisar sua própria solicitação.")
                await conn.execute("""
                    UPDATE sistemas_punishment_requests
                    SET status=$2, reviewer_id=$3, decided_at=NOW()
                    WHERE id=$1 AND status='pending'
                """, request["id"], "approved" if approved else "rejected", actor.id)
        if approved:
            try:
                await self.execute_punishment(guild, request, actor)
            except (discord.Forbidden, discord.HTTPException, ValueError) as exc:
                async with self.pool.acquire() as conn:
                    await conn.execute("""
                        UPDATE sistemas_punishment_requests
                        SET status='execution_failed', decision_reason=$2
                        WHERE id=$1
                    """, request["id"], clipped(str(exc), 500))
                await send_ephemeral(interaction, f"A decisão foi registrada, mas a punição não pôde ser executada: {exc}")
                return
        embed = interaction.message.embeds[0] if interaction.message.embeds else make_embed("Solicitação analisada")
        embed.colour = GREEN if approved else RED
        embed.add_field(
            name="Decisão",
            value=("Aprovada e executada" if approved else "Rejeitada") + f"\nResponsável: {actor.mention}",
            inline=False,
        )
        try:
            await interaction.message.edit(embed=embed, view=None)
        except discord.HTTPException:
            pass
        await send_ephemeral(interaction, "Solicitação aprovada e punição executada." if approved else "Solicitação rejeitada.")
        await self.log(guild, "⚖️ Solicitação analisada",
                       f"Solicitação `#{request['id']}` • {'Aprovada' if approved else 'Rejeitada'}",
                       colour=GREEN if approved else RED, actor=actor)

    async def execute_punishment(self, guild: discord.Guild, request, moderator: discord.Member):
        target = guild.get_member(request["target_id"])
        if target is None:
            target = await guild.fetch_member(request["target_id"])
        bot_member = guild.me
        allowed, error = can_manage_target(moderator, target, bot_member)
        if not allowed:
            raise ValueError(error)
        if request["punishment_type"] == "advertencia":
            action = "advertência"
        elif request["punishment_type"] == "timeout":
            if not bot_member.guild_permissions.moderate_members:
                raise ValueError("O bot não possui a permissão Moderar membros.")
            await target.timeout(timedelta(hours=1), reason=f"Solicitação #{request['id']}: {request['reason']}")
            action = "timeout"
        elif request["punishment_type"] == "expulsao":
            if not bot_member.guild_permissions.kick_members:
                raise ValueError("O bot não possui a permissão Expulsar membros.")
            await target.kick(reason=f"Solicitação #{request['id']}: {request['reason']}")
            action = "expulsão"
        elif request["punishment_type"] == "banimento":
            if not bot_member.guild_permissions.ban_members:
                raise ValueError("O bot não possui a permissão Banir membros.")
            await target.ban(reason=f"Solicitação #{request['id']}: {request['reason']}", delete_message_seconds=0)
            action = "banimento"
        else:
            raise ValueError("Tipo de punição desconhecido.")
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO sistemas_moderation_cases
                (guild_id,user_id,moderator_id,action,reason,source_request_id)
                VALUES ($1,$2,$3,$4,$5,$6)
            """, guild.id, request["target_id"], moderator.id, action,
                request["reason"], request["id"])

    # -----------------------------------------------------------------------
    # Comandos de configuração
    # -----------------------------------------------------------------------

    @app_commands.command(name="sistemas_config", description="Configura canais e cargos dos sistemas administrativos.")
    @app_commands.describe(opcao="Configuração que deseja alterar", id="ID do canal ou cargo; use 0 para limpar", url="URL do banner (somente para banner)")
    @app_commands.choices(opcao=[
        app_commands.Choice(name="Canal de logs", value="log_channel_id"),
        app_commands.Choice(name="Painel de punições", value="punishment_panel_channel_id"),
        app_commands.Choice(name="Canal de análise", value="punishment_review_channel_id"),
        app_commands.Choice(name="Cargo de análise", value="reviewer_role_id"),
        app_commands.Choice(name="Canal AFK", value="afk_channel_id"),
        app_commands.Choice(name="Entrada de salas temporárias", value="temp_voice_trigger_id"),
        app_commands.Choice(name="Categoria de salas temporárias", value="temp_voice_category_id"),
        app_commands.Choice(name="Banner dos painéis", value="banner_url"),
    ])
    @app_commands.checks.has_permissions(administrator=True)
    async def sistemas_config(self, interaction: discord.Interaction,
                              opcao: app_commands.Choice[str],
                              id: Optional[str] = None,
                              url: Optional[str] = None):
        if opcao.value == "banner_url":
            if url and not valid_http_url(url):
                return await send_ephemeral(interaction, "URL do banner inválida.")
            value = url or None
        else:
            if id is None or not id.isdigit():
                return await send_ephemeral(interaction, "Informe um ID numérico válido no campo ID.")
            value = int(id) or None
            if value:
                channel_options = {
                    "log_channel_id": discord.TextChannel,
                    "punishment_panel_channel_id": discord.TextChannel,
                    "punishment_review_channel_id": discord.TextChannel,
                    "afk_channel_id": discord.TextChannel,
                    "temp_voice_trigger_id": discord.VoiceChannel,
                    "temp_voice_category_id": discord.CategoryChannel,
                }
                expected = channel_options.get(opcao.value)
                if expected:
                    obj = interaction.guild.get_channel(value)
                    if not isinstance(obj, expected):
                        return await send_ephemeral(interaction, "O ID informado não corresponde ao tipo de canal esperado.")
                elif opcao.value == "reviewer_role_id" and interaction.guild.get_role(value) is None:
                    return await send_ephemeral(interaction, "Cargo não encontrado neste servidor.")
        await self.set_config_value(interaction.guild.id, opcao.value, value)
        await send_ephemeral(interaction, f"Configuração **{opcao.name}** atualizada.")

    @app_commands.command(name="staff_cargos", description="Define os cargos considerados staff (IDs separados por espaço).")
    @app_commands.checks.has_permissions(administrator=True)
    async def staff_cargos(self, interaction: discord.Interaction, ids: str):
        role_ids = []
        for token in ids.replace(",", " ").split():
            if not token.isdigit():
                return await send_ephemeral(interaction, f"ID inválido: `{token}`.")
            role_id = int(token)
            if interaction.guild.get_role(role_id) is None:
                return await send_ephemeral(interaction, f"O cargo `{role_id}` não existe neste servidor.")
            if role_id not in role_ids:
                role_ids.append(role_id)
        if len(role_ids) > 25:
            return await send_ephemeral(interaction, "É possível cadastrar no máximo 25 cargos staff.")
        await self.ensure_config(interaction.guild.id)
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE sistemas_config SET staff_role_ids=$2, updated_at=NOW()
                WHERE guild_id=$1
            """, interaction.guild.id, role_ids)
        await send_ephemeral(interaction, f"{len(role_ids)} cargo(s) staff configurado(s).")

    @app_commands.command(name="painel_punicoes", description="Publica o painel permanente de solicitações de punição.")
    @app_commands.checks.has_permissions(administrator=True)
    async def painel_punicoes(self, interaction: discord.Interaction):
        config = await self.get_config(interaction.guild.id)
        if not config or not config["punishment_panel_channel_id"]:
            return await send_ephemeral(interaction, "Configure primeiro o canal do painel com /sistemas_config.")
        channel = interaction.guild.get_channel(config["punishment_panel_channel_id"])
        if not isinstance(channel, discord.TextChannel):
            return await send_ephemeral(interaction, "Canal do painel inválido.")
        embed = make_embed(
            "🛡️ CENTRAL DE SOLICITAÇÕES DISCIPLINARES",
            "Selecione abaixo a medida que deseja solicitar.\n\n"
            "Preencha o formulário com o ID do membro, um motivo detalhado e, se possível, uma evidência.\n"
            "Todas as solicitações são encaminhadas à equipe responsável e ficam registradas no histórico.",
        )
        if config["banner_url"] and valid_http_url(config["banner_url"]):
            embed.set_image(url=config["banner_url"])
        embed.add_field(name="⚠️ Advertência", value="Registro formal de orientação.", inline=True)
        embed.add_field(name="🔇 Timeout", value="Restrição temporária de comunicação.", inline=True)
        embed.add_field(name="🔨 Expulsão / Banimento", value="Medidas de remoção do servidor.", inline=True)
        await channel.send(embed=embed, view=PunishmentPanelView())
        await send_ephemeral(interaction, f"Painel publicado em {channel.mention}.")

    # -----------------------------------------------------------------------
    # Moderação
    # -----------------------------------------------------------------------

    async def record_case(self, guild: discord.Guild, user_id: int, moderator_id: int,
                          action: str, reason: str, expires_at=None):
        async with self.pool.acquire() as conn:
            case_id = await conn.fetchval("""
                INSERT INTO sistemas_moderation_cases
                (guild_id,user_id,moderator_id,action,reason,expires_at)
                VALUES ($1,$2,$3,$4,$5,$6) RETURNING id
            """, guild.id, user_id, moderator_id, action, reason, expires_at)
        await self.log(guild, f"🛡️ Moderação • {action.title()}",
                       f"Membro: <@{user_id}> (`{user_id}`)\nMotivo: {reason}\nRegistro: `#{case_id}`",
                       actor=guild.get_member(moderator_id))
        return case_id

    async def check_moderation(self, interaction: discord.Interaction,
                               member: discord.Member, permission: str):
        actor = interaction.user
        if not isinstance(actor, discord.Member):
            return False, "Ação disponível apenas para membros do servidor."
        if not (actor.guild_permissions.administrator or getattr(actor.guild_permissions, permission, False)):
            return False, "Você não possui a permissão necessária."
        bot_member = interaction.guild.me
        return can_manage_target(actor, member, bot_member)

    @app_commands.command(name="advertir", description="Registra uma advertência para um membro.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def advertir(self, interaction: discord.Interaction, membro: discord.Member, motivo: str):
        ok, error = await self.check_moderation(interaction, membro, "moderate_members")
        if not ok:
            return await send_ephemeral(interaction, error)
        case_id = await self.record_case(interaction.guild, membro.id, interaction.user.id, "advertência", motivo)
        await send_ephemeral(interaction, f"Advertência registrada para {membro.mention}. Registro `#{case_id}`.")

    @app_commands.command(name="timeout", description="Aplica timeout em um membro.")
    @app_commands.describe(duracao_minutos="Duração entre 1 e 40320 minutos")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def timeout_member(self, interaction: discord.Interaction, membro: discord.Member,
                             duracao_minutos: app_commands.Range[int, 1, 40320], motivo: str):
        ok, error = await self.check_moderation(interaction, membro, "moderate_members")
        if not ok:
            return await send_ephemeral(interaction, error)
        if not interaction.guild.me.guild_permissions.moderate_members:
            return await send_ephemeral(interaction, "O bot não possui a permissão Moderar membros.")
        expires = datetime.now(timezone.utc) + timedelta(minutes=duracao_minutos)
        try:
            await membro.timeout(timedelta(minutes=duracao_minutos), reason=f"{interaction.user}: {motivo}")
        except discord.Forbidden:
            return await send_ephemeral(interaction, "A hierarquia ou as permissões do bot impedem o timeout.")
        case_id = await self.record_case(interaction.guild, membro.id, interaction.user.id, "timeout", motivo, expires)
        await send_ephemeral(interaction, f"Timeout aplicado em {membro.mention} por {duracao_minutos} minuto(s). Registro `#{case_id}`.")

    @app_commands.command(name="remover_timeout", description="Remove o timeout de um membro.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def remover_timeout(self, interaction: discord.Interaction, membro: discord.Member, motivo: str):
        ok, error = await self.check_moderation(interaction, membro, "moderate_members")
        if not ok:
            return await send_ephemeral(interaction, error)
        try:
            await membro.timeout(None, reason=f"{interaction.user}: {motivo}")
        except discord.Forbidden:
            return await send_ephemeral(interaction, "Não foi possível remover o timeout por falta de permissão ou hierarquia.")
        case_id = await self.record_case(interaction.guild, membro.id, interaction.user.id, "remoção de timeout", motivo)
        await send_ephemeral(interaction, f"Timeout removido de {membro.mention}. Registro `#{case_id}`.")

    @app_commands.command(name="historico_moderacao", description="Consulta os registros administrativos de um membro.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def historico_moderacao(self, interaction: discord.Interaction, membro: discord.Member):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, moderator_id, action, reason, expires_at, created_at
                FROM sistemas_moderation_cases
                WHERE guild_id=$1 AND user_id=$2
                ORDER BY created_at DESC LIMIT 10
            """, interaction.guild.id, membro.id)
        embed = make_embed(f"📚 Histórico de {membro}", f"Registros encontrados: **{len(rows)}**")
        if not rows:
            embed.description = "Nenhum registro administrativo encontrado."
        for row in rows:
            date = row["created_at"].strftime("%d/%m/%Y %H:%M UTC")
            embed.add_field(
                name=f"#{row['id']} • {row['action']} • {date}",
                value=clipped(f"Moderador: <@{row['moderator_id']}>\nMotivo: {row['reason']}", 1000),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # -----------------------------------------------------------------------
    # AFK
    # -----------------------------------------------------------------------

    @app_commands.command(name="afk", description="Define seu status de ausência.")
    async def afk(self, interaction: discord.Interaction, motivo: Optional[str] = None):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO sistemas_afk (guild_id,user_id,reason,since)
                VALUES ($1,$2,$3,NOW())
                ON CONFLICT (guild_id,user_id)
                DO UPDATE SET reason=EXCLUDED.reason, since=NOW()
            """, interaction.guild.id, interaction.user.id, motivo)
        embed = make_embed("🌙 Status AFK ativado",
                           f"{interaction.user.mention}, sua ausência foi registrada."
                           + (f"\n**Motivo:** {motivo}" if motivo else ""),
                           colour=GOLD)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot:
            return
        # Mensagem nova encerra o AFK do autor.
        async with self.pool.acquire() as conn:
            removed = await conn.fetchrow("""
                DELETE FROM sistemas_afk WHERE guild_id=$1 AND user_id=$2
                RETURNING reason
            """, message.guild.id, message.author.id)
            mentioned = []
            if message.mentions:
                mentioned = await conn.fetch("""
                    SELECT user_id, reason, since FROM sistemas_afk
                    WHERE guild_id=$1 AND user_id = ANY($2::BIGINT[])
                """, message.guild.id, [m.id for m in message.mentions])
        if removed:
            try:
                await message.channel.send(
                    embed=make_embed("☀️ Bem-vindo de volta",
                                     f"{message.author.mention}, seu status AFK foi removido.",
                                     colour=GREEN),
                    delete_after=8,
                )
            except discord.HTTPException:
                pass
        for row in mentioned:
            reason = f"\n**Motivo:** {row['reason']}" if row["reason"] else ""
            try:
                await message.channel.send(
                    embed=make_embed("🌙 Membro ausente",
                                     f"<@{row['user_id']}> está AFK desde <t:{int(row['since'].timestamp())}:R>.{reason}",
                                     colour=GOLD),
                    delete_after=12,
                )
            except discord.HTTPException:
                pass

    # -----------------------------------------------------------------------
    # Logs de eventos Discord
    # -----------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self.log(member.guild, "📥 Membro entrou",
                       f"{member.mention} (`{member.id}`)\nConta criada: <t:{int(member.created_at.timestamp())}:R>")
        await self.sync_one_staff_member(member)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self.log(member.guild, "📤 Membro saiu",
                       f"**{member}** (`{member.id}`)", colour=RED)
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE sistemas_staff_members SET active=FALSE,last_seen=NOW()
                WHERE guild_id=$1 AND user_id=$2
            """, member.guild.id, member.id)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        before_ids = {r.id for r in before.roles}
        after_ids = {r.id for r in after.roles}
        added, removed = after_ids - before_ids, before_ids - after_ids
        if added or removed:
            await self.log(after.guild, "🎭 Cargos alterados",
                           f"Membro: {after.mention}\nAdicionados: {', '.join(f'<@&{x}>' for x in added) or 'Nenhum'}\nRemovidos: {', '.join(f'<@&{x}>' for x in removed) or 'Nenhum'}")
            config = await self.get_config(after.guild.id)
            staff_ids = set(config["staff_role_ids"] or []) if config else set()
            for role_id in added & staff_ids:
                await self.staff_event(after.guild.id, after.id, None, "cargo_staff_adicionado", role_id)
            for role_id in removed & staff_ids:
                await self.staff_event(after.guild.id, after.id, None, "cargo_staff_removido", role_id)
            await self.sync_one_staff_member(after)
        changed = []
        if before.nick != after.nick:
            changed.append(f"Apelido: `{before.nick}` → `{after.nick}`")
        if before.pending != after.pending:
            changed.append(f"Verificação pendente: `{before.pending}` → `{after.pending}`")
        if changed:
            await self.log(after.guild, "👤 Dados do membro alterados",
                           f"Membro: {after.mention}\n" + "\n".join(changed))

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.guild is None or before.author.bot or before.content == after.content:
            return
        await self.log(before.guild, "✏️ Mensagem editada",
                       f"Autor: {before.author.mention}\nCanal: {before.channel.mention}\nMensagem: [abrir]({after.jump_url})\nO conteúdo não é copiado para os logs.")

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.guild is None or message.author.bot:
            return
        # Privacidade: registra metadados, sem replicar conteúdo ou anexos da mensagem.
        await self.log(message.guild, "🗑️ Mensagem excluída",
                       f"Autor: {message.author.mention}\nCanal: {message.channel.mention}\nID da mensagem: `{message.id}`\nO conteúdo não é copiado para os logs.")

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        await self.log(channel.guild, "➕ Canal criado", f"{channel.mention} (`{channel.id}`)")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        await self.log(channel.guild, "➖ Canal excluído", f"**{channel.name}** (`{channel.id}`)", colour=RED)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel,
                                      after: discord.abc.GuildChannel):
        changes = []
        if before.name != after.name:
            changes.append(f"Nome: `{before.name}` → `{after.name}`")
        if before.category_id != after.category_id:
            changes.append(f"Categoria: `{before.category_id}` → `{after.category_id}`")
        if changes:
            await self.log(after.guild, "🛠️ Canal atualizado",
                           f"Canal: {after.mention}\n" + "\n".join(changes))

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        await self.log(guild, "🔨 Banimento detectado",
                       f"Usuário: **{user}** (`{user.id}`)", colour=RED)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        await self.log(guild, "♻️ Banimento removido",
                       f"Usuário: **{user}** (`{user.id}`)", colour=GREEN)

    # -----------------------------------------------------------------------
    # Staff persistente
    # -----------------------------------------------------------------------

    async def staff_event(self, guild_id: int, user_id: int, actor_id: Optional[int],
                          event: str, role_id: Optional[int] = None, details: Optional[str] = None):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO sistemas_staff_history
                (guild_id,user_id,actor_id,event,role_id,details)
                VALUES ($1,$2,$3,$4,$5,$6)
            """, guild_id, user_id, actor_id, event, role_id, details)

    async def sync_one_staff_member(self, member: discord.Member):
        config = await self.get_config(member.guild.id)
        if not config:
            return
        staff_ids = set(config["staff_role_ids"] or [])
        active = any(role.id in staff_ids for role in member.roles)
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO sistemas_staff_members
                (guild_id,user_id,active,last_seen)
                VALUES ($1,$2,$3,NOW())
                ON CONFLICT (guild_id,user_id)
                DO UPDATE SET active=EXCLUDED.active,last_seen=NOW()
            """, member.guild.id, member.id, active)

    @app_commands.command(name="staff_sincronizar", description="Sincroniza membros que possuem cargos staff configurados.")
    @app_commands.checks.has_permissions(administrator=True)
    async def staff_sincronizar(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        config = await self.get_config(interaction.guild.id)
        if not config or not config["staff_role_ids"]:
            return await interaction.followup.send("Cadastre os cargos com /staff_cargos primeiro.", ephemeral=True)
        count = 0
        async for member in interaction.guild.fetch_members(limit=None):
            await self.sync_one_staff_member(member)
            count += 1
        await interaction.followup.send(f"Sincronização concluída. **{count}** membros verificados.", ephemeral=True)

    @app_commands.command(name="staff_consultar", description="Consulta o cadastro e o histórico staff de um membro.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def staff_consultar(self, interaction: discord.Interaction, membro: discord.Member):
        async with self.pool.acquire() as conn:
            record = await conn.fetchrow("""
                SELECT * FROM sistemas_staff_members WHERE guild_id=$1 AND user_id=$2
            """, interaction.guild.id, membro.id)
            history = await conn.fetch("""
                SELECT event,role_id,actor_id,created_at FROM sistemas_staff_history
                WHERE guild_id=$1 AND user_id=$2 ORDER BY created_at DESC LIMIT 8
            """, interaction.guild.id, membro.id)
        embed = make_embed(f"👥 Perfil staff • {membro}")
        embed.add_field(name="Status", value=("Ativo" if record and record["active"] else "Inativo / não cadastrado"), inline=True)
        embed.add_field(name="Primeiro registro", value=(record["first_seen"].strftime("%d/%m/%Y") if record else "—"), inline=True)
        embed.add_field(name="Última atividade registrada", value=(record["last_seen"].strftime("%d/%m/%Y %H:%M") if record else "—"), inline=True)
        embed.add_field(name="Histórico", value="\n".join(
            f"• {r['event']} — cargo <@&{r['role_id']}>" for r in history
        ) or "Sem alterações registradas.", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # -----------------------------------------------------------------------
    # Salas de voz temporárias
    # -----------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member,
                                   before: discord.VoiceState, after: discord.VoiceState):
        if before.channel and before.channel.id != (after.channel.id if after.channel else None):
            await self.delete_empty_temp_channel(before.channel)
        if after.channel is None or before.channel == after.channel:
            return
        config = await self.get_config(member.guild.id)
        if not config or after.channel.id != config["temp_voice_trigger_id"]:
            return
        lock = self._voice_locks.setdefault(member.guild.id, asyncio.Lock())
        async with lock:
            # Confere novamente se o membro continua no canal de entrada.
            current = member.voice
            if current is None or current.channel is None or current.channel.id != after.channel.id:
                return
            category = member.guild.get_channel(config["temp_voice_category_id"]) if config["temp_voice_category_id"] else None
            if category is not None and not isinstance(category, discord.CategoryChannel):
                category = None
            overwrites = {
                member.guild.default_role: discord.PermissionOverwrite(connect=True, view_channel=True),
                member: discord.PermissionOverwrite(
                    connect=True, view_channel=True, manage_channels=True,
                    move_members=True, mute_members=True, deafen_members=True,
                ),
                member.guild.me: discord.PermissionOverwrite(
                    connect=True, view_channel=True, manage_channels=True, move_members=True,
                ),
            }
            try:
                channel = await member.guild.create_voice_channel(
                    name=f"・{member.display_name}"[:95],
                    category=category,
                    overwrites=overwrites,
                    reason=f"Sala temporária de {member} ({member.id})",
                )
                async with self.pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO sistemas_temp_voice (channel_id,guild_id,owner_id)
                        VALUES ($1,$2,$3)
                    """, channel.id, member.guild.id, member.id)
                await member.move_to(channel, reason="Criação de sala temporária")
                await self.log(member.guild, "🔊 Sala temporária criada",
                               f"Sala: {channel.mention}\nProprietário: {member.mention}")
            except (discord.Forbidden, discord.HTTPException) as exc:
                await self.log(member.guild, "⚠️ Falha ao criar sala temporária", clipped(exc, 500), colour=RED)

    async def delete_empty_temp_channel(self, channel: discord.VoiceChannel):
        async with self.pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT 1 FROM sistemas_temp_voice WHERE channel_id=$1 AND guild_id=$2",
                channel.id, channel.guild.id,
            )
        if not exists or channel.members:
            return
        try:
            await channel.delete(reason="Sala temporária vazia")
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM sistemas_temp_voice WHERE channel_id=$1", channel.id)
        await self.log(channel.guild, "🧹 Sala temporária removida",
                       f"Canal **{channel.name}** (`{channel.id}`) ficou vazio.")

    @commands.Cog.listener()
    async def on_ready(self):
        # Recupera canais registrados antes de reiniciar. Canais vazios são limpos;
        # canais ocupados permanecem válidos e serão removidos quando esvaziarem.
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT channel_id,guild_id FROM sistemas_temp_voice")
        for row in rows:
            guild = self.bot.get_guild(row["guild_id"])
            channel = guild.get_channel(row["channel_id"]) if guild else None
            if channel is None:
                async with self.pool.acquire() as conn:
                    await conn.execute("DELETE FROM sistemas_temp_voice WHERE channel_id=$1", row["channel_id"])
            elif isinstance(channel, discord.VoiceChannel) and not channel.members:
                await self.delete_empty_temp_channel(channel)

    # -----------------------------------------------------------------------
    # Criador de embeds por webhook
    # -----------------------------------------------------------------------

    @app_commands.command(name="criar_embed", description="Abre o criador de publicação por webhook.")
    @app_commands.describe(
        canal="Canal de destino",
        nome_webhook="Nome exibido pelo webhook (2 a 80 caracteres)",
        avatar_url="URL opcional do avatar",
        campos="Campos extras: uma linha por campo no formato Nome | Valor | sim/não",
    )
    @app_commands.checks.has_permissions(manage_webhooks=True)
    async def criar_embed(self, interaction: discord.Interaction,
                          canal: discord.TextChannel,
                          nome_webhook: str = "Central Administrativa",
                          avatar_url: Optional[str] = None,
                          campos: Optional[str] = None):
        if not interaction.guild.me.guild_permissions.manage_webhooks:
            return await send_ephemeral(interaction, "O bot precisa da permissão Gerenciar webhooks.")
        if not 2 <= len(nome_webhook) <= 80:
            return await send_ephemeral(interaction, "O nome do webhook precisa ter entre 2 e 80 caracteres.")
        if avatar_url and not valid_http_url(avatar_url):
            return await send_ephemeral(interaction, "URL de avatar inválida.")
        if campos and len(campos) > 1024:
            return await send_ephemeral(interaction, "A configuração dos campos excede 1024 caracteres.")
        if canal.guild.id != interaction.guild.id:
            return await send_ephemeral(interaction, "Canal inválido.")
        await interaction.response.send_modal(
            EmbedBuilderModal(canal, nome_webhook, avatar_url, campos)
        )

    async def publish_webhook_embed(self, interaction: discord.Interaction,
                                    channel: discord.TextChannel, embed: discord.Embed,
                                    webhook_name: str, avatar_url: Optional[str]):
        try:
            webhooks = await channel.webhooks()
            webhook = next((w for w in webhooks if w.name == webhook_name and w.user == self.bot.user), None)
            if webhook is None:
                webhook = await channel.create_webhook(
                    name=webhook_name,
                    avatar=None,
                    reason=f"Publicação administrativa solicitada por {interaction.user}",
                )
            await webhook.send(
                embed=embed,
                username=webhook_name,
                avatar_url=avatar_url,
                allowed_mentions=discord.AllowedMentions.none(),
                wait=True,
            )
        except discord.Forbidden:
            return await send_ephemeral(interaction, "Não tenho permissão para criar ou utilizar webhooks neste canal.")
        except discord.HTTPException as exc:
            return await send_ephemeral(interaction, f"Falha ao publicar o embed: {clipped(exc, 300)}")
        await send_ephemeral(interaction, f"Publicação enviada com sucesso em {channel.mention}.")


# ---------------------------------------------------------------------------
# Setup da extensão
# ---------------------------------------------------------------------------

async def setup(bot: commands.Bot):
    # No main.py fornecido, connect_database() é executado antes de load_extension().
    # Como o arquivo é executado como script, o módulo principal é __main__.
    main_module = sys.modules.get("__main__")
    pool = getattr(main_module, "db_pool", None) if main_module else None
    if pool is None:
        raise RuntimeError(
            "O pool global db_pool não está disponível. "
            "Carregue a extensão somente depois de connect_database() no main.py."
        )
    if not isinstance(pool, asyncpg.Pool):
        # Mantém compatibilidade com pools/proxies asyncpg e facilita testes.
        if not hasattr(pool, "acquire"):
            raise RuntimeError("A variável __main__.db_pool não é um pool asyncpg válido.")
    await bot.add_cog(Sistemas(bot, pool))
