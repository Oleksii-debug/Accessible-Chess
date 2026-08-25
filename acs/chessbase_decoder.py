from __future__ import annotations

"""Evidence-gated ChessBase semantic decoding through an external backend.

Accessible Chess owns this protocol boundary and the neutral GameTree conversion.
A decoder implementation is an optional external executable.  It is never
loaded into the Python process and is never allowed to mutate the source family.
The current reference backend is libcbh, whose distribution/license lifecycle is
kept separate from the Accessible Chess release until explicitly approved.
"""

from dataclasses import dataclass
from enum import Enum
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import threading
import time
from typing import Iterable

from .chessbase_adapter import probe_chessbase_source
from .chessbase_integrity import (
    ChessBaseIntegritySnapshot,
    ChessBaseIntegrityIOError,
    ChessBaseSourceChangedError,
    capture_integrity_snapshot,
    verify_integrity_snapshot,
)
from .chesscore import Board, Move
from .gametree import Comment, MoveNode, PgnGame, VariationLine
from .report_paths import report_safe_name

PROTOCOL_ID = "accessible-chess-libcbh-v1"
MAX_BACKEND_STDOUT = 64 * 1024 * 1024
MAX_BACKEND_STDERR = 1 * 1024 * 1024
MAX_DECODED_GAMES = 100_000
MAX_DECODED_TOKENS_PER_GAME = 500_000
MAX_DECODED_TOKENS_TOTAL = 2_000_000
MAX_TAGS_PER_GAME = 4096
MAX_TAG_CHARS = 1 * 1024 * 1024
MAX_COMMENT_CHARS = 1 * 1024 * 1024
MAX_START_FEN_CHARS = 4096
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")


class ChessBaseDecodeCode(str, Enum):
    UNSUPPORTED_SOURCE = "unsupported_source"
    BACKEND_INVALID = "backend_invalid"
    BACKEND_TIMEOUT = "backend_timeout"
    BACKEND_OUTPUT_LIMIT = "backend_output_limit"
    BACKEND_FAILED = "backend_failed"
    PROTOCOL_ERROR = "protocol_error"
    RESOURCE_LIMIT = "resource_limit"
    SOURCE_CHANGED = "source_changed"
    INVALID_MOVE = "invalid_move"
    INVALID_VARIATION = "invalid_variation"
    INVALID_GAME = "invalid_game"


class ChessBaseDecodeError(RuntimeError):
    def __init__(self, message: str, *, code: ChessBaseDecodeCode) -> None:
        super().__init__(message)
        self.code = ChessBaseDecodeCode(code)


@dataclass(frozen=True, slots=True)
class ExternalChessBaseDecoderConfig:
    executable: Path
    expected_backend_commit: str | None = None
    timeout_seconds: float = 120.0
    max_stdout_bytes: int = MAX_BACKEND_STDOUT
    max_stderr_bytes: int = MAX_BACKEND_STDERR
    library_directory: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "executable", Path(self.executable))
        if self.expected_backend_commit is not None and (
            type(self.expected_backend_commit) is not str
            or _SHA40_RE.fullmatch(self.expected_backend_commit) is None
        ):
            raise ValueError("expected_backend_commit must be a lowercase 40-hex SHA")
        if type(self.timeout_seconds) not in (int, float) or not 0 < float(self.timeout_seconds) <= 600:
            raise ValueError("timeout_seconds must be within (0, 600]")
        for value, label in (
            (self.max_stdout_bytes, "max_stdout_bytes"),
            (self.max_stderr_bytes, "max_stderr_bytes"),
        ):
            if type(value) is not int or value < 1024 or value > 256 * 1024 * 1024:
                raise ValueError(f"{label} is outside the supported bound")
        if self.library_directory is not None:
            object.__setattr__(self, "library_directory", Path(self.library_directory))


@dataclass(frozen=True, slots=True)
class ChessBaseDecodeWarning:
    game_index: int
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ChessBaseDecodedDatabase:
    source: ChessBaseIntegritySnapshot
    backend_name: str
    backend_commit: str
    games: tuple[PgnGame, ...]
    warnings: tuple[ChessBaseDecodeWarning, ...] = ()

    @property
    def total_games(self) -> int:
        return len(self.games)


