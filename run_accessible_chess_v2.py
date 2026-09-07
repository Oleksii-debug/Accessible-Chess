import json
import sys

from acs.webview2_accessibility import enable_webview2_renderer_accessibility
from acs.webview_safe_server import install_pywebview_safe_local_server_port


# Renderer accessibility must be enabled before pywebview/WebView2 is imported.
enable_webview2_renderer_accessibility()


if "--diagnostic" in sys.argv:
    # Automated evidence only. Human NVDA verification remains Oleksii-only on
    # the exact packaged candidate and is never inferred from this diagnostic.
    from acs.selftest import run as core_run
    from acs.stage1_release_ui import Stage1ReleaseAccessibleChessAPI, complete_user_flow_diagnostic
    from acs.version2_profile import validate_version2_profile
    from acs.version2_release_ui import _resource_sources

    core_run()
    validate_version2_profile()
    resources = _resource_sources()
    api = Stage1ReleaseAccessibleChessAPI()
    try:
        semantic = api.diagnostic()
        flow = complete_user_flow_diagnostic(api)
    finally:
        api.close_analysis()

    resource_names = tuple(name for name, _source in resources)
    if (
        not semantic.get("ok")
        or semantic.get("boardCells") != 64
        or not semantic.get("semanticDocumentPresent")
        or not flow.get("ok")
        or flow.get("boardCells") != 64
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
