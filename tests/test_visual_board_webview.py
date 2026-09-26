import hashlib
from pathlib import Path
import tempfile
import unittest

from acs.visual_board_webview import (
    VisualBoardWebViewError,
    VisualBoardWebViewState,
)
from acs.visual_pack_store import VisualPackStore, VisualPreferencesStore
from acs.visual_preferences import (
    BoardVisualPreferences,
    CoordinateMode,
    VisualAssetSpec,
    VisualPackKind,
    VisualPackManifest,
)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _png(label: bytes, *, pad: int = 0) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + label + (b"x" * pad)


def _board_pack(
    *,
    pack_id: str = "contrast",
    version: str = "1.0.0",
    pad: int = 0,
) -> tuple[VisualPackManifest, dict[str, bytes]]:
    light = _png(b"light", pad=pad)
    dark = _png(b"dark", pad=pad)
    payloads = {
        "board/light.png": light,
        "board/dark.png": dark,
    }
    manifest = VisualPackManifest(
        pack_id=pack_id,
        version=version,
        title="Contrast",
        kind=VisualPackKind.BOARD,
        license_id="CC0-1.0",
        author="Accessible Chess",
        provenance="Project-authored test fixture.",
        assets={
            "light_square": VisualAssetSpec("board/light.png", _digest(light)),
            "dark_square": VisualAssetSpec("board/dark.png", _digest(dark)),
        },
    )
    return manifest, payloads


def _piece_pack() -> tuple[VisualPackManifest, dict[str, bytes]]:
    assets: dict[str, VisualAssetSpec] = {}
    payloads: dict[str, bytes] = {}
    for side in ("white", "black"):
        for piece in ("king", "queen", "rook", "bishop", "knight", "pawn"):
            asset_id = f"{side}_{piece}"
            path = f"pieces/{asset_id}.png"
            data = _png(asset_id.encode())
            assets[asset_id] = VisualAssetSpec(path, _digest(data))
            payloads[path] = data
    return (
        VisualPackManifest(
            pack_id="large-pieces",
            version="2.0.0",
            title="Large pieces",
            kind=VisualPackKind.PIECES,
            license_id="CC-BY-4.0",
            author="Accessible Chess",
            provenance="Project-authored test fixture.",
            assets=assets,
        ),
        payloads,
    )


class VisualBoardWebViewStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.pack_store = VisualPackStore(root / "packs")
        self.preference_store = VisualPreferencesStore(root / "visual.json")
        self.state = VisualBoardWebViewState(
            self.pack_store,
            self.preference_store,
        )

    def test_default_snapshot_is_builtin_and_exposes_no_filesystem_paths(self):
        snapshot = self.state.snapshot()
        self.assertEqual("classic", snapshot["effective"]["board_theme_id"])
        self.assertEqual("classic", snapshot["effective"]["piece_theme_id"])
        self.assertEqual({}, snapshot["assets"]["board"])
        self.assertEqual({}, snapshot["assets"]["pieces"])
        self.assertEqual(
            ["classic"],
            [item["pack_id"] for item in snapshot["themes"]["board"]],
        )
        self.assertEqual(
            ["classic"],
            [item["pack_id"] for item in snapshot["themes"]["pieces"]],
        )
        self.assertNotIn(str(self.pack_store.root), repr(snapshot))

    def test_trusted_install_then_update_projects_verified_raster_assets_and_persists(self):
        board, board_payloads = _board_pack()
        pieces, piece_payloads = _piece_pack()
        self.state.install(board, board_payloads)
        self.state.install(pieces, piece_payloads)
        requested = BoardVisualPreferences(
            board_theme_id=board.pack_id,
            piece_theme_id=pieces.pack_id,
            coordinate_mode=CoordinateMode.EVERY_SQUARE,
            board_scale_percent=125,
            piece_scale_percent=115,
            show_last_move=False,
            reduced_motion=True,
        )
        snapshot = self.state.update(requested.as_dict())

        self.assertEqual(board.pack_id, snapshot["effective"]["board_theme_id"])
        self.assertEqual(pieces.pack_id, snapshot["effective"]["piece_theme_id"])
        self.assertFalse(snapshot["effective"]["board_fallback_used"])
        self.assertFalse(snapshot["effective"]["piece_fallback_used"])
        self.assertTrue(
            snapshot["assets"]["board"]["light_square"].startswith(
                "data:image/png;base64,"
            )
        )
        self.assertEqual(12, len(snapshot["assets"]["pieces"]))
        self.assertEqual(requested.as_dict(), snapshot["preferences"])
        self.assertNotIn(str(self.pack_store.root), repr(snapshot))

        restarted = VisualBoardWebViewState(
            self.pack_store,
            self.preference_store,
        ).snapshot(include_assets=False)
        self.assertEqual(requested.as_dict(), restarted["preferences"])
        self.assertNotIn("assets", restarted)

    def test_update_rejects_missing_pack_and_preserves_prior_preferences(self):
        before = self.state.snapshot()["preferences"]
        requested = BoardVisualPreferences(board_theme_id="not-installed")
        with self.assertRaisesRegex(VisualBoardWebViewError, "unavailable"):
            self.state.update(requested.as_dict())
        self.assertEqual(before, self.state.snapshot()["preferences"])
        self.assertIsNone(self.preference_store.load())

    def test_installed_asset_above_webview_bound_is_not_selectable(self):
        board, payloads = _board_pack(pack_id="oversize", pad=300 * 1024)
        self.state.install(board, payloads)
        self.assertIsNotNone(
            self.pack_store.latest_usable_manifest(
                VisualPackKind.BOARD,
                board.pack_id,
            )
        )
        with self.assertRaisesRegex(VisualBoardWebViewError, "cannot be rendered safely"):
            self.state.update(
                BoardVisualPreferences(board_theme_id=board.pack_id).as_dict()
            )

        # A preference written by an older build remains evidence but cannot make
        # browser content consume an oversized asset.
        self.preference_store.save(
            BoardVisualPreferences(board_theme_id=board.pack_id)
        )
        restarted = VisualBoardWebViewState(
            self.pack_store,
            self.preference_store,
        ).snapshot()
        self.assertEqual(board.pack_id, restarted["preferences"]["board_theme_id"])
        self.assertEqual("classic", restarted["effective"]["board_theme_id"])
        self.assertTrue(restarted["effective"]["board_fallback_used"])
        rows = [
            item
            for item in restarted["themes"]["board"]
            if item["pack_id"] == board.pack_id
        ]
        self.assertEqual(1, len(rows))
        self.assertFalse(rows[0]["renderable"])

    def test_uninstall_active_pack_preserves_requested_intent_and_falls_back(self):
        board, payloads = _board_pack()
        self.state.install(board, payloads)
        self.state.update(
            BoardVisualPreferences(board_theme_id=board.pack_id).as_dict()
        )
        self.assertTrue(
            self.state.uninstall(
                board.kind,
                board.pack_id,
                board.version,
            )
        )
        snapshot = self.state.snapshot()
        self.assertEqual(board.pack_id, snapshot["preferences"]["board_theme_id"])
        self.assertEqual("classic", snapshot["effective"]["board_theme_id"])
        self.assertTrue(snapshot["effective"]["board_fallback_used"])

    def test_update_is_closed_world_and_strictly_typed(self):
        payload = BoardVisualPreferences().as_dict()
        payload["unknown"] = True
        with self.assertRaises(VisualBoardWebViewError):
            self.state.update(payload)

        payload = BoardVisualPreferences().as_dict()
        payload["piece_scale_percent"] = True
        with self.assertRaises(VisualBoardWebViewError):
            self.state.update(payload)

    def test_single_field_update_is_bounded_and_strict(self):
        changed = self.state.update_field("coordinate_mode", "every_square")
        self.assertEqual(
            "every_square",
            changed["preferences"]["coordinate_mode"],
        )
        with self.assertRaises(VisualBoardWebViewError):
            self.state.update_field("position_fen", "secret")
        with self.assertRaises(VisualBoardWebViewError):
            self.state.update_field("board_scale_percent", True)
        self.assertEqual(
            "every_square",
            self.state.snapshot()["preferences"]["coordinate_mode"],
        )

    def test_reset_restores_builtin_preferences_and_assets_can_be_omitted(self):
        board, payloads = _board_pack()
        self.state.install(board, payloads)
        self.state.update(
            BoardVisualPreferences(
                board_theme_id=board.pack_id,
                coordinate_mode=CoordinateMode.OFF,
                reduced_motion=True,
            ).as_dict()
        )
        snapshot = self.state.reset()
        self.assertEqual(BoardVisualPreferences().as_dict(), snapshot["preferences"])
        self.assertEqual("classic", snapshot["effective"]["board_theme_id"])
        lean = self.state.snapshot(include_assets=False)
        self.assertNotIn("assets", lean)


if __name__ == "__main__":
    unittest.main()
