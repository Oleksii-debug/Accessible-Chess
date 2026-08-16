from __future__ import annotations

import unittest
from pathlib import Path

from acs.teaching_board_webapp import TeachingBoardAPI
from acs.visual_board_presentation import VisualBoardPresentation
from acs.visual_preferences import BoardVisualPreferences, CoordinateMode, VisualPackKind, VisualPackManifest


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "web" / "teaching_board.html"


def piece_assets() -> dict[str, str]:
    return {
        f"{side}_{piece}": f"pieces/{side}_{piece}.svg"
        for side in ("white", "black")
        for piece in ("king", "queen", "rook", "bishop", "knight", "pawn")
    }


def board_pack() -> VisualPackManifest:
    return VisualPackManifest(
        pack_id="contrast-board",
        version="2",
        title="Contrast Board",
        kind=VisualPackKind.BOARD,
        license_id="CC0-1.0",
        assets={"light": "board/light.svg", "dark": "board/dark.svg"},
    )


def pieces_pack() -> VisualPackManifest:
    return VisualPackManifest(
        pack_id="large-pieces",
        version="3",
        title="Large Pieces",
        kind=VisualPackKind.PIECES,
        license_id="CC0-1.0",
        assets=piece_assets(),
    )


class FakeAssetUrls:
    def __init__(self, prefix: str = "app-asset://packs") -> None:
        self.prefix = prefix
        self.calls: list[tuple[str, str]] = []

    def resolve(self, pack_id: str, asset_id: str) -> str:
        self.calls.append((pack_id, asset_id))
        return f"{self.prefix}/{pack_id}/{asset_id}.svg"


