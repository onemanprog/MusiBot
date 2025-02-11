import discord
import asyncio
from discord import app_commands
from discord.ext import commands
from models.youtube_player import YouTubePlayer
from views.music_view import MusicView
from loguru import logger


class Song:
    def __init__(self, url):
        self.url = url

    async def play(self, vc):
        raise NotImplementedError("Subclasses must implement play method")


class YouTubeSong(Song):
    def __init__(self, url):
        super().__init__(url)
        self.player = YouTubePlayer()

    async def play(self, vc):
        await self.player.play(vc, self.url)  # Вызываем метод play из YouTubePlayer


class SpotifySong(Song):
    def __init__(self, url):
        super().__init__(url)
        self.player = SpotifyPlayer()

    async def play(self, vc):
        await self.player.play(vc, self.url)


class MusicQueue:
    def __init__(self):
        self.queue = asyncio.Queue()

    async def add_to_queue(self, song):
        await self.queue.put(song)

    async def process_queue(self, vc):
        while not self.queue.empty():
            song = await self.queue.get()
            await song.play(vc)
            await asyncio.sleep(1)


def setup_music_commands(bot):
    music_queue = MusicQueue()

    @bot.tree.command(name="join", description="Joins a voice channel.")
    async def join(interaction: discord.Interaction):
        if interaction.user.voice:
            channel = interaction.user.voice.channel
            await channel.connect()
            await interaction.response.send_message("✅ Joined the channel!")
        else:
            await interaction.response.send_message("❌ You need to be in a voice channel to use this command!")

    @bot.tree.command(name="leave", description="Leaves the voice channel.")
    async def leave(interaction: discord.Interaction):
        if interaction.guild.voice_client:
            await interaction.guild.voice_client.disconnect()
            await interaction.response.send_message("✅ Left the voice channel!")
        else:
            await interaction.response.send_message("❌ I'm not in a voice channel!")

    @bot.tree.command(name="play", description="Play a song from YouTube or Spotify.")
    async def play(interaction: discord.Interaction, url: str):
        if interaction.user.voice is None:
            await interaction.response.send_message("❌ You need to be in a voice channel to use this command!")
            return

        channel = interaction.user.voice.channel
        if interaction.guild.voice_client is None:
            vc = await channel.connect()
        else:
            vc = interaction.guild.voice_client

        # Определяем источник песни
        if "youtube.com" in url or "youtu.be" in url:
            song = YouTubeSong(url)
        elif "open.spotify.com" in url:
            song = SpotifySong(url)
        else:
            await interaction.response.send_message("❌ Invalid URL. Only YouTube and Spotify links are supported.")
            return

        await music_queue.add_to_queue(song)
        await interaction.response.send_message(f"Added to queue: {url}")

        # Если бот не воспроизводит музыку, начинаем воспроизведение
        if not vc.is_playing():
            await music_queue.process_queue(vc)  # Передаем vc вместо interaction

    @bot.tree.command(name="skip", description="Skips the current song and plays the next in queue.")
    async def skip(interaction: discord.Interaction):
        if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
            interaction.guild.voice_client.stop()
            await interaction.response.send_message("Skipped!")
            await music_queue.process_queue(interaction.guild.voice_client)
        else:
            await interaction.response.send_message("No song is playing.")

    @bot.tree.command(name="queue", description="Displays the current song queue.")
    async def queue(interaction: discord.Interaction):
        if not music_queue.queue:  # Эта проверка эквивалентна len(music_queue.queue) == 0
            await interaction.response.send_message("The queue is empty.")
        else:
            queue_list = [song.url for song in list(music_queue.queue)]
            await interaction.response.send_message(f"Upcoming songs:\n" + "\n".join(queue_list))