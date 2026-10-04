from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FinalProductAnnouncementLocalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.composition = (ROOT / "acs" / "version2_education_mutation_release.py").read_text(
            encoding="utf-8"
        )
        cls.stage1_bridge = (ROOT / "web" / "stage1_board_actions.js").read_text(
            encoding="utf-8"
        )
        cls.p0_runtime = (ROOT / "web" / "p0_accessibility_runtime.js").read_text(
            encoding="utf-8"
        )

    def test_final_product_loads_canonical_p0_runtime_after_v2_bootstrap(self) -> None:
        bootstrap = self.composition.index(
            '("V2 final-product bootstrap", root / "version2_final_product_bootstrap.js")'
        )
        p0 = self.composition.index(
            '("P0 accessibility runtime", root / "p0_accessibility_runtime.js")'
        )
        self.assertLess(bootstrap, p0)

    def test_p0_generic_bridge_failure_uses_live_document_language(self) -> None:
        self.assertIn(
            'const genericFailure = documentRef.documentElement && documentRef.documentElement.lang === "en"',
            self.p0_runtime,
        )
        self.assertIn('? "Action could not be completed."', self.p0_runtime)
        self.assertIn(': "Не вдалося виконати дію.";', self.p0_runtime)
        self.assertIn("exposeAnnouncement(genericFailure, dispatchId);", self.p0_runtime)
        self.assertNotIn(
            'exposeAnnouncement("Не вдалося виконати дію.", dispatchId);',
            self.p0_runtime,
        )

    def test_p0_runtime_remains_the_single_event_aware_delivery_owner(self) -> None:
        self.assertIn("global.announce = function (message, eventId)", self.p0_runtime)
        self.assertIn("return exposeAnnouncement(message, dispatch);", self.p0_runtime)
        self.assertIn('const dispatchId = "api:" + String(++dispatchCounter);', self.p0_runtime)
        self.assertIn("rememberDispatchMessage", self.p0_runtime)
        self.assertIn("announcementQueue.push(text)", self.p0_runtime)

    def test_stage1_adapter_remains_compatible_without_second_live_region(self) -> None:
        self.assertIn("const baseAnnounce = window.announce;", self.stage1_bridge)
        self.assertIn("message === 'Не вдалося виконати дію.'", self.stage1_bridge)
        self.assertIn("'Action could not be completed.'", self.stage1_bridge)
        self.assertIn("return baseAnnounce(localized, eventId);", self.stage1_bridge)
        self.assertNotIn("aria-live", self.stage1_bridge)


if __name__ == "__main__":
    unittest.main()
