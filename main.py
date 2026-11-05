import os
import json
import sqlite3
import asyncio
import requests
import discord

from discord.ext import commands
from discord import app_commands
from fastapi import FastAPI, Request, HTTPException
from threading import Thread
import uvicorn

# ==============================
# CONFIGURAÇÕES
# ==============================

TOKEN = os.getenv("DISCORD_TOKEN")
MP_TOKEN = os.getenv("MP_ACCESS_TOKEN")

GUILD_ID = int(os.getenv("GUILD_ID", "0"))
SHOP_CHANNEL_ID = int(os.getenv("SHOP_CHANNEL_ID", "0"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))

PORT = int(os.getenv("PORT", "8080"))

DB_FILE = "bot.db"
PRODUCTS_FILE = "products.json"

# ==============================
# PRODUTOS
# ==============================

def load_products():
    try:
        with open(PRODUCTS_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}

products = load_products()

# ==============================
# BANCO DE DADOS
# ==============================

def database():
    return sqlite3.connect(DB_FILE)

def setup_database():
    conn = database()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payment_id TEXT UNIQUE,
            user_id TEXT,
            guild_id TEXT,
            product_id TEXT,
            amount REAL,
            status TEXT DEFAULT 'pending'
        )
    """)

    conn.commit()
    conn.close()

setup_database()

# ==============================
# REGISTRAR PEDIDO
# ==============================

def create_order(payment_id, user_id, guild_id, product_id, amount):
    conn = database()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO orders
        (payment_id, user_id, guild_id, product_id, amount)
        VALUES (?, ?, ?, ?, ?)
    """, (
        str(payment_id),
        str(user_id),
        str(guild_id),
        str(product_id),
        float(amount)
    ))

    conn.commit()
    conn.close()

# ==============================
# BUSCAR PEDIDO
# ==============================

def get_order(payment_id):
    conn = database()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM orders WHERE payment_id = ?",
        (str(payment_id),)
    )

    result = cursor.fetchone()
    conn.close()

    return result

# ==============================
# ATUALIZAR PEDIDO
# ==============================

