from __future__ import annotations

"""Packaged WebView2 accessibility boundaries for Stage 1."""

import os
from collections.abc import MutableMapping
from typing import Any

WEBVIEW2_BROWSER_ARGUMENTS_ENV = "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"
FORCE_RENDERER_ACCESSIBILITY = "--force-renderer-accessibility"
_PATCH_MARKER = "_acs_stage1_accessibility_host_patched"
_HANDLER_MARKER = "_acs_stage1_accessibility_host_handlers"


def enable_webview2_renderer_accessibility(
    environment: MutableMapping[str, str] | None = None,
) -> str:
    """Preserve WebView2 browser arguments and request renderer accessibility."""
    env = os.environ if environment is None else environment
    current = str(env.get(WEBVIEW2_BROWSER_ARGUMENTS_ENV, "")).strip()
    tokens = current.split()
    if not any(
        token == FORCE_RENDERER_ACCESSIBILITY
        or token.startswith(FORCE_RENDERER_ACCESSIBILITY + "=")
        for token in tokens
    ):
        current = (current + " " + FORCE_RENDERER_ACCESSIBILITY).strip()
        env[WEBVIEW2_BROWSER_ARGUMENTS_ENV] = current
    return str(env.get(WEBVIEW2_BROWSER_ARGUMENTS_ENV, current))


def _same_managed_object(left: Any, right: Any) -> bool:
    if left is right:
        return True
    if left is None or right is None:
        return False
    try:
        from System import Object  # type: ignore
        if bool(Object.ReferenceEquals(left, right)):
            return True
    except Exception:
        pass
    try:
        equals = getattr(left, "Equals", None)
        if callable(equals) and bool(equals(right)):
            return True
    except Exception:
        pass
    try:
        return bool(left == right)
    except Exception:
        return False


def _find_core_controller(webview_control: Any) -> Any | None:
    """Resolve the WinForms WebView2 controller without assuming a field name."""
    try:
        from System.Reflection import BindingFlags  # type: ignore
        flags = BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public
        for field in webview_control.GetType().GetFields(flags):
            try:
                value = field.GetValue(webview_control)
                full_name = str(getattr(getattr(value, "GetType", lambda: None)(), "FullName", ""))
            except Exception:
                continue
            if full_name == "Microsoft.Web.WebView2.Core.CoreWebView2Controller":
                return value
    except Exception:
        pass
    return None


def repair_edgechromium_accessibility_host(edge_instance: Any) -> dict[str, bool]:
    """Bind the real WebView2 controller to its actual visible WinForms host.

    WebView2 documents that parent/ancestor HWND movement must be reported to the
    controller for accessibility to work correctly. pywebview owns the WinForms
    WebView2 control, while Accessible Chess also changes the top-level host by
    attaching its native MenuStrip. Keep that controller notified instead of
    creating any duplicate native Move control.
    """
    control = getattr(edge_instance, "webview", None)
    host = getattr(edge_instance, "form", None)
    if control is None or host is None:
        return {"control": False, "host": False, "same_host": False, "controller": False, "notified": False}

    try:
        actual_host = control.FindForm()
    except Exception:
        actual_host = None
    same_host = _same_managed_object(actual_host, host)
    if not same_host:
        return {"control": True, "host": True, "same_host": False, "controller": False, "notified": False}

    try:
        control.TabStop = True
    except Exception:
        pass

    controller = _find_core_controller(control)
    if controller is None:
        return {"control": True, "host": True, "same_host": True, "controller": False, "notified": False}

    notified = False

    def notify_parent(*_args: Any) -> None:
        nonlocal notified
        try:
            controller.NotifyParentWindowPositionChanged()
            notified = True
        except Exception:
            pass

    notify_parent()

    # Keep handlers alive on the EdgeChrome instance. Location/size changes can
    # alter an ancestor HWND after the WebView2 controller was created.
    handlers = getattr(edge_instance, _HANDLER_MARKER, None)
    if handlers is None:
        handlers = []
        try:
            host.LocationChanged += notify_parent
            handlers.append((host, "LocationChanged", notify_parent))
        except Exception:
            pass
        try:
            host.SizeChanged += notify_parent
            handlers.append((host, "SizeChanged", notify_parent))
        except Exception:
            pass
        setattr(edge_instance, _HANDLER_MARKER, handlers)

    return {"control": True, "host": True, "same_host": True, "controller": True, "notified": notified}


def install_pywebview_accessibility_host_patch(edge_module: Any | None = None) -> bool:
    """Patch pywebview's EdgeChromium ready boundary before any window exists."""
    if edge_module is None:
        import webview.platforms.edgechromium as edge_module  # type: ignore

    edge_class = getattr(edge_module, "EdgeChrome", None)
    if edge_class is None:
        return False
    if bool(getattr(edge_class, _PATCH_MARKER, False)):
        return True

    original = edge_class.on_webview_ready

    def on_webview_ready(self: Any, sender: Any, args: Any) -> Any:
        result = original(self, sender, args)
        state = repair_edgechromium_accessibility_host(self)
        setattr(self, "_acs_stage1_accessibility_host_state", state)
        return result

    edge_class.on_webview_ready = on_webview_ready
    setattr(edge_class, _PATCH_MARKER, True)
    return True
