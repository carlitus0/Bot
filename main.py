
import os
import io
import html
import asyncio
import re
import unicodedata
from datetime import datetime, timezone

import discord
from discord.ext import commands
from discord import app_commands
import asyncpg


# ==========================================
# CONFIGURAÇÕES
# ==========================================

TOKEN = os.getenv("DISCORD_TOKEN")
DB_PASSWORD = os.getenv("SUPABASE_DB_PASSWORD")

TICKET_CATEGORY_ID = 1574487012004728873
TRANSCRIPT_CHANNEL_ID = 1574486817309327511
STAFF_ROLE_ID = 1574488158895341628

PANEL_TITLE = "🎫 CENTRAL DE ATENDIMENTO"

PANEL_DESCRIPTION = (
    "Precisa de ajuda ou deseja entrar em contato com nossa equipe?\n\n"
    "Selecione uma das opções abaixo para abrir um ticket. "
    "Nossa equipe estará disponível para analisar sua solicitação "
    "e prestar o suporte necessário."
)

PANEL_IMAGE = (
    "https://cdn.discordapp.com/attachments/"
    "1573540268878077984/1574494273016172624/"
    "Central_de_Atendimento_Roxa.png"
    "?ex=6b05d98f&is=6b04880f"
    "&hm=d2a83f98a563cb8ac43cce815ba3bb52"
    "e78b3d8b88be000e215dbcee20623878&"
)

TICKET_TYPES = [
    ("🚨 Denunciar membro", "denuncia"),
    ("👥 Entrar em contato com a equipe", "equipe"),
    ("🤝 Solicitar parceria", "parceria"),
    ("⚖️ Solicitar revisão de punição", "revisao"),
    ("❓ Dúvidas", "duvidas"),
    ("🛠️ Suporte geral", "suporte"),
    ("🐛 Relatar bug ou erro", "bug"),
]

EMBED_COLOR = discord.Colour.from_rgb(128, 128, 128)

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

db_pool = None


# ==========================================
# FUNÇÕES AUXILIARES
# ==========================================

def gerar_nome_ticket(categoria, numero):
    nome = unicodedata.normalize("NFKD", categoria)
    nome = nome.encode("ascii", "ignore").decode("ascii")
    nome = nome.lower()
    nome = re.sub(r"[^a-z0-9]+", "-", nome).strip("-")

    return f"{nome}-{numero:04d}"


# ==========================================
# BANCO DE DADOS SUPABASE
# ==========================================

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
        max_size=5
    )

    async with db_pool.acquire() as conn:
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

    print("Conexão com Supabase estabelecida.")


async def next_ticket_number():
    async with db_pool.acquire() as conn:
        return await conn.fetchval("""
            UPDATE ticket_counter
            SET last_number = last_number + 1
            WHERE id = 1
            RETURNING last_number
        """)


async def save_ticket(number, guild_id, channel_id,
                      opener_id, category):
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
# TRANSCRIPT HTML
# ==========================================

async def create_transcript(channel, ticket, opener, closer, reason):
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
            <p><b>Responsável:</b> {html.escape(str(opener))} ({opener.id})</p>
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
# ABERTURA DE TICKETS
# ==========================================

