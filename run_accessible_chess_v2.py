import json
from pathlib import Path
import sys
import tempfile

from acs.webview2_accessibility import enable_webview2_renderer_accessibility
from acs.webview_safe_server import install_pywebview_safe_local_server_port


# Renderer accessibility must be enabled before pywebview/WebView2 is imported.
enable_webview2_renderer_accessibility()


if "--diagnostic" in sys.argv:
    # Automated evidence only. Human NVDA verification remains Oleksii-only on
    # the exact packaged candidate and is never inferred from this diagnostic.
    from acs.selftest import run as core_run
    from acs.stage1_release_ui import complete_user_flow_diagnostic
    from acs.version2_profile import validate_version2_profile
    from acs.version2_release_app import create_version2_release_application
    from acs.version2_release_ui import _resource_sources

    class _DiagnosticEngineRuntime:
        """No-process engine owner used only to prove production composition wiring."""

        def __init__(self, _config):
            # The diagnostic deliberately does not request engine analysis or play.
            # Both production services receive the same callable provider port,
            # preserving the composition topology without launching Stockfish.
            self.provider = lambda: None
            self.closed = False

        def close(self):
            self.closed = True

    class _DiagnosticSoundPlayback:
        def play(self, _event, *, volume):
            if not isinstance(volume, int):
                raise TypeError("diagnostic volume must be an integer")

    core_run()
    validate_version2_profile()
    resources = _resource_sources()
    resource_names = tuple(name for name, _source in resources)

    semantic = flow = v2_snapshot = None
    application_closed = False
    runtime_closed = False
    with tempfile.TemporaryDirectory(prefix="accessible-chess-v2-diagnostic-") as temp:
        api, application, runtime, _native_runtime_factory = create_version2_release_application(
            runtime_factory=_DiagnosticEngineRuntime,
            sound_playback=_DiagnosticSoundPlayback(),
            data_root=Path(temp),
            copy_text=lambda _text: None,
        )
        try:
            semantic = api.diagnostic()
            flow = complete_user_flow_diagnostic(api)
            v2_snapshot = api.v2_snapshot()
        finally:
            try:
                application_closed = application.shutdown() is True
            finally:
                try:
                    api.close_analysis()
                finally:
                    runtime.close()
                    runtime_closed = bool(getattr(runtime, "closed", False))

    navigation = v2_snapshot.get("navigation") if isinstance(v2_snapshot, dict) else None
    screen = v2_snapshot.get("screen") if isinstance(v2_snapshot, dict) else None
    library = v2_snapshot.get("library") if isinstance(v2_snapshot, dict) else None
    navigation_sequence = isinstance(navigation, (list, tuple))
    v2_composition_ok = (
        navigation_sequence
        and len(navigation) == 7
        and isinstance(screen, dict)
        and screen.get("route_id") == "board"
        and isinstance(library, dict)
        and application_closed
        and runtime_closed
    )

    if (
        not semantic.get("ok")
        or semantic.get("boardCells") != 64
        or not semantic.get("semanticDocumentPresent")
        or not flow.get("ok")
        or flow.get("boardCells") != 64
        or not v2_composition_ok
        or "V2 release bootstrap" not in resource_names
        or "V2 PGN surface" not in resource_names
        or "V2 Library surface" not in resource_names
        or "V2 Books surface" not in resource_names
    ):
        raise SystemExit(
            "ACCESSIBLE CHESS V2 DIAGNOSTIC FAILED: "
            + json.dumps(
                {
                    "semantic": semantic,
                    "userFlow": flow,
                    "v2Composition": {
                        "ok": v2_composition_ok,
                        "navigationCount": len(navigation) if navigation_sequence else None,
                        "route": screen.get("route_id") if isinstance(screen, dict) else None,
                        "libraryPresent": isinstance(library, dict),
                        "applicationClosed": application_closed,
                        "runtimeClosed": runtime_closed,
                    },
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
