
from discord.ext import commands


async def setup(bot: commands.Bot):
    print("[SISTEMAS] Sistemas carregados.")

# ============================================================
# SISTEMAS DO BOT
# Logs • Moderação • Solicitações • Configurações • Staff
# Embeds/Webhooks • AFK • Calls temporárias
# ============================================================

import re
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands


PURPLE = discord.Colour.from_rgb(129, 85, 199)
DARK = discord.Colour.from_rgb(30, 24, 42)
GREEN = discord.Colour.from_rgb(65, 170, 110)
RED = discord.Colour.from_rgb(190, 65, 75)
YELLOW = discord.Colour.from_rgb(220, 170, 65)

CONFIG_KEYS = [
    "logs_channel_id",
    "punishment_channel_id",
    "request_channel_id",
    "approver_role_id",
    "staff_role_id",
    "staff_list_channel_id",
    "voice_lobby_id",
    "voice_category_id",
    "banner_url",
]

# ============================================================
# BANCO DE DADOS
# ============================================================

async def create_tables(pool):
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS system_config (
                guild_id BIGINT NOT NULL,
                config_key TEXT NOT NULL,
                config_value TEXT NOT NULL,
                PRIMARY KEY (guild_id, config_key)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS system_punishments (
                id BIGSERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                moderator_id BIGINT NOT NULL,
                punishment_type TEXT NOT NULL,
                reason TEXT NOT NULL,
                duration_minutes INTEGER,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS system_punishment_requests (
                id BIGSERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                target_id BIGINT NOT NULL,
                requester_id BIGINT NOT NULL,
                punishment_type TEXT NOT NULL,
                reason TEXT NOT NULL,
                evidence_url TEXT,
                duration_minutes INTEGER,
                message_id BIGINT,
                status TEXT NOT NULL DEFAULT 'pending',
                reviewer_id BIGINT,
                review_reason TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                reviewed_at TIMESTAMPTZ
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS system_afk (
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                reason TEXT NOT NULL,
                since TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS system_staff_history (
                id BIGSERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                action TEXT NOT NULL,
                role_id BIGINT NOT NULL,
                executor_id BIGINT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS system_staff_registry (
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                active BOOLEAN NOT NULL DEFAULT TRUE,
                PRIMARY KEY (guild_id, user_id)
            )
        """)


async def get_config(pool, guild_id: int, key: str, default=None):
    async with pool.acquire() as conn:
        value = await conn.fetchval(
            "SELECT config_value FROM system_config WHERE guild_id=$1 AND config_key=$2",
            guild_id, key
        )
    return value if value is not None else default


async def set_config(pool, guild_id: int, key: str, value: str):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO system_config (guild_id, config_key, config_value)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, config_key)
            DO UPDATE SET config_value=EXCLUDED.config_value
        """, guild_id, key, value)


def parse_id(value: str):
    if not value or value.lower() in {"none", "desativado", "off"}:
        return None
    if not value.isdigit():
        raise ValueError("Informe um ID numérico válido ou `none`.")
    return int(value)


def make_embed(title: str, description: str = "", color=PURPLE):
    embed = discord.Embed(
        title=title,
        description=description,
        colour=color,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text="Central Administrativa")
    return embed


async def send_log(bot, guild: discord.Guild, title: str, description: str,
                   color=PURPLE, fields=None):
    pool = bot.db_pool
    channel_id = await get_config(pool, guild.id, "logs_channel_id")
    if not channel_id:
        return
    channel = guild.get_channel(int(channel_id))
    if channel is None:
        return
    embed = make_embed(title, description, color)
    for name, value, inline in (fields or []):
        embed.add_field(name=name, value=value, inline=inline)
    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        pass


async def save_punishment(pool, guild_id, user_id, moderator_id,
                          kind, reason, duration=None, status="active"):
    async with pool.acquire() as conn:
        return await conn.fetchval("""
            INSERT INTO system_punishments
            (guild_id, user_id, moderator_id, punishment_type, reason,
             duration_minutes, status)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            RETURNING id
        """, guild_id, user_id, moderator_id, kind, reason, duration, status)


# ============================================================
# APROVAÇÃO DE PUNIÇÕES
# ============================================================

class PunishmentApprovalView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def decide(self, interaction: discord.Interaction, approved: bool):
        bot = interaction.client
        pool = bot.db_pool
        guild = interaction.guild

        approver_role_id = await get_config(
            pool, guild.id, "approver_role_id"
        )
        approver_role = (
            guild.get_role(int(approver_role_id))
            if approver_role_id else None
        )
        is_admin = interaction.user.guild_permissions.administrator
        if not is_admin and (
            approver_role is None or approver_role not in interaction.user.roles
        ):
            return await interaction.response.send_message(
                "Você não tem autorização para analisar solicitações.",
                ephemeral=True
            )

        async with pool.acquire() as conn:
            request = await conn.fetchrow("""
                SELECT * FROM system_punishment_requests
                WHERE message_id=$1 AND guild_id=$2
            """, interaction.message.id, guild.id)

        if request is None:
            return await interaction.response.send_message(
                "Solicitação não encontrada no banco de dados.",
                ephemeral=True
            )
        if request["status"] != "pending":
            return await interaction.response.send_message(
                "Esta solicitação já foi analisada.",
                ephemeral=True
            )
        if request["requester_id"] == interaction.user.id:
            return await interaction.response.send_message(
                "Você não pode aprovar ou rejeitar sua própria solicitação.",
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        result_status = "approved" if approved else "rejected"
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE system_punishment_requests
                SET status=$1, reviewer_id=$2, reviewed_at=NOW()
                WHERE id=$3 AND status='pending'
            """, result_status, interaction.user.id, request["id"])

        if approved:
            target = guild.get_member(request["target_id"])
            kind = request["punishment_type"]
            reason = request["reason"]
            try:
                if kind == "kick":
                    if target is None:
                        raise ValueError("O membro não está mais no servidor.")
                    await target.kick(reason=f"Solicitação #{request['id']}: {reason}")
                elif kind == "ban":
                    await guild.ban(
                        discord.Object(id=request["target_id"]),
                        reason=f"Solicitação #{request['id']}: {reason}"
                    )
                elif kind == "timeout":
                    if target is None:
                        raise ValueError("O membro não está mais no servidor.")
                    minutes = request["duration_minutes"] or 1440
                    await target.timeout(
                        timedelta(minutes=minutes),
                        reason=f"Solicitação #{request['id']}: {reason}"
                    )
                else:
                    raise ValueError("Tipo de punição desconhecido.")

                await save_punishment(
                    pool, guild.id, request["target_id"], interaction.user.id,
                    kind, reason, request["duration_minutes"]
                )
                result_text = "Aprovada e aplicada"
                result_color = GREEN
            except (discord.Forbidden, discord.HTTPException, ValueError) as exc:
                result_text = f"Aprovada, mas não foi possível aplicar: {exc}"
                result_color = RED
        else:
            result_text = "Rejeitada"
            result_color = RED

        embed = interaction.message.embeds[0] if interaction.message.embeds else make_embed(
            "Solicitação de punição"
        )
        embed.colour = result_color
        embed.add_field(
            name="Decisão",
            value=f"{result_text}\nResponsável: {interaction.user.mention}",
            inline=False
        )
        await interaction.message.edit(embed=embed, view=None)
        await send_log(
            bot, guild, "Análise de solicitação",
            f"Solicitação **#{request['id']}**: {result_text}.\n"
            f"Analisada por {interaction.user.mention}.",
            result_color
        )
        await interaction.followup.send(result_text, ephemeral=True)

    @discord.ui.button(
        label="Aprovar e aplicar",
        style=discord.ButtonStyle.success,
        custom_id="systems:punishment:approve"
    )
    async def approve(self, interaction, button):
        await self.decide(interaction, True)

    @discord.ui.button(
        label="Rejeitar",
        style=discord.ButtonStyle.danger,
        custom_id="systems:punishment:reject"
    )
    async def reject(self, interaction, button):
        await self.decide(interaction, False)


# ============================================================
# SISTEMAS PRINCIPAIS
# ============================================================

class Systems(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pool = bot.db_pool
        self.temp_voice_ids = set()

    # --------------------------------------------------------
    # CONFIGURAÇÕES
    # --------------------------------------------------------

    @app_commands.command(
        name="configurar",
        description="Configura os canais e cargos dos sistemas."
    )
    @app_commands.describe(
        chave="Configuração que deseja alterar",
        valor="ID do canal/cargo ou URL do banner; use none para limpar"
    )
    @app_commands.choices(chave=[
        app_commands.Choice(name="Canal de logs", value="logs_channel_id"),
        app_commands.Choice(name="Canal de punições", value="punishment_channel_id"),
        app_commands.Choice(name="Canal de solicitações", value="request_channel_id"),
        app_commands.Choice(name="Cargo aprovador", value="approver_role_id"),
        app_commands.Choice(name="Cargo da staff", value="staff_role_id"),
        app_commands.Choice(name="Canal da lista staff", value="staff_list_channel_id"),
        app_commands.Choice(name="Lobby de voz", value="voice_lobby_id"),
        app_commands.Choice(name="Categoria das calls", value="voice_category_id"),
        app_commands.Choice(name="Banner padrão (URL)", value="banner_url"),
    ])
    @app_commands.checks.has_permissions(administrator=True)
    async def configurar(self, interaction: discord.Interaction,
                         chave: app_commands.Choice[str], valor: str):
        if chave.value == "banner_url" and valor.lower() not in {"none", "off"}:
            if not valor.startswith(("https://", "http://")):
                return await interaction.response.send_message(
                    "A URL do banner precisa começar com http:// ou https://.",
                    ephemeral=True
                )
        elif valor.lower() not in {"none", "off", "desativado"}:
            try:
                object_id = parse_id(valor)
            except ValueError as exc:
                return await interaction.response.send_message(str(exc), ephemeral=True)
            if chave.value.endswith("_channel_id") or chave.value in {
                "voice_lobby_id", "voice_category_id"
            }:
                obj = interaction.guild.get_channel(object_id)
                if obj is None:
                    return await interaction.response.send_message(
                        "Não encontrei esse canal/categoria neste servidor.",
                        ephemeral=True
                    )
            if chave.value.endswith("_role_id"):
                if interaction.guild.get_role(object_id) is None:
                    return await interaction.response.send_message(
                        "Não encontrei esse cargo neste servidor.",
                        ephemeral=True
                    )

        await set_config(self.pool, interaction.guild.id, chave.value, valor)
        await interaction.response.send_message(
            f"Configuração **{chave.name}** atualizada.",
            ephemeral=True
        )
        await send_log(
            self.bot, interaction.guild, "Configuração alterada",
            f"{interaction.user.mention} alterou **{chave.name}**."
        )

    # --------------------------------------------------------
    # MODERAÇÃO DIRETA
    # --------------------------------------------------------

    @app_commands.command(name="advertir", description="Registra uma advertência.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def advertir(self, interaction: discord.Interaction,
                       membro: discord.Member, motivo: str):
        if membro.bot:
            return await interaction.response.send_message(
                "Não é possível advertir bots.", ephemeral=True
            )
        record_id = await save_punishment(
            self.pool, interaction.guild.id, membro.id,
            interaction.user.id, "advertência", motivo
        )
        embed = make_embed("Advertência registrada", color=YELLOW)
        embed.add_field(name="Membro", value=membro.mention)
        embed.add_field(name="Responsável", value=interaction.user.mention)
        embed.add_field(name="Motivo", value=motivo, inline=False)
        embed.add_field(name="Registro", value=f"#{record_id}")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await send_log(self.bot, interaction.guild, "Advertência aplicada",
                       f"{membro.mention} recebeu uma advertência.\n"
                       f"Responsável: {interaction.user.mention}\nMotivo: {motivo}",
                       YELLOW)

    @app_commands.command(name="timeout", description="Aplica timeout de até 60 minutos.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def timeout_member(self, interaction: discord.Interaction,
                             membro: discord.Member, minutos: app_commands.Range[int, 1, 60],
                             motivo: str):
        if membro.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            return await interaction.response.send_message(
                "Você não pode moderar alguém com cargo igual ou superior ao seu.",
                ephemeral=True
            )
        try:
            await membro.timeout(
                timedelta(minutes=minutos),
                reason=f"{interaction.user}: {motivo}"
            )
        except discord.Forbidden:
            return await interaction.response.send_message(
                "Não tenho permissão ou posição hierárquica para aplicar esse timeout.",
                ephemeral=True
            )
        record_id = await save_punishment(
            self.pool, interaction.guild.id, membro.id, interaction.user.id,
            "timeout", motivo, minutos
        )
        await interaction.response.send_message(
            f"Timeout aplicado em {membro.mention} por {minutos} minuto(s). Registro #{record_id}.",
            ephemeral=True
        )
        await send_log(self.bot, interaction.guild, "Timeout aplicado",
                       f"Membro: {membro.mention}\nModerador: {interaction.user.mention}\n"
                       f"Duração: {minutos} minuto(s)\nMotivo: {motivo}", YELLOW)

    @app_commands.command(name="untimeout", description="Remove o timeout de um membro.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def untimeout_member(self, interaction: discord.Interaction,
                               membro: discord.Member, motivo: str = "Não informado"):
        try:
            await membro.timeout(None, reason=f"{interaction.user}: {motivo}")
        except discord.Forbidden:
            return await interaction.response.send_message(
                "Não tenho permissão para remover esse timeout.", ephemeral=True
            )
        await interaction.response.send_message(
            f"Timeout removido de {membro.mention}.", ephemeral=True
        )
        await send_log(self.bot, interaction.guild, "Timeout removido",
                       f"Membro: {membro.mention}\nResponsável: {interaction.user.mention}\n"
                       f"Motivo: {motivo}", GREEN)

    # --------------------------------------------------------
    # SOLICITAÇÕES DE PUNIÇÃO COM APROVAÇÃO
    # --------------------------------------------------------

    @app_commands.command(
        name="solicitar_punicao",
        description="Envia uma punição grave para aprovação."
    )
    @app_commands.choices(tipo=[
        app_commands.Choice(name="Expulsão (kick)", value="kick"),
        app_commands.Choice(name="Banimento (ban)", value="ban"),
        app_commands.Choice(name="Timeout prolongado", value="timeout"),
    ])
    async def solicitar_punicao(
        self, interaction: discord.Interaction,
        membro: discord.Member,
        tipo: app_commands.Choice[str],
        motivo: str,
        duracao_minutos: app_commands.Range[int, 61, 40320] = None,
        evidencia_url: str = None
    ):
        channel_id = await get_config(
            self.pool, interaction.guild.id, "request_channel_id"
        )
        channel = interaction.guild.get_channel(int(channel_id)) if channel_id else None
        if channel is None:
            return await interaction.response.send_message(
                solicitações.",
                ephemeral=True
            )

        if membro.bot:
            return await interaction.response.send_message(
                "Não é possível solicitar punição para bots.",
                ephemeral=True
            )

        if membro.id == interaction.user.id:
            return await interaction.response.send_message(
                "Você não pode solicitar punição contra si mesmo.",
                ephemeral=True
            )

        if tipo.value == "timeout" and duracao_minutos is None:
            return await interaction.response.send_message(
                "Informe a duração do timeout.",
                ephemeral=True
            )

        if evidencia_url and not evidencia_url.startswith(("https://", "http://")):
            return await interaction.response.send_message(
                "A evidência precisa ser uma URL válida.",
                ephemeral=True
            )

        async with self.pool.acquire() as conn:
            request_id = await conn.fetchval("""
                INSERT INTO system_punishment_requests
                (guild_id, target_id, requester_id, punishment_type,
                 reason, evidence_url, duration_minutes)
                VALUES ($1,$2,$3,$4,$5,$6,$7)
                RETURNING id
            """,
                interaction.guild.id,
                membro.id,
                interaction.user.id,
                tipo.value,
                motivo,
                evidencia_url,
                duracao_minutos
            )

        embed = make_embed(
            f"Solicitação de punição #{request_id}",
            "Uma nova solicitação aguarda análise."
        )
        embed.add_field(name="Membro", value=f"{membro.mention} (`{membro.id}`)")
        embed.add_field(name="Solicitante", value=interaction.user.mention)
        embed.add_field(name="Tipo", value=tipo.name)
        embed.add_field(name="Motivo", value=motivo, inline=False)

        if duracao_minutos:
            embed.add_field(
                name="Duração",
                value=f"{duracao_minutos} minutos"
            )

        if evidencia_url:
            embed.add_field(
                name="Evidência",
                value=f"[Abrir evidência]({evidencia_url})",
                inline=False
            )

        message = await channel.send(
            embed=embed,
            view=PunishmentApprovalView()
        )

        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE system_punishment_requests
                SET message_id=$1
                WHERE id=$2
            """, message.id, request_id)

        await interaction.response.send_message(
            f"Solicitação **#{request_id}** enviada para análise.",
            ephemeral=True
        )

        await send_log(
            self.bot,
            interaction.guild,
            "Solicitação criada",
            f"Solicitação **#{request_id}** criada por {interaction.user.mention}.\n"
            f"Membro: {membro.mention}\nTipo: {tipo.name}"
        )

    # --------------------------------------------------------
    # HISTÓRICO DE PUNIÇÕES
    # --------------------------------------------------------

    @app_commands.command(
        name="historico_punicoes",
        description="Consulta o histórico de punições de um membro."
    )
    @app_commands.checks.has_permissions(moderate_members=True)
    async def historico_punicoes(
        self,
        interaction: discord.Interaction,
        membro: discord.Member
    ):
        async with self.pool.acquire() as conn:
            records = await conn.fetch("""
                SELECT * FROM system_punishments
                WHERE guild_id=$1 AND user_id=$2
                ORDER BY created_at DESC
                LIMIT 10
            """, interaction.guild.id, membro.id)

        if not records:
            return await interaction.response.send_message(
                f"Nenhuma punição registrada para {membro.mention}.",
                ephemeral=True
            )

        embed = make_embed(
            f"Histórico de {membro}",
            f"Últimos {len(records)} registros."
        )

        for record in records:
            date = record["created_at"].strftime("%d/%m/%Y %H:%M")
            duration = (
                f"\nDuração: {record['duration_minutes']} minutos"
                if record["duration_minutes"] else ""
            )

            embed.add_field(
                name=f"Registro #{record['id']} • {record['punishment_type']}",
                value=(
                    f"Motivo: {record['reason']}\n"
                    f"Moderador: <@{record['moderator_id']}>\n"
                    f"Status: {record['status']}\n"
                    f"Data: {date}{duration}"
                ),
                inline=False
            )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )

    # --------------------------------------------------------
    # LISTA DA STAFF
    # --------------------------------------------------------

    @app_commands.command(
        name="atualizar_lista_staff",
        description="Atualiza a lista de membros da staff."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def atualizar_lista_staff(self, interaction: discord.Interaction):
        role_id = await get_config(
            self.pool, interaction.guild.id, "staff_role_id"
        )
        channel_id = await get_config(
            self.pool, interaction.guild.id, "staff_list_channel_id"
        )

        if not role_id or not channel_id:
            return await interaction.response.send_message(
                "Configure o cargo da staff e o canal da lista primeiro.",
                ephemeral=True
            )

        role = interaction.guild.get_role(int(role_id))
        channel = interaction.guild.get_channel(int(channel_id))

        if role is None or channel is None:
            return await interaction.response.send_message(
                "O cargo ou canal configurado não existe mais.",
                ephemeral=True
            )

        members = sorted(
            role.members,
            key=lambda member: (
                member.top_role.position,
                member.display_name.lower()
            ),
            reverse=True
        )

        embed = make_embed(
            "Equipe administrativa",
            f"Total de membros: **{len(members)}**"
        )

        if members:
            lines = [
                f"{member.mention} — **{member.top_role.name}**"
                for member in members
            ]
            description = "\n".join(lines)

            if len(description) <= 4000:
                embed.description = description
            else:
                embed.description = (
                    "\n".join(lines[:50])
                    + "\n\nLista limitada aos primeiros 50 membros."
                )
        else:
            embed.description = "Nenhum membro encontrado."

        await channel.send(embed=embed)

        async with self.pool.acquire() as conn:
            for member in members:
                await conn.execute("""
                    INSERT INTO system_staff_registry
                    (guild_id, user_id, active)
                    VALUES ($1,$2,TRUE)
                    ON CONFLICT (guild_id, user_id)
                    DO UPDATE SET active=TRUE
                """, interaction.guild.id, member.id)

        await interaction.response.send_message(
            "Lista da staff atualizada.",
            ephemeral=True
        )

    @app_commands.command(
        name="staff_info",
        description="Consulta informações de um membro da staff."
    )
    @app_commands.checks.has_permissions(moderate_members=True)
    async def staff_info(
        self,
        interaction: discord.Interaction,
        membro: discord.Member
    ):
        async with self.pool.acquire() as conn:
            registry = await conn.fetchrow("""
                SELECT * FROM system_staff_registry
                WHERE guild_id=$1 AND user_id=$2
            """, interaction.guild.id, membro.id)

            history = await conn.fetch("""
                SELECT * FROM system_staff_history
                WHERE guild_id=$1 AND user_id=$2
                ORDER BY created_at DESC
                LIMIT 5
            """, interaction.guild.id, membro.id)

        embed = make_embed(
            f"Informações da staff: {membro.display_name}"
        )
        embed.add_field(
            name="Membro",
            value=membro.mention,
            inline=True
        )
        embed.add_field(
            name="Cargo mais alto",
            value=membro.top_role.mention,
            inline=True
        )
        embed.add_field(
            name="Registro",
            value=(
                "Ativo no cadastro"
                if registry and registry["active"]
                else "Sem registro ativo"
            ),
            inline=True
        )

        if registry:
            embed.add_field(
                name="Entrada no cadastro",
                value=registry["joined_at"].strftime("%d/%m/%Y"),
                inline=True
            )

        if history:
            lines = []
            for item in history:
                lines.append(
                    f"**{item['action']}** — <@{item['role_id']}>\n"
                    f"<t:{int(item['created_at'].timestamp())}:d>"
                )
            embed.add_field(
                name="Histórico de alterações",
                value="\n".join(lines),
                inline=False
            )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )

    # --------------------------------------------------------
    # CRIADOR DE EMBEDS COM WEBHOOK
    # --------------------------------------------------------

    @app_commands.command(
        name="embed",
        description="Cria um embed personalizado usando webhook."
    )
    @app_commands.checks.has_permissions(manage_webhooks=True)
    @app_commands.describe(
        canal="Canal onde o embed será enviado",
        titulo="Título do embed",
        descricao="Texto principal",
        cor="Cor hexadecimal, exemplo: 8155C7",
        nome_webhook="Nome que aparecerá como autor",
        avatar_url="URL da imagem de perfil do webhook"
    )
    async def embed_creator(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel,
        titulo: str,
        descricao: str,
        cor: str = "8155C7",
        nome_webhook: str = "Central Administrativa",
        avatar_url: str = None
    ):
        if not interaction.guild.me.guild_permissions.manage_webhooks:
            return await interaction.response.send_message(
                "Preciso da permissão **Gerenciar Webhooks**.",
                ephemeral=True
            )

        cor = cor.replace("#", "").strip()

        if not re.fullmatch(r"[0-9a-fA-F]{6}", cor):
            return await interaction.response.send_message(
                "Cor inválida. Use seis caracteres hexadecimais, como `8155C7`.",
                ephemeral=True
            )

        if avatar_url and not avatar_url.startswith(("https://", "http://")):
            return await interaction.response.send_message(
                "A URL do avatar precisa começar com http:// ou https://.",
                ephemeral=True
            )

        if len(titulo) > 256 or len(descricao) > 4000:
            return await interaction.response.send_message(
                "O título ou a descrição ultrapassou o limite permitido.",
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        embed = discord.Embed(
            title=titulo,
            description=descricao,
            colour=int(cor, 16),
            timestamp=datetime.now(timezone.utc)
        )

        banner = await get_config(
            self.pool, interaction.guild.id, "banner_url"
        )
        if banner:
            embed.set_image(url=banner)

        try:
            webhooks = await canal.webhooks()
            webhook = discord.utils.get(
                webhooks,
                name="Central Embed Creator"
            )

            if webhook is None:
                webhook = await canal.create_webhook(
                    name="Central Embed Creator",
                    reason=f"Criado por {interaction.user}"
                )

            await webhook.send(
                embed=embed,
                username=nome_webhook[:80],
                avatar_url=avatar_url,
                allowed_mentions=discord.AllowedMentions.none()
            )

        except discord.Forbidden:
            return await interaction.followup.send(
                "Não tenho permissão para criar ou utilizar webhooks nesse canal.",
                ephemeral=True
            )
        except discord.HTTPException as exc:
            return await interaction.followup.send(
                f"Não foi possível enviar o embed: {exc}",
                ephemeral=True
            )

        await interaction.followup.send(
            f"Embed enviado em {canal.mention}.",
            ephemeral=True
        )

        await send_log(
            self.bot,
            interaction.guild,
            "Embed enviado por webhook",
            f"Responsável: {interaction.user.mention}\n"
            f"Canal: {canal.mention}\nTítulo: {titulo}"
        )

    # --------------------------------------------------------
    # SISTEMA AFK
    # --------------------------------------------------------

    @app_commands.command(
        name="afk",
        description="Define seu status como AFK."
    )
    async def afk(
        self,
        interaction: discord.Interaction,
        motivo: str = "Não informado"
    ):
        if len(motivo) > 300:
            return await interaction.response.send_message(
                "O motivo pode ter no máximo 300 caracteres.",
                ephemeral=True
            )

        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO system_afk (guild_id, user_id, reason)
                VALUES ($1,$2,$3)
                ON CONFLICT (guild_id, user_id)
                DO UPDATE SET reason=$3, since=NOW()
            """, interaction.guild.id, interaction.user.id, motivo)

        await interaction.response.send_message(
            f"Seu status AFK foi ativado. Motivo: **{motivo}**",
            ephemeral=True
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot:
            return

        async with self.pool.acquire() as conn:
            own_afk = await conn.fetchrow("""
                SELECT * FROM system_afk
                WHERE guild_id=$1 AND user_id=$2
            """, message.guild.id, message.author.id)

            if own_afk:
                await conn.execute("""
                    DELETE FROM system_afk
                    WHERE guild_id=$1 AND user_id=$2
                """, message.guild.id, message.author.id)

        if own_afk:
            await message.channel.send(
                f"Bem-vindo de volta, {message.author.mention}. "
                "Seu status AFK foi removido.",
                delete_after=8
            )

        mentioned_ids = {
            member.id
            for member in message.mentions
            if member.id != message.author.id
        }

        if not mentioned_ids:
            return

        async with self.pool.acquire() as conn:
            afk_users = await conn.fetch("""
                SELECT user_id, reason, since
                FROM system_afk
                WHERE guild_id=$1 AND user_id = ANY($2::BIGINT[])
            """, message.guild.id, list(mentioned_ids))

        for user in afk_users:
            elapsed = int(
                (datetime.now(timezone.utc) - user["since"]).total_seconds()
            )
            hours, remainder = divmod(elapsed, 3600)
            minutes = remainder // 60

            await message.channel.send(
                f"<@{user['user_id']}> está AFK.\n"
                f"Motivo: **{user['reason']}**\n"
                f"Tempo: **{hours}h {minutes}min**",
                delete_after=12
            )

    # --------------------------------------------------------
    # CALLS TEMPORÁRIAS
    # --------------------------------------------------------

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState
    ):
        if member.bot:
            return

        guild = member.guild

        lobby_id = await get_config(
            self.pool, guild.id, "voice_lobby_id"
        )
        category_id = await get_config(
            self.pool, guild.id, "voice_category_id"
        )

        # Entrou no canal de criação.
        if after.channel and lobby_id:
            if after.channel.id == int(lobby_id):
                category = (
                    guild.get_channel(int(category_id))
                    if category_id else after.channel.category
                )

                try:
                    overwrites = {
                        guild.default_role: discord.PermissionOverwrite(
                            view_channel=True,
                            connect=True
                        ),
                        member: discord.PermissionOverwrite(
                            view_channel=True,
                            connect=True,
                            manage_channels=True,
                            move_members=True
                        )
                    }

                    temp_channel = await guild.create_voice_channel(
                        name=f"🔊・{member.display_name}"[:100],
                        category=category,
                        overwrites=overwrites,
                        reason=f"Call temporária de {member}"
                    )

                    await member.move_to(temp_channel)

                except discord.Forbidden:
                    try:
                        await member.send(
                            "Não consegui criar sua call. "
                            "Verifique as permissões do bot."
                        )
                    except discord.HTTPException:
                        pass
                except discord.HTTPException:
                    pass

        # Saiu de uma call temporária: exclui se ficou vazia.
        if before.channel:
            old_channel = before.channel

            if old_channel.name.startswith("🔊・") and not old_channel.members:
                try:
                    await old_channel.delete(
                        reason="Call temporária vazia"
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass

    # --------------------------------------------------------
    # LOGS AUTOMÁTICOS
    # --------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await send_log(
            self.bot,
            member.guild,
            "Membro entrou",
            f"{member.mention} entrou no servidor.\n"
            f"ID: `{member.id}`"
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await send_log(
            self.bot,
            member.guild,
            "Membro saiu",
            f"**{member}** saiu do servidor.\n"
            f"ID: `{member.id}`",
            RED
        )

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord
        if message.guild is None or message.author.bot:
            return

        content = message.content or "[Mensagem sem texto]"
        if len(content) > 1500:
            content = content[:1500] + "..."

        await send_log(
            self.bot,
            message.guild,
            "Mensagem apagada",
            f"Autor: {message.author.mention}\n"
            f"Canal: {message.channel.mention}\n"
            f"Conteúdo:\n```{content}```",
            RED
        )

    @commands.Cog.listener()
    async def on_message_edit(
        self,
        before: discord.Message,
        after: discord.Message
    ):
        if before.guild is None or before.author.bot:
            return

        if before.content == after.content:
            return

        old = before.content or "[Sem texto]"
        new = after.content or "[Sem texto]"

        await send_log(
            self.bot,
            before.guild,
            "Mensagem editada",
            f"Autor: {before.author.mention}\n"
            f"Canal: {before.channel.mention}\n"
            f"Antes:\n```{old[:1000]}```\n"
            f"Depois:\n```{new[:1000]}```",
            YELLOW
        )

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        await send_log(
            self.bot,
            channel.guild,
            "Canal criado",
            f"Canal: {channel.name}"
        )

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        await send_log(
            self.bot,
            channel.guild,
            "Canal excluído",
            f"Nome: **{channel.name}**\nID: `{channel.id}`",
            RED
        )

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        changes = []

        if before.name != after.name:
            changes.append(
                f"Nome: `{before.name}` → `{after.name}`"
            )

        if getattr(before, "topic", None) != getattr(after, "topic", None):
            changes.append("Tópico do canal alterado.")

        if not changes:
            return

        await send_log(
            self.bot,
            after.guild,
            "Canal atualizado",
            f"Canal: {after.name}\n" + "\n".join(changes),
            YELLOW
        )

    @commands.Cog.listener()
    async def on_member_update(
        self,
        before: discord.Member,
        after: discord.Member
    ):
        if before.roles == after.roles:
            return

        before_ids = {role.id for role in before.roles}
        after_ids = {role.id for role in after.roles}

        added = [
            role for role in after.roles
            if role.id not in before_ids
        ]
        removed = [
            role for role in before.roles
            if role.id not in after_ids
        ]

        details = []

        if added:
            details.append(
                "Cargos adicionados: "
                + ", ".join(role.mention for role in added)
            )

        if removed:
            details.append(
                "Cargos removidos: "
                + ", ".join(role.name for role in removed)
            )

        await send_log(
            self.bot,
            after.guild,
            "Cargos alterados",
            f"Membro: {after.mention}\n" + "\n".join(details),
            YELLOW
        )


# ============================================================
# TRATAMENTO DE ERROS
# ============================================================

async def systems_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):
    if isinstance(error, app_commands.MissingPermissions):
        message = "Você não possui as permissões necessárias."
    else:
        message = "Ocorreu um erro ao executar o comando."

    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                message,
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                message,
                ephemeral=True
            )
    except discord.HTTPException:
        pass


# ============================================================
# CARREGAMENTO DA EXTENSÃO
# ============================================================

async def setup(bot: commands.Bot):
    if not hasattr(bot, "db_pool") or bot.db_pool is None:
        raise RuntimeError(
            "A conexão com o banco de dados não foi inicializada."
        )

    await create_tables(bot.db_pool)

    cog = Systems(bot)
    await bot.add_cog(cog)

    bot.tree.on_error = systems_app_command_error

    bot.add_view(PunishmentApprovalView())

    print("[SISTEMAS] Sistemas carregados.")
