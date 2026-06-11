import discord

class LogSystem:

    def __init__(self, bot, log_channel_id):
        self.bot = bot
        self.log_channel_id = log_channel_id

    async def send_log(self, guild, msg):

        channel = guild.get_channel(
            self.log_channel_id
        )

        if channel:
            await channel.send(msg)

    def setup(self):

        bot = self.bot

        @bot.event
        async def on_message(message):

            if message.author.bot:
                return

            await self.send_log(
                message.guild,
                f"📨 MSG | {message.author} | {message.channel.mention}\n{message.content}"
            )

            await bot.process_commands(message)

        @bot.event
        async def on_message_delete(message):

            if message.author.bot:
                return

            await self.send_log(
                message.guild,
                f"🗑 DELETE | {message.author}\n{message.content}"
            )

        @bot.event
        async def on_message_edit(before, after):

            if before.author.bot:
                return

            if before.content == after.content:
                return

            await self.send_log(
                before.guild,
                f"✏ EDIT\nUsuário: {before.author}\nAntes: {before.content}\nDepois: {after.content}"
            )

        @bot.event
        async def on_member_join(member):

            await self.send_log(
                member.guild,
                f"✅ JOIN | {member}"
            )

        @bot.event
        async def on_member_remove(member):

            await self.send_log(
                member.guild,
                f"❌ LEAVE | {member}"
            )

        @bot.event
        async def on_guild_channel_create(channel):

            await self.send_log(
                channel.guild,
                f"📁 CANAL CRIADO | {channel.name}"
            )

        @bot.event
        async def on_guild_channel_delete(channel):

            await self.send_log(
                channel.guild,
                f"🗑 CANAL APAGADO | {channel.name}"
            )

        @bot.event
        async def on_guild_role_create(role):

            await self.send_log(
                role.guild,
                f"🎭 CARGO CRIADO | {role.name}"
            )

        @bot.event
        async def on_guild_role_delete(role):

            await self.send_log(
                role.guild,
                f"🗑 CARGO APAGADO | {role.name}"
            )

        @bot.event
        async def on_member_update(before, after):

            if len(after.roles) > len(before.roles):

                role = list(
                    set(after.roles) - set(before.roles)
                )[0]

                await self.send_log(
                    after.guild,
                    f"➕ CARGO ADICIONADO | {after} | {role.name}"
                )

            elif len(after.roles) < len(before.roles):

                role = list(
                    set(before.roles) - set(after.roles)
                )[0]

                await self.send_log(
                    after.guild,
                    f"➖ CARGO REMOVIDO | {after} | {role.name}"
          )
