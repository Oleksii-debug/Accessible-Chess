from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .teaching_ui import TeachingUiState
from .teaching_webapp import TeachingAccessibleChessAPI
from .visual_board_presentation import VisualAssetUrlPort, VisualBoardPresentation
from .visual_preferences import VisualPackManifest


_START_PIECES: dict[str, str] = {
    **{f"{file_name}2": "white_pawn" for file_name in "abcdefgh"},
    **{f"{file_name}7": "black_pawn" for file_name in "abcdefgh"},
    "a1": "white_rook",
    "b1": "white_knight",
    "c1": "white_bishop",
    "d1": "white_queen",
    "e1": "white_king",
    "f1": "white_bishop",
    "g1": "white_knight",
    "h1": "white_rook",
    "a8": "black_rook",
    "b8": "black_knight",
    "c8": "black_bishop",
    "d8": "black_queen",
    "e8": "black_king",
    "f8": "black_bishop",
    "g8": "black_knight",
    "h8": "black_rook",
}


class TeachingBoardAPI(TeachingAccessibleChessAPI):
    """Dedicated accessible board composition for the isolated teaching lane.

    The preview piece map is presentation-only and exists to make board/piece
    themes inspectable. It is not a chess game and never becomes canonical game
    state. Square semantics, CoachPointer and annotations remain owned by the
    existing teaching contracts.
    """

    def __init__(
        self,
        *,
        visual_packs: tuple[VisualPackManifest, ...] = (),
        asset_urls: VisualAssetUrlPort | None = None,
        preview_pieces: Mapping[str, str] | None = None,
    ) -> None:
        teaching = TeachingUiState(visual_packs=visual_packs)
        super().__init__(state=teaching)
        self._board = VisualBoardPresentation(packs=visual_packs, asset_urls=asset_urls)
        self._preview_pieces = dict(_START_PIECES if preview_pieces is None else preview_pieces)

    def teaching_board_visual_snapshot(self) -> dict[str, object]:
        teaching_snapshot = self.teaching.snapshot()
        board = self._board.snapshot(
            self.teaching.visual,
            pieces=self._preview_pieces,
            pointer_square=self.teaching.pointer.square,
        )
        descriptions: dict[str, list[str]] = {}
        for item in teaching_snapshot.get("annotations", []):
            kind = str(item.get("kind", ""))
            source = str(item.get("source", ""))
            target = item.get("target")
            if kind == "arrow" and target:
                text = f"Стрілка {source[0]} {source[1]} — {str(target)[0]} {str(target)[1]}."
                descriptions.setdefault(source, []).append(text)
                descriptions.setdefault(str(target), []).append(text)
            elif kind == "square" and source:
                descriptions.setdefault(source, []).append(f"Виділене поле {source[0]} {source[1]}.")
        for square in board["squares"]:
            square["accessibleDescription"] = " ".join(descriptions.get(str(square["square"]), ()))
        return board


def main() -> None:
    import webview

    html = Path(__file__).resolve().parents[1] / "web" / "teaching_board.html"
    if not html.exists():
        raise RuntimeError("Teaching board UI file is missing")
    webview.create_window(
        "Accessible Chess — Дошка тренера",
        url=str(html),
        js_api=TeachingBoardAPI(),
        width=1040,
        height=840,
        min_size=(760, 600),
        text_select=True,
    )
    webview.start(gui="edgechromium", private_mode=True)


if __name__ == "__main__":
    main()
