from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from types import MappingProxyType


VISUAL_PREFERENCES_SCHEMA_VERSION = 1
_MAX_ID_LENGTH = 64
_MAX_VERSION_LENGTH = 64
_MAX_TITLE_LENGTH = 200
_MAX_LICENSE_LENGTH = 128
_MAX_AUTHOR_LENGTH = 200
_MAX_ASSETS = 128
_MAX_ASSET_PATH_LENGTH = 512
_MAX_ASSET_COMPONENT_LENGTH = 128
_MAX_ASSET_DEPTH = 8


class CoordinateMode(str, Enum):
    OFF = "off"
    EDGES = "edges"
    EVERY_SQUARE = "every_square"


class VisualPackKind(str, Enum):
    BOARD = "board"
    PIECES = "pieces"


_ALLOWED_ASSET_SUFFIXES = {".svg", ".png", ".webp", ".jpg", ".jpeg"}
_REQUIRED_PIECE_ASSETS = frozenset(
    f"{side}_{piece}"
    for side in ("white", "black")
    for piece in ("king", "queen", "rook", "bishop", "knight", "pawn")
)
_BIDI_FORMAT_CONTROLS = frozenset(
    "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
)


def _text_field(
    value: object,
    field_name: str,
    *,
    max_length: int,
    allow_empty: bool = False,
) -> str:
    if type(value) is not str:
        raise ValueError(f"{field_name} must be text")
    text = value.strip()
    if not text and not allow_empty:
        raise ValueError(f"{field_name} must not be empty")
    if len(text) > max_length:
        raise ValueError(f"{field_name} is too long")
    if any(ord(ch) < 32 or ch in _BIDI_FORMAT_CONTROLS for ch in text):
        raise ValueError(f"{field_name} contains unsafe control text")
    return text


def _stable_id(value: object, field_name: str) -> str:
    text = _text_field(value, field_name, max_length=_MAX_ID_LENGTH).lower()
    if any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for ch in text):
        raise ValueError(f"{field_name} must be a stable lowercase id")
    return text


def _coerce_pack_kind(value: object) -> VisualPackKind:
    if isinstance(value, VisualPackKind):
        return value
    if type(value) is not str:
        raise ValueError("visual pack kind must be board or pieces")
    try:
        return VisualPackKind(value.strip().lower())
    except ValueError as exc:
        raise ValueError("visual pack kind must be board or pieces") from exc


def _coerce_coordinate_mode(value: object) -> CoordinateMode:
    if isinstance(value, CoordinateMode):
        return value
    if type(value) is not str:
        raise ValueError("coordinate_mode must be text")
    try:
        return CoordinateMode(value.strip().lower())
    except ValueError as exc:
        raise ValueError("unknown coordinate_mode") from exc


def _safe_asset_path(value: object) -> str:
    if type(value) is not str:
        raise ValueError("visual asset path must be text")
    text = value.strip()
    if not text or "\\" in text or len(text) > _MAX_ASSET_PATH_LENGTH:
        raise ValueError("visual asset path must be a canonical relative path")
    path = PurePosixPath(text)
    if path.is_absolute() or path.as_posix() != text:
        raise ValueError("visual asset path must be a canonical relative path")
    if len(path.parts) > _MAX_ASSET_DEPTH:
        raise ValueError("visual asset path is too deeply nested")
    for part in path.parts:
        if (
            part in {"", ".", ".."}
            or len(part) > _MAX_ASSET_COMPONENT_LENGTH
            or part[-1] in {" ", "."}
            or any(ord(ch) < 32 for ch in part)
        ):
            raise ValueError("visual asset path contains an unsafe component")
    if path.suffix.lower() not in _ALLOWED_ASSET_SUFFIXES:
        raise ValueError("unsupported visual asset type")
    return path.as_posix()


