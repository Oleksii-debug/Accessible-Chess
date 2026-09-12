from __future__ import annotations

"""Release-grade P0-F starter Books and Training content.

This module composes the already-authored Ukrainian W3 lesson corpus into
substantial multi-chapter offline learning materials and converts a reviewed
opening-line catalogue into real position-specific canonical Training tasks.
It deliberately reuses BookDocument, Exercise and the canonical chess core; it
adds no second Books/Training engine and has no network/LLM dependency.
"""

from dataclasses import dataclass

from .bookdocument import BookDocument, Exercise, Heading, Paragraph
from .chesscore import Board, parse_sq
from .starter_books_training_content import (
    STARTER_CONTENT_LANGUAGE,
    STARTER_COURSE_BOOK_KEY,
    STARTER_CONTENT_RIGHTS,
    _LESSONS,
)
from .starter_content import INSTRUCTIONAL_SEEDS


STARTER_RELEASE_SCHEMA_VERSION = 1
STARTER_RELEASE_LICENSE_ID = "LicenseRef-Accessible-Chess-Starter-Books-Training-1.0"
STARTER_RELEASE_LICENSE_TERMS_UK = (
    "Матеріали стартових Books/Training, позначені цим LicenseRef, створені "
    "проєктом Accessible Chess. Дозволено використовувати, копіювати, "
    "змінювати та поширювати їх разом з Accessible Chess або окремо за умови "
    "збереження повідомлення про походження та цю ліцензію. Сторонні книги, "
    "курси, задачники або коментарі цим дозволом не охоплюються."
)
STARTER_RELEASE_SOURCE = "Accessible Chess project-authored offline starter corpus"
STARTER_BOOKLET_COUNT = 24
STARTER_BOOKLET_CHAPTERS = 12


@dataclass(frozen=True, slots=True)
class StarterTrainingTask:
    task_id: str
    opening: str
    theme_uk: str
    learning_goal_uk: str
    ply: int
    fen: str
    answer_uci: str


# Three reviewed continuation plies extend each already-reviewed W2 six-ply
# instructional prefix. They are kept explicit so the Training catalogue is
# authored data rather than a hash/random legal-move generator.
_CURATED_TAILS: tuple[tuple[str, str, str], ...] = (
    ("d2d3", "f8c5", "c2c3"),  # Italian
    ("b5a4", "g8f6", "e1g1"),  # Ruy Lopez
    ("f3d4", "g8f6", "b1c3"),  # Scotch
    ("f4e5", "f6e4", "g1f3"),  # Vienna
    ("f3d4", "g8f6", "b1c3"),  # Sicilian
    ("e4e5", "f6d7", "f2f4"),  # French
    ("c3e4", "c8f5", "e4g3"),  # Caro-Kann
    ("d2d4", "g8f6", "g1f3"),  # Scandinavian
    ("c1g5", "f8e7", "e2e3"),  # Queen's Gambit
    ("b1c3", "d5c4", "a2a4"),  # Slav
    ("e2e4", "d7d6", "g1f3"),  # King's Indian
    ("e2e3", "e8g8", "f1d3"),  # Nimzo-Indian
    ("c4d5", "f6d5", "f1g2"),  # English
    ("f1g2", "f8e7", "e1g1"),  # Reti
    ("e2e3", "f8e7", "f1d3"),  # London
    ("g1f3", "f8g7", "e1g1"),  # Dutch
)


def _push_uci(board: Board, uci: str) -> None:
    if len(uci) not in (4, 5):
        raise ValueError(f"invalid curated UCI move: {uci!r}")
    frm = parse_sq(uci[:2])
    to = parse_sq(uci[2:4])
    promotion = uci[4].upper() if len(uci) == 5 else None
    for move in board.legal_moves():
        if move.frm == frm and move.to == to and move.promotion == promotion:
            board.push(move)
            return
    raise ValueError(f"curated move is illegal in canonical chess core: {uci}")


