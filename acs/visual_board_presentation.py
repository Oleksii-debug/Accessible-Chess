from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol
from urllib.parse import urlparse

from .visual_preferences import BoardVisualPreferences, CoordinateMode, VisualPackKind, VisualPackManifest


_FILES = "abcdefgh"
_RANKS_DESC = "87654321"
_PIECE_LABELS_UA = {
    "white_king": "білий король",
    "white_queen": "білий ферзь",
    "white_rook": "біла тура",
    "white_bishop": "білий слон",
    "white_knight": "білий кінь",
    "white_pawn": "білий пішак",
    "black_king": "чорний король",
    "black_queen": "чорний ферзь",
    "black_rook": "чорна тура",
    "black_bishop": "чорний слон",
    "black_knight": "чорний кінь",
    "black_pawn": "чорний пішак",
}
_ALLOWED_RENDER_URL_SCHEMES = {"app-asset", "data"}


class VisualAssetUrlPort(Protocol):
    """Resolve a validated manifest asset to a browser-safe presentation URL.

    Installation, filesystem access and integrity verification do not belong to
    the UI. The adapter may expose an ``app-asset:`` URL or a bounded image data
    URL. Raw file/http/javascript URLs are rejected by this presentation layer.
    """

    def resolve(self, pack_id: str, asset_id: str) -> str | None: ...


@dataclass(frozen=True)
class VisualBoardSquare:
    square: str
    row: int
    column: int
    piece_id: str | None
    accessible_name: str
    coordinate_text: str
    show_file_coordinate: bool
    show_rank_coordinate: bool
    piece_asset_url: str | None
    is_pointer: bool = False
    is_last_move: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "square": self.square,
            "row": self.row,
            "column": self.column,
            "pieceId": self.piece_id,
            "accessibleName": self.accessible_name,
            "coordinateText": self.coordinate_text,
            "showFileCoordinate": self.show_file_coordinate,
            "showRankCoordinate": self.show_rank_coordinate,
            "pieceAssetUrl": self.piece_asset_url,
            "isPointer": self.is_pointer,
            "isLastMove": self.is_last_move,
        }


