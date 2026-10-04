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

    def test_canonical_p0_announcement_owner_precedes_stage1_language_adapter(self) -> None:
        p0 = self.composition.index(
            '("P0 accessibility runtime", root / "p0_accessibility_runtime.js")'
        )
        adapter = self.composition.index(
            '("Stage 1 board action bridge", root / "stage1_board_actions.js")'
        )
        self.assertLess(
            p0,
            adapter,
            "the Stage1 language adapter must wrap the final canonical P0 announce boundary",
        )

    def test_p0_still_loads_after_final_product_bootstrap_for_selection_authority(self) -> None:
        bootstrap = self.composition.index(
            '("V2 final-product bootstrap", root / "version2_final_product_bootstrap.js")'
        )
        p0 = self.composition.index(
            '("P0 accessibility runtime", root / "p0_accessibility_runtime.js")'
        )
        self.assertLess(bootstrap, p0)

    def test_stage1_adapter_localizes_only_the_known_generic_failure(self) -> None:
        self.assertIn("const baseAnnounce = window.announce;", self.stage1_bridge)
        self.assertIn("document.documentElement.lang === 'en'", self.stage1_bridge)
        self.assertIn("message === 'Не вдалося виконати дію.'", self.stage1_bridge)
        self.assertIn("'Action could not be completed.'", self.stage1_bridge)
        self.assertIn("return baseAnnounce(localized, eventId);", self.stage1_bridge)

    def test_canonical_p0_runtime_remains_the_event_aware_delivery_owner(self) -> None:
        self.assertIn("global.announce = function (message, eventId)", self.p0_runtime)
        self.assertIn("return exposeAnnouncement(message, dispatch);", self.p0_runtime)
        self.assertIn('const dispatchId = "api:" + String(++dispatchCounter);', self.p0_runtime)
        self.assertIn('exposeAnnouncement("Не вдалося виконати дію.", dispatchId);', self.p0_runtime)
        self.assertNotIn("aria-live", self.stage1_bridge)


if __name__ == "__main__":
    unittest.main()
