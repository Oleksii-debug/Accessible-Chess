from __future__ import annotations

"""Final-product V2 application with deterministic offline starter Books/Training.

This layer only binds project-authored content to the existing BookDocument,
BookReader and Training authorities. It does not add a second content engine,
router, persistence format, or browser authority.
"""

from collections.abc import Mapping

from .book_board_workflow import BookBoardWorkflow
from .book_library_game_lookup import AcsdbBookGameLookup
from .bookdocument import BookDocument, Exercise, Paragraph
from .bookreader import BookReader
from .full_product_ui_shell import UILanguage
from .starter_books_training_content import STARTER_COURSE_BOOK_KEY
from .starter_books_training_release import (
    build_release_booklets,
    starter_release_manifest,
)
from .starter_books_training_runtime import build_training_ready_starter_course
from .version2_book_workspace import build_version2_book_webview
from .version2_education_mutation_application import Version2EducationMutationApplication
from .version2_windows_book_board_adapter import Version2WindowsBookBoardActionDelegate


_STARTER_COURSE_MATERIAL_ID = "starter-course"
_STARTER_BOOK_KEY_PREFIX = f"{STARTER_COURSE_BOOK_KEY}:material:"

_CATALOGUE_LABELS = {
    UILanguage.UA: {
        "heading": "Стартові офлайн-матеріали",
        "label": "Матеріал",
        "open": "Відкрити матеріал",
        "description": "Усі 24 посібники вже входять до програми й відкриваються без мережі.",
        "opened": "Відкрито матеріал",
    },
    UILanguage.EN: {
        "heading": "Offline starter materials",
        "label": "Material",
        "open": "Open material",
        "description": "All 24 booklets are bundled with the application and open offline.",
        "opened": "Opened material",
    },
}


