from __future__ import annotations

"""Strict presentation-only visual preferences and visual-pack metadata.

This module owns no chess state, rendering engine, filesystem installation, or
network access. It defines stable values that a Windows/WebView presentation
adapter may consume without changing semantic square/piece identities.
"""

from dataclasses import dataclass
from enum import Enum
import re
from pathlib import PurePosixPath
from typing import Mapping

VISUAL_PREFERENCES_SCHEMA_VERSION = 1
VISUAL_PACK_MANIFEST_SCHEMA_VERSION = 1
VISUAL_PACK_API_VERSION = 1

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_VERSION_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z.-]{1,32}))?$"
)
_LICENSE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+-]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_ASSET_SUFFIXES = frozenset({".png", ".webp", ".jpg", ".jpeg"})
_REQUIRED_BOARD_ASSETS = frozenset({"light_square", "dark_square"})
_REQUIRED_PIECE_ASSETS = frozenset(
    f"{side}_{piece}"
    for side in ("white", "black")
    for piece in ("king", "queen", "rook", "bishop", "knight", "pawn")
)
_PREFERENCE_FIELDS = frozenset({
    "board_theme_id",
    "piece_theme_id",
    "coordinate_mode",
    "board_scale_percent",
    "piece_scale_percent",
    "show_last_move",
    "reduced_motion",
})
_MANIFEST_FIELDS = frozenset({
    "schema_version",
    "product_api_version",
    "pack_id",
    "version",
    "title",
    "kind",
    "license_id",
    "author",
    "provenance",
    "assets",
})
_ASSET_FIELDS = frozenset({"path", "sha256"})


class CoordinateMode(str, Enum):
    OFF = "off"
    EDGES = "edges"
    EVERY_SQUARE = "every_square"


class VisualPackKind(str, Enum):
    BOARD = "board"
    PIECES = "pieces"


def _exact_text(
    value: object,
    label: str,
    *,
    maximum: int = 256,
    allow_empty: bool = False,
) -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be text")
    if value != value.strip() or "\x00" in value or len(value) > maximum:
        raise ValueError(f"{label} is invalid")
    if not value and not allow_empty:
        raise ValueError(f"{label} must not be empty")
    if any(ord(ch) < 32 for ch in value):
        raise ValueError(f"{label} contains control characters")
    if any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
        raise ValueError(f"{label} contains invalid Unicode scalar value")
    return value


def stable_id(value: object, label: str = "id") -> str:
    text = _exact_text(value, label, maximum=64)
    if _ID_RE.fullmatch(text) is None:
        raise ValueError(f"{label} must be a stable lowercase id")
    return text


def stable_version(value: object) -> str:
    text = _exact_text(value, "visual pack version", maximum=64)
    if _VERSION_RE.fullmatch(text) is None:
        raise ValueError("visual pack version must be canonical semantic version text")
    return text


def _license_id(value: object) -> str:
    text = _exact_text(value, "visual pack license_id", maximum=64)
    if _LICENSE_RE.fullmatch(text) is None:
        raise ValueError("visual pack license_id is invalid")
    return text


def safe_asset_path(value: object) -> str:
    text = _exact_text(value, "visual asset path", maximum=240)
    if "\\" in text or ":" in text:
        raise ValueError("visual asset path must be portable relative POSIX text")
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("visual asset path must stay below pack root")
    if path.suffix.lower() not in _ALLOWED_ASSET_SUFFIXES:
        raise ValueError("unsupported visual asset type")
    if path.as_posix() != text:
        raise ValueError("visual asset path must be canonical")
    return text


