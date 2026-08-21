from __future__ import annotations

import unittest

from acs.stage1_native_menu_router import Stage1NativeMenuActionProxy
from acs.ui_keymap_editor import KeymapEditorModel


class _PartialMenuAPI:
    def __init__(self) -> None:
        self.direct_calls = 0

    def toggle_engine(self):
        self.direct_calls += 1
        return {"ok": True}


class Dev1ReleaseUiRegressionTests(unittest.TestCase):
    def test_native_menu_proxy_accepts_partial_release_seam_but_registry_actions_fail_closed(self) -> None:
        api = _PartialMenuAPI()
        proxy = Stage1NativeMenuActionProxy(api)

        self.assertTrue(proxy.toggle_engine()["ok"])
        self.assertEqual(api.direct_calls, 1)

        with self.assertRaisesRegex(TypeError, "must expose dispatch_action"):
            proxy.undo()
        with self.assertRaisesRegex(TypeError, "must expose dispatch_action"):
            proxy.select_relative_analysis_pv(1)
        self.assertEqual(api.direct_calls, 1)

    def test_dense_rank_file_labels_do_not_flood_generic_localized_navigation_search(self) -> None:
        uk = KeymapEditorModel(lang="uk")
        self.assertEqual(
            [row.action_id for row in uk.rows(query="перейти")],
            ["history.go_to_move"],
        )
        uk_rank = next(row for row in uk.rows() if row.action_id == "board.rank_1")
        uk_file = next(row for row in uk.rows() if row.action_id == "board.file_1")
        self.assertEqual(uk_rank.label, "Горизонталь 1")
        self.assertEqual(uk_file.label, "Вертикаль a")
        self.assertEqual(
            {row.action_id for row in uk.rows(query="горизонталь")},
            {f"board.rank_{number}" for number in range(1, 9)},
        )

        en = KeymapEditorModel(lang="en")
        self.assertEqual(
            [row.action_id for row in en.rows(query="go")],
            ["history.go_to_move"],
        )
        en_rank = next(row for row in en.rows() if row.action_id == "board.rank_1")
        en_file = next(row for row in en.rows() if row.action_id == "board.file_1")
        self.assertEqual(en_rank.label, "Rank 1")
        self.assertEqual(en_file.label, "File a")


if __name__ == "__main__":
    unittest.main()
