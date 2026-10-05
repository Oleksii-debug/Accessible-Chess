from __future__ import annotations

from pathlib import Path
import unittest

from acs.i18n import STRINGS
from acs.full_product_ui_shell import ROUTES, UILanguage
from acs.full_product_native_menu import _TEXT as NATIVE_MENU_TEXT
from acs.library_webview_projection import _LABELS as LIBRARY_LABELS, _IMPORT_LABELS as LIBRARY_IMPORT_LABELS
from acs.book_webview_projection import _LABELS as BOOK_LABELS
from acs.training_webview_projection import _LABELS as TRAINING_LABELS
from acs.classroom_webview_projection import _LABELS as CLASSROOM_LABELS
from acs.education_webview_projection import _TEXT as EDUCATION_TEXT


class BilingualLocalizationContractCurrentTests(unittest.TestCase):
    def assert_catalog_parity(self, name: str, ua: dict[str, str], en: dict[str, str]) -> None:
        self.assertEqual(set(ua), set(en), f"{name}: Ukrainian/English keys diverge")
        for key in sorted(ua):
            self.assertIsInstance(ua[key], str, f"{name}.{key}: Ukrainian value must be text")
            self.assertIsInstance(en[key], str, f"{name}.{key}: English value must be text")
            self.assertTrue(ua[key].strip(), f"{name}.{key}: missing Ukrainian text")
            self.assertTrue(en[key].strip(), f"{name}.{key}: missing English text")

    def test_stage1_core_catalog_has_exact_uk_en_parity(self) -> None:
        self.assertEqual(set(STRINGS), {"uk", "en"})
        self.assert_catalog_parity("stage1", STRINGS["uk"], STRINGS["en"])

    def test_full_product_routes_are_complete_in_both_languages(self) -> None:
        for route in ROUTES:
            self.assertTrue(route.heading[UILanguage.UA].strip(), route.route_id)
            self.assertTrue(route.heading[UILanguage.EN].strip(), route.route_id)
            self.assertTrue(route.description[UILanguage.UA].strip(), route.route_id)
            self.assertTrue(route.description[UILanguage.EN].strip(), route.route_id)

    def test_product_surface_catalogs_have_exact_uk_en_parity(self) -> None:
        catalogs = (
            ("native-menu", NATIVE_MENU_TEXT),
            ("library", LIBRARY_LABELS),
            ("library-import", LIBRARY_IMPORT_LABELS),
            ("books", BOOK_LABELS),
            ("training", TRAINING_LABELS),
            ("classroom", CLASSROOM_LABELS),
            ("education", EDUCATION_TEXT),
        )
        for name, catalog in catalogs:
            with self.subTest(catalog=name):
                self.assertEqual(set(catalog), {UILanguage.UA, UILanguage.EN})
                self.assert_catalog_parity(
                    name,
                    dict(catalog[UILanguage.UA]),
                    dict(catalog[UILanguage.EN]),
                )

    def test_webview_generic_failure_path_is_bilingual(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("function localizedUiText(uk,en)", source)
        self.assertIn("'Дія недоступна.'", source)
        self.assertIn("'Action unavailable.'", source)
        self.assertIn("'Не вдалося виконати дію.'", source)
        self.assertIn("'The action could not be completed.'", source)
        self.assertNotIn("announce('Не вдалося виконати дію.'", source)


if __name__ == "__main__":
    unittest.main()
