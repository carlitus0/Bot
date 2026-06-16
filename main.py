import os
import discord
from discord.ext import commands
from discord import Embed
from datetime import datetime
import json
import asyncio
from discord.ui import View, Button

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)

# Lista temporária de staff
staff_roles = set()
staff_users = set()


@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user}")


def is_staff():
    async def predicate(ctx):

        if ctx.author.guild_permissions.administrator:
            return True

        if ctx.author.id in staff_users:
            return True

        for role in ctx.author.roles:
            if role.id in staff_roles:
                return True

        raise commands.CheckFailure

    return commands.check(predicate)


@bot.command()
@commands.has_permissions(administrator=True)
async def staff(ctx, alvo: discord.Role | discord.Member):

    if isinstance(alvo, discord.Role):
        staff_roles.add(alvo.id)
        await ctx.send(
            f"✅ O cargo {alvo.mention} agora pode usar comandos de moderação."
        )

    else:
        staff_users.add(alvo.id)
        await ctx.send(
            f"✅ {alvo.mention} agora pode usar comandos de moderação."
        )


@bot.command()
@commands.has_permissions(administrator=True)
async def unstaff(ctx, alvo: discord.Role | discord.Member):

    if isinstance(alvo, discord.Role):
        staff_roles.discard(alvo.id)
        await ctx.send(
            f"✅ O cargo {alvo.mention} perdeu acesso aos comandos de moderação."
        )

    else:
        staff_users.discard(alvo.id)
        await ctx.send(
            f"✅ {alvo.mention} perdeu acesso aos comandos de moderação."
        )


@bot.command()
@is_staff()
async def ban(ctx, member: discord.Member, *, motivo="Nenhum motivo informado"):

    if member == ctx.author:
        return await ctx.send("❌ Você não pode banir a si mesmo.")

    if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
        return await ctx.send(
            "❌ Você não pode banir alguém com cargo igual ou superior ao seu."
        )

    embed = Embed(
        title="🔨 Você foi banido",
        description="Você foi removido do servidor.",
        color=discord.Color.red(),
        timestamp=datetime.utcnow()
    )

    embed.add_field(
        name="Servidor",
        value=ctx.guild.name,
        inline=False
    )

    embed.add_field(
        name="Motivo",
        value=motivo,
        inline=False
    )

    embed.add_field(
        name="Moderador",
        value=str(ctx.author),
        inline=False
    )

    embed.add_field(
        name="Aviso",
        value=(
            "Se você acredita que este banimento foi aplicado incorretamente, "
            "entre em contato com a equipe do servidor."
        ),
        inline=False
    )

    embed.set_footer(text="Sistema de Moderação")

    try:
        await member.send(embed=embed)
    except:
        pass

    await member.ban(reason=f"{motivo} | Staff: {ctx.author}")

    await ctx.send(
        f"✅ {member.mention} foi banido.\n📝 Motivo: `{motivo}`"
    )


@staff.error
@unstaff.error
@ban.error
async def command_error(ctx, error):

    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Você não possui permissão para usar este comando.")

    elif isinstance(error, commands.CheckFailure):
        await ctx.send("❌ Apenas membros da staff podem usar este comando.")

    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Usuário não encontrado.")

    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Faltam argumentos no comando.")

    else:
        raise error
@bot.command()
@is_staff()
async def unban(ctx, user_id: int, *, motivo="Nenhum motivo informado"):

    try:
        user = await bot.fetch_user(user_id)

        await ctx.guild.unban(
            user,
            reason=f"{motivo} | Staff: {ctx.author}"
        )

        embed = Embed(
            title="🔓 Seu banimento foi removido",
            description="Você pode entrar novamente no servidor.",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )

        embed.add_field(
            name="Servidor",
            value=ctx.guild.name,
            inline=False
        )

        embed.add_field(
            name="Motivo",
            value=motivo,
            inline=False
        )

        embed.add_field(
            name="Moderador",
            value=str(ctx.author),
            inline=False
        )

        embed.set_footer(text="Sistema de Moderação")

        try:
            await user.send(embed=embed)
        except:
            pass

        await ctx.send(
            f"✅ O banimento de **{user}** foi removido."
        )

    except discord.NotFound:
        await ctx.send("❌ Usuário não encontrado.")

    except discord.Forbidden:
        await ctx.send("❌ Não tenho permissão para remover este banimento.")
        
from datetime import timedelta
from discord.utils import utcnow


