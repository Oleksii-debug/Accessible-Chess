from __future__ import annotations

import io
import logging
import unittest

from acs.secret_redaction import (
    REDACTED,
    RedactingFormatter,
    SecretRedactionError,
    is_secret_key,
    redact_diagnostic,
    redact_text,
)


class SecretRedactionTests(unittest.TestCase):
    def test_secret_key_normalization_covers_common_provider_neutral_names(self) -> None:
        for key in (
            "Authorization",
            "proxy-authorization",
            "access_token",
            "Access-Token",
            "refreshToken",
            "client_secret",
            "API-KEY",
            "license_key",
            "password",
            "Cookie",
            "Set-Cookie",
        ):
            with self.subTest(key=key):
                self.assertTrue(is_secret_key(key))
        self.assertFalse(is_secret_key("account_id"))
        self.assertFalse(is_secret_key("feature_id"))
        self.assertFalse(is_secret_key("fen"))

    def test_nested_structured_diagnostic_redacts_secret_values_only(self) -> None:
        source = {
            "account_id": "acct-42",
            "authorization": "Bearer top-secret",
            "nested": {
                "refresh_token": "refresh-secret",
                "feature_id": "analysis.engine",
            },
            "events": [
                {"client-secret": "client-secret-value", "state": "connected"},
                "ordinary text",
            ],
        }
        sanitized = redact_diagnostic(source)
        self.assertEqual(sanitized["account_id"], "acct-42")
        self.assertEqual(sanitized["authorization"], REDACTED)
        self.assertEqual(sanitized["nested"]["refresh_token"], REDACTED)
        self.assertEqual(sanitized["nested"]["feature_id"], "analysis.engine")
        self.assertEqual(sanitized["events"][0]["client-secret"], REDACTED)
        self.assertEqual(sanitized["events"][0]["state"], "connected")
        self.assertEqual(source["authorization"], "Bearer top-secret")

    def test_text_redaction_covers_headers_assignments_json_and_bearer(self) -> None:
        raw = (
            "Authorization: Bearer abc.def.ghi\n"
            "refresh_token=refresh-123; client_secret:secret-456\n"
            "payload={'access_token':'json-token','account_id':'acct-1'}\n"
            "fallback Bearer loose-token"
        )
        output = redact_text(raw)
        for secret in ("abc.def.ghi", "refresh-123", "secret-456", "json-token", "loose-token"):
            self.assertNotIn(secret, output)
        self.assertIn("account_id", output)
        self.assertGreaterEqual(output.count(REDACTED), 5)

    def test_quoted_assignments_redact_entire_secret_value(self) -> None:
        raw = (
            'password="correct horse battery" '
            "client_secret='two word secret' account_id=acct-8"
        )
        output = redact_text(raw)
        self.assertNotIn("correct horse battery", output)
        self.assertNotIn("horse battery", output)
        self.assertNotIn("two word secret", output)
        self.assertIn('password="' + REDACTED + '"', output)
        self.assertIn("client_secret='" + REDACTED + "'", output)
        self.assertIn("account_id=acct-8", output)

    def test_quoted_assignment_with_escaped_quote_redacts_the_entire_value(self) -> None:
        raw = r'password="correct \"horse\" battery" account_id=acct-esc'
        output = redact_text(raw)
        self.assertNotIn("correct", output)
        self.assertNotIn("horse", output)
        self.assertNotIn("battery", output)
        self.assertIn('password="' + REDACTED + '"', output)
        self.assertIn("account_id=acct-esc", output)

    def test_cookie_headers_redact_the_complete_header_value(self) -> None:
        raw = (
            "Cookie: sessionid=session-secret; theme=dark; csrftoken=csrf-secret\n"
            "Set-Cookie: refresh=refresh-secret; Path=/; HttpOnly; SameSite=Lax\n"
            "account_id=acct-7"
        )
        output = redact_text(raw)
        for secret in ("session-secret", "csrf-secret", "refresh-secret"):
            self.assertNotIn(secret, output)
        self.assertNotIn("theme=dark", output)
        self.assertNotIn("HttpOnly", output)
        self.assertIn("Cookie: " + REDACTED, output)
        self.assertIn("Set-Cookie: " + REDACTED, output)
        self.assertIn("account_id=acct-7", output)

    def test_oauth_url_query_secrets_are_redacted_but_navigation_context_survives(self) -> None:
        raw = (
            "redirect https://login.example/callback?code=oauth-code&state=csrf-state&"
            "account_id=acct-5&lang=uk then continue"
        )
        output = redact_text(raw)
        self.assertNotIn("oauth-code", output)
        self.assertNotIn("csrf-state", output)
        self.assertIn("account_id=acct-5", output)
        self.assertIn("lang=uk", output)

    def test_oauth_url_fragment_secrets_are_redacted_without_losing_safe_context(self) -> None:
        raw = (
            "callback https://login.example/callback?lang=uk#access_token=fragment-secret&"
            "state=fragment-state&account_id=acct-9"
        )
        output = redact_text(raw)
        self.assertNotIn("fragment-secret", output)
        self.assertNotIn("fragment-state", output)
        self.assertIn("lang=uk", output)
        self.assertIn("account_id=acct-9", output)
        self.assertIn("access_token=%5BREDACTED%5D", output)
        self.assertEqual(
            redact_text("open https://docs.example/guide#keyboard-navigation"),
            "open https://docs.example/guide#keyboard-navigation",
        )

    def test_chess_text_is_not_misclassified_as_secret(self) -> None:
        ordinary = (
            '[Event "Training"]\n[Site "Local"]\n1. e4 e5 2. Nf3 Nc6\n'
            "FEN r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3\n"
            "token advantage is a coaching phrase; code review is ordinary prose"
        )
        self.assertEqual(redact_text(ordinary), ordinary)
        self.assertEqual(redact_diagnostic({"pgn": ordinary, "fen": ordinary})["pgn"], ordinary)

    def test_binary_and_unknown_objects_never_render_their_payload(self) -> None:
        class Dangerous:
            def __repr__(self) -> str:
                raise AssertionError("repr must not run")

            def __str__(self) -> str:
                raise AssertionError("str must not run")

        sanitized = redact_diagnostic({"blob": b"super-secret-binary", "object": Dangerous()})
        self.assertEqual(sanitized["blob"], "<binary:19 bytes>")
        self.assertIn("Dangerous", sanitized["object"])
        self.assertNotIn("super-secret", sanitized["blob"])

    def test_hostile_mapping_key_fails_closed_without_text_conversion(self) -> None:
        conversions: list[str] = []

        class DangerousKey:
            def __hash__(self) -> int:
                return 1

            def __repr__(self) -> str:
                conversions.append("repr")
                raise AssertionError("repr must not run")

            def __str__(self) -> str:
                conversions.append("str")
                raise AssertionError("str must not run")

        key = DangerousKey()
        self.assertFalse(is_secret_key(key))
        with self.assertRaisesRegex(SecretRedactionError, "mapping keys must be plain text"):
            redact_diagnostic({key: "Bearer must-not-be-rendered"})
        self.assertEqual(conversions, [])

    def test_text_subclass_cannot_inject_custom_string_conversion(self) -> None:
        conversions: list[str] = []

        class DangerousText(str):
            def __str__(self) -> str:
                conversions.append("str")
                raise AssertionError("str must not run")

        value = DangerousText("Authorization: Bearer secret")
        sanitized = redact_diagnostic({"value": value})
        self.assertIn("DangerousText", sanitized["value"])
        self.assertEqual(conversions, [])
        with self.assertRaisesRegex(SecretRedactionError, "plain text"):
            redact_text(value)
        self.assertEqual(conversions, [])

    def test_cycles_and_excessive_depth_fail_closed(self) -> None:
        cyclic: dict[str, object] = {}
        cyclic["self"] = cyclic
        with self.assertRaisesRegex(SecretRedactionError, "cyclic"):
            redact_diagnostic(cyclic)

        deep: object = "leaf"
        for _ in range(5):
            deep = [deep]
        with self.assertRaisesRegex(SecretRedactionError, "depth limit"):
            redact_diagnostic(deep, max_depth=2)

    def test_redacting_formatter_scrubs_message_args_and_exception_text(self) -> None:
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(RedactingFormatter("%(levelname)s %(message)s"))
        logger = logging.getLogger("accessible_chess_test_redaction")
        logger.handlers.clear()
        logger.propagate = False
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        try:
            logger.info("request access_token=%s account=%s", "arg-secret", "acct-7")
            try:
                raise RuntimeError("Authorization: Bearer exception-secret")
            except RuntimeError:
                logger.exception("request failed client_secret=message-secret")
        finally:
            logger.removeHandler(handler)
            handler.close()

        output = stream.getvalue()
        for secret in ("arg-secret", "exception-secret", "message-secret"):
            self.assertNotIn(secret, output)
        self.assertIn("acct-7", output)
        self.assertIn(REDACTED, output)
        self.assertIn("RuntimeError", output)

    def test_formatter_does_not_mutate_shared_log_record(self) -> None:
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="access_token=%s",
            args=("secret-value",),
            exc_info=None,
        )
        output = RedactingFormatter("%(message)s").format(record)
        self.assertNotIn("secret-value", output)
        self.assertEqual(record.msg, "access_token=%s")
        self.assertEqual(record.args, ("secret-value",))


if __name__ == "__main__":
    unittest.main()