class VisualBoardPresentation:
    """Theme-independent semantic 64-square presentation.

    Chess legality/state stays outside this object. It consumes a neutral piece
    map and produces a board view-model. Theme IDs, artwork and scaling affect
    visual fields only; square identity, keyboard order and accessible names are
    invariant. Missing or unsafe artwork falls back to semantic text rather than
    hiding a piece from a screen reader.
    """

    def __init__(
        self,
        *,
        packs: tuple[VisualPackManifest, ...] = (),
        asset_urls: VisualAssetUrlPort | None = None,
        built_in_board_id: str = "classic",
        built_in_piece_id: str = "classic",
    ) -> None:
        self._packs = {pack.pack_id: pack for pack in packs}
        self._asset_urls = asset_urls
        self._fallback_board = str(built_in_board_id).strip().lower()
        self._fallback_pieces = str(built_in_piece_id).strip().lower()

    def snapshot(
        self,
        preferences: BoardVisualPreferences,
        *,
        pieces: Mapping[str, str] | None = None,
        pointer_square: str | None = None,
        last_move: tuple[str, str] | None = None,
    ) -> dict[str, object]:
        pieces = self._normalize_pieces(pieces or {})
        board_pack = self._usable_pack(preferences.board_theme_id, VisualPackKind.BOARD)
        piece_pack = self._usable_pack(preferences.piece_theme_id, VisualPackKind.PIECES)
        effective_board_id = board_pack.pack_id if board_pack else self._fallback_board
        effective_piece_id = piece_pack.pack_id if piece_pack else self._fallback_pieces
        pointer = self._normalize_optional_square(pointer_square)
        last = set()
        if last_move is not None:
            if len(last_move) != 2:
                raise ValueError("last_move must contain source and target squares")
            last = {self._normalize_square(last_move[0]), self._normalize_square(last_move[1])}

        squares: list[dict[str, object]] = []
        for row, rank in enumerate(_RANKS_DESC, start=1):
            for column, file_name in enumerate(_FILES, start=1):
                square = f"{file_name}{rank}"
                piece_id = pieces.get(square)
                show_file, show_rank = self._coordinate_flags(preferences.coordinate_mode, square)
                coordinate = square if preferences.coordinate_mode is CoordinateMode.EVERY_SQUARE else (
                    f"{file_name if show_file else ''}{rank if show_rank else ''}"
                )
                accessible = self._accessible_square_name(square, piece_id)
                asset_url = self._piece_asset_url(piece_pack, piece_id)
                squares.append(
                    VisualBoardSquare(
                        square=square,
                        row=row,
                        column=column,
                        piece_id=piece_id,
                        accessible_name=accessible,
                        coordinate_text=coordinate,
                        show_file_coordinate=show_file,
                        show_rank_coordinate=show_rank,
                        piece_asset_url=asset_url,
                        is_pointer=pointer == square,
                        is_last_move=preferences.show_last_move and square in last,
                    ).as_dict()
                )

        return {
            "boardThemeId": effective_board_id,
            "pieceThemeId": effective_piece_id,
            "requestedBoardThemeId": preferences.board_theme_id,
            "requestedPieceThemeId": preferences.piece_theme_id,
            "boardFallbackUsed": effective_board_id != preferences.board_theme_id,
            "pieceFallbackUsed": effective_piece_id != preferences.piece_theme_id,
            "boardScalePercent": preferences.board_scale_percent,
            "pieceScalePercent": preferences.piece_scale_percent,
            "coordinateMode": preferences.coordinate_mode.value,
            "reducedMotion": preferences.reduced_motion,
            "squares": squares,
        }

    def _usable_pack(self, pack_id: str, kind: VisualPackKind) -> VisualPackManifest | None:
        if pack_id in {self._fallback_board, self._fallback_pieces}:
            return None
        pack = self._packs.get(pack_id)
        if pack is None or pack.kind is not kind:
            return None
        return pack

    def _piece_asset_url(self, pack: VisualPackManifest | None, piece_id: str | None) -> str | None:
        if pack is None or piece_id is None or self._asset_urls is None:
            return None
        if piece_id not in pack.assets:
            return None
        try:
            value = self._asset_urls.resolve(pack.pack_id, piece_id)
        except (KeyError, OSError, ValueError):
            return None
        if not value:
            return None
        text = str(value).strip()
        parsed = urlparse(text)
        if parsed.scheme not in _ALLOWED_RENDER_URL_SCHEMES:
            return None
        if parsed.scheme == "data" and not text.lower().startswith("data:image/"):
            return None
        return text

    @staticmethod
    def _normalize_pieces(pieces: Mapping[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for raw_square, raw_piece in pieces.items():
            square = VisualBoardPresentation._normalize_square(raw_square)
            piece_id = str(raw_piece).strip().lower()
            if piece_id not in _PIECE_LABELS_UA:
                raise ValueError(f"unknown piece id: {piece_id}")
            normalized[square] = piece_id
        return normalized

    @staticmethod
    def _normalize_square(value: object) -> str:
        square = str(value).strip().lower()
        if len(square) != 2 or square[0] not in _FILES or square[1] not in "12345678":
            raise ValueError("square must be a1..h8")
        return square

    @classmethod
    def _normalize_optional_square(cls, value: object | None) -> str | None:
        if value is None or not str(value).strip():
            return None
        return cls._normalize_square(value)

    @staticmethod
    def _accessible_square_name(square: str, piece_id: str | None) -> str:
        square_name = f"{square[0]} {square[1]}"
        if piece_id is None:
            return square_name
        return f"{_PIECE_LABELS_UA[piece_id]}, {square_name}"

    @staticmethod
    def _coordinate_flags(mode: CoordinateMode, square: str) -> tuple[bool, bool]:
        if mode is CoordinateMode.OFF:
            return False, False
        if mode is CoordinateMode.EVERY_SQUARE:
            return True, True
        file_name, rank = square[0], square[1]
        return rank == "1", file_name == "a"
