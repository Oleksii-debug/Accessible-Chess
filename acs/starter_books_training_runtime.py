from __future__ import annotations

"""Runtime adapter for the release-grade offline starter Books/Training corpus.

The release corpus already contains canonical, position-specific chess exercises
with legal coordinate solutions. Runtime therefore does not rewrite factual quiz
answers into arbitrary opening moves; it simply publishes the authored release
course through the existing BookDocument/Training authority.
"""

from .bookdocument import BookDocument
from .starter_books_training_release import build_release_starter_course


def build_training_ready_starter_course() -> BookDocument:
    """Return the ready-to-open release course accepted by canonical Training."""

    document = build_release_starter_course()
    # Fail closed at the authoring/runtime boundary before any UI publication.
    document.as_dict()
    return document


__all__ = ["build_training_ready_starter_course"]