@dataclass(frozen=True, slots=True)
class VisualAssetSpec:
    path: str
    sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", safe_asset_path(self.path))
        if type(self.sha256) is not str or _SHA256_RE.fullmatch(self.sha256) is None:
            raise ValueError("visual asset sha256 must be lowercase SHA-256 hex")

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "sha256": self.sha256}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "VisualAssetSpec":
        if not isinstance(payload, Mapping) or any(
            type(key) is not str for key in payload
        ):
            raise TypeError("visual asset descriptor must be an object")
        if set(payload) != _ASSET_FIELDS:
            raise ValueError("visual asset descriptor fields are invalid")
        return cls(
            path=payload["path"],  # type: ignore[arg-type]
            sha256=payload["sha256"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class VisualPackManifest:
    pack_id: str
    version: str
    title: str
    kind: VisualPackKind
    license_id: str
    author: str
    provenance: str
    assets: Mapping[str, VisualAssetSpec]
    product_api_version: int = VISUAL_PACK_API_VERSION
    schema_version: int = VISUAL_PACK_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != VISUAL_PACK_MANIFEST_SCHEMA_VERSION
        ):
            raise ValueError("unsupported visual pack manifest schema_version")
        if (
            type(self.product_api_version) is not int
            or not 1 <= self.product_api_version <= 1_000_000
        ):
            raise ValueError(
                "visual pack product_api_version must be a positive bounded integer"
            )
        object.__setattr__(self, "pack_id", stable_id(self.pack_id, "pack_id"))
        object.__setattr__(self, "version", stable_version(self.version))
        object.__setattr__(self, "title", _exact_text(self.title, "visual pack title"))
        if not isinstance(self.kind, VisualPackKind):
            raise TypeError("visual pack kind must be VisualPackKind")
        object.__setattr__(self, "license_id", _license_id(self.license_id))
        object.__setattr__(
            self,
            "author",
            _exact_text(self.author, "visual pack author", allow_empty=True),
        )
        object.__setattr__(
            self,
            "provenance",
            _exact_text(
                self.provenance,
                "visual pack provenance",
                maximum=1024,
            ),
        )

        if not isinstance(self.assets, Mapping) or any(
            type(key) is not str for key in self.assets
        ):
            raise TypeError("visual pack assets must be an object")
        normalized: dict[str, VisualAssetSpec] = {}
        paths: set[str] = set()
        for raw_id, raw_spec in self.assets.items():
            asset_id = stable_id(raw_id, "visual asset id")
            if not isinstance(raw_spec, VisualAssetSpec):
                raise TypeError("visual pack asset must be VisualAssetSpec")
            path_key = raw_spec.path.casefold()
            if path_key in paths:
                raise ValueError(
                    "visual pack contains duplicate or case-colliding asset path"
                )
            paths.add(path_key)
            normalized[asset_id] = raw_spec
        if not normalized:
            raise ValueError("visual pack must contain at least one asset")
        if len(normalized) > 128:
            raise ValueError("visual pack contains too many assets")
        if self.kind is VisualPackKind.BOARD:
            missing = sorted(_REQUIRED_BOARD_ASSETS - normalized.keys())
            if missing:
                raise ValueError(
                    "board pack is missing required assets: " + ", ".join(missing)
                )
        if self.kind is VisualPackKind.PIECES:
            missing = sorted(_REQUIRED_PIECE_ASSETS - normalized.keys())
            if missing:
                raise ValueError(
                    "piece pack is missing required assets: " + ", ".join(missing)
                )
        object.__setattr__(self, "assets", normalized)

    @property
    def compatible(self) -> bool:
        return self.product_api_version == VISUAL_PACK_API_VERSION

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "product_api_version": self.product_api_version,
            "pack_id": self.pack_id,
            "version": self.version,
            "title": self.title,
            "kind": self.kind.value,
            "license_id": self.license_id,
            "author": self.author,
            "provenance": self.provenance,
            "assets": {
                key: self.assets[key].as_dict()
                for key in sorted(self.assets)
            },
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "VisualPackManifest":
        if not isinstance(payload, Mapping) or any(
            type(key) is not str for key in payload
        ):
            raise TypeError("visual pack manifest must be an object")
        if set(payload) != _MANIFEST_FIELDS:
            raise ValueError("visual pack manifest fields are invalid")
        raw_assets = payload["assets"]
        if not isinstance(raw_assets, Mapping) or any(
            type(key) is not str for key in raw_assets
        ):
            raise TypeError("visual pack assets must be an object")
        try:
            kind = VisualPackKind(payload["kind"])
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported visual pack kind") from exc
        assets = {
            key: VisualAssetSpec.from_dict(value)  # type: ignore[arg-type]
            for key, value in raw_assets.items()
        }
        return cls(
            schema_version=payload["schema_version"],  # type: ignore[arg-type]
            product_api_version=payload["product_api_version"],  # type: ignore[arg-type]
            pack_id=payload["pack_id"],  # type: ignore[arg-type]
            version=payload["version"],  # type: ignore[arg-type]
            title=payload["title"],  # type: ignore[arg-type]
            kind=kind,
            license_id=payload["license_id"],  # type: ignore[arg-type]
            author=payload["author"],  # type: ignore[arg-type]
            provenance=payload["provenance"],  # type: ignore[arg-type]
            assets=assets,
        )


@dataclass(frozen=True, slots=True)
class BoardVisualPreferences:
    board_theme_id: str = "classic"
    piece_theme_id: str = "classic"
    coordinate_mode: CoordinateMode = CoordinateMode.EDGES
    board_scale_percent: int = 100
    piece_scale_percent: int = 92
    show_last_move: bool = True
    reduced_motion: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "board_theme_id",
            stable_id(self.board_theme_id, "board_theme_id"),
        )
        object.__setattr__(
            self,
            "piece_theme_id",
            stable_id(self.piece_theme_id, "piece_theme_id"),
        )
        if not isinstance(self.coordinate_mode, CoordinateMode):
            raise TypeError("coordinate_mode must be CoordinateMode")
        if (
            type(self.board_scale_percent) is not int
            or not 50 <= self.board_scale_percent <= 200
        ):
            raise ValueError(
                "board_scale_percent must be an exact integer in 50..200"
            )
        if (
            type(self.piece_scale_percent) is not int
            or not 50 <= self.piece_scale_percent <= 150
        ):
            raise ValueError(
                "piece_scale_percent must be an exact integer in 50..150"
            )
        if (
            type(self.show_last_move) is not bool
            or type(self.reduced_motion) is not bool
        ):
            raise TypeError("visual preference flags must be booleans")

    def as_dict(self) -> dict[str, object]:
        return {
            "board_theme_id": self.board_theme_id,
            "piece_theme_id": self.piece_theme_id,
            "coordinate_mode": self.coordinate_mode.value,
            "board_scale_percent": self.board_scale_percent,
            "piece_scale_percent": self.piece_scale_percent,
            "show_last_move": self.show_last_move,
            "reduced_motion": self.reduced_motion,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "BoardVisualPreferences":
        if not isinstance(payload, Mapping) or any(
            type(key) is not str for key in payload
        ):
            raise TypeError("visual preferences must be an object")
        if set(payload) != _PREFERENCE_FIELDS:
            raise ValueError("visual preference fields are invalid")
        try:
            mode = CoordinateMode(payload["coordinate_mode"])
        except (TypeError, ValueError) as exc:
            raise ValueError("unknown coordinate_mode") from exc
        return cls(
            board_theme_id=payload["board_theme_id"],  # type: ignore[arg-type]
            piece_theme_id=payload["piece_theme_id"],  # type: ignore[arg-type]
            coordinate_mode=mode,
            board_scale_percent=payload["board_scale_percent"],  # type: ignore[arg-type]
            piece_scale_percent=payload["piece_scale_percent"],  # type: ignore[arg-type]
            show_last_move=payload["show_last_move"],  # type: ignore[arg-type]
            reduced_motion=payload["reduced_motion"],  # type: ignore[arg-type]
        )
