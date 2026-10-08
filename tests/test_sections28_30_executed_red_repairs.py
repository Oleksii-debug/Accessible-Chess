from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.server_application_boundary import ApiRequest, EntityRef, SqliteJobStore
from acs.version2_profile import build_version2_action_registry, build_version2_menu_spec
from acs.full_product_ui_shell import UILanguage


class Sections28And30ExecutedRedRepairTests(unittest.TestCase):
    def test_v2_position_menu_action_is_registered(self) -> None:
        registry = build_version2_action_registry()
        definition = registry.definition("position.copy_fen")
        self.assertEqual(definition.action_id, "position.copy_fen")

        menus = build_version2_menu_spec(registry, language=UILanguage.EN)
        position = next(menu for menu in menus if menu.menu_id == "position")
        action_ids = {
            item.action_id
            for item in position.items
            if getattr(item, "action_id", None) is not None
        }
        self.assertIn("position.copy_fen", action_ids)

    def test_sqlite_job_store_releases_file_handle_after_operation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.sqlite3"
            store = SqliteJobStore(path)
            store.enqueue(
                ApiRequest(
                    1,
                    "req-handle-release",
                    "workspace-1",
                    "server.heavy.import",
                    {"value": 1},
                    EntityRef("library-1", 0),
                )
            )

            moved = Path(directory) / "jobs-moved.sqlite3"
            path.replace(moved)
            moved.replace(path)
            self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