@bot.command(
    name="mute",
    help="Aplica um timeout em um membro."
)
async def mute(
    ctx,
    member: discord.Member,
    minutos: int,
    *,
    motivo="Nenhum motivo informado"
):
    # Verifica permissão de staff definida pelo seu sistema !staff
    if not has_staff_permission(ctx.author):
        return await ctx.send(
            "❌ Você não possui permissão para usar este comando."
        )

    # Impede punição em si mesmo
    if member == ctx.author:
        return await ctx.send(
            "❌ Você não pode aplicar timeout em si mesmo."
        )

    # Impede punição no dono do servidor
    if member == ctx.guild.owner:
        return await ctx.send(
            "❌ Você não pode aplicar timeout no dono do servidor."
        )

    # Verifica hierarquia de cargos
    if (
        member.top_role >= ctx.author.top_role
        and ctx.author != ctx.guild.owner
    ):
        return await ctx.send(
            "❌ Você não pode punir alguém com cargo igual ou superior ao seu."
        )

    # Verifica se o bot possui permissão
    if not ctx.guild.me.guild_permissions.moderate_members:
        return await ctx.send(
            "❌ Eu não tenho a permissão 'Moderar membros'."
        )

    # Verifica hierarquia do bot
    if member.top_role >= ctx.guild.me.top_role:
        return await ctx.send(
            "❌ Meu cargo precisa estar acima do cargo deste usuário."
        )

    # Verifica tempo válido
    if minutos <= 0:
        return await ctx.send(
            "❌ Informe um tempo válido em minutos."
        )

    # Limite máximo do Discord: 28 dias
    if minutos > 40320:
        return await ctx.send(
            "❌ O tempo máximo de timeout é 28 dias (40320 minutos)."
        )

    until = utcnow() + timedelta(minutes=minutos)

    embed_dm = discord.Embed(
        title="🔇 Você recebeu um timeout",
        description=(
            "Seu acesso para enviar mensagens, participar de chamadas "
            "de voz e interagir no servidor foi temporariamente restringido."
        ),
        color=discord.Color.orange(),
        timestamp=utcnow()
    )

    embed_dm.add_field(
        name="🏠 Servidor",
        value=ctx.guild.name,
        inline=False
    )

    embed_dm.add_field(
        name="⏱️ Duração",
        value=f"{minutos} minuto(s)",
        inline=True
    )

    embed_dm.add_field(
        name="📝 Motivo",
        value=motivo,
        inline=False
    )

    embed_dm.add_field(
        name="🛡️ Moderador",
        value=str(ctx.author),
        inline=False
    )

    embed_dm.add_field(
        name="ℹ️ Informações",
        value=(
            "Após o término do tempo, suas permissões serão restauradas "
            "automaticamente.\n\n"
            "Caso considere a punição incorreta, entre em contato com a equipe."
        ),
        inline=False
    )

    embed_dm.set_footer(text="Sistema de Moderação")

    try:
        await member.send(embed=embed_dm)
    except discord.Forbidden:
        pass

    await member.timeout(
        until,
        reason=f"{motivo} | Staff: {ctx.author}"
    )

    embed_publico = discord.Embed(
        title="🔇 Timeout aplicado",
        color=discord.Color.orange(),
        timestamp=utcnow()
    )

    embed_publico.add_field(
        name="👤 Usuário",
        value=f"{member.mention} (`{member.id}`)",
        inline=False
    )

    embed_publico.add_field(
        name="⏱️ Duração",
        value=f"{minutos} minuto(s)",
        inline=True
    )

    embed_publico.add_field(
        name="🛡️ Moderador",
        value=ctx.author.mention,
        inline=True
    )

    embed_publico.add_field(
        name="📝 Motivo",
        value=motivo,
        inline=False
    )

    await ctx.send(embed=embed_publico)


@mute.error
async def mute_error(ctx, error):

    if isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Usuário não encontrado.")

    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            "❌ Uso correto: `!mute @usuário <minutos> <motivo>`"
        )

    elif isinstance(error, commands.BadArgument):
        await ctx.send(
            "❌ O tempo deve ser um número inteiro."
        )

    else:
        raise error

