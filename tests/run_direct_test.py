import asyncio
import sys
import types

# Insert a fake loguru with a simple logger to avoid external dependency during tests
fake_loguru = types.ModuleType("loguru")
class SimpleLogger:
    def info(self, *args, **kwargs):
        print("INFO:", *args)
    def error(self, *args, **kwargs):
        print("ERROR:", *args)
    def warning(self, *args, **kwargs):
        print("WARNING:", *args)
    def debug(self, *args, **kwargs):
        print("DEBUG:", *args)

fake_loguru.logger = SimpleLogger()
sys.modules['loguru'] = fake_loguru

# Now import the modules under test
import importlib.util
import pathlib

# Load modules by file path to avoid package/import issues in test environment
root = pathlib.Path(__file__).resolve().parents[1]
controllers_path = root / 'controllers' / 'music_controller.py'
youtube_player_path = root / 'models' / 'youtube_player.py'
views_path = root / 'views' / 'music_view.py'

# Insert a fake minimal `discord` package to avoid importing the real dependency
fake_discord = types.ModuleType("discord")
fake_discord.app_commands = types.SimpleNamespace()
fake_discord.ext = types.SimpleNamespace()
fake_discord.ext.commands = types.SimpleNamespace(Bot=lambda *a, **k: None, Cog=object, Context=object)
fake_discord.ui = types.SimpleNamespace(View=object, Button=object, ButtonStyle=types.SimpleNamespace(primary=1, success=2, danger=3))
# Provide a `button` decorator equivalent used in views.music_view
def _fake_button(*args, **kwargs):
    def _decorator(func):
        return func
    return _decorator
fake_discord.ui.button = _fake_button
fake_discord.ButtonStyle = fake_discord.ui.ButtonStyle
fake_discord.FFmpegPCMAudio = lambda *a, **k: object()
fake_discord.Interaction = object
fake_discord.Member = object
sys.modules['discord'] = fake_discord
sys.modules['discord.app_commands'] = fake_discord.app_commands
sys.modules['discord.ext'] = fake_discord.ext
sys.modules['discord.ext.commands'] = fake_discord.ext.commands
sys.modules['discord.ui'] = fake_discord.ui

spec2 = importlib.util.spec_from_file_location('models.youtube_player', str(youtube_player_path))
youtube_mod = importlib.util.module_from_spec(spec2)
sys.modules['models.youtube_player'] = youtube_mod
spec2.loader.exec_module(youtube_mod)

spec3 = importlib.util.spec_from_file_location('views.music_view', str(views_path))
views_mod = importlib.util.module_from_spec(spec3)
sys.modules['views.music_view'] = views_mod
spec3.loader.exec_module(views_mod)

spec = importlib.util.spec_from_file_location('controllers.music_controller', str(controllers_path))
controllers = importlib.util.module_from_spec(spec)
sys.modules['controllers.music_controller'] = controllers
spec.loader.exec_module(controllers)

MusicQueue = controllers.MusicQueue
YouTubeSong = controllers.YouTubeSong
ResolvedTrack = youtube_mod.ResolvedTrack
YouTubePlayer = youtube_mod.YouTubePlayer

async def run_test():
    mq = MusicQueue()

    class FakeVC:
        def is_connected(self):
            return True

        def is_playing(self):
            return False

        def is_paused(self):
            return False

        def stop(self):
            return None

    vc = FakeVC()

    played = []

    async def fake_play(self, vc_arg, url, callback=None):
        print(f"fake_play called with url={url}")
        played.append(url)
        await asyncio.sleep(0)
        if callback:
            await callback()

    # Monkeypatch
    YouTubePlayer.play = fake_play

    song = YouTubeSong(ResolvedTrack(title="test", url="https://youtu.be/test_video"))
    await mq.add_to_queue([song], vc)

    await asyncio.wait_for(mq._worker_task, timeout=1)

    if played == ["https://youtu.be/test_video"]:
        print("TEST PASSED: song was played")
        return 0
    else:
        print("TEST FAILED: played list:", played)
        return 2

if __name__ == '__main__':
    code = asyncio.run(run_test())
    sys.exit(code)
