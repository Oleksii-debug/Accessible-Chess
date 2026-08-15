from __future__ import annotations

"""Production composition root for the packaged Accessible Chess application."""

import os
from pathlib import Path
from typing import Any, Callable

from .analysis_service import AnalysisService
from .continuous_analysis import ContinuousAnalysisService
from .sound_events import MoveSoundFacts
from .sound_runtime import GameSoundRuntime, SoundRuntime, SoundRuntimeSettings
from .sound_windows import PackagedSoundAssetResolver, WindowsSoundPlaybackAdapter
from .stockfish_runtime import StockfishRuntime, StockfishRuntimeConfig
from .ui_native_menu import install_windows_native_menu
from .webapp_keymap import KeymapAwareAccessibleChessAPI, _asset_root


class ReleaseAccessibleChessAPI(KeymapAwareAccessibleChessAPI):
    """Release API with real semantic chess-sound delivery.

    Sound playback is intentionally composed here, outside chess/domain code.
    The API compares the move list before/after a user action so selecting a
    square never produces a false move sound. Illegal attempts emit only the
    semantic illegal event.
    """

    def __init__(self, *args: Any, game_sounds: GameSoundRuntime | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._game_sounds = game_sounds

    def _play_latest_move(self) -> None:
        if self._game_sounds is None or not self.sans:
            return
        san = str(self.sans[-1])
        facts = MoveSoundFacts(
            legal=True,
            capture="x" in san,
            check=("+" in san or "#" in san),
            castle=san.startswith("O-O"),
            promotion="=" in san,
            game_ended=not bool(self.board.legal_moves()),
        )
        self._game_sounds.move(facts)

    def new_game(self) -> dict[str, Any]:
        result = super().new_game()
        if result.get("ok") and self._game_sounds is not None:
            self._game_sounds.start()
        return result

    def make_move(self, text: str) -> dict[str, Any]:
        before = len(self.sans)
        result = super().make_move(text)
        after = len(self.sans)
        if self._game_sounds is not None:
            if result.get("ok") and after > before:
                self._play_latest_move()
            elif not result.get("ok"):
                self._game_sounds.illegal()
        return result

    def activate_square(self, square: str) -> dict[str, Any]:
        before = len(self.sans)
        result = super().activate_square(square)
        after = len(self.sans)
        if self._game_sounds is not None:
            if result.get("ok") and after > before:
                self._play_latest_move()
            elif not result.get("ok"):
                self._game_sounds.illegal()
        return result


def _sound_cache_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / ".accessible-chess"
    return base / "AccessibleChess" / "sound-cache"


def create_release_api(
    *,
    application_dir: str | Path | None = None,
    runtime_factory: Callable[[StockfishRuntimeConfig], Any] = StockfishRuntime,
):
    """Compose one shared Stockfish provider plus packaged sound playback."""
    app_dir = Path(application_dir) if application_dir is not None else _asset_root()
    runtime = runtime_factory(StockfishRuntimeConfig(application_dir=app_dir))
    analysis = AnalysisService(runtime.provider, owns_engine=False)
    continuous = ContinuousAnalysisService(analysis)

    sound_adapter = WindowsSoundPlaybackAdapter(
        PackagedSoundAssetResolver(app_dir),
        cache_dir=_sound_cache_dir(),
    )
    sound_runtime = SoundRuntime(sound_adapter, settings=SoundRuntimeSettings(enabled=True, volume=80))
    game_sounds = GameSoundRuntime(sound_runtime)

    api = ReleaseAccessibleChessAPI(continuous_analysis=continuous, game_sounds=game_sounds)
    return api, runtime


def main() -> None:
    import webview

    api, runtime = create_release_api()
    html = _asset_root() / "web" / "index.html"
    if not html.exists():
        runtime.close()
        raise RuntimeError(f"Accessible HTML UI not found: {html}")

    window = webview.create_window(
        "Accessible Chess",
        url=str(html),
        js_api=api,
        width=1150,
        height=820,
        min_size=(800, 600),
        text_select=True,
    )

    def install_native_menu() -> None:
        if not install_windows_native_menu(window, api):
            raise RuntimeError("Native Windows Alt menu could not be installed")

    try:
        webview.start(install_native_menu, gui="edgechromium", private_mode=True)
    finally:
        try:
            api.close_analysis()
        finally:
            runtime.close()