@bot.command(
    name="warn",
    help="Aplica uma advertência em um membro."
)
async def warn(ctx, member: discord.Member, *, motivo="Nenhum motivo informado"):

    if not has_staff_permission(ctx.author):
        return await ctx.send(
            "❌ Você não possui permissão para usar este comando."
        )

    if member == ctx.author:
        return await ctx.send(
            "❌ Você não pode advertir a si mesmo."
        )

    if member == ctx.guild.owner:
        return await ctx.send(
            "❌ Você não pode advertir o dono do servidor."
        )

    if (
        member.top_role >= ctx.author.top_role
        and ctx.author != ctx.guild.owner
    ):
        return await ctx.send(
            "❌ Você não pode advertir alguém com cargo igual ou superior ao seu."
        )

    if member.top_role >= ctx.guild.me.top_role:
        return await ctx.send(
            "❌ Meu cargo precisa estar acima do cargo deste usuário."
        )

    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS warns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        moderator_id INTEGER NOT NULL,
        reason TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)

    data_warn = datetime.utcnow().strftime("%d/%m/%Y %H:%M:%S")

    cursor.execute("""
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
        data_warn
    ))

    conn.commit()

    cursor.execute("""
        SELECT COUNT(*)
        FROM warns
        WHERE guild_id = ? AND user_id = ?
    """, (
        ctx.guild.id,
        member.id
    ))

    total_warns = cursor.fetchone()[0]

    conn.close()

    embed_dm = discord.Embed(
        title="⚠️ Você recebeu uma advertência",
        description="Esta é uma notificação oficial da equipe de moderação.",
        color=discord.Color.gold(),
        timestamp=datetime.utcnow()
    )

    embed_dm.add_field(
        name="🏠 Servidor",
        value=ctx.guild.name,
        inline=False
    )

    embed_dm.add_field(
        name="📝 Motivo",
        value=motivo,
        inline=False
    )

    embed_dm.add_field(
        name="📊 Advertências",
        value=f"{total_warns}/4",
        inline=True
    )

    embed_dm.add_field(
        name="🛡️ Moderador",
        value=str(ctx.author),
        inline=True
    )

    embed_dm.add_field(
        name="ℹ️ Aviso",
        value=(
            "Ao atingir 4 advertências, o banimento será aplicado automaticamente.\n"
            "Caso considere esta punição incorreta, entre em contato com a equipe."
        ),
        inline=False
    )

    embed_dm.set_footer(text="Sistema de Moderação")

    try:
        await member.send(embed=embed_dm)
    except discord.Forbidden:
        pass

    embed_publico = discord.Embed(
        title="⚠️ Advertência aplicada",
        color=discord.Color.gold(),
        timestamp=datetime.utcnow()
    )

    embed_publico.add_field(
        name="👤 Usuário",
        value=f"{member.mention} (`{member.id}`)",
        inline=False
    )

    embed_publico.add_field(
        name="📊 Advertências",
        value=f"{total_warns}/4",
        inline=True
    )

    embed_publico.add_field(
        name="🛡️ Moderador",
        value=ctx.author.mention,
        inline=True
    )

    embed_publico.add_field(
        name="📝 Motivo",
        value=motivo,
        inline=False
    )

    await ctx.send(embed=embed_publico)

    if total_warns >= 4:

        embed_ban = discord.Embed(
            title="🔨 Você foi banido",
            description="Você atingiu o limite máximo de advertências permitido.",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )

        embed_ban.add_field(
            name="🏠 Servidor",
            value=ctx.guild.name,
            inline=False
        )

        embed_ban.add_field(
            name="📊 Advertências",
            value=f"{total_warns}/4",
            inline=True
        )

        embed_ban.add_field(
            name="📝 Motivo",
            value="Acúmulo de advertências.",
            inline=False
        )

        embed_ban.set_footer(text="Sistema de Moderação")

        try:
            await member.send(embed=embed_ban)
        except discord.Forbidden:
            pass

        await member.ban(
            reason="Banimento automático: 4 advertências."
        )

        await ctx.send(
            f"🔨 {member.mention} foi banido automaticamente por atingir 4 advertências."
        )


@bot.command(
    name="warns",
    help="Exibe as advertências de um membro."
)
async def warns(ctx, member: discord.Member = None):

    if not has_staff_permission(ctx.author):
        return await ctx.send(
            "❌ Você não possui permissão para usar este comando."
        )

    member = member or ctx.author

    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT moderator_id, reason, created_at
        FROM warns
        WHERE guild_id = ? AND user_id = ?
        ORDER BY id DESC
    """, (
        ctx.guild.id,
        member.id
    ))

    registros = cursor.fetchall()

    conn.close()

    if not registros:
        return await ctx.send(
            f"✅ {member.mention} não possui advertências."
        )

    embed = discord.Embed(
        title=f"📋 Advertências de {member}",
        color=discord.Color.orange(),
        timestamp=datetime.utcnow()
    )

    embed.set_thumbnail(url=member.display_avatar.url)

    embed.description = (
        f"**Total de advertências:** {len(registros)}/4\n\n"
    )

    for indice, (moderator_id, reason, created_at) in enumerate(registros[:10], start=1):

        moderador = bot.get_user(moderator_id)

        embed.add_field(
            name=f"⚠️ Warn #{indice}",
            value=(
                f"**Motivo:** {reason}\n"
                f"**Moderador:** {moderador or moderator_id}\n"
                f"**Data:** {created_at}"
            ),
            inline=False
        )

    embed.set_footer(text="Máximo exibido: 10 advertências")

    await ctx.send(embed=embed)


