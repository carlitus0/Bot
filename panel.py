import discord


class BanModal(discord.ui.Modal,title="Banir Usuário"):

    user_id = discord.ui.TextInput(
        label="ID do usuário"
    )

    motivo = discord.ui.TextInput(
        label="Motivo"
    )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        guild = interaction.guild

        try:

            user = await guild.fetch_member(
                int(self.user_id.value)
            )

            await user.ban(
                reason=self.motivo.value
            )

            await interaction.response.send_message(
                "Usuário banido.",
                ephemeral=True
            )

        except:

            await interaction.response.send_message(
                "Erro ao banir.",
                ephemeral=True
            )


class PanelView(discord.ui.View):

    @discord.ui.button(
        label="BAN",
        style=discord.ButtonStyle.red
    )
    async def ban_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.send_modal(
            BanModal()
        )
