import discord
from discord.ext import commands
import asyncio
import os

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# -------------------------
# TROLL SYSTEM
# -------------------------
troll_users = set()

@bot.command()
async def troll(ctx, user_id: int):
    if user_id in troll_users:
        troll_users.remove(user_id)
        await ctx.send("🔴 Troll desativado")
    else:
        troll_users.add(user_id)
        await ctx.send("🟢 Troll ativado")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.author.id in troll_users:
        await message.channel.send("bah")

    await bot.process_commands(message)

# -------------------------
# MUTE
# -------------------------
@bot.command()
@commands.has_permissions(manage_roles=True)
async def mute(ctx, user_id: int, tempo: int):
    member = ctx.guild.get_member(user_id)

    if not member:
        await ctx.send("❌ Usuário não encontrado no servidor")
        return

    role = discord.utils.get(ctx.guild.roles, name="Muted")

    if not role:
        await ctx.send("❌ Crie a role 'Muted' primeiro")
        return

    await member.add_roles(role)
    await ctx.send(f"🔇 Mutado por {tempo}s")

    await asyncio.sleep(tempo)

    await member.remove_roles(role)
    await ctx.send("🔊 Mute acabou")

# -------------------------
# BAN
# -------------------------
@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, user_id: int, *, reason=None):
    user = await bot.fetch_user(user_id)
    await ctx.guild.ban(user, reason=reason)
    await ctx.send(f"🔨 Banido: {user_id}")

# -------------------------
# START
# -------------------------
@bot.event
async def on_ready():
    print(f"Logado como {bot.user}")

bot.run(os.getenv("TOKEN"))