@warn.error
@warns.error
async def warn_error(ctx, error):

    if isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Usuário não encontrado.")

    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            "❌ Uso correto:\n"
            "`!warn @usuário <motivo>`\n"
            "`!warns @usuário`"
        )

    else:
        raise error

@bot.command()
async def hackban(ctx, user_id: int, *, motivo="Nenhum motivo informado"):

    if not await is_staff(ctx.author):
        return await ctx.send("❌ Você não possui permissão para usar este comando.")

    try:
        user = await bot.fetch_user(user_id)

        embed = Embed(
            title="🔨 Você foi banido",
            description=(
                "Seu acesso a um servidor foi permanentemente revogado "
                "por descumprimento das regras."
            ),
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )

        embed.add_field(
            name="Servidor",
            value=ctx.guild.name,
            inline=False
        )

        embed.add_field(
            name="Motivo",
            value=motivo,
            inline=False
        )

        embed.add_field(
            name="Moderador",
            value=str(ctx.author),
            inline=False
        )

        embed.add_field(
            name="Tipo de punição",
            value="Banimento por ID (Hackban)",
            inline=False
        )

        embed.add_field(
            name="Aviso",
            value=(
                "Caso considere esta punição incorreta, "
                "entre em contato com a equipe responsável."
            ),
            inline=False
        )

        embed.set_footer(text="Sistema de Moderação")

        try:
            await user.send(embed=embed)
        except:
            pass

        await ctx.guild.ban(
            user,
            reason=f"{motivo} | Staff: {ctx.author}"
        )

        await ctx.send(
            f"✅ Usuário `{user}` (`{user.id}`) foi banido por ID.\n"
            f"📝 Motivo: `{motivo}`"
        )

    except discord.NotFound:
        await ctx.send("❌ Usuário não encontrado.")

    except discord.Forbidden:
        await ctx.send("❌ Não tenho permissão para realizar este banimento.")

    except Exception as e:
        await ctx.send(f"❌ Ocorreu um erro: `{e}`")


@bot.command()
async def unban(ctx, user_id: int, *, motivo="Nenhum motivo informado"):

    if not await is_staff(ctx.author):
        return await ctx.send("❌ Você não possui permissão para usar este comando.")

    try:
        user = await bot.fetch_user(user_id)

        await ctx.guild.unban(
            user,
            reason=f"{motivo} | Staff: {ctx.author}"
        )

        embed = Embed(
            title="🔓 Seu banimento foi removido",
            description="Você pode entrar novamente no servidor.",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )

        embed.add_field(
            name="Servidor",
            value=ctx.guild.name,
            inline=False
        )

        embed.add_field(
            name="Motivo da remoção",
            value=motivo,
            inline=False
        )

        embed.add_field(
            name="Moderador",
            value=str(ctx.author),
            inline=False
        )

        embed.set_footer(text="Sistema de Moderação")

        try:
            await user.send(embed=embed)
        except:
            pass

        await ctx.send(
            f"✅ Banimento removido de `{user}` (`{user.id}`)."
        )

    except discord.NotFound:
        await ctx.send("❌ Usuário não encontrado.")

    except discord.Forbidden:
        await ctx.send("❌ Não tenho permissão para remover este banimento.")

    except Exception as e:
        await ctx.send(f"❌ Ocorreu um erro: `{e}`")


@hackban.error
@unban.error
async def hackban_unban_error(ctx, error):

    if isinstance(error, commands.MissingRequiredArgument):
        if ctx.command.name == "hackban":
            await ctx.send("❌ Use: `!hackban <id> <motivo>`")
        else:
            await ctx.send("❌ Use: `!unban <id> <motivo>`")

    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Informe um ID válido.")

    else:
        raise error

