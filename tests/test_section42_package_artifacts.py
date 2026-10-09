"""Offline licensed piece pack release preflight acceptance."""
from pathlib import Path
import tempfile
import unittest

from acs.version2_package_preflight import Version2PackagePreflightError
from tests.test_version2_package_preflight import _make_tree, _write_checksums, _validate_tree

ROOT = Path(__file__).resolve().parents[1]
ASSETS = "web/assets/pieces/rhosgfx/"
NAMES = [color + kind + ".svg" for color in "wb" for kind in "KQRBNP"]
NAMES += ["SECTION42_PROVENANCE.json", "SOURCE_COPYING.md"]


class Section42ReleaseArtTests(unittest.TestCase):
    def test_all_sources_required_and_exact(self):
        with tempfile.TemporaryDirectory() as temp:
            candidate = Path(temp) / "candidate"
            candidate.mkdir()
            _make_tree(candidate)
            product = candidate / "AccessibleChess"
            index = product / "web/index.html"
            index.write_text("assets/pieces/rhosgfx/", encoding="utf-8")
            _write_checksums(candidate)
            with self.assertRaises(Version2PackagePreflightError):
                _validate_tree(candidate)

            for name in NAMES:
                dest = product / ASSETS / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes((ROOT / ASSETS / name).read_bytes())
            _write_checksums(candidate)
            _validate_tree(candidate)

            for name in ("wK.svg", "bP.svg", "SOURCE_COPYING.md"):
                with self.subTest(name=name):
                    target = product / ASSETS / name
                    raw = target.read_bytes()
                    target.write_bytes(raw + b"invalid")
                    _write_checksums(candidate)
                    with self.assertRaises(Version2PackagePreflightError):
                        _validate_tree(candidate)
                    target.write_bytes(raw)
                    _write_checksums(candidate)
                    _validate_tree(candidate)


if __name__ == "__main__":
    unittest.main()