class Version2StarterContentApplication(Version2EducationMutationApplication):
    """Bind the offline starter corpus to the already accepted Books/Training UX."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self._starter_course_document = build_training_ready_starter_course()
        self._starter_manifest = starter_release_manifest()
        self._starter_booklets = build_release_booklets()
        self._starter_material_documents: dict[str, BookDocument] = {}
        self._starter_material_entries: tuple[dict[str, str], ...] = ()
        self._starter_current_material_id: str | None = None
        self._prepare_starter_material_catalogue()
        self._install_starter_course()

    def _prepare_starter_material_catalogue(self) -> None:
        raw_materials = self._starter_manifest.get("materials")
        if not isinstance(raw_materials, tuple):
            raise RuntimeError("starter release material inventory is unavailable")
        if len(raw_materials) != len(self._starter_booklets):
            raise RuntimeError("starter release material inventory is inconsistent")

        documents: dict[str, BookDocument] = {}
        entries: list[dict[str, str]] = []
        for raw, document in zip(raw_materials, self._starter_booklets, strict=True):
            if not isinstance(raw, Mapping):
                raise RuntimeError("starter release material metadata is invalid")
            material_id = raw.get("material_id")
            title = raw.get("title")
            if type(material_id) is not str or not material_id.startswith("starter-booklet-"):
                raise RuntimeError("starter release material identity is invalid")
            if type(title) is not str or not title.strip() or title != document.title:
                raise RuntimeError("starter release material title is invalid")
            if material_id in documents:
                raise RuntimeError("starter release material identity is duplicated")
            documents[material_id] = document
            entries.append({"material_id": material_id, "title": title})

        expected_count = self._starter_manifest.get("material_count")
        if type(expected_count) is not int or expected_count != len(entries) or expected_count < 24:
            raise RuntimeError("starter release material count is below the accepted P0-F gate")

        self._starter_material_documents = documents
        self._starter_material_entries = tuple(entries)

    def _stage_book_document(
        self,
        *,
        material_id: str,
        book_key: str,
        document: BookDocument,
        open_route: bool,
        persist_new: bool,
    ) -> None:
        """Stage one bundled document through the canonical Books authority.

        Existing progress is durably saved before replacement. The new reader,
        workflow and WebView are constructed before publication, so a failure
        cannot leave a half-switched Books surface.
        """

        if self.book_workflow is not None and self.book_workflow.active:
            raise ValueError("return to the book before replacing the starter material")

        self.save_training_progress()
        self.save_book_progress()

        has_progress = self.progress_store.has(book_key)
        reader = (
            self.progress_store.restore(book_key, document)
            if has_progress
            else BookReader(document)
        )
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

        if persist_new and not has_progress:
            self.progress_store.save(book_key, reader)

        self.reader = reader
        self.book_key = book_key
        self.book_workflow = workflow
        self.book_delegate = delegate
        self.books = bridge
        self.training_workspace = self.training = None
        self._starter_current_material_id = material_id
        if open_route:
            self.shell.open_route("books")

    def _install_starter_course(self) -> None:
        """Stage the canonical built-in course without changing the active route."""

        document = self._starter_course_document
        introduction = document.blocks[1]
        if isinstance(introduction, Paragraph):
            introduction.text = (
                f"Офлайн-пакет містить {self._starter_manifest['material_count']} багаторозділові українські "
                f"посібники та {self._starter_manifest['training_exercise_count']} позиційні вправи. "
                "Він використовує той самий BookDocument і той самий Training, що й імпортовані "
                "книги, тому доступний без мережі та без ручного пошуку файлів."
            )

        self._stage_book_document(
            material_id=_STARTER_COURSE_MATERIAL_ID,
            book_key=STARTER_COURSE_BOOK_KEY,
            document=document,
            open_route=False,
            # Preserve the previous startup contract: a brand-new store is not
            # required to become writable merely to launch the application.
            persist_new=self.reader is not None,
        )

    def _starter_catalogue_snapshot(self) -> dict[str, object]:
        labels = _CATALOGUE_LABELS[self.shell.language]
        items = (
            {
                "material_id": _STARTER_COURSE_MATERIAL_ID,
                "title": self._starter_course_document.title,
            },
            *self._starter_material_entries,
        )
        return {
            "heading": labels["heading"],
            "label": labels["label"],
            "open_label": labels["open"],
            "description": labels["description"],
            "current_id": self._starter_current_material_id or "",
            "booklet_count": len(self._starter_material_entries),
            "items": items,
        }

    def _decorate_book_snapshot(self, snapshot: Mapping[str, object]) -> dict[str, object]:
        result = dict(snapshot)
        result["starter_materials"] = self._starter_catalogue_snapshot()
        return result

    def _decorate_book_result(self, result: dict[str, object]) -> dict[str, object]:
        if result.get("kind") != "render":
            return result
        payload = result.get("payload")
        if not isinstance(payload, Mapping):
            return result
        snapshot = payload.get("snapshot")
        if not isinstance(snapshot, Mapping):
            return result
        updated_payload = dict(payload)
        updated_payload["snapshot"] = self._decorate_book_snapshot(snapshot)
        updated = dict(result)
        updated["payload"] = updated_payload
        return updated

    @staticmethod
    def _starter_book_key(material_id: str) -> str:
        return f"{_STARTER_BOOK_KEY_PREFIX}{material_id}"

    def _open_starter_material(self, material_id: object) -> dict[str, object]:
        if type(material_id) is not str:
            raise TypeError("starter material identity must be text")
        if material_id == _STARTER_COURSE_MATERIAL_ID:
            document = self._starter_course_document
            book_key = STARTER_COURSE_BOOK_KEY
        else:
            document = self._starter_material_documents.get(material_id)
            if document is None:
                raise ValueError("starter material identity is not current")
            book_key = self._starter_book_key(material_id)

        self._stage_book_document(
            material_id=material_id,
            book_key=book_key,
            document=document,
            open_route=True,
            persist_new=True,
        )
        snapshot = self._decorate_book_snapshot(self.books.projection.snapshot())
        labels = _CATALOGUE_LABELS[self.shell.language]
        return {
            "kind": "render",
            "payload": {
                "snapshot": snapshot,
                "focus_target": snapshot["block"]["dom_id"],
                "announcement": f"{labels['opened']}: {document.title}",
            },
        }

    def open_book(self, source):
        warnings = super().open_book(source)
        self._starter_current_material_id = None
        return warnings

    def _start_training_from_current_book(self):
        """Make the existing Training route useful without manual block hunting."""

        if self.reader is None or not self.reader.document.exercises():
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

    def browser_command(self, area, command, payload=None):
        self._assert_thread()
        if area == "books" and command == "book.open_starter_material":
            try:
                if not isinstance(payload, Mapping) or set(payload) != {"material_id"}:
                    raise ValueError("starter material request is invalid")
                return self._open_starter_material(payload["material_id"])
            except Exception:
                return self._error()

        result = super().browser_command(area, command, payload)
        if area == "books" and isinstance(result, dict):
            return self._decorate_book_result(result)
        return result

    def snapshot(self) -> dict[str, object]:
        result = super().snapshot()
        books = result.get("books")
        if isinstance(books, Mapping):
            result["books"] = self._decorate_book_snapshot(books)
        return result


__all__ = ["Version2StarterContentApplication"]