# ===== SISTEMA DE TICKETS =====

TICKET_CONFIG = "tickets.json"


def load_ticket_config():
    try:
        with open(TICKET_CONFIG, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def save_ticket_config(data):
    with open(TICKET_CONFIG, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


class TicketControlsView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🔒 Fechar",
        style=discord.ButtonStyle.red,
        custom_id="ticket_close"
    )
    async def close_ticket(self, interaction: discord.Interaction, button):

        if not await is_staff(interaction.user):
            return await interaction.response.send_message(
                "❌ Apenas a equipe pode fechar tickets.",
                ephemeral=True
            )

        await interaction.response.send_message(
            "🔒 Ticket será fechado em 5 segundos.",
            ephemeral=True
        )

        await asyncio.sleep(5)

        await interaction.channel.delete()

    @discord.ui.button(
        label="➕ Adicionar",
        style=discord.ButtonStyle.secondary,
        custom_id="ticket_add"
    )
    async def add_info(self, interaction: discord.Interaction, button):

        await interaction.response.send_message(
            "Use `!ticketadd @usuário`.",
            ephemeral=True
        )

    @discord.ui.button(
        label="➖ Remover",
        style=discord.ButtonStyle.secondary,
        custom_id="ticket_remove"
    )
    async def remove_info(self, interaction: discord.Interaction, button):

        await interaction.response.send_message(
            "Use `!ticketremove @usuário`.",
            ephemeral=True
        )


class TicketPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🎫 Abrir Ticket",
        style=discord.ButtonStyle.green,
        custom_id="ticket_open"
    )
    async def open_ticket(self, interaction: discord.Interaction, button):

        data = load_ticket_config()
        guild_data = data.get(str(interaction.guild.id))

        if not guild_data:
            return await interaction.response.send_message(
                "❌ Sistema de tickets não configurado.",
                ephemeral=True
            )

        category = interaction.guild.get_channel(
            guild_data["category_id"]
        )

        if not category:
            return await interaction.response.send_message(
                "❌ Categoria de tickets não encontrada.",
                ephemeral=True
            )

        existing = discord.utils.get(
            category.text_channels,
            name=f"ticket-{interaction.user.id}"
        )

        if existing:
            return await interaction.response.send_message(
                f"❌ Você já possui um ticket: {existing.mention}",
                ephemeral=True
            )

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(
                view_channel=False
            ),

            interaction.user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                attach_files=True,
                embed_links=True,
                read_message_history=True
            ),

            interaction.guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                manage_messages=True
            )
        }

        for role_id in guild_data.get("staff_roles", []):
            role = interaction.guild.get_role(role_id)

            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True
                )

        channel = await interaction.guild.create_text_channel(
            name=f"ticket-{interaction.user.id}",
            category=category,
            overwrites=overwrites
        )

        embed = Embed(
            title="🎫 Ticket Aberto",
            description=(
                f"Olá {interaction.user.mention}.\n\n"
                "Explique detalhadamente seu problema.\n"
                "A equipe responderá em breve."
            ),
            color=discord.Color.blurple()
        )

        embed.set_footer(text=f"ID do usuário: {interaction.user.id}")

        await channel.send(
            content=interaction.user.mention,
            embed=embed,
            view=TicketControlsView()
        )

        await interaction.response.send_message(
            f"✅ Ticket criado: {channel.mention}",
            ephemeral=True
        )


@bot.command()
async def setticket(ctx, category: discord.CategoryChannel):

    if not await is_staff(ctx.author):
        return await ctx.send("❌ Você não possui permissão.")

    data = load_ticket_config()

    data[str(ctx.guild.id)] = {
        "category_id": category.id,
        "staff_roles": []
    }

    save_ticket_config(data)

    await ctx.send(
        f"✅ Categoria de tickets definida para **{category.name}**."
    )


@bot.command()
async def ticketstaff(ctx, role: discord.Role):

    if not await is_staff(ctx.author):
        return await ctx.send("❌ Você não possui permissão.")

    data = load_ticket_config()
    guild_id = str(ctx.guild.id)

    if guild_id not in data:
        return await ctx.send(
            "❌ Configure primeiro usando `!setticket`."
        )

    if role.id not in data[guild_id]["staff_roles"]:
        data[guild_id]["staff_roles"].append(role.id)

    save_ticket_config(data)

    await ctx.send(
        f"✅ {role.mention} adicionada à equipe de tickets."
    )


