from __future__ import annotations

"""Production composition root for the packaged Accessible Chess application."""

import os
from pathlib import Path
from typing import Any, Callable

from .analysis_service import AnalysisService
from .continuous_analysis import ContinuousAnalysisService
from .engine_play_service import EnginePlayService
from .settings import Settings
from .sound_runtime import GameSoundRuntime, SoundRuntime, SoundRuntimeSettings
from .sound_windows import PackagedSoundAssetResolver, WindowsSoundPlaybackAdapter
from .stage1_release_ui import Stage1ReleaseAccessibleChessAPI
from .stockfish_runtime import StockfishRuntime, StockfishRuntimeConfig
from .webapp_keymap import _asset_root

# Compatibility name for callers/tests that imported the old split release API.
# There is now only one concrete release-facing API implementation.
ReleaseAccessibleChessAPI = Stage1ReleaseAccessibleChessAPI


def _user_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    return Path(local) / "AccessibleChess" if local else Path.home() / ".accessible-chess"


def _sound_cache_dir() -> Path:
    return _user_root() / "sound-cache"


def _settings_path() -> Path:
    return _user_root() / "settings.json"


def _sound_variant_provider(settings: Settings, sound_assets: PackagedSoundAssetResolver):
    """Return the one fail-safe persisted variant selector used by Stage 1 and V2."""

    def selected_sound_variant(event):
        choice = str(settings.get(f"sound_{event.value}_variant", "1"))
        try:
            available = {
                option.variant_id for option in sound_assets.variants_for(event)
            }
        except Exception:
            return "1"
        return choice if choice in available else "1"

    return selected_sound_variant


def create_release_api(
    *,
    application_dir: str | Path | None = None,
    runtime_factory: Callable[[StockfishRuntimeConfig], Any] = StockfishRuntime,
    sound_playback: Any | None = None,
    settings_path: str | Path | None = None,
):
    """Compose one shared Stockfish provider, persisted settings and sound runtime.

    The same returned ``Stage1ReleaseAccessibleChessAPI`` is used by the actual
    packaged WebView launcher. Tests can inject an engine runtime and playback
    port without creating a second product composition path.
    """
    app_dir = Path(application_dir) if application_dir is not None else _asset_root()
    runtime = runtime_factory(StockfishRuntimeConfig(application_dir=app_dir))
    analysis = AnalysisService(runtime.provider, owns_engine=False)
    continuous = ContinuousAnalysisService(analysis)
    engine_play = EnginePlayService(runtime.provider, owns_engine=False)

    settings = Settings(Path(settings_path) if settings_path is not None else _settings_path())
    sound_assets = PackagedSoundAssetResolver(app_dir)
    selected_sound_variant = _sound_variant_provider(settings, sound_assets)

    playback = sound_playback
    if playback is None:
        playback = WindowsSoundPlaybackAdapter(
            sound_assets,
            cache_dir=_sound_cache_dir(),
            variant_provider=selected_sound_variant,
        )
    sound_runtime = SoundRuntime(
        playback,
        settings=lambda: SoundRuntimeSettings.from_mapping(settings.data),
    )
    game_sounds = GameSoundRuntime(sound_runtime)

    api = Stage1ReleaseAccessibleChessAPI(
        continuous_analysis=continuous,
        game_sounds=game_sounds,
        sound_runtime=sound_runtime,
        settings=settings,
        sound_asset_resolver=sound_assets,
        engine_play_service=engine_play,
    )
    return api, runtime


def main() -> None:
    # Kept as a public entry point for compatibility. The actual launcher uses
    # stage1_release_ui.main, which calls this same composition factory.
    from .stage1_release_ui import run_release_window

    api, runtime = create_release_api()
    run_release_window(api, runtime)
