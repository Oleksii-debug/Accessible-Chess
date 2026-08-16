from __future__ import annotations

import unittest
from pathlib import Path

from acs.visual_pack_presentation import (
    VisualPackCatalogEntry,
    VisualPackCatalogPresentation,
    VisualPackInstallState,
)
from acs.visual_preferences import VisualPackKind, VisualPackManifest


def board_manifest(pack_id: str, title: str = "Board") -> VisualPackManifest:
    return VisualPackManifest(
        pack_id=pack_id,
        version="1.0.0",
        title=title,
        kind=VisualPackKind.BOARD,
        license_id="CC-BY-4.0",
        author="Artist",
        assets={"light": "board/light.png", "dark": "board/dark.png"},
    )


def piece_manifest(pack_id: str, title: str = "Pieces") -> VisualPackManifest:
    assets = {
        f"{side}_{piece}": f"pieces/{side}_{piece}.svg"
        for side in ("white", "black")
        for piece in ("king", "queen", "rook", "bishop", "knight", "pawn")
    }
    return VisualPackManifest(
        pack_id=pack_id,
        version="2.0.0",
        title=title,
        kind=VisualPackKind.PIECES,
        license_id="MIT",
        author="Designer",
        assets=assets,
    )


class FakeCatalog:
    def __init__(self, entries: tuple[VisualPackCatalogEntry, ...]) -> None:
        self.entries = {item.manifest.pack_id: item for item in entries}
        self.calls: list[tuple[str, str]] = []
        self.fail_operation: str | None = None

    def list_entries(self) -> tuple[VisualPackCatalogEntry, ...]:
        return tuple(self.entries.values())

    def install(self, pack_id: str) -> VisualPackCatalogEntry:
        return self._change("install", pack_id, VisualPackInstallState.INSTALLED)

    def update(self, pack_id: str) -> VisualPackCatalogEntry:
        return self._change("update", pack_id, VisualPackInstallState.INSTALLED)

    def uninstall(self, pack_id: str) -> VisualPackCatalogEntry:
        return self._change("uninstall", pack_id, VisualPackInstallState.AVAILABLE)

    def _change(
        self,
        operation: str,
        pack_id: str,
        state: VisualPackInstallState,
    ) -> VisualPackCatalogEntry:
        self.calls.append((operation, pack_id))
        if self.fail_operation == operation:
            raise OSError("private provider path C:/secret/pack")
        current = self.entries[pack_id]
        updated = VisualPackCatalogEntry(
            current.manifest,
            state,
            installed_version=(current.manifest.version if state is VisualPackInstallState.INSTALLED else None),
            compatible=current.compatible,
            description=current.description,
            provenance=current.provenance,
        )
        self.entries[pack_id] = updated
        return updated


