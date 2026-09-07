from __future__ import annotations

"""Real public-book acceptance oracle for the V2 HTML BookDocument adapter.

The workflow downloads Project Gutenberg eBook #16377 transiently.  This script
never vendors or republishes the book; it binds the exact downloaded bytes to a
SHA-256 supplied by CI and then exercises the Product importer plus existing
canonical Books/GameTree/Board/progress services.
"""

import argparse
from hashlib import sha256
from pathlib import Path
import tempfile

from acs.book_game_content import resolve_book_game
from acs.book_html_import import import_html_book
from acs.book_progress_store import BookProgressStore
from acs.bookdocument import Game, Heading, Note, Paragraph
from acs.bookreader import BookReader
from acs.chesscore import Board
from acs.gametree import serialize_game


EXPECTED_GAME_COUNT = 85
MIN_SOURCE_BYTES = 500_000
MIN_HEADINGS = 30
MIN_PARAGRAPHS = 200
MIN_IMAGE_REFERENCES = 20
MIN_ANNOTATED_GAMES = 5
MIN_NAG_GAMES = 2
MIN_VARIATION_GAMES = 1


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def run(source_path: Path, expected_sha256: str) -> None:
    raw = source_path.read_bytes()
    digest = sha256(raw).hexdigest()
    print(f"REAL_BOOK_SOURCE_BYTES={len(raw)}")
    print(f"REAL_BOOK_SOURCE_SHA256={digest}")
    if expected_sha256 == "UNPINNED":
        raise SystemExit(f"REAL_BOOK_SHA_NEEDS_PINNING={digest}")
    require(digest == expected_sha256, "real book source SHA-256 changed")
    require(len(raw) >= MIN_SOURCE_BYTES, "real book corpus is unexpectedly small")

    result = import_html_book(
        raw,
        source_name="Project Gutenberg eBook #16377",
        author="Howard Staunton",
        language="en",
        # Intentionally provide no resolved assets: the acceptance path must keep
        # the semantic text/game book usable while reporting missing image files.
        available_assets=(),
    )
    document = result.document
    headings = [block for block in document.blocks if isinstance(block, Heading)]
    paragraphs = [block for block in document.blocks if isinstance(block, Paragraph)]
    image_notes = [
        block for block in document.blocks
        if isinstance(block, Note) and block.note_type == "image"
    ]
    games = [block for block in document.blocks if isinstance(block, Game)]

    print(f"REAL_BOOK_TITLE={document.title}")
    print(f"REAL_BOOK_BLOCKS={len(document.blocks)}")
    print(f"REAL_BOOK_HEADINGS={len(headings)}")
    print(f"REAL_BOOK_PARAGRAPHS={len(paragraphs)}")
    print(f"REAL_BOOK_IMAGE_REFERENCES={len(result.image_references)}")
    print(f"REAL_BOOK_IMAGE_NOTES={len(image_notes)}")
    print(f"REAL_BOOK_MISSING_ASSETS={len(result.missing_assets)}")
    print(f"REAL_BOOK_PGN_GAMES={len(games)}")
    print(f"REAL_BOOK_WARNINGS={len(result.warnings)}")

    require("blue book of chess" in document.title.lower(), "real book title was not preserved")
    require(len(headings) >= MIN_HEADINGS, "real book heading hierarchy was not preserved")
    require(len(paragraphs) >= MIN_PARAGRAPHS, "real book instructional text was not preserved")
    require(len(result.image_references) >= MIN_IMAGE_REFERENCES, "real book image/diagram references were not observed")
    require(result.missing_assets, "real book missing-asset path was not exercised")
    require(len(image_notes) > 0, "real book image accessible text was not preserved")
    require(not any(block.kind == "Diagram" for block in document.blocks), "image-only source diagrams were fabricated as chess positions")
    require(len(games) == EXPECTED_GAME_COUNT, f"expected exactly {EXPECTED_GAME_COUNT} real embedded PGN games")
    require(any(ord(character) > 127 for block in headings + paragraphs for character in getattr(block, "text", "")), "real book Unicode text was not preserved")

    annotated = 0
    nagged = 0
    varied = 0
    for block in games:
        resolved = resolve_book_game(block)
        text = serialize_game(resolved.game)
        annotated += int("{" in text and "}" in text)
        nagged += int("$" in text)
        varied += int("(" in text and ")" in text)

    print(f"REAL_BOOK_ANNOTATED_GAMES={annotated}")
    print(f"REAL_BOOK_NAG_GAMES={nagged}")
    print(f"REAL_BOOK_VARIATION_GAMES={varied}")
    require(annotated >= MIN_ANNOTATED_GAMES, "real book annotations did not survive canonical GameTree")
    require(nagged >= MIN_NAG_GAMES, "real book NAGs did not survive canonical GameTree")
    require(varied >= MIN_VARIATION_GAMES, "real book RAV did not survive canonical GameTree")

    reader = BookReader(document)
    origin_index = next(
        index for index, block in enumerate(document.blocks)
        if isinstance(block, Paragraph) and len(block.text) > 40
    )
    origin = reader.go_to(origin_index)
    reader.save_return_point("real-book-origin")
    game_location = reader.next_game()
    game_block = document.blocks[game_location.index]
    require(isinstance(game_block, Game), "real book game navigation did not land on Game")
    resolved = resolve_book_game(game_block)
    start_fen = (
        resolved.game.tags.get("FEN")
        if resolved.game.tags.get("SetUp") == "1" and resolved.game.tags.get("FEN")
        else Board.START
    )
    board = Board(start_fen)
    require(len(board.board) == 64, "real book game did not open through canonical Board")
    returned = reader.restore_return_point("real-book-origin")
    require(returned == origin, "real book did not return to the exact reading origin")

    with tempfile.TemporaryDirectory() as directory:
        store = BookProgressStore(Path(directory) / "book-progress.json")
        store.save(result.book_key, reader)
        fresh = import_html_book(
            raw,
            source_name="Project Gutenberg eBook #16377",
            author="Howard Staunton",
            language="en",
            available_assets=(),
        )
        require(fresh.source_sha256 == result.source_sha256, "real book reimport identity changed")
        reopened = store.restore(result.book_key, fresh.document)
        require(reopened.location() == origin, "real book reading progress did not reopen exactly")
        reopened_game = reopened.next_game()
        require(reopened_game.block_id == game_location.block_id, "real book game identity drifted after reopen")

    print("REAL_HTML_BOOK_ACCEPTANCE=PASS")
    print("REAL_HTML_BOOK_DIAGRAM_POLICY=IMAGE_REFERENCES_PRESERVED_NO_POSITION_FABRICATION")
    print("REAL_HTML_BOOK_PROGRESS_REOPEN=PASS")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    run(args.source, args.expected_sha256)


if __name__ == "__main__":
    main()
