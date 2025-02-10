import asyncio
import discord
import yt_dlp
from collections import deque
from loguru import logger

class YouTubePlayer:
    """Handles YouTube audio playback and queue management."""

    def __init__(self):
        self.queue = deque()
        self.currently_playing = None
        self.queue_lock = asyncio.Lock()

    async def add_to_queue(self, url):
        """Adds a song to the queue safely."""
        async with self.queue_lock:
            self.queue.append(url)
    
    def is_valid_youtube_url(self, url):
        """Checks if a given URL is a valid YouTube link."""
        return url.startswith("https://www.youtube.com/") or url.startswith("https://youtu.be/")

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
            try:
                info = ydl.extract_info(url, download=False)
                if not info or 'url' not in info:
                    await ctx.send("❌ Failed to retrieve audio. Skipping...")
                    return await self.process_queue(ctx)  # Retry the queue
                audio_url = info['url']
            except Exception as e:
                logger.error(f"yt-dlp error: {e}")
                await ctx.send("❌ Error processing the song. Skipping...")
                return await self.process_queue(ctx)  # Retry the queue


        voice_client = ctx.voice_client

        if not voice_client:
            await ctx.send("❌ I'm not connected to a voice channel.")
            return

        ffmpeg_options = {
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
            'options': '-vn'
        }

        if not discord.FFmpegPCMAudio:
            await ctx.send("❌ FFmpeg is not installed. Please install it and restart the bot.")
            return
        
        voice_client.play(
            discord.FFmpegPCMAudio(audio_url, **ffmpeg_options),
            after= lambda ex: ctx.bot.loop.call_soon_threadsafe(asyncio.Event().set)
        )
        

        await ctx.send(f"🎶 Now playing: {info['title']}")

        await asyncio.Event().wait()

    async def after(self, ctx):
        if not self.queue.empty() and not ctx.voice_client.is_playing():
            logger.info("looping start")
            await self.process_queue(ctx)
            logger.info("looping end")

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