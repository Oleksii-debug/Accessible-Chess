from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.version2_application import Version2Application
from acs.version2_starter_content_application import Version2StarterContentApplication


TEXT_BOOK = """# Chapter

First paragraph.

Second paragraph.

Third paragraph.
"""

GAME_BOOK = """# Games

Intro.

```pgn
[Event "Lease"]
[White "Alpha"]
[Black "Beta"]
[Result "*"]

1. e4 e5 *
```

Tail.
"""

REPLACEMENT_BOOK = """# Replacement

Replacement first.

Replacement second.
"""


class BookBrowserPresentationLeaseRequiredTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = AcsDatabase(self.root / "library.acsdb")
        self.addCleanup(self.database.close)
        self.analysis = AnalysisService(lambda: None)
        self.addCleanup(self.analysis.close)
        self.app = Version2Application(
            self.database,
            progress_store=BookProgressStore(self.root / "book-progress.json"),
            engine_assistance=EngineAssistedWorkflowService(self.analysis),
            board_dispatch=lambda *_: None,
            board_position_projector=lambda _fen: {"ok": True},
        )
        self.book = self.root / "book.md"
        self.book.write_text(TEXT_BOOK, encoding="utf-8")
        self.replacement = self.root / "replacement.md"
        self.replacement.write_text(REPLACEMENT_BOOK, encoding="utf-8")
        self.game_book = self.root / "game.md"
        self.game_book.write_text(GAME_BOOK, encoding="utf-8")
        self.app.open_book(self.book)

    @staticmethod
    def _token(snapshot: dict[str, object]) -> str:
        token = snapshot.get("presentation_token")
        if type(token) is not str:
            raise AssertionError("Book snapshot has no presentation token")
        return token

    def test_snapshot_exposes_bounded_opaque_book_presentation_token(self) -> None:
        snapshot = self.app.snapshot()["books"]
        self.assertIsNotNone(snapshot)
        token = self._token(snapshot)
        self.assertRegex(token, r"^[0-9a-f]{64}$")
        self.assertNotIn(str(self.root), token)
        self.assertNotIn(str(self.app.book_key), token)

    def test_echoed_lease_allows_navigation_and_rotates_with_reader_state(self) -> None:
        visible = self.app.snapshot()["books"]
        token = self._token(visible)
        before = self.app.reader.location().index

        accepted = self.app.browser_command(
            "books",
            "book.next",
            {"presentation_token": token},
        )

        self.assertEqual("render", accepted["kind"])
        self.assertEqual(before + 1, self.app.reader.location().index)
        next_token = self._token(accepted["payload"]["snapshot"])
        self.assertNotEqual(token, next_token)

        # Once the browser has echoed a lease, tokenless browser intent is no
        # longer a legacy/bootstrap command. Recover the current presentation.
        rejected = self.app.browser_command("books", "book.next", {})
        self.assertEqual("render", rejected["kind"])
        self.assertEqual(before + 1, self.app.reader.location().index)
        self.assertEqual(
            next_token,
            self._token(rejected["payload"]["snapshot"]),
        )

        resumed = self.app.browser_command(
            "books",
            "book.next",
            {"presentation_token": next_token},
        )
        self.assertEqual("render", resumed["kind"])
        self.assertEqual(before + 2, self.app.reader.location().index)

    def test_hidden_host_cursor_change_makes_old_dom_intent_recovery_only(self) -> None:
        visible = self.app.snapshot()["books"]
        token = self._token(visible)
        accepted = self.app.browser_command(
            "books",
            "book.next",
            {"presentation_token": token},
        )
        visible_token = self._token(accepted["payload"]["snapshot"])

        hidden_location = self.app.reader.next_block()
        rejected = self.app.browser_command(
            "books",
            "book.next",
            {"presentation_token": visible_token},
        )

        self.assertEqual("render", rejected["kind"])
        self.assertEqual(hidden_location, self.app.reader.location())
        self.assertEqual(
            hidden_location.index,
            rejected["payload"]["snapshot"]["block"]["index"],
        )
        self.assertNotEqual(
            visible_token,
            self._token(rejected["payload"]["snapshot"]),
        )

    def test_owner_replacement_rejects_stale_same_surface_token(self) -> None:
        visible = self.app.snapshot()["books"]
        old_token = self._token(visible)

        self.app.open_book(self.replacement)
        replacement_reader = self.app.reader
        replacement_location = replacement_reader.location()

        rejected = self.app.browser_command(
            "books",
            "book.next",
            {"presentation_token": old_token},
        )

        self.assertEqual("render", rejected["kind"])
        self.assertIs(self.app.reader, replacement_reader)
        self.assertEqual(replacement_location, replacement_reader.location())
        self.assertEqual(
            replacement_location.index,
            rejected["payload"]["snapshot"]["block"]["index"],
        )

    def test_reentrant_owner_replacement_cannot_persist_old_progress_command(self) -> None:
        visible = self.app.snapshot()["books"]
        token = self._token(visible)
        old_bridge = self.app.books
        real_dispatch = old_bridge.dispatch
        swapped = False

        def replace_then_dispatch(command, payload):
            nonlocal swapped
            if not swapped:
                swapped = True
                self.app.open_book(self.replacement)
            return real_dispatch(command, payload)

        with patch.object(old_bridge, "dispatch", side_effect=replace_then_dispatch):
            rejected = self.app.browser_command(
                "books",
                "book.next",
                {"presentation_token": token},
            )

        self.assertTrue(swapped)
        self.assertEqual("render", rejected["kind"])
        self.assertIsNot(self.app.books, old_bridge)
        self.assertEqual(0, self.app.reader.location().index)
        self.assertEqual(0, rejected["payload"]["snapshot"]["block"]["index"])

    def test_reentrant_owner_replacement_is_rechecked_before_board_mutation(self) -> None:
        self.app.open_book(self.game_book)
        first = self.app.snapshot()["books"]
        moved = self.app.browser_command(
            "books",
            "book.next_game",
            {"presentation_token": self._token(first)},
        )
        token = self._token(moved["payload"]["snapshot"])
        self.assertEqual("Game", self.app.reader.location().kind)
        old_projection = self.app.books.projection
        real_dispatch = old_projection._dispatch
        swapped = False

        def replace_then_route(action, payload):
            nonlocal swapped
            if not swapped:
                swapped = True
                self.app.open_book(self.replacement)
            return real_dispatch(action, payload)

        with patch.object(
            old_projection,
            "_dispatch",
            side_effect=replace_then_route,
        ):
            rejected = self.app.browser_command(
                "books",
                "book.open_game",
                {"presentation_token": token},
            )

        self.assertTrue(swapped)
        self.assertEqual("render", rejected["kind"])
        self.assertFalse(self.app.book_workflow.active)
        self.assertEqual("books", self.app.shell.current_route.route_id)
        self.assertEqual(0, self.app.reader.location().index)

    def test_same_lease_survives_read_only_game_board_open_and_exact_return(self) -> None:
        self.app.open_book(self.game_book)
        initial = self.app.snapshot()["books"]
        moved = self.app.browser_command(
            "books",
            "book.next_game",
            {"presentation_token": self._token(initial)},
        )
        game_snapshot = moved["payload"]["snapshot"]
        token = self._token(game_snapshot)
        origin = self.app.reader.location()

        opened = self.app.browser_command(
            "books",
            "book.open_game",
            {"presentation_token": token},
        )
        self.assertEqual("delegated", opened["kind"])
        self.assertTrue(self.app.book_workflow.active)
        self.assertEqual("board", self.app.shell.current_route.route_id)

        returned = self.app.browser_command(
            "books",
            "book.return_from_board",
            {"presentation_token": token},
        )
        self.assertEqual("render", returned["kind"])
        self.assertFalse(self.app.book_workflow.active)
        self.assertEqual("books", self.app.shell.current_route.route_id)
        self.assertEqual(origin, self.app.reader.location())
        self.assertEqual(
            token,
            self._token(returned["payload"]["snapshot"]),
        )

    def test_hostile_token_and_mapping_subclasses_are_rejected_before_hooks(self) -> None:
        visible = self.app.snapshot()["books"]
        accepted = self.app.browser_command(
            "books",
            "book.next",
            {"presentation_token": self._token(visible)},
        )
        current = self.app.reader.location()

        class HostileToken(str):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("hostile lease token hook executed")

            def __eq__(self, _other):
                type(self).touched = True
                raise AssertionError("hostile lease token equality executed")

        hostile_token = HostileToken(
            self._token(accepted["payload"]["snapshot"])
        )
        rejected = self.app.browser_command(
            "books",
            "book.next",
            {"presentation_token": hostile_token},
        )
        self.assertEqual("render", rejected["kind"])
        self.assertFalse(HostileToken.touched)
        self.assertEqual(current, self.app.reader.location())

        class HostilePayload(dict):
            touched = False

            def __contains__(self, _key):
                type(self).touched = True
                raise AssertionError("hostile payload containment executed")

            def items(self):
                type(self).touched = True
                raise AssertionError("hostile payload items executed")

        hostile_payload = HostilePayload(
            presentation_token=self._token(accepted["payload"]["snapshot"])
        )
        rejected_mapping = self.app.browser_command(
            "books",
            "book.next",
            hostile_payload,
        )
        self.assertEqual("render", rejected_mapping["kind"])
        self.assertFalse(HostilePayload.touched)
        self.assertEqual(current, self.app.reader.location())

    def test_bookmark_presentation_state_rotates_token_and_stale_name_cannot_replay(self) -> None:
        visible = self.app.snapshot()["books"]
        token = self._token(visible)

        saved = self.app.browser_command(
            "books",
            "book.bookmark.save",
            {"name": "lease-point", "presentation_token": token},
        )
        self.assertEqual("render", saved["kind"])
        saved_token = self._token(saved["payload"]["snapshot"])
        self.assertNotEqual(token, saved_token)
        self.assertEqual(
            "lease-point",
            saved["payload"]["snapshot"]["bookmark"]["value"],
        )

        stale = self.app.browser_command(
            "books",
            "book.bookmark.save",
            {"name": "stale-replay", "presentation_token": token},
        )
        self.assertEqual("render", stale["kind"])
        self.assertEqual(
            "lease-point",
            stale["payload"]["snapshot"]["bookmark"]["value"],
        )
        self.assertNotIn(
            "stale-replay",
            self.app.reader.snapshot()["return_points"],
        )

    def test_malformed_token_fails_closed_after_browser_lease_is_active(self) -> None:
        visible = self.app.snapshot()["books"]
        token = self._token(visible)
        accepted = self.app.browser_command(
            "books",
            "book.next",
            {"presentation_token": token},
        )
        current = self.app.reader.location()

        for invalid in ("", "A" * 64, "0" * 63, "g" * 64, None, 7):
            with self.subTest(token=invalid):
                rejected = self.app.browser_command(
                    "books",
                    "book.next",
                    {"presentation_token": invalid},
                )
                self.assertEqual("render", rejected["kind"])
                self.assertEqual(current, self.app.reader.location())

        missing = self.app.browser_command("books", "book.next", {})
        self.assertEqual("render", missing["kind"])
        self.assertEqual(current, self.app.reader.location())
        self.assertEqual(
            self._token(accepted["payload"]["snapshot"]),
            self._token(missing["payload"]["snapshot"]),
        )


