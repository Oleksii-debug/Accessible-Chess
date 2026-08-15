import json
import sys

if '--diagnostic' in sys.argv:
    # Diagnostic is deliberately presentation-toolkit independent. Windows CI
    # separately verifies packaged WebView2 startup and real Stockfish runtime.
    from acs.selftest import run as core_run
    from acs.webapp_keymap import KeymapAwareAccessibleChessAPI

    core_run()
    result = KeymapAwareAccessibleChessAPI().diagnostic()
    if not result.get('ok') or result.get('boardCells') != 64 or not result.get('semanticDocumentPresent'):
        raise SystemExit('ACCESSIBLE WEB UI DIAGNOSTIC FAILED: ' + json.dumps(result, ensure_ascii=False))
    print('ACCESSIBLE CHESS 0.4 WEBVIEW2 DIAGNOSTIC PASS')
else:
    from acs.release_app import main
    main()
