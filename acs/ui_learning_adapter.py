from __future__ import annotations

"""Accessible product projection for semantic books and legal training."""

import json
from typing import Any

from .acsdb import (
    MAX_BOOK_DOCUMENT_CHARACTERS,
    MAX_TRAINING_DEFINITION_CHARACTERS,
    AcsDatabase,
)
from .bookdocument import (
    BookDocument,
    Diagram,
    Exercise,
    Game,
    Heading,
    Note,
    Paragraph,
    Position,
    VariationTree,
)
from .bookreader import BookReader, ChessBlockContext
from .gametree import serialize_game
from .training import ExerciseDefinition, ExerciseSession


class LearningPresentationAdapter:
    def __init__(self, database: AcsDatabase, *, language: str = "uk") -> None:
        if not isinstance(database, AcsDatabase):
            raise TypeError("database must be an AcsDatabase")
        self._database = database
        self.language = language if language in {"uk", "en"} else "uk"
        self._reader: BookReader | None = None
        self._session: ExerciseSession | None = None
        self._last_hint: str | None = None

    @property
    def reader(self) -> BookReader | None:
        return self._reader

    @property
    def session(self) -> ExerciseSession | None:
        return self._session

    @property
    def book_context(self) -> ChessBlockContext | None:
        return self._reader.embedded_context if self._reader is not None else None

    def set_language(self, language: str) -> None:
        self.language = language if language in {"uk", "en"} else "uk"

    def import_book_json(self, text: str) -> dict[str, Any]:
        if type(text) is not str:
            raise TypeError("book JSON must be text")
        if not text.strip() or len(text) > MAX_BOOK_DOCUMENT_CHARACTERS:
            raise ValueError("book JSON is empty or exceeds the safety limit")
        payload = json.loads(text)
        document = BookDocument.from_dict(payload)
        self._database.save_book(document)
        return self.open_book(document.book_id or f"sha256:{BookReader(document).snapshot_id}")

    def open_book(self, book: int | str) -> dict[str, Any]:
        self._reader = BookReader(self._database.get_book(book))
        return self.book_state()

    def close_book(self) -> dict[str, Any]:
        self._reader = None
        return self.book_state()

    def _require_reader(self) -> BookReader:
        if self._reader is None:
            raise LookupError("No book is open")
        return self._reader

    @staticmethod
    def _block_projection(block: object) -> dict[str, Any]:
        projection: dict[str, Any] = {
            "kind": getattr(block, "kind", type(block).__name__),
            "blockId": getattr(block, "block_id", None),
            "sourceAnchor": getattr(block, "source_anchor", None),
            "text": "",
            "canOpenChess": isinstance(
                block,
                (Position, Diagram, Game, VariationTree, Exercise),
            ),
        }
        if isinstance(block, Heading):
            projection.update(text=block.text, level=block.level)
        elif isinstance(block, Paragraph):
            projection["text"] = block.text
        elif isinstance(block, Note):
            projection.update(text=block.text, noteType=block.note_type)
        elif isinstance(block, Diagram):
            projection.update(
                text=block.caption or block.alt_text or "Diagram",
                positionFen=block.fen,
                altText=block.alt_text,
            )
        elif isinstance(block, Position):
            projection.update(text=block.caption or "Position", positionFen=block.fen)
        elif isinstance(block, Game):
            projection.update(text=block.title or "Game", gameId=block.game_id)
        elif isinstance(block, VariationTree):
            projection.update(
                text=block.title or "Variation",
                positionFen=block.root_fen,
            )
        elif isinstance(block, Exercise):
            projection.update(
                text=block.prompt,
                positionFen=block.fen,
                difficulty=block.difficulty,
            )
        return projection

    def book_state(self) -> dict[str, Any]:
        books = self._database.list_books(limit=100)
        reader = self._reader
        if reader is None:
            return {
                "open": False,
                "books": books,
                "location": None,
                "block": None,
                "embedded": None,
            }
        location = reader.location()
        block = reader.block_at()
        embedded = reader.embedded_context
        return {
            "open": True,
            "books": books,
            "bookId": reader.book_id,
            "title": reader.title,
            "location": location.as_dict(),
            "block": self._block_projection(block),
            "embedded": (
                {
                    "positionFen": embedded.position_fen,
                    "block": embedded.block.as_dict(),
                    "origin": embedded.origin.as_dict(),
                }
                if embedded is not None
                else None
            ),
        }

    def book_next(self) -> dict[str, Any]:
        self._require_reader().next_block()
        return self.book_state()

    def book_previous(self) -> dict[str, Any]:
        self._require_reader().previous_block()
        return self.book_state()

    def book_go_to(self, index: int, reading_offset: int = 0) -> dict[str, Any]:
        self._require_reader().go_to(index, reading_offset=reading_offset)
        return self.book_state()

    def open_book_chess_block(self, index: int | None = None) -> ChessBlockContext:
        reader = self._require_reader()
        block = reader.block_at(index)
        resolved_pgn = None
        if isinstance(block, Game) and not block.pgn and block.game_id is not None:
            game = self._database.get_game_tree(block.game_id)
            if game is None:
                raise LookupError("Referenced database game is unavailable")
            resolved_pgn = serialize_game(game)
        return reader.open_chess_block(index, resolved_game_pgn=resolved_pgn)

    def return_to_book_text(self) -> dict[str, Any]:
        self._require_reader().return_to_text()
        return self.book_state()

    def save_bookmark(self, name: str = "default") -> dict[str, Any]:
        reader = self._require_reader()
        self._database.save_bookmark(reader.book_id, name, reader.location())
        return self.book_state()

    def load_bookmark(self, name: str = "default") -> dict[str, Any]:
        reader = self._require_reader()
        reader.restore_location(self._database.load_bookmark(reader.book_id, name))
        return self.book_state()

    def import_training_json(self, text: str) -> dict[str, Any]:
        if type(text) is not str:
            raise TypeError("training JSON must be text")
        if not text.strip() or len(text) > MAX_TRAINING_DEFINITION_CHARACTERS:
            raise ValueError("training JSON is empty or exceeds the safety limit")
        definition = ExerciseDefinition.from_dict(json.loads(text))
        self._database.save_training_definition(definition)
        return self.start_training(definition.exercise_id)

    def start_training(self, exercise_id: str) -> dict[str, Any]:
        self._session = self._database.load_training_session(exercise_id)
        self._last_hint = None
        return self.training_state()

    def close_training(self) -> dict[str, Any]:
        self._session = None
        self._last_hint = None
        return self.training_state()

    def _require_session(self) -> ExerciseSession:
        if self._session is None:
            raise LookupError("No training exercise is open")
        return self._session

    def training_state(self) -> dict[str, Any]:
        rows = self._database.list_training_definitions(limit=100)
        session = self._session
        if session is None:
            return {
                "open": False,
                "exercises": rows,
                "revealedMoves": [],
                "hint": None,
            }
        definition = session.definition
        revealed = (
            sorted(definition.steps[session.step_index].accepted_moves)
            if session.solution_revealed and not session.completed
            else []
        )
        return {
            "open": True,
            "exercises": rows,
            "exerciseId": definition.exercise_id,
            "title": definition.title or definition.exercise_id,
            "tags": list(definition.tags),
            "sourceId": definition.source_id,
            "status": session.status.value,
            "stepIndex": session.step_index,
            "stepCount": len(definition.steps),
            "attempts": session.attempts,
            "mistakes": session.mistakes,
            "hintsUsed": session.hints_used,
            "positionFen": session.position_fen,
            "completed": session.completed,
            "analysisAllowed": session.analysis_allowed,
            "solutionRevealed": session.solution_revealed,
            "revealedMoves": revealed,
            "hint": self._last_hint,
        }

    def submit_training(self, move: str) -> tuple[dict[str, Any], bool, str | None]:
        session = self._require_session()
        result = session.submit(move)
        self._last_hint = None
        self._database.save_training_progress(session)
        return self.training_state(), result.accepted, result.explanation

    def request_training_hint(self) -> dict[str, Any]:
        session = self._require_session()
        result = session.request_hint()
        self._last_hint = result.hint if result.available else None
        self._database.save_training_progress(session)
        return self.training_state()

    def reveal_training_solution(self) -> dict[str, Any]:
        session = self._require_session()
        session.reveal_solution()
        self._database.save_training_progress(session)
        return self.training_state()

    def reset_training(self) -> dict[str, Any]:
        session = self._require_session()
        session.reset()
        self._last_hint = None
        self._database.save_training_progress(session)
        return self.training_state()
