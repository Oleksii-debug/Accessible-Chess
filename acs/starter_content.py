"""Deterministic, project-authored offline starter chess content.

This module deliberately reuses the canonical Accessible Chess move engine and
ACSDB implementation.  It does not embed or copy any third-party chess corpus.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .acsdb import AcsDatabase
from .chesscore import Board, Move


STARTER_GAME_COUNT = 240
STRESS_GAME_COUNT = 1200
STARTER_MAX_PLIES = 32
STRESS_MAX_PLIES = 16
GENERATOR_VERSION = 1
SOURCE_LICENSE = "project-authored-synthetic"
_SOURCE_DATE_PREFIX = "2026.01."


@dataclass(frozen=True)
class GeneratedGame:
    """One legal, deterministic synthetic PGN record."""

    index: int
    movetext: str
    result: str
    plies: int


def _move_key(move: Move) -> tuple[int, int, str, bool, bool]:
    return (
        move.frm,
        move.to,
        move.promotion or "",
        move.en_passant,
        move.castle,
    )


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


def _generate_game(index: int, *, max_plies: int) -> GeneratedGame:
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
        selected = legal[
            _choice_index(
                game_index=index,
                ply=ply,
                fen=board.fen(),
                size=len(legal),
            )
        ]
        san_moves.append(board.push(selected))

    result = _terminal_result(board)
    parts: list[str] = []
    for offset in range(0, len(san_moves), 2):
        move_number = offset // 2 + 1
        parts.append(f"{move_number}. {san_moves[offset]}")
        if offset + 1 < len(san_moves):
            parts.append(san_moves[offset + 1])
    parts.append(result)
    return GeneratedGame(
        index=index,
        movetext=" ".join(parts),
        result=result,
        plies=len(san_moves),
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
    header = "\n".join(f'[{name} "{value}"]' for name, value in tags)
    comment = "{Синтетична навчальна партія, створена локально без стороннього корпусу.}"
    return f"{header}\n\n{comment} {game.movetext}\n"


def build_pgn_corpus(
    count: int,
    *,
    max_plies: int,
    corpus_name: str,
) -> str:
    """Return a deterministic multi-game UTF-8 PGN corpus."""
    if type(count) is not int or count < 1:
        raise ValueError("count must be a positive integer")
    if type(max_plies) is not int or max_plies < 1:
        raise ValueError("max_plies must be a positive integer")
    if type(corpus_name) is not str or not corpus_name.strip():
        raise ValueError("corpus_name must be non-empty text")

    records = [
        _pgn_record(
            _generate_game(index, max_plies=max_plies),
            corpus_name=corpus_name,
        )
        for index in range(1, count + 1)
    ]
    return "\n".join(records)


def build_starter_pgn(count: int = STARTER_GAME_COUNT) -> str:
    return build_pgn_corpus(
        count,
        max_plies=STARTER_MAX_PLIES,
        corpus_name="навчальна серія",
    )


def build_stress_pgn(count: int = STRESS_GAME_COUNT) -> str:
    return build_pgn_corpus(
        count,
        max_plies=STRESS_MAX_PLIES,
        corpus_name="перевірка великої бібліотеки",
    )


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


def build_sample_library(
    destination: str | Path,
    *,
    starter_pgn: str | None = None,
    overwrite: bool = False,
) -> Path:
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
            report = database.import_pgn_text(
                pgn_text,
                source_name="accessible-chess-starter-uk.pgn",
            )
            expected_games = pgn_text.count('[Event "')
            imported_games = len(report.game_ids)
            if imported_games != expected_games:
                raise RuntimeError(
                    f"Starter ACSDB import count mismatch: expected "
                    f"{expected_games}, got {imported_games}"
                )
            if report.damaged:
                raise RuntimeError(
                    f"Starter ACSDB import reported {report.damaged} damaged games"
                )
            database.verify_integrity()
            # Canonicalize volatile import timestamps so repeated local builds
            # do not encode wall-clock state into the starter database.
            with database.conn:
                for table, column in (
                    ("sources", "imported_at"),
                    ("import_attempts", "started_at"),
                ):
                    try:
                        database.conn.execute(
                            f"UPDATE {table} SET {column}=?",
                            ("2026-09-11T00:00:00+00:00",),
                        )
                    except Exception:
                        # Schema evolution may remove a non-essential provenance
                        # timestamp. Integrity remains authoritative.
                        pass
                try:
                    database.conn.execute(
                        "UPDATE import_attempts SET finished_at=?",
                        ("2026-09-11T00:00:00+00:00",),
                    )
                except Exception:
                    pass
            database.verify_integrity()
    except Exception:
        _remove_sqlite_sidecars(target)
        raise

    # WAL/SHM files are runtime sidecars and are not part of the distributable.
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(target) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    return target


def _manifest(
    *,
    starter_bytes: bytes,
    stress_bytes: bytes,
    library_bytes: bytes,
    starter_count: int,
    stress_count: int,
) -> dict:
    return {
        "schema_version": 1,
        "generator_version": GENERATOR_VERSION,
        "provenance": {
            "kind": "project-authored-synthetic",
            "third_party_corpus": False,
            "network_required": False,
            "description_uk": (
                "Усі партії та метадані створюються детермінованим кодом "
                "Accessible Chess; сторонні PGN-бази не копіюються."
            ),
        },
        "counts": {
            "starter_games": starter_count,
            "stress_games": stress_count,
        },
        "files": {
            "starter_uk.pgn": {
                "sha256": _sha256_bytes(starter_bytes),
                "bytes": len(starter_bytes),
            },
            "stress_uk.pgn": {
                "sha256": _sha256_bytes(stress_bytes),
                "bytes": len(stress_bytes),
            },
            "sample_library.acsdb": {
                "sha256": _sha256_bytes(library_bytes),
                "bytes": len(library_bytes),
            },
        },
    }


def build_starter_bundle(
    destination: str | Path,
    *,
    overwrite: bool = False,
    starter_count: int = STARTER_GAME_COUNT,
    stress_count: int = STRESS_GAME_COUNT,
) -> dict:
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
        existing = [
            path
            for path in (starter_path, stress_path, library_path, manifest_path)
            if path.exists()
        ]
        if existing:
            raise FileExistsError(existing[0])

    _write_text_atomic(starter_path, starter_text, overwrite=overwrite)
    _write_text_atomic(stress_path, stress_text, overwrite=overwrite)
    build_sample_library(
        library_path,
        starter_pgn=starter_text,
        overwrite=overwrite,
    )

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