class VisualPackCatalogPresentationTests(unittest.TestCase):
    def test_unavailable_catalog_is_explicit_and_never_fakes_install(self) -> None:
        view = VisualPackCatalogPresentation()
        snapshot = view.snapshot()
        self.assertFalse(snapshot["available"])
        self.assertEqual(snapshot["entries"], [])
        result = view.install("modern")
        self.assertFalse(result["ok"])
        self.assertIn("недоступне", result["accessibleText"])

    def test_snapshot_exposes_safe_metadata_status_and_stable_order(self) -> None:
        catalog = FakeCatalog(
            (
                VisualPackCatalogEntry(
                    piece_manifest("modern-pieces", "Modern Pieces"),
                    VisualPackInstallState.UPDATE_AVAILABLE,
                    installed_version="1.5.0",
                    provenance="curated catalog",
                ),
                VisualPackCatalogEntry(
                    board_manifest("contrast-board", "High Contrast"),
                    VisualPackInstallState.AVAILABLE,
                    description="Strong visual separation",
                    provenance="community",
                ),
            )
        )
        snapshot = VisualPackCatalogPresentation(catalog).snapshot()
        self.assertTrue(snapshot["available"])
        self.assertEqual([row["id"] for row in snapshot["entries"]], ["contrast-board", "modern-pieces"])
        board = snapshot["entries"][0]
        self.assertEqual(board["license"], "CC-BY-4.0")
        self.assertEqual(board["author"], "Artist")
        self.assertEqual(board["provenance"], "community")
        self.assertTrue(board["canInstall"])
        self.assertIn("High Contrast", board["accessibleText"])
        pieces = snapshot["entries"][1]
        self.assertTrue(pieces["canUpdate"])
        self.assertTrue(pieces["canUninstall"])

    def test_lifecycle_calls_port_only_for_valid_state(self) -> None:
        catalog = FakeCatalog(
            (
                VisualPackCatalogEntry(board_manifest("new-board"), VisualPackInstallState.AVAILABLE),
                VisualPackCatalogEntry(piece_manifest("new-pieces"), VisualPackInstallState.UPDATE_AVAILABLE),
            )
        )
        view = VisualPackCatalogPresentation(catalog)
        self.assertTrue(view.install("new-board")["ok"])
        self.assertTrue(view.update("new-pieces")["ok"])
        self.assertTrue(view.uninstall("new-board")["ok"])
        self.assertEqual(
            catalog.calls,
            [("install", "new-board"), ("update", "new-pieces"), ("uninstall", "new-board")],
        )

    def test_wrong_state_is_denied_without_provider_call(self) -> None:
        catalog = FakeCatalog(
            (VisualPackCatalogEntry(board_manifest("ready"), VisualPackInstallState.INSTALLED),)
        )
        result = VisualPackCatalogPresentation(catalog).install("ready")
        self.assertFalse(result["ok"])
        self.assertEqual(catalog.calls, [])
        self.assertIn("недоступна", result["accessibleText"])

    def test_incompatible_and_damaged_entries_are_fail_closed(self) -> None:
        catalog = FakeCatalog(
            (
                VisualPackCatalogEntry(
                    board_manifest("old"),
                    VisualPackInstallState.INCOMPATIBLE,
                    compatible=False,
                ),
                VisualPackCatalogEntry(
                    piece_manifest("broken"),
                    VisualPackInstallState.DAMAGED,
                ),
            )
        )
        view = VisualPackCatalogPresentation(catalog)
        self.assertFalse(view.install("old")["ok"])
        self.assertFalse(view.update("broken")["ok"])
        self.assertEqual(catalog.calls, [])

    def test_built_in_fallback_cannot_be_uninstalled_or_presented_as_removable(self) -> None:
        catalog = FakeCatalog(
            (
                VisualPackCatalogEntry(board_manifest("classic", "Classic"), VisualPackInstallState.INSTALLED),
                VisualPackCatalogEntry(piece_manifest("classic", "Classic Pieces"), VisualPackInstallState.INSTALLED),
            )
        )
        view = VisualPackCatalogPresentation(catalog)
        rows = view.snapshot()["entries"]
        self.assertTrue(all(not row["canUninstall"] for row in rows))
        result = view.uninstall("classic")
        self.assertFalse(result["ok"])
        self.assertIn("резервний", result["accessibleText"])
        self.assertEqual(catalog.calls, [])

    def test_unknown_pack_returns_concise_user_error(self) -> None:
        view = VisualPackCatalogPresentation(FakeCatalog(()))
        result = view.update("does-not-exist")
        self.assertFalse(result["ok"])
        self.assertEqual(result["accessibleText"], "Пакет оформлення не знайдено.")

    def test_provider_error_does_not_leak_internal_exception_text(self) -> None:
        catalog = FakeCatalog(
            (VisualPackCatalogEntry(board_manifest("remote"), VisualPackInstallState.AVAILABLE),)
        )
        catalog.fail_operation = "install"
        result = VisualPackCatalogPresentation(catalog).install("remote")
        self.assertFalse(result["ok"])
        self.assertNotIn("C:/secret", result["accessibleText"])
        self.assertNotIn("OSError", result["accessibleText"])

    def test_installed_manifests_excludes_unavailable_incompatible_and_damaged(self) -> None:
        catalog = FakeCatalog(
            (
                VisualPackCatalogEntry(board_manifest("installed"), VisualPackInstallState.INSTALLED),
                VisualPackCatalogEntry(piece_manifest("updatable"), VisualPackInstallState.UPDATE_AVAILABLE),
                VisualPackCatalogEntry(board_manifest("remote"), VisualPackInstallState.AVAILABLE),
                VisualPackCatalogEntry(
                    board_manifest("legacy"),
                    VisualPackInstallState.INCOMPATIBLE,
                    compatible=False,
                ),
            )
        )
        ids = [item.pack_id for item in VisualPackCatalogPresentation(catalog).installed_manifests()]
        self.assertEqual(ids, ["installed", "updatable"])

    def test_visual_pack_page_has_single_action_live_region_and_no_global_key_hijack(self) -> None:
        html = (Path(__file__).resolve().parents[1] / "web" / "visual_packs.html").read_text(encoding="utf-8")
        self.assertEqual(html.count('role="status"'), 1)
        self.assertIn('id="board-pack-list"', html)
        self.assertIn('id="piece-pack-list"', html)
        self.assertIn("visual_pack_snapshot", html)
        self.assertIn("visual_pack_install", html)
        self.assertIn("visual_pack_update", html)
        self.assertIn("visual_pack_uninstall", html)
        self.assertNotIn("document.addEventListener('keydown'", html)
        self.assertNotIn('document.onkeydown', html)


if __name__ == "__main__":
    unittest.main()
