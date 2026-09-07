import unittest

from acs.full_product_ui_shell import UILanguage, concise_user_error


class V2UserErrorSurfacePrivacyTests(unittest.TestCase):
    def test_internal_paths_exception_types_and_provider_terms_fail_closed(self):
        raw_messages = (
            "FileNotFoundError: /home/alice/private/book.pgn",
            "RuntimeError: failed while reading /tmp/accessible-chess/cache.bin",
            r"PermissionError: \\server\private-share\secret.cbh",
            r"could not open C:Users\Alice\private\game.pgn",
            r"could not open \\?\C:\Users\Alice\private\game.pgn",
            "missing /srv/accessible-chess/private/state.db",
            "file:///C:/Users/Alice/private/game.pgn",
            "ValueError: provider returned malformed payload",
            "Engine backend process exited unexpectedly.",
            "subprocess returned exit status 2",
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

    def test_raw_uci_protocol_is_never_projected_to_user_speech(self):
        raw_messages = (
            "uci",
            "isready",
            "uciok",
            "readyok",
            "id name Stockfish 18",
            "id author Stockfish developers",
            "option name Threads type spin default 1 min 1 max 1024",
            "bestmove e2e4 ponder e7e5",
            "info depth 18 score cp 34 pv e2e4 e7e5",
            "setoption name MultiPV value 5",
            "position fen rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            "position startpos moves e2e4 e7e5",
            "go movetime 1000",
            "go infinite",
            "go wtime 1000 btime 1000",
            "ponderhit",
            "stop",
            "quit",
        )
        for raw in raw_messages:
            with self.subTest(raw=raw):
                self.assertEqual(
                    "The action could not be completed.",
                    concise_user_error(raw, language=UILanguage.EN),
                )

    def test_safe_domain_errors_and_public_urls_still_reach_user_concisely(self):
        for message in (
            "Invalid PGN tag.",
            "No game is open.",
            "The selected variation is unavailable.",
            "Import was cancelled.",
            "Invalid FEN.",
            "File is already open.",
            "Invalid URL https://example.com/help",
            "Invalid command /help",
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
