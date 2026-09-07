import json
import sys

from acs.webview2_accessibility import enable_webview2_renderer_accessibility
from acs.webview_safe_server import install_pywebview_safe_local_server_port


# Renderer accessibility must be enabled before pywebview/WebView2 is imported.
enable_webview2_renderer_accessibility()


if "--diagnostic" in sys.argv:
    # Automated evidence only. Human NVDA verification remains Oleksii-only on
    # the exact packaged candidate and is never inferred from this diagnostic.
    from collections.abc import Mapping
    from tempfile import TemporaryDirectory

    from acs.selftest import run as core_run
    from acs.stage1_release_ui import complete_user_flow_diagnostic
    from acs.version2_profile import VERSION2_ROUTE_IDS, validate_version2_profile
    from acs.version2_release_app import create_version2_release_application
    from acs.version2_release_ui import _resource_sources

    class _DiagnosticEngine:
        """Deterministic in-process engine port used only by automated diagnostic."""

        def __init__(self) -> None:
            self.closed = False

        def analyze(self, fen: str, multipv: int = 5, depth: int = 16):
            return ()

        def best_move(self, fen: str, skill_level: int = 10, movetime_ms: int = 500):
            return None

        def close(self) -> None:
            self.closed = True

    class _DiagnosticRuntime:
        """StockfishRuntime-shaped owner without external process or filesystem lookup."""

        def __init__(self, _config) -> None:
            self.engine = _DiagnosticEngine()
            self.closed = False

        def provider(self):
            if self.closed:
                raise RuntimeError("diagnostic runtime is closed")
            return self.engine

        def close(self) -> None:
            if self.closed:
                return
            self.closed = True
            self.engine.close()

    class _DiagnosticSoundPlayback:
        def play(self, _event, *, volume: int) -> None:
            if not isinstance(volume, int):
                raise TypeError("diagnostic sound volume must be an integer")

    core_run()
    validate_version2_profile()
    resources = _resource_sources()
    resource_names = tuple(name for name, _source in resources)

    api = application = runtime = None
    shutdown_ok = False
    with TemporaryDirectory(prefix="accessible-chess-v2-diagnostic-") as temp_root:
        try:
            api, application, runtime, _native_runtime_factory = create_version2_release_application(
                data_root=temp_root,
                runtime_factory=_DiagnosticRuntime,
                sound_playback=_DiagnosticSoundPlayback(),
                copy_text=lambda _value: None,
            )

            # Stage1 and V2 must be proven through the same composed API instance.
            semantic = api.diagnostic()
            flow = complete_user_flow_diagnostic(api)
            v2 = api.v2_snapshot()
            stage1_state = api.get_state()
        finally:
            try:
                if application is not None:
                    shutdown_ok = application.shutdown() is True
            finally:
                try:
                    if api is not None:
                        api.close_analysis()
                finally:
                    if runtime is not None:
                        runtime.close()

    navigation = v2.get("navigation", ()) if isinstance(v2, Mapping) else ()
    route_ids = tuple(
        str(item.get("route_id", ""))
        for item in navigation
        if isinstance(item, Mapping)
    )
    library = v2.get("library") if isinstance(v2, Mapping) else None
    screen = v2.get("screen") if isinstance(v2, Mapping) else None

    if (
        not shutdown_ok
        or not semantic.get("ok")
        or semantic.get("boardCells") != 64
        or not semantic.get("semanticDocumentPresent")
        or not flow.get("ok")
        or flow.get("boardCells") != 64
        or len(stage1_state.get("board", ())) != 64
        or not isinstance(screen, Mapping)
        or screen.get("route_id") != "board"
        or route_ids != VERSION2_ROUTE_IDS
        or not isinstance(library, Mapping)
        or "V2 release bootstrap" not in resource_names
        or "V2 PGN surface" not in resource_names
        or "V2 Library surface" not in resource_names
        or "V2 Books surface" not in resource_names
        or not bool(getattr(runtime, "closed", False))
        or not bool(getattr(getattr(runtime, "engine", None), "closed", False))
    ):
        raise SystemExit(
            "ACCESSIBLE CHESS V2 DIAGNOSTIC FAILED: "
            + json.dumps(
                {
                    "semantic": semantic,
                    "userFlow": flow,
                    "v2Route": screen.get("route_id") if isinstance(screen, Mapping) else None,
                    "v2Routes": route_ids,
                    "libraryComposed": isinstance(library, Mapping),
                    "stage1BoardCells": len(stage1_state.get("board", ())),
                    "shutdown": shutdown_ok,
                    "runtimeClosed": bool(getattr(runtime, "closed", False)),
                    "engineClosed": bool(getattr(getattr(runtime, "engine", None), "closed", False)),
                    "resources": resource_names,
                },
                ensure_ascii=False,
            )
        )
    print("ACCESSIBLE CHESS V2 RELEASE-CANDIDATE DIAGNOSTIC PASS")
else:
    from acs.webview2_accessibility import install_pywebview_accessibility_host_patch

    if not install_pywebview_accessibility_host_patch():
        raise SystemExit("Accessible WebView2 host could not be initialized.")
    if not install_pywebview_safe_local_server_port():
        raise SystemExit("Accessible WebView2 local server could not be initialized.")

    from acs.version2_release_app import main

    main()
