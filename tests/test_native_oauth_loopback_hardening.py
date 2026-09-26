from __future__ import annotations

import socket
import threading
import unittest
from unittest import mock
from urllib.parse import urlsplit

from acs.native_oauth_loopback import (
    NativeLoopbackCallback,
    NativeLoopbackError,
    open_system_browser,
)


AUTH_URL = "https://identity.example.invalid/authorize?client_id=public"


def _raw_exchange(port: int, request: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=2.0) as connection:
        connection.sendall(request)
        connection.shutdown(socket.SHUT_WR)
        chunks: list[bytes] = []
        while True:
            chunk = connection.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)


class NativeOAuthLoopbackHardeningTests(unittest.TestCase):
    def test_invalid_authorization_preflight_closes_bound_listener(self) -> None:
        listener = NativeLoopbackCallback.create(timeout_seconds=1.0)
        with self.assertRaisesRegex(NativeLoopbackError, "HTTPS"):
            listener.wait_for_callback(
                "http://identity.example.invalid/authorize",
                opener=lambda _: self.fail("browser must not be opened"),
            )
        with self.assertRaisesRegex(NativeLoopbackError, "closed"):
            _ = listener.redirect_uri

    def test_public_browser_helper_enforces_same_preflight(self) -> None:
        hostile_urls = (
            "http://identity.example.invalid/authorize",
            "https://identity.example.invalid\\attacker.invalid/authorize",
            "https://identity.example.invalid/authorize\x7f",
        )
        with mock.patch(
            "acs.native_oauth_loopback.webbrowser.open",
            side_effect=AssertionError("browser must not receive invalid URL"),
        ) as browser:
            for url in hostile_urls:
                with self.subTest(url=url), self.assertRaises(NativeLoopbackError):
                    open_system_browser(url)
        browser.assert_not_called()

    def test_public_browser_helper_sanitizes_browser_exception(self) -> None:
        with mock.patch(
            "acs.native_oauth_loopback.webbrowser.open",
            side_effect=RuntimeError("browser-provider-private-detail"),
        ):
            with self.assertRaises(NativeLoopbackError) as caught:
                open_system_browser(AUTH_URL)
        self.assertEqual(str(caught.exception), "authorization browser could not be opened")
        self.assertIsNone(caught.exception.__cause__)
        self.assertNotIn("provider-private", str(caught.exception))

    def test_duplicate_host_header_is_rejected_before_valid_callback(self) -> None:
        listener = NativeLoopbackCallback.create(timeout_seconds=2.0, max_attempts=3)
        port = urlsplit(listener.redirect_uri).port
        self.assertIsNotNone(port)
        responses: list[bytes] = []
        worker: threading.Thread | None = None

        def send_sequence() -> None:
            duplicate_host = (
                f"GET /oauth/callback?code=ambiguous HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{port}\r\n"
                "Host: attacker.invalid\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
            responses.append(_raw_exchange(port, duplicate_host))
            valid = (
                f"GET /oauth/callback?code=accepted HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{port}\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
            responses.append(_raw_exchange(port, valid))

        def opener(_: str) -> bool:
            nonlocal worker
            worker = threading.Thread(target=send_sequence)
            worker.start()
            return True

        callback = listener.wait_for_callback(AUTH_URL, opener=opener)
        if worker is not None:
            worker.join(timeout=2.0)
        self.assertTrue(callback.endswith("?code=accepted"))
        self.assertEqual(len(responses), 2)
        self.assertIn(b"400 Bad Request", responses[0])
        self.assertIn(b"200 OK", responses[1])
        self.assertNotIn(b"ambiguous", responses[0])
        self.assertNotIn(b"accepted", responses[1])

    def test_arbitrary_parsed_methods_consume_attempt_budget_and_use_static_error(self) -> None:
        listener = NativeLoopbackCallback.create(timeout_seconds=2.0, max_attempts=2)
        port = urlsplit(listener.redirect_uri).port
        self.assertIsNotNone(port)
        responses: list[bytes] = []
        worker: threading.Thread | None = None

        def send_sequence() -> None:
            for method in ("HEAD", "BREW"):
                request = (
                    f"{method} /oauth/callback?code=must-not-reflect HTTP/1.1\r\n"
                    f"Host: 127.0.0.1:{port}\r\n"
                    "Connection: close\r\n\r\n"
                ).encode("ascii")
                responses.append(_raw_exchange(port, request))

        def opener(_: str) -> bool:
            nonlocal worker
            worker = threading.Thread(target=send_sequence)
            worker.start()
            return True

        with self.assertRaisesRegex(NativeLoopbackError, "attempt limit exceeded"):
            listener.wait_for_callback(AUTH_URL, opener=opener)
        if worker is not None:
            worker.join(timeout=2.0)
        self.assertEqual(len(responses), 2)
        for response in responses:
            self.assertIn(b"405 Method Not Allowed", response)
            self.assertIn(b"Cache-Control: no-store", response)
            self.assertIn(b"Content-Security-Policy: default-src 'none'", response)
            self.assertNotIn(b"must-not-reflect", response)
            self.assertNotIn(b"Unsupported method", response)

    def test_non_finite_clock_fails_closed_without_waiting(self) -> None:
        for bad_time in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(bad_time=bad_time):
                listener = NativeLoopbackCallback.create(
                    timeout_seconds=1.0,
                    clock=lambda value=bad_time: value,
                )
                with self.assertRaisesRegex(NativeLoopbackError, "clock unavailable"):
                    listener.wait_for_callback(AUTH_URL, opener=lambda _: True)
                with self.assertRaisesRegex(NativeLoopbackError, "closed"):
                    _ = listener.redirect_uri


if __name__ == "__main__":
    unittest.main()
