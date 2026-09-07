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
    # The diagnostic deliberately composes the same Version 2 application root
    # as the real launcher, while replacing only external engine/audio effects
    # with deterministic local ports so CI never needs a GUI or paid resource.
    from acs.selftest import run as core_run
    from acs.stage1_release_ui import complete_user_flow_diagnostic
    from acs.version2_profile import validate_version2_profile
    from acs.version2_release_app import create_version2_release_application
    from acs.version2_release_ui import _resource_sources

    class _DiagnosticEngine:
        def analyze(self, fen, multipv=5, depth=16):
            return ()

        def best_move(self, fen, skill_level=10, movetime_ms=500):
            return None

        def close(self):
            return None

    class _DiagnosticRuntime:
        def __init__(self):
            self.engine = _DiagnosticEngine()
            self.closed = False

        def provider(self):
            if self.closed:
                raise RuntimeError("diagnostic engine runtime is closed")
            return self.engine

        def close(self):
            self.closed = True
            self.engine.close()

    class _SilentPlayback:
        def play(self, event, *, volume):
            return None

    core_run()
    validate_version2_profile()
    resources = _resource_sources()
    runtime = _DiagnosticRuntime()
    application = None
    api = None
    semantic = flow = v2_state = None

    with tempfile.TemporaryDirectory() as temp:
        try:
            api, application, composed_runtime, _native_runtime_factory = (
                create_version2_release_application(
                    runtime_factory=lambda _config: runtime,
                    sound_playback=_SilentPlayback(),
                    data_root=Path(temp) / "v2-user-data",
                    copy_text=lambda _value: None,
                )
            )
            if composed_runtime is not runtime:
                raise RuntimeError("Version 2 diagnostic did not retain its composed runtime")
            semantic = api.diagnostic()
            flow = complete_user_flow_diagnostic(api)
            v2_state = api.v2_snapshot()
        finally:
            try:
                if application is not None:
                    application.shutdown()
            finally:
                try:
                    if api is not None:
                        api.close_analysis()
                finally:
                    runtime.close()

    resource_names = tuple(name for name, _source in resources)
    if (
        not isinstance(semantic, dict)
        or not semantic.get("ok")
        or semantic.get("boardCells") != 64
        or not semantic.get("semanticDocumentPresent")
        or not isinstance(flow, dict)
        or not flow.get("ok")
        or flow.get("boardCells") != 64
        or not isinstance(v2_state, dict)
        or not isinstance(v2_state.get("library"), dict)
        or not runtime.closed
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
                    "v2": v2_state,
                    "runtimeClosed": runtime.closed,
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
