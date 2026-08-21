from __future__ import annotations

"""Packaged WebView2 accessibility boundaries for Stage 1."""

import os
from collections.abc import MutableMapping
from typing import Any

WEBVIEW2_BROWSER_ARGUMENTS_ENV = "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"
WEBVIEW2_WAIT_FOR_SCRIPT_DEBUGGER_ENV = "WEBVIEW2_WAIT_FOR_SCRIPT_DEBUGGER"
WEBVIEW2_PIPE_FOR_SCRIPT_DEBUGGER_ENV = "WEBVIEW2_PIPE_FOR_SCRIPT_DEBUGGER"
FORCE_RENDERER_ACCESSIBILITY = "--force-renderer-accessibility"
_PATCH_MARKER = "_acs_stage1_accessibility_host_patched"
_HANDLER_MARKER = "_acs_stage1_accessibility_host_handlers"

_BLOCKED_BROWSER_ARGUMENTS = frozenset(
    {
        "--remote-debugging-port",
        "--remote-debugging-address",
        "--remote-debugging-pipe",
        "--remote-allow-origins",
        "--disable-web-security",
        "--allow-running-insecure-content",
        "--allow-file-access-from-files",
        "--allow-universal-access-from-files",
        "--ignore-certificate-errors",
        "--no-sandbox",
        "--disable-site-isolation-trials",
        "--load-extension",
        "--disable-extensions-except",
    }
)
_REMOTE_DEBUG_FEATURE = "msedgedevtoolswdpremotedebugging"
_DEBUGGER_ENV_VARS = (
    WEBVIEW2_WAIT_FOR_SCRIPT_DEBUGGER_ENV,
    WEBVIEW2_PIPE_FOR_SCRIPT_DEBUGGER_ENV,
)


def _unquote_token(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {"'", '"'}:
        return token[1:-1]
    return token


def _sanitize_browser_arguments(value: str) -> str:
    """Drop release-incompatible WebView2 switches without leaving values behind."""
    tokens = value.split()
    kept: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        comparable = _unquote_token(token)
        name = comparable.split("=", 1)[0].casefold()
        blocked_feature = (
            name == "--enable-features"
            and _REMOTE_DEBUG_FEATURE in comparable.casefold()
        )
        split_feature = False
        if name == "--enable-features" and "=" not in comparable and index + 1 < len(tokens):
            following = _unquote_token(tokens[index + 1])
            split_feature = (
                not following.startswith("--")
                and _REMOTE_DEBUG_FEATURE in following.casefold()
            )
        if name in _BLOCKED_BROWSER_ARGUMENTS or blocked_feature or split_feature:
            if "=" not in comparable and index + 1 < len(tokens):
                following = _unquote_token(tokens[index + 1])
                if not following.startswith("--"):
                    index += 2
                    continue
            index += 1
            continue
        kept.append(token)
        index += 1
    return " ".join(kept)


def enable_webview2_renderer_accessibility(
    environment: MutableMapping[str, str] | None = None,
) -> str:
    """Preserve benign browser arguments while closing debugger exposure."""
    env = os.environ if environment is None else environment
    for name in _DEBUGGER_ENV_VARS:
        env.pop(name, None)
    current = _sanitize_browser_arguments(str(env.get(WEBVIEW2_BROWSER_ARGUMENTS_ENV, "")).strip())
    tokens = current.split()
    if not any(
        token == FORCE_RENDERER_ACCESSIBILITY
        or token.startswith(FORCE_RENDERER_ACCESSIBILITY + "=")
        for token in tokens
    ):
        current = (current + " " + FORCE_RENDERER_ACCESSIBILITY).strip()
    env[WEBVIEW2_BROWSER_ARGUMENTS_ENV] = current
    return current


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
    """Bind the real WebView2 controller to its actual visible WinForms host."""
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

    original = getattr(edge_class, "on_webview_ready", None)
    if not callable(original):
        return False

    def on_webview_ready(self: Any, sender: Any, args: Any) -> Any:
        result = original(self, sender, args)
        state = repair_edgechromium_accessibility_host(self)
        setattr(self, "_acs_stage1_accessibility_host_state", state)
        return result

    edge_class.on_webview_ready = on_webview_ready
    setattr(edge_class, _PATCH_MARKER, True)
    return True
