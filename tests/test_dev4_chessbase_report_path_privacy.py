from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acs.chessbase_adapter import probe_chessbase_source
from acs.chessbase_integrity import capture_integrity_snapshot
from acs.chessbase_manifest import build_chessbase_manifest


class Dev4ChessBaseReportPathPrivacyTests(unittest.TestCase):
    """QA gate: serialized import/report DTOs must not expose private local paths."""

    def _fixture(self, root: Path) -> tuple[Path, Path]:
        source = root / "private-database.cbh"
        companion = root / "private-database.cbg"
        source.write_bytes(b"CBH")
        companion.write_bytes(b"CBG")
        return source, companion

    def _assert_private_paths_absent(self, rendered: str, root: Path, source: Path, companion: Path) -> None:
        # The contract deliberately does not prescribe the eventual public
        # representation (basename, stable source id, redaction token, etc.).
        # It only forbids exposing workstation/build absolute paths in report
        # or persisted provenance payloads.
        self.assertNotIn(str(root), rendered)
        self.assertNotIn(str(source), rendered)
        self.assertNotIn(str(companion), rendered)

    def test_probe_report_does_not_expose_absolute_source_or_component_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dev4-private-chessbase-") as directory:
            root = Path(directory)
            source, companion = self._fixture(root)
            rendered = repr(probe_chessbase_source(source).as_report_fields())
            self._assert_private_paths_absent(rendered, root, source, companion)

    def test_integrity_report_does_not_expose_absolute_source_or_component_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dev4-private-chessbase-") as directory:
            root = Path(directory)
            source, companion = self._fixture(root)
            rendered = repr(capture_integrity_snapshot(source).as_report_fields())
            self._assert_private_paths_absent(rendered, root, source, companion)

    def test_manifest_dict_does_not_expose_absolute_source_or_component_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dev4-private-chessbase-") as directory:
            root = Path(directory)
            source, companion = self._fixture(root)
            rendered = repr(build_chessbase_manifest(source).as_dict())
            self._assert_private_paths_absent(rendered, root, source, companion)


if __name__ == "__main__":
    unittest.main()
