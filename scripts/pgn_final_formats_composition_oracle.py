from __future__ import annotations

"""Evidence-only composition oracle for accepted Version 2 D06 surfaces.

The oracle deliberately owns no PGN grammar, GameTree semantics, chess rules, or
filesystem publication.  Real external content is transport-framed only.  All
semantic work is delegated to the canonical D06 parser/GameTree, durable resume
record, document workspace, and incremental atomic exporter.
"""

import argparse
from contextlib import contextmanager
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
from typing import Iterator, TextIO
from urllib.request import Request, urlopen

import zstandard

from acs.gametree_navigation import GameTreeCursor
from acs.gametree_resume import (
    build_resume_record,
    resume_record_from_json,
    resume_record_to_json,
    restore_resume_record,
)
from acs.pgn_document import PgnDocumentSession
from acs.pgn_roundtrip import parse_pgn_text, serialize_pgn_text
from acs.pgn_service import open_pgn, save_pgn_atomic


AUTHORITY_SHA = "43b8d22f4c80fa89c2bdd39a2f23d5f4819cc86d"
CORPUS_URL = "https://database.lichess.org/standard/lichess_db_standard_rated_2013-01.pgn.zst"
CORPUS_SHA256 = "aa40b3671fa3cf1072eb182892cd90b0e1e003a4a5943492f64b77e7f3fd1635"
CORPUS_LICENSE = "CC0"
CORPUS_PUBLISHED_GAMES = 121_332
REAL_GAME_COUNT = 64
MAX_COMPRESSED_BYTES = 32 * 1024 * 1024
DOWNLOAD_CHUNK = 1024 * 1024


@contextmanager
def _open_zstd_text(path: Path):
    source = path.open("rb")
    reader = zstandard.ZstdDecompressor().stream_reader(source)
    text = io.TextIOWrapper(reader, encoding="utf-8", errors="strict", newline=None)
    try:
        yield text
    finally:
        text.close()
        try:
            reader.close()
        finally:
            source.close()


def _scan_comment_state(line: str, inside_brace: bool) -> bool:
    index = 0
    while index < len(line):
        character = line[index]
        if inside_brace:
            if character == "}":
                inside_brace = False
        else:
            if character == ";":
                break
            if character == "{":
                inside_brace = True
        index += 1
    return inside_brace


def iter_complete_records(stream: TextIO, *, limit: int) -> Iterator[str]:
    """Frame Lichess transport records without interpreting PGN semantics."""

    current: list[str] = []
    inside_brace = False
    yielded = 0
    for line in stream:
        if not inside_brace and line.startswith('[Event "') and current:
            record = "".join(current).strip()
            if record:
                yielded += 1
                yield record + "\n"
                if yielded >= limit:
                    return
            current = [line]
            inside_brace = _scan_comment_state(line, False)
            continue
        current.append(line)
        inside_brace = _scan_comment_state(line, inside_brace)
    if current and yielded < limit:
        record = "".join(current).strip()
        if record:
            yield record + "\n"


