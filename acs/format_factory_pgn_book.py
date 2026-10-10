from __future__ import annotations

"""Strict PGN collection -> existing semantic BookDocument adapter.

This is a private reading bridge, not a chess rules engine or a publication gate.
The D06 PGN parser and serializer remain authoritative for tags, SAN, comments,
variations and resource budgets. Actual move/position legality is a distinct
Section 54.4 gate and is NOT certified by this conversion.
"""

from hashlib import sha256

from .bookdocument import BookDocument, BookDocumentError, Game, MAX_BOOK_DOCUMENT_BLOCKS
from .gametree import GameTreeSerializationError, serialize_game
from .pgn_roundtrip import PgnRoundTripError, parse_pgn_bytes


class FactoryPgnBookError(ValueError):
    """PGN source cannot be represented safely as a book without data loss."""


def import_pgn_as_book(
    source: bytes, *, source_name: str,
    title: str | None = None, author: str | None = None,
    language: str | None = None,
) -> BookDocument:
    """Read one or more valid PGN games as linked semantic Book Game blocks.

    Fail atomically if ANY input game cannot be parsed and serialized strictly.
    Do not infer author, edition, rights, Chess960 rules, or position truth.
    """
    if type(source) is not bytes or not source:
        raise FactoryPgnBookError("A non-empty immutable PGN file is required")
    if type(source_name) is not str or not source_name:
        raise FactoryPgnBookError("A verified source name is required")

    try:
        games = parse_pgn_bytes(source, strict=True)
        if not games or len(games) > MAX_BOOK_DOCUMENT_BLOCKS:
            raise FactoryPgnBookError("PGN collection exceeds the supported book size")
        blocks: list[Game] = []
        for index, game in enumerate(games, start=1):
            serialized = serialize_game(game)
            if not serialized.strip():
                raise FactoryPgnBookError("A game cannot be represented without loss")
            participants = [
                game.tags.get(key) for key in ("White", "Black")
            ]
            game_title = " — ".join(
                name for name in participants if name and name != "?"
            ) or game.tags.get("Event") or f"Chess game {index}"
            game_title = game_title[:256]
            digest = sha256(serialized.encode("utf-8")).hexdigest()[:20]
            blocks.append(Game(
                pgn=serialized,
                title=game_title,
                block_id=f"factory-pgn-{digest}-{index}",
                source_anchor=f"pgn:game:{index}",
            ))
        document = BookDocument(
            title=title if title is not None else source_name.rsplit(".", 1)[0],
            author=author,
            language=language,
            source_name=source_name,
            blocks=blocks,
            warnings=[
                "PGN spacing and notation may be canonicalized; source bytes remain authoritative",
                "Chess move legality and diagram fidelity require separate Section 54.4 verification",
            ],
        )
        # Assert canonical wire representation before returning a readable book.
        document.as_dict()
        return document
    except (PgnRoundTripError, GameTreeSerializationError, BookDocumentError,
            UnicodeError, RecursionError, TypeError) as exc:
        raise FactoryPgnBookError("PGN failed strict semantic book conversion") from exc
