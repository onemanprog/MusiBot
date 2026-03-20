"""Tests for lazy-loading music queue system.

Tests the efficient handling of large playlists (3000+ songs) without
excessive memory usage or rendering delays.
"""

import asyncio
import random
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from controllers.music_controller import (
    LazyResolvingSong,
    MusicQueue,
    YouTubeSong,
    create_lazy_resolving_songs,
)
from models.spotify_player import SpotifyTrack
from models.youtube_player import ResolvedTrack


class TestLazyResolvingSong:
    """Test suite for LazyResolvingSong class."""

    @pytest.fixture
    def spotify_track(self):
        """Create a test Spotify track."""
        return SpotifyTrack(
            title="Test Song",
            artists=("Artist One", "Artist Two"),
        )

    @pytest.fixture
    def mock_youtube_player(self):
        """Create a mock YouTube player."""
        player = MagicMock()
        player.search = AsyncMock()
        player.play = AsyncMock()
        return player

    def test_lazy_song_initialization(self, spotify_track, mock_youtube_player):
        """Test that LazyResolvingSong initializes correctly."""
        song = LazyResolvingSong(spotify_track, mock_youtube_player)
        
        assert song.title == "Test Song - Artist One, Artist Two"
        assert song.requested_query == "Test Song Artist One Artist Two"
        assert song.url == ""
        assert not song._is_resolved
        assert song._resolved_url is None

    @pytest.mark.asyncio
    async def test_lazy_song_resolution_success(self, spotify_track, mock_youtube_player):
        """Test successful resolution of a lazy song."""
        mock_youtube_player.search.return_value = MagicMock(
            url="https://www.youtube.com/watch?v=test",
            title="Test Song - Artist One, Artist Two",
        )
        
        song = LazyResolvingSong(spotify_track, mock_youtube_player)
        result = await song.resolve()
        
        assert result is True
        assert song._is_resolved
        assert song._resolved_url == "https://www.youtube.com/watch?v=test"
        assert song.url == "https://www.youtube.com/watch?v=test"
        mock_youtube_player.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_lazy_song_resolution_failure(self, spotify_track, mock_youtube_player):
        """Test resolution failure when no match found."""
        mock_youtube_player.search.return_value = None
        
        song = LazyResolvingSong(spotify_track, mock_youtube_player)
        result = await song.resolve()
        
        assert result is False
        assert song._is_resolved
        assert song._resolved_url is None

    @pytest.mark.asyncio
    async def test_lazy_song_resolution_caching(self, spotify_track, mock_youtube_player):
        """Test that resolution result is cached."""
        mock_youtube_player.search.return_value = MagicMock(
            url="https://www.youtube.com/watch?v=test"
        )
        
        song = LazyResolvingSong(spotify_track, mock_youtube_player)
        
        # First resolution
        result1 = await song.resolve()
        assert result1 is True
        
        # Second resolution should use cache
        result2 = await song.resolve()
        assert result2 is True
        
        # Should only be called once
        assert mock_youtube_player.search.call_count == 1

    @pytest.mark.asyncio
    async def test_lazy_song_play_unresolved(self, spotify_track, mock_youtube_player):
        """Test playing an unresolved song resolves it first."""
        mock_youtube_player.search.return_value = MagicMock(
            url="https://www.youtube.com/watch?v=test"
        )
        
        song = LazyResolvingSong(spotify_track, mock_youtube_player)
        mock_vc = MagicMock()
        
        await song.play(mock_vc)
        
        # Should have called search to resolve
        mock_youtube_player.search.assert_called()
        # Should have called play with the resolved URL
        mock_youtube_player.play.assert_called_once_with(
            mock_vc,
            "https://www.youtube.com/watch?v=test",
            callback=None,
        )

    @pytest.mark.asyncio
    async def test_lazy_song_play_fails_if_resolution_fails(self, spotify_track, mock_youtube_player):
        """Test that play raises error if resolution fails."""
        mock_youtube_player.search.return_value = None
        
        song = LazyResolvingSong(spotify_track, mock_youtube_player)
        mock_vc = MagicMock()
        
        with pytest.raises(RuntimeError, match="Failed to resolve track"):
            await song.play(mock_vc)


class TestCreateLazyResolvingSongs:
    """Test suite for create_lazy_resolving_songs helper function."""

    @pytest.fixture
    def mock_youtube_player(self):
        """Create a mock YouTube player."""
        return MagicMock()

    def test_create_lazy_songs_from_tracks(self, mock_youtube_player):
        """Test creating lazy songs from Spotify tracks."""
        tracks = [
            SpotifyTrack(title=f"Song {i}", artists=(f"Artist {i}",))
            for i in range(10)
        ]
        
        songs = create_lazy_resolving_songs(tracks, mock_youtube_player)
        
        assert len(songs) == 10
        assert all(isinstance(song, LazyResolvingSong) for song in songs)
        assert songs[0].title == "Song 0 - Artist 0"

    def test_create_empty_lazy_songs(self, mock_youtube_player):
        """Test creating lazy songs from empty list."""
        songs = create_lazy_resolving_songs([], mock_youtube_player)
        assert len(songs) == 0


