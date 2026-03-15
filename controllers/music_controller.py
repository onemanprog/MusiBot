import asyncio
from collections import deque
from contextlib import suppress
from typing import Sequence

import discord
from loguru import logger

from models.spotify_player import SpotifyPlayer, SpotifyTrack
from models.youtube_player import ResolvedTrack, YouTubePlayer


def is_voice_dependency_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "pynacl library needed in order to use voice" in text
        or "davey library needed in order to use voice" in text
        or "library needed in order to use voice" in text
    )


class Song:
    def __init__(self, url: str, title: str | None = None):
        self.url = url
        self.title = title or url

    async def play(self, vc, callback=None):
        raise NotImplementedError("Subclasses must implement play()")


class YouTubeSong(Song):
    def __init__(self, track: ResolvedTrack):
        super().__init__(track.url, track.title)
        self.player = YouTubePlayer()

    async def play(self, vc, callback=None):
        logger.info(f"Starting YouTube song: {self.title}")
        logger.debug(f"Track URL: {self.url}")
        await self.player.play(vc, self.url, callback=callback)


async def resolve_spotify_tracks_to_youtube(
    spotify_tracks: Sequence[SpotifyTrack],
    youtube_player: YouTubePlayer,
    *,
    concurrency: int = 5,
) -> tuple[list[ResolvedTrack], list[SpotifyTrack]]:
    if not spotify_tracks:
        return [], []

    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _resolve(track: SpotifyTrack) -> ResolvedTrack | None:
        try:
            async with semaphore:
                match = await youtube_player.search(track.search_query)
            if match is None:
                return None
            return ResolvedTrack(title=track.display_title, url=match.url)
        except Exception as exc:
            logger.exception(f"Failed to resolve Spotify track on YouTube ({track.display_title}): {exc}")
            return None

    resolved_candidates = await asyncio.gather(*[_resolve(track) for track in spotify_tracks])

    resolved_tracks: list[ResolvedTrack] = []
    unresolved_tracks: list[SpotifyTrack] = []
    for original_track, candidate in zip(spotify_tracks, resolved_candidates):
        if candidate is None:
            unresolved_tracks.append(original_track)
            continue
        resolved_tracks.append(candidate)

    logger.debug(
        "Spotify->YouTube resolution completed: total={}, resolved={}, unresolved={}",
        len(spotify_tracks),
        len(resolved_tracks),
        len(unresolved_tracks),
    )
    return resolved_tracks, unresolved_tracks


class MusicQueue:
    def __init__(self):
        self.queue_list: deque[Song] = deque()
        self.currently_playing: Song | None = None
        self.youtube_player = YouTubePlayer()
        self._queue_lock = asyncio.Lock()
        self._worker_task: asyncio.Task | None = None
        self._voice_client = None

    async def add_to_queue(self, songs: list[Song], vc):
        if not songs:
            logger.debug("add_to_queue called with empty songs list")
            return

        async with self._queue_lock:
            previous_len = len(self.queue_list)
            self._voice_client = vc
            self.queue_list.extend(songs)
            should_start_worker = self._worker_task is None or self._worker_task.done()
            logger.debug(
                "Queue updated: added={}, previous_len={}, new_len={}, should_start_worker={}",
                len(songs),
                previous_len,
                len(self.queue_list),
                should_start_worker,
            )
            if should_start_worker:
                self._worker_task = asyncio.create_task(self._playback_loop())
                logger.debug("Playback worker task created")

    async def _playback_loop(self):
        logger.debug("Playback loop started")
        while True:
            async with self._queue_lock:
                if not self.queue_list or self._voice_client is None:
                    self.currently_playing = None
                    logger.debug(
                        "Playback loop exiting: queue_empty={}, has_voice_client={}",
                        not self.queue_list,
                        self._voice_client is not None,
                    )
                    return

                song = self.queue_list.popleft()
                vc = self._voice_client
                self.currently_playing = song
                logger.debug(
                    "Dequeued track for playback: title={}, queue_remaining={}",
                    song.title,
                    len(self.queue_list),
                )

            song_finished = asyncio.Event()

            async def mark_finished():
                song_finished.set()

            try:
                if not vc.is_connected():
                    logger.warning("Voice client is no longer connected; clearing playback loop")
                    return
                await song.play(vc, callback=mark_finished)
                await asyncio.wait_for(song_finished.wait(), timeout=3600)
                logger.debug(f"Track completed successfully: {song.title}")
            except asyncio.CancelledError:
                logger.info("Playback loop cancelled")
                raise
            except asyncio.TimeoutError:
                logger.error(f"Playback timed out for {song.title}")
                if vc.is_playing():
                    vc.stop()
            except Exception as exc:
                logger.error(f"Error while playing {song.title}: {exc}", exc_info=True)
            finally:
                self.currently_playing = None
                logger.debug("currently_playing cleared")

    async def skip(self, vc):
        if vc and vc.is_playing():
            vc.stop()
            return True
        return False

    async def teardown(self, vc=None):
        logger.debug("Tearing down music queue state")
        async with self._queue_lock:
            self.queue_list.clear()
            self.currently_playing = None
            worker = self._worker_task
            self._worker_task = None
            if vc is None:
                vc = self._voice_client
            self._voice_client = None

        if worker and not worker.done():
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
            logger.debug("Playback worker cancelled during teardown")

        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            logger.debug("Voice client playback stopped during teardown")

    def snapshot(self) -> list[str]:
        return [song.title for song in self.queue_list]