class VisualBoardPresentationTests(unittest.TestCase):
    def make_renderer(self, asset_urls=None) -> VisualBoardPresentation:
        return VisualBoardPresentation(packs=(board_pack(), pieces_pack()), asset_urls=asset_urls)

    def test_snapshot_is_exactly_64_squares_in_visual_rank_order(self) -> None:
        view = self.make_renderer().snapshot(BoardVisualPreferences())
        self.assertEqual(len(view["squares"]), 64)
        self.assertEqual(view["squares"][0]["square"], "a8")
        self.assertEqual(view["squares"][7]["square"], "h8")
        self.assertEqual(view["squares"][-1]["square"], "h1")
        self.assertEqual(view["squares"][0]["row"], 1)
        self.assertEqual(view["squares"][0]["column"], 1)

    def test_accessible_square_name_is_independent_of_board_and_piece_theme(self) -> None:
        renderer = self.make_renderer()
        classic = renderer.snapshot(BoardVisualPreferences(), pieces={"f3": "white_knight"})
        themed = renderer.snapshot(
            BoardVisualPreferences(board_theme_id="contrast-board", piece_theme_id="large-pieces"),
            pieces={"f3": "white_knight"},
        )
        classic_f3 = next(x for x in classic["squares"] if x["square"] == "f3")
        themed_f3 = next(x for x in themed["squares"] if x["square"] == "f3")
        self.assertEqual(classic_f3["accessibleName"], "білий кінь, f 3")
        self.assertEqual(themed_f3["accessibleName"], classic_f3["accessibleName"])

    def test_empty_square_accessible_name_is_concise(self) -> None:
        view = self.make_renderer().snapshot(BoardVisualPreferences())
        e4 = next(x for x in view["squares"] if x["square"] == "e4")
        self.assertEqual(e4["accessibleName"], "e 4")

    def test_coordinate_mode_off_hides_all_visual_coordinates_only(self) -> None:
        view = self.make_renderer().snapshot(BoardVisualPreferences(coordinate_mode=CoordinateMode.OFF))
        self.assertTrue(all(not x["coordinateText"] for x in view["squares"]))
        self.assertEqual(next(x for x in view["squares"] if x["square"] == "e4")["accessibleName"], "e 4")

    def test_coordinate_mode_edges_is_bounded_to_a_file_and_first_rank(self) -> None:
        view = self.make_renderer().snapshot(BoardVisualPreferences(coordinate_mode=CoordinateMode.EDGES))
        a4 = next(x for x in view["squares"] if x["square"] == "a4")
        e1 = next(x for x in view["squares"] if x["square"] == "e1")
        e4 = next(x for x in view["squares"] if x["square"] == "e4")
        self.assertEqual(a4["coordinateText"], "4")
        self.assertEqual(e1["coordinateText"], "e")
        self.assertEqual(e4["coordinateText"], "")

    def test_coordinate_mode_every_square_shows_each_square_visually(self) -> None:
        view = self.make_renderer().snapshot(BoardVisualPreferences(coordinate_mode=CoordinateMode.EVERY_SQUARE))
        self.assertTrue(all(x["coordinateText"] == x["square"] for x in view["squares"]))

    def test_board_and_piece_theme_are_selected_independently(self) -> None:
        view = self.make_renderer().snapshot(
            BoardVisualPreferences(board_theme_id="contrast-board", piece_theme_id="large-pieces")
        )
        self.assertEqual(view["boardThemeId"], "contrast-board")
        self.assertEqual(view["pieceThemeId"], "large-pieces")
        self.assertFalse(view["boardFallbackUsed"])
        self.assertFalse(view["pieceFallbackUsed"])

    def test_missing_theme_falls_back_without_changing_requested_setting_or_semantics(self) -> None:
        view = self.make_renderer().snapshot(
            BoardVisualPreferences(board_theme_id="missing-board", piece_theme_id="missing-pieces"),
            pieces={"e1": "white_king"},
        )
        self.assertEqual(view["requestedBoardThemeId"], "missing-board")
        self.assertEqual(view["requestedPieceThemeId"], "missing-pieces")
        self.assertEqual(view["boardThemeId"], "classic")
        self.assertEqual(view["pieceThemeId"], "classic")
        self.assertTrue(view["boardFallbackUsed"])
        self.assertTrue(view["pieceFallbackUsed"])
        self.assertEqual(next(x for x in view["squares"] if x["square"] == "e1")["accessibleName"], "білий король, e 1")

    def test_safe_piece_asset_resolution_uses_only_piece_pack(self) -> None:
        resolver = FakeAssetUrls()
        view = self.make_renderer(resolver).snapshot(
            BoardVisualPreferences(board_theme_id="contrast-board", piece_theme_id="large-pieces"),
            pieces={"f3": "white_knight"},
        )
        f3 = next(x for x in view["squares"] if x["square"] == "f3")
        self.assertEqual(f3["pieceAssetUrl"], "app-asset://packs/large-pieces/white_knight.svg")
        self.assertEqual(resolver.calls, [("large-pieces", "white_knight")])

    def test_unsafe_asset_url_is_rejected_and_semantic_piece_remains(self) -> None:
        for prefix in ("file:///tmp", "https://example.invalid", "javascript:alert"):
            view = self.make_renderer(FakeAssetUrls(prefix)).snapshot(
                BoardVisualPreferences(piece_theme_id="large-pieces"),
                pieces={"f3": "white_knight"},
            )
            f3 = next(x for x in view["squares"] if x["square"] == "f3")
            self.assertIsNone(f3["pieceAssetUrl"])
            self.assertEqual(f3["accessibleName"], "білий кінь, f 3")

    def test_pointer_and_last_move_are_overlay_flags_not_names(self) -> None:
        view = self.make_renderer().snapshot(
            BoardVisualPreferences(show_last_move=True),
            pointer_square="f3",
            last_move=("g1", "f3"),
        )
        f3 = next(x for x in view["squares"] if x["square"] == "f3")
        g1 = next(x for x in view["squares"] if x["square"] == "g1")
        self.assertTrue(f3["isPointer"])
        self.assertTrue(f3["isLastMove"])
        self.assertTrue(g1["isLastMove"])
        self.assertEqual(f3["accessibleName"], "f 3")

    def test_scale_and_reduced_motion_project_without_touching_square_semantics(self) -> None:
        prefs = BoardVisualPreferences(board_scale_percent=155, piece_scale_percent=130, reduced_motion=True)
        view = self.make_renderer().snapshot(prefs)
        self.assertEqual(view["boardScalePercent"], 155)
        self.assertEqual(view["pieceScalePercent"], 130)
        self.assertTrue(view["reducedMotion"])
        self.assertEqual(next(x for x in view["squares"] if x["square"] == "a1")["accessibleName"], "a 1")

    def test_invalid_piece_or_square_fails_closed(self) -> None:
        renderer = self.make_renderer()
        with self.assertRaises(ValueError):
            renderer.snapshot(BoardVisualPreferences(), pieces={"z9": "white_king"})
        with self.assertRaises(ValueError):
            renderer.snapshot(BoardVisualPreferences(), pieces={"a1": "dragon"})
        with self.assertRaises(ValueError):
            renderer.snapshot(BoardVisualPreferences(), pointer_square="i4")


