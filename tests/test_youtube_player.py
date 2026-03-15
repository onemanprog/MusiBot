import pytest

from models.youtube_player import ResolvedTrack, YouTubePlayer


@pytest.fixture
def yt_player():
    return YouTubePlayer()


def test_is_valid_youtube_url(yt_player):
    assert yt_player.is_youtube_url("https://www.youtube.com/watch?v=test123")
    assert yt_player.is_youtube_url("https://youtu.be/test123")
    assert not yt_player.is_youtube_url("https://example.com/video")


def test_is_playlist_url(yt_player):
    assert yt_player.is_playlist_url("https://www.youtube.com/playlist?list=abc123")
    assert yt_player.is_playlist_url("https://www.youtube.com/watch?v=test123&list=abc123")
    assert not yt_player.is_playlist_url("https://youtu.be/test123")


def test_track_from_entry_normalizes_watch_url(yt_player):
    track = yt_player._track_from_entry({"title": "Song", "url": "/watch?v=abc123"})
    assert track == ResolvedTrack(title="Song", url="https://www.youtube.com/watch?v=abc123")


@pytest.mark.asyncio
async def test_resolve_input_routes_search(monkeypatch, yt_player):
    async def fake_search(query):
        assert query == "best song"
        return ResolvedTrack(title="Song", url="https://youtu.be/found")

    monkeypatch.setattr(yt_player, "search", fake_search)

    tracks = await yt_player.resolve_input("best song")

    assert tracks == [ResolvedTrack(title="Song", url="https://youtu.be/found")]


@pytest.mark.asyncio
async def test_resolve_input_routes_playlist(monkeypatch, yt_player):
    async def fake_extract_playlist(url):
        assert "list=abc123" in url
        return [ResolvedTrack(title="Playlist song", url="https://youtu.be/playlist")]

    monkeypatch.setattr(yt_player, "extract_playlist", fake_extract_playlist)

    tracks = await yt_player.resolve_input("https://www.youtube.com/watch?v=test123&list=abc123")

    assert tracks == [ResolvedTrack(title="Playlist song", url="https://youtu.be/playlist")]
