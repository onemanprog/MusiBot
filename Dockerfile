# Use an official lightweight Python image
FROM python:3.11-slim

ENV TZ=Asia/Omsk

# Install dependencies
# Install ffmpeg, libopus and libsodium (required for Discord voice)
RUN apt-get update \
 && apt-get install -y \
	ffmpeg \
	libopus0 \
	libffi8 \
	libsodium23 \
	ca-certificates \
	--no-install-recommends
# Keep image small
RUN rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app
VOLUME ["/app"]

# Copy files
COPY requirements.txt requirements.txt
RUN python -m pip uninstall -y discord py-cord nextcord disnake || true
RUN python -m pip install --no-cache-dir -r requirements.txt
RUN python -c "import discord, discord.voice_client as vc; print('discord', discord.__version__, discord.__file__, vc.__file__)"
RUN python -c "import pathlib, discord.voice_client as vc; s=pathlib.Path(vc.__file__).read_text(encoding='utf-8', errors='ignore'); expects_davey='davey library needed in order to use voice' in s; expects_pynacl='PyNaCl library needed in order to use voice' in s; has_nacl=getattr(vc, 'has_nacl', False); has_davey=getattr(vc, 'has_davey', False); assert has_nacl or has_davey, f'voice backend missing: expects_davey={expects_davey}, expects_pynacl={expects_pynacl}, has_nacl={has_nacl}, has_davey={has_davey}'"

COPY . .

# Run the bot
CMD ["python", "main.py"]
