from __future__ import annotations

"""Deterministic Chromium-safe loopback port policy for the packaged WebView2 UI.

pywebview 6.2.1 serves local files through a loopback HTTP server. When no
``http_port`` is supplied in private mode, its built-in selector chooses a random
port from 1023..65535. Chromium rejects a small set of restricted ports with
``ERR_UNSAFE_PORT``; 6666 is one of them. The release launcher installs this
policy before Stage 1 imports its WebView entrypoint so the packaged app can
never delegate port choice to pywebview's unrestricted random selector.
"""

from collections.abc import Callable, Iterable
from functools import wraps
import socket
from typing import Any


# Current Chromium restricted-port list from net/base/port_util.cc. Keeping the
# observed 6666 failure inside the same fail-closed policy prevents a regression
# where a future change merely swaps one unsafe random port for another.
CHROMIUM_RESTRICTED_PORTS = frozenset(
    {
        0,
        1,
        7,
        9,
        11,
        13,
        15,
        17,
        19,
        20,
        21,
        22,
        23,
        25,
        37,
        42,
        43,
        53,
        69,
        77,
        79,
        87,
        95,
        101,
        102,
        103,
        104,
        109,
        110,
        111,
        113,
        115,
        117,
        119,
        123,
        135,
        137,
        139,
        143,
        161,
        179,
        389,
        427,
        465,
        512,
        513,
        514,
        515,
        526,
        530,
        531,
        532,
        540,
        548,
        554,
        556,
        563,
        587,
        601,
        636,
        989,
        990,
        993,
        995,
        1719,
        1720,
        1723,
        2049,
        3659,
        4045,
        5060,
        5061,
        6000,
        6566,
        6665,
        6666,
        6667,
        6668,
        6669,
        6697,
        10080,
    }
)

# pywebview itself uses 42001 as DEFAULT_HTTP_PORT outside private mode. Stage 1
# keeps private mode, but deterministically walks a small vetted high-port range
# instead of allowing pywebview to choose any random port.
STAGE1_WEBVIEW_SAFE_PORTS = tuple(range(42001, 42033))
_HTTP_PORT_POSITION = 6


def validate_chromium_safe_port(port: int) -> int:
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("WebView loopback port must be an integer from 1 to 65535.")
    if port in CHROMIUM_RESTRICTED_PORTS:
        raise ValueError(f"Chromium-restricted WebView loopback port: {port}")
    return port


def _can_bind_loopback(port: int) -> bool:
    """Return True only when the exact loopback port is presently bindable."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def choose_chromium_safe_loopback_port(
    candidates: Iterable[int] = STAGE1_WEBVIEW_SAFE_PORTS,
    *,
    availability_probe: Callable[[int], bool] = _can_bind_loopback,
) -> int:
    """Select the first available vetted port; never return a restricted port."""

    for candidate in candidates:
        try:
            port = validate_chromium_safe_port(candidate)
        except ValueError:
            continue
        if availability_probe(port):
            return port
    raise RuntimeError("No Chromium-safe loopback port is available for Accessible Chess.")


def _with_safe_http_port(
    args: tuple[Any, ...], kwargs: dict[str, Any], safe_port: int
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Replace both positional and keyword ``http_port`` forms fail-closed."""

    positional = list(args)
    rewritten = dict(kwargs)
    if len(positional) > _HTTP_PORT_POSITION:
        positional[_HTTP_PORT_POSITION] = safe_port
        rewritten.pop("http_port", None)
    else:
        rewritten["http_port"] = safe_port
    return tuple(positional), rewritten


def install_pywebview_safe_local_server_port(
    webview_module: Any | None = None,
    *,
    port_selector: Callable[[], int] = choose_chromium_safe_loopback_port,
) -> bool:
    """Force pywebview's local server onto a vetted available Chromium-safe port.

    The wrapper uses pywebview's public ``start(..., http_port=...)`` contract.
    It is intentionally installed once and overrides any accidental caller port,
    including the observed blocked port 6666. If a safe port cannot be selected,
    startup fails rather than opening a browser error document.
    """

    if webview_module is None:
        import webview as webview_module

    if getattr(webview_module, "_accessible_chess_safe_server_installed", False):
        return callable(getattr(webview_module, "start", None))

    original_start = getattr(webview_module, "start", None)
    if not callable(original_start):
        return False

    @wraps(original_start)
    def safe_start(*args: Any, **kwargs: Any) -> Any:
        safe_port = validate_chromium_safe_port(port_selector())
        safe_args, safe_kwargs = _with_safe_http_port(args, kwargs, safe_port)
        setattr(webview_module, "_accessible_chess_safe_http_port", safe_port)
        return original_start(*safe_args, **safe_kwargs)

    setattr(webview_module, "_accessible_chess_original_start", original_start)
    setattr(webview_module, "_accessible_chess_safe_server_installed", True)
    setattr(webview_module, "start", safe_start)
    return True
