from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from acs import version2_package_preflight, version2_release_payload
from acs.version2_upgrade_status_release import final_product_resource_sources


class CurrentLauncherResourceContractTests(unittest.TestCase):
    def test_every_script_loaded_by_the_actual_launcher_is_mandatory_in_both_validators(self):
        loaded: list[Path] = []
        read_text = Path.read_text

        def record_read(path, *args, **kwargs):
            loaded.append(path)
            return read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", autospec=True, side_effect=record_read):
            resources = final_product_resource_sources()
        self.assertEqual(len(resources), len(loaded))
        self.assertTrue(all(source for _label, source in resources))
        names = {path.name for path in loaded}
        self.assertIn("version2_local_profile.js", names)
        self.assertIn("p0_accessibility_runtime.js", names)
        payload_required = set(version2_release_payload._REQUIRED_WEB_FILES)
        preflight_required = set(version2_package_preflight._REQUIRED_WEB_FILES)
        for path in loaded:
            with self.subTest(resource=path.name):
                relative = Path("web") / path.name
                self.assertIn(relative, payload_required)
                self.assertIn("AccessibleChess/" + relative.as_posix(), preflight_required)


if __name__ == "__main__":
    unittest.main()