def _download_verified(destination: Path) -> dict[str, object]:
    request = Request(
        CORPUS_URL,
        headers={"User-Agent": "Accessible-Chess-D06-Final-Formats-QA/1"},
    )
    digest = hashlib.sha256()
    total = 0
    started = time.perf_counter()
    with urlopen(request, timeout=60) as response, destination.open("wb") as output:
        while True:
            chunk = response.read(DOWNLOAD_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_COMPRESSED_BYTES:
                raise AssertionError("pinned Lichess corpus exceeds QA transport bound")
            digest.update(chunk)
            output.write(chunk)
    actual = digest.hexdigest()
    if actual != CORPUS_SHA256:
        raise AssertionError(f"pinned Lichess corpus digest mismatch: {actual}")
    return {
        "compressed_bytes": total,
        "sha256": actual,
        "download_seconds": round(time.perf_counter() - started, 3),
    }


def _choose_real_cursor(game) -> GameTreeCursor:
    if not game.line.moves:
        return GameTreeCursor()
    return GameTreeCursor((), min(8, len(game.line.moves)))


class _CountingGames:
    """Single-pass iterable proving the exporter does not require collection APIs."""

    def __init__(self, games) -> None:
        self._games = games
        self.yielded = 0
        self.iterations = 0

    def __iter__(self):
        if self.iterations:
            raise AssertionError("incremental exporter attempted to iterate games twice")
        self.iterations += 1
        for game in self._games:
            self.yielded += 1
            yield game

    def __len__(self):
        raise AssertionError("incremental exporter requested collection length")

    def __getitem__(self, _index):
        raise AssertionError("incremental exporter requested random access")


def _real_composition(records: list[str], root: Path) -> dict[str, object]:
    source_text = "\n".join(records)
    strict_games = parse_pgn_text(source_text, strict=True)
    if len(strict_games) != REAL_GAME_COUNT:
        raise AssertionError(
            f"strict real corpus cardinality changed: {len(strict_games)} != {REAL_GAME_COUNT}"
        )

    selected_index = next(
        (index for index, game in enumerate(strict_games) if len(game.line.moves) >= 8),
        0,
    )
    selected = strict_games[selected_index]
    cursor = _choose_real_cursor(selected)

    resume = build_resume_record(selected, cursor, generation=1)
    encoded_resume = resume_record_to_json(resume)
    decoded_resume = resume_record_from_json(encoded_resume)
    restored_game, restored_cursor = restore_resume_record(
        decoded_resume,
        expected_tree_digest=resume.snapshot.tree_digest,
    )
    if restored_game != selected or restored_cursor != cursor:
        raise AssertionError("durable resume changed the selected real GameTree/cursor")

    composed_games = list(strict_games)
    composed_games[selected_index] = restored_game
    canonical_expected = serialize_pgn_text(tuple(composed_games))

    destination = root / "composed-real.pgn"
    streamed = _CountingGames(tuple(composed_games))
    saved = save_pgn_atomic(destination, streamed)
    if streamed.iterations != 1 or streamed.yielded != REAL_GAME_COUNT:
        raise AssertionError("incremental exporter did not consume exactly one real-game pass")
    actual_bytes = destination.read_bytes()
    expected_bytes = canonical_expected.encode("utf-8")
    if actual_bytes != expected_bytes:
        raise AssertionError("incremental export bytes diverged from canonical serializer bytes")
    if saved.sha256 != hashlib.sha256(expected_bytes).hexdigest():
        raise AssertionError("saved fingerprint does not identify canonical export bytes")

    opened = open_pgn(destination)
    if opened.global_warnings or opened.games != tuple(composed_games):
        raise AssertionError("canonical file reopen changed real composed GameTrees")

    session = PgnDocumentSession.open(destination)
    if session.view().game_count != REAL_GAME_COUNT or session.view().global_warnings:
        raise AssertionError("professional document reopen changed real composed document state")
    if session.workspace.games() != tuple(composed_games):
        raise AssertionError("professional workspace changed composed real GameTrees")

    return {
        "games": REAL_GAME_COUNT,
        "selected_game_index": selected_index,
        "selected_event": selected.tags.get("Event", ""),
        "selected_white": selected.tags.get("White", ""),
        "selected_black": selected.tags.get("Black", ""),
        "cursor_next_move_index": cursor.next_move_index,
        "resume_generation": decoded_resume.generation,
        "resume_tree_digest": resume.snapshot.tree_digest,
        "resume_payload_digest": decoded_resume.payload_digest,
        "export_bytes": len(actual_bytes),
        "export_sha256": saved.sha256,
        "export_iterations": streamed.iterations,
        "export_games_yielded": streamed.yielded,
        "byte_identical_to_canonical_serializer": True,
        "strict_file_reopen_equal": True,
        "professional_document_reopen_equal": True,
    }


def _nested_selftest(root: Path) -> dict[str, object]:
    """Composition-shape control; real format support is proved separately above."""

    text = """[Event \"Nested composition control\"]
[Site \"QA\"]
[Result \"*\"]

1. e4 (1. d4 d5 (1... Nf6)) e5 2. Nf3 *
"""
    games = parse_pgn_text(text, strict=True)
    game = games[0]
    # Cursor inside the nested variation after Nf6.
    from acs.gametree_navigation import VariationStep

    cursor = GameTreeCursor((VariationStep(0, 0), VariationStep(1, 0)), 1)
    resume = build_resume_record(game, cursor, generation=7)
    restored, restored_cursor = restore_resume_record(
        resume_record_from_json(resume_record_to_json(resume)),
        expected_tree_digest=resume.snapshot.tree_digest,
    )
    if restored != game or restored_cursor != cursor:
        raise AssertionError("nested-RAV resume composition control changed tree/cursor")

    destination = root / "nested-control.pgn"
    save_pgn_atomic(destination, iter((restored,)))
    reopened = parse_pgn_text(destination.read_text(encoding="utf-8"), strict=True)
    if reopened != (game,):
        raise AssertionError("nested-RAV incremental export/reopen changed canonical tree")
    return {
        "generation": 7,
        "nested_depth": 2,
        "roundtrip_equal": True,
    }


def run() -> int:
    with tempfile.TemporaryDirectory(prefix="accessible-chess-d06-compose-") as directory:
        root = Path(directory)
        compressed = root / "lichess-standard-2013-01.pgn.zst"
        download = _download_verified(compressed)
        with _open_zstd_text(compressed) as stream:
            records = list(iter_complete_records(stream, limit=REAL_GAME_COUNT))
        if len(records) != REAL_GAME_COUNT:
            raise AssertionError(
                f"real corpus yielded {len(records)} records, expected {REAL_GAME_COUNT}"
            )
        real = _real_composition(records, root)
        nested = _nested_selftest(root)

    report = {
        "schema": 1,
        "authority_sha": AUTHORITY_SHA,
        "source": {
            "name": "Lichess standard rated 2013-01",
            "url": CORPUS_URL,
            "license": CORPUS_LICENSE,
            "published_games": CORPUS_PUBLISHED_GAMES,
            **download,
        },
        "real_composition": real,
        "nested_control": nested,
        "capability": {
            "real_pgn_to_resume_to_incremental_export_to_reopen": "SUPPORTED_ON_EXACT_AUTHORITY",
            "product_mutation": "NONE",
            "nvda_verified": "NO",
        },
    }
    print("PGN_FINAL_FORMATS_COMPOSITION=" + json.dumps(report, ensure_ascii=False, sort_keys=True))
    print("D06 FINAL FORMATS COMPOSITION PASS")
    return 0


def selftest() -> int:
    with tempfile.TemporaryDirectory(prefix="accessible-chess-d06-compose-selftest-") as directory:
        evidence = _nested_selftest(Path(directory))
    if evidence["nested_depth"] != 2 or not evidence["roundtrip_equal"]:
        raise AssertionError("composition oracle selftest did not cover nested-RAV roundtrip")
    print("D06 FINAL FORMATS ORACLE SELFTEST PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    return selftest() if args.selftest else run()


if __name__ == "__main__":
    raise SystemExit(main())
