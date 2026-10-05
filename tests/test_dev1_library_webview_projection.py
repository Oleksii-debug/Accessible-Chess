from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from acs.full_product_presenters import LibraryPresenter, SurfaceStatus
from acs.full_product_ui_shell import UILanguage
from acs.library_import_service import LibraryImportProgress, LibraryImportResult
from acs.library_webview_bridge import LibraryWebViewBridge
from acs.library_webview_projection import LibraryWebViewProjection
from acs.search_service import GameSearchItem, GameSearchPage, GameSearchQuery


def item(
    game_id: int,
    *,
    source_id: int = 10,
    source_name: str = r"C:\private\library.pgn",
    source_index: int = 0,
    white: str = "Alpha",
    black: str = "Beta",
    event: str | None = "Event",
    result: str = "1-0",
    eco: str | None = "C20",
    opening: str | None = "King Pawn",
) -> GameSearchItem:
    return GameSearchItem(
        game_id=game_id,
        source_id=source_id,
        source_name=source_name,
        source_format="PGN",
        source_index=source_index,
        import_status="full",
        white=white,
        black=black,
        event=event,
        site=None,
        game_date="2026.08.22",
        round="1",
        result=result,
        eco=eco,
        opening=opening,
        start_fen=None,
    )


class FakeSearchService:
    def __init__(self) -> None:
        self.calls: list[GameSearchQuery] = []
        self.pages = {
            None: GameSearchPage(
                items=(
                    item(1, source_index=0, white="Олексій", black="Beta"),
                    item(2, source_index=1, white="Gamma", black="Delta", result="0-1"),
                ),
                next_after_game_id=2,
                has_more=True,
            ),
            2: GameSearchPage(
                items=(
                    item(
                        3,
                        source_id=11,
                        source_name="/home/private/second.pgn",
                        white="Epsilon",
                        black="Zeta",
                        result="1/2-1/2",
                    ),
                ),
                next_after_game_id=None,
                has_more=False,
            ),
        }

    def search(self, query: GameSearchQuery) -> GameSearchPage:
        normalized = query.normalized()
        self.calls.append(normalized)
        return self.pages[normalized.after_game_id]


class FailingSearchService:
    def search(self, query: GameSearchQuery) -> GameSearchPage:
        raise RuntimeError(r"sqlite OperationalError at C:\private\library.db query SELECT secret")


