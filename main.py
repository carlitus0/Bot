import os
import json
import sqlite3
import asyncio
import uuid
import hmac
import hashlib
import base64
import io
import math
from threading import Thread

import requests
import discord
from discord.ext import commands
from discord import app_commands
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import uvicorn


# CONFIGURAÇÕES

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
MP_TOKEN = os.getenv("MP_ACCESS_TOKEN")
PORT = int(os.getenv("PORT", "8080"))

DB_FILE = "bot.db"
PRODUCTS_FILE = "products.json"


# PRODUTOS

def load_products():
    try:
        with open(PRODUCTS_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
            return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        print("AVISO: products.json não encontrado.")
        return {}
    except json.JSONDecodeError:
        print("ERRO: products.json inválido.")
        return {}


products = load_products()


# BANCO DE DADOS

def database():
    return sqlite3.connect(DB_FILE, timeout=30)


def setup_database():
    with database() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_id TEXT UNIQUE,
                user_id TEXT NOT NULL,
                guild_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                amount REAL NOT NULL,
                status TEXT DEFAULT 'pending'
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS guild_config (
                guild_id TEXT PRIMARY KEY,
                shop_channel_id TEXT,
                log_channel_id TEXT
            )
        """)


def set_guild_channel(guild_id, column, channel_id):
    if column not in ("shop_channel_id", "log_channel_id"):
        raise ValueError("Configuração inválida.")

    with database() as conn:
        conn.execute(
            f"""
            INSERT INTO guild_config (guild_id, {column})
            VALUES (?, ?)
            ON CONFLICT(guild_id)
            DO UPDATE SET {column} = excluded.{column}
            """,
            (str(guild_id), str(channel_id))
        )


def get_guild_config(guild_id):
    with database() as conn:
        row = conn.execute("""
            SELECT shop_channel_id, log_channel_id
            FROM guild_config
            WHERE guild_id = ?
        """, (str(guild_id),)).fetchone()

    if not row:
        return {"shop_channel_id": None, "log_channel_id": None}

    return {
        "shop_channel_id": int(row[0]) if row[0] else None,
        "log_channel_id": int(row[1]) if row[1] else None
    }


def create_order(payment_id, user_id, guild_id, product_id, amount):
    with database() as conn:
        conn.execute("""
            INSERT INTO orders
            (payment_id, user_id, guild_id, product_id, amount, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
        """, (
            str(payment_id),
            str(user_id),
            str(guild_id),
            str(product_id),
            float(amount)
        ))


def get_order(payment_id):
    with database() as conn:
        return conn.execute(
            "SELECT * FROM orders WHERE payment_id = ?",
            (str(payment_id),)
        ).fetchone()


def update_order(payment_id, status):
    with database() as conn:
        conn.execute(
            "UPDATE orders SET status = ? WHERE payment_id = ?",
            (status, str(payment_id))
        )


setup_database()


# BOT DISCORD

intents = discord.Intents.default()
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
api = FastAPI()
persistent_view_registered = False


# MERCADO PAGO

def create_pix_payment(user_id, guild_id, product_id, email):
    if not MP_TOKEN:
        raise RuntimeError("MP_ACCESS_TOKEN não configurado.")

    product = products.get(product_id)
    if not product:
        raise ValueError("Produto não encontrado.")

    amount = float(product["price"])

    if amount <= 0:
        raise ValueError("Preço inválido.")

    response = requests.post(
        "https://api.mercadopago.com/v1/payments",
        headers={
            "Authorization": f"Bearer {MP_TOKEN}",
            "Content-Type": "application/json",
            "X-Idempotency-Key": str(uuid.uuid4())
        },
        json={
            "transaction_amount": amount,
            "description": str(product["name"]),
            "payment_method_id": "pix",
            "payer": {"email": email},
            "external_reference": f"{user_id}:{guild_id}:{product_id}"
        },
        timeout=30
    )

    response.raise_for_status()
    payment = response.json()

    payment_id = payment["id"]
    transaction = payment["point_of_interaction"]["transaction_data"]

    create_order(
        payment_id,
        user_id,
        guild_id,
        product_id,
        amount
    )

    return {
        "id": payment_id,
        "qr_code": transaction["qr_code"],
        "qr_base64": transaction.get("qr_code_base64")
    }


def get_payment(payment_id):
    if not MP_TOKEN:
        raise RuntimeError("MP_ACCESS_TOKEN não configurado.")

    response = requests.get(
        f"https://api.mercadopago.com/v1/payments/{payment_id}",
        headers={"Authorization": f"Bearer {MP_TOKEN}"},
        timeout=30
    )

    response.raise_for_status()
    return response.json()


# MODAL DE E-MAIL

class EmailModal(discord.ui.Modal):
    def __init__(self, product_id):
        super().__init__(title="Finalizar compra")
        self.product_id = product_id

        self.email = discord.ui.TextInput(
            label="E-mail da conta Mercado Pago",
            placeholder="seuemail@email.com",
            required=True,
            max_length=100
        )

        self.add_item(self.email)

    async def on_submit(self, interaction):
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "Use a loja dentro do servidor.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            payment = await asyncio.to_thread(
                create_pix_payment,
                interaction.user.id,
                interaction.guild_id,
                self.product_id,
                str(self.email.value)
            )

            embed = discord.Embed(
                title="Pagamento Pix criado",
                description=(
                    "Copie o código abaixo e pague pelo aplicativo do seu banco.\n\n"
                    f"```{payment['qr_code']}```\n"
                    f"ID do pagamento: `{payment['id']}`"
                ),
                color=discord.Color.green()
            )

            file = None

            if payment["qr_base64"]:
                image_bytes = base64.b64decode(payment["qr_base64"])
                file = discord.File(
                    io.BytesIO(image_bytes),
                    filename="pix.png"
                )
                embed.set_image(url="attachment://pix.png")

            await interaction.followup.send(
                embed=embed,
                file=file,
                ephemeral=True
            )

        except Exception as error:
            print("Erro ao criar Pix:", repr(error))
            await interaction.followup.send(
                "Não foi possível criar o pagamento.",
                ephemeral=True
            )


# MENU E BOTÃO DE COMPRA

class BuyButton(discord.ui.Button):
    def __init__(self, product_id):
        super().__init__(
            label="Continuar",
            style=discord.ButtonStyle.success,
            custom_id=f"buy:{product_id}"
        )
        self.product_id = product_id

    async def callback(self, interaction):
        await interaction.response.send_modal(
            EmailModal(self.product_id)
        )


class BuyView(discord.ui.View):
    def __init__(self, product_id):
        super().__init__(timeout=180)
        self.add_item(BuyButton(product_id))


class ProductSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=str(product["name"])[:100],
                description=f"R$ {float(product['price']):.2f}",
                value=product_id
            )
            for product_id, product in list(products.items())[:25]
        ]

        super().__init__(
            placeholder="Selecione um produto...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="shop:product_select"
        )

    async def callback(self, interaction):
        product_id = self.values[0]
        product = products.get(product_id)

        if not product:
            await interaction.response.send_message(
                "Produto indisponível.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="Confirmar compra",
            description=(
                f"**Produto:** {product['name']}\n"
                f"**Valor:** R$ {float(product['price']):.2f}\n\n"
                "Clique abaixo para gerar seu Pix."
            ),
            color=discord.Color.blurple()
        )

        await interaction.response.send_message(
            embed=embed,
            view=BuyView(product_id),
            ephemeral=True
        )


class ShopView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ProductSelect())


# LOG DE VENDAS

async def send_sale_log(guild_id, user_id, product_id, payment_id):
    config = get_guild_config(int(guild_id))
    channel_id = config["log_channel_id"]

    if not channel_id:
        return

    channel = bot.get_channel(channel_id)

    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException
        ):
            return

    product = products.get(product_id, {})
    guild = bot.get_guild(int(guild_id))
    member = guild.get_member(int(user_id)) if guild else None

    embed = discord.Embed(
        title="Venda aprovada",
        color=discord.Color.green()
    )

    embed.add_field(
        name="Cliente",
        value=member.mention if member else f"`{user_id}`",
        inline=True
    )

    embed.add_field(
        name="Produto",
        value=product.get("name", product_id),
        inline=True
    )

    embed.add_field(
        name="Pagamento",
        value=f"`{payment_id}`",
        inline=False
    )

    await channel.send(embed=embed)


# WEBHOOK

def verify_signature(request, payment_id):
    secret = os.getenv("MP_WEBHOOK_SECRET")

    if not secret:
        return False

    signature = request.headers.get("x-signature", "")
    request_id = request.headers.get("x-request-id", "")
    parts = {}

    for item in signature.split(","):
        if "=" in item:
            key, value = item.split("=", 1)
            parts[key.strip()] = value.strip()

    timestamp = parts.get("ts")
    received_hash = parts.get("v1")

    if not timestamp or not received_hash:
        return False

    manifest = (
        f"id:{str(payment_id).lower()};"
        f"request-id:{request_id};"
        f"ts:{timestamp};"
    )

    calculated_hash = hmac.new(
        secret.encode("utf-8"),
        manifest.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(calculated_hash, received_hash)


async def deliver_product(order):
    payment_id = order[1]
    user_id = int(order[2])
    guild_id = int(order[3])
    product_id = order[4]

    guild = bot.get_guild(guild_id)

    if guild is None:
        return False

    try:
        member = guild.get_member(user_id) or await guild.fetch_member(user_id)
    except (
        discord.NotFound,
        discord.Forbidden,
        discord.HTTPException
    ):
        return False

    product = products.get(product_id)

    if not product:
        return False

    role = guild.get_role(int(product["role_id"]))

    if role is None:
        return False

    try:
        if role not in member.roles:
            await member.add_roles(
                role,
                reason=f"Compra Pix aprovada: {payment_id}"
            )
    except (
        discord.Forbidden,
        discord.HTTPException
    ) as error:
        print("Erro ao entregar cargo:", repr(error))
        return False

    update_order(payment_id, "approved")

    try:
        await send_sale_log(
            guild_id,
            user_id,
            product_id,
            payment_id
        )
    except Exception as error:
        print("Erro ao enviar log:", repr(error))

    return True


@api.post("/webhook")
async def mercado_pago_webhook(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="JSON inválido"
        )

    payment_id = (
        body.get("data", {}).get("id")
        or request.query_params.get("data.id")
    )

    if not payment_id:
        return JSONResponse(
            {"error": "Pagamento não informado"},
            status_code=400
        )

    if not verify_signature(request, payment_id):
        raise HTTPException(
            status_code=401,
            detail="Assinatura inválida"
        )

    try:
        payment = await asyncio.to_thread(
            get_payment,
            payment_id
        )

        order = get_order(payment_id)

        if not order:
            return {"status": "pedido não encontrado"}

        if order[6] == "approved":
            return {"status": "já processado"}

        expected_reference = f"{order[2]}:{order[3]}:{order[4]}"

        if payment.get("external_reference") != expected_reference:
            raise HTTPException(
                status_code=400,
                detail="Referência inválida"
            )

        if payment.get("status") == "approved":
            paid_amount = float(payment.get("transaction_amount", 0))
            expected_amount = float(order[5])

            if (
                not math.isclose(
                    paid_amount,
                    expected_amount,
                    abs_tol=0.01
                )
                or payment.get("currency_id") != "BRL"
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Valor ou moeda inválidos"
                )

            success = await deliver_product(order)

            if not success:
                return {"status": "entrega pendente"}

        elif payment.get("status") in (
            "rejected",
            "cancelled",
            "refunded"
        ):
            update_order(payment_id, payment["status"])

        return {"status": "ok"}

    except HTTPException:
        raise

    except Exception as error:
        print("Erro no webhook:", repr(error))
        raise HTTPException(
            status_code=500,
            detail="Erro interno"
        )


# COMANDOS DE CONFIGURAÇÃO

def admin_only():
    return app_commands.checks.has_permissions(
        administrator=True
    )


@bot.tree.command(
    name="configurar_loja",
    description="Define o canal onde a loja será publicada."
)
@admin_only()
@app_commands.describe(canal="Canal de texto para publicar a loja")
async def configurar_loja(interaction, canal: discord.TextChannel):
    set_guild_channel(
        interaction.guild_id,
        "shop_channel_id",
        canal.id
    )

    await interaction.response.send_message(
        f"Canal da loja definido para {canal.mention}.",
        ephemeral=True
    )


@bot.tree.command(
    name="configurar_logs",
    description="Define o canal que receberá os registros de vendas."
)
@admin_only()
@app_commands.describe(canal="Canal de texto para os logs")
async def configurar_logs(interaction, canal: discord.TextChannel):
    set_guild_channel(
        interaction.guild_id,
        "log_channel_id",
        canal.id
    )

    await interaction.response.send_message(
        f"Canal de logs definido para {canal.mention}.",
        ephemeral=True
    )


# PUBLICAR LOJA

@bot.tree.command(
    name="publicar_loja",
    description="Publica a loja no canal configurado."
)
@admin_only()
async def publicar_loja(interaction):
    if not products:
        await interaction.response.send_message(
            "Nenhum produto encontrado no products.json.",
            ephemeral=True
        )
        return

    if len(products) > 25:
        await interaction.response.send_message(
            "O Discord permite no máximo 25 produtos neste menu.",
            ephemeral=True
        )
        return

    config = get_guild_config(interaction.guild_id)
    channel_id = config["shop_channel_id"]

    if not channel_id:
        await interaction.response.send_message(
            "Configure primeiro o canal com /configurar_loja.",
            ephemeral=True
        )
        return

    channel = interaction.guild.get_channel(channel_id)

    if channel is None:
        await interaction.response.send_message(
            "Canal não encontrado. Configure novamente.",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    try:
        await channel.send(
            embed=discord.Embed(
                title="LOJA OFICIAL — OZEN BOY",
                description=(
                    "Bem-vindo à nossa loja!\n\n"
                    "Selecione um produto no menu para consultar o valor "
                    "e gerar seu pagamento via Pix.\n\n"
                    "A entrega do cargo ocorre após a confirmação do pagamento."
                ),
                color=discord.Color.blurple()
            ),
            view=ShopView()
        )

        await interaction.followup.send(
            f"Loja publicada em {channel.mention}.",
            ephemeral=True
        )

    except discord.Forbidden:
        await interaction.followup.send(
            "Não tenho permissão para enviar mensagens nesse canal.",
            ephemeral=True
        )


# VENDAS

@bot.tree.command(
    name="vendas",
    description="Consulta as vendas aprovadas deste servidor."
)
@admin_only()
async def vendas(interaction):
    with database() as conn:
        total, amount = conn.execute("""
            SELECT COUNT(*), COALESCE(SUM(amount), 0)
            FROM orders
            WHERE status = 'approved' AND guild_id = ?
        """, (str(interaction.guild_id),)).fetchone()

    embed = discord.Embed(
        title="Relatório de vendas",
        color=discord.Color.green()
    )

    embed.add_field(
        name="Vendas aprovadas",
        value=str(total)
    )

    embed.add_field(
        name="Total arrecadado",
        value=f"R$ {amount:.2f}"
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# INICIALIZAÇÃO

@bot.event
async def on_ready():
    global persistent_view_registered

    print(f"Bot conectado como {bot.user}")

    if products and not persistent_view_registered:
        bot.add_view(ShopView())
        persistent_view_registered = True

    try:
        for guild in bot.guilds:
            guild_object = discord.Object(id=guild.id)
            bot.tree.copy_global_to(guild=guild_object)
            await bot.tree.sync(guild=guild_object)

        print("Comandos sincronizados!")

    except Exception as error:
        print("Erro ao sincronizar comandos:", repr(error))


# SERVIDOR WEB

def run_api():
    uvicorn.run(
        api,
        host="0.0.0.0",
        port=PORT
    )

# ==========================================
# PAINEL DE CONFIGURAÇÃO DA LOJA
# ==========================================

def save_products():
    with open(PRODUCTS_FILE, "w", encoding="utf-8") as file:
        json.dump(products, file, ensure_ascii=False, indent=4)


class ProductModal(discord.ui.Modal):
    def __init__(self, product_id=None):
        super().__init__(title="Cadastrar / Editar Produto")

        self.old_id = product_id
        product = products.get(product_id, {}) if product_id else {}

        self.product_id = discord.ui.TextInput(
            label="ID do produto",
            placeholder="Ex: vip",
            default=product_id or "",
            max_length=50
        )

        self.name = discord.ui.TextInput(
            label="Nome do produto",
            placeholder="Ex: VIP",
            default=product.get("name", ""),
            max_length=100
        )

        self.price = discord.ui.TextInput(
            label="Preço (R$)",
            placeholder="Ex: 10.00",
            default=str(product.get("price", "")),
            max_length=15
        )

        self.role_id = discord.ui.TextInput(
            label="ID do cargo entregue",
            placeholder="ID do cargo no Discord",
            default=str(product.get("role_id", "")),
            max_length=25
        )

        self.description = discord.ui.TextInput(
            label="Descrição",
            placeholder="Descrição do produto",
            default=product.get("description", ""),
            required=False,
            max_length=300
        )

        for item in (
            self.product_id,
            self.name,
            self.price,
            self.role_id,
            self.description
        ):
            self.add_item(item)

    async def on_submit(self, interaction):
        pid = str(self.product_id.value).strip()
        name = str(self.name.value).strip()

        try:
            price = float(str(self.price.value).replace(",", "."))
            role_id = int(self.role_id.value.strip())

            if not math.isfinite(price) or price <= 0:
                raise ValueError

        except ValueError:
            await interaction.response.send_message(
                "Preço ou ID do cargo inválido.",
                ephemeral=True
            )
            return

        if pid != self.old_id and pid in products:
            await interaction.response.send_message(
                "Já existe um produto com esse ID.",
                ephemeral=True
            )
            return

        if self.old_id is None and len(products) >= 25:
            await interaction.response.send_message(
                "Limite de 25 produtos atingido.",
                ephemeral=True
            )
            return

        if self.old_id and self.old_id != pid:
            products.pop(self.old_id, None)

        products[pid] = {
            "name": name,
            "price": price,
            "role_id": role_id,
            "description": str(self.description.value).strip()
        }

        save_products()

        await interaction.response.send_message(
            f"Produto **{name}** salvo com sucesso!",
            ephemeral=True
        )


class ProductActionsView(discord.ui.View):
    def __init__(self, product_id):
        super().__init__(timeout=180)
        self.product_id = product_id

    @discord.ui.button(
        label="Editar",
        style=discord.ButtonStyle.primary,
        emoji="✏️"
    )
    async def edit(self, interaction, button):
        if self.product_id not in products:
            await interaction.response.send_message(
                "Produto não encontrado.",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(
            ProductModal(self.product_id)
        )

    @discord.ui.button(
        label="Excluir",
        style=discord.ButtonStyle.danger,
        emoji="🗑️"
    )
    async def delete(self, interaction, button):
        if self.product_id not in products:
            await interaction.response.send_message(
                "Produto não encontrado.",
                ephemeral=True
            )
            return

        name = products[self.product_id]["name"]

        del products[self.product_id]
        save_products()

        await interaction.response.edit_message(
            content=f"Produto **{name}** excluído.",
            embed=None,
            view=None
        )


class ProductManageSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=str(product["name"])[:100],
                description=f"R$ {float(product['price']):.2f}",
                value=pid
            )
            for pid, product in products.items()
        ]

        super().__init__(
            placeholder="Gerenciar um produto...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction):
        pid = self.values[0]
        product = products.get(pid)

        if not product:
            await interaction.response.send_message(
                "Produto não encontrado.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="Gerenciar produto",
            description=(
                f"**Nome:** {product['name']}\n"
                f"**ID:** `{pid}`\n"
                f"**Preço:** R$ {float(product['price']):.2f}\n"
                f"**Cargo:** `{product['role_id']}`\n"
                f"**Descrição:** {product.get('description') or 'Nenhuma'}"
            ),
            color=discord.Color.blurple()
        )

        await interaction.response.send_message(
            embed=embed,
            view=ProductActionsView(pid),
            ephemeral=True
        )


class ShopChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="Definir canal da loja",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction):
        channel = self.values[0]

        set_guild_channel(
            interaction.guild_id,
            "shop_channel_id",
            channel.id
        )

        await interaction.response.send_message(
            f"Canal da loja definido: {channel.mention}",
            ephemeral=True
        )


class LogChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="Definir canal de vendas",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction):
        channel = self.values[0]

        set_guild_channel(
            interaction.guild_id,
            "log_channel_id",
            channel.id
        )

        await interaction.response.send_message(
            f"Canal de vendas definido: {channel.mention}",
            ephemeral=True
        )


class SetupPublishButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Publicar loja",
            emoji="🛒",
            style=discord.ButtonStyle.success
        )

    async def callback(self, interaction):
        if not products:
            await interaction.response.send_message(
                "Cadastre pelo menos um produto primeiro.",
                ephemeral=True
            )
            return

        config = get_guild_config(interaction.guild_id)
        channel_id = config["shop_channel_id"]

        if not channel_id:
            await interaction.response.send_message(
                "Configure o canal da loja primeiro.",
                ephemeral=True
            )
            return

        channel = interaction.guild.get_channel(channel_id)

        if channel is None:
            await interaction.response.send_message(
                "Canal não encontrado. Configure novamente.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            await channel.send(
                embed=discord.Embed(
                    title="LOJA OFICIAL — OZEN BOY",
                    description=(
                        "Bem-vindo à nossa loja!\n\n"
                        "Selecione um produto para consultar o preço "
                        "e gerar seu pagamento via Pix.\n\n"
                        "A entrega acontece após a confirmação do pagamento."
                    ),
                    color=discord.Color.blurple()
                ),
                view=ShopView()
            )

            await interaction.followup.send(
                f"Loja publicada em {channel.mention}!",
                ephemeral=True
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "Não tenho permissão para publicar nesse canal.",
                ephemeral=True
            )


class SetupLojaView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)

        self.add_item(
            discord.ui.Button(
                label="Cadastrar produto",
                emoji="➕",
                style=discord.ButtonStyle.primary,
                custom_id="setup:add",
            )
        )

        self.children[0].callback = self.add_product

        if products:
            self.add_item(ProductManageSelect())

        self.add_item(ShopChannelSelect())
        self.add_item(LogChannelSelect())
        self.add_item(SetupPublishButton())

    async def add_product(self, interaction):
        await interaction.response.send_modal(ProductModal())


@bot.tree.command(
    name="setup_loja",
    description="Abre o painel de gerenciamento da loja."
)
@admin_only()
async def setup_loja(interaction):
    config = get_guild_config(interaction.guild_id)

    shop = (
        f"<#{config['shop_channel_id']}>"
        if config["shop_channel_id"] else "Não configurado"
    )

    logs = (
        f"<#{config['log_channel_id']}>"
        if config["log_channel_id"] else "Não configurado"
    )

    embed = discord.Embed(
        title="PAINEL DE CONFIGURAÇÃO — LOJA",
        description=(
            "Gerencie sua loja diretamente pelo Discord.\n\n"
            f"**Produtos cadastrados:** {len(products)}/25\n"
            f"**Canal da loja:** {shop}\n"
            f"**Canal de vendas:** {logs}\n\n"
            "Utilize os controles abaixo para configurar sua loja."
        ),
        color=discord.Color.blurple()
    )

    await interaction.response.send_message(
        embed=embed,
        view=SetupLojaView(),
        ephemeral=True
    )


# ==========================================
# FIM DO PAINEL
# ==========================================
# ==========================================
# PIX MANUAL - NUBANK
# ==========================================

# Adicionar configurações ao banco existente
with database() as conn:
    for column in ("pix_key", "pix_name"):
        try:
            conn.execute(
                f"ALTER TABLE guild_config ADD COLUMN {column} TEXT"
            )
        except sqlite3.OperationalError:
            pass


def save_pix_config(guild_id, key, name):
    with database() as conn:
        conn.execute("""
            INSERT INTO guild_config (guild_id, pix_key, pix_name)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
            pix_key = excluded.pix_key,
            pix_name = excluded.pix_name
        """, (str(guild_id), key, name))


def get_pix_config(guild_id):
    with database() as conn:
        row = conn.execute("""
            SELECT pix_key, pix_name
            FROM guild_config
            WHERE guild_id = ?
        """, (str(guild_id),)).fetchone()

    return row if row else (None, None)


class PixManualButton(discord.ui.Button):
    def __init__(self, product_id):
        super().__init__(
            label="Pagar com Pix Nubank",
            emoji="💜",
            style=discord.ButtonStyle.primary,
            custom_id=f"manual_pix:{product_id}"
        )
        self.product_id = product_id

    async def callback(self, interaction):
        product = products.get(self.product_id)

        if not product:
            await interaction.response.send_message(
                "Produto não encontrado.",
                ephemeral=True
            )
            return

        key, name = get_pix_config(interaction.guild_id)

        if not key:
            await interaction.response.send_message(
                "O Pix manual ainda não foi configurado.",
                ephemeral=True
            )
            return

        payment_id = "manual-" + str(uuid.uuid4())

        create_order(
            payment_id,
            interaction.user.id,
            interaction.guild_id,
            self.product_id,
            product["price"]
        )

        embed = discord.Embed(
            title="Pagamento via Pix",
            description=(
                f"**Produto:** {product['name']}\n"
                f"**Valor:** R$ {float(product['price']):.2f}\n\n"
                f"**Chave Pix:**\n```{key}```\n"
                f"**Titular:** {name}\n\n"
                f"**Pedido:** `{payment_id}`\n\n"
                "Copie a chave e faça o pagamento pelo aplicativo "
                "do seu banco. Depois, aguarde a confirmação."
            ),
            color=discord.Color.blurple()
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )


# Adiciona o botão Nubank sem remover o botão existente
def new_buy_view_init(self, product_id):
    discord.ui.View.__init__(self, timeout=180)
    self.add_item(BuyButton(product_id))
    self.add_item(PixManualButton(product_id))


BuyView.__init__ = new_buy_view_init


# CONFIGURAR CHAVE PIX
@bot.tree.command(
    name="configurar_pix",
    description="Configura a chave Pix manual da loja."
)
@admin_only()
@app_commands.describe(
    chave="Sua chave Pix",
    titular="Nome do titular da conta"
)
async def configurar_pix(interaction, chave: str, titular: str):
    save_pix_config(
        interaction.guild_id,
        chave.strip(),
        titular.strip()
    )

    await interaction.response.send_message(
        "Chave Pix configurada com sucesso!",
        ephemeral=True
    )


# APROVAR PAGAMENTO MANUAL
@bot.tree.command(
    name="aprovar_pix",
    description="Aprova manualmente um pedido Pix após conferir o recebimento."
)
@admin_only()
@app_commands.describe(
    pedido="Código do pedido mostrado ao comprador"
)
async def aprovar_pix(interaction, pedido: str):

    order = get_order(pedido.strip())

    if not order or not order[1].startswith("manual-"):
        await interaction.response.send_message(
            "Pedido Pix manual não encontrado.",
            ephemeral=True
        )
        return

    if str(order[3]) != str(interaction.guild_id):
        await interaction.response.send_message(
            "Esse pedido pertence a outro servidor.",
            ephemeral=True
        )
        return

    if order[6] == "approved":
        await interaction.response.send_message(
            "Esse pedido já foi aprovado.",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    success = await deliver_product(order)

    if success:
        await interaction.followup.send(
            "Pagamento aprovado e cargo entregue!",
            ephemeral=True
        )
    else:
        await interaction.followup.send(
            "Não foi possível entregar o cargo. Confira as permissões e o cargo configurado.",
            ephemeral=True
        )


# ==========================================
# FIM DO PIX MANUAL
# ==========================================

# ==========================================
# PIX NUBANK COM TICKET AUTOMÁTICO
# ==========================================

PIX_CATEGORY_NAME = "🛒・PEDIDOS"


def pix_setup_database():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pix_config (
                guild_id INTEGER PRIMARY KEY,
                pix_key TEXT NOT NULL,
                pix_name TEXT NOT NULL
            )
        """)


pix_setup_database()


def pix_save_config(guild_id, key, name):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO pix_config
            (guild_id, pix_key, pix_name)
            VALUES (?, ?, ?)
        """, (guild_id, key, name))


def pix_get_config(guild_id):
    with sqlite3.connect(DB_FILE) as conn:
        return conn.execute("""
            SELECT pix_key, pix_name
            FROM pix_config WHERE guild_id = ?
        """, (guild_id,)).fetchone()


async def pix_get_category(guild):
    category = discord.utils.get(
        guild.categories,
        name=PIX_CATEGORY_NAME
    )

    if category:
        return category

    return await guild.create_category(PIX_CATEGORY_NAME)


class PixTicketControls(discord.ui.View):

    def __init__(self, order_id):
        super().__init__(timeout=86400)
        self.order_id = order_id

    @discord.ui.button(
        label="Aprovar pagamento",
        style=discord.ButtonStyle.success,
        emoji="✅"
    )
    async def approve(self, interaction, button):

        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "Você não tem permissão para aprovar pagamentos.",
                ephemeral=True
            )

        order = get_order(self.order_id)

        if not order:
            return await interaction.response.send_message(
                "Pedido não encontrado.",
                ephemeral=True
            )

        if not order[1].startswith("manual-"):
            return await interaction.response.send_message(
                "Este não é um pedido Pix manual.",
                ephemeral=True
            )

        if order[6] == "approved":
            return await interaction.response.send_message(
                "Este pedido já foi aprovado.",
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        try:
            await deliver_product(order)

            await interaction.followup.send(
                "Pagamento aprovado e produto entregue.",
                ephemeral=True
            )

            await interaction.channel.send(
                "✅ **Pagamento aprovado.** Este pedido foi finalizado."
            )

        except Exception as e:
            await interaction.followup.send(
                f"Erro ao entregar o produto: {e}",
                ephemeral=True
            )

    @discord.ui.button(
        label="Fechar ticket",
        style=discord.ButtonStyle.danger,
        emoji="🔒"
    )
    async def close(self, interaction, button):

        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "Você não tem permissão para fechar este ticket.",
                ephemeral=True
            )

        await interaction.response.send_message(
            "Ticket será fechado em alguns segundos."
        )

        await asyncio.sleep(3)
        await interaction.channel.delete()


class PixTicketButton(discord.ui.Button):

    def __init__(self, product_id):
        super().__init__(
            label="Pix Nubank",
            emoji="💠",
            style=discord.ButtonStyle.primary
        )
        self.product_id = product_id

    async def callback(self, interaction):

        guild = interaction.guild
        user = interaction.user

        config = pix_get_config(guild.id)

        if not config:
            return await interaction.response.send_message(
                "O Pix ainda não foi configurado neste servidor.",
                ephemeral=True
            )

        product = products.get(self.product_id)

        if not product:
            return await interaction.response.send_message(
                "Produto não encontrado.",
                ephemeral=True
            )

        existing = discord.utils.get(
            guild.text_channels,
            topic=f"pix-user-{user.id}"
        )

        if existing:
            return await interaction.response.send_message(
                f"Você já possui um ticket aberto: {existing.mention}",
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        category = await pix_get_category(guild)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False
            ),
            user: discord.PermissionOverwrite(
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

        channel = await guild.create_text_channel(
            name=f"pedido-{user.name}".lower()[:90],
            category=category,
            overwrites=overwrites,
            topic=f"pix-user-{user.id}"
        )

        payment_id = "manual-" + str(uuid.uuid4())

        create_order(
            payment_id,
            user.id,
            guild.id,
            self.product_id,
            product["price"]
        )

        embed = discord.Embed(
            title="💠 Pagamento via Pix Nubank",
            description=(
                f"Olá, {user.mention}!\n\n"
                f"**Produto:** {product['name']}\n"
                f"**Valor:** R$ {float(product['price']):.2f}\n\n"
                f"**Chave Pix:**\n`{config[0]}`\n\n"
                f"**Titular:** {config[1]}\n\n"
                f"**Código do pedido:**\n`{payment_id}`\n\n"
                "Após realizar o pagamento, envie o comprovante "
                "neste canal. A staff irá conferir o recebimento."
            ),
            color=discord.Color.blue()
        )

        await channel.send(
            content=f"{user.mention}",
            embed=embed,
            view=PixTicketControls(payment_id)
        )

        await interaction.followup.send(
            f"Seu ticket foi criado: {channel.mention}",
            ephemeral=True
        )

@app_commands.describe(
    chave="Sua chave Pix",
    titular="Nome do titular da conta"
)
@app_commands.checks.has_permissions(administrator=True)
async def configurar_pix(
    interaction: discord.Interaction,
    chave: str,
    titular: str
):

    pix_save_config(
        interaction.guild.id,
        chave.strip(),
        titular.strip()
    )

    await interaction.response.send_message(
        "✅ Pix Nubank configurado.",
        ephemeral=True
    )



# EXECUTAR

if not DISCORD_TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN não configurado no Railway."
    )
Thread(
    target=run_api,
    daemon=True
).start()

bot.run(DISCORD_TOKEN)
