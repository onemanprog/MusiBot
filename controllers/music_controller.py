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
        self.queue_list = []
        self.currently_playing = None
        self.youtube_player = YouTubePlayer()
        self.is_processing = False

    async def add_to_queue(self, song, vc):
        """Добавляет песню или весь плейлист в очередь."""
        url_or_query = song.url  # Получаем URL из объекта YouTubeSong

        if isinstance(url_or_query, str):
            if ("playlist?" in url_or_query or "list=" in url_or_query):
                # Если это плейлист, загружаем все песни
                songs = await self.youtube_player.extract_playlist(url_or_query)
                if songs:
                    for song_url in songs:
                        new_song = YouTubeSong(song_url)  # Создаем объекты YouTubeSong
                        self.queue_list.append(new_song)
                    logger.info(f"Добавлено {len(songs)} треков из плейлиста!")
                else:
                    logger.warning("Не удалось загрузить плейлист.")
                    
        elif url_or_query.startswith("https://www.youtube.com/") or url_or_query.startswith("https://youtu.be/"):
            # Если это одиночное видео
            self.queue_list.append(song)
        else:
            # If it's not a URL, perform a YouTube search
            search_result = await self.youtube_player.search_and_play(None, url_or_query)
            if search_result:
                logger.debug("found song")
                title, song_url = search_result
                new_song = YouTubeSong(song_url)
                self.queue_list.append(new_song)
                logger.info(f"🎵 Найден и добавлен в очередь: {title}")
                

        if not vc.is_playing() and not self.is_processing:
            await self.process_queue(vc)

    async def process_queue(self, vc):
        """Processes songs from the queue sequentially."""
        if self.is_processing:
            return
        
        self.is_processing = True
        try:
            while self.queue_list:
                if vc.is_playing():  # Если уже играет - ждем окончания
                    await asyncio.sleep(1)
                    continue

                song = self.queue_list.pop(0)  # Получаем первую песню из списка
                self.currently_playing = song

                # Воспроизведение трека
                await song.play(vc)

                # Ожидаем завершения трека
                while vc.is_playing():
                    await asyncio.sleep(1)
        finally:
            self.is_processing = False


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
    async def play(interaction: discord.Interaction, url_or_query: str):
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
        if "youtube.com" in url_or_query or "youtu.be" in url_or_query:
            song = YouTubeSong(url_or_query)
            title = url_or_query
        # elif "open.spotify.com" in url:
        #     #EVEN IF Spotify URL pushed should be handled by YoutubeSong, cause Spotify doesn't give API for songs
        #     song = SpotifySong(url)
        else:
            result = await YouTubePlayer().search_and_play(None, url_or_query)  # search by name
            if not result:
                await interaction.followup.send("❌ No results found on YouTube.")
                return
            title, url = result
            song = YouTubeSong(url)
            # await interaction.followup.send("❌ Invalid URL. Only YouTube and Spotify links are supported.")
            # return

        if not song:  # If no song was created
            await interaction.followup.send("❌ No results found on YouTube.")
            return  # Stop execution to avoid using `title` and `url`

        await music_queue.add_to_queue(song, vc)  # Передаем vc в add_to_queue
        await interaction.followup.send(f"✅ Added to queue: {title}")

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