class LibraryWebViewProjectionTests(unittest.TestCase):
    def build(self, service=None, *, language=UILanguage.EN):
        service = service or FakeSearchService()
        calls = []

        def dispatch(action_id, payload):
            calls.append((action_id, dict(payload)))
            return {"internal": "backend value must not reach browser"}

        presenter = LibraryPresenter(service, language=language)
        projection = LibraryWebViewProjection(presenter, dispatch, language=language)
        bridge = LibraryWebViewBridge(projection)
        return service, presenter, projection, bridge, calls

    def test_search_projects_semantic_rows_and_explicit_focus_from_one_view(self) -> None:
        _service, _presenter, projection, _bridge, _calls = self.build()
        event = projection.search(GameSearchQuery(player="  Олексій  ", limit=2))
        snapshot = event.payload["snapshot"]
        self.assertEqual("render", event.kind)
        self.assertEqual("ready", snapshot["status"])
        self.assertEqual(2, len(snapshot["rows"]))
        self.assertEqual(1, snapshot["selected_game_id"])
        selected = [row for row in snapshot["rows"] if row["selected"]]
        self.assertEqual(1, len(selected))
        self.assertEqual(selected[0]["dom_id"], snapshot["focus_target"])
        self.assertEqual("library.pgn", selected[0]["source_label"])
        self.assertNotIn("private", selected[0]["source_label"].casefold())

    def test_filter_projection_never_exposes_keyset_cursor(self) -> None:
        _service, _presenter, projection, _bridge, _calls = self.build()
        projection.search(
            GameSearchQuery(
                player="Alpha",
                event="Event",
                eco="C2",
                opening="King",
                result="1-0",
                source_id=10,
                source_name="library",
                limit=25,
            )
        )
        snapshot = projection.snapshot()
        ids = {field["id"] for field in snapshot["filters"]}
        self.assertEqual(
            {"player", "event", "eco", "opening", "result", "source_id", "source_name", "limit", "date_from", "date_to"},
            ids,
        )
        self.assertNotIn("after_game_id", repr(snapshot))

    def test_keyset_paging_is_owned_by_presenter_not_browser_payload(self) -> None:
        service, _presenter, projection, bridge, _calls = self.build()
        bridge.dispatch("library.search", {"player": "Alpha", "limit": "2"})
        event = bridge.dispatch("library.next_page", {})
        snapshot = event.payload["snapshot"]
        self.assertEqual(3, snapshot["selected_game_id"])
        self.assertEqual("second.pgn", snapshot["rows"][0]["source_label"])
        self.assertEqual([None, 2], [call.after_game_id for call in service.calls])
        self.assertNotIn("after_game_id", repr(snapshot))

    def test_keyboard_selection_moves_only_inside_current_rendered_page(self) -> None:
        _service, _presenter, projection, bridge, _calls = self.build()
        projection.search(GameSearchQuery(limit=2))
        moved = bridge.dispatch("library.move", {"delta": 1})
        snapshot = moved.payload["snapshot"]
        self.assertEqual(2, snapshot["selected_game_id"])
        self.assertEqual(2, [row for row in snapshot["rows"] if row["selected"]][0]["game_id"])
        boundary = bridge.dispatch("library.move", {"delta": 1})
        self.assertEqual("error", boundary.kind)

    def test_failed_search_render_restores_query_page_and_selection(self) -> None:
        _service, presenter, projection, bridge, _calls = self.build()
        projection.search(GameSearchQuery(player="Alpha", limit=2))
        projection.select(2)
        before_query = projection.query
        before = projection.snapshot()

        with patch.object(
            projection,
            "_snapshot_from_view",
            side_effect=ValueError("candidate search render rejected"),
        ):
            failed = bridge.dispatch(
                "library.search",
                {"player": "Gamma", "limit": "2"},
            )

        self.assertEqual("error", failed.kind)
        self.assertEqual(before_query, projection.query)
        self.assertEqual(2, presenter.selected_game_id)
        after = projection.snapshot()
        self.assertEqual(before["rows"], after["rows"])
        self.assertEqual(before["selected_game_id"], after["selected_game_id"])
        self.assertEqual(
            {field["id"]: field["value"] for field in before["filters"]},
            {field["id"]: field["value"] for field in after["filters"]},
        )

    def test_abort_class_search_render_restores_query_page_and_selection(self) -> None:
        _service, presenter, projection, _bridge, _calls = self.build()
        projection.search(GameSearchQuery(player="Alpha", limit=2))
        projection.select(2)
        before_query = projection.query
        before = projection.snapshot()

        class ProjectionAbort(BaseException):
            pass

        with patch.object(
            projection,
            "_snapshot_from_view",
            side_effect=ProjectionAbort(),
        ):
            with self.assertRaises(ProjectionAbort):
                projection.search(GameSearchQuery(player="Gamma", limit=2))

        self.assertEqual(before_query, projection.query)
        self.assertEqual(2, presenter.selected_game_id)
        after = projection.snapshot()
        self.assertEqual(before["rows"], after["rows"])
        self.assertEqual(before["selected_game_id"], after["selected_game_id"])
        self.assertEqual(
            {field["id"]: field["value"] for field in before["filters"]},
            {field["id"]: field["value"] for field in after["filters"]},
        )

    def test_failed_selection_render_restores_previous_nvda_cursor(self) -> None:
        _service, presenter, projection, bridge, _calls = self.build()
        projection.search(GameSearchQuery(limit=2))
        before = projection.snapshot()
        self.assertEqual(1, before["selected_game_id"])

        with patch.object(
            projection,
            "_snapshot_from_view",
            side_effect=ValueError("candidate selection render rejected"),
        ):
            failed = bridge.dispatch("library.select", {"game_id": 2})

        self.assertEqual("error", failed.kind)
        self.assertEqual(1, presenter.selected_game_id)
        after = projection.snapshot()
        self.assertEqual(1, after["selected_game_id"])
        self.assertEqual(before["focus_target"], after["focus_target"])

    def test_failed_next_page_render_discards_unpublished_page_cache(self) -> None:
        service, presenter, projection, bridge, _calls = self.build()
        projection.search(GameSearchQuery(limit=2))
        before = projection.snapshot()
        self.assertEqual([None], [call.after_game_id for call in service.calls])

        with patch.object(
            projection,
            "_snapshot_from_view",
            side_effect=ValueError("candidate page render rejected"),
        ):
            failed = bridge.dispatch("library.next_page", {})

        self.assertEqual("error", failed.kind)
        self.assertEqual([None, 2], [call.after_game_id for call in service.calls])
        after = projection.snapshot()
        self.assertEqual(before["rows"], after["rows"])
        self.assertEqual(before["selected_game_id"], after["selected_game_id"])
        self.assertEqual(1, presenter.selected_game_id)

        committed = bridge.dispatch("library.next_page", {})
        self.assertEqual("render", committed.kind)
        self.assertEqual(3, committed.payload["snapshot"]["selected_game_id"])
        self.assertEqual([None, 2, 2], [call.after_game_id for call in service.calls])

    def test_open_selected_delegates_only_neutral_identifiers_and_hides_return_value(self) -> None:
        _service, _presenter, projection, bridge, calls = self.build()
        projection.search(GameSearchQuery(limit=2))
        bridge.dispatch("library.select", {"game_id": 2})
        event = bridge.dispatch("library.open_game", {})
        self.assertEqual("delegated", event.kind)
        self.assertEqual({"action": "library.open_game"}, dict(event.payload))
        self.assertEqual(
            [("library.open_game", {"game_id": 2, "source_id": 10, "source_index": 1})],
            calls,
        )
        self.assertNotIn("backend value", repr(event.payload))

    def test_search_error_is_concise_and_does_not_leak_database_or_path_details(self) -> None:
        _service, _presenter, projection, _bridge, _calls = self.build(FailingSearchService())
        event = projection.search(GameSearchQuery(player="secret"))
        snapshot = event.payload["snapshot"]
        self.assertEqual(SurfaceStatus.ERROR.value, snapshot["status"])
        text = (snapshot["message"] + " " + snapshot["summary"]).casefold()
        self.assertNotIn("sqlite", text)
        self.assertNotIn("select", text)
        self.assertNotIn("c:\\", text)
        self.assertNotIn("private", text)

    def test_bridge_rejects_cursor_and_unknown_fields_without_reflecting_values(self) -> None:
        _service, _presenter, _projection, bridge, _calls = self.build()
        for payload in (
            {"after_game_id": 999},
            {"player": "TOP-SECRET", "sql": "SELECT * FROM games"},
            {"source_id": "999999999999999999999999999"},
            {"limit": 0},
        ):
            event = bridge.dispatch("library.search", payload)
            self.assertEqual("error", event.kind)
            visible = repr(event.payload).casefold()
            self.assertNotIn("top-secret", visible)
            self.assertNotIn("select *", visible)
            self.assertNotIn("999999", visible)

    def test_bridge_rejects_active_browser_subclasses_before_hooks(self) -> None:
        _service, _presenter, _projection, bridge, _calls = self.build()

        class HostileText(str):
            armed = False
            touched = False

            def _touch(self):
                if type(self).armed:
                    type(self).touched = True
                    raise AssertionError("hostile browser text hook must not execute")

            def __len__(self):
                self._touch()
                return super().__len__()

            def __eq__(self, other):
                self._touch()
                return super().__eq__(other)

            def __hash__(self):
                self._touch()
                return super().__hash__()

            def strip(self, *args, **kwargs):
                self._touch()
                return super().strip(*args, **kwargs)

            def isascii(self):
                self._touch()
                return super().isascii()

            def isdecimal(self):
                self._touch()
                return super().isdecimal()

        class HostileDict(dict):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("hostile browser mapping length must not execute")

            def __iter__(self):
                type(self).touched = True
                raise AssertionError("hostile browser mapping iteration must not execute")

            def items(self):
                type(self).touched = True
                raise AssertionError("hostile browser mapping items must not execute")

        hostile_command = HostileText("library.search")
        hostile_key = HostileText("player")
        hostile_value = HostileText("Alpha")
        hostile_key_payload = {hostile_key: "Alpha"}
        hostile_value_payload = {"player": hostile_value}
        hostile_numeric_payload = {"source_id": HostileText("10")}
        hostile_result_payload = {"result": HostileText("1-0")}
        hostile_language_payload = {"language": HostileText("en")}
        HostileText.armed = True

        cases = (
            (hostile_command, {}),
            ("library.search", HostileDict({"player": "Alpha"})),
            ("library.search", hostile_key_payload),
            ("library.search", hostile_value_payload),
            ("library.search", hostile_numeric_payload),
            ("library.search", hostile_result_payload),
            ("library.language", hostile_language_payload),
        )
        for command, payload in cases:
            with self.subTest(command=type(command).__name__, payload_type=type(payload).__name__):
                event = bridge.dispatch(command, payload)
                self.assertEqual("error", event.kind)

        self.assertFalse(HostileText.touched)
        self.assertFalse(HostileDict.touched)

    def test_language_switch_changes_labels_but_preserves_row_and_focus_identity(self) -> None:
        _service, _presenter, projection, _bridge, _calls = self.build(language=UILanguage.UA)
        ua = projection.search(GameSearchQuery(limit=2)).payload["snapshot"]
        en = projection.set_language(UILanguage.EN).payload["snapshot"]
        self.assertNotEqual(ua["heading"], en["heading"])
        self.assertEqual(
            [row["dom_id"] for row in ua["rows"]],
            [row["dom_id"] for row in en["rows"]],
        )
        self.assertEqual(ua["focus_target"], en["focus_target"])

    def test_failed_language_render_rolls_back_library_presenter_and_import_locale(self) -> None:
        service = FakeSearchService()
        service.pages[None] = GameSearchPage(
            items=(
                item(1, white=None, black=None),
            ),
            next_after_game_id=None,
            has_more=False,
        )
        _service, presenter, projection, bridge, _calls = self.build(
            service,
            language=UILanguage.UA,
        )
        projection.search(GameSearchQuery(limit=25))
        before = projection.snapshot()

        with patch.object(
            projection,
            "_snapshot_from_view",
            side_effect=ValueError("candidate library render rejected"),
        ):
            failed = bridge.dispatch("library.language", {"language": "en"})

        self.assertEqual("error", failed.kind)
        self.assertEqual(UILanguage.UA, projection.language)

        # All three language owners must still describe the same previous
        # locale after the failed browser transition.
        after = projection.snapshot()
        self.assertEqual(before["document"], after["document"])
        self.assertEqual(before["heading"], after["heading"])
        self.assertEqual(before["import"]["document"], after["import"]["document"])
        self.assertIn("невідомо", after["rows"][0]["label"])
        self.assertIn("невідомо", presenter.view().rows[0].label)

        # The rollback must be recoverable: a later valid transition can commit
        # normally instead of inheriting a mixed or poisoned state.
        committed = projection.set_language(UILanguage.EN).payload["snapshot"]
        self.assertNotEqual(before["heading"], committed["heading"])
        self.assertIn("unknown", committed["rows"][0]["label"])
        self.assertNotEqual(
            before["import"]["document"],
            committed["import"]["document"],
        )

    def test_abort_class_language_render_restores_all_locale_owners(self) -> None:
        service = FakeSearchService()
        service.pages[None] = GameSearchPage(
            items=(item(1, white=None, black=None),),
            next_after_game_id=None,
            has_more=False,
        )
        _service, presenter, projection, _bridge, _calls = self.build(
            service,
            language=UILanguage.UA,
        )
        projection.search(GameSearchQuery(limit=25))
        before = projection.snapshot()

        class ProjectionAbort(BaseException):
            pass

        with patch.object(
            projection,
            "_snapshot_from_view",
            side_effect=ProjectionAbort(),
        ):
            with self.assertRaises(ProjectionAbort):
                projection.set_language(UILanguage.EN)

        self.assertEqual(UILanguage.UA, projection.language)
        after = projection.snapshot()
        self.assertEqual(before["document"], after["document"])
        self.assertEqual(before["heading"], after["heading"])
        self.assertEqual(before["import"]["document"], after["import"]["document"])
        self.assertIn("невідомо", after["rows"][0]["label"])
        self.assertIn("невідомо", presenter.view().rows[0].label)

    def test_presenter_subclass_is_rejected_before_presentation_hooks(self) -> None:
        service = FakeSearchService()

        class HostilePresenter(LibraryPresenter):
            armed = False
            touched = False

            def set_language(self, language):
                if type(self).armed:
                    type(self).touched = True
                    raise AssertionError("hostile Library presenter hook must not execute")
                return super().set_language(language)

        hostile = HostilePresenter(service, language=UILanguage.EN)
        HostilePresenter.armed = True

        with self.assertRaisesRegex(TypeError, "presenter must be LibraryPresenter"):
            LibraryWebViewProjection(
                hostile,
                lambda _action, _payload: None,
                language=UILanguage.EN,
            )

        self.assertFalse(HostilePresenter.touched)

    def test_snapshot_does_not_mix_live_selection_changed_after_immutable_view_capture(self) -> None:
        service = FakeSearchService()
        presenter = LibraryPresenter(service, language=UILanguage.EN)
        projection = LibraryWebViewProjection(
            presenter,
            lambda _action, _payload: None,
            language=UILanguage.EN,
        )
        # Seed pages before injecting re-entrant view behavior so the product
        # ingress contract stays exact while the atomicity proof stays adversarial.
        presenter.search(GameSearchQuery(limit=2))
        presenter._selected_game_id = 1
        original_view = presenter.view
        state = {"view_calls": 0, "live_selection_after_read": None}

        def mutating_view():
            state["view_calls"] += 1
            view = original_view()
            if state["view_calls"] == 1 and len(view.rows) > 1:
                presenter._selected_game_id = view.rows[1].game_id
                state["live_selection_after_read"] = presenter._selected_game_id
            return view

        with patch.object(presenter, "view", side_effect=mutating_view):
            snapshot = projection.snapshot()

        self.assertEqual(1, state["view_calls"])
        self.assertEqual(2, state["live_selection_after_read"])
        self.assertEqual(1, snapshot["selected_game_id"])
        self.assertEqual(1, [row for row in snapshot["rows"] if row["selected"]][0]["game_id"])


    def test_browser_game_identity_boundary_matches_javascript_number_contract(self) -> None:
        maximum = (1 << 53) - 1
        service = FakeSearchService()
        service.pages[None] = GameSearchPage(
            items=(item(maximum),),
            next_after_game_id=None,
            has_more=False,
        )
        _service, _presenter, projection, _bridge, _calls = self.build(service)
        event = projection.search(GameSearchQuery(limit=25))
        self.assertEqual(maximum, event.payload["snapshot"]["rows"][0]["game_id"])

        oversized = FakeSearchService()
        oversized.pages[None] = GameSearchPage(
            items=(item(maximum + 1),),
            next_after_game_id=None,
            has_more=False,
        )
        _service, _presenter, projection, _bridge, _calls = self.build(oversized)
        with self.assertRaisesRegex(ValueError, "browser-safe"):
            projection.search(GameSearchQuery(limit=25))
        with self.assertRaisesRegex(ValueError, "browser-safe"):
            projection.select(maximum + 1)

    def test_import_projection_rejects_derived_progress_before_field_hooks(self) -> None:
        _service, _presenter, projection, _bridge, _calls = self.build()
        projection.import_projection.begin(2)
        touched = []

        class ActiveProgress(LibraryImportProgress):
            def __getattribute__(self, name):
                if name in {"attempt_id", "processed_games", "total_games"}:
                    touched.append(name)
                    raise AssertionError("derived progress field hook executed")
                return super().__getattribute__(name)

        hostile = ActiveProgress.__new__(ActiveProgress)
        object.__setattr__(hostile, "attempt_id", 1)
        object.__setattr__(hostile, "processed_games", 1)
        object.__setattr__(hostile, "total_games", 2)

        with self.assertRaisesRegex(TypeError, "exact LibraryImportProgress"):
            projection.import_projection.progress(hostile)

        self.assertEqual(touched, [])
        self.assertEqual(projection.import_projection.snapshot()["processed_games"], 0)

    def test_import_projection_revalidates_exact_progress_scalars_before_comparison(self) -> None:
        _service, _presenter, projection, _bridge, _calls = self.build()
        projection.import_projection.begin(2)
        touched = []

        class ActiveInt(int):
            def __lt__(self, other):
                touched.append("lt")
                raise AssertionError("active scalar comparison executed")

            def __gt__(self, other):
                touched.append("gt")
                raise AssertionError("active scalar comparison executed")

            def __eq__(self, other):
                touched.append("eq")
                raise AssertionError("active scalar equality executed")

        hostile = LibraryImportProgress(1, 1, 2)
        object.__setattr__(hostile, "processed_games", ActiveInt(1))

        with self.assertRaises(TypeError):
            projection.import_projection.progress(hostile)

        self.assertEqual(touched, [])
        self.assertEqual(projection.import_projection.snapshot()["processed_games"], 0)

    def test_import_projection_rejects_derived_result_before_field_hooks(self) -> None:
        _service, _presenter, projection, _bridge, _calls = self.build()
        projection.import_projection.begin(2)
        touched = []

        class ActiveResult(LibraryImportResult):
            def __getattribute__(self, name):
                if name in {
                    "attempt_id",
                    "source_id",
                    "game_count",
                    "warning_count",
                    "first_game_id",
                    "last_game_id",
                    "reused",
                }:
                    touched.append(name)
                    raise AssertionError("derived result field hook executed")
                return super().__getattribute__(name)

        hostile = ActiveResult.__new__(ActiveResult)
        for name, value in (
            ("attempt_id", 1),
            ("source_id", 1),
            ("game_count", 2),
            ("warning_count", 0),
            ("first_game_id", 1),
            ("last_game_id", 2),
            ("reused", False),
        ):
            object.__setattr__(hostile, name, value)

        with self.assertRaisesRegex(TypeError, "exact LibraryImportResult"):
            projection.import_projection.complete(hostile)

        self.assertEqual(touched, [])
        self.assertEqual(projection.import_projection.phase.value, "running")

    def test_import_count_boundary_matches_javascript_number_contract(self) -> None:
        maximum = (1 << 53) - 1
        _service, _presenter, projection, _bridge, _calls = self.build()
        event = projection.import_projection.begin(maximum)
        self.assertEqual(maximum, event.payload["import"]["total_games"])

        _service, _presenter, projection, _bridge, _calls = self.build()
        with self.assertRaisesRegex(ValueError, "browser-safe"):
            projection.import_projection.begin(maximum + 1)


class LibraryWebAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (Path(__file__).parents[1] / "web" / "full_product_library.js").read_text(
            encoding="utf-8"
        )

    def test_renderer_uses_semantic_form_listbox_options_and_native_controls(self) -> None:
        source = self.source
        self.assertIn('node("form")', source)
        self.assertIn('node("input")', source)
        self.assertIn('node("select")', source)
        self.assertIn('node("button"', source)
        self.assertIn('setAttribute("role", "listbox")', source)
        self.assertIn('setAttribute("role", "option")', source)
        self.assertIn('setAttribute("aria-selected"', source)

    def test_renderer_never_uses_markup_injection(self) -> None:
        source = self.source
        self.assertIn("textContent", source)
        for token in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            self.assertNotIn(token, source)

    def test_keyboard_handler_is_scoped_to_result_options(self) -> None:
        source = self.source
        self.assertIn('option.addEventListener("keydown"', source)
        self.assertNotIn('document.addEventListener("keydown"', source)
        self.assertNotIn('window.addEventListener("keydown"', source)
        self.assertIn('event.key === "ArrowUp"', source)
        self.assertIn('event.key === "ArrowDown"', source)
        self.assertIn('event.key === "Enter"', source)

    def test_renderer_does_not_create_background_live_region_spam(self) -> None:
        source = self.source
        self.assertIn('setAttribute("aria-live", "off")', source)
        self.assertNotIn('aria-live", "polite"', source)
        self.assertNotIn('setAttribute("role", "status")', source)

    def test_transport_rejection_is_handled_without_backend_text(self) -> None:
        source = self.source
        self.assertIn('.catch(function ()', source)
        self.assertIn("transport_error_message", source)
        self.assertNotIn("error.message", source)
        self.assertNotIn("reason.message", source)

    def test_focus_moves_only_to_explicit_requested_target(self) -> None:
        source = self.source
        self.assertIn("function focusRequestedOption(root, focusTarget)", source)
        self.assertIn('focusRequestedOption(root, requestedFocus || "")', source)
        self.assertNotIn('[role="option"][aria-selected="true"]', source)

    def test_import_progress_uses_native_controls_without_live_region_spam(self) -> None:
        source = self.source
        self.assertIn('node("progress")', source)
        self.assertIn('focusTarget === "library-import-file"', source)
        self.assertIn('focusTarget === "library-import-cancel"', source)
        self.assertIn('result.kind === "render-import"', source)
        self.assertIn('root.querySelector("#library-import-region")', source)
        self.assertIn("region.contains(active)", source)
        self.assertIn("region.replaceWith(replacement)", source)
        self.assertIn("apply: applyLibraryEvent", source)
        self.assertIn('status.setAttribute("aria-live", "off")', source)
        self.assertNotIn('input.type = "file"', source)


if __name__ == "__main__":
    unittest.main()
