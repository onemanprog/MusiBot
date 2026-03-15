import asyncio

from controllers.music_controller import MusicQueue, YouTubeSong
from models.youtube_player import ResolvedTrack, YouTubePlayer


def test_queue_triggers_play(monkeypatch):
    async def _run_test():
        queue = MusicQueue()

        class FakeVC:
            def is_connected(self):
                return True

            def is_playing(self):
                return False

            def is_paused(self):
                return False

            def stop(self):
                return None

        played = []

        async def fake_play(self, vc_arg, url, callback=None):
            played.append(url)
            await asyncio.sleep(0)
            if callback:
                await callback()

        monkeypatch.setattr(YouTubePlayer, "play", fake_play)

        song = YouTubeSong(ResolvedTrack(title="test", url="https://youtu.be/test_video"))
        await queue.add_to_queue([song], FakeVC())
        await asyncio.wait_for(queue._worker_task, timeout=1)

        assert played == ["https://youtu.be/test_video"]

    asyncio.run(_run_test())