def update_order(payment_id, status):
    conn = database()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE orders
        SET status = ?
        WHERE payment_id = ?
    """, (status, str(payment_id)))

    conn.commit()
    conn.close()

# ==============================
# BOT DISCORD
# ==============================

intents = discord.Intents.default()
intents.guilds = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

api = FastAPI()
# ==============================
# CRIAR PAGAMENTO PIX
# ==============================

def create_pix_payment(user_id, guild_id, product_id, email):
    product = products.get(product_id)

    if not product:
        raise ValueError("Produto não encontrado.")

    amount = float(product["price"])

    url = "https://api.mercadopago.com/v1/payments"

    headers = {
        "Authorization": f"Bearer {MP_TOKEN}",
        "Content-Type": "application/json",
        "X-Idempotency-Key": f"{user_id}-{product_id}-{asyncio.get_event_loop().time()}"
    }

    data = {
        "transaction_amount": amount,
        "description": product["name"],
        "payment_method_id": "pix",
        "payer": {
            "email": email
        },
        "external_reference": f"{user_id}:{guild_id}:{product_id}"
    }

    response = requests.post(
        url,
        headers=headers,
        json=data,
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


# ==============================
# MODAL DE E-MAIL
# ==============================

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

    async def on_submit(self, interaction: discord.Interaction):
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
                    "**Copie o código abaixo e pague pelo aplicativo do seu banco.**\n\n"
                    f"```{payment['qr_code']}```\n"
                    f"ID do pagamento: `{payment['id']}`"
                ),
                color=discord.Color.green()
            )

            if payment["qr_base64"]:
                import base64
                image_bytes = base64.b64decode(payment["qr_base64"])
                file = discord.File(
                    fp=__import__("io").BytesIO(image_bytes),
                    filename="pix.png"
                )
                embed.set_image(url="attachment://pix.png")
                await interaction.followup.send(
                    embed=embed,
                    file=file,
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    embed=embed,
                    ephemeral=True
                )

        except Exception as error:
            print("Erro ao criar Pix:", error)
            await interaction.followup.send(
                "Não foi possível criar o pagamento. Tente novamente mais tarde.",
                ephemeral=True
            )


# ==============================
# MENU DE PRODUTOS
# ==============================

class ProductSelect(discord.ui.Select):
    def __init__(self):
        options = []

        for product_id, product in products.items():
            options.append(
                discord.SelectOption(
                    label=product["name"][:100],
                    description=f"R$ {float(product['price']):.2f}",
                    value=product_id
                )
            )

        super().__init__(
            placeholder="Selecione um produto...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        product_id = self.values[0]
        product = products[product_id]

        embed = discord.Embed(
            title="Confirmar compra",
            description=(
                f"**Produto:** {product['name']}\n"
                f"**Valor:** R$ {float(product['price']):.2f}\n\n"
                "Clique no botão abaixo para gerar seu Pix."
            ),
            color=discord.Color.blurple()
        )

        view = discord.ui.View()
        view.add_item(
            discord.ui.Button(
                label="Continuar",
                style=discord.ButtonStyle.success,
                custom_id=f"buy_{product_id}"
            )
        )

        button = view.children[0]

        async def buy_callback(button_interaction):
            await button_interaction.response.send_modal(
                EmailModal(product_id)
            )

        button.callback = buy_callback

        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True
        )


class ShopView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ProductSelect())


# ==============================
# LOG DE VENDAS
# ==============================

async def send_sale_log(guild_id, user_id, product_id, payment_id):
    channel = bot.get_channel(LOG_CHANNEL_ID)

    if not channel:
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
import hmac
import hashlib
from fastapi.responses import JSONResponse


# ==============================
# VERIFICAR ASSINATURA DO WEBHOOK
# ==============================

def verify_signature(request: Request, payment_id):
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
        f"id:{payment_id};"
        f"request-id:{request_id};"
        f"ts:{timestamp};"
    )

    calculated_hash = hmac.new(
        secret.encode(),
        manifest.encode(),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(calculated_hash, received_hash)


# ==============================
# CONSULTAR PAGAMENTO NO MERCADO PAGO
# ==============================

def get_payment(payment_id):
    response = requests.get(
        f"https://api.mercadopago.com/v1/payments/{payment_id}",
        headers={
            "Authorization": f"Bearer {MP_TOKEN}"
        },
        timeout=30
    )

    response.raise_for_status()
    return response.json()


# ==============================
# ENTREGAR PRODUTO
# ==============================

async def deliver_product(order):
    payment_id = order[1]
    user_id = int(order[2])
    guild_id = int(order[3])
    product_id = order[4]

    guild = bot.get_guild(guild_id)

    if not guild:
        return False

    member = guild.get_member(user_id)

    if not member:
        try:
            member = await guild.fetch_member(user_id)
        except discord.NotFound:
            return False

    product = products.get(product_id)

    if not product:
        return False

    role_id = int(product["role_id"])
    role = guild.get_role(role_id)

    if not role:
        return False

    if role not in member.roles:
        await member.add_roles(
            role,
            reason=f"Compra Pix aprovada: {payment_id}"
        )

    update_order(payment_id, "approved")

    await send_sale_log(
        guild_id,
        user_id,
        product_id,
        payment_id
    )

    return True


# ==============================
# WEBHOOK MERCADO PAGO
# ==============================

@api.post("/webhook")
async def mercado_pago_webhook(request: Request):
    body = await request.json()

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

        product = products.get(order[4])

        if not product:
            return {"status": "produto não encontrado"}

        expected_reference = (
            f"{order[2]}:{order[3]}:{order[4]}"
        )

        if payment.get("external_reference") != expected_reference:
            raise HTTPException(
                status_code=400,
                detail="Referência inválida"
            )

        if payment.get("status") == "approved":
            if (
                float(payment.get("transaction_amount", 0))
                != float(order[5])
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
        print("Erro no webhook:", error)

        raise HTTPException(
            status_code=500,
            detail="Erro interno"
        )


# ==============================
# COMANDO PUBLICAR LOJA
# ==============================

@bot.tree.command(
    name="publicar_loja",
    description="Publica o catálogo da loja."
)
@app_commands.checks.has_permissions(administrator=True)
async def publicar_loja(interaction: discord.Interaction):

    embed = discord.Embed(
        title="🛒 LOJA OFICIAL — OZEN BOY",
        description=(
            "Bem-vindo à nossa loja!\n\n"
            "Selecione um produto no menu abaixo para consultar "
            "o valor e realizar sua compra via Pix.\n\n"
            "A entrega é feita automaticamente após a confirmação "
            "do pagamento."
        ),
        color=discord.Color.blurple()
    )

    await interaction.channel.send(
        embed=embed,
        view=ShopView()
    )

    await interaction.response.send_message(
        "Loja publicada!",
        ephemeral=True
    )


# ==============================
# COMANDO VENDAS
# ==============================

@bot.tree.command(
    name="vendas",
    description="Consulta o total de vendas aprovadas."
)
@app_commands.checks.has_permissions(administrator=True)
async def vendas(interaction: discord.Interaction):

    conn = database()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*), COALESCE(SUM(amount), 0)
        FROM orders
        WHERE status = 'approved'
    """)

    total, amount = cursor.fetchone()
    conn.close()

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


# ==============================
# INICIALIZAÇÃO DO BOT
# ==============================

@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")

    try:
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
        else:
            await bot.tree.sync()

        print("Comandos sincronizados!")

    except Exception as error:
        print("Erro ao sincronizar comandos:", error)


# ==============================
# SERVIDOR WEB
# ==============================

def run_api():
    uvicorn.run(
        api,
        host="0.0.0.0",
        port=PORT
    )


# ==============================
# EXECUTAR
# ==============================

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN não configurado.")

if not MP_TOKEN:
    raise RuntimeError("MP_ACCESS_TOKEN não configurado.")

Thread(
    target=run_api,
    daemon=True
).start()

bot.run(TOKEN)
