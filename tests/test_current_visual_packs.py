import hashlib
from pathlib import Path
import tempfile
import unittest

from acs.visual_preferences import (
    BoardVisualPreferences,
    CoordinateMode,
    VisualAssetSpec,
    VisualPackKind,
    VisualPackManifest,
)
from acs.visual_pack_store import (
    VisualPackStore,
    VisualPackStoreError,
    VisualPreferencesStore,
)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _board_manifest(
    data: bytes = b"png-board",
    *,
    version: str = "1.0.0",
    api: int = 1,
    pack_id: str = "high-contrast",
) -> tuple[VisualPackManifest, dict[str, bytes]]:
    payloads = {"board/light.png": data}
    return (
        VisualPackManifest(
            pack_id=pack_id,
            version=version,
            title="High contrast",
            kind=VisualPackKind.BOARD,
            license_id="CC0-1.0",
            author="Accessible Chess",
            provenance="Project-authored test visual asset.",
            product_api_version=api,
            assets={
                "light": VisualAssetSpec(
                    "board/light.png",
                    _digest(data),
                )
            },
        ),
        payloads,
    )


def _piece_manifest() -> tuple[VisualPackManifest, dict[str, bytes]]:
    payloads: dict[str, bytes] = {}
    assets: dict[str, VisualAssetSpec] = {}
    for side in ("white", "black"):
        for piece in ("king", "queen", "rook", "bishop", "knight", "pawn"):
            asset_id = f"{side}_{piece}"
            path = f"pieces/{asset_id}.svg"
            data = f"<svg>{asset_id}</svg>".encode()
            payloads[path] = data
            assets[asset_id] = VisualAssetSpec(path, _digest(data))
    return (
        VisualPackManifest(
            pack_id="large-symbols",
            version="2.1.0",
            title="Large symbols",
            kind=VisualPackKind.PIECES,
            license_id="CC-BY-4.0",
            author="Accessible Chess",
            provenance="Project-authored deterministic test assets.",
            assets=assets,
        ),
        payloads,
    )


