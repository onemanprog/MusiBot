import discord
from discord.ext import commands
from models.youtube_player import YouTubePlayer
from views.music_view import MusicView

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
        print(f"Received command: !play {url}")  # Debugging line
        if ctx.author.voice is None:
            await ctx.send("❌ You need to be in a voice channel to use this command!")
            return

        channel = ctx.author.voice.channel
        if ctx.voice_client is None:
            vc = await discord.VoiceChannel.connect(channel)
        else:
            vc = ctx.voice_client

        """Queues a song and starts playing if not already playing."""
        await self.yt_player.add_to_queue(url)
        await ctx.send(f"Added to queue: {url}")

        if not ctx.voice_client.is_playing():
            await self.yt_player.process_queue(ctx)

    @commands.command()
    async def skip(self, ctx):
        """Skips the current song and plays the next in queue."""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("Skipped!")
            await self.yt_player.process_queue(ctx)
        else:
            await ctx.send("No song is playing.")

    @commands.command()
    async def queue(self, ctx):
        """Displays the current song queue."""
        if self.yt_player.queue.empty():
            await ctx.send("The queue is empty.")
        else:
            queue_list = list(self.yt_player.queue._queue)
            await ctx.send(f"Upcoming songs:\n" + "\n".join(queue_list))