import asyncio

import pytest

from controllers.music_controller import resolve_spotify_tracks_to_youtube
from models.spotify_player import SpotifyTrack
from models.youtube_player import ResolvedTrack


@pytest.mark.asyncio
async def test_resolve_spotify_tracks_to_youtube_preserves_order_and_reports_missing():
    spotify_tracks = (
        SpotifyTrack(title="First Song", artists=("First Artist",)),
        SpotifyTrack(title="Second Song", artists=("Second Artist",)),
        SpotifyTrack(title="Third Song", artists=("Third Artist",)),
    )

    class FakeYouTubePlayer:
        async def search(self, query):
            if query == "First Song First Artist":
                await asyncio.sleep(0.02)
                return ResolvedTrack(title="yt-first", url="https://youtu.be/first")
            if query == "Second Song Second Artist":
                return None
            if query == "Third Song Third Artist":
                await asyncio.sleep(0.01)
                return ResolvedTrack(title="yt-third", url="https://youtu.be/third")
            raise AssertionError(f"Unexpected search query: {query}")

    resolved, unresolved = await resolve_spotify_tracks_to_youtube(
        spotify_tracks,
        FakeYouTubePlayer(),
        concurrency=2,
    )

    assert resolved == [
        ResolvedTrack(title="First Song - First Artist", url="https://youtu.be/first"),
        ResolvedTrack(title="Third Song - Third Artist", url="https://youtu.be/third"),
    ]
    assert unresolved == [SpotifyTrack(title="Second Song", artists=("Second Artist",))]
