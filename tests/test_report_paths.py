from __future__ import annotations

import unittest

from acs.report_paths import report_safe_name


class ReportSafeNameTests(unittest.TestCase):
    def test_preserves_normal_unicode_relative_provenance(self) -> None:
        self.assertEqual(
            report_safe_name("імпорт/партії/гра.pgn"),
            "імпорт/партії/гра.pgn",
        )

    def test_windows_absolute_and_drive_relative_paths_hide_drive_and_directories(self) -> None:
        cases = {
            r"C:\Users\Oleksii\secret\game.pgn": "game.pgn",
            r"C:secret\game.pgn": "game.pgn",
            r"C:game.pgn": "game.pgn",
            r"z:private\book.cbh": "book.cbh",
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(report_safe_name(path), expected)

    def test_local_file_uris_hide_private_directories_and_uri_metadata(self) -> None:
        cases = {
            "file:///C:/Users/Oleksii/secret/game.pgn": "game.pgn",
            "file://server/share/private/book.cbh": "book.cbh",
            r"file:C:secret\game.pgn": "game.pgn",
            "FILE:///home/oleksii/private/%D0%B3%D1%80%D0%B0.pgn": "гра.pgn",
            "file:///C:/private/dir%2Fgame.pgn": "game.pgn",
            "file:///C:/private/game.pgn?token=private#fragment": "game.pgn",
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(report_safe_name(path), expected)

    def test_encoded_unsafe_file_uri_text_fails_closed(self) -> None:
        for path in (
            "file:///C:/private/evil%0ASTATUS%3A%20PASS.pgn",
            "file:///C:/private/evil%E2%80%AEgnp.live.pgn",
            "file:///C:/private/%FFgame.pgn",
        ):
            with self.subTest(path=path):
                self.assertEqual(report_safe_name(path), "source")

    def test_report_control_characters_fail_closed(self) -> None:
        for path in (
            "incoming/evil\nSTATUS: PASS.pgn",
            "incoming/evil\rPASS.pgn",
            "incoming/evil\tgame.pgn",
            "incoming/evil\u202egnp.live.pgn",
            "incoming/evil\u2028game.pgn",
        ):
            with self.subTest(path=repr(path)):
                self.assertEqual(report_safe_name(path), "source")

    def test_relative_traversal_still_fails_closed_to_basename(self) -> None:
        self.assertEqual(report_safe_name("../private/game.pgn"), "game.pgn")


if __name__ == "__main__":
    unittest.main()