async def ensure_voice_client(interaction: discord.Interaction):
    if interaction.user.voice is None:
        logger.debug(
            "ensure_voice_client: user has no voice channel (user_id={})",
            getattr(interaction.user, "id", "unknown"),
        )
        await interaction.followup.send("You need to be in a voice channel to use this command.")
        return None

    channel = interaction.user.voice.channel
    vc = interaction.guild.voice_client
    logger.debug(
        "ensure_voice_client called: guild_id={}, user_id={}, target_channel={}, has_existing_vc={}",
        getattr(interaction.guild, "id", "unknown"),
        getattr(interaction.user, "id", "unknown"),
        getattr(channel, "name", "unknown"),
        vc is not None,
    )

    try:
        if vc is not None and not vc.is_connected():
            logger.debug("Existing voice client is disconnected; running cleanup")
            if vc.is_playing() or vc.is_paused():
                vc.stop()
            vc.cleanup()
            vc = None

        if vc is None:
            logger.debug("Connecting to voice channel")
            vc = await channel.connect()
            logger.info(f"Connected to voice channel: {getattr(channel, 'name', 'unknown')}")
        elif vc.channel != channel:
            logger.debug(
                "Moving voice client from channel={} to channel={}",
                getattr(vc.channel, "name", "unknown"),
                getattr(channel, "name", "unknown"),
            )
            await vc.move_to(channel)
            logger.info(f"Moved voice client to: {getattr(channel, 'name', 'unknown')}")
    except Exception as exc:
        if is_voice_dependency_error(exc):
            logger.error(
                "Voice dependency error while connecting to voice. "
                "Required voice backend package is missing in runtime."
            )
            logger.debug(f"Voice dependency exception payload: {exc!r}")
            await interaction.followup.send(
                "Voice is unavailable because required voice backend is missing in runtime "
                "(PyNaCl or davey, depending on discord.py build). "
                "Rebuild the container with --no-cache and verify with: "
                "`python -c \"import discord, discord.voice_client as vc; "
                "print(discord.__version__, vc.__file__, getattr(vc, 'has_nacl', None), "
                "getattr(vc, 'has_davey', None))\"`."
            )
            return None

        logger.exception(f"Failed to connect to voice channel: {exc}")
        await interaction.followup.send(f"Failed to connect to voice channel: {exc}")
        return None

    return vc


