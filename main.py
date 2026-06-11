import discord
from discord.ext import commands
import json
import os

TOKEN = os.getenv("TOKEN")
LOG_CHANNEL_ID = 1514512718923567254

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ----------------------------
# SISTEMA DE WARNS (JSON)
# ----------------------------
WARN_FILE = "warns.json"

try:
    with open(WARN_FILE, "r") as f:
        warns = json.load(f)
except:
    warns = {}

def save_warns():
    with open(WARN_FILE, "w") as f:
        json.dump(warns, f, indent=4)

def add_warn(user_id, reason):
    uid = str(user_id)
    warns.setdefault(uid, []).append(reason)
    save_warns()

# ----------------------------
# LOG SYSTEM
# ----------------------------
async def log(title, text, color=discord.Color.red()):
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if channel:
        embed = discord.Embed(title=title, description=text, color=color)
        await channel.send(embed=embed)

# ----------------------------
# EVENT
# ----------------------------
@bot.event
async def on_ready():
    print(f"Logado como {bot.user}")

# ----------------------------
# COMANDOS BASE
# ----------------------------
@bot.command()
async def ping(ctx):
    await ctx.send("Pong!")

# ----------------------------
# BAN
# ----------------------------
@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="sem motivo"):
    await member.ban(reason=reason)

    await log("BAN", f"{member} | Staff: {ctx.author} | {reason}")
    await ctx.send("Usuário banido.")

# ----------------------------
# KICK
# ----------------------------
@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="sem motivo"):
    await member.kick(reason=reason)

    await log("KICK", f"{member} | Staff: {ctx.author} | {reason}")
    await ctx.send("Usuário expulso.")

# ----------------------------
# MUTE (TIMEOUT)
# ----------------------------
@bot.command()
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, minutes: int, *, reason="sem motivo"):
    await member.timeout(discord.utils.utcnow() + discord.timedelta(minutes=minutes), reason=reason)

    await log("MUTE", f"{member} | {minutes} min | {reason}")
    await ctx.send("Usuário mutado.")

# ----------------------------
# WARN
# ----------------------------
@bot.command()
async def warn(ctx, member: discord.Member, *, reason="sem motivo"):
    add_warn(member.id, reason)

    await member.send(f"⚠️ Você recebeu warn: {reason}")

    await log("WARN", f"{member} | Staff: {ctx.author} | {reason}")
    await ctx.send("Warn aplicado.")

# ----------------------------
# VER WARNS
# ----------------------------
@bot.command()
async def warns(ctx, member: discord.Member):
    data = warns.get(str(member.id), [])

    if not data:
        return await ctx.send("Sem warns.")

    await ctx.send("\n".join([f"{i+1}. {r}" for i, r in enumerate(data)]))

# ----------------------------
# PAINEL DE STAFF (BOTÕES)
# ----------------------------
class StaffPanel(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="BAN", style=discord.ButtonStyle.red)
    async def ban_btn(self, interaction, button):
        await interaction.response.send_message("Use: !ban @user motivo", ephemeral=True)

    @discord.ui.button(label="KICK", style=discord.ButtonStyle.orange)
    async def kick_btn(self, interaction, button):
        await interaction.response.send_message("Use: !kick @user motivo", ephemeral=True)

    @discord.ui.button(label="MUTE", style=discord.ButtonStyle.blurple)
    async def mute_btn(self, interaction, button):
        await interaction.response.send_message("Use: !mute @user tempo motivo", ephemeral=True)

    @discord.ui.button(label="WARN", style=discord.ButtonStyle.grey)
    async def warn_btn(self, interaction, button):
        await interaction.response.send_message("Use: !warn @user motivo", ephemeral=True)

# ----------------------------
# COMANDO PAINEL
# ----------------------------
@bot.command()
@commands.has_permissions(administrator=True)
async def panel(ctx):
    await ctx.send("📊 PAINEL DE STAFF", view=StaffPanel())

# ----------------------------
bot.run(TOKEN)
