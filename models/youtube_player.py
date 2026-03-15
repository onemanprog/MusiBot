import asyncio
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import discord
import yt_dlp
from loguru import logger


@dataclass(frozen=True)
class ResolvedTrack:
    title: str
    url: str


class YouTubePlayer:
    def __init__(self):
        self.currently_playing = None

    @staticmethod
    def is_youtube_url(value: str) -> bool:
        parsed = urlparse(value)
        return parsed.netloc in {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "youtu.be",
        }

    @classmethod
    def is_playlist_url(cls, value: str) -> bool:
        if not cls.is_youtube_url(value):
            return False
        parsed = urlparse(value)
        query = parse_qs(parsed.query)
        return "list" in query

    async def resolve_input(self, value: str) -> list[ResolvedTrack]:
        logger.debug(f"resolve_input called with value={value}")
        if self.is_playlist_url(value):
            logger.debug("Input classified as playlist URL")
            return await self.extract_playlist(value)
        if self.is_youtube_url(value):
            logger.debug("Input classified as direct YouTube URL")
            track = await self.extract_track(value)
            return [track] if track else []

        logger.debug("Input classified as search query")
        track = await self.search(value)
        return [track] if track else []

    async def extract_playlist(self, playlist_url: str) -> list[ResolvedTrack]:
        ydl_opts = {
            "quiet": True,
            "extract_flat": True,
            "skip_download": True,
        }

        def _extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(playlist_url, download=False)

        try:
            logger.debug(f"Extracting playlist metadata: {playlist_url}")
            info = await asyncio.to_thread(_extract)
            entries = info.get("entries") or []
            tracks = []
            for entry in entries:
                track = self._track_from_entry(entry)
                if track:
                    tracks.append(track)
            logger.debug(
                "Playlist extraction completed: input_entries={}, resolved_tracks={}",
                len(entries),
                len(tracks),
            )
            return tracks
        except Exception as exc:
            logger.exception(f"Failed to extract playlist: {exc}")
            return []

    async def extract_track(self, url: str) -> ResolvedTrack | None:
        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "noplaylist": True,
        }

        def _extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)

        try:
            logger.debug(f"Extracting single track metadata: {url}")
            info = await asyncio.to_thread(_extract)
            track = self._track_from_entry(info)
            logger.debug(f"Extracted single track: {track}")
            return track
        except Exception as exc:
            logger.exception(f"Failed to extract track: {exc}")
            return None

    async def search(self, query: str) -> ResolvedTrack | None:
        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "noplaylist": True,
            "default_search": "ytsearch1",
            "extract_flat": True,
        }

        def _search():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(query, download=False)

        try:
            logger.debug(f"Executing YouTube search query: {query}")
            info = await asyncio.to_thread(_search)
            entries = info.get("entries") or []
            if not entries:
                logger.debug("YouTube search returned no entries")
                return None
            first_track = self._track_from_entry(entries[0])
            logger.debug(f"YouTube search resolved track: {first_track}")
            return first_track
        except Exception as exc:
            logger.exception(f"Error searching YouTube: {exc}")
            return None

    async def play(self, vc, url, callback=None):
        ydl_opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "noplaylist": True,
            "ignoreerrors": True,
        }

        def _extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)

        try:
            logger.debug(f"Resolving playable audio URL for: {url}")
            info = await asyncio.to_thread(_extract)
            if not info or "url" not in info:
                raise RuntimeError("yt-dlp did not return a playable audio URL")

            audio_url = info["url"]
            title = info.get("title", url)
            loop = asyncio.get_running_loop()
            logger.debug(f"Audio URL resolved for title={title}")

            def after_playing(error):
                if error:
                    logger.error(f"Playback error: {error}")
                else:
                    logger.debug(f"Playback callback completed without error: {title}")
                if callback:
                    asyncio.run_coroutine_threadsafe(callback(), loop)
                    logger.debug("Track completion callback scheduled")

            self.currently_playing = url
            logger.info(f"Now playing: {title}")
            vc.play(
                discord.FFmpegPCMAudio(
                    audio_url,
                    before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                    options="-vn",
                ),
                after=after_playing,
            )
            logger.debug("Voice client play() invoked")
        except Exception as exc:
            logger.exception(f"Playback failed: {exc}")
            if callback:
                await callback()
                logger.debug("Fallback callback awaited after playback failure")

    @staticmethod
    def _track_from_entry(entry) -> ResolvedTrack | None:
        if not entry:
            logger.debug("_track_from_entry received empty entry")
            return None

        title = entry.get("title") or "Unknown title"
        webpage_url = entry.get("webpage_url") or entry.get("url")
        if not webpage_url:
            video_id = entry.get("id")
            if video_id:
                webpage_url = f"https://www.youtube.com/watch?v={video_id}"

        if not webpage_url:
            logger.debug("_track_from_entry failed: no URL fields found")
            return None

        if webpage_url.startswith("/watch"):
            webpage_url = f"https://www.youtube.com{webpage_url}"
        elif not webpage_url.startswith("http"):
            webpage_url = f"https://www.youtube.com/watch?v={webpage_url}"

        track = ResolvedTrack(title=title, url=webpage_url)
        logger.debug(f"_track_from_entry resolved: {track}")
        return track
