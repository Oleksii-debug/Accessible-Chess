from __future__ import annotations

import unittest

from acs.visual_preferences import (
    BoardVisualPreferences,
    CoordinateMode,
    VisualPackKind,
    VisualPackManifest,
)


class BoardVisualPreferencesTests(unittest.TestCase):
    def test_coordinate_modes_are_explicit_and_round_trip(self) -> None:
        prefs = BoardVisualPreferences(
            board_theme_id="blue.green",
            piece_theme_id="large-outline",
            coordinate_mode=CoordinateMode.EVERY_SQUARE,
            board_scale_percent=125,
            piece_scale_percent=105,
            reduced_motion=True,
        )
        restored = BoardVisualPreferences.from_dict(prefs.as_dict())
        self.assertEqual(restored, prefs)
        self.assertEqual(restored.coordinate_mode, CoordinateMode.EVERY_SQUARE)

    def test_invalid_scale_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            BoardVisualPreferences(board_scale_percent=49)
        with self.assertRaises(ValueError):
            BoardVisualPreferences(piece_scale_percent=151)

    def test_invalid_theme_id_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            BoardVisualPreferences(board_theme_id="../../escape")


class VisualPackManifestTests(unittest.TestCase):
    def test_piece_pack_requires_all_twelve_piece_assets(self) -> None:
        assets = {
            f"{side}_{piece}": f"pieces/{side}-{piece}.svg"
            for side in ("white", "black")
            for piece in ("king", "queen", "rook", "bishop", "knight", "pawn")
        }
        pack = VisualPackManifest(
            "outline.large",
            "1.0.0",
            "Outline Large",
            VisualPackKind.PIECES,
            "CC0-1.0",
            assets=assets,
        )
        self.assertEqual(len(pack.assets), 12)

    def test_piece_pack_missing_asset_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            VisualPackManifest(
                "broken",
                "1",
                "Broken",
                VisualPackKind.PIECES,
                "MIT",
                assets={"white_king": "king.svg"},
            )

    def test_asset_path_cannot_escape_pack_root(self) -> None:
        with self.assertRaises(ValueError):
            VisualPackManifest(
                "board.one",
                "1",
                "Board One",
                VisualPackKind.BOARD,
                "MIT",
                assets={"texture": "../outside.png"},
            )

    def test_executable_asset_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            VisualPackManifest(
                "board.one",
                "1",
                "Board One",
                VisualPackKind.BOARD,
                "MIT",
                assets={"texture": "payload.exe"},
            )


if __name__ == "__main__":
    unittest.main()