class TicketSelect(discord.ui.Select):

    def __init__(self):
        options = [
            discord.SelectOption(
                label=name,
                value=value
            )
            for name, value in TICKET_TYPES
        ]

        super().__init__(
            placeholder="Selecione o motivo do atendimento...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="ticket:select"
        )

    async def callback(self, interaction):
        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )

        guild = interaction.guild
        member = interaction.user

        category_value = self.values[0]

        category_name = next(
            name for name, value in TICKET_TYPES
            if value == category_value
        )

        category = guild.get_channel(TICKET_CATEGORY_ID)
        staff_role = guild.get_role(STAFF_ROLE_ID)

        if category is None:
            return await interaction.followup.send(
                "A categoria de tickets não foi encontrada.",
                ephemeral=True
            )

        if not isinstance(category, discord.CategoryChannel):
            return await interaction.followup.send(
                "O ID configurado não corresponde a uma categoria.",
                ephemeral=True
            )

        if staff_role is None:
            return await interaction.followup.send(
                "O cargo Staff não foi encontrado.",
                ephemeral=True
            )

        existing = await get_open_ticket(member.id, guild.id)

        if existing:
            existing_channel = guild.get_channel(
                existing["channel_id"]
            )

            if existing_channel:
                return await interaction.followup.send(
                    f"Você já possui um ticket aberto: "
                    f"{existing_channel.mention}",
                    ephemeral=True
                )

        number = await next_ticket_number()
        channel_name = gerar_nome_ticket(category_name, number)

        bot_member = guild.me

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
            staff_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                manage_messages=True
            ),
            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                attach_files=True
            )
        }

        channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            reason=f"Ticket aberto por {member}"
        )

        try:
            await save_ticket(
                number,
                guild.id,
                channel.id,
                member.id,
                category_name
            )
        except Exception:
            await channel.delete(
                reason="Falha ao registrar ticket no banco"
            )
            raise

        embed = discord.Embed(
            title="🎫 Atendimento iniciado!",
            description=(
                f"Olá, {member.mention}! Seu atendimento foi criado "
                "com sucesso.\n\n"
                "Nossa equipe recebeu sua solicitação. "
                "Enquanto aguarda, descreva seu problema ou pedido "
                "com o máximo de detalhes possível.\n\n"
                "**Informações do atendimento**"
            ),
            color=EMBED_COLOR
        )

        embed.add_field(
            name="📁 Categoria",
            value=category_name,
            inline=True
        )

        embed.add_field(
            name="🔢 Protocolo",
            value=f"#{number:04d}",
            inline=True
        )

        embed.add_field(
            name="👤 Solicitante",
            value=member.mention,
            inline=True
        )

        embed.set_footer(
            text="Central de Atendimento • Aguarde nossa equipe."
        )

        await channel.send(
            content=f"{member.mention} | {staff_role.mention}",
            embed=embed,
            view=TicketControlView()
        )

        try:
            dm_embed = discord.Embed(
                title="🎫 Seu atendimento foi aberto!",
                description=(
                    f"Seu ticket no servidor **{guild.name}** "
                    "foi criado com sucesso.\n\n"
                    f"**Protocolo:** #{number:04d}\n"
                    f"**Categoria:** {category_name}\n"
                    f"**Canal:** #{channel.name}\n\n"
                    "Nossa equipe atenderá sua solicitação assim "
                    "que possível."
                ),
                color=EMBED_COLOR
            )

            await member.send(embed=dm_embed)

        except (discord.Forbidden, discord.HTTPException):
            pass

        await interaction.followup.send(
            f"Seu atendimento foi criado com sucesso: {channel.mention}",
            ephemeral=True
        )


class TicketPanelView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelect())


# ==========================================
# FECHAMENTO DE TICKETS
# ==========================================

class CloseReasonModal(
    discord.ui.Modal,
    title="Fechar atendimento"
):

    reason = discord.ui.TextInput(
        label="Motivo do fechamento",
        placeholder="Informe o motivo do encerramento...",
        style=discord.TextStyle.paragraph,
        min_length=3,
        max_length=500,
        required=True
    )

    async def on_submit(self, interaction):
        channel = interaction.channel
        guild = interaction.guild
        closer = interaction.user

        ticket = await get_ticket(channel.id)

        if ticket is None:
            return await interaction.response.send_message(
                "Este ticket não está registrado como aberto.",
                ephemeral=True
            )

        staff_role = guild.get_role(STAFF_ROLE_ID)

        is_staff = (
            staff_role is not None
            and staff_role in closer.roles
        )

        if not (
            is_staff
            or closer.guild_permissions.administrator
        ):
            return await interaction.response.send_message(
                "Apenas a equipe pode fechar este ticket.",
                ephemeral=True
            )

        log_channel = guild.get_channel(
            TRANSCRIPT_CHANNEL_ID
        )

        if log_channel is None:
            return await interaction.response.send_message(
                "O canal de transcripts não foi encontrado. "
                "O ticket não foi fechado.",
                ephemeral=True
            )

        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )

        opener = guild.get_member(ticket["opener_id"])

        if opener is None:
            try:
                opener = await bot.fetch_user(
                    ticket["opener_id"]
                )
            except (discord.NotFound, discord.HTTPException):
                opener = discord.Object(
                    id=ticket["opener_id"]
                )

        reason_text = str(self.reason.value)

        close_embed = discord.Embed(
            title="🔒 Atendimento finalizado",
            description=(
                "Este atendimento foi encerrado pela equipe.\n\n"
                "Agradecemos por entrar em contato conosco. "
                "Esperamos ter ajudado!\n\n"
                "**Resumo do encerramento**"
            ),
            color=EMBED_COLOR
        )

        close_embed.add_field(
            name="📁 Categoria",
            value=ticket["category"],
            inline=True
        )

        close_embed.add_field(
            name="🔢 Protocolo",
            value=f"#{ticket['ticket_number']:04d}",
            inline=True
        )

        close_embed.add_field(
            name="🛡️ Fechado por",
            value=closer.mention,
            inline=True
        )

        close_embed.add_field(
            name="📝 Motivo",
            value=reason_text,
            inline=False
        )

        close_embed.set_footer(
            text="Central de Atendimento"
        )

        await channel.send(embed=close_embed)

        transcript = await create_transcript(
            channel,
            ticket,
            opener,
            closer,
            reason_text
        )

        log_embed = discord.Embed(
            title=f"📁 Atendimento #{ticket['ticket_number']:04d} encerrado",
            description=(
                "O atendimento foi finalizado e o transcript "
                "foi registrado."
            ),
            color=EMBED_COLOR,
            timestamp=datetime.now(timezone.utc)
        )

        log_embed.add_field(
            name="👤 Aberto por",
            value=f"{opener} (`{opener.id}`)",
            inline=False
        )

        log_embed.add_field(
            name="🛡️ Fechado por",
            value=f"{closer} (`{closer.id}`)",
            inline=False
        )

        log_embed.add_field(
            name="📁 Categoria",
            value=ticket["category"],
            inline=True
        )

        log_embed.add_field(
            name="🔢 Protocolo",
            value=f"#{ticket['ticket_number']:04d}",
            inline=True
        )

        log_embed.add_field(
            name="📝 Motivo",
            value=reason_text,
            inline=False
        )

        try:
            await log_channel.send(
                embed=log_embed,
                file=transcript
            )

        except discord.HTTPException:
            return await interaction.followup.send(
                "Não foi possível enviar o transcript. "
                "O ticket continua aberto.",
                ephemeral=True
            )

        await close_ticket_db(
            ticket["ticket_number"],
            closer.id,
            reason_text
        )

        try:
            dm_embed = discord.Embed(
                title="🔒 Seu atendimento foi encerrado",
                description=(
                    f"Seu ticket no servidor **{guild.name}** "
                    "foi finalizado pela equipe.\n\n"
                    f"**Protocolo:** #{ticket['ticket_number']:04d}\n"
                    f"**Categoria:** {ticket['category']}\n"
                    f"**Fechado por:** {closer}\n"
                    f"**Motivo:** {reason_text}\n\n"
                    "Agradecemos por entrar em contato conosco!"
                ),
                color=EMBED_COLOR
            )

            await opener.send(embed=dm_embed)

        except (discord.Forbidden, discord.HTTPException):
            pass

        await interaction.followup.send(
            "Atendimento encerrado. O transcript foi enviado aos logs.",
            ephemeral=True
        )