@bot.command()
async def ticketpanel(ctx):

    if not await is_staff(ctx.author):
        return await ctx.send("❌ Você não possui permissão.")

    embed = Embed(
        title="🎫 Central de Atendimento",
        description=(
            "Clique no botão abaixo para abrir um ticket.\n\n"
            "Evite criar tickets duplicados."
        ),
        color=discord.Color.blurple()
    )

    await ctx.send(
        embed=embed,
        view=TicketPanelView()
    )


@bot.command()
async def ticketadd(ctx, member: discord.Member):

    if not await is_staff(ctx.author):
        return await ctx.send("❌ Você não possui permissão.")

    await ctx.channel.set_permissions(
        member,
        view_channel=True,
        send_messages=True,
        read_message_history=True
    )

    await ctx.send(
        f"✅ {member.mention} foi adicionado ao ticket."
    )


@bot.command()
async def ticketremove(ctx, member: discord.Member):

    if not await is_staff(ctx.author):
        return await ctx.send("❌ Você não possui permissão.")

    await ctx.channel.set_permissions(
        member,
        overwrite=None
    )

    await ctx.send(
        f"✅ {member.mention} foi removido do ticket."
                 )

# ========= BANCO DE DADOS DOS LOGS =========

def create_logs_table():
    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            guild_id INTEGER PRIMARY KEY,
            punishment_log INTEGER,
            message_log INTEGER,
            command_log INTEGER
        )
    """)

    conn.commit()
    conn.close()

create_logs_table()


def set_log(guild_id, log_type, channel_id):

    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()

    cur.execute(
        "INSERT OR IGNORE INTO logs (guild_id) VALUES (?)",
        (guild_id,)
    )

    cur.execute(
        f"UPDATE logs SET {log_type} = ? WHERE guild_id = ?",
        (channel_id, guild_id)
    )

    conn.commit()
    conn.close()


def get_log(guild_id, log_type):

    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()

    cur.execute(
        f"SELECT {log_type} FROM logs WHERE guild_id = ?",
        (guild_id,)
    )

    data = cur.fetchone()

    conn.close()

    return data[0] if data and data[0] else None


# ========= COMANDOS =========

@bot.command()
async def setlogcommands(ctx, canal: discord.TextChannel):

    if not is_staff(ctx.author, ctx.guild):
        return await ctx.send("❌ Você não possui permissão.")

    set_log(ctx.guild.id, "command_log", canal.id)

    await ctx.send(
        f"✅ Logs de comandos definidos para {canal.mention}"
    )


@bot.command()
async def setlogmessages(ctx, canal: discord.TextChannel):

    if not is_staff(ctx.author, ctx.guild):
        return await ctx.send("❌ Você não possui permissão.")

    set_log(ctx.guild.id, "message_log", canal.id)

    await ctx.send(
        f"✅ Logs de mensagens definidos para {canal.mention}"
    )


@bot.command()
async def setlogpunishments(ctx, canal: discord.TextChannel):

    if not is_staff(ctx.author, ctx.guild):
        return await ctx.send("❌ Você não possui permissão.")

    set_log(ctx.guild.id, "punishment_log", canal.id)

    await ctx.send(
        f"✅ Logs de punições definidos para {canal.mention}"
    )


# ========= LOG DE COMANDOS =========

@bot.event
async def on_command(ctx):

    if not ctx.guild:
        return

    canal_id = get_log(ctx.guild.id, "command_log")

    if not canal_id:
        return

    canal = bot.get_channel(canal_id)

    if not canal:
        return

    embed = Embed(
        title="📋 Comando Executado",
        color=discord.Color.blue(),
        timestamp=datetime.utcnow()
    )

    embed.add_field(
        name="Autor",
        value=f"{ctx.author} ({ctx.author.id})",
        inline=False
    )

    embed.add_field(
        name="Canal",
        value=ctx.channel.mention,
        inline=False
    )

    embed.add_field(
        name="Comando",
        value=f"```{ctx.message.content[:1000]}```",
        inline=False
    )

    await canal.send(embed=embed)


# ========= LOG DE MENSAGENS =========

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    if message.guild:

        canal_id = get_log(message.guild.id, "message_log")

        if canal_id:

            canal = bot.get_channel(canal_id)

            if canal and canal.id != message.channel.id:

                embed = Embed(
                    title="💬 Nova Mensagem",
                    color=discord.Color.dark_grey(),
                    timestamp=datetime.utcnow()
                )

                embed.add_field(
                    name="Autor",
                    value=f"{message.author} ({message.author.id})",
                    inline=False
                )

                embed.add_field(
                    name="Canal",
                    value=message.channel.mention,
                    inline=False
                )

                embed.add_field(
                    name="Conteúdo",
                    value=message.content[:1024] or "*Sem texto*",
                    inline=False
                )

                if message.attachments:

                    arquivos = "\n".join(
                        anexo.url
                        for anexo in message.attachments[:10]
                    )

                    embed.add_field(
                        name="Anexos",
                        value=arquivos[:1024],
                        inline=False
                    )

                await canal.send(embed=embed)

    await bot.process_commands(message)


# ========= LOGS AUTOMÁTICOS DE PUNIÇÕES =========

@bot.event
async def on_command_completion(ctx):

    if not ctx.guild:
        return

    comandos_punicao = {
        "ban": "🔨 Banimento",
        "unban": "🔓 Desbanimento",
        "mute": "🔇 Timeout",
        "unmute": "🔊 Remoção de Timeout",
        "warn": "⚠️ Advertência",
        "warns": "📄 Consulta de Advertências",
        "hackban": "🛑 Hackban",
        "prision": "⛓️ Prisão",
        "unprision": "🔓 Remoção da Prisão"
    }

    comando = ctx.command.name.lower()

    if comando not in comandos_punicao:
        return

    canal_id = get_log(ctx.guild.id, "punishment_log")

    if not canal_id:
        return

    canal = bot.get_channel(canal_id)

    if not canal:
        return

    embed = Embed(
        title=comandos_punicao[comando],
        color=discord.Color.red(),
        timestamp=datetime.utcnow()
    )

    embed.add_field(
        name="Moderador",
        value=f"{ctx.author} ({ctx.author.id})",
        inline=False
    )

    embed.add_field(
        name="Canal",
        value=ctx.channel.mention,
        inline=False
    )

    embed.add_field(
        name="Comando Utilizado",
        value=f"```{ctx.message.content[:1000]}```",
        inline=False
    )

    await canal.send(embed=embed)

# ========= TABELAS =========

def create_automod_tables():

    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS automod_words (
            guild_id INTEGER,
            word TEXT,
            PRIMARY KEY (guild_id, word)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS automod_config (
            guild_id INTEGER PRIMARY KEY,
            punishment TEXT DEFAULT 'delete',
            mute_minutes INTEGER DEFAULT 10
        )
    """)

    conn.commit()
    conn.close()


