from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.version2_package_preflight import Version2PackagePreflightError
from tests.test_version2_package_preflight import (
    _make_tree, _validate_tree, _write_checksums,
)

REAL_SCRIPT = Path(__file__).resolve().parent.parent / "web/section45_design_studio.js"
LINK = '<script src="section45_design_studio.js"></script>'


class Section45PackageStudioAssetTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(self.sandbox.cleanup)
        self.root = Path(self.sandbox.name) / "package"
        self.root.mkdir()
        _make_tree(self.root)
        self.web = self.root / "AccessibleChess/web"
        index = self.web / "index.html"
        index.write_text(index.read_text(encoding="utf-8") + LINK + "\n", encoding="utf-8")

    def test_missing_script_fails_closed_even_with_fresh_checksums(self):
        _write_checksums(self.root)
        with self.assertRaisesRegex(Version2PackagePreflightError,
                                    "design studio|Section 45|local design studio"):
            _validate_tree(self.root)

    def test_tampered_script_bridge_fails_closed_with_consistent_checksums(self):
        (self.web / "section45_design_studio.js").write_text(
            'console.log("fake ui only");',
            encoding="utf-8",
        )
        _write_checksums(self.root)
        with self.assertRaisesRegex(Version2PackagePreflightError,
                                    "bridge semantics"):
            _validate_tree(self.root)

    def test_real_studio_source_fulfills_optional_packaged_feature(self):
        (self.web / "section45_design_studio.js").write_bytes(REAL_SCRIPT.read_bytes())
        _write_checksums(self.root)
        result = _validate_tree(self.root)
        self.assertGreater(result.checksums_verified, 3)

    def test_duplicate_script_tag_rejected_before_shipping(self):
        (self.web / "section45_design_studio.js").write_bytes(REAL_SCRIPT.read_bytes())
        index = self.web / "index.html"
        index.write_text(index.read_text(encoding="utf-8") + LINK, encoding="utf-8")
        _write_checksums(self.root)
        with self.assertRaisesRegex(Version2PackagePreflightError,
                                    "linked exactly once"):
            _validate_tree(self.root)


if __name__ == "__main__":
    unittest.main()
