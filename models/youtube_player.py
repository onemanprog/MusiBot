import asyncio
import discord
import yt_dlp
from collections import deque
from loguru import logger

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

    async def skip(self, vc):
        """Skips the current song."""
        if vc and vc.is_playing():
            vc.stop()
            await self.process_queue(vc)  # Обрабатываем следующую песню в очереди

    async def stop(self, vc):
        """Stops playback and clears the queue."""
        if vc:
            vc.stop()
            self.queue.clear()