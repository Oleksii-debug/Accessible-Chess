"""Windows source-runtime oracle for the shipping V2 native MenuBar.

This launches the same final-product composition used by ``run_accessible_chess_v2.py``
and compares in-process WinForms ownership/handle state with an independent
process-scoped Windows UIA probe. It is machine evidence only; it does not replace
packaged qualification or human NVDA verification.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _managed_type(value: Any) -> str:
    if value is None:
        return ""
    try:
        return str(value.GetType().FullName)
    except Exception:
        return type(value).__name__


def _handle(value: Any) -> int:
    try:
        if not bool(getattr(value, "IsHandleCreated", False)):
            return 0
        return int(value.Handle.ToInt64())
    except Exception:
        return 0


def _winforms_snapshot(api: Any, window: Any) -> dict[str, Any]:
    def collect() -> dict[str, Any]:
        from acs.ui_native_menu import _same_managed_object

        host = getattr(window, "_accessible_chess_native_menu_host", None)
        menu = getattr(window, "_accessible_chess_native_menu", None)
        controls: list[dict[str, Any]] = []
        if host is not None:
            try:
                controls = [
                    {
                        "type": _managed_type(control),
                        "name": str(getattr(control, "Name", "")),
                        "visible": bool(getattr(control, "Visible", False)),
                        "enabled": bool(getattr(control, "Enabled", False)),
                        "created": bool(getattr(control, "Created", False)),
                        "is_handle_created": bool(getattr(control, "IsHandleCreated", False)),
                        "handle": _handle(control),
                    }
                    for control in list(host.Controls)
                ]
            except Exception as exc:
                controls = [{"snapshot_error": type(exc).__name__}]
        return {
            "host_exists": host is not None,
            "host_type": _managed_type(host),
            "host_visible": bool(getattr(host, "Visible", False)) if host is not None else False,
            "host_created": bool(getattr(host, "Created", False)) if host is not None else False,
            "host_is_handle_created": bool(getattr(host, "IsHandleCreated", False)) if host is not None else False,
            "host_handle": _handle(host),
            "menu_exists": menu is not None,
            "menu_type": _managed_type(menu),
            "menu_name": str(getattr(menu, "Name", "")) if menu is not None else "",
            "menu_accessible_name": str(getattr(menu, "AccessibleName", "")) if menu is not None else "",
            "menu_visible": bool(getattr(menu, "Visible", False)) if menu is not None else False,
            "menu_enabled": bool(getattr(menu, "Enabled", False)) if menu is not None else False,
            "menu_created": bool(getattr(menu, "Created", False)) if menu is not None else False,
            "menu_is_handle_created": bool(getattr(menu, "IsHandleCreated", False)) if menu is not None else False,
            "menu_handle": _handle(menu),
            "menu_parent_is_host": _same_managed_object(getattr(menu, "Parent", None), host) if menu is not None else False,
            "main_menu_strip_is_menu": _same_managed_object(getattr(host, "MainMenuStrip", None), menu) if host is not None else False,
            "menu_item_count": int(getattr(getattr(menu, "Items", None), "Count", 0)) if menu is not None else 0,
            "controls": controls,
        }

    return api._invoke_ui(collect)


def _uia_snapshot(
    pid: int,
    *,
    menu_handle: int = 0,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    """Probe UIA out-of-process so pywebview/pythonnet CLR binding cannot mask UIA."""

    shell = shutil.which("pwsh") or shutil.which("powershell.exe") or shutil.which("powershell")
    if not shell:
        raise RuntimeError("PowerShell is unavailable for the independent UIA probe")
    probe = _REPO_ROOT / "scripts" / "p0_native_menubar_uia_probe.ps1"
    if not probe.is_file():
        raise RuntimeError("external UIA probe script is missing")

    with tempfile.TemporaryDirectory(prefix="acs-p0-uia-probe-") as raw:
        output = Path(raw) / "uia.json"
        completed = subprocess.run(
            [
                shell,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(probe),
                "-TargetProcessId",
                str(pid),
                "-MenuHandle",
                str(menu_handle),
                "-OutputPath",
                str(output),
                "-TimeoutSeconds",
                str(timeout_seconds),
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds + 20,
            check=False,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.strip().replace("\r", " ").replace("\n", " ")
            stdout = completed.stdout.strip().replace("\r", " ").replace("\n", " ")
            detail = (stderr or stdout or "no diagnostic output")[:2000]
            raise RuntimeError(f"external UIA probe failed ({completed.returncode}): {detail}")
        if not output.is_file():
            raise RuntimeError("external UIA probe produced no evidence file")
        try:
            value = json.loads(output.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("external UIA probe evidence is unreadable") from exc
        if not isinstance(value, dict):
            raise RuntimeError("external UIA probe evidence root is invalid")
        return value


def main() -> int:
    if sys.platform != "win32":
        raise SystemExit("This oracle requires Windows")

    from acs.webview2_accessibility import (
        enable_webview2_renderer_accessibility,
        install_pywebview_accessibility_host_patch,
    )
    from acs.webview_safe_server import install_pywebview_safe_local_server_port

    enable_webview2_renderer_accessibility()
    if not install_pywebview_accessibility_host_patch():
        raise SystemExit("Accessible WebView2 host patch failed")
    if not install_pywebview_safe_local_server_port():
        raise SystemExit("Accessible WebView2 local server patch failed")

    from acs import version2_education_mutation_release as education_release
    from acs import version2_release_ui as release_ui
    from acs.version2_upgrade_status_release import create_version2_release_application

    result: dict[str, Any] = {}
    errors: list[str] = []
    worker_done = threading.Event()

    class _Engine:
        def analyze(self, fen: str, multipv: int = 5, depth: int = 16):
            return ()

        def best_move(self, fen: str, skill_level: int = 10, movetime_ms: int = 500):
            return None

        def close(self) -> None:
            return None

    class _Runtime:
        def __init__(self) -> None:
            self.engine = _Engine()

        def provider(self):
            return self.engine

        def close(self) -> None:
            self.engine.close()

    with tempfile.TemporaryDirectory(prefix="acs-p0-menubar-") as raw:
        runtime = _Runtime()
        with education_release._final_product_mutation_bindings():
            api, application_factory, composed_runtime, native_runtime_factory = create_version2_release_application(
                defer_ui=True,
                data_root=Path(raw),
                runtime_factory=lambda _config: runtime,
            )
            if composed_runtime is not runtime:
                raise RuntimeError("oracle did not retain injected engine runtime")

            def loaded(window: Any) -> None:
                def inspect() -> None:
                    try:
                        result["winforms"] = _winforms_snapshot(api, window)
                        result["uia"] = _uia_snapshot(
                            os.getpid(),
                            menu_handle=int(result["winforms"].get("menu_handle") or 0),
                        )
                        result["winforms_after_uia"] = _winforms_snapshot(api, window)
                    except Exception as exc:
                        errors.append(type(exc).__name__ + ": " + str(exc))
                    finally:
                        worker_done.set()
                        try:
                            window.destroy()
                        except Exception as exc:
                            errors.append("destroy " + type(exc).__name__ + ": " + str(exc))

                threading.Thread(
                    target=inspect,
                    name="p0-menubar-uia-oracle",
                    daemon=True,
                ).start()

            release_ui.run_version2_release_window(
                api,
                application_factory,
                runtime,
                file_runtime_factory=native_runtime_factory,
                loaded_hook=loaded,
            )

    if not worker_done.wait(5):
        errors.append("UIA oracle worker did not complete")

    expected_ua = [
        "Файл", "Гра", "Позиція", "PGN", "Бібліотека", "Імпорт", "Експорт",
        "Stockfish", "Аналіз", "Книги", "Учитель/Клас", "Налаштування", "Довідка",
    ]
    expected_en = [
        "File", "Game", "Position", "PGN", "Library", "Import", "Export",
        "Engine", "Analysis", "Books", "Teacher/Classroom", "Settings", "Help",
    ]
    winforms = result.get("winforms_after_uia") or result.get("winforms") or {}
    uia = result.get("uia") or {}
    names = uia.get("top_level_names") or []
    patterns = uia.get("top_level_expand_collapse") or []
    checks = {
        "host_handle_created": bool(winforms.get("host_is_handle_created")),
        "menu_parent_is_host": bool(winforms.get("menu_parent_is_host")),
        "main_menu_strip_is_menu": bool(winforms.get("main_menu_strip_is_menu")),
        "menu_handle_created": bool(winforms.get("menu_is_handle_created")),
        "menu_handle_nonzero": int(winforms.get("menu_handle") or 0) != 0,
        "winforms_top_level_count_13": int(winforms.get("menu_item_count") or 0) == 13,
        "uia_exact_menu_bar_count_1": int(uia.get("exact_menu_bar_count") or 0) == 1,
        "uia_top_level_profile_13": names in (expected_ua, expected_en),
        "uia_expand_collapse_all": len(patterns) == 13 and all(patterns),
    }
    passed = not errors and all(checks.values())
    summary = {
        "status": "PASS" if passed else "FAIL",
        "machine_scope": "Windows source final-product WinForms plus external process-scoped UIA",
        "checks": checks,
        "winforms": result.get("winforms"),
        "uia": result.get("uia"),
        "winforms_after_uia": result.get("winforms_after_uia"),
        "errors": errors,
        "PACKAGED_EXECUTABLE": "NOT_TESTED",
        "NVDA_VERIFIED": False,
    }
    Path("p0-native-menubar-uia-source-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # Keep CI console output ASCII-safe; the artifact preserves the original Unicode.
    print(json.dumps(summary, ensure_ascii=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
