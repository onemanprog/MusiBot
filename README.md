# MusiBot
Discord bot for Spotify (and maybe other) music listening

#TODO:  
~~Add Discord Bot Integration~~  
Add Spotify Integration  
~~Write base code in main.py :P~~  
Add deploy to our server  
Add CI/CD to deploy  
Add Playlist link processing  
Add Shuffle  

Project structure:

/discord-music-bot
│── /src
│   │── __init__.py
│   │── youtube_player.py
│   │── spotify_player.py
│   │── music_bot.py
│── main.py
│── requirements.txt
│── Dockerfile
│── .env
│── .gitignore
|


How It Works:

✅ !play <URL> → Adds a song to the queue.
✅ !skip → Moves to the next song in the queue.
✅ !queue → Shows upcoming songs.
✅ !join / !leave → Manages voice channel connection.

DEPLOY:
1. create (if not exists) .env and set: DISCORD_BOT_TOKEN=
2. docker build -t discord-music-bot .
3. docker run --env-file .env --rm --name d_bot_cont discord-music-bot
