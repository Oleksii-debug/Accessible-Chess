from __future__ import annotations

import unittest

from acs.visual_pack_presentation import (
    VisualPackCatalogEntry,
    VisualPackCatalogPresentation,
    VisualPackInstallState,
)
from acs.visual_preferences import VisualPackKind, VisualPackManifest


def board_manifest(pack_id: str = "board.one") -> VisualPackManifest:
    return VisualPackManifest(
        pack_id,
        "1.0.0",
        "Board",
        VisualPackKind.BOARD,
        "MIT",
        assets={"texture": "board.png"},
    )


class _Catalog:
    def __init__(self, entries: tuple[VisualPackCatalogEntry, ...]) -> None:
        self.entries = entries
        self.result: object | None = None
        self.error: Exception | None = None

    def list_entries(self):
        return self.entries

    def install(self, pack_id: str):
        if self.error is not None:
            raise self.error
        if self.result is not None:
            return self.result
        return VisualPackCatalogEntry(
            self.entries[0].manifest,
            VisualPackInstallState.INSTALLED,
            installed_version=self.entries[0].manifest.version,
        )

    update = install
    uninstall = install


class VisualPackTrustBoundaryTests(unittest.TestCase):
    def test_raw_install_state_is_normalized_before_policy_checks(self) -> None:
        entry = VisualPackCatalogEntry(board_manifest(), "available")
        self.assertIs(entry.state, VisualPackInstallState.AVAILABLE)
        with self.assertRaises(ValueError):
            VisualPackCatalogEntry(
                board_manifest(),
                "incompatible",
                compatible=True,
            )

    def test_compatible_flag_requires_actual_boolean(self) -> None:
        with self.assertRaises(ValueError):
            VisualPackCatalogEntry(
                board_manifest(),
                "available",
                compatible="false",
            )

    def test_provider_snapshot_must_be_bounded_unique_tuple(self) -> None:
        entry = VisualPackCatalogEntry(board_manifest(), "available")

        class BadShape(_Catalog):
            def list_entries(self):
                return [entry]

        self.assertFalse(
            VisualPackCatalogPresentation(BadShape((entry,))).snapshot()["healthy"]
        )
        self.assertFalse(
            VisualPackCatalogPresentation(
                _Catalog(tuple(entry for _ in range(513)))
            ).snapshot()["healthy"]
        )
        self.assertFalse(
            VisualPackCatalogPresentation(
                _Catalog((entry, entry))
            ).snapshot()["healthy"]
        )

    def test_provider_runtime_failure_is_sanitized(self) -> None:
        entry = VisualPackCatalogEntry(board_manifest(), "available")
        catalog = _Catalog((entry,))
        catalog.error = RuntimeError("private C:/secret/provider")
        result = VisualPackCatalogPresentation(catalog).install("board.one")
        self.assertFalse(result["ok"])
        self.assertNotIn("secret", result["accessibleText"])
        self.assertNotIn("RuntimeError", result["accessibleText"])

    def test_provider_cannot_return_a_different_pack_as_success(self) -> None:
        entry = VisualPackCatalogEntry(board_manifest(), "available")
        catalog = _Catalog((entry,))
        catalog.result = VisualPackCatalogEntry(
            board_manifest("other"),
            "installed",
            installed_version="1.0.0",
        )
        result = VisualPackCatalogPresentation(catalog).install("board.one")
        self.assertFalse(result["ok"])
        self.assertNotIn("Other", result["accessibleText"])

    def test_non_text_request_id_does_not_string_coerce(self) -> None:
        entry = VisualPackCatalogEntry(board_manifest(), "available")
        catalog = _Catalog((entry,))
        result = VisualPackCatalogPresentation(catalog).install(123)
        self.assertFalse(result["ok"])
        self.assertEqual(result["accessibleText"], "Пакет оформлення не знайдено.")

    def test_catalog_metadata_rejects_control_and_oversize_text(self) -> None:
        with self.assertRaises(ValueError):
            VisualPackCatalogEntry(
                board_manifest(),
                "available",
                provenance="trusted\u202eexe",
            )
        with self.assertRaises(ValueError):
            VisualPackCatalogEntry(
                board_manifest(),
                "available",
                description="x" * 1001,
            )


if __name__ == "__main__":
    unittest.main()
