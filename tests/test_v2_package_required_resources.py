from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.version2_package_preflight import Version2PackagePreflightError
from tests.test_version2_package_preflight import _make_tree, _validate_tree


class Version2PackageRequiredResourcesTests(unittest.TestCase):
    def test_preflight_rejects_package_without_release_critical_runtime_resources(self):
        """A package without engine/sounds/GPL evidence must never validate.

        The historical preflight fixture intentionally contains only the EXE and
        a dummy content file.  That is useful here as an exact RED oracle: the V2
        release contract requires bundled Stockfish, all semantic WAV events and
        the corresponding GPL source/notices before a package can be considered
        machine-valid.
        """

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)

            with self.assertRaises(Version2PackagePreflightError):
                _validate_tree(root)


if __name__ == "__main__":
    unittest.main()
