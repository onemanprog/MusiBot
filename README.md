# MusiBot

Discord music bot focused on YouTube playback through Discord voice.

## Development Model

Development is expected to happen inside a Linux environment, preferably through VS Code Remote Explorer with WSL.

- Edit and run the project from WSL.
- Keep secrets in `.env`.
- Use Docker with a bind mount so code changes stay on the host filesystem.

## Configuration

Create a project-level `.env` file:

```dotenv
DISCORD_BOT_TOKEN=your_token_here
MODE=debug
```

The bot reads `DISCORD_BOT_TOKEN` from the environment. `DISCORD_BOT_TOKEN_FILE` is supported as an optional fallback, but `.env` is the default workflow.
Set `MODE=debug` to enable verbose debug logs in `docker logs`.

## Local Run Inside WSL

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Start the bot:

```bash
python3 main.py
```

## Tests

Install dev dependencies:

```bash
python3 -m pip install -r requirements-dev.txt
```

Run the pytest suite:

```bash
pytest -q
```

Run the direct queue/playback test without Discord or ffmpeg:

```bash
python3 tests/run_direct_test.py
```

## Docker From WSL

Build the image:

```bash
docker build -t discord-music-bot .
```

Run with the current project directory mounted into the container:

```bash
docker run --rm --name d_bot_cont --env-file .env -v "$(pwd):/app" discord-music-bot
```

If the source code changes, restart the container process. You do not need to rebuild the image unless dependencies or the Docker image itself changed.

## Docker From Windows Host

Keep this workflow if you want the source of truth to remain on the Windows filesystem while still running the container with a bind mount:

```text
docker run --rm --name d_bot_cont --env-file .env -v "C:\Users\user\vs_code_projects\musibot:/app" discord-music-bot
```

## Notes

- Slash commands are synced on startup through `bot.tree.sync()`.
- If playback queues but does not start, run `python3 tests/run_direct_test.py` first to isolate queue logic from Discord voice issues.
- If voice connection fails, check the bot token, guild permissions, ffmpeg availability, and that only one bot instance is connected.

## Voice Dependency Troubleshooting

If you see voice dependency errors (`PyNaCl` or `davey`), rebuild the image without cache and inspect voice backend flags inside the container:

```bash
docker build --no-cache -t discord-music-bot .
docker run --rm discord-music-bot python -c "import discord,discord.voice_client as vc; print(discord.__version__, discord.__file__, vc.__file__, getattr(vc, 'has_nacl', None), getattr(vc, 'has_davey', None))"
```
