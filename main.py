import asyncio
import os
import discord
from discord.ext import commands
from controllers.music_controller import MusicController

def main():
    # load_dotenv()
    token = os.getenv("DISCORD_BOT_TOKEN")

    # Intents setup
    intents = discord.Intents.default()
    intents.voice_states = True
    intents.message_content = True

    # Create bot instance
    bot = commands.Bot(command_prefix="!", intents=intents)

    # Define the bot with a custom class to handle setup
    class MyBot(commands.Bot):
        async def setup_hook(self):
            """Properly load cogs before bot starts."""
            await self.add_cog(MusicController(self))

    # Create bot instance
    bot = MyBot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        print(f"✅ Logged in as {bot.user.name}")

    # Run the bot
    bot.run(token)
    

    

if __name__ == "__main__":
    main()