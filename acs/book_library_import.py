"""Supported book files -> existing canonical GameTree/Library ingress.

This adapter imports games only. It never flattens narrative books into PGN,
guesses image positions, queries Library storage or implements chess rules.
The original book remains readable through the existing Book Open workflow.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .book_epub_import import MAX_EPUB_SOURCE_BYTES, import_epub_book
from .book_html_import import MAX_HTML_SOURCE_BYTES, import_html_book
from .book_text_import import MAX_TEXT_SOURCE_BYTES, BookTextFormat, import_text_book
from .book_game_content import resolve_book_game
from .bookdocument import Game
from .gametree import PgnGame
from .import_contract import SourceFingerprint, SourceReadCancelledError, read_source_snapshot
from .report_paths import report_safe_name


BOOK_LIBRARY_SUFFIXES = frozenset({'.epub', '.html', '.htm', '.xhtml', '.md', '.markdown'})


class BookLibrarySourceReadError(ValueError):
    """A bounded book source could not be read under the canonical authority."""


@dataclass(frozen=True, slots=True)
class BookLibrarySource:
    source: SourceFingerprint
    games: tuple[PgnGame, ...]
    warnings: tuple[str, ...]
    retained_book_blocks: int = 0


def open_book_library_source(
    path: str | Path, *, cancel_check: Callable[[], bool] | None = None,
) -> BookLibrarySource:
    source_path = Path(path)
    suffix = source_path.suffix.casefold()
    if suffix not in BOOK_LIBRARY_SUFFIXES:
        raise ValueError('book format is not supported for Library game import')
    if suffix == '.epub':
        limit = MAX_EPUB_SOURCE_BYTES
    elif suffix in {'.md', '.markdown'}:
        limit = MAX_TEXT_SOURCE_BYTES
    else:
        limit = MAX_HTML_SOURCE_BYTES
    try:
        source, raw = read_source_snapshot(source_path, max_bytes=limit, cancel_check=cancel_check)
    except (OSError, ValueError):
        raise BookLibrarySourceReadError('book source could not be read safely') from None

    def poll():
        if cancel_check is not None:
            cancelled = cancel_check()
            if type(cancelled) is not bool:
                raise TypeError('cancel_check must return a boolean')
            if cancelled:
                raise SourceReadCancelledError('book game import cancelled')

    poll()
    control = {"control_checkpoint": poll} if cancel_check is not None else {}
    if suffix == '.epub':
        imported = import_epub_book(raw, source_name=report_safe_name(source_path), **control)
    elif suffix in {'.md', '.markdown'}:
        imported = import_text_book(raw, source_name=report_safe_name(source_path), source_format=BookTextFormat.MARKDOWN, **control)
    else:
        imported = import_html_book(raw, source_name=report_safe_name(source_path), available_assets=(), **control)
    poll()
    games = []
    prose_blocks = 0
    for block in imported.document.blocks:
        poll()
        if type(block) is Game:
            resolved = resolve_book_game(block)
            game = resolved.game
            # Stable source ordering across many separately marked regions.
            # Each resolver returns one detached canonical tree; no Book state
            # or original source metadata is mutated by Library publication.
            game.source_index = len(games)
            games.append(game)
        else:
            prose_blocks += 1
    warnings = list(imported.warnings)
    if prose_blocks:
        warnings.append(
            f'Library imports games only; {prose_blocks} narrative/position blocks remain in the source book. Use Open Book to read them.'
        )
    return BookLibrarySource(source, tuple(games), tuple(warnings), prose_blocks)
