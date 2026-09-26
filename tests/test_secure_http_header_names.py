from __future__ import annotations

from email.message import Message
import io
import unittest

from acs.secure_http import BoundedHttpsJsonTransport, SecureHttpError, TransportErrorCode


class _Response:
    def __init__(self) -> None:
        self._body = io.BytesIO(b"{}")
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def getcode(self) -> int:
        return 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _Opener:
    def open(self, request, **kwargs):
        return _Response()


class SecureHttpHeaderNameTests(unittest.TestCase):
    def test_non_token_header_names_fail_closed(self) -> None:
        transport = BoundedHttpsJsonTransport(opener=_Opener())
        for name in (
            "Bad:Name",
            "Bad Name",
            "Bad\tName",
            "Bad/Name",
            "Bad(Name)",
            "Nämé",
        ):
            with self.subTest(name=name), self.assertRaises(SecureHttpError) as caught:
                transport.get_json("https://example.invalid/", headers={name: "value"})
            self.assertEqual(caught.exception.code, TransportErrorCode.INVALID_REQUEST)
            self.assertIsNone(caught.exception.__cause__)

    def test_rfc_token_punctuation_header_name_remains_allowed(self) -> None:
        transport = BoundedHttpsJsonTransport(opener=_Opener())
        response = transport.get_json(
            "https://example.invalid/",
            headers={"X-Client_Trace~1": "opaque"},
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(response.value, {})


if __name__ == "__main__":
    unittest.main()
