from __future__ import annotations

"""PGN-05 post-repair real-world large-document acceptance.

This is evidence-only QA. Lichess transport records are framed at Event-tag
boundaries solely to create bounded test documents; every PGN semantic decision,
GameTree normalization, serialization and document workflow is delegated to the
canonical Accessible Chess D06 Product APIs.
"""

import argparse
from contextlib import contextmanager
import hashlib
import io
import json
import multiprocessing
from pathlib import Path
import tempfile
import time
from typing import Iterator, TextIO
from unittest.mock import patch
from urllib.request import Request, urlopen

import zstandard

from acs.import_contract import SourceFingerprint
from acs.pgn_document import PgnDocumentSession
from acs.pgn_roundtrip import (
    MAX_PGN_LEXICAL_TOKENS,
    PgnRoundTripError,
    PgnRoundTripErrorCode,
    canonical_round_trip_text,
    parse_pgn_text,
)
from acs.pgn_service import (
    MAX_PGN_SOURCE_BYTES,
    PgnResourceLimitError,
    open_pgn,
)


PRODUCT_BASE = "357d78f96ba404035c9eae7444c67b9c3b4f4c31"
CORPUS_URL = "https://database.lichess.org/standard/lichess_db_standard_rated_2013-01.pgn.zst"
CORPUS_SHA256 = "aa40b3671fa3cf1072eb182892cd90b0e1e003a4a5943492f64b77e7f3fd1635"
CORPUS_LICENSE = "CC0"
CORPUS_PUBLISHED_GAMES = 121_332
REPAIRED_RECORD_INDEX = 201
REPAIRED_RECORD_SHA256 = "731e9e823e72aae59a479df8f8840b55b997cbc86b5a4b700b99998d833db096"
CHECKPOINTS = (250, 500, 1000, 1500, 2000)
E2E_GAMES = 500
MAX_COMPRESSED_BYTES = 32 * 1024 * 1024
DOWNLOAD_CHUNK = 1024 * 1024
CHILD_TIMEOUT_SECONDS = 120.0


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
    """Frame Lichess records without interpreting PGN moves or annotations."""

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
    request = Request(CORPUS_URL, headers={"User-Agent": "Accessible-Chess-PGN-05-Revalidation/1"})
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
                raise AssertionError("pinned corpus compressed payload exceeded QA bound")
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


def _roundtrip_child(connection, text: str) -> None:
    started = time.perf_counter()
    try:
        result = canonical_round_trip_text(text)
    except PgnRoundTripError as exc:
        resource_codes = {
            PgnRoundTripErrorCode.BYTE_SIZE_LIMIT,
            PgnRoundTripErrorCode.TEXT_SIZE_LIMIT,
            PgnRoundTripErrorCode.TOKEN_SIZE_LIMIT,
            PgnRoundTripErrorCode.TOKEN_COUNT_LIMIT,
            PgnRoundTripErrorCode.COMMENT_SIZE_LIMIT,
            PgnRoundTripErrorCode.TAG_SIZE_LIMIT,
            PgnRoundTripErrorCode.TAG_COUNT_LIMIT,
            PgnRoundTripErrorCode.GAME_COUNT_LIMIT,
        }
        payload = {
            "status": "resource_reject" if exc.code in resource_codes else "unexpected_reject",
            "code": exc.code.value,
            "seconds": round(time.perf_counter() - started, 3),
        }
    except BaseException as exc:
        payload = {
            "status": "unexpected_exception",
            "code": type(exc).__name__,
            "seconds": round(time.perf_counter() - started, 3),
        }
    else:
        payload = {
            "status": "accepted",
            "games": len(result.games),
            "canonical_chars": len(result.text),
            "seconds": round(time.perf_counter() - started, 3),
        }
    try:
        connection.send(payload)
    finally:
        connection.close()


def _bounded_roundtrip(text: str) -> dict[str, object]:
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_roundtrip_child, args=(child, text))
    process.start()
    child.close()
    process.join(CHILD_TIMEOUT_SECONDS)
    if process.is_alive():
        process.terminate()
        process.join(5)
        parent.close()
        raise AssertionError("canonical large-PGN round-trip exceeded QA timeout")
    if not parent.poll():
        exitcode = process.exitcode
        parent.close()
        raise AssertionError(f"large-PGN child exited without evidence: {exitcode}")
    payload = parent.recv()
    parent.close()
    if process.exitcode not in (0, None):
        raise AssertionError(f"large-PGN child failed: {process.exitcode}")
    return payload