class TeachingBoardApiTests(unittest.TestCase):
    def test_board_api_composes_existing_teaching_state_and_preview_only_pieces(self) -> None:
        api = TeachingBoardAPI(visual_packs=(board_pack(), pieces_pack()))
        before = api.teaching_board_visual_snapshot()
        self.assertEqual(len(before["squares"]), 64)
        self.assertEqual(next(x for x in before["squares"] if x["square"] == "e1")["pieceId"], "white_king")
        api.teaching_set_visual_preferences({
            "board_theme_id": "contrast-board",
            "piece_theme_id": "large-pieces",
            "coordinate_mode": "every_square",
            "board_scale_percent": 120,
            "piece_scale_percent": 110,
        })
        api.teaching_pointer_commit("f3")
        after = api.teaching_board_visual_snapshot()
        self.assertEqual(after["boardThemeId"], "contrast-board")
        self.assertEqual(after["pieceThemeId"], "large-pieces")
        self.assertTrue(next(x for x in after["squares"] if x["square"] == "f3")["isPointer"])


class TeachingBoardSemanticHtmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = HTML.read_text(encoding="utf-8")

    def test_surface_exposes_complete_visual_cluster(self) -> None:
        for control_id in ("board-theme", "piece-theme", "coordinate-mode", "board-scale", "piece-scale", "apply-visual"):
            self.assertIn(f'id="{control_id}"', self.html)
        self.assertIn("teaching_board_visual_snapshot", self.html)
        self.assertIn("snapshot.availablePacks", self.html)

    def test_board_uses_renderer_accessible_names_and_visual_assets_are_hidden(self) -> None:
        self.assertIn("cell.setAttribute('aria-label',row.accessibleName)", self.html)
        self.assertIn("img.alt=''", self.html)
        self.assertIn("wrap.setAttribute('aria-hidden','true')", self.html)
        self.assertNotIn("aria-label',snapshot.visual", self.html)

    def test_visual_coordinates_are_not_added_to_accessibility_tree(self) -> None:
        self.assertIn("coord.setAttribute('aria-hidden','true')", self.html)
        self.assertIn("row.coordinateText", self.html)

    def test_theme_and_piece_set_are_applied_independently(self) -> None:
        self.assertIn("board_theme_id:el('board-theme').value", self.html)
        self.assertIn("piece_theme_id:el('piece-theme').value", self.html)
        self.assertIn("board.dataset.boardTheme=visualBoard.boardThemeId", self.html)
        self.assertIn("board.dataset.pieceTheme=visualBoard.pieceThemeId", self.html)

    def test_pointer_input_still_auto_commits_clears_and_refocuses(self) -> None:
        self.assertIn("teaching_pointer_commit", self.html)
        self.assertIn("event.target.value=''", self.html)
        self.assertIn("event.target.focus()", self.html)
        self.assertIn("returnBoardFocus:true", self.html)

    def test_keyboard_board_remains_reusable_and_no_global_command_hijack(self) -> None:
        self.assertIn('src="accessible_board_keyboard.js"', self.html)
        self.assertNotIn("document.addEventListener('keydown'", self.html)
        self.assertNotIn('window.addEventListener("keydown"', self.html)
        self.assertEqual(self.html.count('role="status"'), 1)

    def test_fallback_is_passive_not_live_spam(self) -> None:
        self.assertIn('id="visual-fallback" class="fallback" aria-live="off"', self.html)
        self.assertIn("boardFallbackUsed", self.html)
        self.assertIn("pieceFallbackUsed", self.html)


if __name__ == "__main__":
    unittest.main()
