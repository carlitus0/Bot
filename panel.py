import discord

class BanModal(discord.ui.Modal, title="Banir usuário"):
    user_id = discord.ui.TextInput(label="ID do usuário")
    reason = discord.ui.TextInput(label="Motivo")

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = await guild.fetch_member(int(self.user_id.value))

        await user.ban(reason=self.reason.value)

        await interaction.response.send_message(
            f"Usuário {user} banido",
            ephemeral=True
        )


class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="BANIR", style=discord.ButtonStyle.red)
    async def ban(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BanModal())
