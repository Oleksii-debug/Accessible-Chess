import unittest
from pathlib import Path

from acs.full_product_ui_shell import UILanguage
from acs.pgn_webview_projection import _bounded_text


class V2PgnWebViewPathPrivacyTests(unittest.TestCase):
    def _project(self, text: str, *, language: UILanguage = UILanguage.EN) -> str:
        return _bounded_text(text, language=language, limit=1200)

    def test_cross_platform_private_path_tokens_are_redacted(self):
        cases = (
            (r"C:\Users\PrivateUser\Documents\book.pgn", "PrivateUser"),
            (r"C:Users\PrivateUser\Documents\book.pgn", "PrivateUser"),
            (r"\\server\private-share\secret.pgn", "private-share"),
            (r"\\server/private-share/PrivateUser/secret.pgn", "PrivateUser"),
            (r"\\server/private-share\PrivateUser\secret.pgn", "PrivateUser"),
            (r"\\?\UNC/private-server/private-share/secret.pgn", "private-server"),
            (r"\\?\C:\Users\PrivateUser\secret.pgn", "PrivateUser"),
            ("file:///C:/Users/PrivateUser/secret.pgn", "PrivateUser"),
            ("file:///C:/Users/Public/My Private Folder/PrivateUser/secret.pgn", "PrivateUser"),
            ("file://private-server/Public Share/PrivateUser/secret.pgn", "PrivateUser"),
            ("file://private-server/private-share/secret.pgn", "private-server"),
            ("file://localhost/C:/Users/PrivateUser/secret.pgn", "PrivateUser"),
            ("file:/C:/Users/PrivateUser/secret.pgn", "PrivateUser"),
            ("file:C:/Users/PrivateUser/secret.pgn", "PrivateUser"),
            ("FILE://private-server/private%20share/secret.pgn", "private-server"),
            ("file:%2F%2F%2Fhome%2FPrivateUser%2Fsecret.pgn", "PrivateUser"),
            ("file:%5C%5Cprivate-server%5Cprivate-share%5Csecret.pgn", "private-server"),
            ("file:C%3A%5CUsers%5CPrivateUser%5Csecret.pgn", "PrivateUser"),
            ("/home/private-user/book.pgn", "private-user"),
            ("/opt/accessible-chess/private/book.pgn", "accessible-chess"),
            ("/srv/accessible-chess/private/book.pgn", "accessible-chess"),
            ("/etc/accessible-chess/private.conf", "accessible-chess"),
            ("/root/accessible-chess/private/book.pgn", "accessible-chess"),
            ("/run/accessible-chess/private.sock", "accessible-chess"),
            ("/Applications/AccessibleChess/private/book.pgn", "AccessibleChess"),
            ("/Volumes/PrivateDisk/PrivateUser/book.pgn", "PrivateUser"),
            ("/Library/Application Support/AccessibleChess/private/book.pgn", "AccessibleChess"),
            ("/System/Volumes/Data/Users/PrivateUser/book.pgn", "PrivateUser"),
        )
        for token, private_component in cases:
            with self.subTest(token=token):
                projected = self._project(f"Parser note: {token}")
                self.assertIn("[local path hidden]", projected)
                self.assertNotIn(private_component, projected)

    def test_d01_gate_uses_reviewed_stage1_blobs_not_historical_branch_name(self):
        workflow = (
            Path(__file__).parents[1]
            / ".github"
            / "workflows"
            / "d01-pgn-workspace-webview.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "b8586a26b9ab20c3d3ec0b0a3dbbbd53e38e94e6|"
            "b579ca0f59ba20f6b69b3a4b7d89589256d54852",
            workflow,
        )
        self.assertNotIn(
            "integration/clock-engine-serial-intake-20261002",
            workflow,
        )
        self.assertIn(
            "acs/presentation_privacy.py=e30c873e8e9aeca414334a6cc1db5ac7a92fac7f",
            workflow,
        )
        self.assertIn(
            "tests.test_v2_shared_presentation_path_privacy",
            workflow,
        )

    def test_ukrainian_projection_uses_localized_redaction_marker(self):
        projected = self._project(
            r"Джерело C:Users\PrivateUser\book.pgn",
            language=UILanguage.UA,
        )
        self.assertIn("[локальний шлях приховано]", projected)
        self.assertNotIn("PrivateUser", projected)

    def test_safe_chess_web_and_relative_text_is_not_redacted(self):
        safe = (
            "https://example.com/docs/game.pgn",
            "https://example.com/home/private/game.pgn",
            "https://example.com/C:/Users/Public/game.pgn",
            "Invalid command /help",
            "Line e4/e5 continues with Nf3/Nc6",
            "FEN rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            "relative source incoming/game.pgn",
            "file format: PGN",
            "profile:file-not-a-uri",
            "Result 1-0",
        )
        for text in safe:
            with self.subTest(text=text):
                self.assertEqual(text, self._project(text))


if __name__ == "__main__":
    unittest.main()
