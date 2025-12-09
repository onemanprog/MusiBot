import asyncio
import discord
import yt_dlp
from collections import deque
from loguru import logger

from discord.ext import commands

class YouTubePlayer:
    """Проигрывает YouTube-видео и поддерживает работу с плейлистами."""

    def __init__(self):
        self.loop = asyncio.get_event_loop()
        self.currently_playing = None

    async def extract_playlist(self, playlist_url):
        """Получает список видео из плейлиста."""
        ydl_opts = {
            'quiet': True,
            'extract_flat': True,  # Позволяет получить ссылки без скачивания
            'force_generic_extractor': True
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(playlist_url, download=False)
                if 'entries' in info:
                    return [entry['url'] for entry in info['entries'] if 'url' in entry]
        except Exception as e:
            logger.error(f"Ошибка при получении плейлиста: {e}")
        return []

    async def play(self, vc, url):
        """Проигрывает песню."""
        ydl_opts = {
            'format': 'bestaudio/best',
            'noplaylist': True,  # Отключаем автоматическую загрузку плейлистов
            'ignoreerrors': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                audio_url = info["url"]  # Просто берем URL без .decode()
                title = info["title"]
                await vc.send(f"🎵 Now playing {title}")


            #ffmpeg_path = r"G:\Разработка\ffmpeg\bin\ffmpeg.exe"
            ffmpeg_options = {
                'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
                'options': '-vn'
            }

            def after_playing(error):
                if error:
                    logger.error(f"Ошибка воспроизведения: {error}")
                logger.info("Трек завершился")

            vc.play(
                discord.FFmpegPCMAudio(audio_url, **ffmpeg_options),
                after=after_playing
            )

        except Exception as e:
            logger.error(f"Ошибка воспроизведения: {e}")
    
    async def search_and_play(self, ctx: commands.Context, query):
        """Searches for a song on YouTube and returns the first result."""
        
        ydl_opts = {
            "format": "bestaudio/best",
            "noplaylist": True,
            "quiet": True,
            'default_search': 'ytsearch',  # Enables YouTube search
            'extract_flat': True  # Avoids downloading the video
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(query, download=False)
                if "entries" not in info or not info["entries"]:
                    return None
                
                first_result = info["entries"][0]
                url = first_result.get('webpage_url', 'URL not found')
                title = first_result.get('title', 'Title not found')

                logger.debug(f"Found song: {title}")
                logger.debug(f"Found url: {url}")

                return title, url

            except Exception as e:
                logger.error(f"Error searching YouTube: {e}")
                return None


