from __future__ import annotations

"""Production composition root for the packaged Accessible Chess application."""

from pathlib import Path
from typing import Any, Callable

from .analysis_service import AnalysisService
from .continuous_analysis import ContinuousAnalysisService
from .stockfish_runtime import StockfishRuntime, StockfishRuntimeConfig
from .webapp_keymap import KeymapAwareAccessibleChessAPI, _asset_root
from .ui_native_menu import make_keymap_menu


def create_release_api(
    *,
    application_dir: str | Path | None = None,
    runtime_factory: Callable[[StockfishRuntimeConfig], Any] = StockfishRuntime,
):
    """Compose one application-owned Stockfish provider and the semantic UI API."""
    app_dir = Path(application_dir) if application_dir is not None else _asset_root()
    runtime = runtime_factory(StockfishRuntimeConfig(application_dir=app_dir))
    analysis = AnalysisService(runtime.provider, owns_engine=False)
    continuous = ContinuousAnalysisService(analysis)
    api = KeymapAwareAccessibleChessAPI(continuous_analysis=continuous)
    return api, runtime


def main() -> None:
    import webview

    api, runtime = create_release_api()
    window_holder: dict[str, Any] = {}
    html = _asset_root() / "web" / "index.html"
    if not html.exists():
        runtime.close()
        raise RuntimeError(f"Accessible HTML UI not found: {html}")
    menu = make_keymap_menu(webview, api, window_holder)
    window = webview.create_window(
        "Accessible Chess — 0.4 NVDA architecture",
        url=str(html),
        js_api=api,
        width=1150,
        height=820,
        min_size=(800, 600),
        text_select=True,
        menu=menu,
    )
    window_holder["window"] = window
    try:
        webview.start(gui="edgechromium", private_mode=True)
    finally:
        try:
            api.close_analysis()
        finally:
            runtime.close()
