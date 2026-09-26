from __future__ import annotations

"""Bounded native-browser loopback callback transport.

This module deliberately owns no OAuth/OIDC semantic validation.  It opens a
system browser for an already-constructed HTTPS authorization URL, receives one
callback on a literal IPv4 loopback listener, and returns the raw callback URL
to the canonical OAuth authority.  State, code/error, redirect and token rules
remain outside this transport boundary.
"""

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
import math
import time
from typing import Callable
from urllib.parse import urlsplit
import webbrowser


class NativeLoopbackError(RuntimeError):
    """Bounded failure from the native browser/loopback lifecycle."""


BrowserOpener = Callable[[str], bool]
Clock = Callable[[], float]

_MAX_AUTHORIZATION_URL = 16384
_MAX_CALLBACK_TARGET = 8192
_MAX_CALLBACK_PATH = 512
_MAX_ATTEMPTS = 16
_MAX_TIMEOUT_SECONDS = 300.0
_SUCCESS_HTML = (
    b"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
    b"<title>Accessible Chess sign-in</title></head><body>"
    b"<h1>Sign-in received</h1><p>You can return to Accessible Chess.</p>"
    b"</body></html>"
)
_ERROR_HTML = (
    b"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
    b"<title>Accessible Chess sign-in</title></head><body>"
    b"<h1>Sign-in callback not accepted</h1>"
    b"<p>Return to Accessible Chess and try again.</p></body></html>"
)


