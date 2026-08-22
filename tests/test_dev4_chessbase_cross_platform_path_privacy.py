from __future__ import annotations

import unittest

from acs.chessbase_adapter import probe_chessbase_source


class Dev4ChessBaseCrossPlatformPathPrivacyTests(unittest.TestCase):
    """Report-safe identifiers must not leak workstation directories cross-platform."""

    def test_windows_style_private_path_is_not_serialized_whole_on_posix(self) -> None:
        submitted = r"C:\Users\PrivateUser\Documents\Training Database.CBH"
        report = probe_chessbase_source(submitted).as_report_fields()

        serialized = str(report["source_path"])
        self.assertNotIn("PrivateUser", serialized)
        self.assertNotIn("Documents", serialized)
        self.assertNotIn("Users", serialized)
        self.assertEqual(serialized, "Training Database.CBH")


if __name__ == "__main__":
    unittest.main()
