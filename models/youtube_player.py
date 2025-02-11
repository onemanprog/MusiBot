import asyncio
import discord
import yt_dlp
from collections import deque

class YouTubePlayer:
    """Handles YouTube audio playback and queue management."""

    def __init__(self):
        self.queue = deque()
        self.loop = asyncio.get_event_loop()
        self.currently_playing = None

    async def add_to_queue(self, url):
        """Adds a song to the queue."""
        self.queue.append(url)

    async def print_queue(self, ctx):
        """Prints the current queue."""
        if not self.queue:
            await ctx.send("🎵 Queue is empty.")
            return
    async def play(self, vc, url):
        """Plays a song or adds it to the queue."""
        await self.add_to_queue(url)  # Добавляем песню в очередь

        # Если ничего не воспроизводится, начинаем обработку очереди
        if not vc.is_playing():
            await self.process_queue(vc)

    async def process_queue(self, vc):
        """Processes and plays the next song in the queue."""
        if not self.queue:
            return  # Если очередь пуста, ничего не делаем

        url = self.queue.popleft()
        self.currently_playing = url

        ydl_opts = {
            'format': 'bestaudio/best',
            'noplaylist': True,  # Ensures only single video is processed
            'ignoreerrors': True,  # Prevents crash on unavailable videos
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True,
            'http_headers': {'User-Agent': 'Mozilla/5.0'}
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            audio_url = info['url']


        ffmpeg_options = {
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
            'options': '-vn'
        }

        # Play the audio
        vc.play(
            discord.FFmpegPCMAudio(audio_url, executable=ffmpeg_path, **ffmpeg_options),
            after=lambda e: self.loop.call_soon_threadsafe(
                asyncio.create_task,  # Создаем задачу в основном цикле событий
                self.process_queue(vc)  # Обрабатываем следующую песню в очереди
            )
        )

    async def skip(self, vc):
        """Skips the current song."""
        if vc and vc.is_playing():
            vc.stop()
            await self.process_queue(vc)  # Обрабатываем следующую песню в очереди

    async def stop(self, vc):
        """Stops playback and clears the queue."""
        if vc:
            vc.stop()
            self.queue.clear()