import asyncio
import discord
import yt_dlp
from collections import deque
from loguru import logger

class YouTubePlayer:
    """Убираем лишнюю очередь, полагаемся на управление в MusicQueue."""

    def __init__(self):
        self.loop = asyncio.get_event_loop()
        self.currently_playing = None

    async def play(self, vc, url):
        """Загружает и воспроизводит YouTube-аудио."""
        try:
            ydl_opts = {
                'format': 'bestaudio/best',
                'noplaylist': True,
                'ignoreerrors': True,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'quiet': True,
                'http_headers': {'User-Agent': 'Mozilla/5.0'}
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                audio_url = info['url']

            ffmpeg_path = r"G:\Разработка\ffmpeg\bin\ffmpeg.exe"
            ffmpeg_options = {
                'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
                'options': '-vn'
            }

            # Запускаем воспроизведение
            def after_playing(error):
                if error:
                    logger.error(f"Ошибка воспроизведения: {error}")
                logger.info("Трек завершился")

            vc.play(
                discord.FFmpegPCMAudio(audio_url, executable=ffmpeg_path, **ffmpeg_options),
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