class StarterBookBrowserPresentationLeaseTests(unittest.TestCase):
    def test_starter_material_switch_consumes_old_lease_once_and_returns_new_owner_lease(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="accessible-chess-book-browser-lease-starter-"
        ) as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    app.browser_command("shell", "screen.books")
                    visible = app.snapshot()["books"]
                    token = visible["presentation_token"]
                    first_material = visible["starter_materials"]["items"][1][
                        "material_id"
                    ]
                    opened = app.browser_command(
                        "books",
                        "book.open_starter_material",
                        {
                            "material_id": first_material,
                            "presentation_token": token,
                        },
                    )
                    self.assertEqual("render", opened["kind"])
                    current = opened["payload"]["snapshot"]
                    self.assertEqual(
                        first_material,
                        current["starter_materials"]["current_id"],
                    )
                    self.assertNotEqual(token, current["presentation_token"])

                    second_material = visible["starter_materials"]["items"][2][
                        "material_id"
                    ]
                    stale = app.browser_command(
                        "books",
                        "book.open_starter_material",
                        {
                            "material_id": second_material,
                            "presentation_token": token,
                        },
                    )
                    self.assertEqual("render", stale["kind"])
                    self.assertEqual(
                        first_material,
                        stale["payload"]["snapshot"]["starter_materials"][
                            "current_id"
                        ],
                    )
                    self.assertEqual(
                        first_material,
                        app._starter_current_material_id,
                    )
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                database.close()


    def test_starter_material_switch_revalidates_lease_after_progress_persistence(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="accessible-chess-book-browser-lease-starter-race-"
        ) as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    app.browser_command("shell", "screen.books")
                    visible = app.snapshot()["books"]
                    token = visible["presentation_token"]
                    initial_material = visible["starter_materials"]["current_id"]
                    target_material = visible["starter_materials"]["items"][1][
                        "material_id"
                    ]
                    before = app.reader.location()
                    real_save = app.save_book_progress
                    injected = False

                    def mutate_reader_after_progress_save() -> None:
                        nonlocal injected
                        real_save()
                        if not injected:
                            injected = True
                            app.reader.next_block()

                    with patch.object(
                        app,
                        "save_book_progress",
                        side_effect=mutate_reader_after_progress_save,
                    ):
                        rejected = app.browser_command(
                            "books",
                            "book.open_starter_material",
                            {
                                "material_id": target_material,
                                "presentation_token": token,
                            },
                        )

                    self.assertTrue(injected)
                    self.assertEqual("render", rejected["kind"])
                    self.assertEqual(initial_material, app._starter_current_material_id)
                    self.assertNotEqual(before, app.reader.location())
                    self.assertEqual(
                        app.reader.location().index,
                        rejected["payload"]["snapshot"]["block"]["index"],
                    )
                    self.assertNotEqual(
                        token,
                        rejected["payload"]["snapshot"]["presentation_token"],
                    )
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                database.close()



if __name__ == "__main__":
    unittest.main()
