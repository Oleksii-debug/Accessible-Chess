from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.full_product_ui_shell import UILanguage
from acs.network_security import DEFAULT_SECTION29_POLICY
from acs.server_application_boundary import (
    ApiRequest,
    AuthenticatedPrincipal,
    EntityRef,
    ServerApplicationBoundary,
    SqliteJobStore,
    build_application_operations,
)
from acs.version2_application import Version2Application
from acs.version2_profile import build_version2_action_registry, build_version2_menu_spec


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

    def test_server_boundary_reads_real_current_version2_application_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2Application(
                    database,
                    progress_store=BookProgressStore(root / "progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_args: {"ok": True},
                    board_position_projector=lambda _fen: {"ok": True},
                    copy_text=lambda _text: None,
                )
                operations = build_application_operations(
                    snapshot=app.snapshot,
                    dispatch=app._delegate,
                )
                policy = DEFAULT_SECTION29_POLICY
                boundary = ServerApplicationBoundary(
                    security_policy=policy,
                    security_gate=policy.gate(),
                    operations=operations,
                )
                principal = AuthenticatedPrincipal(
                    actor_id="integration-user",
                    workspace_id="integration-workspace",
                    session_id="integration-session",
                    roles=frozenset({"teacher"}),
                    permissions=frozenset({"app.read", "app.write"}),
                )
                response = boundary.handle(
                    principal,
                    ApiRequest(
                        1,
                        "req-real-v2-snapshot",
                        "integration-workspace",
                        "server.application.snapshot",
                        {},
                    ),
                )
                snapshot = response["result"]
                self.assertIsInstance(snapshot, dict)
                self.assertIn("navigation", snapshot)
                self.assertIn("library", snapshot)
            finally:
                analysis.close()
                database.close()

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
