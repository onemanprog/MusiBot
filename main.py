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
    intents.messages = True
    intents.voice_states = True
    intents.message_content = True

    # Create bot instance
    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        print(f"✅ Logged in as {bot.user.name}")
            
    on_ready()

    async def setup(Bot):
        await bot.add_cog(MusicController(bot=bot))
        
    asyncio.run(setup(bot))
    bot.run(token)


    

    

if __name__ == "__main__":
    main()