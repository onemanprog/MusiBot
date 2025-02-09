import asyncio
import discord
import yt_dlp
from collections import deque

class YouTubePlayer:
    """Handles YouTube audio playback and queue management."""

    def __init__(self):
        self.queue = deque()
        self.currently_playing = None

    async def add_to_queue(self, url):
        """Adds a song to the queue."""
        self.queue.append(url)

    async def print_queue(self, ctx):
        """Prints the current queue."""
        if not self.queue:
            await ctx.send("🎵 Queue is empty.")
            return

        queue_list = "\n".join(self.queue)
        await ctx.send(f"🎵 Queue:\n{queue_list}")

    async def process_queue(self, ctx):
        """Processes and plays the next song in the queue."""
        if not self.queue:
            await ctx.send("🎵 Queue is empty.")
            return

        url = self.queue.popleft()
        self.currently_playing = url

        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            audio_url = info['url']

        voice_client = ctx.voice_client

        if not voice_client:
            await ctx.send("❌ I'm not connected to a voice channel.")
            return

        ffmpeg_options = {
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
            'options': '-vn'
        }

        voice_client.play(discord.FFmpegPCMAudio(audio_url, **ffmpeg_options), after=lambda e: asyncio.run_coroutine_threadsafe(self.process_queue(ctx), asyncio.get_event_loop()))

        await ctx.send(f"🎶 Now playing: {info['title']}")

    async def skip(self, ctx):
        """Skips the current song."""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("⏩ Skipped!")
            await self.process_queue(ctx)
        else:
            await ctx.send("No song is currently playing.")

    async def stop(self, ctx):
        """Stops playback and clears the queue."""
        if ctx.voice_client:
            ctx.voice_client.stop()
            self.queue.clear()
            await ctx.send("🛑 Stopped playback and cleared the queue.")