@dataclass(frozen=True)
class VisualPackManifest:
    """Validated presentation-only board/piece asset-pack metadata.

    Filesystem I/O deliberately stays outside this contract. The installer can
    resolve the validated relative asset paths inside a sandboxed pack root.
    The asset mapping is snapshotted after validation so provider-side mutation
    cannot change an already-approved manifest.
    """

    pack_id: str
    version: str
    title: str
    kind: VisualPackKind
    license_id: str
    author: str = ""
    assets: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        pack_id = _stable_id(self.pack_id, "pack_id")
        version = _text_field(
            self.version,
            "visual pack version",
            max_length=_MAX_VERSION_LENGTH,
        )
        title = _text_field(
            self.title,
            "visual pack title",
            max_length=_MAX_TITLE_LENGTH,
        )
        kind = _coerce_pack_kind(self.kind)
        license_id = _text_field(
            self.license_id,
            "visual pack license_id",
            max_length=_MAX_LICENSE_LENGTH,
        )
        author = _text_field(
            self.author,
            "visual pack author",
            max_length=_MAX_AUTHOR_LENGTH,
            allow_empty=True,
        )
        if not isinstance(self.assets, Mapping):
            raise ValueError("visual pack assets must be a mapping")
        if len(self.assets) > _MAX_ASSETS:
            raise ValueError("visual pack has too many assets")

        normalized_assets: dict[str, str] = {}
        for key, value in self.assets.items():
            asset_id = _stable_id(key, "asset id")
            asset_path = _safe_asset_path(value)
            if asset_id in normalized_assets:
                raise ValueError(f"duplicate visual asset id: {asset_id}")
            normalized_assets[asset_id] = asset_path

        if kind is VisualPackKind.PIECES:
            missing = sorted(_REQUIRED_PIECE_ASSETS - normalized_assets.keys())
            if missing:
                raise ValueError(
                    f"piece pack is missing required assets: {', '.join(missing)}"
                )

        object.__setattr__(self, "pack_id", pack_id)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "license_id", license_id)
        object.__setattr__(self, "author", author)
        object.__setattr__(
            self,
            "assets",
            MappingProxyType(dict(normalized_assets)),
        )


@dataclass(frozen=True)
class BoardVisualPreferences:
    board_theme_id: str = "classic"
    piece_theme_id: str = "classic"
    coordinate_mode: CoordinateMode = CoordinateMode.EDGES
    board_scale_percent: int = 100
    piece_scale_percent: int = 92
    show_last_move: bool = True
    reduced_motion: bool = False

    def __post_init__(self) -> None:
        board_theme_id = _stable_id(self.board_theme_id, "board_theme_id")
        piece_theme_id = _stable_id(self.piece_theme_id, "piece_theme_id")
        mode = _coerce_coordinate_mode(self.coordinate_mode)
        if (
            type(self.board_scale_percent) is not int
            or not 50 <= self.board_scale_percent <= 200
        ):
            raise ValueError(
                "board_scale_percent must be an integer in 50..200"
            )
        if (
            type(self.piece_scale_percent) is not int
            or not 50 <= self.piece_scale_percent <= 150
        ):
            raise ValueError(
                "piece_scale_percent must be an integer in 50..150"
            )
        if type(self.show_last_move) is not bool:
            raise ValueError("show_last_move must be boolean")
        if type(self.reduced_motion) is not bool:
            raise ValueError("reduced_motion must be boolean")

        object.__setattr__(self, "board_theme_id", board_theme_id)
        object.__setattr__(self, "piece_theme_id", piece_theme_id)
        object.__setattr__(self, "coordinate_mode", mode)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": VISUAL_PREFERENCES_SCHEMA_VERSION,
            "board_theme_id": self.board_theme_id,
            "piece_theme_id": self.piece_theme_id,
            "coordinate_mode": self.coordinate_mode.value,
            "board_scale_percent": self.board_scale_percent,
            "piece_scale_percent": self.piece_scale_percent,
            "show_last_move": self.show_last_move,
            "reduced_motion": self.reduced_motion,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "BoardVisualPreferences":
        if not isinstance(payload, Mapping):
            raise ValueError("visual preferences payload must be a mapping")

        schema = payload.get("schema_version", 0)
        if (
            type(schema) is not int
            or schema not in {0, VISUAL_PREFERENCES_SCHEMA_VERSION}
        ):
            raise ValueError("unsupported visual preferences schema_version")

        allowed = {
            "schema_version",
            "board_theme_id",
            "piece_theme_id",
            "coordinate_mode",
            "board_scale_percent",
            "piece_scale_percent",
            "show_last_move",
            "reduced_motion",
        }
        if set(payload) - allowed:
            raise ValueError("unknown visual preferences fields")

        return cls(
            board_theme_id=payload.get("board_theme_id", "classic"),
            piece_theme_id=payload.get("piece_theme_id", "classic"),
            coordinate_mode=payload.get(
                "coordinate_mode",
                CoordinateMode.EDGES.value,
            ),
            board_scale_percent=payload.get("board_scale_percent", 100),
            piece_scale_percent=payload.get("piece_scale_percent", 92),
            show_last_move=payload.get("show_last_move", True),
            reduced_motion=payload.get("reduced_motion", False),
        )
