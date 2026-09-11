from __future__ import annotations

"""Final-product V2 application with deterministic offline starter Books/Training.

This layer only binds project-authored content to the existing BookDocument,
BookReader and Training authorities. It does not add a second content engine,
router, persistence format, or browser authority.
"""

from .book_board_workflow import BookBoardWorkflow
from .book_library_game_lookup import AcsdbBookGameLookup
from .bookdocument import Exercise
from .bookreader import BookReader
from .starter_books_training_content import STARTER_COURSE_BOOK_KEY, build_starter_course
from .version2_book_workspace import build_version2_book_webview
from .version2_education_mutation_application import Version2EducationMutationApplication
from .version2_windows_book_board_adapter import Version2WindowsBookBoardActionDelegate


class Version2StarterContentApplication(Version2EducationMutationApplication):
    """Bind the offline starter course to the already accepted Books/Training UX."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._install_starter_course()

    def _install_starter_course(self) -> None:
        """Stage one canonical built-in book without changing the active route."""
        if self.book_workflow is not None and self.book_workflow.active:
            raise ValueError("return to the book before replacing the starter course")

        document = build_starter_course()
        if self.progress_store.has(STARTER_COURSE_BOOK_KEY):
            reader = self.progress_store.restore(STARTER_COURSE_BOOK_KEY, document)
        else:
            reader = BookReader(document)

        workflow = BookBoardWorkflow(
            reader,
            self.engine_assistance,
            game_lookup=AcsdbBookGameLookup(self.database),
        )
        delegate = Version2WindowsBookBoardActionDelegate(
            workflow,
            event_sink=self._book_event,
            next_delegate=self._board_dispatch,
        )
        bridge = build_version2_book_webview(
            reader,
            workflow,
            self.router.dispatch,
            language=self.shell.language,
        )
        self.reader = reader
        self.book_key = STARTER_COURSE_BOOK_KEY
        self.book_workflow = workflow
        self.book_delegate = delegate
        self.books = bridge
        self.training_workspace = self.training = None

    def _start_training_from_current_book(self):
        """Make the existing Training route useful without manual block hunting."""
        if self.reader is None:
            self._install_starter_course()
        if self.reader is None:
            return False

        if self.reader.location().kind != "Exercise":
            exercise_index = next(
                (
                    index
                    for index, block in enumerate(self.reader.document.blocks)
                    if isinstance(block, Exercise)
                ),
                None,
            )
            if exercise_index is None:
                return False
            self.reader.go_to(exercise_index)
            self.save_book_progress()

        return super()._start_training_from_current_book()


__all__ = ["Version2StarterContentApplication"]
