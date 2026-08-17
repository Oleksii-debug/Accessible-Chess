import json
import os
import sys


def _enable_packaged_webview2_accessibility() -> None:
    """Force Chromium renderer accessibility before pywebview creates WebView2.

    The packaged Windows process is tested through raw Windows UI Automation,
    which does not necessarily look like an attached assistive-technology
    client to Chromium.  WebView2 officially appends
    WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS to its environment options, so force
    renderer accessibility at the process boundary before importing pywebview.
    Existing application/browser arguments are preserved.
    """

    key = "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"
    current = os.environ.get(key, "").strip()
    tokens = current.split()
    if not any(
        token == "--force-renderer-accessibility"
        or token.startswith("--force-renderer-accessibility=")
        for token in tokens
    ):
        os.environ[key] = (current + " --force-renderer-accessibility").strip()


_enable_packaged_webview2_accessibility()


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
    from acs.stage1_release_ui import main
    main()