def _scalability(records: list[str]) -> tuple[list[dict[str, object]], int]:
    outcomes: list[dict[str, object]] = []
    largest_accepted = 0
    rejected = False
    for count in CHECKPOINTS:
        source = "\n".join(records[:count])
        result = _bounded_roundtrip(source)
        outcome = {
            "games_requested": count,
            "source_bytes": len(source.encode("utf-8")),
            "source_chars": len(source),
            **result,
        }
        if result["status"] == "accepted":
            if rejected:
                raise AssertionError("larger checkpoint accepted after earlier resource rejection")
            if result.get("games") != count:
                raise AssertionError(f"checkpoint {count} changed game cardinality")
            largest_accepted = count
        elif result["status"] == "resource_reject":
            rejected = True
        else:
            raise AssertionError(f"checkpoint {count} failed outside resource contract: {result}")
        outcomes.append(outcome)
    if largest_accepted < E2E_GAMES:
        raise AssertionError(f"only {largest_accepted} real games accepted; need {E2E_GAMES}")
    return outcomes, largest_accepted


def _walk_nodes(line):
    for node in line.moves:
        yield node
        for variation in node.variations:
            yield from _walk_nodes(variation)


def _verify_repaired_record(records: list[str]) -> dict[str, object]:
    raw = records[REPAIRED_RECORD_INDEX - 1]
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    if digest != REPAIRED_RECORD_SHA256:
        raise AssertionError(f"repaired record identity changed: {digest}")

    canonical = parse_pgn_text(raw, strict=True)
    if len(canonical) != 1:
        raise AssertionError("repaired real record changed strict cardinality")
    canonical_hits = [node for node in _walk_nodes(canonical[0].line) if node.san == "c4" and "?!" in node.nags]
    if not canonical_hits:
        raise AssertionError("canonical strict record no longer contains c4 + ?! NAG")

    with tempfile.TemporaryDirectory(prefix="accessible-chess-pgn05-record201-") as directory:
        path = Path(directory) / "record201.pgn"
        path.write_text(raw, encoding="utf-8", newline="\n")
        session = PgnDocumentSession.open(path)
        games = session.workspace.games()
        if games != canonical:
            raise AssertionError("file/document ingress differs from canonical strict record #201")
        view = session.view()
        if view.global_warnings or not view.source_overwrite_safe:
            raise AssertionError("repaired strict record opened with recovery warnings")

    return {
        "record_index": REPAIRED_RECORD_INDEX,
        "record_sha256": digest,
        "canonical_file_ingress_equal": True,
        "normalized_san": "c4",
        "normalized_nag": "?!",
    }


def _professional_e2e(records: list[str]) -> dict[str, object]:
    source_text = "\n".join(records[:E2E_GAMES])
    with tempfile.TemporaryDirectory(prefix="accessible-chess-pgn05-e2e-") as directory:
        root = Path(directory)
        source = root / "real-500.pgn"
        saved_path = root / "real-500-save-as.pgn"
        source.write_text(source_text, encoding="utf-8", newline="\n")
        source_digest = hashlib.sha256(source.read_bytes()).hexdigest()

        started = time.perf_counter()
        session = PgnDocumentSession.open(source)
        open_seconds = round(time.perf_counter() - started, 3)
        view = session.view()
        if view.game_count != E2E_GAMES:
            raise AssertionError(f"professional open returned {view.game_count} games")
        if view.global_warnings or not view.source_overwrite_safe:
            raise AssertionError("professional 500-game source required recovery")
        before = session.workspace.games()

        started = time.perf_counter()
        saved = session.save_as(saved_path)
        save_seconds = round(time.perf_counter() - started, 3)

        started = time.perf_counter()
        reopened = PgnDocumentSession.open(saved_path)
        reopen_seconds = round(time.perf_counter() - started, 3)
        if reopened.workspace.games() != before:
            raise AssertionError("Save As/reopen changed canonical 500-game GameTrees")
        if reopened.view().game_count != E2E_GAMES or reopened.view().global_warnings:
            raise AssertionError("reopened 500-game document changed cardinality or warnings")

        return {
            "games": E2E_GAMES,
            "source_bytes": source.stat().st_size,
            "source_sha256": source_digest,
            "saved_bytes": saved_path.stat().st_size,
            "saved_sha256": saved.sha256,
            "open_seconds": open_seconds,
            "save_as_seconds": save_seconds,
            "reopen_seconds": reopen_seconds,
            "integrity": "canonical_gametree_equality",
        }


class _RecordingHandle:
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.calls: list[int] = []
        self.done = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size: int = -1):
        self.calls.append(size)
        if self.done:
            return ""
        self.done = True
        return self.payload


def _io_model_probe() -> dict[str, object]:
    source = SourceFingerprint(path="probe.pgn", size=30, sha256="0" * 64, suffix=".pgn")
    handle = _RecordingHandle('[Event "QA"]\n[Result "*"]\n\n*\n')
    with patch("acs.pgn_service.fingerprint", return_value=source), patch.object(Path, "open", return_value=handle):
        opened = open_pgn("probe.pgn")
    if opened.total_games != 1:
        raise AssertionError("bounded I/O probe changed game count")
    expected = MAX_PGN_SOURCE_BYTES + 1
    if handle.calls != [expected]:
        raise AssertionError(f"unexpected PGN read pattern: {handle.calls}")
    return {
        "read_calls": handle.calls,
        "bounded_read": True,
        "whole_document_read": True,
        "streaming_api_observed": False,
        "classification": "BOUNDED_WHOLE_DOCUMENT_NOT_STREAMING",
    }


