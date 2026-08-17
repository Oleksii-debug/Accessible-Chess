import json
import sys

from acs.webview2_accessibility import enable_webview2_renderer_accessibility


# This must run before importing pywebview or creating a WebView2 environment.
enable_webview2_renderer_accessibility()


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
    from acs.webview2_accessibility import install_pywebview_accessibility_host_patch

    # Patch the actual pywebview WinForms/WebView2 host before any EdgeChrome
    # instance is created. No duplicate native or hidden Move control is used.
    if not install_pywebview_accessibility_host_patch():
        raise SystemExit('Accessible WebView2 host could not be initialized.')

    from acs.stage1_release_ui import main
    main()
