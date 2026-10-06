"""Actual Windows/WebView2 source host, bridge, SQLite and import-pump oracle.

This checks thread ownership, not packaged resources, picker accessibility or
human NVDA acceptance. Only trusted file-picker boundaries are replaced by
fixtures owned by this oracle.
"""
from concurrent.futures import Future
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time

from acs.version2_release_app import create_version2_release_application
from acs.version2_release_ui import run_version2_release_window
from acs.version2_windows_file_workflows import FileWorkflowEventKind


def main():
    if sys.platform != "win32":
        raise SystemExit("This oracle requires real Windows/WebView2")
    checks, failures = {}, []
    with tempfile.TemporaryDirectory(prefix="acs-v2-native-") as raw:
        root = Path(raw)
        source = root / "thread-fixture.pgn"
        source.write_text('[Event "Thread oracle"]\n[White "Петренко"]\n[Result "*"]\n\n1. e4 {original} (1. d4 d5) e5 *\n', encoding="utf-8")
        api, factory, runtime, native_factory = create_version2_release_application(
            data_root=root, defer_ui=True)
        launcher_thread = threading.get_ident()
        observed = {}

        def loaded(window):
            app = None
            files = None

            def wait(predicate):
                deadline = time.monotonic() + 25
                while time.monotonic() < deadline:
                    if predicate():
                        return
                    time.sleep(0.05)
                raise AssertionError("native runtime condition timed out")

            def bridge(expression):
                result = Future()
                window.evaluate_js("(async () => { try { return {ok:true,value:await (" + expression +
                    ")}; } catch (e) { return {ok:false,error:e.name}; } })()", callback=result.set_result)
                value = result.result(25)
                if not value or not value.get("ok"):
                    raise AssertionError("actual JavaScript/Python bridge rejected a command")
                return value.get("value")

            try:
                # Route count is intentionally not exact: additive canonical V2 routes
                # (for example Training) must not turn runtime readiness into a false
                # negative. Require the release-critical semantic routes plus the
                # original accessible 64-square board instead.
                wait(lambda: window.evaluate_js(
                    "document.querySelector('#v2-navigation') !== null && "
                    "document.querySelector('#v2-nav-board') !== null && "
                    "document.querySelector('#v2-nav-library') !== null && "
                    "document.querySelector('#v2-nav-books') !== null && "
                    "document.querySelector('#v2-nav-training') !== null && "
                    "document.querySelectorAll('[role=gridcell]').length===64"))
                checks["real_webview2_loaded"] = True
                app = api._version2_application
                files = app._files
                observed["files"] = files
                from System.Threading import Thread  # type: ignore
                checks["one_native_sta_owner"] = api._invoke_ui(lambda:
                    launcher_thread != threading.get_ident() == app._thread == files.ui_thread_id
                    and str(Thread.CurrentThread.GetApartmentState()) == "STA")
                checks["owned_native_menu"] = api._invoke_ui(lambda:
                    api._ui_owner.MainMenuStrip.Name == "AccessibleChessFullProductMenu")
                snapshots = bridge("Promise.all(Array.from({length:12},()=>pywebview.api.v2_snapshot()))")
                checks["concurrent_bridge_sqlite_snapshots"] = len(snapshots) == 12 and all(
                    value["screen"]["route_id"] == "board" for value in snapshots)
                move = bridge("pywebview.api.make_move('e4')")
                state = bridge("pywebview.api.get_state()")
                checks["inherited_board_api"] = move["ok"] and state["fen"] == move["fen"]

                # Select only a test-owned source at the trusted picker boundary.
                # The real runtime, worker, parser, DB, UI poster and mailbox remain.
                api._invoke_ui(lambda: setattr(files.file_dialogs, "select_library_import", lambda: source))
                bridge("pywebview.api.v2_browser_command('library','library.import',{})")
                wait(lambda: api.v2_snapshot()["library"]["import"]["phase"] == "completed")
                checks["native_worker_mailbox_sqlite_import"] = api.v2_snapshot()["library"]["import"]["processed_games"] == 1
                searched = bridge("pywebview.api.v2_browser_command('library','library.search',{player:'Петренко'})")
                opened = bridge("pywebview.api.v2_browser_command('library','library.open_game',{})")
                selected = bridge("pywebview.api.v2_browser_command('pgn','pgn.select',{node_id:'g0:main/m0'})")
                edited = bridge("pywebview.api.v2_browser_command('pgn','pgn.comment_edit',{text:'Коментар з Windows'})")
                dirty_before_save = api._invoke_ui(lambda: app.session.dirty)
                checks["library_to_detached_pgn_edit"] = (
                    searched["kind"] == "render" and opened["kind"] == "delegated"
                    and selected["kind"] == edited["kind"] == "selection"
                    and dirty_before_save)

                # A dirty-document close now correctly opens a native confirmation.
                # A headless runner cannot answer that modal dialog, so finish the
                # actual user journey through the existing trusted Save As workflow
                # before closing. This keeps the close guard enabled and exercises
                # canonical PGN persistence instead of bypassing Product behavior.
                saved_copy = root / "thread-edited-saved.pgn"
                api._invoke_ui(lambda: setattr(
                    files.file_dialogs,
                    "save_pgn_as",
                    lambda _suggested="game.pgn": saved_copy,
                ))
                saved_event = api._invoke_ui(lambda: files("pgn.save_as", {}))
                checks["dirty_pgn_saved_before_close"] = (
                    getattr(saved_event, "kind", None) is FileWorkflowEventKind.PGN_SAVED_AS
                    and saved_copy.is_file()
                    and "Коментар з Windows" in saved_copy.read_text(encoding="utf-8")
                    and not api._invoke_ui(lambda: app.session.dirty)
                )

                checks["canonical_affinity_guard_retained"] = False
                try:
                    app.snapshot()
                except RuntimeError:
                    checks["canonical_affinity_guard_retained"] = True
                checks["original_64_square_board_retained"] = window.evaluate_js(
                    "document.querySelectorAll('[role=gridcell]').length===64")
            except Exception as error:
                failures.append(type(error).__name__ + ": " + str(error))
            finally:
                # If an assertion fails after the oracle made the document dirty,
                # save the test-owned session directly through its canonical PGN
                # session contract so teardown cannot deadlock on a modal prompt.
                if app is not None:
                    try:
                        dirty = api._invoke_ui(
                            lambda: bool(app.session is not None and app.session.dirty)
                        )
                        if dirty:
                            cleanup_path = root / "thread-oracle-cleanup.pgn"
                            api._invoke_ui(lambda: app.session.save_as(cleanup_path))
                    except Exception as error:
                        failures.append("teardown " + type(error).__name__ + ": " + str(error))
                window.destroy()

        run_version2_release_window(api, factory, runtime,
            file_runtime_factory=native_factory, loaded_hook=loaded)
        checks["closed_on_native_thread"] = api._ui_closed and bool(
            observed.get("files") and observed["files"].closed)
        with closing(sqlite3.connect(root / "library.acsdb")) as database:
            checks["library_reopens_after_window_close"] = (
                database.execute("PRAGMA quick_check").fetchone()[0] == "ok"
                and database.execute("SELECT count(*) FROM games").fetchone()[0] == 1)
    passed = bool(checks) and not failures and all(value is True for value in checks.values())
    print(json.dumps({"status": "PASS" if passed else "FAIL", "checks": checks,
        "failures": failures, "PACKAGED_EXECUTABLE": "NOT_TESTED",
        "NATIVE_PICKER_UI": "NOT_TESTED", "NVDA_VERIFIED": False}, ensure_ascii=False))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    from acs.webview2_accessibility import enable_webview2_renderer_accessibility, install_pywebview_accessibility_host_patch
    from acs.webview_safe_server import install_pywebview_safe_local_server_port
    enable_webview2_renderer_accessibility()
    if not install_pywebview_accessibility_host_patch() or not install_pywebview_safe_local_server_port():
        raise SystemExit("Accessible Windows initialization failed")
    main()
