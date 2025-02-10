import discord
from discord.ext import commands
from models.youtube_player import YouTubePlayer
from views.music_view import MusicView
from loguru import logger

class MusicController(commands.Cog):
    """Controller for handling music commands"""

    def __init__(self, bot):
        self.bot = bot
        self.yt_player = YouTubePlayer()

    @commands.command()
    async def join(self, ctx):
        """Joins a voice channel."""
        if ctx.author.voice:
            channel = ctx.author.voice.channel
            await channel.connect()
        else:
            await ctx.send("❌ You need to be in a voice channel to use this command!")

    @commands.command()
    async def leave(self, ctx):
        """Leaves the voice channel."""
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
        else:
            await ctx.send("I'm not in a voice channel!")

    @commands.command()
    async def play(self, ctx, url):
        logger.info(f"Received command: !play {url}")  # Debugging line
        if ctx.author.voice is None:
            await ctx.send("❌ You need to be in a voice channel to use this command!")
            return

        channel = ctx.author.voice.channel
        if ctx.voice_client is None:
            try:
                vc = await discord.VoiceChannel.connect(channel)
            except discord.errors.Forbidden:
                await ctx.send("❌ I don't have permission to join this voice channel.")
                return
            except discord.errors.ClientException:
                await ctx.send("❌ I'm already connected to a voice channel.")
                return
        else:
            vc = ctx.voice_client

        if not self.yt_player.is_valid_youtube_url(url):
            await ctx.send("❌ Invalid YouTube URL. Please provide a valid link.")
            return

        """Queues a song and starts playing if not already playing."""
        await self.yt_player.add_to_queue(url)
        await ctx.send(f"Added to queue: {url}")

        if ctx.voice_client and not ctx.voice_client.is_playing():
            await self.yt_player.process_queue(ctx)

    @commands.command()
    async def skip(self, ctx):
        """Skips the current song and plays the next in queue."""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            if self.yt_player.queue:
                await ctx.send("⏭️ Skipping to next song...")
                await self.yt_player.process_queue(ctx)
            else:
                await ctx.send("🚫 No more songs in the queue.")

    @commands.command()
    async def queue(self, ctx):
        """Displays the current song queue."""
        await self.yt_player.print_queue(ctx)