create_automod_tables()


# ========= FUNÇÕES =========

def add_automod_word(guild_id, word):

    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()

    cur.execute(
        "INSERT OR IGNORE INTO automod_words VALUES (?, ?)",
        (guild_id, word.lower())
    )

    conn.commit()
    conn.close()


def remove_automod_word(guild_id, word):

    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()

    cur.execute(
        "DELETE FROM automod_words WHERE guild_id = ? AND word = ?",
        (guild_id, word.lower())
    )

    conn.commit()
    conn.close()


def get_automod_words(guild_id):

    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()

    cur.execute(
        "SELECT word FROM automod_words WHERE guild_id = ?",
        (guild_id,)
    )

    words = [row[0] for row in cur.fetchall()]

    conn.close()

    return words


def set_automod_punishment(guild_id, punishment):

    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()

    cur.execute(
        "INSERT OR IGNORE INTO automod_config (guild_id) VALUES (?)",
        (guild_id,)
    )

    cur.execute(
        "UPDATE automod_config SET punishment = ? WHERE guild_id = ?",
        (punishment, guild_id)
    )

    conn.commit()
    conn.close()


def set_automod_mute(guild_id, minutes):

    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()

    cur.execute(
        "INSERT OR IGNORE INTO automod_config (guild_id) VALUES (?)",
        (guild_id,)
    )

    cur.execute(
        "UPDATE automod_config SET mute_minutes = ? WHERE guild_id = ?",
        (minutes, guild_id)
    )

    conn.commit()
    conn.close()


def get_automod_config(guild_id):

    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()

    cur.execute(
        "SELECT punishment, mute_minutes FROM automod_config WHERE guild_id = ?",
        (guild_id,)
    )

    data = cur.fetchone()

    conn.close()

    if data:
        return data

    return ("delete", 10)


# ========= COMANDOS =========

@bot.command()
async def addword(ctx, *, palavra):

    if not is_staff(ctx.author, ctx.guild):
        return await ctx.send("❌ Sem permissão.")

    add_automod_word(ctx.guild.id, palavra)

    await ctx.send(f"✅ Palavra adicionada: `{palavra}`")


