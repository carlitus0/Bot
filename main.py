# =========================================================
# 01. IMPORTS E CONFIGURAÇÕES GERAIS
# =========================================================

import os
import io
import re
import json
import html
import asyncio
import unicodedata
import traceback

from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import commands
from discord import app_commands

import asyncpg


# =========================================================
# 1.1 VARIÁVEIS DE AMBIENTE
# =========================================================

TOKEN = os.getenv("DISCORD_TOKEN")
DB_PASSWORD = os.getenv("SUPABASE_DB_PASSWORD")

DB_HOST = os.getenv(
    "SUPABASE_DB_HOST",
    "aws-0-us-west-2.pooler.supabase.com"
)

DB_PORT = int(os.getenv("SUPABASE_DB_PORT", "5432"))

DB_USER = os.getenv(
    "SUPABASE_DB_USER",
    "postgres.sdtivbtxtujgdizxyhed"
)

DB_NAME = os.getenv("SUPABASE_DB_NAME", "postgres")

PREFIX = "!"

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN não configurado.")

if not DB_PASSWORD:
    raise RuntimeError("SUPABASE_DB_PASSWORD não configurado.")


# =========================================================
# 1.2 CONFIGURAÇÕES VISUAIS
# =========================================================

EMBED_COLOR = discord.Colour.from_rgb(128, 128, 128)

TICKET_IMAGE_URL = (
    "https://cdn.discordapp.com/attachments/1573540268878077984/"
    "1574494273016172624/Central_de_Atendimento_Roxa.png"
    "?ex=6b05d98f&is=6b04880f"
    "&hm=d2a83f98a563cb8ac43cce815ba3bb52"
    "e78e9b3d8b88be000e215dbcee20623878&"
)


# =========================================================
# 1.3 BANCO DE DADOS
# =========================================================

db_pool: Optional[asyncpg.Pool] = None


# =========================================================
# 1.4 TIPOS DE TICKETS
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
# 1.5 INTENTS DO DISCORD
# =========================================================

intents = discord.Intents.default()

intents.guilds = True
intents.members = True
intents.message_content = True
intents.moderation = True
# =========================================================
# 02. BANCO DE DADOS SUPABASE
# =========================================================

