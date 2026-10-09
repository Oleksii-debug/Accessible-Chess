import json
import sys
import traceback

ACCESSIBILITY_HOST_INIT_EXIT_CODE = 71
SAFE_LOCAL_SERVER_INIT_EXIT_CODE = 72
RELEASE_UI_STARTUP_EXIT_CODE = 73


def _abort_packaged_startup(
    exit_code: int,
    message: str,
    *,
    include_traceback: bool = False,
) -> None:
    """Fail closed with a launcher-readable code without requiring a console."""

    stream = getattr(sys, "stderr", None)
    if stream is not None:
        try:
            print(message, file=stream)
            if include_traceback:
                traceback.print_exc(file=stream)
        except Exception:
            # A windowed frozen executable may expose an unusable stderr proxy.
            # The stable numeric code remains the package-local launch authority.
            pass
    raise SystemExit(exit_code)


# This must run before importing pywebview or creating a WebView2 environment.
try:
    from acs.webview2_accessibility import enable_webview2_renderer_accessibility
except Exception:
    _abort_packaged_startup(
        ACCESSIBILITY_HOST_INIT_EXIT_CODE,
        'Accessible WebView2 renderer accessibility support could not be loaded.',
        include_traceback=True,
    )

try:
    enable_webview2_renderer_accessibility()
except Exception:
    _abort_packaged_startup(
        ACCESSIBILITY_HOST_INIT_EXIT_CODE,
        'Accessible WebView2 renderer accessibility could not be initialized.',
    )


if '--diagnostic' in sys.argv:
    # Diagnostic is deliberately presentation-toolkit independent. Windows CI
    # separately proves the packaged WebView2 executable. Real NVDA acceptance
    # remains a human test by Oleksii.
    from acs.selftest import run as core_run
    from acs.stage1_release_ui import Stage1ReleaseAccessibleChessAPI, complete_user_flow_diagnostic

    core_run()
    api = Stage1ReleaseAccessibleChessAPI()
    semantic = api.diagnostic()
    flow = complete_user_flow_diagnostic(api)
    if (
        not semantic.get('ok')
        or semantic.get('boardCells') != 64
        or not semantic.get('semanticDocumentPresent')
        or not flow.get('ok')
        or flow.get('boardCells') != 64
    ):
        raise SystemExit(
            'ACCESSIBLE WEB UI DIAGNOSTIC FAILED: '
            + json.dumps({'semantic': semantic, 'userFlow': flow}, ensure_ascii=False)
        )
    print('ACCESSIBLE CHESS 0.4 WEBVIEW2 COMPLETE USER FLOW DIAGNOSTIC PASS')
else:
    try:
        from acs.webview2_accessibility import install_pywebview_accessibility_host_patch
    except Exception:
        _abort_packaged_startup(
            ACCESSIBILITY_HOST_INIT_EXIT_CODE,
            'Accessible WebView2 host support could not be loaded.',
            include_traceback=True,
        )

    try:
        from acs.webview_safe_server import (
            SafeLocalServerPortError,
            install_pywebview_safe_local_server_port,
        )
    except Exception:
        _abort_packaged_startup(
            SAFE_LOCAL_SERVER_INIT_EXIT_CODE,
            'Accessible WebView2 local server support could not be loaded.',
            include_traceback=True,
        )

    # Patch the actual pywebview WinForms/WebView2 host before any EdgeChrome
    # instance is created. No duplicate native or hidden Move control is used.
    try:
        host_patch_ok = install_pywebview_accessibility_host_patch()
    except Exception:
        host_patch_ok = False
    if not host_patch_ok:
        _abort_packaged_startup(
            ACCESSIBILITY_HOST_INIT_EXIT_CODE,
            'Accessible WebView2 host could not be initialized.',
        )

    # pywebview 6.2.1 otherwise chooses a random local-server port in private
    # mode. The release must never reach Chromium-restricted ports such as 6666.
    try:
        safe_server_ok = install_pywebview_safe_local_server_port()
    except Exception:
        safe_server_ok = False
    if not safe_server_ok:
        _abort_packaged_startup(
            SAFE_LOCAL_SERVER_INIT_EXIT_CODE,
            'Accessible WebView2 local server could not be initialized.',
        )

    try:
        from acs.stage1_release_ui import main
        main()
    except SafeLocalServerPortError:
        _abort_packaged_startup(
            SAFE_LOCAL_SERVER_INIT_EXIT_CODE,
            'Accessible WebView2 local server could not obtain a safe loopback port.',
        )
    except Exception:
        _abort_packaged_startup(
            RELEASE_UI_STARTUP_EXIT_CODE,
            'Accessible Chess release UI could not be started.',
            include_traceback=True,
        )
