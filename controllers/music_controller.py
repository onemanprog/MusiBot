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
        self.queue_list = []
        self.youtube_player = YouTubePlayer()

    async def add_to_queue(self, song, vc):
        """Добавляет песню или весь плейлист в очередь."""
        url = song.url  # Получаем URL из объекта YouTubeSong

        if isinstance(url, str) and ("playlist?" in url or "list=" in url):
            # Если это плейлист, загружаем все песни
            songs = await self.youtube_player.extract_playlist(url)
            if songs:
                for song_url in songs:
                    new_song = YouTubeSong(song_url)  # Создаем объекты YouTubeSong
                    await self.queue.put(new_song)
                    self.queue_list.append(new_song)
                logger.info(f"Добавлено {len(songs)} треков из плейлиста!")
            else:
                logger.warning("Не удалось загрузить плейлист.")
        else:
            # Если это одиночное видео
            await self.queue.put(song)
            self.queue_list.append(song)

        if not vc.is_playing():
            await self.process_queue(vc)

    async def process_queue(self, vc):
        while not self.queue.empty():
            if vc.is_playing():  # Если уже играет - ждем окончания
                await asyncio.sleep(1)
                continue

            song = await self.queue.get()
            self.currently_playing = song

            # Воспроизведение трека
            await song.play(vc)

            # Ожидаем завершения трека
            while vc.is_playing():
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
        await interaction.response.defer()  # Даем Discord понять, что команда обрабатывается

        if interaction.user.voice is None:
            await interaction.followup.send("❌ You need to be in a voice channel to use this command!")
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
            await interaction.followup.send("❌ Invalid URL. Only YouTube and Spotify links are supported.")
            return

        await music_queue.add_to_queue(song, vc)  # Передаем vc в add_to_queue
        await interaction.followup.send(f"✅ Added to queue: {url}")

        # Если бот не воспроизводит музыку, начинаем воспроизведение
        if not vc.is_playing():
            await music_queue.process_queue(vc)

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
        if not music_queue.queue_list:  # Проверяем список, а не очередь
            await interaction.response.send_message("The queue is empty.")
        else:
            queue_list = [song.url for song in music_queue.queue_list]
            await interaction.response.send_message(f"Upcoming songs:\n" + "\n".join(queue_list))