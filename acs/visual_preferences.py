from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Mapping


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


@dataclass(frozen=True)
class VisualPackManifest:
    """Validated presentation-only board/piece asset-pack metadata.

    Filesystem I/O deliberately stays outside this contract. The installer can
    resolve the validated relative asset paths inside a sandboxed pack root.
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
        version = str(self.version).strip()
        title = str(self.title).strip()
        license_id = str(self.license_id).strip()
        if not version:
            raise ValueError("visual pack version must not be empty")
        if not title:
            raise ValueError("visual pack title must not be empty")
        if not license_id:
            raise ValueError("visual pack license_id must not be empty")
        normalized_assets: dict[str, str] = {}
        for key, value in dict(self.assets).items():
            asset_id = _stable_id(key, "asset id")
            asset_path = _safe_asset_path(value)
            if asset_id in normalized_assets:
                raise ValueError(f"duplicate visual asset id: {asset_id}")
            normalized_assets[asset_id] = asset_path
        if self.kind is VisualPackKind.PIECES:
            missing = sorted(_REQUIRED_PIECE_ASSETS - normalized_assets.keys())
            if missing:
                raise ValueError(f"piece pack is missing required assets: {', '.join(missing)}")
        object.__setattr__(self, "pack_id", pack_id)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "license_id", license_id)
        object.__setattr__(self, "author", str(self.author).strip())
        object.__setattr__(self, "assets", normalized_assets)


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
        object.__setattr__(self, "board_theme_id", _stable_id(self.board_theme_id, "board_theme_id"))
        object.__setattr__(self, "piece_theme_id", _stable_id(self.piece_theme_id, "piece_theme_id"))
        if isinstance(self.board_scale_percent, bool) or not 50 <= int(self.board_scale_percent) <= 200:
            raise ValueError("board_scale_percent must be in 50..200")
        if isinstance(self.piece_scale_percent, bool) or not 50 <= int(self.piece_scale_percent) <= 150:
            raise ValueError("piece_scale_percent must be in 50..150")
        object.__setattr__(self, "board_scale_percent", int(self.board_scale_percent))
        object.__setattr__(self, "piece_scale_percent", int(self.piece_scale_percent))

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
        try:
            mode = CoordinateMode(str(payload.get("coordinate_mode", CoordinateMode.EDGES.value)))
        except ValueError as exc:
            raise ValueError("unknown coordinate_mode") from exc
        return cls(
            board_theme_id=str(payload.get("board_theme_id", "classic")),
            piece_theme_id=str(payload.get("piece_theme_id", "classic")),
            coordinate_mode=mode,
            board_scale_percent=int(payload.get("board_scale_percent", 100)),
            piece_scale_percent=int(payload.get("piece_scale_percent", 92)),
            show_last_move=bool(payload.get("show_last_move", True)),
            reduced_motion=bool(payload.get("reduced_motion", False)),
        )


def _stable_id(value: object, field_name: str) -> str:
    text = str(value).strip().lower()
    if not text or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for ch in text):
        raise ValueError(f"{field_name} must be a stable lowercase id")
    return text


def _safe_asset_path(value: object) -> str:
    text = str(value).strip().replace("\\", "/")
    path = PurePosixPath(text)
    if not text or path.is_absolute() or ".." in path.parts:
        raise ValueError("visual asset path must stay below pack root")
    if path.suffix.lower() not in _ALLOWED_ASSET_SUFFIXES:
        raise ValueError("unsupported visual asset type")
    return path.as_posix()
