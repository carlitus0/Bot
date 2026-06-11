import discord
from discord.ext import commands
import os

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------- READY ----------------
@bot.event
async def on_ready():
    print(f"Logado como {bot.user}")

# ---------------- PING ----------------
@bot.command()
async def ping(ctx):
    await ctx.send("Pong!")

# ---------------- KICK ----------------
@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason=None):
    await member.kick(reason=reason)
    await ctx.send(f"{member} foi kickado.")

# ---------------- BAN ----------------
@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason=None):
    await member.ban(reason=reason)
    await ctx.send(f"{member} foi banido.")

# ---------------- MUTE (timeout) ----------------
@bot.command()
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, minutes: int, *, reason=None):
    duration = discord.utils.utcnow() + discord.timedelta(minutes=minutes)
    await member.edit(timed_out_until=duration, reason=reason)
    await ctx.send(f"{member} mutado por {minutes} minutos.")

# ---------------- WARN (DM) ----------------
warns = {}

@bot.command()
@commands.has_permissions(kick_members=True)
async def warn(ctx, member: discord.Member, *, reason=None):
    user_id = member.id

    warns[user_id] = warns.get(user_id, 0) + 1

    try:
        await member.send(f"Você recebeu um warn no servidor {ctx.guild.name}. Motivo: {reason}")
    except:
        pass

    await ctx.send(f"{member} recebeu warn. Total: {warns[user_id]}")

# ---------------- PAINEL DE STAFF ----------------

class BanModal(discord.ui.Modal, title="Banir usuário"):
    user_id = discord.ui.TextInput(label="ID do usuário", placeholder="123456789")

    async def on_submit(self, interaction: discord.Interaction):
        try:
            user = await bot.fetch_user(int(self.user_id.value))
            await interaction.guild.ban(user, reason="Ban via painel")
            await interaction.response.send_message(f"{user} foi banido pelo painel.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Erro: {e}", ephemeral=True)

class StaffPanel(discord.ui.View):
    @discord.ui.button(label="Banir usuário", style=discord.ButtonStyle.red)
    async def ban_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BanModal())

@bot.command()
@commands.has_permissions(administrator=True)
async def painel(ctx):
    await ctx.send("Painel de Staff:", view=StaffPanel())

# ---------------- RUN ----------------
bot.run(os.getenv("TOKEN"))
