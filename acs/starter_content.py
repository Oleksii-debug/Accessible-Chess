"""Deterministic, project-authored offline starter chess content.

This module deliberately reuses the canonical Accessible Chess move engine and
ACSDB implementation. It does not embed or copy any third-party chess corpus.
The starter set is anchored in a reviewed catalogue of legal opening themes;
the larger stress set is deterministic generated data for import/search load.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .acsdb import AcsDatabase
from .chesscore import Board, Move, parse_sq


STARTER_GAME_COUNT = 240
STRESS_GAME_COUNT = 1200
STARTER_MAX_PLIES = 32
STRESS_MAX_PLIES = 16
GENERATOR_VERSION = 2
CONTENT_LICENSE_ID = "LicenseRef-Accessible-Chess-Starter-Content-1.0"
CONTENT_LICENSE_TERMS_UK = (
    "Матеріали starter-content, позначені цим LicenseRef, створені проєктом "
    "Accessible Chess. Дозволено використовувати, копіювати, змінювати та "
    "поширювати їх разом з Accessible Chess або окремо за умови збереження "
    "цього повідомлення про походження та ліцензію. Сторонні шахові корпуси "
    "цим дозволом не охоплюються."
)
_SOURCE_DATE_PREFIX = "2026.01."


@dataclass(frozen=True)
class InstructionalSeed:
    """Reviewed legal opening prefix plus an explicit Ukrainian learning goal."""

    opening: str
    theme_uk: str
    learning_goal_uk: str
    uci_moves: tuple[str, ...]


INSTRUCTIONAL_SEEDS: tuple[InstructionalSeed, ...] = (
    InstructionalSeed("Italian Game", "Швидкий розвиток", "Розвинути коня і слона та контролювати центр.", ("e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6")),
    InstructionalSeed("Ruy Lopez", "Тиск на центр", "Зрозуміти тиск слона на захисника пішака e5.", ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6")),
    InstructionalSeed("Scotch Game", "Відкритий центр", "Побачити раннє розкриття центру ходом d4.", ("e2e4", "e7e5", "g1f3", "b8c6", "d2d4", "e5d4")),
    InstructionalSeed("Vienna Game", "Активний центр", "Порівняти розвиток коня c3 з типовим Nf3.", ("e2e4", "e7e5", "b1c3", "g8f6", "f2f4", "d7d5")),
    InstructionalSeed("Sicilian Defense", "Асиметричний центр", "Розпізнавати структуру після c5 і центрального обміну.", ("e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4")),
    InstructionalSeed("French Defense", "Пішаковий ланцюг", "Вивчити напруження e4-d5 та розвиток фігур.", ("e2e4", "e7e6", "d2d4", "d7d5", "b1c3", "g8f6")),
    InstructionalSeed("Caro-Kann Defense", "Надійний центр", "Побачити підготовлений удар d5 і центральний обмін.", ("e2e4", "c7c6", "d2d4", "d7d5", "b1c3", "d5e4")),
    InstructionalSeed("Scandinavian Defense", "Темп проти ферзя", "Оцінити ранній вихід ферзя та розвиток з темпом.", ("e2e4", "d7d5", "e4d5", "d8d5", "b1c3", "d5d8")),
    InstructionalSeed("Queen's Gambit", "Тиск на d5", "Зрозуміти ідею c4 проти центрального пішака d5.", ("d2d4", "d7d5", "c2c4", "e7e6", "b1c3", "g8f6")),
    InstructionalSeed("Slav Defense", "Міцний ферзевий центр", "Порівняти підтримку d5 пішаком c6.", ("d2d4", "d7d5", "c2c4", "c7c6", "g1f3", "g8f6")),
    InstructionalSeed("King's Indian Defense", "Фіанкетто", "Розпізнавати фіанкетто чорного слона і боротьбу за центр.", ("d2d4", "g8f6", "c2c4", "g7g6", "b1c3", "f8g7")),
    InstructionalSeed("Nimzo-Indian Defense", "Зв'язка коня", "Побачити тиск Bb4 на коня c3 і центр білих.", ("d2d4", "g8f6", "c2c4", "e7e6", "b1c3", "f8b4")),
    InstructionalSeed("English Opening", "Фланговий контроль", "Контролювати d5 через c4 без раннього e4 або d4.", ("c2c4", "e7e5", "b1c3", "g8f6", "g2g3", "d7d5")),
    InstructionalSeed("Reti Opening", "Гнучкий розвиток", "Розвивати королівський фланг із відкладеним центром.", ("g1f3", "d7d5", "c2c4", "e7e6", "g2g3", "g8f6")),
    InstructionalSeed("London System", "Стабільна схема розвитку", "Відпрацювати ранній Bf4 у ферзевому дебюті.", ("d2d4", "d7d5", "g1f3", "g8f6", "c1f4", "e7e6")),
    InstructionalSeed("Dutch Defense", "Контроль e4", "Побачити ідею f5 та фіанкетто у закритому центрі.", ("d2d4", "f7f5", "g2g3", "g8f6", "f1g2", "g7g6")),
)


@dataclass(frozen=True)
class GeneratedGame:
    """One legal deterministic PGN record."""

    index: int
    movetext: str
    result: str
    plies: int
    opening: str = ""
    theme_uk: str = ""
    learning_goal_uk: str = ""


def _move_key(move: Move) -> tuple[int, int, str, bool, bool]:
    return (move.frm, move.to, move.promotion or "", move.en_passant, move.castle)


def _choice_index(*, game_index: int, ply: int, fen: str, size: int) -> int:
    if size <= 0:
        raise ValueError("size must be positive")
    payload = f"ac-starter-v{GENERATOR_VERSION}:{game_index}:{ply}:{fen}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "big") % size


def _terminal_result(board: Board) -> str:
    if board.legal_moves():
        return "*"
    if board.in_check():
        return "0-1" if board.turn == "w" else "1-0"
    return "1/2-1/2"


def _movetext(san_moves: list[str], result: str) -> str:
    parts: list[str] = []
    for offset in range(0, len(san_moves), 2):
        parts.append(f"{offset // 2 + 1}. {san_moves[offset]}")
        if offset + 1 < len(san_moves):
            parts.append(san_moves[offset + 1])
    parts.append(result)
    return " ".join(parts)


def _push_uci(board: Board, uci: str) -> str:
    if len(uci) not in (4, 5):
        raise ValueError(f"Invalid curated UCI move: {uci!r}")
    frm = parse_sq(uci[:2])
    to = parse_sq(uci[2:4])
    promotion = uci[4].upper() if len(uci) == 5 else None
    for move in board.legal_moves():
        if move.frm == frm and move.to == to and move.promotion == promotion:
            return board.push(move)
    raise RuntimeError(f"Curated opening move is not legal in canonical engine: {uci}")


def _generate_game(index: int, *, max_plies: int) -> GeneratedGame:
    """Generate a deterministic legal load/stress game from the start position."""
    if type(index) is not int or index < 1:
        raise ValueError("index must be a positive integer")
    if type(max_plies) is not int or max_plies < 1:
        raise ValueError("max_plies must be a positive integer")

    board = Board()
    san_moves: list[str] = []
    for ply in range(max_plies):
        legal = sorted(board.legal_moves(), key=_move_key)
        if not legal:
            break
        selected = legal[_choice_index(game_index=index, ply=ply, fen=board.fen(), size=len(legal))]
        san_moves.append(board.push(selected))

    result = _terminal_result(board)
    return GeneratedGame(index=index, movetext=_movetext(san_moves, result), result=result, plies=len(san_moves))


def _generate_instructional_game(index: int, *, max_plies: int) -> GeneratedGame:
    """Generate one sample game anchored in a reviewed instructional opening line."""
    if type(index) is not int or index < 1:
        raise ValueError("index must be a positive integer")
    if type(max_plies) is not int or max_plies < 1:
        raise ValueError("max_plies must be a positive integer")

    seed = INSTRUCTIONAL_SEEDS[(index - 1) % len(INSTRUCTIONAL_SEEDS)]
    if max_plies < len(seed.uci_moves):
        raise ValueError("max_plies is shorter than the curated instructional prefix")

    board = Board()
    san_moves = [_push_uci(board, uci) for uci in seed.uci_moves]
    for ply in range(len(san_moves), max_plies):
        legal = sorted(board.legal_moves(), key=_move_key)
        if not legal:
            break
        selected = legal[_choice_index(game_index=index, ply=ply, fen=board.fen(), size=len(legal))]
        san_moves.append(board.push(selected))

    result = _terminal_result(board)
    return GeneratedGame(
        index=index,
        movetext=_movetext(san_moves, result),
        result=result,
        plies=len(san_moves),
        opening=seed.opening,
        theme_uk=seed.theme_uk,
        learning_goal_uk=seed.learning_goal_uk,
    )


def _pgn_record(game: GeneratedGame, *, corpus_name: str) -> str:
    day = ((game.index - 1) % 28) + 1
    student = ((game.index - 1) % 24) + 1
    coach = ((game.index - 1) % 12) + 1
    lesson = ((game.index - 1) % 16) + 1
    tags = [
        ("Event", f"Accessible Chess — {corpus_name} {lesson:02d}"),
        ("Site", "Офлайн"),
        ("Date", f"{_SOURCE_DATE_PREFIX}{day:02d}"),
        ("Round", str(game.index)),
        ("White", f"Учень {student:02d}"),
        ("Black", f"Тренер {coach:02d}"),
        ("Result", game.result),
        ("Annotator", "Accessible Chess deterministic generator"),
        ("Source", "project-authored synthetic corpus"),
    ]
    if game.opening:
        tags.extend((
            ("Opening", game.opening),
            ("Theme", game.theme_uk),
            ("LearningGoal", game.learning_goal_uk),
        ))
        comment = f"{{Навчальна тема: {game.theme_uk} Мета: {game.learning_goal_uk}}}"
    else:
        comment = "{Синтетична партія для перевірки імпорту, пошуку та навігації великою бібліотекою.}"
    header = "\n".join(f'[{name} "{value}"]' for name, value in tags)
    return f"{header}\n\n{comment} {game.movetext}\n"


def build_pgn_corpus(count: int, *, max_plies: int, corpus_name: str) -> str:
    """Return a deterministic legal load/stress PGN corpus."""
    if type(count) is not int or count < 1:
        raise ValueError("count must be a positive integer")
    if type(max_plies) is not int or max_plies < 1:
        raise ValueError("max_plies must be a positive integer")
    if type(corpus_name) is not str or not corpus_name.strip():
        raise ValueError("corpus_name must be non-empty text")
    return "\n".join(
        _pgn_record(_generate_game(index, max_plies=max_plies), corpus_name=corpus_name)
        for index in range(1, count + 1)
    )


def build_starter_pgn(count: int = STARTER_GAME_COUNT) -> str:
    if type(count) is not int or count < 1:
        raise ValueError("count must be a positive integer")
    return "\n".join(
        _pgn_record(
            _generate_instructional_game(index, max_plies=STARTER_MAX_PLIES),
            corpus_name="навчальна серія",
        )
        for index in range(1, count + 1)
    )


def build_stress_pgn(count: int = STRESS_GAME_COUNT) -> str:
    return build_pgn_corpus(count, max_plies=STRESS_MAX_PLIES, corpus_name="перевірка великої бібліотеки")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_text_atomic(path: Path, text: str, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temp = Path(raw_temp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def _remove_sqlite_sidecars(path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            if candidate.is_dir():
                raise IsADirectoryError(candidate)
            candidate.unlink()


def build_sample_library(destination: str | Path, *, starter_pgn: str | None = None, overwrite: bool = False) -> Path:
    """Build a sample ACSDB by going through the canonical PGN import path."""
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        raise FileExistsError(target)
    if overwrite:
        _remove_sqlite_sidecars(target)

    pgn_text = starter_pgn if starter_pgn is not None else build_starter_pgn()
    try:
        with AcsDatabase(target) as database:
            report = database.import_pgn_text(pgn_text, source_name="accessible-chess-starter-uk.pgn")
            expected_games = pgn_text.count('[Event "')
            if len(report.game_ids) != expected_games:
                raise RuntimeError(f"Starter ACSDB import count mismatch: expected {expected_games}, got {len(report.game_ids)}")
            if report.damaged:
                raise RuntimeError(f"Starter ACSDB import reported {report.damaged} damaged games")
            database.verify_integrity()
            with database.conn:
                database.conn.execute("UPDATE sources SET imported_at=?", ("2026-09-11T00:00:00+00:00",))
                database.conn.execute(
                    "UPDATE import_attempts SET started_at=?, finished_at=?",
                    ("2026-09-11T00:00:00+00:00", "2026-09-11T00:00:00+00:00"),
                )
            database.verify_integrity()
    except Exception:
        _remove_sqlite_sidecars(target)
        raise

    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(target) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    return target


def _licensed_file(payload: bytes) -> dict:
    return {
        "sha256": _sha256_bytes(payload),
        "bytes": len(payload),
        "license_id": CONTENT_LICENSE_ID,
    }


def _manifest(*, starter_bytes: bytes, stress_bytes: bytes, library_bytes: bytes, starter_count: int, stress_count: int) -> dict:
    return {
        "schema_version": 2,
        "generator_version": GENERATOR_VERSION,
        "provenance": {
            "kind": "project-authored-synthetic",
            "third_party_corpus": False,
            "network_required": False,
            "description_uk": "Усі партії та метадані створюються кодом Accessible Chess; сторонні PGN-бази не копіюються.",
        },
        "license": {
            "id": CONTENT_LICENSE_ID,
            "type": "project-owned-redistribution-grant",
            "terms_uk": CONTENT_LICENSE_TERMS_UK,
            "third_party_rights_asserted": False,
            "applies_to": ["starter_uk.pgn", "stress_uk.pgn", "sample_library.acsdb"],
        },
        "instructional_catalog": {
            "curated_seed_count": len(INSTRUCTIONAL_SEEDS),
            "opening_names": [seed.opening for seed in INSTRUCTIONAL_SEEDS],
        },
        "counts": {"starter_games": starter_count, "stress_games": stress_count},
        "files": {
            "starter_uk.pgn": _licensed_file(starter_bytes),
            "stress_uk.pgn": _licensed_file(stress_bytes),
            "sample_library.acsdb": _licensed_file(library_bytes),
        },
    }


def build_starter_bundle(destination: str | Path, *, overwrite: bool = False, starter_count: int = STARTER_GAME_COUNT, stress_count: int = STRESS_GAME_COUNT) -> dict:
    """Materialize the P0-F W2 starter assets into ``destination``."""
    output = Path(destination)
    output.mkdir(parents=True, exist_ok=True)

    starter_text = build_starter_pgn(starter_count)
    stress_text = build_stress_pgn(stress_count)
    starter_path = output / "starter_uk.pgn"
    stress_path = output / "stress_uk.pgn"
    library_path = output / "sample_library.acsdb"
    manifest_path = output / "manifest.json"

    if not overwrite:
        existing = [path for path in (starter_path, stress_path, library_path, manifest_path) if path.exists()]
        if existing:
            raise FileExistsError(existing[0])

    _write_text_atomic(starter_path, starter_text, overwrite=overwrite)
    _write_text_atomic(stress_path, stress_text, overwrite=overwrite)
    build_sample_library(library_path, starter_pgn=starter_text, overwrite=overwrite)

    starter_bytes = starter_path.read_bytes()
    stress_bytes = stress_path.read_bytes()
    library_bytes = library_path.read_bytes()
    manifest = _manifest(
        starter_bytes=starter_bytes,
        stress_bytes=stress_bytes,
        library_bytes=library_bytes,
        starter_count=starter_count,
        stress_count=stress_count,
    )
    _write_text_atomic(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        overwrite=overwrite,
    )
    return manifest