def setup_music_commands(bot):
    music_queue = MusicQueue()
    youtube_player = YouTubePlayer()
    spotify_player = SpotifyPlayer()

    @bot.tree.command(name="join", description="Joins a voice channel.")
    async def join(interaction: discord.Interaction):
        logger.debug(
            "Command /join received: guild_id={} user_id={}",
            getattr(interaction.guild, "id", "unknown"),
            getattr(interaction.user, "id", "unknown"),
        )
        await interaction.response.defer(ephemeral=True)
        vc = await ensure_voice_client(interaction)
        if vc is not None:
            await interaction.followup.send(f"Joined {vc.channel.name}.")

    @bot.tree.command(name="leave", description="Leaves the voice channel.")
    async def leave(interaction: discord.Interaction):
        logger.debug(
            "Command /leave received: guild_id={} user_id={}",
            getattr(interaction.guild, "id", "unknown"),
            getattr(interaction.user, "id", "unknown"),
        )
        vc = interaction.guild.voice_client
        if vc:
            await music_queue.teardown(vc)
            if vc.is_connected():
                await vc.disconnect()
            await interaction.response.send_message("Left the voice channel.")
            return
        await interaction.response.send_message("I'm not in a voice channel.")

    @bot.tree.command(name="play", description="Play music from YouTube or a Spotify URL.")
    async def play(interaction: discord.Interaction, url_or_query: str):
        logger.debug(
            "Command /play received: guild_id={} user_id={} input={}",
            getattr(interaction.guild, "id", "unknown"),
            getattr(interaction.user, "id", "unknown"),
            url_or_query,
        )
        await interaction.response.defer()

        vc = await ensure_voice_client(interaction)
        if vc is None:
            return

        if spotify_player.is_spotify_url(url_or_query):
            collection = await spotify_player.resolve_collection(url_or_query)
            if collection is None or not collection.tracks:
                await interaction.followup.send(
                    "No playable tracks were found in the Spotify URL. "
                    "The link may be private, geo-blocked, or blocked by network rules."
                )
                return

            logger.debug(
                "Spotify collection resolved: type={}, name={}, tracks={}",
                collection.source_type,
                collection.source_name,
                len(collection.tracks),
            )
            resolved_tracks, unresolved_tracks = await resolve_spotify_tracks_to_youtube(
                collection.tracks,
                youtube_player,
            )
            if not resolved_tracks:
                await interaction.followup.send(
                    "Spotify tracks were found, but none could be matched on YouTube."
                )
                return

            songs = [YouTubeSong(track) for track in resolved_tracks]
            await music_queue.add_to_queue(songs, vc)

            total = len(collection.tracks)
            added = len(resolved_tracks)
            missing = len(unresolved_tracks)
            if missing == 0:
                await interaction.followup.send(
                    f"Added {added} tracks from Spotify {collection.source_type}: {collection.source_name}"
                )
                return

            await interaction.followup.send(
                f"Added {added}/{total} tracks from Spotify {collection.source_type}: "
                f"{collection.source_name}. Could not match {missing} track(s) on YouTube."
            )
            return

        tracks = await youtube_player.resolve_input(url_or_query)
        if not tracks:
            logger.debug(f"No tracks resolved for input: {url_or_query}")
            await interaction.followup.send("No playable tracks were found.")
            return

        songs = [YouTubeSong(track) for track in tracks]
        await music_queue.add_to_queue(songs, vc)
        logger.debug(f"Tracks added to queue: {len(tracks)}")

        if len(tracks) == 1:
            await interaction.followup.send(f"Added to queue: {tracks[0].title}")
            return

        await interaction.followup.send(
            f"Added {len(tracks)} tracks from playlist: {tracks[0].title}"
        )

    @bot.tree.command(name="skip", description="Skips the current song and plays the next in queue.")
    async def skip(interaction: discord.Interaction):
        logger.debug(
            "Command /skip received: guild_id={} user_id={}",
            getattr(interaction.guild, "id", "unknown"),
            getattr(interaction.user, "id", "unknown"),
        )
        vc = interaction.guild.voice_client
        if await music_queue.skip(vc):
            await interaction.response.send_message("Skipped.")
            return
        await interaction.response.send_message("No song is playing.")

    @bot.tree.command(name="queue", description="Displays the current song queue.")
    async def queue(interaction: discord.Interaction):
        logger.debug(
            "Command /queue received: guild_id={} user_id={}, queue_len={}, has_current={}",
            getattr(interaction.guild, "id", "unknown"),
            getattr(interaction.user, "id", "unknown"),
            len(music_queue.queue_list),
            music_queue.currently_playing is not None,
        )
        if music_queue.currently_playing is None and not music_queue.queue_list:
            await interaction.response.send_message("The queue is empty.")
            return

        lines = []
        if music_queue.currently_playing is not None:
            lines.append(f"Now playing: {music_queue.currently_playing.title}")

        queued = music_queue.snapshot()
        if queued:
            lines.extend(f"{index}. {title}" for index, title in enumerate(queued, start=1))

        await interaction.response.send_message("\n".join(lines))
