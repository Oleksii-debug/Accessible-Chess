from __future__ import annotations

"""Bind the P0-F starter corpus to the canonical Accessible Chess Training model.

The quality layer already authors position-specific exercises with legal canonical
coordinate moves. This adapter intentionally contains no move invention, parser
workaround, or second quiz/training engine.
"""

from .bookdocument import BookDocument
from .starter_books_training_quality import build_p0f_starter_course


def build_training_ready_starter_course() -> BookDocument:
    document = build_p0f_starter_course()
    # Rebuild every semantic block before publication. Any invalid FEN, duplicate
    # unsupported field, or malformed exercise fails before Books/Training UI sees it.
    document.as_dict()
    return document


__all__ = ["build_training_ready_starter_course"]
