from __future__ import annotations

import unittest

from acs.visual_preferences import (
    VISUAL_PREFERENCES_SCHEMA_VERSION,
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
        payload = prefs.as_dict()
        self.assertEqual(payload["schema_version"], VISUAL_PREFERENCES_SCHEMA_VERSION)
        self.assertEqual(BoardVisualPreferences.from_dict(payload), prefs)

    def test_legacy_unversioned_payload_migrates(self) -> None:
        prefs = BoardVisualPreferences.from_dict(
            {
                "coordinate_mode": "every_square",
                "show_last_move": False,
                "reduced_motion": True,
            }
        )
        self.assertIs(prefs.coordinate_mode, CoordinateMode.EVERY_SQUARE)
        self.assertEqual(prefs.as_dict()["schema_version"], 1)

    def test_invalid_scale_and_boolean_types_fail_closed(self) -> None:
        for payload in (
            {"board_scale_percent": "100"},
            {"board_scale_percent": True},
            {"show_last_move": "false"},
            {"reduced_motion": 0},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    BoardVisualPreferences.from_dict(payload)

    def test_future_schema_and_unknown_fields_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            BoardVisualPreferences.from_dict({"schema_version": 2})
        with self.assertRaises(ValueError):
            BoardVisualPreferences.from_dict({"future_setting": True})

    def test_invalid_theme_id_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            BoardVisualPreferences(board_theme_id="../../escape")
        with self.assertRaises(ValueError):
            BoardVisualPreferences(board_theme_id=123)


class VisualPackManifestTests(unittest.TestCase):
    @staticmethod
    def piece_assets() -> dict[str, str]:
        return {
            f"{side}_{piece}": f"pieces/{side}-{piece}.svg"
            for side in ("white", "black")
            for piece in ("king", "queen", "rook", "bishop", "knight", "pawn")
        }

    def test_piece_pack_requires_all_twelve_piece_assets(self) -> None:
        pack = VisualPackManifest(
            "outline.large",
            "1.0.0",
            "Outline Large",
            VisualPackKind.PIECES,
            "CC0-1.0",
            assets=self.piece_assets(),
        )
        self.assertEqual(len(pack.assets), 12)

    def test_string_piece_kind_cannot_bypass_required_assets(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing required assets"):
            VisualPackManifest(
                "broken",
                "1",
                "Broken",
                "pieces",
                "MIT",
                assets={"white_king": "king.svg"},
            )

    def test_valid_string_kind_is_normalized(self) -> None:
        pack = VisualPackManifest(
            "outline.large",
            "1",
            "Outline Large",
            "pieces",
            "MIT",
            assets=self.piece_assets(),
        )
        self.assertIs(pack.kind, VisualPackKind.PIECES)

    def test_asset_paths_are_canonical_and_bounded(self) -> None:
        for path in (
            "../outside.png",
            "art//board.png",
            "art\\board.png",
            "./board.png",
            "a/b/c/d/e/f/g/h/i.png",
            f"{'x' * 129}.png",
        ):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    VisualPackManifest(
                        "board.one",
                        "1",
                        "Board One",
                        VisualPackKind.BOARD,
                        "MIT",
                        assets={"texture": path},
                    )

    def test_manifest_assets_are_snapshotted_and_read_only(self) -> None:
        source = {"texture": "board.png"}
        pack = VisualPackManifest(
            "board.one",
            "1",
            "Board One",
            VisualPackKind.BOARD,
            "MIT",
            assets=source,
        )
        source["texture"] = "changed.png"
        self.assertEqual(pack.assets["texture"], "board.png")
        with self.assertRaises(TypeError):
            pack.assets["texture"] = "other.png"

    def test_manifest_input_types_and_cardinality_are_bounded(self) -> None:
        with self.assertRaises(ValueError):
            VisualPackManifest(123, "1", "Board", "board", "MIT")
        assets = {f"asset_{index}": f"{index}.png" for index in range(129)}
        with self.assertRaisesRegex(ValueError, "too many"):
            VisualPackManifest(
                "board.one",
                "1",
                "Board",
                "board",
                "MIT",
                assets=assets,
            )


if __name__ == "__main__":
    unittest.main()
