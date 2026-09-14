from pathlib import Path
import unittest
import xml.etree.ElementTree as ET


EXPECTED_SWITCHES = (
    "Switch.UseLegacyAccessibilityFeatures=false",
    "Switch.UseLegacyAccessibilityFeatures.2=false",
    "Switch.UseLegacyAccessibilityFeatures.3=false",
    "Switch.UseLegacyAccessibilityFeatures.4=false",
    "Switch.UseLegacyAccessibilityFeatures.5=false",
)


class PackagedWinFormsAppConfigTests(unittest.TestCase):
    def test_exact_modern_accessibility_switches_are_bound_to_standalone_host(self) -> None:
        config = Path("packaging/AccessibleChess.exe.config")
        root = ET.fromstring(config.read_text(encoding="utf-8"))
        node = root.find("./runtime/AppContextSwitchOverrides")
        self.assertIsNotNone(node)
        value = node.attrib.get("value", "")
        self.assertEqual(EXPECTED_SWITCHES, tuple(value.split(";")))

    def test_nuitka_main_contract_places_config_beside_accessible_chess_exe(self) -> None:
        source = Path("run_accessible_chess_v2.py").read_text(encoding="utf-8")
        directive = (
            "#    nuitka-project: --include-data-files={MAIN_DIRECTORY}/"
            "packaging/AccessibleChess.exe.config=AccessibleChess.exe.config"
        )
        self.assertIn('# nuitka-project-if: {OS} == "Windows":', source)
        self.assertIn(directive, source)
        self.assertLess(source.index(directive), source.index("import json"))


if __name__ == "__main__":
    unittest.main()