def build_training_task_catalogue() -> tuple[StarterTrainingTask, ...]:
    """Return 144 authored position/move tasks from reviewed opening lines."""

    if len(INSTRUCTIONAL_SEEDS) != len(_CURATED_TAILS):
        raise RuntimeError("starter opening/tail catalogues are out of sync")

    tasks: list[StarterTrainingTask] = []
    for opening_index, (seed, tail) in enumerate(
        zip(INSTRUCTIONAL_SEEDS, _CURATED_TAILS, strict=True), start=1
    ):
        board = Board()
        line = seed.uci_moves + tail
        for ply, uci in enumerate(line, start=1):
            tasks.append(
                StarterTrainingTask(
                    task_id=f"opening-{opening_index:02d}-ply-{ply:02d}",
                    opening=seed.opening,
                    theme_uk=seed.theme_uk,
                    learning_goal_uk=seed.learning_goal_uk,
                    ply=ply,
                    fen=board.fen(),
                    answer_uci=uci,
                )
            )
            _push_uci(board, uci)
    return tuple(tasks)


def _booklet_lesson_indexes(booklet_index: int) -> tuple[int, ...]:
    """Return an explicit deterministic 12-chapter reading path.

    A coprime step distributes each booklet across fundamentals, tactics,
    strategy, notation and accessibility topics instead of taking one small
    adjacent fragment of the source course.
    """

    lesson_count = len(_LESSONS)
    if lesson_count < STARTER_BOOKLET_CHAPTERS:
        raise RuntimeError("source lesson corpus is too small for release booklets")
    step = 5
    return tuple((booklet_index + offset * step) % lesson_count for offset in range(STARTER_BOOKLET_CHAPTERS))


def _self_check_text(question: str, answer: str) -> str:
    return f"Самоперевірка: {question} Правильна відповідь: {answer}."


def _build_booklet(booklet_index: int) -> BookDocument:
    indexes = _booklet_lesson_indexes(booklet_index)
    anchor = _LESSONS[indexes[0]]
    booklet_id = f"starter-booklet-{booklet_index + 1:02d}"
    blocks: list[object] = [
        Heading(
            text=f"Accessible Chess: посібник {booklet_index + 1:02d} — {anchor.title}",
            level=1,
            block_id=f"{booklet_id}-heading",
            source_anchor=f"{booklet_id}:heading",
        ),
        Paragraph(
            text=(
                "Цей офлайн-посібник є завершеним навчальним маршрутом із дванадцяти "
                "взаємопов'язаних розділів. Читайте розділи послідовно, перевіряйте "
                "координати та шахові поняття на семантичній дошці й використовуйте "
                "запитання самоперевірки перед переходом до позиційного тренажера."
            ),
            block_id=f"{booklet_id}-intro",
            source_anchor=f"{booklet_id}:intro",
        ),
    ]

    for chapter_number, lesson_index in enumerate(indexes, start=1):
        spec = _LESSONS[lesson_index]
        chapter_id = f"{booklet_id}-chapter-{chapter_number:02d}-{spec.lesson_id}"
        blocks.append(
            Heading(
                text=f"Розділ {chapter_number}. {spec.title}",
                level=2,
                block_id=f"{chapter_id}-heading",
                source_anchor=f"{chapter_id}:heading",
            )
        )
        for paragraph_number, text in enumerate(spec.paragraphs, start=1):
            blocks.append(
                Paragraph(
                    text=text,
                    block_id=f"{chapter_id}-p{paragraph_number}",
                    source_anchor=f"{chapter_id}:p{paragraph_number}",
                )
            )
        for check_number, (question, answer) in enumerate(spec.checks, start=1):
            blocks.append(
                Paragraph(
                    text=_self_check_text(question, answer),
                    block_id=f"{chapter_id}-check-{check_number:02d}",
                    source_anchor=f"{chapter_id}:check:{check_number:02d}",
                )
            )

    return BookDocument(
        title=f"Accessible Chess: посібник {booklet_index + 1:02d} — {anchor.title}",
        language=STARTER_CONTENT_LANGUAGE,
        author="Accessible Chess project",
        source_name=f"{STARTER_RELEASE_SOURCE}; booklet {booklet_index + 1:02d}",
        source_rights=f"{STARTER_RELEASE_LICENSE_ID}; {STARTER_CONTENT_RIGHTS}",
        blocks=blocks,
    )


def build_release_booklets() -> tuple[BookDocument, ...]:
    """Return 24 substantial, multi-chapter, project-authored offline materials."""

    return tuple(_build_booklet(index) for index in range(STARTER_BOOKLET_COUNT))