def _validated_callback_path(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_CALLBACK_PATH:
        raise NativeLoopbackError("invalid callback path")
    if not value.startswith("/") or value.startswith("//"):
        raise NativeLoopbackError("invalid callback path")
    if any(ord(char) < 0x20 or ord(char) == 0x7F or char in "?#\\" for char in value):
        raise NativeLoopbackError("invalid callback path")
    if any(segment in (".", "..") for segment in value.split("/")):
        raise NativeLoopbackError("invalid callback path")
    return value


def _validated_authorization_url(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise NativeLoopbackError("invalid authorization URL")
    if len(value) > _MAX_AUTHORIZATION_URL or any(
        ord(char) < 0x20 or ord(char) == 0x7F for char in value
    ):
        raise NativeLoopbackError("invalid authorization URL")
    if "\\" in value:
        raise NativeLoopbackError("invalid authorization URL")
    try:
        parsed = urlsplit(value)
        _ = parsed.hostname
        _ = parsed.port
    except (TypeError, ValueError):
        raise NativeLoopbackError("invalid authorization URL") from None
    if parsed.scheme != "https" or not parsed.netloc or not parsed.hostname:
        raise NativeLoopbackError("authorization URL must use HTTPS")
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise NativeLoopbackError("invalid authorization URL")
    return value


def open_system_browser(url: str) -> bool:
    """Validate and open an authorization URL in the user's default browser."""

    target = _validated_authorization_url(url)
    try:
        return bool(webbrowser.open(target, new=2, autoraise=True))
    except Exception:
        raise NativeLoopbackError("authorization browser could not be opened") from None


class _LoopbackServer(HTTPServer):
    allow_reuse_address = False

    def __init__(self, server_address: tuple[str, int], callback_path: str):
        super().__init__(server_address, _CallbackHandler, bind_and_activate=True)
        self.callback_path = callback_path
        self.accepted_callback: str | None = None
        self.request_count = 0


class _CallbackHandler(BaseHTTPRequestHandler):
    server: _LoopbackServer
    protocol_version = "HTTP/1.1"
    server_version = "AccessibleChessLoopback"
    sys_version = ""

    def log_message(self, format: str, *args: object) -> None:
        return

    def _respond(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'none'; img-src 'none'")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def do_GET(self) -> None:
        self.server.request_count += 1
        if self.client_address[0] != "127.0.0.1":
            self._respond(403, _ERROR_HTML)
            return
        expected_host = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get_all("Host", []) != [expected_host]:
            self._respond(400, _ERROR_HTML)
            return
        target = self.path
        if not isinstance(target, str) or len(target) > _MAX_CALLBACK_TARGET:
            self._respond(414, _ERROR_HTML)
            return
        try:
            parsed = urlsplit(target)
        except ValueError:
            self._respond(400, _ERROR_HTML)
            return
        if parsed.scheme or parsed.netloc or parsed.fragment or parsed.path != self.server.callback_path:
            self._respond(404, _ERROR_HTML)
            return
        self.server.accepted_callback = f"http://127.0.0.1:{self.server.server_port}{target}"
        self._respond(200, _SUCCESS_HTML)

    def do_POST(self) -> None:
        self.server.request_count += 1
        self._respond(405, _ERROR_HTML)

    do_PUT = do_POST
    do_DELETE = do_POST
    do_PATCH = do_POST


@dataclass
class NativeLoopbackCallback:
    """One-use literal-loopback callback listener for a native auth attempt."""

    _server: _LoopbackServer
    timeout_seconds: float
    max_attempts: int
    clock: Clock = time.monotonic
    _closed: bool = False
    _used: bool = False

    @classmethod
    def create(
        cls,
        *,
        callback_path: str = "/oauth/callback",
        timeout_seconds: float = 180.0,
        max_attempts: int = 8,
        clock: Clock = time.monotonic,
    ) -> "NativeLoopbackCallback":
        path = _validated_callback_path(callback_path)
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
            raise NativeLoopbackError("invalid callback timeout")
        timeout = float(timeout_seconds)
        if not 0.1 <= timeout <= _MAX_TIMEOUT_SECONDS:
            raise NativeLoopbackError("invalid callback timeout")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
            raise NativeLoopbackError("invalid callback attempt limit")
        if not 1 <= max_attempts <= _MAX_ATTEMPTS:
            raise NativeLoopbackError("invalid callback attempt limit")
        try:
            server = _LoopbackServer(("127.0.0.1", 0), path)
        except OSError:
            raise NativeLoopbackError("loopback listener unavailable") from None
        return cls(server, timeout, max_attempts, clock)

    @property
    def redirect_uri(self) -> str:
        if self._closed:
            raise NativeLoopbackError("loopback listener is closed")
        return f"http://127.0.0.1:{self._server.server_port}{self._server.callback_path}"

    def wait_for_callback(
        self,
        authorization_url: str,
        *,
        opener: BrowserOpener = open_system_browser,
    ) -> str:
        if self._closed:
            raise NativeLoopbackError("loopback listener is closed")
        if self._used:
            raise NativeLoopbackError("loopback listener is single-use")
        try:
            url = _validated_authorization_url(authorization_url)
        except NativeLoopbackError:
            self.close()
            raise
        self._used = True
        try:
            opened = opener(url)
        except NativeLoopbackError:
            self.close()
            raise
        except Exception:
            self.close()
            raise NativeLoopbackError("authorization browser could not be opened") from None
        if opened is not True:
            self.close()
            raise NativeLoopbackError("authorization browser could not be opened")

        try:
            try:
                start = float(self.clock())
            except Exception:
                raise NativeLoopbackError("callback clock unavailable") from None
            if not math.isfinite(start) or start < 0:
                raise NativeLoopbackError("callback clock unavailable")
            deadline = start + self.timeout_seconds
            attempts_at_start = self._server.request_count
            while self._server.accepted_callback is None:
                try:
                    now = float(self.clock())
                except Exception:
                    raise NativeLoopbackError("callback clock unavailable") from None
                if not math.isfinite(now) or now < 0:
                    raise NativeLoopbackError("callback clock unavailable")
                remaining = deadline - now
                if remaining <= 0:
                    raise NativeLoopbackError("authorization callback timed out")
                attempts = self._server.request_count - attempts_at_start
                if attempts >= self.max_attempts:
                    raise NativeLoopbackError("authorization callback attempt limit exceeded")
                self._server.timeout = remaining
                self._server.handle_request()
            return self._server.accepted_callback
        except NativeLoopbackError:
            raise
        except Exception:
            raise NativeLoopbackError("authorization callback failed") from None
        finally:
            self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._server.server_close()
        except Exception:
            pass

    def __enter__(self) -> "NativeLoopbackCallback":
        if self._closed:
            raise NativeLoopbackError("loopback listener is closed")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


__all__ = [
    "BrowserOpener",
    "NativeLoopbackCallback",
    "NativeLoopbackError",
    "open_system_browser",
]
