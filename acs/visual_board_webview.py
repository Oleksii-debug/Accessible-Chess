from __future__ import annotations

"""WebView-safe projection and persistence for visual board preferences.

This layer is deliberately presentation-only. It never owns or mutates chess
state and never exposes filesystem paths to browser content. Installed packs are
projected only as bounded, digest-verified raster data URLs supplied by the
canonical local VisualPackStore.
"""

from collections.abc import Mapping
from typing import Any

from .visual_pack_store import (
    VisualPackCatalogEntry,
    VisualPackStore,
    VisualPackStoreError,
    VisualPreferencesStore,
)
from .visual_preferences import (
    BoardVisualPreferences,
    VisualPackKind,
    VisualPackManifest,
)

_CLASSIC_ID = "classic"
_BOARD_ASSETS = ("light_square", "dark_square")
_PIECE_ASSETS = tuple(
    f"{side}_{piece}"
    for side in ("white", "black")
    for piece in ("king", "queen", "rook", "bishop", "knight", "pawn")
)


class VisualBoardWebViewError(ValueError):
    """Stable failure at the visual-preference/browser boundary."""


class VisualBoardWebViewState:
    """Own presentation preferences while delegating pack truth to the store."""

    def __init__(
        self,
        packs: VisualPackStore,
        preferences: VisualPreferencesStore,
    ) -> None:
        if not isinstance(packs, VisualPackStore):
            raise TypeError("packs must be VisualPackStore")
        if not isinstance(preferences, VisualPreferencesStore):
            raise TypeError("preferences must be VisualPreferencesStore")
        self._packs = packs
        self._preferences = preferences
        self._cached_snapshot: dict[str, object] | None = None

    @property
    def pack_store(self) -> VisualPackStore:
        return self._packs

    @property
    def preference_store(self) -> VisualPreferencesStore:
        return self._preferences

    @staticmethod
    def _required_assets(kind: VisualPackKind) -> tuple[str, ...]:
        if kind is VisualPackKind.BOARD:
            return _BOARD_ASSETS
        if kind is VisualPackKind.PIECES:
            return _PIECE_ASSETS
        raise VisualBoardWebViewError("unsupported visual pack kind")

    def _asset_urls(
        self,
        kind: VisualPackKind,
        pack_id: str,
    ) -> dict[str, str] | None:
        if pack_id == _CLASSIC_ID:
            return {}
        manifest = self._packs.latest_usable_manifest(kind, pack_id)
        if manifest is None:
            return None
        urls: dict[str, str] = {}
        for asset_id in self._required_assets(kind):
            url = self._packs.resolve_asset_data_url(kind, pack_id, asset_id)
            if url is None:
                return None
            urls[asset_id] = url
        return urls

    def _theme_rows(
        self,
        catalog: tuple[VisualPackCatalogEntry, ...],
        kind: VisualPackKind,
    ) -> tuple[dict[str, object], ...]:
        # Theme selection is by stable pack id, not version. Only the latest
        # installed usable/renderable version is selectable; management metadata
        # for damaged historical versions remains in VisualPackStore.catalog().
        rows: list[dict[str, object]] = []
        seen: set[str] = set()
        candidates = [
            row
            for row in catalog
            if row.kind is kind and row.usable and row.latest_installed
        ]
        for row in sorted(candidates, key=lambda item: (item.pack_id, item.version)):
            if row.pack_id in seen:
                continue
            seen.add(row.pack_id)
            renderable = (
                row.pack_id == _CLASSIC_ID
                or self._asset_urls(kind, row.pack_id) is not None
            )
            rows.append(
                {
                    "pack_id": row.pack_id,
                    "version": row.version,
                    "title": row.title,
                    "license_id": row.license_id,
                    "author": row.author,
                    "provenance": row.provenance,
                    "renderable": renderable,
                }
            )
        return tuple(rows)

    def _build_snapshot(self) -> dict[str, object]:
        requested = self._preferences.load_or_default()
        board_urls = self._asset_urls(
            VisualPackKind.BOARD,
            requested.board_theme_id,
        )
        piece_urls = self._asset_urls(
            VisualPackKind.PIECES,
            requested.piece_theme_id,
        )
        effective_board = (
            requested.board_theme_id
            if board_urls is not None
            else _CLASSIC_ID
        )
        effective_pieces = (
            requested.piece_theme_id
            if piece_urls is not None
            else _CLASSIC_ID
        )
        catalog = self._packs.catalog()
        return {
            "preferences": requested.as_dict(),
            "effective": {
                "board_theme_id": effective_board,
                "piece_theme_id": effective_pieces,
                "board_fallback_used": effective_board != requested.board_theme_id,
                "piece_fallback_used": effective_pieces != requested.piece_theme_id,
            },
            "themes": {
                "board": self._theme_rows(catalog, VisualPackKind.BOARD),
                "pieces": self._theme_rows(catalog, VisualPackKind.PIECES),
            },
            "assets": {
                "board": board_urls or {},
                "pieces": piece_urls or {},
            },
        }

    @staticmethod
    def _copy_snapshot(
        snapshot: Mapping[str, object],
        *,
        include_assets: bool,
    ) -> dict[str, object]:
        result = dict(snapshot)
        result["preferences"] = dict(snapshot["preferences"])  # type: ignore[arg-type]
        result["effective"] = dict(snapshot["effective"])  # type: ignore[arg-type]
        themes = snapshot["themes"]
        assert isinstance(themes, Mapping)
        result["themes"] = {
            "board": tuple(dict(item) for item in themes["board"]),  # type: ignore[index]
            "pieces": tuple(dict(item) for item in themes["pieces"]),  # type: ignore[index]
        }
        if include_assets:
            assets = snapshot["assets"]
            assert isinstance(assets, Mapping)
            result["assets"] = {
                "board": dict(assets["board"]),  # type: ignore[index]
                "pieces": dict(assets["pieces"]),  # type: ignore[index]
            }
        else:
            result.pop("assets", None)
        return result

    def snapshot(self, *, include_assets: bool = True) -> dict[str, object]:
        if type(include_assets) is not bool:
            raise TypeError("include_assets must be boolean")
        if self._cached_snapshot is None:
            try:
                self._cached_snapshot = self._build_snapshot()
            except (OSError, TypeError, ValueError, VisualPackStoreError) as exc:
                # Invalid pack metadata must not make Teacher/Classroom unusable.
                # PreferencesStore already preserves corrupt preference evidence;
                # a pack-store topology failure falls back to built-in visuals.
                requested = self._preferences.load_or_default()
                self._cached_snapshot = {
                    "preferences": requested.as_dict(),
                    "effective": {
                        "board_theme_id": _CLASSIC_ID,
                        "piece_theme_id": _CLASSIC_ID,
                        "board_fallback_used": requested.board_theme_id != _CLASSIC_ID,
                        "piece_fallback_used": requested.piece_theme_id != _CLASSIC_ID,
                    },
                    "themes": {
                        "board": (
                            {
                                "pack_id": _CLASSIC_ID,
                                "version": "0.0.0",
                                "title": "Built-in classic",
                                "license_id": "Project",
                                "author": "Accessible Chess",
                                "provenance": "Bundled with Accessible Chess",
                                "renderable": True,
                            },
                        ),
                        "pieces": (
                            {
                                "pack_id": _CLASSIC_ID,
                                "version": "0.0.0",
                                "title": "Built-in classic",
                                "license_id": "Project",
                                "author": "Accessible Chess",
                                "provenance": "Bundled with Accessible Chess",
                                "renderable": True,
                            },
                        ),
                    },
                    "assets": {"board": {}, "pieces": {}},
                }
        return self._copy_snapshot(
            self._cached_snapshot,
            include_assets=include_assets,
        )

    def update(self, payload: Mapping[str, object]) -> dict[str, object]:
        if not isinstance(payload, Mapping) or any(
            type(key) is not str for key in payload
        ):
            raise VisualBoardWebViewError("visual preferences must be an object")
        try:
            candidate = BoardVisualPreferences.from_dict(payload)
        except (TypeError, ValueError) as exc:
            raise VisualBoardWebViewError("visual preferences are invalid") from exc

        for kind, pack_id in (
            (VisualPackKind.BOARD, candidate.board_theme_id),
            (VisualPackKind.PIECES, candidate.piece_theme_id),
        ):
            if pack_id != _CLASSIC_ID and self._asset_urls(kind, pack_id) is None:
                raise VisualBoardWebViewError(
                    "selected visual theme is unavailable or cannot be rendered safely"
                )

        try:
            self._preferences.save(candidate)
        except (OSError, TypeError, ValueError, VisualPackStoreError) as exc:
            raise VisualBoardWebViewError(
                "visual preferences could not be saved"
            ) from exc
        self._cached_snapshot = None
        return self.snapshot(include_assets=True)

    def update_field(
        self,
        field: object,
        value: object,
    ) -> dict[str, object]:
        """Apply exactly one browser-selectable preference field."""

        if type(field) is not str or field not in {
            "board_theme_id",
            "piece_theme_id",
            "coordinate_mode",
            "board_scale_percent",
            "piece_scale_percent",
            "show_last_move",
            "reduced_motion",
        }:
            raise VisualBoardWebViewError("visual preference field is invalid")
        current = self._preferences.load_or_default().as_dict()
        current[field] = value
        return self.update(current)

    def reset(self) -> dict[str, object]:
        try:
            self._preferences.save(BoardVisualPreferences())
        except (OSError, TypeError, ValueError, VisualPackStoreError) as exc:
            raise VisualBoardWebViewError(
                "visual preferences could not be reset"
            ) from exc
        self._cached_snapshot = None
        return self.snapshot(include_assets=True)

    def install(
        self,
        manifest: VisualPackManifest,
        payloads: Mapping[str, bytes],
    ) -> None:
        """Trusted-host install seam; browser content never supplies pack bytes."""

        self._packs.install(manifest, payloads)
        self._cached_snapshot = None

    def uninstall(
        self,
        kind: VisualPackKind | str,
        pack_id: str,
        version: str,
    ) -> bool:
        """Trusted-host removal seam with automatic active-theme fallback."""

        removed = self._packs.uninstall(kind, pack_id, version)
        self._cached_snapshot = None
        return removed
