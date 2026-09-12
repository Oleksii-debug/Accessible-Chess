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
    # The diagnostic composes the same final-product release root as the real
    # launcher. Only external engine/audio/clipboard/data-root effects are
    # replaced through existing injected composition ports for deterministic CI.
    from acs.selftest import run as core_run
    from acs.stage1_release_ui import complete_user_flow_diagnostic
    from acs.version2_final_product_profile import validate_final_product_profile
    from acs.version2_education_mutation_release import (
        create_version2_release_application,
        final_product_resource_sources,
    )

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
            self.engine.close()
            self.closed = True

    class _SilentPlayback:
        def play(self, event, *, volume):
            return None

    core_run()
    validate_final_product_profile()
    resources = final_product_resource_sources()
    runtime = _DiagnosticRuntime()
    application = None
    api = None
    semantic = flow = v2_state = None
    cleanup_order = []

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
                    cleanup_order.append("application")
            finally:
                try:
                    if api is not None:
                        api.close_analysis()
                        cleanup_order.append("analysis")
                finally:
                    runtime.close()
                    cleanup_order.append("runtime")

    resource_names = tuple(name for name, _source in resources)
    navigation = (
        tuple(item.get("route_id", "") for item in v2_state.get("navigation", ()))
        if isinstance(v2_state, dict)
        else ()
    )
    product_status = (
        v2_state.get("product_status", {})
        if isinstance(v2_state, dict)
        else {}
    )
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
        or not isinstance(v2_state.get("education"), dict)
        or v2_state.get("teacher") is not None
        or "teacher" not in navigation
        or "classes" not in navigation
        or product_status.get("remote_transport") != "not_approved"
        or cleanup_order != ["application", "analysis", "runtime"]
        or not runtime.closed
        or "V2 final-product bootstrap" not in resource_names
        or "V2 Teacher surface" not in resource_names
        or "V2 Education surface" not in resource_names
        or "V2 PGN surface" not in resource_names
        or "V2 Library surface" not in resource_names
        or "V2 Books surface" not in resource_names
    ):
        raise SystemExit(
            "ACCESSIBLE CHESS V2 FINAL-PRODUCT DIAGNOSTIC FAILED: "
            + json.dumps(
                {
                    "semantic": semantic,
                    "userFlow": flow,
                    "v2": v2_state,
                    "cleanupOrder": cleanup_order,
                    "runtimeClosed": runtime.closed,
                    "resources": resource_names,
                },
                ensure_ascii=False,
            )
        )
    print("PRODUCTION COMPOSITION DIAGNOSTIC PASS")
    print("ACCESSIBLE CHESS V2 FINAL-PRODUCT COMPOSITION DIAGNOSTIC PASS")
else:
    from acs.webview2_accessibility import install_pywebview_accessibility_host_patch

    if not install_pywebview_accessibility_host_patch():
        raise SystemExit("Accessible WebView2 host could not be initialized.")
    if not install_pywebview_safe_local_server_port():
        raise SystemExit("Accessible WebView2 local server could not be initialized.")

    from acs.version2_education_mutation_release import main

    main()
