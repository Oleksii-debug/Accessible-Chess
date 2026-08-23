from __future__ import annotations

import unittest

from acs.report_paths import report_safe_name


class Dev3Stage1DriveRelativePathPrivacyTests(unittest.TestCase):
    """Windows drive-relative workstation paths must fail closed in reports."""

    def test_drive_relative_windows_path_redacts_private_parent(self) -> None:
        private_path = r"C:Users\PrivateUser\Documents\analysis.pgn"
        rendered = report_safe_name(private_path)
        self.assertEqual(rendered, "analysis.pgn")
        self.assertNotIn("PrivateUser", rendered)
        self.assertNotIn("Documents", rendered)
        self.assertNotIn("Users", rendered)


if __name__ == "__main__":
    unittest.main()
