import asyncio
import os
import discord
from discord.ext import commands
from controllers.music_controller import setup_music_commands

def main():
    # load_dotenv()
    token = os.getenv("DISCORD_BOT_TOKEN")

    # Intents setup
    intents = discord.Intents.default()
    intents.voice_states = True
    intents.message_content = True

    # Create bot instance
    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        print(f"✅ Logged in as {bot.user.name}")
        await bot.tree.sync()  # Syncing slash commands when bot is ready

    @bot.event
    async def setup_hook():
        setup_music_commands(bot)

    # Run the bot
    bot.run(token)

if __name__ == "__main__":
    main()