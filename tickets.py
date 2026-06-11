import discord
import config


class CloseTicket(discord.ui.View):

    @discord.ui.button(
        label="Fechar Ticket",
        style=discord.ButtonStyle.red
    )
    async def close(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.channel.delete()


class TicketView(discord.ui.View):

    @discord.ui.button(
        label="Abrir Ticket",
        style=discord.ButtonStyle.green
    )
    async def ticket(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        guild = interaction.guild

        staff_role = guild.get_role(
            config.STAFF_ROLE_ID
        )

        overwrites = {

            guild.default_role:
            discord.PermissionOverwrite(
                read_messages=False
            ),

            interaction.user:
            discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True
            ),

            staff_role:
            discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True
            )
        }

        channel = await guild.create_text_channel(
            f"ticket-{interaction.user.name}",
            overwrites=overwrites
        )

        await channel.send(
            f"{interaction.user.mention}",
            view=CloseTicket()
        )

        await interaction.response.send_message(
            f"Ticket criado: {channel.mention}",
            ephemeral=True
        )
