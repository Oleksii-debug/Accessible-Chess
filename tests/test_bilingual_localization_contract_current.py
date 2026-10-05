from __future__ import annotations

from pathlib import Path
import re
import unittest

from acs.i18n import STRINGS
from acs.keybindings import ActionRegistry
from acs.full_product_ui_shell import ROUTES, UILanguage
from acs.full_product_native_menu import _TEXT as NATIVE_MENU_TEXT
from acs.library_webview_projection import _LABELS as LIBRARY_LABELS, _IMPORT_LABELS as LIBRARY_IMPORT_LABELS
from acs.library_export_webview_projection import _EXPORT_LABELS as LIBRARY_EXPORT_LABELS
from acs.book_webview_projection import _LABELS as BOOK_LABELS
from acs.training_webview_projection import _LABELS as TRAINING_LABELS
from acs.classroom_webview_projection import _LABELS as CLASSROOM_LABELS
from acs.education_webview_projection import _TEXT as EDUCATION_TEXT
from acs.pgn_webview_projection import _LABELS as PGN_LABELS
from acs.ui_keymap_editor import _CONTEXT_LABELS_EN, _CONTEXT_LABELS_UK
from acs.ui_keymap_adapter import build_web_keymap
from acs.ui_native_menu import _LABELS_EN as STAGE1_NATIVE_MENU_EN, _LABELS_UK as STAGE1_NATIVE_MENU_UK
from acs.version2_final_product_profile import build_final_product_action_registry
from acs.full_product_actions import build_full_product_action_registry


_CYRILLIC = re.compile(r"[А-Яа-яІіЇїЄєҐґ]")


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

    def test_stage1_native_menu_has_exact_uk_en_parity(self) -> None:
        self.assert_catalog_parity("stage1-native-menu", STAGE1_NATIVE_MENU_UK, STAGE1_NATIVE_MENU_EN)

    def test_keymap_context_labels_have_exact_uk_en_parity(self) -> None:
        self.assert_catalog_parity("keymap-context", _CONTEXT_LABELS_UK, _CONTEXT_LABELS_EN)

    def test_generated_keymap_has_real_english_labels_for_every_current_action(self) -> None:
        snapshot = build_web_keymap(ActionRegistry())
        actions = tuple(snapshot["actions"])
        self.assertTrue(actions)
        for action in actions:
            label = action["labelEn"]
            self.assertIsInstance(label, str, action["id"])
            self.assertTrue(label.strip(), action["id"])
            self.assertIsNone(_CYRILLIC.search(label), f"{action['id']}: English label leaks Cyrillic: {label!r}")

    def test_full_product_routes_are_complete_in_both_languages(self) -> None:
        for route in ROUTES:
            self.assertTrue(route.heading[UILanguage.UA].strip(), route.route_id)
            self.assertTrue(route.heading[UILanguage.EN].strip(), route.route_id)
            self.assertTrue(route.description[UILanguage.UA].strip(), route.route_id)
            self.assertTrue(route.description[UILanguage.EN].strip(), route.route_id)

    def test_composed_and_preview_keymaps_have_real_bilingual_labels(self) -> None:
        for factory in (build_final_product_action_registry, build_full_product_action_registry):
            for action in build_web_keymap(factory())["actions"]:
                with self.subTest(profile=factory.__name__, action=action["id"]):
                    self.assertIsNotNone(_CYRILLIC.search(action["labelUk"]),
                                         f"Ukrainian label falls back to English: {action['labelUk']!r}")
                    self.assertTrue(action["labelEn"].strip())
                    self.assertIsNone(_CYRILLIC.search(action["labelEn"]),
                                      f"English label leaks Ukrainian: {action['labelEn']!r}")

    def test_product_surface_catalogs_have_exact_uk_en_parity(self) -> None:
        catalogs = (
            ("native-menu", NATIVE_MENU_TEXT),
            ("pgn", PGN_LABELS),
            ("library", LIBRARY_LABELS),
            ("library-import", LIBRARY_IMPORT_LABELS),
            ("library-export", LIBRARY_EXPORT_LABELS),
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
