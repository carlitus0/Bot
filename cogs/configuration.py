import sqlite3

from discord.ext import commands


class Configuration(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setprisonrole(self, ctx, role):

        conn = sqlite3.connect("database/bot.db")
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT OR REPLACE INTO settings
            (guild_id, prison_role)
            VALUES (?, ?)
            """,
            (ctx.guild.id, role.id)
        )

        conn.commit()
        conn.close()

        await ctx.send("✅ Cargo de prisão configurado.")


async def setup(bot):
    await bot.add_cog(Configuration(bot))
