import sqlite3
from datetime import datetime, timedelta

import discord
from discord.ext import commands


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_db(self):
        return sqlite3.connect("database/bot.db")

    async def send_dm(self, user, embed):
        try:
            await user.send(embed=embed)
        except:
            pass

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def warn(self, ctx, member: discord.Member, *, reason="Sem motivo"):

        conn = self.get_db()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO warns (
                guild_id, user_id, moderator_id, reason, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                ctx.guild.id,
                member.id,
                ctx.author.id,
                reason,
                datetime.utcnow().isoformat()
            )
        )

        conn.commit()
        conn.close()

        embed = discord.Embed(
            title="⚠️ Aviso Recebido",
            description=f"Você recebeu um aviso em **{ctx.guild.name}**.",
            color=discord.Color.orange()
        )

        embed.add_field(name="Motivo", value=reason, inline=False)
        embed.add_field(name="Moderador", value=ctx.author, inline=False)

        await self.send_dm(member, embed)

        await ctx.send(f"✅ {member.mention} recebeu um aviso.")

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def warns(self, ctx, member: discord.Member):

        conn = self.get_db()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT reason, created_at
            FROM warns
            WHERE guild_id = ? AND user_id = ?
            """,
            (ctx.guild.id, member.id)
        )

        warns = cursor.fetchall()
        conn.close()

        if not warns:
            return await ctx.send("Este usuário não possui avisos.")

        embed = discord.Embed(
            title=f"📋 Avisos de {member}",
            color=discord.Color.yellow()
        )

        for index, warn in enumerate(warns, start=1):
            embed.add_field(
                name=f"Aviso #{index}",
                value=warn[0],
                inline=False
            )

        await ctx.send(embed=embed)

    @commands.command()
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, member: discord.Member, *, reason="Sem motivo"):

        embed = discord.Embed(
            title="🔨 Você foi banido",
            description=f"Servidor: **{ctx.guild.name}**",
            color=discord.Color.red()
        )

        embed.add_field(name="Motivo", value=reason, inline=False)

        await self.send_dm(member, embed)

        await member.ban(reason=reason)

        await ctx.send(f"✅ {member} foi banido.")

    @commands.command()
    @commands.has_permissions(ban_members=True)
    async def hackban(self, ctx, user_id: int, *, reason="Sem motivo"):

        user = discord.Object(id=user_id)

        await ctx.guild.ban(user, reason=reason)

        await ctx.send(f"✅ ID `{user_id}` banido.")

    @commands.command()
    @commands.has_permissions(manage_roles=True)
    async def prision(self, ctx, member: discord.Member, minutes: int, *, reason="Sem motivo"):

        conn = self.get_db()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT prison_role FROM settings WHERE guild_id = ?",
            (ctx.guild.id,)
        )

        result = cursor.fetchone()
        conn.close()

        if not result:
            return await ctx.send(
                "Configure o cargo usando !setprisonrole"
            )

        role = ctx.guild.get_role(result[0])

        if role is None:
            return await ctx.send("Cargo não encontrado.")

        await member.add_roles(role)

        embed = discord.Embed(
            title="🔒 Você foi preso",
            color=discord.Color.dark_red()
        )

        embed.add_field(name="Tempo", value=f"{minutes} minutos")
        embed.add_field(name="Motivo", value=reason)

        await self.send_dm(member, embed)

        await ctx.send(
            f"✅ {member.mention} foi preso por {minutes} minutos."
        )


async def setup(bot):
    await bot.add_cog(Moderation(bot))