async def conectar_db():
    global db_pool

    db_pool = await asyncpg.create_pool(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        ssl="require",
        min_size=1,
        max_size=5
    )

    async with db_pool.acquire() as conn:

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_config (
                guild_id BIGINT PRIMARY KEY,
                data JSONB NOT NULL DEFAULT '{}'::jsonb,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS ticket_counters (
                guild_id BIGINT PRIMARY KEY,
                last_number BIGINT NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS tickets (
                id BIGSERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                channel_id BIGINT UNIQUE NOT NULL,
                user_id BIGINT NOT NULL,
                ticket_number BIGINT NOT NULL,
                ticket_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                claimed_by BIGINT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                closed_at TIMESTAMPTZ,
                closed_by BIGINT,
                close_reason TEXT
            );

            CREATE TABLE IF NOT EXISTS moderation_history (
                id BIGSERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                moderator_id BIGINT NOT NULL,
                target_id BIGINT NOT NULL,
                action TEXT NOT NULL,
                reason TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS bot_logs (
                id BIGSERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                event TEXT NOT NULL,
                details TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)

    print("Conexão com Supabase estabelecida.")


# =========================================================
# 2.1 GERAR NUMERAÇÃO DOS TICKETS
# =========================================================

async def gerar_numero_ticket(guild_id: int) -> int:

    async with db_pool.acquire() as conn:

        resultado = await conn.fetchrow("""
            INSERT INTO ticket_counters (
                guild_id,
                last_number
            )
            VALUES ($1, 1)

            ON CONFLICT (guild_id)
            DO UPDATE SET
                last_number = ticket_counters.last_number + 1

            RETURNING last_number;
        """, guild_id)

    return resultado["last_number"]


# =========================================================
# 2.2 BUSCAR CONFIGURAÇÕES
# =========================================================

async def buscar_config(guild_id: int) -> dict:

    async with db_pool.acquire() as conn:

        resultado = await conn.fetchrow("""
            SELECT data
            FROM bot_config
            WHERE guild_id = $1
        """, guild_id)

    if resultado:
        return dict(resultado["data"])

    return {}


# =========================================================
# 2.3 SALVAR CONFIGURAÇÕES
# =========================================================

async def salvar_config(guild_id: int, config: dict):

    async with db_pool.acquire() as conn:

        await conn.execute("""
            INSERT INTO bot_config (
                guild_id,
                data
            )
            VALUES ($1, $2::jsonb)

            ON CONFLICT (guild_id)
            DO UPDATE SET
                data = EXCLUDED.data,
                updated_at = NOW()
        """, guild_id, json.dumps(config, ensure_ascii=False))


# =========================================================
# 2.4 REGISTRAR LOG NO BANCO
# =========================================================

async def registrar_log(
    guild_id: int,
    evento: str,
    detalhes: str
):
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO bot_logs (
                guild_id,
                event,
                details
            )
            VALUES ($1, $2, $3)
            """,
            guild_id,
            evento,
            detalhes
        )
# =========================================================
# 03. CONFIGURAÇÕES MANUAIS
# =========================================================

CONFIG_PADRAO = {
    "ticket_panel_channel": None,
    "ticket_staff_role": None,
    "ticket_transcript_channel": None,
    "ticket_log_channel": None,

    "ticket_categories": {
        "denuncia": None,
        "equipe": None,
        "parceria": None,
        "revisao": None,
        "duvidas": None,
        "suporte": None,
        "bug": None
    },

    "welcome_channel": None,
    "leave_channel": None,
    "member_log_channel": None,
    "moderation_log_channel": None,
    "staff_log_channel": None,

    "admin_role": None,
    "director_role": None,
    "moderator_role": None,
    "support_role": None,

    "blocked_words": [],
    "warn_limit": 3
}


# =========================================================
# 3.1 OBTER CONFIGURAÇÃO COMPLETA
# =========================================================

async def obter_config(guild_id: int) -> dict:

    config_salva = await buscar_config(guild_id)

    config = json.loads(json.dumps(CONFIG_PADRAO))

    for chave, valor in config_salva.items():

        if chave == "ticket_categories":
            config["ticket_categories"].update(valor)

        else:
            config[chave] = valor

    return config


# =========================================================
# 3.2 ALTERAR UMA CONFIGURAÇÃO
# =========================================================

async def alterar_config(
    guild_id: int,
    chave: str,
    valor
):

    config = await obter_config(guild_id)

    config[chave] = valor

    await salvar_config(guild_id, config)

    return config


# =========================================================
# 3.3 ALTERAR CATEGORIA DE TICKET
# =========================================================

async def alterar_categoria_ticket(
    guild_id: int,
    tipo: str,
    categoria_id: int
):

    if tipo not in CONFIG_PADRAO["ticket_categories"]:
        raise ValueError("Tipo de ticket inválido.")

    config = await obter_config(guild_id)

    config["ticket_categories"][tipo] = categoria_id

    await salvar_config(guild_id, config)


# =========================================================
# 3.4 VERIFICAR EQUIPE
# =========================================================

async def membro_equipe(
    member: discord.Member,
    config: dict
) -> bool:

    if member.guild_permissions.administrator:
        return True

    cargos = [
        config.get("ticket_staff_role"),
        config.get("admin_role"),
        config.get("director_role"),
        config.get("moderator_role"),
        config.get("support_role")
    ]

    cargos = [int(cargo) for cargo in cargos if cargo]

    return any(role.id in cargos for role in member.roles)


# =========================================================
# 3.5 ENVIAR LOG PARA CANAL CONFIGURADO
# =========================================================

async def enviar_log(
    guild: discord.Guild,
    chave: str,
    embed: discord.Embed
):

    config = await obter_config(guild.id)

    canal_id = config.get(chave)

    if not canal_id:
        return

    canal = guild.get_channel(int(canal_id))

    if canal:
        try:
            await canal.send(embed=embed)
        except discord.Forbidden:
            print(f"Sem permissão para enviar log em {canal.id}.")


# =========================================================
# 04. SISTEMA DE CRIAÇÃO DE TICKETS
# =========================================================

TICKET_LABELS = {
    value: label
    for label, value in TICKET_TYPES
}


# =========================================================
# 4.1 VERIFICAR TICKET ABERTO
# =========================================================

async def buscar_ticket_aberto(
    guild_id: int,
    user_id: int
):

    async with db_pool.acquire() as conn:

        return await conn.fetchrow("""
            SELECT *
            FROM tickets
            WHERE guild_id = $1
            AND user_id = $2
            AND status = 'open'
            LIMIT 1
        """, guild_id, user_id)


# =========================================================
# 4.2 CRIAR TICKET
# =========================================================

async def criar_ticket(
    guild: discord.Guild,
    usuario: discord.Member,
    tipo: str
):

    if tipo not in TICKET_LABELS:
        raise ValueError("Tipo de atendimento inválido.")

    config = await obter_config(guild.id)

    # Verificar categoria configurada
    categoria_id = config["ticket_categories"].get(tipo)

    if not categoria_id:
        raise ValueError(
            f"A categoria de **{TICKET_LABELS[tipo]}** não foi configurada."
        )

    categoria = guild.get_channel(int(categoria_id))

    if not isinstance(categoria, discord.CategoryChannel):
        raise ValueError(
            "A categoria configurada não existe. Configure novamente."
        )

    # Impedir vários tickets abertos pelo mesmo usuário
    ticket_existente = await buscar_ticket_aberto(
        guild.id,
        usuario.id
    )

    if ticket_existente:

        canal_existente = guild.get_channel(
            int(ticket_existente["channel_id"])
        )

        if canal_existente:
            raise ValueError(
                f"Você já possui um ticket aberto: {canal_existente.mention}"
            )

    # Gerar número
    numero = await gerar_numero_ticket(guild.id)

    # Cargo responsável
    cargo_id = config.get("ticket_staff_role")


# =========================================================
# 4.2 CRIAR TICKET
# =========================================================

async def criar_ticket(
    guild: discord.Guild,
    usuario: discord.Member,
    tipo: str
):
    if tipo not in TICKET_LABELS:
        raise ValueError("Tipo de atendimento inválido.")

    config = await obter_config(guild.id)

    # Verificar categoria
    categoria_id = config["ticket_categories"].get(tipo)

    if not categoria_id:
        raise ValueError(
            f"A categoria de {TICKET_LABELS[tipo]} não foi configurada."
        )

    categoria = guild.get_channel(int(categoria_id))

    if not isinstance(categoria, discord.CategoryChannel):
        raise ValueError("A categoria configurada não existe.")

    # Verificar ticket existente
    ticket_existente = await buscar_ticket_aberto(
        guild.id,
        usuario.id
    )

    if ticket_existente:
        canal_existente = guild.get_channel(
            int(ticket_existente["channel_id"])
        )

        if canal_existente:
            raise ValueError(
                f"Você já possui um ticket aberto: {canal_existente.mention}"
            )

    # Gerar número
    numero = await gerar_numero_ticket(guild.id)

    # Cargo da equipe
    cargo_id = config.get("ticket_staff_role")
    cargo_equipe = (
        guild.get_role(int(cargo_id))
        if cargo_id else None
    )

    # Permissões
    permissoes = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False
        ),
        usuario: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True
        )
    }

    if guild.me:
        permissoes[guild.me] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
            attach_files=True
        )

    if cargo_equipe:
        permissoes[cargo_equipe] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_messages=True,
            attach_files=True
        )

    # Nome do canal
    nome_usuario = re.sub(
        r"[^a-z0-9-]",
        "-",
        usuario.name.lower()
    )

    nome_canal = f"ticket-{numero:04d}-{nome_usuario}"[:100]

    canal = None

    try:
        # Criar canal
        canal = await guild.create_text_channel(
            name=nome_canal,
            category=categoria,
            overwrites=permissoes,
            topic=(
                f"Ticket #{numero:04d} | "
                f"Usuário: {usuario.id} | "
                f"Tipo: {tipo}"
            ),
            reason=f"Ticket aberto por {usuario}"
        )

        # Registrar no banco
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO tickets (
                    guild_id,
                    channel_id,
                    user_id,
                    ticket_number,
                    ticket_type,
                    status
                )
                VALUES ($1, $2, $3, $4, $5, 'open')
                """,
                guild.id,
                canal.id,
                usuario.id,
                numero,
                tipo
            )

        # Mensagem do atendimento
        embed = discord.Embed(
            title=f"Central de Atendimento • #{numero:04d}",
            description=(
                f"Olá, {usuario.mention}! Seja bem-vindo(a) à nossa "
                "Central de Atendimento.\n\n"
                "Seu atendimento foi registrado com sucesso. "
                "Este canal será utilizado para acompanhar sua solicitação "
                "e manter toda a comunicação organizada.\n\n"

                "**INFORMAÇÕES DO ATENDIMENTO**\n"
                f"> **Protocolo:** #{numero:04d}\n"
                f"> **Assunto:** {TICKET_LABELS[tipo]}\n"
                f"> **Solicitante:** {usuario.mention}\n\n"

                "**COMO PROSSEGUIR?**\n"
                "• Descreva sua solicitação de forma clara e detalhada.\n"
                "• Informe todos os detalhes relevantes para a equipe.\n"
                "• Envie imagens ou arquivos, caso sejam necessários.\n"
                "• Aguarde o retorno de um membro responsável.\n\n"

                "**ORIENTAÇÕES IMPORTANTES**\n"
                "• Evite enviar mensagens repetidas.\n"
                "• Não marque os membros da equipe sem necessidade.\n"
                "• Mantenha as informações relacionadas ao atendimento "
                "neste canal.\n\n"

                "Nossa equipe analisará sua solicitação assim que possível. "
                "Agradecemos pela compreensão e colaboração!"
            ),
            color=EMBED_COLOR,
            timestamp=datetime.now(timezone.utc)
        )

        embed.set_footer(
            text=(
                f"Central de Atendimento • "
                f"Ticket #{numero:04d} • ID: {usuario.id}"
            )
        )

        # Enviar mensagem
        await canal.send(
            embed=embed,
            view=TicketControlView()
        )

        # Registrar log
        await registrar_log(
            guild.id,
            "ticket_criado",
            f"Ticket #{numero:04d} criado por {usuario} "
            f"({usuario.id}). Tipo: {tipo}. Canal: {canal.id}"
        )

        return canal

    except Exception:
        if canal is not None:
            try:
                async with db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        DELETE FROM tickets
                        WHERE channel_id = $1
                        """,
                        canal.id
                    )

                await canal.delete(
                    reason="Falha durante a criação do ticket."
                )

            except Exception:
                pass

        raise


# =========================================================
            
# =========================================================
# 4.2 CRIAR TICKET
# =========================================================

async def criar_ticket(
    guild: discord.Guild,
    usuario: discord.Member,
    tipo: str
):
    if tipo not in TICKET_LABELS:
        raise ValueError("Tipo de atendimento inválido.")

    config = await obter_config(guild.id)

    ticket_existente = await buscar_ticket_aberto(
        guild.id,
        usuario.id
    )

    if ticket_existente:
        canal_existente = guild.get_channel(
            ticket_existente["channel_id"]
        )

        if canal_existente:
            raise ValueError(
                f"Você já possui um atendimento aberto: {canal_existente.mention}"
            )

    categorias = config.get("ticket_categories", {})
    categoria_id = categorias.get(tipo)

    categoria = (
        guild.get_channel(int(categoria_id))
        if categoria_id else None
    )

    if categoria_id and not isinstance(categoria, discord.CategoryChannel):
        raise ValueError("A categoria configurada não existe.")

    numero = await gerar_numero_ticket(guild.id)

    nome_canal = f"ticket-{numero:04d}"

    cargo_id = config.get("ticket_staff_role")
    cargo_equipe = (
        guild.get_role(int(cargo_id))
        if cargo_id else None
    )

    permissoes = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False
        ),

        usuario: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True
        )
    }

    if guild.me:
        permissoes[guild.me] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
            manage_messages=True,
            attach_files=True,
            embed_links=True
        )

    if cargo_equipe:
        permissoes[cargo_equipe] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_messages=True
        )

    canal = None

    try:
        canal = await guild.create_text_channel(
            name=nome_canal,
            category=categoria,
            overwrites=permissoes,
            reason=f"Ticket criado por {usuario}"
        )

        await db_pool.execute(
            """
            INSERT INTO tickets (
                guild_id,
                channel_id,
                user_id,
                ticket_number,
                ticket_type,
                status
            )
            VALUES ($1, $2, $3, $4, $5, 'open')
            """,
            guild.id,
            canal.id,
            usuario.id,
            numero,
            tipo
        )

        embed = discord.Embed(
            title=f"Atendimento #{numero:04d}",
            description=(
                f"Olá, {usuario.mention}!\n\n"
                f"**Tipo:** {TICKET_LABELS[tipo]}\n"
                "A equipe responderá assim que possível.\n\n"
                "Utilize os botões abaixo para controlar este atendimento."
            ),
            color=EMBED_COLOR,
            timestamp=datetime.now(timezone.utc)
        )

        embed.set_footer(

# =========================================================
# 4.2 CRIAR TICKET
# =========================================================

async def criar_ticket(
    guild: discord.Guild,
    usuario: discord.Member,
    tipo: str
):
    if tipo not in TICKET_LABELS:
        raise ValueError("Tipo de atendimento inválido.")

    config = await obter_config(guild.id)

    ticket_existente = await buscar_ticket_aberto(
        guild.id,
        usuario.id
    )

    if ticket_existente:
        canal_existente = guild.get_channel(
            ticket_existente["channel_id"]
        )

        if canal_existente:
            raise ValueError(
                f"Você já possui um atendimento aberto: {canal_existente.mention}"
            )

    # Buscar categoria
    categorias = config.get("ticket_categories", {})
    categoria_id = categorias.get(tipo)

    if not categoria_id:
        raise ValueError(
            "A categoria deste tipo de ticket não foi configurada."
        )

    categoria = guild.get_channel(int(categoria_id))

    if not isinstance(categoria, discord.CategoryChannel):
        raise ValueError(
            "A categoria configurada não foi encontrada."
        )

    # Gerar número
    numero = await gerar_numero_ticket(guild.id)

    # Buscar cargo da equipe
    cargo_equipe = None
    cargo_id = config.get("ticket_staff_role")

    if cargo_id:
        cargo_equipe = guild.get_role(int(cargo_id))

    # Nome do canal
    nome_usuario = re.sub(
        r"[^a-z0-9-]",
        "-",
        usuario.name.lower()
    )

    nome_canal = f"ticket-{numero:04d}-{nome_usuario}"[:100]

    # Permissões
    permissoes = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False
        ),
        usuario: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True
        )
    }

    if guild.me:
        permissoes[guild.me] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
            manage_messages=True,
            attach_files=True
        )

    if cargo_equipe:
        permissoes[cargo_equipe] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_messages=True,
            attach_files=True
        )

    canal = None

    try:
        # Criar canal
        canal = await guild.create_text_channel(
            name=nome_canal,
            category=categoria,
            overwrites=permissoes,
            topic=(
                f"Ticket #{numero:04d} | "
                f"Usuário: {usuario.id} | "
                f"Tipo: {tipo}"
            ),
            reason=f"Ticket aberto por {usuario}"
        )

        # Registrar no banco
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO tickets (
                    guild_id,
                    channel_id,
                    user_id,
                    ticket_number,
                    ticket_type,
                    status
                )
                VALUES ($1, $2, $3, $4, $5, 'open')
                """,
                guild.id,
                canal.id,
                usuario.id,
                numero,
                tipo
            )

        # Mensagem do atendimento
        embed = discord.Embed(
            title=f"Central de Atendimento • #{numero:04d}",
            description=(
                f"Olá, {usuario.mention}! Seja bem-vindo(a) à nossa "
                "central de atendimento.\n\n"

                "Seu atendimento foi iniciado com sucesso. "
                "Este canal será utilizado para acompanhar sua "
                "solicitação e manter toda a comunicação organizada.\n\n"

                "**INFORMAÇÕES DO ATENDIMENTO**\n"
                f"> **Número:** #{numero:04d}\n"
                f"> **Assunto:** {TICKET_LABELS[tipo]}\n"
                f"> **Solicitante:** {usuario.mention}\n\n"

                "**COMO PROSSEGUIR?**\n"
                "• Descreva sua solicitação de maneira clara e objetiva.\n"
                "• Apresente todos os detalhes relevantes para a equipe.\n"
                "• Caso necessário, envie imagens ou arquivos "
                "que ajudem na análise.\n"
                "• Aguarde a disponibilidade de um membro responsável.\n\n"

                "**ORIENTAÇÕES IMPORTANTES**\n"
                "Mantenha a comunicação neste canal e evite enviar "
                "mensagens repetidas ou marcar membros da equipe "
                "sem necessidade.\n\n"

                "Todas as solicitações serão analisadas pela equipe "
                "conforme a disponibilidade e a natureza do assunto.\n\n"

                "Agradecemos por entrar em contato. "
                "Estamos à disposição para ajudá-lo!"
            ),
            color=EMBED_COLOR,
            timestamp=datetime.now(timezone.utc)
        )

        embed.set_footer(
            text=(
                f"Central de Atendimento • "
                f"Ticket #{numero:04d} • ID: {usuario.id}"
            )
        )

        # Enviar mensagem
        await canal.send(
            embed=embed,
            view=TicketControlView()
        )

        # Registrar log
        await registrar_log(
            guild.id,
            "ticket_criado",
            f"Ticket #{numero:04d} criado por {usuario} "
            f"({usuario.id}). Tipo: {tipo}. Canal: {canal.id}"
        )

        return canal

    except Exception:
        if canal is not None:
            try:
                async with db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        DELETE FROM tickets
                        WHERE channel_id = $1
                        """,
                        canal.id
                    )

                await canal.delete(
                    reason="Falha durante a criação do ticket."
                )

            except Exception:
                pass

        raise

# =========================================================
# 05. TRANSCRIÇÕES DOS TICKETS
# =========================================================

async def gerar_transcricao(
    canal: discord.TextChannel
) -> discord.File:

    linhas = [
        f"Servidor: {canal.guild.name}",
        f"Canal: {canal.name}",
        f"ID: {canal.id}",
        f"Data: {datetime.now(timezone.utc)}",
        "=" * 60,
        ""
    ]

    async for mensagem in canal.history(
        limit=None,
        oldest_first=True
    ):

        data = mensagem.created_at.strftime(
            "%d/%m/%Y %H:%M:%S"
        )

        conteudo = mensagem.clean_content or "[Sem texto]"

        linhas.append(
            f"[{data}] {mensagem.author} "
            f"({mensagem.author.id}): {conteudo}"
        )

        for anexo in mensagem.attachments:
            linhas.append(f"Anexo: {anexo.url}")

        if mensagem.embeds:
            linhas.append(
                f"[{len(mensagem.embeds)} embed(s)]"
            )

    arquivo = io.BytesIO(
        "\n".join(linhas).encode("utf-8")
    )

    return discord.File(
        arquivo,
        filename=f"ticket-{canal.id}.txt"
    )


# =========================================================
# 5.1 BUSCAR DADOS DO TICKET
# =========================================================

async def buscar_ticket(channel_id: int):

    async with db_pool.acquire() as conn:

        return await conn.fetchrow("""
            SELECT *
            FROM tickets
            WHERE channel_id = $1
            AND status = 'open'
        """, channel_id)


# =========================================================
# 5.2 ENCERRAR TICKET
# =========================================================

async def encerrar_ticket(
    canal: discord.TextChannel,
    moderador: discord.Member,
    motivo: str
):

    ticket = await buscar_ticket(canal.id)

    if not ticket:
        raise ValueError(
            "Este canal não possui um ticket aberto."
        )

    config = await obter_config(canal.guild.id)

    # Gerar transcrição
    arquivo = await gerar_transcricao(canal)

    # Enviar transcrição
    transcript_id = config.get(
        "ticket_transcript_channel"
    )

    transcript_channel = (
        canal.guild.get_channel(int(transcript_id))
        if transcript_id else None
    )

    if transcript_channel:

        await transcript_channel.send(
            content=(
                f"Transcrição do ticket "
                f"**#{ticket['ticket_number']:04d}**\n"
                f"Usuário: <@{ticket['user_id']}>\n"
                f"Encerrado por: {moderador.mention}\n"
                f"Motivo: {motivo}"
            ),
            file=arquivo
        )

    else:

        raise ValueError(
            "O canal de transcrições não foi configurado. "
            "Configure antes de encerrar o ticket."
        )

    # Atualizar banco
    async with db_pool.acquire() as conn:

        await conn.execute("""
            UPDATE tickets
            SET
                status = 'closed',
                closed_at = NOW(),
                closed_by = $2,
                close_reason = $3
            WHERE channel_id = $1
        """,
            canal.id,
            moderador.id,
            motivo
        )

    # Avisar usuário por mensagem privada
    usuario = canal.guild.get_member(
        int(ticket["user_id"])
    )

    if usuario:

        try:
            await usuario.send(
                f"Seu ticket **#{ticket['ticket_number']:04d}** "
                f"em **{canal.guild.name}** foi encerrado.\n\n"
                f"**Motivo:** {motivo}"
            )
        except discord.Forbidden:
            pass

    # Log
    embed = discord.Embed(
        title="Ticket encerrado",
        description=(
            f"**Número:** #{ticket['ticket_number']:04d}\n"
            f"**Usuário:** <@{ticket['user_id']}>\n"
            f"**Responsável:** {moderador.mention}\n"
            f"**Motivo:** {motivo}"
        ),
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc)
    )

    await enviar_log(
        canal.guild,
        "ticket_log_channel",
        embed
    )

    # Excluir canal
    await canal.delete(
        reason=f"Ticket encerrado por {moderador}: {motivo}"
)

# =========================================================
# 6. PAINEL DE TICKETS E MENU DE SELEÇÃO
# =========================================================

class TicketTypeSelect(discord.ui.Select):
    def __init__(self):
        opcoes = [
            discord.SelectOption(
                label=nome,
                value=tipo
            )
            for nome, tipo in TICKET_TYPES
        ]

        super().__init__(
            placeholder="Selecione o motivo do atendimento...",
            min_values=1,
            max_values=1,
            options=opcoes,
            custom_id="ticket:type_select"
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Este painel só funciona dentro de um servidor.",
                ephemeral=True
            )
            return

        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Não foi possível identificar seu usuário no servidor.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            canal = await criar_ticket(
                interaction.guild,
                interaction.user,
                self.values[0]
            )

            await interaction.followup.send(
                f"Seu atendimento foi criado: {canal.mention}",
                ephemeral=True
            )

        except ValueError as erro:
            await interaction.followup.send(
                str(erro),
                ephemeral=True
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "Não tenho permissão para criar o ticket. Verifique minhas permissões.",
                ephemeral=True
            )

        except Exception:
            traceback.print_exc()

            await interaction.followup.send(
                "Ocorreu um erro ao criar seu ticket. Avise a equipe.",
                ephemeral=True
            )


class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketTypeSelect())


def criar_embed_painel_ticket():
    embed = discord.Embed(
        color=EMBED_COLOR
    )

    embed.set_image(url=TICKET_IMAGE_URL)

    return embed


# =========================================================
# 7. CONTROLES DOS TICKETS
# =========================================================

class MotivoEncerramentoModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Encerrar atendimento")

        self.motivo = discord.ui.TextInput(
            label="Motivo do encerramento",
            placeholder="Informe o motivo...",
            required=True,
            max_length=500
        )

        self.add_item(self.motivo)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.channel is None:
            await interaction.response.send_message(
                "Canal não encontrado.",
                ephemeral=True
            )
            return

        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Não foi possível identificar sua conta.",
                ephemeral=True
            )
            return

        config = await obter_config(interaction.guild.id)

        if not membro_equipe(interaction.user, config):
            await interaction.response.send_message(
                "Você não tem permissão para encerrar este atendimento.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            await encerrar_ticket(
                interaction.channel,
                interaction.user,
                str(self.motivo.value)
            )

            await interaction.followup.send(
                "Atendimento encerrado com sucesso.",
                ephemeral=True
            )

        except Exception:
            traceback.print_exc()

            await interaction.followup.send(
                "Não foi possível encerrar o atendimento. Verifique a configuração do canal de transcrições.",
                ephemeral=True
            )


class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def verificar_equipe(self, interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Este controle só funciona dentro do servidor.",
                ephemeral=True
            )
            return False

        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Não foi possível identificar sua conta.",
                ephemeral=True
            )
            return False

        config = await obter_config(interaction.guild.id)

        if not membro_equipe(interaction.user, config):
            await interaction.response.send_message(
                "Você não tem permissão para usar este controle.",
                ephemeral=True
            )
            return False

        return True

    @discord.ui.button(
        label="Assumir",
        emoji="🙋",
        style=discord.ButtonStyle.success,
        custom_id="ticket:assumir"
    )
    async def assumir(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await self.verificar_equipe(interaction):
            return

        ticket = await buscar_ticket(interaction.channel.id)

        if ticket is None:
            await interaction.response.send_message(
                "Este canal não possui um ticket aberto.",
                ephemeral=True
            )
            return

        if ticket["claimed_by"] is not None:
            await interaction.response.send_message(
                "Este ticket já foi assumido por outro membro.",
                ephemeral=True
            )
            return

        await db_pool.execute(
            """
            UPDATE tickets
            SET claimed_by = $1
            WHERE channel_id = $2 AND status = 'open'
            """,
            interaction.user.id,
            interaction.channel.id
        )

        await interaction.response.send_message(
            f"🙋 Atendimento assumido por {interaction.user.mention}."
        )

    @discord.ui.button(
        label="Liberar",
        emoji="🔓",
        style=discord.ButtonStyle.secondary,
        custom_id="ticket:liberar"
    )
    async def liberar(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await self.verificar_equipe(interaction):
            return

        ticket = await buscar_ticket(interaction.channel.id)

        if ticket is None:
            await interaction.response.send_message(
                "Este canal não possui um ticket aberto.",
                ephemeral=True
            )
            return

        if ticket["claimed_by"] is None:
            await interaction.response.send_message(
                "Este ticket ainda não foi assumido.",
                ephemeral=True
            )
            return

        if (
            ticket["claimed_by"] != interaction.user.id
            and not interaction.user.guild_permissions.administrator
        ):
            await interaction.response.send_message(
                "Somente quem assumiu o ticket ou um administrador pode liberá-lo.",
                ephemeral=True
            )
            return

        await db_pool.execute(
            """
            UPDATE tickets
            SET claimed_by = NULL
            WHERE channel_id = $1 AND status = 'open'
            """,
            interaction.channel.id
        )

        await interaction.response.send_message(
            f"🔓 Atendimento liberado por {interaction.user.mention}."
        )

    @discord.ui.button(
        label="Encerrar",
        emoji="🔒",
        style=discord.ButtonStyle.danger,
        custom_id="ticket:encerrar"
    )
    async def encerrar(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await self.verificar_equipe(interaction):
            return

        await interaction.response.send_modal(
            MotivoEncerramentoModal()
        )
# =========================================================
# 8. COMANDOS DE CONFIGURAÇÃO
# =========================================================

class ConfiguracaoTickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def verificar_admin(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Este comando só funciona dentro de um servidor.",
                ephemeral=True
            )
            return False

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "Somente administradores podem alterar as configurações.",
                ephemeral=True
            )
            return False

        return True

    @app_commands.command(
        name="configurar_categoria_ticket",
        description="Define a categoria de um tipo de ticket."
    )
    @app_commands.describe(
        tipo="Tipo de atendimento",
        categoria="Categoria onde os tickets serão criados"
    )
    @app_commands.choices(
        tipo=[
            app_commands.Choice(name=nome, value=valor)
            for nome, valor in TICKET_TYPES
        ]
    )
    async def configurar_categoria_ticket(
        self,
        interaction: discord.Interaction,
        tipo: app_commands.Choice[str],
        categoria: discord.CategoryChannel
    ):
        if not await self.verificar_admin(interaction):
            return

        await alterar_categoria_ticket(
            interaction.guild.id,
            tipo.value,
            categoria.id
        )

        await interaction.response.send_message(
            f"Categoria de **{tipo.name}** definida para {categoria.mention}.",
            ephemeral=True
        )

    @app_commands.command(
        name="configurar_cargo_equipe",
        description="Define o cargo responsável pelos tickets."
    )
    async def configurar_cargo_equipe(
        self,
        interaction: discord.Interaction,
        cargo: discord.Role
    ):
        if not await self.verificar_admin(interaction):
            return

        await alterar_config(
            interaction.guild.id,
            "ticket_staff_role",
            cargo.id
        )

        await interaction.response.send_message(
            f"Cargo da equipe definido: {cargo.mention}.",
            ephemeral=True
        )

    @app_commands.command(
        name="configurar_canal_painel",
        description="Define o canal onde o painel de tickets será publicado."
    )
    async def configurar_canal_painel(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel
    ):
        if not await self.verificar_admin(interaction):
            return

        await alterar_config(
            interaction.guild.id,
            "ticket_panel_channel",
            canal.id
        )

        await interaction.response.send_message(
            f"Canal do painel definido: {canal.mention}.",
            ephemeral=True
        )

    @app_commands.command(
        name="configurar_transcricoes",
        description="Define o canal que receberá as transcrições."
    )
    async def configurar_transcricoes(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel
    ):
        if not await self.verificar_admin(interaction):
            return

        await alterar_config(
            interaction.guild.id,
            "ticket_transcript_channel",
            canal.id
        )

        await interaction.response.send_message(
            f"Canal de transcrições definido: {canal.mention}.",
            ephemeral=True
        )

    @app_commands.command(
        name="configurar_log_tickets",
        description="Define o canal de logs dos tickets."
    )
    async def configurar_log_tickets(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel
    ):
        if not await self.verificar_admin(interaction):
            return

        await alterar_config(
            interaction.guild.id,
            "ticket_log_channel",
            canal.id
        )

        await interaction.response.send_message(
            f"Canal de logs definido: {canal.mention}.",
            ephemeral=True
        )

    @app_commands.command(
        name="publicar_painel",
        description="Publica o painel de atendimento no canal configurado."
    )
    async def publicar_painel(
        self,
        interaction: discord.Interaction
    ):
        if not await self.verificar_admin(interaction):
            return

        config = await obter_config(interaction.guild.id)

        canal_id = config.get("ticket_panel_channel")

        if not canal_id:
            await interaction.response.send_message(
                "Configure primeiro o canal com `/configurar_canal_painel`.",
                ephemeral=True
            )
            return

        canal = interaction.guild.get_channel(int(canal_id))

        if not isinstance(canal, discord.TextChannel):
            await interaction.response.send_message(
                "O canal configurado não existe ou não é um canal de texto.",
                ephemeral=True
            )
            return

        try:
            await canal.send(
                embed=criar_embed_painel_ticket(),
                view=TicketPanelView()
            )

            await interaction.response.send_message(
                f"Painel publicado em {canal.mention}.",
                ephemeral=True
            )

        except discord.Forbidden:
            await interaction.response.send_message(
                "Não tenho permissão para enviar mensagens nesse canal.",
                ephemeral=True
            )

    @app_commands.command(
        name="ver_configuracao_tickets",
        description="Mostra as configurações atuais dos tickets."
    )
    async def ver_configuracao_tickets(
        self,
        interaction: discord.Interaction
    ):
        if not await self.verificar_admin(interaction):
            return

        config = await obter_config(interaction.guild.id)

        def mencionar_canal(chave):
            canal_id = config.get(chave)
            canal = interaction.guild.get_channel(int(canal_id)) if canal_id else None
            return canal.mention if canal else "Não configurado"

        cargo_id = config.get("ticket_staff_role")
        cargo = interaction.guild.get_role(int(cargo_id)) if cargo_id else None

        embed = discord.Embed(
            title="Configuração dos Tickets",
            color=EMBED_COLOR
        )

        embed.add_field(
            name="Cargo da equipe",
            value=cargo.mention if cargo else "Não configurado",
            inline=False
        )

        embed.add_field(
            name="Canal do painel",
            value=mencionar_canal("ticket_panel_channel"),
            inline=True
        )

        embed.add_field(
            name="Transcrições",
            value=mencionar_canal("ticket_transcript_channel"),
            inline=True
        )

        embed.add_field(
            name="Logs",
            value=mencionar_canal("ticket_log_channel"),
            inline=True
        )

        categorias = config.get("ticket_categories", {})

        texto_categorias = []

        for nome, tipo in TICKET_TYPES:
            categoria_id = categorias.get(tipo)
            categoria = (
                interaction.guild.get_channel(int(categoria_id))
                if categoria_id else None
            )

            texto_categorias.append(
                f"**{nome}:** {categoria.mention if categoria else 'Não configurada'}"
            )

        embed.add_field(
            name="Categorias",
            value="\n".join(texto_categorias),
            inline=False
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )
# =========================================================
# 9. COMANDOS DE MODERAÇÃO
# =========================================================

class Moderacao(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def registrar_moderacao(
        self,
        guild_id,
        moderador_id,
        alvo_id,
        acao,
        motivo
    ):
        await db_pool.execute(
            """
            INSERT INTO moderation_history
            (guild_id, moderator_id, target_id, action, reason)
            VALUES ($1, $2, $3, $4, $5)
            """,
            guild_id,
            moderador_id,
            alvo_id,
            acao,
            motivo
        )

    async def enviar_log_moderacao(
        self,
        guild,
        titulo,
        descricao
    ):
        embed = discord.Embed(
            title=titulo,
            description=descricao,
            color=EMBED_COLOR,
            timestamp=datetime.now(timezone.utc)
        )

        await enviar_log(
            guild,
            "moderation_log_channel",
            embed
        )

    @app_commands.command(
        name="aviso",
        description="Aplica um aviso a um membro."
    )
    @app_commands.describe(
        membro="Membro que receberá o aviso",
        motivo="Motivo do aviso"
    )
    async def aviso(
        self,
        interaction: discord.Interaction,
        membro: discord.Member,
        motivo: str
    ):
        if not interaction.user.guild_permissions.moderate_members:
            await interaction.response.send_message(
                "Você não tem permissão para aplicar avisos.",
                ephemeral=True
            )
            return

        if membro.bot or membro.id == interaction.user.id:
            await interaction.response.send_message(
                "Você não pode aplicar aviso nesse membro.",
                ephemeral=True
            )
            return

        await self.registrar_moderacao(
            interaction.guild.id,
            interaction.user.id,
            membro.id,
            "aviso",
            motivo
        )

        await self.enviar_log_moderacao(
            interaction.guild,
            "Aviso aplicado",
            f"Membro: {membro.mention}\n"
            f"Moderador: {interaction.user.mention}\n"
            f"Motivo: {motivo}"
        )

        try:
            await membro.send(
                f"Você recebeu um aviso no servidor **{interaction.guild.name}**.\n"
                f"Motivo: {motivo}"
            )
        except discord.Forbidden:
            pass

        await interaction.response.send_message(
            f"{membro.mention} recebeu um aviso.",
            ephemeral=True
        )

    @app_commands.command(
        name="expulsar",
        description="Expulsa um membro do servidor."
    )
    async def expulsar(
        self,
        interaction: discord.Interaction,
        membro: discord.Member,
        motivo: str
    ):
        if not interaction.user.guild_permissions.kick_members:
            await interaction.response.send_message(
                "Você não tem permissão para expulsar membros.",
                ephemeral=True
            )
            return

        if (
            membro.id == interaction.user.id
            or membro.top_role >= interaction.user.top_role
            or membro.top_role >= interaction.guild.me.top_role
        ):
            await interaction.response.send_message(
                "Não é possível expulsar esse membro por causa da hierarquia de cargos.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            await membro.kick(reason=motivo)

            await self.registrar_moderacao(
                interaction.guild.id,
                interaction.user.id,
                membro.id,
                "expulsao",
                motivo
            )

            await self.enviar_log_moderacao(
                interaction.guild,
                "Membro expulso",
                f"Membro: {membro} (`{membro.id}`)\n"
                f"Moderador: {interaction.user.mention}\n"
                f"Motivo: {motivo}"
            )

            await interaction.followup.send(
                f"{membro} foi expulso.",
                ephemeral=True
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "Não tenho permissão para expulsar esse membro.",
                ephemeral=True
            )

    @app_commands.command(
        name="banir",
        description="Bane um membro do servidor."
    )
    async def banir(
        self,
        interaction: discord.Interaction,
        membro: discord.Member,
        motivo: str
    ):
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message(
                "Você não tem permissão para banir membros.",
                ephemeral=True
            )
            return

        if (
            membro.id == interaction.user.id
            or membro.top_role >= interaction.user.top_role
            or membro.top_role >= interaction.guild.me.top_role
        ):
            await interaction.response.send_message(
                "Não é possível banir esse membro por causa da hierarquia de cargos.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            await membro.ban(
                reason=motivo,
                delete_message_seconds=0
            )

            await self.registrar_moderacao(
                interaction.guild.id,
                interaction.user.id,
                membro.id,
                "banimento",
                motivo
            )

            await self.enviar_log_moderacao(
                interaction.guild,
                "Membro banido",
                f"Membro: {membro} (`{membro.id}`)\n"
                f"Moderador: {interaction.user.mention}\n"
                f"Motivo: {motivo}"
            )

            await interaction.followup.send(
                f"{membro} foi banido.",
                ephemeral=True
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "Não tenho permissão para banir esse membro.",
                ephemeral=True
            )

    @app_commands.command(
        name="desbanir",
        description="Remove o banimento de um usuário."
    )
    async def desbanir(
        self,
        interaction: discord.Interaction,
        usuario_id: str,
        motivo: str = "Não informado"
    ):
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message(
                "Você não tem permissão para desbanir usuários.",
                ephemeral=True
            )
            return

        try:
            user_id = int(usuario_id)
        except ValueError:
            await interaction.response.send_message(
                "Informe um ID numérico válido.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            usuario = await self.bot.fetch_user(user_id)

            await interaction.guild.unban(
                usuario,
                reason=motivo
            )

            await self.registrar_moderacao(
                interaction.guild.id,
                interaction.user.id,
                usuario.id,
                "desbanimento",
                motivo
            )

            await self.enviar_log_moderacao(
                interaction.guild,
                "Usuário desbanido",
                f"Usuário: {usuario} (`{usuario.id}`)\n"
                f"Moderador: {interaction.user.mention}\n"
                f"Motivo: {motivo}"
            )

            await interaction.followup.send(
                f"{usuario} foi desbanido.",
                ephemeral=True
            )

        except discord.NotFound:
            await interaction.followup.send(
                "Esse usuário não está banido.",
                ephemeral=True
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "Não tenho permissão para desbanir usuários.",
                ephemeral=True
            )

    @app_commands.command(
        name="limpar",
        description="Apaga mensagens de um canal."
    )
    @app_commands.describe(
        quantidade="Quantidade de mensagens a apagar (1 a 100)"
    )
    async def limpar(
        self,
        interaction: discord.Interaction,
        quantidade: app_commands.Range[int, 1, 100]
    ):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message(
                "Você não tem permissão para apagar mensagens.",
                ephemeral=True
            )
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "Este comando só funciona em canais de texto.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            apagadas = await interaction.channel.purge(
                limit=quantidade
            )

            await interaction.followup.send(
                f"{len(apagadas)} mensagens apagadas.",
                ephemeral=True
            )

            await self.enviar_log_moderacao(
                interaction.guild,
                "Mensagens apagadas",
                f"Canal: {interaction.channel.mention}\n"
                f"Moderador: {interaction.user.mention}\n"
                f"Quantidade: {len(apagadas)}"
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "Não tenho permissão para apagar mensagens.",
                ephemeral=True
        )

# =========================================================
# 10. AUTOMODERAÇÃO E EVENTOS
# =========================================================

class EventosServidor(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot:
            return

        config = await obter_config(message.guild.id)

        # -----------------------------------------
        # BLOQUEIO DE PALAVRAS
        # -----------------------------------------

        palavras = config.get("blocked_words", [])

        conteudo = unicodedata.normalize(
            "NFKC",
            message.content.lower()
        )

        for palavra in palavras:
            if palavra.lower() in conteudo:
                try:
                    await message.delete()

                    await message.channel.send(
                        f"{message.author.mention}, sua mensagem foi removida por conter uma palavra bloqueada.",
                        delete_after=8
                    )

                    await enviar_log(
                        message.guild,
                        "moderation_log_channel",
                        discord.Embed(
                            title="Automoderação: palavra bloqueada",
                            description=(
                                f"**Membro:** {message.author.mention}\n"
                                f"**Canal:** {message.channel.mention}\n"
                                f"**Palavra:** `{palavra}`"
                            ),
                            color=EMBED_COLOR
                        )
                    )

                except discord.Forbidden:
                    pass

                return

        # -----------------------------------------
        # BLOQUEIO DE LINKS
        # -----------------------------------------

        if config.get("automod_links", False):
            padrao = r"https?://\S+|discord\.gg/\S+"

            if re.search(padrao, message.content, re.IGNORECASE):
                if not message.author.guild_permissions.manage_messages:
                    try:
                        await message.delete()

                        await message.channel.send(
                            f"{message.author.mention}, links não são permitidos aqui.",
                            delete_after=8
                        )

                        await enviar_log(
                            message.guild,
                            "moderation_log_channel",
                            discord.Embed(
                                title="Automoderação: link bloqueado",
                                description=(
                                    f"**Membro:** {message.author.mention}\n"
                                    f"**Canal:** {message.channel.mention}"
                                ),
                                color=EMBED_COLOR
                            )
                        )

                    except discord.Forbidden:
                        pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        config = await obter_config(member.guild.id)

        canal_id = config.get("welcome_channel")

        if canal_id:
            canal = member.guild.get_channel(int(canal_id))

            if isinstance(canal, discord.TextChannel):
                embed = discord.Embed(
                    title="Novo membro",
                    description=(
                        f"Bem-vindo(a), {member.mention}!\n"
                        f"Agora somos **{member.guild.member_count} membros**."
                    ),
                    color=EMBED_COLOR
                )

                embed.set_thumbnail(url=member.display_avatar.url)

                await canal.send(embed=embed)

        await enviar_log(
            member.guild,
            "member_log_channel",
            discord.Embed(
                title="Membro entrou",
                description=f"{member.mention} entrou no servidor.",
                color=EMBED_COLOR
            )
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        config = await obter_config(member.guild.id)

        canal_id = config.get("leave_channel")

        if canal_id:
            canal = member.guild.get_channel(int(canal_id))

            if isinstance(canal, discord.TextChannel):
                await canal.send(
                    f"**{member}** saiu do servidor."
                )

        await enviar_log(
            member.guild,
            "member_log_channel",
            discord.Embed(
                title="Membro saiu",
                description=f"**{member}** saiu do servidor.",
                color=EMBED_COLOR
            )
        )

    @app_commands.command(
        name="adicionar_palavra",
        description="Adiciona uma palavra ao filtro automático."
    )
    async def adicionar_palavra(
        self,
        interaction: discord.Interaction,
        palavra: str
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "Somente administradores podem alterar o filtro.",
                ephemeral=True
            )
            return

        config = await obter_config(interaction.guild.id)

        palavras = config.get("blocked_words", [])

        if palavra.lower() in [p.lower() for p in palavras]:
            await interaction.response.send_message(
                "Essa palavra já está bloqueada.",
                ephemeral=True
            )
            return

        palavras.append(palavra.lower())

        await alterar_config(
            interaction.guild.id,
            "blocked_words",
            palavras
        )

        await interaction.response.send_message(
            f"A palavra `{palavra}` foi adicionada ao filtro.",
            ephemeral=True
        )

    @app_commands.command(
        name="remover_palavra",
        description="Remove uma palavra do filtro automático."
    )
    async def remover_palavra(
        self,
        interaction: discord.Interaction,
        palavra: str
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "Somente administradores podem alterar o filtro.",
                ephemeral=True
            )
            return

        config = await obter_config(interaction.guild.id)

        palavras = config.get("blocked_words", [])

        palavras = [
            p for p in palavras
            if p.lower() != palavra.lower()
        ]

        await alterar_config(
            interaction.guild.id,
            "blocked_words",
            palavras
        )

        await interaction.response.send_message(
            f"A palavra `{palavra}` foi removida do filtro.",
            ephemeral=True
        )

    @app_commands.command(
        name="configurar_boas_vindas",
        description="Define o canal de boas-vindas."
    )
    async def configurar_boas_vindas(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "Somente administradores podem alterar essa configuração.",
                ephemeral=True
            )
            return

        await alterar_config(
            interaction.guild.id,
            "welcome_channel",
            canal.id
        )

        await interaction.response.send_message(
            f"Canal de boas-vindas definido: {canal.mention}.",
            ephemeral=True
        )

    @app_commands.command(
        name="configurar_saidas",
        description="Define o canal de avisos de saída."
    )
    async def configurar_saidas(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "Somente administradores podem alterar essa configuração.",
                ephemeral=True
            )
            return

        await alterar_config(
            interaction.guild.id,
            "leave_channel",
            canal.id
        )

        await interaction.response.send_message(
            f"Canal de saídas definido: {canal.mention}.",
            ephemeral=True
        )

    @app_commands.command(
        name="configurar_logs_membros",
        description="Define o canal de logs de entrada e saída."
    )
    async def configurar_logs_membros(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "Somente administradores podem alterar essa configuração.",
                ephemeral=True
            )
            return

        await alterar_config(
            interaction.guild.id,
            "member_log_channel",
            canal.id
        )

        await interaction.response.send_message(
            f"Canal de logs de membros definido: {canal.mention}.",
            ephemeral=True
            )

# =========================================================
# 11. INICIALIZAÇÃO DO BOT
# =========================================================

class TicketBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=PREFIX,
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):
        await conectar_db()

        # Interfaces persistentes dos tickets
        self.add_view(TicketPanelView())
        self.add_view(TicketControlView())

        # Registro das classes e comandos
        await self.add_cog(ConfiguracaoTickets(self))
        await self.add_cog(Moderacao(self))
        await self.add_cog(EventosServidor(self))

        # Sincronização dos comandos slash
        await self.tree.sync()

        print("Banco de dados conectado.")
        print("Interfaces persistentes carregadas.")
        print("Comandos slash sincronizados.")

    async def close(self):
        global db_pool

        if db_pool is not None:
            await db_pool.close()
            db_pool = None

        await super().close()


bot = TicketBot()


@bot.event
async def on_ready():
    print("--------------------------------")
    print(f"Bot conectado: {bot.user}")
    print(f"ID: {bot.user.id}")
    print("Sistema iniciado.")
    print("--------------------------------")


@bot.event
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):
    traceback.print_exception(
        type(error),
        error,
        error.__traceback__
    )

    mensagem = "Ocorreu um erro ao executar esse comando."

    if isinstance(error, app_commands.MissingPermissions):
        mensagem = "Você não possui as permissões necessárias."

    elif isinstance(error, app_commands.CommandOnCooldown):
        mensagem = "Aguarde antes de utilizar esse comando novamente."

    try:
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
    except discord.HTTPException:
        pass


# =========================================================
# 12. EXECUÇÃO
# =========================================================

if __name__ == "__main__":
    bot.run(TOKEN)
