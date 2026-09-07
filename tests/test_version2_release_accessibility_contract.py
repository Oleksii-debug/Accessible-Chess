from __future__ import annotations

import unittest
from pathlib import Path


BOOTSTRAP = (
    Path(__file__).resolve().parents[1] / "web" / "version2_release_bootstrap.js"
).read_text(encoding="utf-8")


class Version2ReleaseAccessibilityContractTests(unittest.TestCase):
    def test_navigation_buttons_keep_concise_native_names(self) -> None:
        self.assertIn('const button = documentRef.createElement("button")', BOOTSTRAP)
        self.assertIn('button.textContent = String(item.label || item.route_id || "")', BOOTSTRAP)
        self.assertIn('button.setAttribute("aria-current", "page")', BOOTSTRAP)
        self.assertNotIn("aria-describedby", BOOTSTRAP)
        self.assertNotIn('button.id + "-description"', BOOTSTRAP)

    def test_v2_navigation_is_a_named_landmark_in_both_languages(self) -> None:
        self.assertIn('const nav = documentRef.createElement("nav")', BOOTSTRAP)
        self.assertIn('nav.setAttribute("aria-label", uiText(', BOOTSTRAP)
        self.assertIn('"Розділи Accessible Chess"', BOOTSTRAP)
        self.assertIn('"Accessible Chess sections"', BOOTSTRAP)
        self.assertIn('navHeading.textContent = uiText("Розділи", "Sections")', BOOTSTRAP)

    def test_document_language_is_set_before_navigation_is_rendered(self) -> None:
        language = '    documentRef.documentElement.lang = currentLanguage;'
        navigation_call = '    renderNavigation(snapshot);'
        self.assertIn(language, BOOTSTRAP)
        self.assertIn(navigation_call, BOOTSTRAP)
        self.assertLess(BOOTSTRAP.index(language), BOOTSTRAP.index(navigation_call))

    def test_workspace_does_not_create_a_second_live_region(self) -> None:
        self.assertIn('workspace.setAttribute("aria-live", "off")', BOOTSTRAP)
        self.assertNotIn('workspace.setAttribute("aria-live", "polite")', BOOTSTRAP)
        self.assertNotIn('workspace.setAttribute("aria-live", "assertive")', BOOTSTRAP)

    def test_fallback_status_text_follows_document_language(self) -> None:
        for english in (
            "Could not open the section.",
            "No PGN is open yet.",
            "No book is open yet.",
            "Could not load Version 2 sections.",
        ):
            with self.subTest(text=english):
                self.assertIn(english, BOOTSTRAP)


if __name__ == "__main__":
    unittest.main()