def _append_authored_lesson_prose(blocks: list[object]) -> None:
    for lesson_number, spec in enumerate(_LESSONS, start=1):
        chapter_id = f"starter-release-lesson-{lesson_number:02d}-{spec.lesson_id}"
        blocks.append(
            Heading(
                text=f"Модуль {lesson_number}. {spec.title}",
                level=2,
                block_id=f"{chapter_id}-heading",
                source_anchor=f"{chapter_id}:heading",
            )
        )
        for paragraph_number, text in enumerate(spec.paragraphs, start=1):
            blocks.append(
                Paragraph(
                    text=text,
                    block_id=f"{chapter_id}-p{paragraph_number}",
                    source_anchor=f"{chapter_id}:p{paragraph_number}",
                )
            )
        for check_number, (question, answer) in enumerate(spec.checks, start=1):
            blocks.append(
                Paragraph(
                    text=_self_check_text(question, answer),
                    block_id=f"{chapter_id}-check-{check_number:02d}",
                    source_anchor=f"{chapter_id}:check:{check_number:02d}",
                )
            )


def build_release_starter_course() -> BookDocument:
    """Return the ready-to-open Books course plus 144 real position exercises."""

    tasks = build_training_task_catalogue()
    blocks: list[object] = [
        Heading(
            text="Accessible Chess: стартовий офлайн-курс",
            level=1,
            block_id="starter-release-course-heading",
            source_anchor="starter-release:course:heading",
        ),
        Paragraph(
            text=(
                f"Пакет містить {STARTER_BOOKLET_COUNT} багаторозділові українські посібники "
                f"та {len(tasks)} позиційні вправи. Увесь матеріал доступний офлайн, "
                "використовує канонічні Books/Training і не потребує ручного завантаження."
            ),
            block_id="starter-release-course-introduction",
            source_anchor="starter-release:course:introduction",
        ),
    ]
    _append_authored_lesson_prose(blocks)
    blocks.append(
        Heading(
            text="Позиційний тренажер: тематичні дебютні рішення",
            level=2,
            block_id="starter-release-training-heading",
            source_anchor="starter-release:training:heading",
        )
    )
    for task in tasks:
        blocks.append(
            Exercise(
                fen=task.fen,
                prompt=(
                    f"{task.opening}. {task.theme_uk} "
                    f"Крок {task.ply}: знайдіть тематичний хід. "
                    f"Навчальна мета: {task.learning_goal_uk}"
                ),
                answer_text=task.answer_uci,
                difficulty="starter",
                block_id=f"starter-release-{task.task_id}",
                source_anchor=f"starter-release:training:{task.task_id}",
            )
        )

    return BookDocument(
        title="Accessible Chess: стартовий офлайн-курс",
        language=STARTER_CONTENT_LANGUAGE,
        author="Accessible Chess project",
        source_name=STARTER_RELEASE_SOURCE,
        source_rights=f"{STARTER_RELEASE_LICENSE_ID}; {STARTER_CONTENT_RIGHTS}",
        blocks=blocks,
    )


def _word_count(document: BookDocument) -> int:
    return sum(
        len(block.text.split())
        for block in document.blocks
        if isinstance(block, (Heading, Paragraph))
    )


def starter_release_manifest() -> dict[str, object]:
    booklets = build_release_booklets()
    tasks = build_training_task_catalogue()
    return {
        "schema_version": STARTER_RELEASE_SCHEMA_VERSION,
        "language": STARTER_CONTENT_LANGUAGE,
        "source": STARTER_RELEASE_SOURCE,
        "license": {
            "id": STARTER_RELEASE_LICENSE_ID,
            "terms_uk": STARTER_RELEASE_LICENSE_TERMS_UK,
            "type": "project-owned-redistribution-grant",
        },
        "material_count": len(booklets),
        "training_exercise_count": len(tasks),
        "training_unique_fen_count": len({task.fen for task in tasks}),
        "materials": tuple(
            {
                "material_id": f"starter-booklet-{index + 1:02d}",
                "title": document.title,
                "chapter_count": sum(isinstance(block, Heading) and block.level == 2 for block in document.blocks),
                "word_count": _word_count(document),
                "source": document.source_name,
                "license_id": STARTER_RELEASE_LICENSE_ID,
            }
            for index, document in enumerate(booklets)
        ),
    }


__all__ = [
    "STARTER_BOOKLET_CHAPTERS",
    "STARTER_BOOKLET_COUNT",
    "STARTER_COURSE_BOOK_KEY",
    "STARTER_RELEASE_LICENSE_ID",
    "STARTER_RELEASE_LICENSE_TERMS_UK",
    "StarterTrainingTask",
    "build_release_booklets",
    "build_release_starter_course",
    "build_training_task_catalogue",
    "starter_release_manifest",
]