# ==========================================
# CONTROLES DO TICKET
# ==========================================

class TicketControlView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Fechar atendimento",
        emoji="🔒",
        style=discord.ButtonStyle.danger,
        custom_id="ticket:close"
    )
    async def close_ticket(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        ticket = await get_ticket(interaction.channel.id)

        if ticket is None:
            return await interaction.response.send_message(
                "Este canal não possui um atendimento aberto.",
                ephemeral=True
            )

        staff_role = interaction.guild.get_role(STAFF_ROLE_ID)

        is_staff = (
            staff_role is not None
            and staff_role in interaction.user.roles
        )

        if not (
            is_staff
            or interaction.user.guild_permissions.administrator
        ):
            return await interaction.response.send_message(
                "Você não tem permissão para fechar este atendimento.",
                ephemeral=True
            )

        await interaction.response.send_modal(
            CloseReasonModal()
        )


# ==========================================
# BOT
# ==========================================

class TicketBot(commands.Bot):

    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):

        # Conectar ao Supabase
        await connect_database()

        # Registrar views persistentes
        self.add_view(TicketPanelView())
        self.add_view(TicketControlView())

        # Sincronizar comandos slash
        await self.tree.sync()

        print("Views persistentes registradas.")
        print("Comandos slash sincronizados.")


bot = TicketBot()


# ==========================================
# COMANDO PARA PUBLICAR O PAINEL
# ==========================================

@bot.hybrid_command(
    name="painel_ticket",
    description="Publica o painel de atendimento."
)
@commands.guild_only()
async def painel_ticket(ctx):

    if not ctx.author.guild_permissions.administrator:
        return await ctx.send(
            "Você precisa ser administrador para usar este comando.",
            ephemeral=True
        )

    embed = discord.Embed(
        title=PANEL_TITLE,
        description=PANEL_DESCRIPTION,
        color=EMBED_COLOR
    )

    embed.set_image(url=PANEL_IMAGE)

    embed.set_footer(
        text="Central de Atendimento • Selecione uma opção abaixo."
    )

    await ctx.send(
        embed=embed,
        view=TicketPanelView()
    )


# ==========================================
# EVENTOS
# ==========================================

@bot.event
async def on_ready():
    print("=" * 40)
    print(f"Bot conectado: {bot.user}")
    print(f"ID: {bot.user.id}")
    print(f"Servidores: {len(bot.guilds)}")
    print("=" * 40)


# ==========================================
# INICIALIZAÇÃO
# ==========================================

if not TOKEN:
    raise RuntimeError(
        "A variável DISCORD_TOKEN não foi configurada."
    )

if not DB_PASSWORD:
    raise RuntimeError(
        "A variável SUPABASE_DB_PASSWORD não foi configurada."
    )

bot.run(TOKEN)
