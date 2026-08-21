from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acs.chessbase_adapter import probe_chessbase_source


class Dev4ChessBaseReportPathPrivacyTests(unittest.TestCase):
    """QA gate: serialized import/report DTOs must not expose private local paths."""

    def test_probe_report_does_not_expose_absolute_source_or_component_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dev4-private-chessbase-") as directory:
            root = Path(directory)
            source = root / "private-database.cbh"
            companion = root / "private-database.cbg"
            source.write_bytes(b"CBH")
            companion.write_bytes(b"CBG")

            report = probe_chessbase_source(source).as_report_fields()
            rendered = repr(report)

            # Full Product export/report metadata may identify the submitted
            # source without disclosing an absolute workstation/build path.
            # This assertion intentionally does not prescribe a replacement
            # representation (basename, token, redaction, etc.); it only locks
            # the privacy boundary.
            self.assertNotIn(str(root), rendered)
            self.assertNotIn(str(source), rendered)
            self.assertNotIn(str(companion), rendered)


if __name__ == "__main__":
    unittest.main()
