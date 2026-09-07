import unittest

from acs.full_product_ui_shell import UILanguage, concise_user_error


class V2UserErrorSurfacePrivacyTests(unittest.TestCase):
    def test_internal_paths_exception_types_and_uci_protocol_fail_closed(self):
        raw_messages = (
            "FileNotFoundError: /home/alice/private/book.pgn",
            "RuntimeError: failed while reading /tmp/accessible-chess/cache.bin",
            r"PermissionError: \\server\private-share\secret.cbh",
            "ValueError: provider returned malformed payload",
            "bestmove e2e4 ponder e7e5",
            "info depth 18 score cp 34 pv e2e4 e7e5",
            "setoption name MultiPV value 5",
            "position fen rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            "go movetime 1000",
            "uciok",
            "readyok",
        )
        for raw in raw_messages:
            with self.subTest(raw=raw):
                self.assertEqual(
                    "The action could not be completed.",
                    concise_user_error(raw, language=UILanguage.EN),
                )
                self.assertEqual(
                    "Не вдалося виконати дію.",
                    concise_user_error(raw, language=UILanguage.UA),
                )

    def test_safe_domain_errors_still_reach_user_concisely(self):
        for message in (
            "Invalid PGN tag.",
            "No game is open.",
            "The selected variation is unavailable.",
            "Import was cancelled.",
        ):
            with self.subTest(message=message):
                self.assertEqual(
                    message,
                    concise_user_error(message, language=UILanguage.EN),
                )

    def test_long_or_empty_messages_keep_existing_generic_fallback(self):
        self.assertEqual(
            "The action could not be completed.",
            concise_user_error("", language=UILanguage.EN),
        )
        self.assertEqual(
            "The action could not be completed.",
            concise_user_error("x" * 181, language=UILanguage.EN),
        )


if __name__ == "__main__":
    unittest.main()
