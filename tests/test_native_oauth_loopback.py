from __future__ import annotations

import socket
import threading
import time
import unittest
from urllib.parse import urlsplit

from acs.native_oauth_loopback import NativeLoopbackCallback, NativeLoopbackError


AUTH_URL = "https://identity.example.invalid/authorize?client_id=public&state=opaque"


def _exchange(port: int, request: bytes) -> bytes:
    last_error: OSError | None = None
    for _ in range(50):
        try:
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
        except OSError as exc:
            last_error = exc
            time.sleep(0.01)
    assert last_error is not None
    raise last_error


def _request(port: int, target: str, *, method: str = "GET", host: str | None = None) -> bytes:
    authority = host if host is not None else f"127.0.0.1:{port}"
    wire = (
        f"{method} {target} HTTP/1.1\r\n"
        f"Host: {authority}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    return _exchange(port, wire)


class NativeOAuthLoopbackTests(unittest.TestCase):
    def test_success_returns_raw_callback_without_reflecting_secret(self) -> None:
        listener = NativeLoopbackCallback.create(timeout_seconds=2.0)
        redirect = urlsplit(listener.redirect_uri)
        port = redirect.port
        self.assertIsNotNone(port)
        responses: list[bytes] = []
        worker: threading.Thread | None = None

        def opener(url: str) -> bool:
            nonlocal worker
            self.assertEqual(url, AUTH_URL)
            worker = threading.Thread(
                target=lambda: responses.append(
                    _request(port, "/oauth/callback?code=private-code&state=private-state")
                )
            )
            worker.start()
            return True

        callback = listener.wait_for_callback(AUTH_URL, opener=opener)
        if worker is not None:
            worker.join(timeout=2.0)
        self.assertEqual(
            callback,
            f"http://127.0.0.1:{port}/oauth/callback?code=private-code&state=private-state",
        )
        self.assertEqual(len(responses), 1)
        response = responses[0]
        self.assertIn(b"200 OK", response)
        self.assertIn(b"Cache-Control: no-store", response)
        self.assertIn(b"Content-Security-Policy: default-src 'none'", response)
        self.assertNotIn(b"private-code", response)
        self.assertNotIn(b"private-state", response)
        with self.assertRaisesRegex(NativeLoopbackError, "closed"):
            _ = listener.redirect_uri

    def test_wrong_host_path_and_method_do_not_consume_valid_callback(self) -> None:
        listener = NativeLoopbackCallback.create(timeout_seconds=3.0, max_attempts=6)
        port = urlsplit(listener.redirect_uri).port
        self.assertIsNotNone(port)
        responses: list[bytes] = []
        worker: threading.Thread | None = None

        def send_sequence() -> None:
            responses.append(_request(port, "/oauth/callback?code=x", host="localhost"))
            responses.append(_request(port, "/wrong?code=x"))
            responses.append(_request(port, "/oauth/callback?code=x", method="POST"))
            responses.append(_request(port, "/oauth/callback?code=accepted&state=s"))

        def opener(_: str) -> bool:
            nonlocal worker
            worker = threading.Thread(target=send_sequence)
            worker.start()
            return True

        callback = listener.wait_for_callback(AUTH_URL, opener=opener)
        if worker is not None:
            worker.join(timeout=3.0)
        self.assertTrue(callback.endswith("?code=accepted&state=s"))
        self.assertEqual(len(responses), 4)
        self.assertIn(b"400 Bad Request", responses[0])
        self.assertIn(b"404 Not Found", responses[1])
        self.assertIn(b"405 Method Not Allowed", responses[2])
        self.assertIn(b"200 OK", responses[3])

    def test_attempt_limit_fails_closed_and_closes_listener(self) -> None:
        listener = NativeLoopbackCallback.create(timeout_seconds=3.0, max_attempts=2)
        port = urlsplit(listener.redirect_uri).port
        worker: threading.Thread | None = None

        def send_bad_requests() -> None:
            _request(port, "/wrong-one")
            _request(port, "/wrong-two")

        def opener(_: str) -> bool:
            nonlocal worker
            worker = threading.Thread(target=send_bad_requests)
            worker.start()
            return True

        with self.assertRaisesRegex(NativeLoopbackError, "attempt limit exceeded"):
            listener.wait_for_callback(AUTH_URL, opener=opener)
        if worker is not None:
            worker.join(timeout=3.0)
        with self.assertRaisesRegex(NativeLoopbackError, "closed"):
            _ = listener.redirect_uri

    def test_timeout_is_bounded_and_closes_listener(self) -> None:
        listener = NativeLoopbackCallback.create(timeout_seconds=0.1)
        started = time.monotonic()
        with self.assertRaisesRegex(NativeLoopbackError, "timed out"):
            listener.wait_for_callback(AUTH_URL, opener=lambda _: True)
        self.assertLess(time.monotonic() - started, 1.5)
        with self.assertRaisesRegex(NativeLoopbackError, "closed"):
            _ = listener.redirect_uri

    def test_browser_failure_is_bounded_and_does_not_echo_detail(self) -> None:
        listener = NativeLoopbackCallback.create(timeout_seconds=1.0)

        def failing(_: str) -> bool:
            raise RuntimeError("private provider/browser detail")

        with self.assertRaisesRegex(NativeLoopbackError, "browser could not be opened") as caught:
            listener.wait_for_callback(AUTH_URL, opener=failing)
        self.assertNotIn("private", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

        second = NativeLoopbackCallback.create(timeout_seconds=1.0)
        with self.assertRaisesRegex(NativeLoopbackError, "browser could not be opened"):
            second.wait_for_callback(AUTH_URL, opener=lambda _: False)

    def test_authorization_url_is_https_only_and_browser_safe(self) -> None:
        invalid = (
            "http://identity.example.invalid/authorize",
            "https://user:pass@identity.example.invalid/authorize",
            "https://identity.example.invalid/authorize#fragment",
            "https://identity.example.invalid\\@evil.invalid/authorize",
            " data:text/plain,x",
            "",
        )
        for value in invalid:
            with self.subTest(value=value):
                listener = NativeLoopbackCallback.create(timeout_seconds=1.0)
                called = False

                def opener(_: str) -> bool:
                    nonlocal called
                    called = True
                    return True

                with self.assertRaises(NativeLoopbackError):
                    listener.wait_for_callback(value, opener=opener)
                self.assertFalse(called)
                listener.close()

    def test_callback_path_and_configuration_are_strictly_bounded(self) -> None:
        for path in ("oauth/callback", "//oauth", "/a/../b", "/oauth?x=1", "/oauth#x", "/oauth\\x"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(NativeLoopbackError, "callback path"):
                    NativeLoopbackCallback.create(callback_path=path)
        for timeout in (0, 301, True, "1"):
            with self.subTest(timeout=timeout):
                with self.assertRaisesRegex(NativeLoopbackError, "timeout"):
                    NativeLoopbackCallback.create(timeout_seconds=timeout)
        for attempts in (0, 17, True, 1.5):
            with self.subTest(attempts=attempts):
                with self.assertRaisesRegex(NativeLoopbackError, "attempt limit"):
                    NativeLoopbackCallback.create(max_attempts=attempts)

    def test_listener_is_literal_ipv4_loopback_and_single_use(self) -> None:
        listener = NativeLoopbackCallback.create(timeout_seconds=2.0)
        parsed = urlsplit(listener.redirect_uri)
        self.assertEqual(parsed.scheme, "http")
        self.assertEqual(parsed.hostname, "127.0.0.1")
        self.assertIsNotNone(parsed.port)
        port = parsed.port
        worker: threading.Thread | None = None

        def opener(_: str) -> bool:
            nonlocal worker
            worker = threading.Thread(target=lambda: _request(port, "/oauth/callback?code=one"))
            worker.start()
            return True

        listener.wait_for_callback(AUTH_URL, opener=opener)
        if worker is not None:
            worker.join(timeout=2.0)
        with self.assertRaisesRegex(NativeLoopbackError, "closed"):
            listener.wait_for_callback(AUTH_URL, opener=lambda _: True)


if __name__ == "__main__":
    unittest.main()