class TestMusicQueueLazyLoading:
    """Test suite for MusicQueue lazy loading functionality."""

    @pytest.fixture
    def mock_youtube_player(self):
        """Create a mock YouTube player."""
        player = MagicMock()
        player.search = AsyncMock()
        player.play = AsyncMock()
        return player

    @pytest.fixture
    def music_queue(self, mock_youtube_player):
        """Create a MusicQueue with mocked YouTube player."""
        queue = MusicQueue(batch_preload_size=20)
        queue.youtube_player = mock_youtube_player
        return queue

    @pytest.mark.asyncio
    async def test_add_lazy_songs_to_queue(self, music_queue, mock_youtube_player):
        """Test adding lazy songs to the queue."""
        tracks = [
            SpotifyTrack(title=f"Song {i}", artists=(f"Artist {i}",))
            for i in range(100)
        ]
        lazy_songs = create_lazy_resolving_songs(tracks, mock_youtube_player)
        
        mock_vc = MagicMock()
        await music_queue.add_to_queue(lazy_songs, mock_vc)
        
        assert len(music_queue.queue_list) == 100
        assert music_queue._total_unresolved_songs == 100
        assert all(isinstance(song, LazyResolvingSong) for song in music_queue.queue_list)

    @pytest.mark.asyncio
    async def test_shuffle_preserves_all_songs(self, music_queue, mock_youtube_player):
        """Test that shuffle handles all songs correctly."""
        # Create a large playlist (3000 songs)
        tracks = [
            SpotifyTrack(title=f"Song {i}", artists=(f"Artist {i}",))
            for i in range(3000)
        ]
        lazy_songs = create_lazy_resolving_songs(tracks, mock_youtube_player)
        
        mock_vc = MagicMock()
        await music_queue.add_to_queue(lazy_songs, mock_vc)
        
        # Shuffle
        shuffled_count = await music_queue.shuffle_queue()
        
        assert shuffled_count == 3000
        assert len(music_queue.queue_list) == 3000
        assert all(isinstance(song, LazyResolvingSong) for song in music_queue.queue_list)

    @pytest.mark.asyncio
    async def test_shuffle_randomizes_order(self, music_queue, mock_youtube_player):
        """Test that shuffle actually randomizes the queue order."""
        tracks = [
            SpotifyTrack(title=f"Song {i}", artists=(f"Artist {i}",))
            for i in range(100)
        ]
        lazy_songs = create_lazy_resolving_songs(tracks, mock_youtube_player)
        original_order = [song.title for song in lazy_songs]
        
        mock_vc = MagicMock()
        await music_queue.add_to_queue(lazy_songs, mock_vc)
        
        await music_queue.shuffle_queue()
        shuffled_order = [song.title for song in music_queue.queue_list]
        
        # Very unlikely to be in same order after shuffle
        assert original_order != shuffled_order
        # But should have all the same songs
        assert sorted(original_order) == sorted(shuffled_order)

    @pytest.mark.asyncio
    async def test_preload_task_resolves_lazy_songs(self, music_queue, mock_youtube_player):
        """Test that preload task resolves upcoming songs."""
        mock_youtube_player.search.return_value = MagicMock(
            url="https://www.youtube.com/watch?v=test",
            title="Resolved Song",
        )
        
        tracks = [
            SpotifyTrack(title=f"Song {i}", artists=(f"Artist {i}",))
            for i in range(50)
        ]
        lazy_songs = create_lazy_resolving_songs(tracks, mock_youtube_player)
        
        mock_vc = MagicMock()
        await music_queue.add_to_queue(lazy_songs, mock_vc)
        
        # Let preload task run
        await asyncio.sleep(0.5)
        
        # Check that some songs have been pre-resolved
        resolved_count = sum(1 for s in music_queue.queue_list if s._is_resolved)
        assert resolved_count > 0
        assert resolved_count <= 10  # Should have resolved some but not all

    @pytest.mark.asyncio
    async def test_large_playlist_3000_songs(self, music_queue, mock_youtube_player):
        """Test handling of very large playlist (3000 songs)."""
        tracks = [
            SpotifyTrack(title=f"Song {i}", artists=(f"Artist {i}",))
            for i in range(3000)
        ]
        lazy_songs = create_lazy_resolving_songs(tracks, mock_youtube_player)
        
        mock_vc = MagicMock()
        await music_queue.add_to_queue(lazy_songs, mock_vc)
        
        # Should handle adding without memory issues
        assert len(music_queue.queue_list) == 3000
        assert music_queue._total_unresolved_songs == 3000

    @pytest.mark.asyncio
    async def test_shuffle_with_3000_songs(self, music_queue, mock_youtube_player):
        """Test shuffling a large 3000-song playlist."""
        tracks = [
            SpotifyTrack(title=f"Song {i:04d}", artists=(f"Artist {i}",))
            for i in range(3000)
        ]
        lazy_songs = create_lazy_resolving_songs(tracks, mock_youtube_player)
        original_titles = [song.title for song in lazy_songs]
        
        mock_vc = MagicMock()
        await music_queue.add_to_queue(lazy_songs, mock_vc)
        
        # Shuffle 3000 items shouldn't take long
        import time
        start = time.time()
        await music_queue.shuffle_queue()
        elapsed = time.time() - start
        
        shuffled_titles = [song.title for song in music_queue.queue_list]
        
        # Verify shuffle worked
        assert original_titles != shuffled_titles
        assert sorted(original_titles) == sorted(shuffled_titles)
        # Shuffle should be fast (< 1 second for 3000 items)
        assert elapsed < 1.0

    @pytest.mark.asyncio
    async def test_mixed_lazy_and_resolved_songs(self, music_queue, mock_youtube_player):
        """Test queue with both lazy and immediately resolved songs."""
        # Create some resolved songs
        resolved_tracks = [
            ResolvedTrack(
                title=f"Resolved Song {i}",
                url=f"https://www.youtube.com/watch?v={i}",
                search_query=f"Song {i}",
            )
            for i in range(10)
        ]
        resolved_songs = [YouTubeSong(track) for track in resolved_tracks]
        
        # Create lazy songs
        spotify_tracks = [
            SpotifyTrack(title=f"Lazy Song {i}", artists=(f"Artist {i}",))
            for i in range(40)
        ]
        lazy_songs = create_lazy_resolving_songs(spotify_tracks, mock_youtube_player)
        
        # Add all to queue
        mock_vc = MagicMock()
        all_songs = resolved_songs + lazy_songs
        await music_queue.add_to_queue(all_songs, mock_vc)
        
        assert len(music_queue.queue_list) == 50
        assert music_queue._total_unresolved_songs == 40

    @pytest.mark.asyncio
    async def test_snapshot_with_lazy_songs(self, music_queue, mock_youtube_player):
        """Test the snapshot method with lazy songs."""
        tracks = [
            SpotifyTrack(title=f"Song {i}", artists=(f"Artist {i}",))
            for i in range(100)
        ]
        lazy_songs = create_lazy_resolving_songs(tracks, mock_youtube_player)
        
        mock_vc = MagicMock()
        await music_queue.add_to_queue(lazy_songs, mock_vc)
        
        # Get snapshot
        snapshot = music_queue.snapshot(limit=20)
        
        assert len(snapshot) == 20
        assert all("Song" in title for title in snapshot)

    @pytest.mark.asyncio
    async def test_teardown_cancels_preload(self, music_queue, mock_youtube_player):
        """Test that teardown properly cancels preload task."""
        tracks = [
            SpotifyTrack(title=f"Song {i}", artists=(f"Artist {i}",))
            for i in range(100)
        ]
        lazy_songs = create_lazy_resolving_songs(tracks, mock_youtube_player)
        
        mock_vc = MagicMock()
        await music_queue.add_to_queue(lazy_songs, mock_vc)
        
        # Let preload task start
        await asyncio.sleep(0.1)
        
        # Teardown
        await music_queue.teardown()
        
        assert len(music_queue.queue_list) == 0
        assert music_queue._total_unresolved_songs == 0
        assert music_queue._preload_task is None


class TestMemoryEfficiency:
    """Test suite for memory efficiency with large playlists."""

    @pytest.mark.asyncio
    async def test_lazy_loading_memory_efficient(self):
        """Test that lazy loading uses minimal memory compared to eager loading.
        
        This is a conceptual test - in a real scenario, you'd use memory_profiler
        to verify actual memory usage.
        """
        # Create 3000 lazy songs
        tracks = [
            SpotifyTrack(title=f"Song {i}", artists=(f"Artist {i}",))
            for i in range(3000)
        ]
        
        mock_player = MagicMock()
        lazy_songs = create_lazy_resolving_songs(tracks, mock_player)
        
        queue = MusicQueue()
        mock_vc = MagicMock()
        
        # Should be able to handle 3000 songs without issues
        await queue.add_to_queue(lazy_songs, mock_vc)
        
        # Shuffle all 3000
        await queue.shuffle_queue()
        
        # Should still be able to snapshot
        snapshot = queue.snapshot(limit=50)
        assert len(snapshot) == 50


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
