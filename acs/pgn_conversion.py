from __future__ import annotations

"""Reviewed legacy PGN -> canonical UTF-8, using the existing D06 authorities.

This is a conversion of a bounded document, not a new parser or a damaged-file
repairer. The source is never written; publication always creates a new file.
"""

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Callable

from .import_contract import SourceFingerprint, SourceReadCancelledError, read_source_snapshot
from .pgn_roundtrip import MAX_PGN_SOURCE_BYTES, PgnRoundTripError, canonical_round_trip_text
from .pgn_service import PgnFileError, _looks_like_windows_1251_pgn_bytes, save_pgn_atomic


ENCODINGS = ("auto", "utf-8", "utf-16", "windows-1251", "windows-1252", "iso-8859-1", "cp866", "koi8-r", "koi8-u")
_CODECS = {name: name for name in ENCODINGS[1:]}
_CODECS.update({"windows-1251": "cp1251", "windows-1252": "cp1252", "utf-8": "utf-8-sig"})
_UTF32_BOMS = (b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")


class PgnConversionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PgnConversionSummary:
    games: int
    moves: int
    variations: int
    comments: int
    annotations: int
    custom_starts: int


@dataclass(frozen=True, slots=True)
class PgnConversionPlan:
    source: SourceFingerprint
    encoding: str
    summary: PgnConversionSummary
    output_sha256: str
    output_bytes: int
    first_game_preview: str

    def public_report(self) -> dict[str, object]:
        """No local paths, original headers, comments or player names in reports."""
        return {
            "source_sha256": self.source.sha256,
            "source_bytes": self.source.size,
            "source_encoding": self.encoding,
            "output_encoding": "utf-8",
            "output_sha256": self.output_sha256,
            "output_bytes": self.output_bytes,
            "summary": asdict(self.summary),
            "semantic_roundtrip_verified": True,
            "chess_legality_verified": False,
            "source_modified": False,
        }


def _poll(cancel_check: Callable[[], bool] | None) -> None:
    if cancel_check is not None:
        cancelled = cancel_check()
        if type(cancelled) is not bool:
            raise TypeError("cancel_check must return bool")
        if cancelled:
            raise PgnConversionError("cancelled", "Перекодування скасовано; новий файл не опубліковано.")


def _decode(raw: bytes, encoding: str) -> tuple[str, str]:
    if raw.startswith(_UTF32_BOMS):
        raise PgnConversionError("encoding", "UTF-32 не підтримується цим перекодуванням.")
    selected = encoding
    if encoding == "auto":
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            selected = "utf-16"
        else:
            try:
                return raw.decode("utf-8-sig", errors="strict"), "utf-8"
            except UnicodeDecodeError:
                if not _looks_like_windows_1251_pgn_bytes(raw):
                    raise PgnConversionError("encoding", "Кодування не визначено. Виберіть кодування джерела й перевірте текст у перегляді.") from None
                selected = "windows-1251"
    # A contradictory BOM must not silently become legacy text inside a tag.
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")) and selected != "utf-16":
        raise PgnConversionError("encoding", "Позначка UTF-16 суперечить вибраному кодуванню.")
    if raw.startswith(b"\xef\xbb\xbf") and selected != "utf-8":
        raise PgnConversionError("encoding", "Позначка UTF-8 суперечить вибраному кодуванню.")
    if selected == "utf-16" and not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise PgnConversionError("encoding", "Для UTF-16 потрібна позначка BOM; порядок байтів не вгадується.")
    try:
        return raw.decode(_CODECS[selected], errors="strict"), selected
    except UnicodeDecodeError:
        raise PgnConversionError("encoding", "Джерело містить неприпустимі байти для вибраного кодування. Символи не замінено.") from None


def _prepare(source_path: str | Path, encoding: str, max_bytes: int, cancel_check):
    if type(encoding) is not str or encoding not in ENCODINGS:
        raise ValueError("unsupported PGN source encoding")
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_PGN_SOURCE_BYTES:
        raise ValueError("PGN conversion byte limit must be between 1 and 64 MiB")
    if cancel_check is not None and not callable(cancel_check):
        raise TypeError("cancel_check must be callable")
    _poll(cancel_check)
    try:
        source, raw = read_source_snapshot(source_path, max_bytes=max_bytes, cancel_check=cancel_check)
    except SourceReadCancelledError:
        raise PgnConversionError("cancelled", "Читання скасовано; новий файл не опубліковано.") from None
    except (OSError, ValueError):
        raise PgnConversionError("source_unavailable", "Джерело недоступне, змінилося або перевищує дозволений розмір.") from None
    text, selected = _decode(raw, encoding)
    _poll(cancel_check)
    try:
        result = canonical_round_trip_text(text)
    except PgnRoundTripError as exc:
        raise PgnConversionError("pgn_" + exc.code.value, "PGN не пройшов перевірку структури. Перекодування не виправляє пошкоджені партії.") from None
    _poll(cancel_check)
    output = result.text.encode("utf-8", errors="strict")
    if len(output) > MAX_PGN_SOURCE_BYTES:
        raise PgnConversionError("output_limit", "Результат перевищує дозволений розмір UTF-8 PGN.")
    moves = variations = comments = annotations = custom_starts = 0
    for game in result.games:
        custom_starts += int(game.tags.get("SetUp") == "1")
        lines = [game.line]
        while lines:
            line = lines.pop()
            comments += len(line.leading_comments) + len(line.trailing_comments)
            moves += len(line.moves)
            for move in line.moves:
                _poll(cancel_check)
                comments += len(move.comments_before) + len(move.comments_after)
                annotations += len(move.nags)
                variations += len(move.variations)
                lines.extend(move.variations)
    # Only the explicit, local review control shows text; public_report never does.
    sample = result.text[:1200]
    sample = "".join(c for c in sample if c.isprintable() or c in "\n\r\t")
    plan = PgnConversionPlan(
        source, selected,
        PgnConversionSummary(len(result.games), moves, variations, comments, annotations, custom_starts),
        hashlib.sha256(output).hexdigest(), len(output), sample,
    )
    return plan, result.games


def preview_conversion(source_path: str | Path, *, encoding: str = "auto", max_bytes: int = MAX_PGN_SOURCE_BYTES, cancel_check=None) -> PgnConversionPlan:
    return _prepare(source_path, encoding, max_bytes, cancel_check)[0]


def convert_pgn(source_path: str | Path, destination: str | Path, *, reviewed_plan: PgnConversionPlan, max_bytes: int = MAX_PGN_SOURCE_BYTES, cancel_check=None) -> SourceFingerprint:
    """Revalidate reviewed bytes and semantics, then atomically create a new PGN."""
    if type(reviewed_plan) is not PgnConversionPlan:
        raise TypeError("reviewed_plan must be PgnConversionPlan")
    source_path, destination = Path(source_path), Path(destination)
    if destination.suffix.casefold() != ".pgn":
        raise PgnConversionError("destination_format", "Новий файл повинен мати розширення .pgn.")
    if os.path.normcase(os.path.abspath(source_path)) == os.path.normcase(os.path.abspath(destination)):
        raise PgnConversionError("same_source", "Виберіть інший файл: оригінал не перезаписується.")
    refreshed, games = _prepare(source_path, reviewed_plan.encoding, max_bytes, cancel_check)
    if refreshed != reviewed_plan:
        raise PgnConversionError("source_changed", "Джерело змінилося після перегляду. Виконайте перегляд знову.")
    _poll(cancel_check)

    def checked_games():
        for game in games:
            _poll(cancel_check)
            yield game
        _poll(cancel_check)

    try:
        return save_pgn_atomic(
            destination,
            checked_games(),
            overwrite=False,
            pre_publish_check=lambda: _poll(cancel_check),
        )
    except FileExistsError:
        raise PgnConversionError("destination_exists", "Файл призначення вже існує. Виберіть нове ім’я.") from None
    except (OSError, PgnFileError):
        raise PgnConversionError("publication_failed", "Не вдалося опублікувати новий файл. Перевірте папку й вільне місце.") from None


def format_conversion_review(plan: PgnConversionPlan, language: str = "uk") -> str:
    if type(plan) is not PgnConversionPlan or type(language) is not str:
        raise TypeError("invalid PGN conversion review")
    s = plan.summary
    if language == "en":
        return (f"Source encoding: {plan.encoding}. Output: UTF-8.\n"
                f"Games: {s.games}; moves (all lines): {s.moves}; variations: {s.variations}; "
                f"comments: {s.comments}; annotations: {s.annotations}; custom starts: {s.custom_starts}.\n"
                "GameTree round-trip verified. Chess legality is not checked by this tool.\n"
                "The original is kept. Whitespace is normalized. Check the text before converting.\n\n" + plan.first_game_preview)
    return (f"Кодування джерела: {plan.encoding}. Результат: UTF-8.\n"
            f"Партій: {s.games}; ходів у всіх лініях: {s.moves}; варіантів: {s.variations}; "
            f"коментарів: {s.comments}; анотацій: {s.annotations}; нестандартних початкових позицій: {s.custom_starts}.\n"
            "Збереження дерева партії перевірено. Допустимість ходів цей інструмент не перевіряє.\n"
            "Оригінал зберігається. Пробіли й переноси нормалізуються. Перевірте текст перед перекодуванням.\n\n" + plan.first_game_preview)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Перегляд і безпечне перекодування PGN у UTF-8 без зміни оригіналу.")
    parser.add_argument("source", help="Шлях до PGN джерела")
    parser.add_argument("--encoding", choices=ENCODINGS, default="auto", help="Кодування джерела")
    parser.add_argument("--output", help="Новий PGN файл; без цього параметра виконується лише перегляд")
    parser.add_argument("--expect-sha256", help="SHA-256 джерела з попереднього перегляду")
    parser.add_argument("--expect-output-sha256", help="SHA-256 UTF-8 результату з попереднього перегляду")
    parser.add_argument("--json", action="store_true", help="Звіт JSON без шляхів і приватного тексту")
    args = parser.parse_args(argv)
    if args.output and (not args.expect_sha256 or not args.expect_output_sha256):
        parser.error("Для запису потрібні --expect-sha256 і --expect-output-sha256 зі звіту перегляду.")
    try:
        plan = preview_conversion(args.source, encoding=args.encoding)
        if args.expect_sha256 is not None and args.expect_sha256 != plan.source.sha256:
            raise PgnConversionError("source_changed", "SHA-256 джерела не збігається з переглядом.")
        if args.expect_output_sha256 is not None and args.expect_output_sha256 != plan.output_sha256:
            raise PgnConversionError(
                "review_changed",
                "SHA-256 UTF-8 результату не збігається з попереднім переглядом. Перевірте кодування й виконайте перегляд знову.",
            )
        report = plan.public_report()
        if args.output:
            saved = convert_pgn(args.source, args.output, reviewed_plan=plan)
            report["published_sha256"] = saved.sha256
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(format_conversion_review(plan))
            print("SHA-256 джерела: " + plan.source.sha256)
            print("SHA-256 UTF-8 результату: " + plan.output_sha256)
            if args.output:
                print("Новий UTF-8 PGN збережено.")
        return 0
    except PgnConversionError as exc:
        print(json.dumps({"error_code": exc.code, "message": str(exc)}, ensure_ascii=False) if args.json else str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
