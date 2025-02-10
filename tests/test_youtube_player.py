import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from collections import deque
from models.youtube_player import YouTubePlayer

@pytest.fixture
def yt_player():
    """Fixture for creating a YouTubePlayer instance."""
    return YouTubePlayer()

@pytest.fixture
def mock_ctx():
    """Mock Discord context object."""
    ctx = MagicMock()
    ctx.voice_client = MagicMock()
    ctx.send = AsyncMock()
    return ctx

@pytest.mark.asyncio
async def test_add_to_queue(yt_player):
    """Test if songs are added to queue correctly."""
    await yt_player.add_to_queue("https://www.youtube.com/watch?v=test123")
    assert len(yt_player.queue) == 1
    assert yt_player.queue[0] == "https://www.youtube.com/watch?v=test123"

def test_is_valid_youtube_url(yt_player):
    """Test YouTube URL validation."""
    assert yt_player.is_valid_youtube_url("https://www.youtube.com/watch?v=test123")
    assert yt_player.is_valid_youtube_url("https://youtu.be/test123")
    assert not yt_player.is_valid_youtube_url("https://example.com/video")

@pytest.mark.asyncio
async def test_print_queue(yt_player, mock_ctx):
    """Test queue printing output."""
    await yt_player.add_to_queue("https://www.youtube.com/watch?v=test123")
    await yt_player.print_queue(mock_ctx)
    mock_ctx.send.assert_called_once_with("🎵 Queue:\nhttps://www.youtube.com/watch?v=test123")

@pytest.mark.asyncio
async def test_process_queue_empty(yt_player, mock_ctx):
    """Test behavior when queue is empty."""
    await yt_player.process_queue(mock_ctx)
    mock_ctx.send.assert_called_once_with("🎵 Queue is empty.")

@pytest.mark.asyncio
async def test_process_queue_with_songs(yt_player, mock_ctx, monkeypatch):
    """Test playing a song from the queue."""
    await yt_player.add_to_queue("https://www.youtube.com/watch?v=test123")

    # Mocking yt_dlp
    async def mock_extract_info(*args, **kwargs):
        return {"url": "https://audio.url", "title": "Test Song"}

    monkeypatch.setattr("yt_dlp.YoutubeDL.extract_info", mock_extract_info)

    # Mocking Discord voice client
    mock_ctx.voice_client.play = MagicMock()

    await yt_player.process_queue(mock_ctx)
    assert yt_player.currently_playing == "https://www.youtube.com/watch?v=test123"
    mock_ctx.voice_client.play.assert_called_once()

@pytest.mark.asyncio
async def test_skip(yt_player, mock_ctx):
    """Test skipping the current song."""
    mock_ctx.voice_client.is_playing.return_value = True
    mock_ctx.voice_client.stop = MagicMock()

    await yt_player.skip(mock_ctx)
    mock_ctx.voice_client.stop.assert_called_once()
    mock_ctx.send.assert_called_once_with("⏩ Skipped!")

@pytest.mark.asyncio
async def test_stop(yt_player, mock_ctx):
    """Test stopping playback and clearing the queue."""
    await yt_player.add_to_queue("https://www.youtube.com/watch?v=test123")
    mock_ctx.voice_client.stop = MagicMock()

    await yt_player.stop(mock_ctx)
    mock_ctx.voice_client.stop.assert_called_once()
    assert len(yt_player.queue) == 0
    mock_ctx.send.assert_called_once_with("🛑 Stopped playback and cleared the queue.")