@dataclass(slots=True)
class _CapturedStream:
    buffer: bytearray
    overflow: threading.Event


def _decode_error(message: str, code: ChessBaseDecodeCode) -> ChessBaseDecodeError:
    return ChessBaseDecodeError(message, code=code)


def _is_reparse_point(st: os.stat_result) -> bool:
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(st, "st_file_attributes", 0) & marker)


def _validate_backend_path(path: Path) -> Path:
    try:
        st = path.lstat()
    except OSError as exc:
        raise _decode_error(
            "ChessBase decoder backend is unavailable",
            ChessBaseDecodeCode.BACKEND_INVALID,
        ) from exc
    if stat.S_ISLNK(st.st_mode) or _is_reparse_point(st) or not stat.S_ISREG(st.st_mode):
        raise _decode_error(
            "ChessBase decoder backend must be a regular non-indirected file",
            ChessBaseDecodeCode.BACKEND_INVALID,
        )
    return Path(os.path.abspath(os.fspath(path)))


def _validate_library_directory(path: Path | None) -> Path | None:
    if path is None:
        return None
    try:
        st = path.lstat()
    except OSError as exc:
        raise _decode_error(
            "ChessBase decoder library directory is unavailable",
            ChessBaseDecodeCode.BACKEND_INVALID,
        ) from exc
    if stat.S_ISLNK(st.st_mode) or _is_reparse_point(st) or not stat.S_ISDIR(st.st_mode):
        raise _decode_error(
            "ChessBase decoder library directory must be a real directory",
            ChessBaseDecodeCode.BACKEND_INVALID,
        )
    return Path(os.path.abspath(os.fspath(path)))


def _sterile_environment(executable: Path, library_directory: Path | None) -> dict[str, str]:
    env: dict[str, str] = {}
    for key in ("SystemRoot", "WINDIR", "COMSPEC", "TEMP", "TMP"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    search_dirs = [str(executable.parent)]
    if library_directory is not None and library_directory != executable.parent:
        search_dirs.append(str(library_directory))
    env["PATH"] = os.pathsep.join(search_dirs)
    if library_directory is not None and os.name != "nt":
        env["LD_LIBRARY_PATH"] = str(library_directory)
    env["LC_ALL"] = "C.UTF-8"
    env["LANG"] = "C.UTF-8"
    return env


def _read_capped(stream, limit: int, captured: _CapturedStream) -> None:
    try:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                return
            remaining = limit + 1 - len(captured.buffer)
            if remaining > 0:
                captured.buffer.extend(chunk[:remaining])
            if len(captured.buffer) > limit:
                captured.overflow.set()
                return
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _run_backend(
    executable: Path,
    source: Path,
    config: ExternalChessBaseDecoderConfig,
) -> bytes:
    library_directory = _validate_library_directory(config.library_directory)
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        process = subprocess.Popen(
            [os.fspath(executable), "--json-v1", os.fspath(source)],
            cwd=os.fspath(executable.parent),
            env=_sterile_environment(executable, library_directory),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            creationflags=creationflags,
            start_new_session=(os.name != "nt"),
        )
    except OSError as exc:
        raise _decode_error(
            "ChessBase decoder backend could not be started",
            ChessBaseDecodeCode.BACKEND_INVALID,
        ) from exc

    assert process.stdout is not None and process.stderr is not None
    stdout = _CapturedStream(bytearray(), threading.Event())
    stderr = _CapturedStream(bytearray(), threading.Event())
    threads = (
        threading.Thread(
            target=_read_capped,
            args=(process.stdout, config.max_stdout_bytes, stdout),
            daemon=True,
        ),
        threading.Thread(
            target=_read_capped,
            args=(process.stderr, config.max_stderr_bytes, stderr),
            daemon=True,
        ),
    )
    for thread in threads:
        thread.start()

    deadline = time.monotonic() + float(config.timeout_seconds)
    timed_out = False
    overflow = False
    while process.poll() is None:
        if stdout.overflow.is_set() or stderr.overflow.is_set():
            overflow = True
            process.kill()
            break
        if time.monotonic() >= deadline:
            timed_out = True
            process.kill()
            break
        time.sleep(0.01)

    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2.0)
    for thread in threads:
        thread.join(timeout=2.0)

    if timed_out:
        raise _decode_error(
            "ChessBase decoder backend exceeded its time limit",
            ChessBaseDecodeCode.BACKEND_TIMEOUT,
        )
    if overflow or stdout.overflow.is_set() or stderr.overflow.is_set():
        raise _decode_error(
            "ChessBase decoder backend exceeded its output limit",
            ChessBaseDecodeCode.BACKEND_OUTPUT_LIMIT,
        )
    if process.returncode != 0:
        raise _decode_error(
            f"ChessBase decoder backend failed with exit code {process.returncode}",
            ChessBaseDecodeCode.BACKEND_FAILED,
        )
    return bytes(stdout.buffer)


