import os
from pathlib import Path


def default_token_path() -> Path:
    return Path.home() / ".config" / "musibot" / "token.txt"


def load_discord_token() -> str:
    direct_token = os.getenv("DISCORD_BOT_TOKEN")
    if direct_token:
        return direct_token.strip()

    configured_path = os.getenv("DISCORD_BOT_TOKEN_FILE")
    token_path = Path(configured_path).expanduser() if configured_path else default_token_path()

    try:
        return token_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Discord bot token was not found. Set DISCORD_BOT_TOKEN "
            "(for example via docker run --env-file .env) or create "
            f"{token_path}."
        ) from exc