@bot.command()
async def removeword(ctx, *, palavra):

    if not is_staff(ctx.author, ctx.guild):
        return await ctx.send("❌ Sem permissão.")

    remove_automod_word(ctx.guild.id, palavra)

    await ctx.send(f"✅ Palavra removida: `{palavra}`")


@bot.command()
async def listwords(ctx):

    if not is_staff(ctx.author, ctx.guild):
        return await ctx.send("❌ Sem permissão.")

    words = get_automod_words(ctx.guild.id)

    if not words:
        return await ctx.send("📭 Nenhuma palavra configurada.")

    embed = discord.Embed(
        title="🛡️ Palavras Bloqueadas",
        description="\n".join(f"• `{w}`" for w in words[:100]),
        color=discord.Color.orange()
    )

    await ctx.send(embed=embed)


@bot.command()
async def clearwords(ctx):

    if not is_staff(ctx.author, ctx.guild):
        return await ctx.send("❌ Sem permissão.")

    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()

    cur.execute(
        "DELETE FROM automod_words WHERE guild_id = ?",
        (ctx.guild.id,)
    )

    conn.commit()
    conn.close()

    await ctx.send("✅ Lista limpa.")


@bot.command()
async def setautomod(ctx, punicao: str):

    if not is_staff(ctx.author, ctx.guild):
        return await ctx.send("❌ Sem permissão.")

    punicao = punicao.lower()

    if punicao not in ["delete", "warn", "mute"]:
        return await ctx.send(
            "❌ Opções: `delete`, `warn`, `mute`"
        )

    set_automod_punishment(ctx.guild.id, punicao)

    await ctx.send(f"✅ Punição definida: `{punicao}`")


@bot.command()
async def setautomodmute(ctx, minutos: int):

    if not is_staff(ctx.author, ctx.guild):
        return await ctx.send("❌ Sem permissão.")

    set_automod_mute(ctx.guild.id, minutos)

    await ctx.send(f"✅ Duração do mute: `{minutos}` minutos")

class StaffPanel(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction):

        if not is_staff(interaction.user, interaction.guild):
            await interaction.response.send_message(
                "❌ Você não possui permissão.",
                ephemeral=True
            )
            return False

        return True

    @discord.ui.button(
        label="Ban",
        emoji="🔨",
        style=discord.ButtonStyle.danger
    )
    async def ban_button(self, interaction, button):

        await interaction.response.send_message(
            "Use: `!ban @usuário motivo`",
            ephemeral=True
        )

    @discord.ui.button(
        label="Mute",
        emoji="🔇",
        style=discord.ButtonStyle.secondary
    )
    async def mute_button(self, interaction, button):

        await interaction.response.send_message(
            "Use: `!mute @usuário tempo motivo`",
            ephemeral=True
        )

    @discord.ui.button(
        label="Warn",
        emoji="⚠️",
        style=discord.ButtonStyle.primary
    )
    async def warn_button(self, interaction, button):

        await interaction.response.send_message(
            "Use: `!warn @usuário motivo`",
            ephemeral=True
        )

    @discord.ui.button(
        label="Prisão",
        emoji="⛓️",
        style=discord.ButtonStyle.secondary
    )
    async def prison_button(self, interaction, button):

        await interaction.response.send_message(
            "Use: `!prision @usuário tempo motivo`",
            ephemeral=True
        )

    @discord.ui.button(
        label="Tickets",
        emoji="🎫",
        style=discord.ButtonStyle.success
    )
    async def ticket_button(self, interaction, button):

        await interaction.response.send_message(
            "Use os comandos de ticket configurados.",
            ephemeral=True
        )


@bot.command()
async def panelstaff(ctx):

    if not is_staff(ctx.author, ctx.guild):
        return await ctx.send("❌ Você não possui permissão.")

    embed = discord.Embed(
        title="🛡️ Painel da Equipe",
        description=(
            "Use os botões abaixo para acessar rapidamente "
            "os sistemas de moderação."
        ),
        color=discord.Color.blurple(),
        timestamp=datetime.utcnow()
    )

    embed.add_field(
        name="Funções",
        value=(
            "🔨 Banimentos\n"
            "🔇 Mutes\n"
            "⚠️ Advertências\n"
            "⛓️ Prisões\n"
            "🎫 Tickets"
        ),
        inline=False
    )

    await ctx.send(
        embed=embed,
        view=StaffPanel()
    )

bot.run(TOKEN)
