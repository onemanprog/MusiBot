import asyncio
import importlib.metadata as metadata
from pathlib import Path

import discord
from discord.ext import commands
from loguru import logger

from config.logging_config import configure_logging
from config.token_store import load_discord_token
from controllers.music_controller import setup_music_commands


def _read_voice_client_source() -> str:
    import discord.voice_client as discord_voice_client

    voice_client_path = getattr(discord_voice_client, "__file__", None)
    if not voice_client_path:
        return ""
    return Path(voice_client_path).read_text(encoding="utf-8", errors="ignore")


def verify_voice_dependencies():
    try:
        import discord.voice_client as discord_voice_client
    except Exception as exc:
        raise RuntimeError(
            "Voice dependencies are missing. Rebuild the container "
            "without cache: docker build --no-cache -t discord-music-bot ."
        ) from exc

    has_nacl = getattr(discord_voice_client, "has_nacl", None)
    has_davey = getattr(discord_voice_client, "has_davey", None)
    if has_nacl is True:
        logger.info("Voice backend ready: PyNaCl")
        return
    if has_davey is True:
        logger.info("Voice backend ready: davey")
        return

    voice_src = _read_voice_client_source()
    expects_davey = "davey library needed in order to use voice" in voice_src
    expects_pynacl = "PyNaCl library needed in order to use voice" in voice_src
    if expects_davey:
        missing = "davey"
    elif expects_pynacl:
        missing = "PyNaCl"
    else:
        missing = "unknown voice backend"

    raise RuntimeError(
        f"discord.voice_client voice backend is unavailable (expected {missing}). "
        "Rebuild without cache and verify installed discord package."
    )


def log_discord_runtime_diagnostics():
    logger.debug(f"discord.__version__={getattr(discord, '__version__', 'unknown')}")
    logger.debug(f"discord.__file__={getattr(discord, '__file__', 'unknown')}")

    related_dists = ["discord.py", "discord", "py-cord", "nextcord", "disnake", "PyNaCl"]
    dist_versions = {}
    for dist_name in related_dists:
        try:
            dist_versions[dist_name] = metadata.version(dist_name)
        except metadata.PackageNotFoundError:
            continue

    logger.debug(f"Installed discord-related distributions: {dist_versions}")

    try:
        import discord.voice_client as discord_voice_client

        voice_client_path = getattr(discord_voice_client, "__file__", None)
        logger.debug(f"discord.voice_client.__file__={voice_client_path}")
        logger.debug(f"discord.voice_client.has_nacl={getattr(discord_voice_client, 'has_nacl', 'unknown')}")
        logger.debug(f"discord.voice_client.has_davey={getattr(discord_voice_client, 'has_davey', 'unknown')}")

        if voice_client_path:
            voice_src = Path(voice_client_path).read_text(encoding="utf-8", errors="ignore")
            has_pynacl_message = "PyNaCl library needed in order to use voice" in voice_src
            has_davey_message = "davey library needed in order to use voice" in voice_src
            logger.debug(
                "voice_client error signatures: has_pynacl_message={}, has_davey_message={}",
                has_pynacl_message,
                has_davey_message,
            )
            if has_davey_message:
                logger.warning(
                    "discord.voice_client expects davey backend. "
                    "This is valid for newer discord.py releases, but davey must be installed."
                )
    except Exception as exc:
        logger.exception(f"Failed to inspect discord.voice_client runtime details: {exc}")


async def main():
    mode, level = configure_logging()
    if mode == "debug":
        log_discord_runtime_diagnostics()
    verify_voice_dependencies()
    logger.debug("Voice dependencies imported successfully")
    token = load_discord_token()
    logger.debug("Discord token loaded from environment/token store")

    intents = discord.Intents.default()
    intents.voice_states = True
    intents.message_content = True
    logger.debug("Discord intents configured")

    bot = commands.Bot(command_prefix="!", intents=intents)
    logger.info(f"Bot instance created (mode={mode}, log_level={level})")

    @bot.event
    async def on_ready():
        logger.info(f"Logged in as {bot.user.name} (id={bot.user.id})")
        try:
            synced = await bot.tree.sync()
            logger.info(f"Synced {len(synced)} command(s)")
        except Exception as exc:
            logger.exception(f"Failed to sync commands: {exc}")

    async def setup_hook():
        logger.debug("setup_hook invoked: registering music commands")
        setup_music_commands(bot)
        logger.debug("Music commands registered")

    bot.setup_hook = setup_hook

    try:
        logger.info("Starting Discord bot")
        await bot.start(token)
    except Exception as exc:
        logger.exception(f"Fatal error while running bot: {exc}")
        raise
    finally:
        logger.info("Shutting down Discord bot")
        if not bot.is_closed():
            await bot.close()
            logger.info("Discord bot closed")


if __name__ == "__main__":
    asyncio.run(main())
