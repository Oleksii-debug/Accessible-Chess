from __future__ import annotations

from pathlib import Path
import unittest

import acs
from acs.version import VERSION
from acs.webapp import VERSION as WEBAPP_VERSION


ROOT = Path(__file__).resolve().parents[1]


class VersionMetadataTests(unittest.TestCase):
    def test_runtime_consumers_delegate_to_one_version_authority(self) -> None:
        self.assertEqual(acs.VERSION, VERSION)
        self.assertEqual(acs.__version__, VERSION)
        self.assertEqual(WEBAPP_VERSION, VERSION)

    def test_release_version_mirror_matches_runtime_authority(self) -> None:
        mirror = (ROOT / "VERSION.txt").read_text(encoding="utf-8")
        self.assertEqual(mirror.splitlines(), [VERSION])
        self.assertTrue(mirror.endswith("\n"))
        self.assertEqual(mirror.strip(), VERSION)


if __name__ == "__main__":
    unittest.main()
