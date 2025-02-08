import discord

class MusicView(discord.ui.View):
    """View with buttons for music control"""

    def __init__(self, music_player):
        super().__init__()
        self.music_player = music_player

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.primary)
    async def pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.music_player.vc.is_playing():
            self.music_player.vc.pause()
            await interaction.response.send_message("⏸ Music Paused", ephemeral=True)

    @discord.ui.button(label="Resume", style=discord.ButtonStyle.success)
    async def resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.music_player.vc.is_paused():
            self.music_player.vc.resume()
            await interaction.response.send_message("▶ Music Resumed", ephemeral=True)

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.music_player.vc.is_playing() or self.music_player.vc.is_paused():
            self.music_player.vc.stop()
            await interaction.response.send_message("⏹ Music Stopped", ephemeral=True)
            await self.music_player.vc.disconnect()