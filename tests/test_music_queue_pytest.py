import asyncio

import pytest

from controllers.music_controller import MusicQueue, YouTubeSong
from models.youtube_player import ResolvedTrack, YouTubePlayer


class FakeVoiceClient:
    def __init__(self):
        self.stopped = False

    def is_connected(self):
        return True

    def is_playing(self):
        return False

    def is_paused(self):
        return False

    def stop(self):
        self.stopped = True


@pytest.mark.asyncio
async def test_queue_plays_tracks_sequentially(monkeypatch):
    queue = MusicQueue()
    vc = FakeVoiceClient()
    played_urls = []

    async def fake_play(self, vc_arg, url, callback=None):
        played_urls.append(url)
        await asyncio.sleep(0)
        if callback:
            await callback()

    monkeypatch.setattr(YouTubePlayer, "play", fake_play)

    songs = [
        YouTubeSong(ResolvedTrack(title="first", url="https://youtu.be/first")),
        YouTubeSong(ResolvedTrack(title="second", url="https://youtu.be/second")),
    ]

    await queue.add_to_queue(songs, vc)
    await asyncio.wait_for(queue._worker_task, timeout=1)

    assert played_urls == ["https://youtu.be/first", "https://youtu.be/second"]
    assert queue.currently_playing is None
    assert queue.snapshot() == []


@pytest.mark.asyncio
async def test_queue_starts_single_worker_for_concurrent_adds(monkeypatch):
    queue = MusicQueue()
    vc = FakeVoiceClient()
    played_urls = []

    async def fake_play(self, vc_arg, url, callback=None):
        played_urls.append(url)
        await asyncio.sleep(0)
        if callback:
            await callback()

    monkeypatch.setattr(YouTubePlayer, "play", fake_play)

    first = [YouTubeSong(ResolvedTrack(title="one", url="https://youtu.be/one"))]
    second = [YouTubeSong(ResolvedTrack(title="two", url="https://youtu.be/two"))]

    await asyncio.gather(
        queue.add_to_queue(first, vc),
        queue.add_to_queue(second, vc),
    )
    await asyncio.wait_for(queue._worker_task, timeout=1)

    assert played_urls == ["https://youtu.be/one", "https://youtu.be/two"]


@pytest.mark.asyncio
async def test_skip_stops_active_voice_client():
    queue = MusicQueue()

    class PlayingVoiceClient(FakeVoiceClient):
        def is_playing(self):
            return True

    vc = PlayingVoiceClient()

    skipped = await queue.skip(vc)

    assert skipped is True
    assert vc.stopped is True