def _no_duplicate_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _parse_backend_json(data: bytes) -> dict[str, object]:
    try:
        text = data.decode("utf-8", errors="strict")
        value = json.loads(text, object_pairs_hook=_no_duplicate_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise _decode_error(
            "ChessBase decoder returned invalid canonical JSON",
            ChessBaseDecodeCode.PROTOCOL_ERROR,
        ) from exc
    if type(value) is not dict:
        raise _decode_error(
            "ChessBase decoder protocol root must be an object",
            ChessBaseDecodeCode.PROTOCOL_ERROR,
        )
    return value


def _exact_int(value: object, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise _decode_error(
            f"ChessBase decoder field {label} is invalid",
            ChessBaseDecodeCode.PROTOCOL_ERROR,
        )
    return value


def _bounded_text(value: object, label: str, maximum: int) -> str:
    if type(value) is not str or len(value) > maximum:
        raise _decode_error(
            f"ChessBase decoder field {label} is invalid",
            ChessBaseDecodeCode.PROTOCOL_ERROR,
        )
    return value


def _square_name(index: int) -> str:
    return chr(ord("a") + index % 8) + str(index // 8 + 1)


def _comment_text(item: dict[str, object]) -> tuple[str, str] | None:
    kind = item.get("kind")
    if kind in ("text_before", "text_after"):
        lang = _exact_int(item.get("lang"), "comment.lang", 0, 65535)
        text = _bounded_text(item.get("text"), "comment.text", MAX_COMMENT_CHARS)
        if lang:
            text = f"[%cbh-lang {lang}] {text}"
        return (str(kind), text)
    if kind == "arrow":
        frm = _exact_int(item.get("from"), "comment.from", 0, 63)
        to = _exact_int(item.get("to"), "comment.to", 0, 63)
        color = _bounded_text(item.get("color"), "comment.color", 32)
        return ("text_after", f"[%cbh-arrow {color} {_square_name(frm)}{_square_name(to)}]")
    if kind == "square":
        sq = _exact_int(item.get("square"), "comment.square", 0, 63)
        color = _bounded_text(item.get("color"), "comment.color", 32)
        return ("text_after", f"[%cbh-square {color} {_square_name(sq)}]")
    if kind == "symbol":
        return None
    raise _decode_error(
        "ChessBase decoder returned an unknown annotation kind",
        ChessBaseDecodeCode.PROTOCOL_ERROR,
    )


def _apply_comments(node: MoveNode, comments: object) -> None:
    if type(comments) is not list or len(comments) > 4096:
        raise _decode_error(
            "ChessBase decoder returned an invalid annotation collection",
            ChessBaseDecodeCode.PROTOCOL_ERROR,
        )
    for raw in comments:
        if type(raw) is not dict:
            raise _decode_error(
                "ChessBase decoder returned an invalid annotation record",
                ChessBaseDecodeCode.PROTOCOL_ERROR,
            )
        if raw.get("kind") == "symbol":
            for field in ("symbol", "evaluation", "prefix"):
                nag = _exact_int(raw.get(field), f"comment.{field}", 0, 255)
                if nag:
                    node.nags.append(f"${nag}")
            continue
        converted = _comment_text(raw)
        assert converted is not None
        where, text = converted
        comment = Comment(text)
        if where == "text_before":
            node.comments_before.append(comment)
        else:
            node.comments_after.append(comment)


def _null_move(board: Board) -> str:
    parts = board.fen().split()
    if len(parts) != 6:
        raise _decode_error(
            "canonical board produced an invalid FEN while decoding a null move",
            ChessBaseDecodeCode.INVALID_MOVE,
        )
    was_black = parts[1] == "b"
    parts[1] = "w" if was_black else "b"
    parts[3] = "-"
    parts[4] = str(int(parts[4]) + 1)
    if was_black:
        parts[5] = str(int(parts[5]) + 1)
    board.set_fen(" ".join(parts))
    return "--"


_PROMOTIONS = {2: "Q", 3: "R", 4: "B", 5: "N", 7: None}


def _decode_move(board: Board, token: dict[str, object]) -> str:
    frm = _exact_int(token.get("from"), "move.from", 0, 63)
    to = _exact_int(token.get("to"), "move.to", 0, 63)
    promote = _exact_int(token.get("promote"), "move.promote", 0, 255)
    if promote == 6:
        return _null_move(board)
    if promote == 1:
        candidates = [
            move
            for move in board.legal_moves()
            if move.frm == frm and move.to == to and move.castle
        ]
    elif promote in _PROMOTIONS:
        promotion = _PROMOTIONS[promote]
        candidates = [
            move
            for move in board.legal_moves()
            if move.frm == frm and move.to == to and move.promotion == promotion
        ]
    else:
        raise _decode_error(
            "ChessBase decoder returned an unsupported promotion marker",
            ChessBaseDecodeCode.INVALID_MOVE,
        )
    if len(candidates) != 1:
        raise _decode_error(
            "ChessBase decoded move is not uniquely legal in the canonical position",
            ChessBaseDecodeCode.INVALID_MOVE,
        )
    return board.push(candidates[0])


def _move_number(board: Board) -> str:
    return f"{board.fullmove}." if board.turn == "w" else f"{board.fullmove}..."


def _decode_line(
    tokens: list[object],
    index: int,
    board: Board,
    *,
    nested: bool,
    budget: list[int],
) -> tuple[VariationLine, int]:
    line = VariationLine()
    while index < len(tokens):
        raw = tokens[index]
        if type(raw) is not dict:
            raise _decode_error(
                "ChessBase decoder move token must be an object",
                ChessBaseDecodeCode.PROTOCOL_ERROR,
            )
        kind = raw.get("kind")
        budget[0] += 1
        if budget[0] > MAX_DECODED_TOKENS_PER_GAME:
            raise _decode_error(
                "ChessBase decoded game exceeds the token safety limit",
                ChessBaseDecodeCode.RESOURCE_LIMIT,
            )
        if kind == "pop":
            if not nested:
                raise _decode_error(
                    "ChessBase decoder returned an unmatched variation pop",
                    ChessBaseDecodeCode.INVALID_VARIATION,
                )
            return line, index + 1
        if kind == "skip":
            index += 1
            continue
        if kind == "push":
            if not line.moves:
                raise _decode_error(
                    "ChessBase variation has no preceding canonical move",
                    ChessBaseDecodeCode.INVALID_VARIATION,
                )
            branch, index = _decode_line(
                tokens,
                index + 1,
                board.clone(),
                nested=True,
                budget=budget,
            )
            if not branch.moves:
                raise _decode_error(
                    "ChessBase decoder returned an empty variation",
                    ChessBaseDecodeCode.INVALID_VARIATION,
                )
            line.moves[-1].variations.append(branch)
            continue
        if kind != "move":
            raise _decode_error(
                "ChessBase decoder returned an unknown move token",
                ChessBaseDecodeCode.PROTOCOL_ERROR,
            )
        number = _move_number(board)
        san = _decode_move(board, raw)
        node = MoveNode(san=san, move_number=number)
        _apply_comments(node, raw.get("comments", []))
        line.moves.append(node)
        index += 1
    if nested:
        raise _decode_error(
            "ChessBase decoder returned an unterminated variation",
            ChessBaseDecodeCode.INVALID_VARIATION,
        )
    return line, index


def _date(year: int, month: int, day: int) -> str:
    return f"{year:04d}.{month:02d}.{day:02d}" if year else "????.??.??"


def _person(first: str, last: str) -> str:
    return " ".join(part for part in (first.strip(), last.strip()) if part)


def _decode_game(raw: object, expected_index: int, total_budget: list[int]) -> tuple[PgnGame | None, ChessBaseDecodeWarning | None]:
    if type(raw) is not dict:
        raise _decode_error(
            "ChessBase decoder game record must be an object",
            ChessBaseDecodeCode.PROTOCOL_ERROR,
        )
    index = _exact_int(raw.get("index"), "game.index", 0, MAX_DECODED_GAMES - 1)
    if index != expected_index:
        raise _decode_error(
            "ChessBase decoder game indexes are not contiguous",
            ChessBaseDecodeCode.PROTOCOL_ERROR,
        )
    status = raw.get("status")
    if status == "skipped":
        error_code = _exact_int(raw.get("error_code"), "game.error_code", 0, 65535)
        return None, ChessBaseDecodeWarning(index, "backend_record_skipped", f"backend record skipped with code {error_code}")
    if status != "decoded":
        raise _decode_error(
            "ChessBase decoder game status is invalid",
            ChessBaseDecodeCode.PROTOCOL_ERROR,
        )

    start_fen = _bounded_text(raw.get("start_fen"), "game.start_fen", MAX_START_FEN_CHARS)
    try:
        board = Board(start_fen)
    except ValueError as exc:
        raise _decode_error(
            "ChessBase decoder returned an invalid start position",
            ChessBaseDecodeCode.INVALID_GAME,
        ) from exc

    raw_tags = raw.get("tags", [])
    if type(raw_tags) is not list or len(raw_tags) > MAX_TAGS_PER_GAME:
        raise _decode_error(
            "ChessBase decoder returned an invalid tag collection",
            ChessBaseDecodeCode.PROTOCOL_ERROR,
        )
    tags: dict[str, str] = {}
    for item in raw_tags:
        if type(item) is not dict:
            raise _decode_error(
                "ChessBase decoder tag must be an object",
                ChessBaseDecodeCode.PROTOCOL_ERROR,
            )
        name = _bounded_text(item.get("name"), "tag.name", 128)
        value = _bounded_text(item.get("value"), "tag.value", MAX_TAG_CHARS)
        if not name or name in tags:
            raise _decode_error(
                "ChessBase decoder returned a duplicate/empty tag name",
                ChessBaseDecodeCode.PROTOCOL_ERROR,
            )
        tags[name] = value

    first_white = _bounded_text(raw.get("white_first", ""), "game.white_first", 4096)
    last_white = _bounded_text(raw.get("white_last", ""), "game.white_last", 4096)
    first_black = _bounded_text(raw.get("black_first", ""), "game.black_first", 4096)
    last_black = _bounded_text(raw.get("black_last", ""), "game.black_last", 4096)
    event = _bounded_text(raw.get("event", ""), "game.event", MAX_TAG_CHARS)
    site = _bounded_text(raw.get("site", ""), "game.site", MAX_TAG_CHARS)
    year = _exact_int(raw.get("year", 0), "game.year", 0, 9999)
    month = _exact_int(raw.get("month", 0), "game.month", 0, 12)
    day = _exact_int(raw.get("day", 0), "game.day", 0, 31)
    result_code = _exact_int(raw.get("result", 0), "game.result", 0, 3)
    result = {0: "*", 1: "1-0", 2: "0-1", 3: "1/2-1/2"}[result_code]
    round_no = _exact_int(raw.get("round", 0), "game.round", 0, 255)
    subround = _exact_int(raw.get("subround", 0), "game.subround", 0, 255)
    white_elo = _exact_int(raw.get("white_elo", 0), "game.white_elo", 0, 65535)
    black_elo = _exact_int(raw.get("black_elo", 0), "game.black_elo", 0, 65535)
    eco = _exact_int(raw.get("eco", 0), "game.eco", 0, 65535)

    tags.setdefault("Event", event or "?")
    tags.setdefault("Site", site or "?")
    tags.setdefault("Date", _date(year, month, day))
    tags.setdefault("Round", f"{round_no}.{subround}" if subround else str(round_no or "?"))
    tags.setdefault("White", _person(first_white, last_white) or "?")
    tags.setdefault("Black", _person(first_black, last_black) or "?")
    tags["Result"] = result
    if white_elo:
        tags.setdefault("WhiteElo", str(white_elo))
    if black_elo:
        tags.setdefault("BlackElo", str(black_elo))
    if eco:
        tags.setdefault("CBH_ECO", str(eco))
    if start_fen != Board.START:
        tags["SetUp"] = "1"
        tags["FEN"] = start_fen

    raw_tokens = raw.get("moves")
    if type(raw_tokens) is not list or len(raw_tokens) > MAX_DECODED_TOKENS_PER_GAME:
        raise _decode_error(
            "ChessBase decoder returned an invalid move collection",
            ChessBaseDecodeCode.RESOURCE_LIMIT,
        )
    total_budget[0] += len(raw_tokens)
    if total_budget[0] > MAX_DECODED_TOKENS_TOTAL:
        raise _decode_error(
            "ChessBase decoded database exceeds the token safety limit",
            ChessBaseDecodeCode.RESOURCE_LIMIT,
        )
    line, consumed = _decode_line(raw_tokens, 0, board, nested=False, budget=[0])
    if consumed != len(raw_tokens):
        raise _decode_error(
            "ChessBase decoder left unconsumed move tokens",
            ChessBaseDecodeCode.PROTOCOL_ERROR,
        )
    line.result = result
    return PgnGame(tags=tags, line=line, source_index=index), None


def decode_chessbase_external(
    path: str | Path,
    config: ExternalChessBaseDecoderConfig,
) -> ChessBaseDecodedDatabase:
    """Decode one classic CBH family into canonical GameTrees.

    The source is fingerprinted before execution and verified byte-for-byte after
    the external process exits.  Any source mutation invalidates all decoder
    output.  Only classic ``.cbh`` is enabled by protocol v1; other recognized
    ChessBase families remain explicitly unsupported rather than guessed.
    """

    source_path = Path(path)
    probe = probe_chessbase_source(source_path)
    if not probe.recognized or not probe.is_primary_source or probe.extension != ".cbh":
        raise _decode_error(
            "This ChessBase decoder backend currently supports classic .cbh families only",
            ChessBaseDecodeCode.UNSUPPORTED_SOURCE,
        )

    executable = _validate_backend_path(config.executable)
    try:
        snapshot = capture_integrity_snapshot(source_path)
        output = _run_backend(executable, snapshot.primary_path, config)
        verify_integrity_snapshot(snapshot)
    except ChessBaseSourceChangedError as exc:
        raise _decode_error(
            "ChessBase source changed during decoding; decoder output was discarded",
            ChessBaseDecodeCode.SOURCE_CHANGED,
        ) from exc
    except ChessBaseIntegrityIOError:
        raise

    root = _parse_backend_json(output)
    if root.get("protocol") != PROTOCOL_ID or root.get("backend") != "libcbh":
        raise _decode_error(
            "ChessBase decoder protocol/backend identity mismatch",
            ChessBaseDecodeCode.PROTOCOL_ERROR,
        )
    backend_commit = _bounded_text(root.get("backend_commit"), "backend_commit", 64)
    if _SHA40_RE.fullmatch(backend_commit) is None:
        raise _decode_error(
            "ChessBase decoder backend commit identity is invalid",
            ChessBaseDecodeCode.PROTOCOL_ERROR,
        )
    if config.expected_backend_commit is not None and backend_commit != config.expected_backend_commit:
        raise _decode_error(
            "ChessBase decoder backend commit does not match the configured trusted identity",
            ChessBaseDecodeCode.PROTOCOL_ERROR,
        )

    raw_games = root.get("games")
    if type(raw_games) is not list or len(raw_games) > MAX_DECODED_GAMES:
        raise _decode_error(
            "ChessBase decoder returned an invalid game collection",
            ChessBaseDecodeCode.RESOURCE_LIMIT,
        )
    games: list[PgnGame] = []
    warnings: list[ChessBaseDecodeWarning] = []
    total_budget = [0]
    for index, raw_game in enumerate(raw_games):
        game, warning = _decode_game(raw_game, index, total_budget)
        if game is not None:
            games.append(game)
        if warning is not None:
            warnings.append(warning)

    return ChessBaseDecodedDatabase(
        source=snapshot,
        backend_name="libcbh",
        backend_commit=backend_commit,
        games=tuple(games),
        warnings=tuple(warnings),
    )
