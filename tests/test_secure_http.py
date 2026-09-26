from __future__ import annotations

from email.message import Message
import io
import socket
import unittest
from urllib.error import HTTPError, URLError

from acs.secure_http import (
    BoundedHttpsJsonTransport,
    SecureHttpError,
    TransportErrorCode,
)


class _Response:
    def __init__(self, body: bytes, *, status: int = 200, content_type: str = "application/json") -> None:
        self._body = io.BytesIO(body)
        self._status = status
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def getcode(self) -> int:
        return self._status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _Opener:
    def __init__(self, outcome) -> None:
        self.outcome = outcome
        self.calls = []

    def open(self, request, **kwargs):
        self.calls.append((request, kwargs))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class SecureHttpTests(unittest.TestCase):
    def test_get_json_accepts_https_and_vendor_json(self) -> None:
        opener = _Opener(_Response(b'{"ok":true}', content_type="application/problem+json; charset=utf-8"))
        transport = BoundedHttpsJsonTransport(opener=opener)
        response = transport.get_json("https://example.invalid/api")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.value, {"ok": True})
        self.assertEqual(response.content_type, "application/problem+json")
        request, kwargs = opener.calls[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertEqual(kwargs["timeout"], 15.0)

    def test_post_json_is_deterministic_utf8_and_bounded(self) -> None:
        opener = _Opener(_Response(b'{}'))
        transport = BoundedHttpsJsonTransport(opener=opener, max_request_bytes=64)
        transport.post_json("https://example.invalid/token", {"b": "є", "a": 1})
        request, _ = opener.calls[0]
        self.assertEqual(request.data, '{"b":"є","a":1}'.encode("utf-8"))
        self.assertIn("application/json", request.get_header("Content-type"))

        tiny = BoundedHttpsJsonTransport(opener=opener, max_request_bytes=4)
        with self.assertRaises(SecureHttpError) as caught:
            tiny.post_json("https://example.invalid/token", {"a": 1})
        self.assertEqual(caught.exception.code, TransportErrorCode.INVALID_REQUEST)

    def test_rejects_non_https_credentials_fragment_backslash_and_controls(self) -> None:
        invalid = [
            "http://example.invalid/",
            "https://user:secret@example.invalid/",
            "https://example.invalid/#fragment",
            "https://example.invalid/\\evil",
            "https://example.invalid/a\nb",
            "https:///missing-host",
            "https://example.invalid:99999/",
        ]
        transport = BoundedHttpsJsonTransport(opener=_Opener(_Response(b'{}')))
        for target in invalid:
            with self.subTest(target=target):
                with self.assertRaises(SecureHttpError) as caught:
                    transport.get_json(target)
                self.assertEqual(caught.exception.code, TransportErrorCode.INVALID_REQUEST)

    def test_rejects_header_injection_and_bad_types(self) -> None:
        transport = BoundedHttpsJsonTransport(opener=_Opener(_Response(b'{}')))
        for headers in [
            {"X-Test\nInjected": "x"},
            {"X-Test": "ok\r\nInjected: yes"},
            {"X-Test": "bad\x00value"},
            {"X-Test": 7},
        ]:
            with self.subTest(headers=headers):
                with self.assertRaises(SecureHttpError) as caught:
                    transport.get_json("https://example.invalid/", headers=headers)
                self.assertEqual(caught.exception.code, TransportErrorCode.INVALID_REQUEST)

    def test_redirect_http_error_timeout_and_network_have_bounded_taxonomy(self) -> None:
        cases = [
            (
                HTTPError("https://secret.invalid/path?token=very-secret", 302, "Found", {}, None),
                TransportErrorCode.REDIRECT,
                302,
            ),
            (
                HTTPError("https://secret.invalid/path?token=very-secret", 503, "Down", {}, None),
                TransportErrorCode.HTTP_STATUS,
                503,
            ),
            (URLError(socket.timeout("private timeout detail")), TransportErrorCode.TIMEOUT, None),
            (URLError("private DNS detail"), TransportErrorCode.NETWORK, None),
        ]
        for failure, expected, status in cases:
            with self.subTest(expected=expected):
                transport = BoundedHttpsJsonTransport(opener=_Opener(failure))
                with self.assertRaises(SecureHttpError) as caught:
                    transport.get_json("https://example.invalid/api", headers={"Authorization": "Bearer super-secret"})
                error = caught.exception
                self.assertEqual(error.code, expected)
                self.assertEqual(error.status, status)
                rendered = str(error)
                self.assertNotIn("secret.invalid", rendered)
                self.assertNotIn("super-secret", rendered)
                self.assertNotIn("private", rendered)

    def test_response_size_is_bounded_before_json_parse(self) -> None:
        opener = _Opener(_Response(b'{"payload":"' + b"x" * 128 + b'"}'))
        transport = BoundedHttpsJsonTransport(opener=opener, max_response_bytes=32)
        with self.assertRaises(SecureHttpError) as caught:
            transport.get_json("https://example.invalid/")
        self.assertEqual(caught.exception.code, TransportErrorCode.RESPONSE_TOO_LARGE)

    def test_content_type_and_json_fail_closed(self) -> None:
        cases = [
            (_Response(b'{}', content_type="text/html"), TransportErrorCode.INVALID_CONTENT_TYPE),
            (_Response(b'{bad json}'), TransportErrorCode.INVALID_JSON),
            (_Response(b'{"a":1,"a":2}'), TransportErrorCode.INVALID_JSON),
            (_Response(b'"\xff"'), TransportErrorCode.INVALID_JSON),
        ]
        for response, expected in cases:
            with self.subTest(expected=expected):
                transport = BoundedHttpsJsonTransport(opener=_Opener(response))
                with self.assertRaises(SecureHttpError) as caught:
                    transport.get_json("https://example.invalid/")
                self.assertEqual(caught.exception.code, expected)

    def test_non_2xx_response_object_fails_closed(self) -> None:
        transport = BoundedHttpsJsonTransport(opener=_Opener(_Response(b'{}', status=204)))
        self.assertEqual(transport.get_json("https://example.invalid/").status, 204)

        transport = BoundedHttpsJsonTransport(opener=_Opener(_Response(b'{}', status=418)))
        with self.assertRaises(SecureHttpError) as caught:
            transport.get_json("https://example.invalid/")
        self.assertEqual(caught.exception.code, TransportErrorCode.HTTP_STATUS)
        self.assertEqual(caught.exception.status, 418)

    def test_constructor_rejects_unbounded_configuration(self) -> None:
        for kwargs in [
            {"timeout_seconds": 0},
            {"timeout_seconds": 121},
            {"max_request_bytes": 0},
            {"max_request_bytes": 1024 * 1024 + 1},
            {"max_response_bytes": 0},
            {"max_response_bytes": 8 * 1024 * 1024 + 1},
        ]:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    BoundedHttpsJsonTransport(**kwargs)


if __name__ == "__main__":
    unittest.main()
