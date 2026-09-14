"""Windows source-runtime oracle for the shipping V2 native MenuBar.

This is machine evidence only. It launches the same final-product composition used
by ``run_accessible_chess_v2.py`` and compares two independent views of the menu:
WinForms ownership/handle state inside the process and process-scoped Windows UIA
from the desktop root. It does not substitute for packaged qualification or human
NVDA verification.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from typing import Any


# Direct ``python scripts/...`` execution puts scripts/ at sys.path[0].  Make the
# repository root explicit so this durable oracle works both locally and in CI.
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
        controls = []
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
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    import clr  # type: ignore

    clr.AddReference("UIAutomationClient")
    clr.AddReference("UIAutomationTypes")
    from System import IntPtr  # type: ignore
    from System.Windows.Automation import (  # type: ignore
        AndCondition,
        AutomationElement,
        ControlType,
        ExpandCollapsePattern,
        PropertyCondition,
        TreeScope,
    )

    desktop = AutomationElement.RootElement
    if desktop is None:
        raise RuntimeError("UIA desktop root is unavailable")
    pid_condition = PropertyCondition(AutomationElement.ProcessIdProperty, pid)
    menu_type_condition = PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.MenuBar)
    menu_condition = AndCondition(pid_condition, menu_type_condition)
    id_condition = PropertyCondition(
        AutomationElement.AutomationIdProperty,
        "AccessibleChessFullProductMenu",
    )
    exact_condition = AndCondition(pid_condition, menu_type_condition, id_condition)
    any_id_condition = AndCondition(pid_condition, id_condition)

    all_bars = []
    exact = []
    any_id = []
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        all_bars = list(desktop.FindAll(TreeScope.Descendants, menu_condition))
        exact = list(desktop.FindAll(TreeScope.Descendants, exact_condition))
        any_id = list(desktop.FindAll(TreeScope.Descendants, any_id_condition))
        if exact:
            break
        time.sleep(0.20)

    def row(element: Any) -> dict[str, Any]:
        return {
            "automation_id": str(element.Current.AutomationId),
            "name": str(element.Current.Name),
            "control_type": str(element.Current.ControlType.ProgrammaticName),
            "process_id": int(element.Current.ProcessId),
            "enabled": bool(element.Current.IsEnabled),
            "offscreen": bool(element.Current.IsOffscreen),
            "native_window_handle": int(element.Current.NativeWindowHandle),
        }

    bars = [row(element) for element in all_bars]
    exact_rows = [row(element) for element in exact]
    any_id_rows = [row(element) for element in any_id]
    from_handle: dict[str, Any] | None = None
    from_handle_error = ""
    if menu_handle:
        try:
            element = AutomationElement.FromHandle(IntPtr(menu_handle))
            from_handle = row(element) if element is not None else None
        except Exception as exc:
            from_handle_error = type(exc).__name__ + ": " + str(exc)

    top_names: list[str] = []
    top_patterns: list[bool] = []
    if len(exact) == 1:
        item_condition = PropertyCondition(
            AutomationElement.ControlTypeProperty,
            ControlType.MenuItem,
        )
        top = list(exact[0].FindAll(TreeScope.Children, item_condition))
        for entry in top:
            top_names.append(str(entry.Current.Name).replace("&", "").strip())
            try:
                pattern = entry.GetCurrentPattern(ExpandCollapsePattern.Pattern)
                top_patterns.append(pattern is not None)
            except Exception:
                top_patterns.append(False)

    return {
        "same_process_menu_bars": bars,
        "same_process_elements_with_exact_automation_id": any_id_rows,
        "exact_menu_bars": exact_rows,
        "exact_menu_bar_count": len(exact),
        "menu_from_handle": from_handle,
        "menu_from_handle_error": from_handle_error,
        "top_level_names": top_names,
        "top_level_expand_collapse": top_patterns,
    }


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
                        menu_handle = int(result["winforms"].get("menu_handle") or 0)
                        result["uia"] = _uia_snapshot(
                            os.getpid(),
                            menu_handle=menu_handle,
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
    checks = {
        "host_handle_created": bool(winforms.get("host_is_handle_created")),
        "menu_parent_is_host": bool(winforms.get("menu_parent_is_host")),
        "main_menu_strip_is_menu": bool(winforms.get("main_menu_strip_is_menu")),
        "menu_handle_created": bool(winforms.get("menu_is_handle_created")),
        "menu_handle_nonzero": int(winforms.get("menu_handle") or 0) != 0,
        "winforms_top_level_count_13": int(winforms.get("menu_item_count") or 0) == 13,
        "uia_exact_menu_bar_count_1": int(uia.get("exact_menu_bar_count") or 0) == 1,
        "uia_top_level_profile_13": names in (expected_ua, expected_en),
        "uia_expand_collapse_all": len(uia.get("top_level_expand_collapse") or []) == 13
        and all(uia.get("top_level_expand_collapse") or []),
    }
    passed = not errors and all(checks.values())
    summary = {
        "status": "PASS" if passed else "FAIL",
        "machine_scope": "Windows source final-product WinForms plus process-scoped UIA",
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
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