def _oversize_probe() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="accessible-chess-pgn05-oversize-") as directory:
        path = Path(directory) / "oversize.pgn"
        with path.open("wb") as handle:
            handle.seek(MAX_PGN_SOURCE_BYTES)
            handle.write(b"X")
        with patch.object(Path, "open", side_effect=AssertionError("oversize payload was opened")):
            try:
                open_pgn(path)
            except PgnResourceLimitError:
                pass
            else:
                raise AssertionError("64 MiB+1 source did not fail closed before payload open")
    return {
        "bytes": MAX_PGN_SOURCE_BYTES + 1,
        "limit_bytes": MAX_PGN_SOURCE_BYTES,
        "payload_opened": False,
        "status": "FAIL_CLOSED_BEFORE_PAYLOAD_READ",
    }


def _file_lexical_limit_probe() -> dict[str, object]:
    text = '[Result "*"]\n\n' + ("e4 " * (MAX_PGN_LEXICAL_TOKENS + 4)) + "*\n"
    with tempfile.TemporaryDirectory(prefix="accessible-chess-pgn05-token-limit-") as directory:
        path = Path(directory) / "token-limit.pgn"
        path.write_text(text, encoding="utf-8", newline="\n")
        try:
            PgnDocumentSession.open(path)
        except PgnRoundTripError as exc:
            if exc.code is not PgnRoundTripErrorCode.TOKEN_COUNT_LIMIT:
                raise AssertionError(f"file ingress returned {exc.code.value} for token limit") from exc
        else:
            raise AssertionError("file/document ingress bypassed canonical lexical token ceiling")
    return {
        "source_bytes": len(text.encode("utf-8")),
        "configured_token_limit": MAX_PGN_LEXICAL_TOKENS,
        "status": PgnRoundTripErrorCode.TOKEN_COUNT_LIMIT.value,
        "file_ingress_fail_closed": True,
    }


def _selftest() -> None:
    sample = '''[Event "One"]\n[Result "*"]\n\n1. e4 e5 *\n\n[Event "Two"]\n[Result "*"]\n\n1. d4 d5 *\n'''
    framed = list(iter_complete_records(io.StringIO(sample), limit=2))
    if len(framed) != 2:
        raise AssertionError("record framing selftest failed")
    if len(parse_pgn_text("\n".join(framed), strict=True)) != 2:
        raise AssertionError("canonical parser selftest failed")
    print("PGN-05 POST-REPAIR ORACLE SELFTEST PASS")


def run(*, games: int) -> int:
    if games < max(CHECKPOINTS):
        raise AssertionError(f"--games must be at least {max(CHECKPOINTS)}")

    with tempfile.TemporaryDirectory(prefix="accessible-chess-pgn05-post-repair-") as directory:
        compressed = Path(directory) / "lichess-standard-2013-01.pgn.zst"
        download = _download_verified(compressed)
        with _open_zstd_text(compressed) as stream:
            records = list(iter_complete_records(stream, limit=games))
        if len(records) != games:
            raise AssertionError(f"pinned corpus yielded {len(records)} records, expected {games}")

        scalability, largest_accepted = _scalability(records)
        repaired_record = _verify_repaired_record(records)
        professional = _professional_e2e(records)

    io_model = _io_model_probe()
    oversize = _oversize_probe()
    lexical = _file_lexical_limit_probe()

    report = {
        "schema": 2,
        "product_base": PRODUCT_BASE,
        "source": {
            "name": "Lichess standard rated 2013-01",
            "url": CORPUS_URL,
            "license": CORPUS_LICENSE,
            "published_games": CORPUS_PUBLISHED_GAMES,
            **download,
        },
        "scalability": scalability,
        "largest_accepted_checkpoint": largest_accepted,
        "repaired_real_record": repaired_record,
        "professional_document": professional,
        "io_model": io_model,
        "oversize_source": oversize,
        "lexical_limit": lexical,
        "capability": {
            "real_multigame_document": f"SUPPORTED_AT_{largest_accepted}_GAME_CHECKPOINT",
            "professional_open_save_reopen": f"SUPPORTED_AT_{E2E_GAMES}_REAL_GAMES",
            "oversize_fail_closed": "SUPPORTED",
            "lexical_limit_fail_closed": "SUPPORTED",
            "streaming": "BLOCKED_NOT_IMPLEMENTED",
            "overall": "PARTIAL_BOUNDED_WHOLE_DOCUMENT",
        },
        "product_mutation": "NONE",
    }
    print("PGN05_POST_REPAIR_REPORT=" + json.dumps(report, sort_keys=True))
    print("PGN-05 POST-REPAIR LARGE RESOURCE ACCEPTANCE PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", type=int, default=2000)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        _selftest()
        return 0
    return run(games=args.games)


if __name__ == "__main__":
    raise SystemExit(main())