class CurrentVisualPacksTests(unittest.TestCase):
    def test_preferences_round_trip_is_strict_and_does_not_coerce_scalars(self):
        original = BoardVisualPreferences(
            board_theme_id="high-contrast",
            piece_theme_id="large-symbols",
            coordinate_mode=CoordinateMode.EVERY_SQUARE,
            board_scale_percent=125,
            piece_scale_percent=110,
            show_last_move=False,
            reduced_motion=True,
        )
        self.assertEqual(
            BoardVisualPreferences.from_dict(original.as_dict()),
            original,
        )
        bad = original.as_dict()
        bad["board_scale_percent"] = True
        with self.assertRaises(ValueError):
            BoardVisualPreferences.from_dict(bad)
        bad = original.as_dict()
        bad["show_last_move"] = 1
        with self.assertRaises(TypeError):
            BoardVisualPreferences.from_dict(bad)

    def test_manifest_requires_typed_kind_semver_provenance_and_safe_assets(self):
        manifest, _ = _board_manifest()
        self.assertEqual(
            VisualPackManifest.from_dict(manifest.as_dict()),
            manifest,
        )
        payload = manifest.as_dict()
        payload["kind"] = "sound"
        with self.assertRaises(ValueError):
            VisualPackManifest.from_dict(payload)
        with self.assertRaises(ValueError):
            _board_manifest(version="01.0.0")
        with self.assertRaises(ValueError):
            VisualAssetSpec("../escape.png", "0" * 64)
        with self.assertRaises(ValueError):
            VisualAssetSpec(r"C:\temp\piece.png", "0" * 64)
        with self.assertRaises(ValueError):
            VisualAssetSpec("payload.exe", "0" * 64)

    def test_piece_pack_requires_all_semantic_piece_assets(self):
        manifest, _ = _piece_manifest()
        self.assertEqual(len(manifest.assets), 12)
        incomplete = dict(manifest.assets)
        incomplete.pop("black_pawn")
        with self.assertRaisesRegex(ValueError, "missing required assets"):
            VisualPackManifest(
                pack_id=manifest.pack_id,
                version=manifest.version,
                title=manifest.title,
                kind=manifest.kind,
                license_id=manifest.license_id,
                author=manifest.author,
                provenance=manifest.provenance,
                assets=incomplete,
            )

    def test_manifest_rejects_windows_case_colliding_asset_paths(self):
        first = b"one"
        second = b"two"
        with self.assertRaisesRegex(ValueError, "case-colliding"):
            VisualPackManifest(
                pack_id="collision",
                version="1.0.0",
                title="Collision",
                kind=VisualPackKind.BOARD,
                license_id="CC0-1.0",
                author="Accessible Chess",
                provenance="Test.",
                assets={
                    "one": VisualAssetSpec("Board/a.png", _digest(first)),
                    "two": VisualAssetSpec("board/A.PNG", _digest(second)),
                },
            )

    def test_install_verify_catalog_version_update_and_asset_resolution(self):
        with tempfile.TemporaryDirectory() as raw:
            store = VisualPackStore(Path(raw) / "packs")
            first, first_payloads = _board_manifest(version="1.0.0")
            installed = store.install(first, first_payloads)
            self.assertTrue(installed.is_dir())
            self.assertTrue(store.verify(first))
            self.assertEqual(store.versions(first.kind, first.pack_id), ("1.0.0",))
            self.assertEqual(
                store.resolve_asset(first.kind, first.pack_id, "light"),
                installed / "board" / "light.png",
            )

            second_data = b"png-board-v2"
            second, second_payloads = _board_manifest(
                second_data,
                version="1.1.0",
            )
            store.install(second, second_payloads)
            self.assertEqual(
                store.versions(second.kind, second.pack_id),
                ("1.0.0", "1.1.0"),
            )
            self.assertEqual(
                store.latest_usable_manifest(second.kind, second.pack_id),
                second,
            )
            rows = [
                row
                for row in store.catalog()
                if row.pack_id == second.pack_id
            ]
            self.assertEqual({row.version for row in rows}, {"1.0.0", "1.1.0"})
            self.assertEqual(
                [row.version for row in rows if row.latest_installed],
                ["1.1.0"],
            )

    def test_checksum_path_and_same_version_collision_fail_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            store = VisualPackStore(Path(raw) / "packs")
            manifest, payloads = _board_manifest()
            with self.assertRaisesRegex(VisualPackStoreError, "checksum"):
                store.install(
                    manifest,
                    {"board/light.png": b"wrong"},
                )
            with self.assertRaisesRegex(VisualPackStoreError, "paths"):
                store.install(
                    manifest,
                    {"board/other.png": next(iter(payloads.values()))},
                )
            store.install(manifest, payloads)
            changed, changed_payloads = _board_manifest(
                b"different",
                version=manifest.version,
            )
            with self.assertRaisesRegex(VisualPackStoreError, "different content"):
                store.install(changed, changed_payloads)

    def test_incompatible_product_api_is_rejected_before_publication(self):
        with tempfile.TemporaryDirectory() as raw:
            store = VisualPackStore(Path(raw) / "packs")
            manifest, payloads = _board_manifest(api=2)
            with self.assertRaisesRegex(VisualPackStoreError, "incompatible"):
                store.install(manifest, payloads)
            self.assertFalse(store.root.exists())

    def test_undeclared_post_install_content_invalidates_pack_and_falls_back(self):
        with tempfile.TemporaryDirectory() as raw:
            store = VisualPackStore(Path(raw) / "packs")
            manifest, payloads = _board_manifest()
            installed = store.install(manifest, payloads)
            (installed / "payload.exe").write_bytes(b"not-declared")
            with self.assertRaisesRegex(VisualPackStoreError, "undeclared"):
                store.verify(manifest)
            resolved = store.effective_preferences(
                BoardVisualPreferences(board_theme_id=manifest.pack_id)
            )
            self.assertEqual(resolved.effective_board_theme_id, "classic")
            self.assertTrue(resolved.board_fallback_used)
            damaged = [
                row
                for row in store.catalog()
                if row.pack_id == manifest.pack_id and row.version == manifest.version
            ]
            self.assertEqual(len(damaged), 1)
            self.assertFalse(damaged[0].usable)
            self.assertTrue(damaged[0].compatible)
            self.assertEqual(damaged[0].reason, "damaged")
            self.assertFalse(damaged[0].latest_installed)

    def test_tampered_asset_checksum_causes_clean_fallback(self):
        with tempfile.TemporaryDirectory() as raw:
            store = VisualPackStore(Path(raw) / "packs")
            manifest, payloads = _board_manifest()
            installed = store.install(manifest, payloads)
            (installed / "board" / "light.png").write_bytes(b"tampered")
            self.assertIsNone(
                store.resolve_asset(manifest.kind, manifest.pack_id, "light")
            )
            resolved = store.effective_preferences(
                BoardVisualPreferences(board_theme_id=manifest.pack_id)
            )
            self.assertEqual(resolved.effective_board_theme_id, "classic")
            self.assertTrue(resolved.board_fallback_used)

    def test_uninstall_causes_builtin_fallback_and_builtin_is_immutable(self):
        with tempfile.TemporaryDirectory() as raw:
            store = VisualPackStore(Path(raw) / "packs")
            manifest, payloads = _board_manifest()
            store.install(manifest, payloads)
            self.assertTrue(store.uninstall(manifest.kind, manifest.pack_id, manifest.version))
            self.assertFalse(store.uninstall(manifest.kind, manifest.pack_id, manifest.version))
            effective = store.effective_preferences(
                BoardVisualPreferences(board_theme_id=manifest.pack_id)
            )
            self.assertTrue(effective.board_fallback_used)
            self.assertEqual(effective.effective_board_theme_id, "classic")
            with self.assertRaisesRegex(VisualPackStoreError, "built-in"):
                store.uninstall(VisualPackKind.BOARD, "classic", "1.0.0")

    def test_version_path_traversal_is_rejected(self):
        manifest, _ = _board_manifest()
        payload = manifest.as_dict()
        payload["version"] = "../1.0.0"
        with self.assertRaises(ValueError):
            VisualPackManifest.from_dict(payload)

    def test_preferences_persist_atomically_and_corrupt_file_falls_back_without_deletion(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "prefs" / "visual.json"
            store = VisualPreferencesStore(path)
            preferences = BoardVisualPreferences(
                board_theme_id="high-contrast",
                piece_theme_id="large-symbols",
                coordinate_mode=CoordinateMode.OFF,
                board_scale_percent=150,
                piece_scale_percent=120,
                show_last_move=False,
                reduced_motion=True,
            )
            store.save(preferences)
            self.assertEqual(store.load(), preferences)

            corrupt = (
                '{"schema_version":1,"schema_version":1,'
                '"preferences":{}}\n'
            ).encode()
            path.write_bytes(corrupt)
            with self.assertRaises(VisualPackStoreError):
                store.load()
            self.assertEqual(store.load_or_default(), BoardVisualPreferences())
            self.assertEqual(path.read_bytes(), corrupt)


if __name__ == "__main__":
    unittest.main()
