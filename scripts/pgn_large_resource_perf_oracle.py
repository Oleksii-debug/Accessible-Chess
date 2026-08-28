from __future__ import annotations

"""PGN-05 evidence-only large-document/resource/performance acceptance.

Real chess content comes from the pinned Lichess CC0 standard-game export.
Record segmentation below is transport framing only; all PGN semantics are
owned by the canonical D06 codec/document stack. Synthetic data is used only
for exact safety-edge probes, never as format-support evidence.
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
    MAX_PGN_SOURCE_BYTES,
    PgnRoundTripError,
    PgnRoundTripErrorCode,
    canonical_round_trip_text,
    parse_pgn_text,
)
from acs.pgn_service import (
    PgnResourceLimitError,
    MAX_PGN_SOURCE_BYTES as FILE_MAX_PGN_SOURCE_BYTES,
    open_pgn,
)


PRODUCT_BASE = "d706eb93b9a4df3c6e99ab1af584a9cfe6b6f5ea"
CORPUS_URL = "https://database.lichess.org/standard/lichess_db_standard_rated_2013-01.pgn.zst"
CORPUS_SHA256 = "aa40b3671fa3cf1072eb182892cd90b0e1e003a4a5943492f64b77e7f3fd1635"
CORPUS_LICENSE = "CC0"
CORPUS_PUBLISHED_GAMES = 121_332
MAX_COMPRESSED_BYTES = 32 * 1024 * 1024
DOWNLOAD_CHUNK = 1024 * 1024
CHECKPOINTS = (250, 500, 1000, 1500, 2000)
MIN_E2E_REAL_GAMES = 500
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
    """Frame complete Lichess transport records without interpreting PGN."""

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
    request = Request(CORPUS_URL, headers={"User-Agent": "Accessible-Chess-PGN-05-QA/1"})
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
                raise AssertionError("pinned real corpus exceeds PGN-05 compressed QA bound")
            digest.update(chunk)
            output.write(chunk)
    actual = digest.hexdigest()
    if actual != CORPUS_SHA256:
        raise AssertionError(f"real corpus digest mismatch: {actual}")
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
        payload = {
            "status": "resource_reject" if exc.code in {
                PgnRoundTripErrorCode.BYTE_SIZE_LIMIT,
                PgnRoundTripErrorCode.TEXT_SIZE_LIMIT,
                PgnRoundTripErrorCode.TOKEN_COUNT_LIMIT,
            } else "unexpected_reject",
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


def _bounded_roundtrip_probe(text: str) -> dict[str, object]:
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
        raise AssertionError("canonical large-PGN round-trip exceeded bounded QA timeout")
    if not parent.poll():
        exitcode = process.exitcode
        parent.close()
        raise AssertionError(f"large-PGN probe exited without evidence: {exitcode}")
    result = parent.recv()
    parent.close()
    if process.exitcode not in (0, None):
        raise AssertionError(f"large-PGN probe process failed: {process.exitcode}")
    return result


def _probe_real_scalability(records: list[str]) -> tuple[list[dict[str, object]], int]:
    outcomes: list[dict[str, object]] = []
    largest_accepted = 0
    seen_rejection = False
    for count in CHECKPOINTS:
        source = "\n".join(records[:count])
        outcome = _bounded_roundtrip_probe(source)
        outcome = {
            "games_requested": count,
            "source_bytes": len(source.encode("utf-8")),
            "source_chars": len(source),
            **outcome,
        }
        if outcome["status"] == "accepted":
            if seen_rejection:
                raise AssertionError("larger real corpus accepted after an earlier resource rejection")
            if outcome.get("games") != count:
                raise AssertionError(
                    f"real checkpoint {count} changed game cardinality to {outcome.get('games')}"
                )
            largest_accepted = count
        elif outcome["status"] == "resource_reject":
            seen_rejection = True
        else:
            raise AssertionError(
                f"real checkpoint {count} failed outside documented resource contract: {outcome}"
            )
        outcomes.append(outcome)

    if largest_accepted < MIN_E2E_REAL_GAMES:
        raise AssertionError(
            f"canonical D06 accepted only {largest_accepted} real games; "
            f"minimum PGN-05 evidence benchmark is {MIN_E2E_REAL_GAMES}"
        )
    return outcomes, largest_accepted


def _real_document_e2e(records: list[str], count: int) -> dict[str, object]:
    source_text = "\n".join(records[:count])
    with tempfile.TemporaryDirectory(prefix="accessible-chess-pgn05-") as directory:
        root = Path(directory)
        source_path = root / "large-real-source.pgn"
        destination = root / "large-real-save-as.pgn"
        source_path.write_text(source_text, encoding="utf-8", newline="\n")
        source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()

        started = time.perf_counter()
        session = PgnDocumentSession.open(source_path)
        open_seconds = round(time.perf_counter() - started, 3)
        view = session.view()
        if view.game_count != count:
            raise AssertionError(f"document open changed game count: {view.game_count} != {count}")
        if view.global_warnings or not view.source_overwrite_safe:
            raise AssertionError("strict real document unexpectedly opened in recovery/unsafe state")

        original_games = session.workspace.games()
        started = time.perf_counter()
        saved = session.save_as(destination)
        save_seconds = round(time.perf_counter() - started, 3)
        if not destination.exists() or saved.size != destination.stat().st_size:
            raise AssertionError("large Save As did not publish a complete destination")

        started = time.perf_counter()
        reopened = PgnDocumentSession.open(destination)
        reopen_seconds = round(time.perf_counter() - started, 3)
        if reopened.workspace.games() != original_games:
            raise AssertionError("large real Save As/reopen changed canonical GameTrees")
        reopened_view = reopened.view()
        if reopened_view.game_count != count or reopened_view.global_warnings:
            raise AssertionError("large saved document reopened with changed cardinality/warnings")

        return {
            "games": count,
            "source_bytes": source_path.stat().st_size,
            "source_sha256": source_sha,
            "canonical_saved_bytes": destination.stat().st_size,
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
    source = SourceFingerprint(
        path="pgn05-probe.pgn",
        size=18,
        sha256="0" * 64,
        suffix=".pgn",
    )
    handle = _RecordingHandle('[Event "QA"]\n[Result "*"]\n\n*\n')
    with patch("acs.pgn_service.fingerprint", return_value=source), patch.object(
        Path, "open", return_value=handle
    ):
        opened = open_pgn("pgn05-probe.pgn")
    if opened.total_games != 1:
        raise AssertionError("I/O model probe changed canonical record count")
    expected = FILE_MAX_PGN_SOURCE_BYTES + 1
    if handle.calls != [expected]:
        raise AssertionError(f"unexpected file read pattern: {handle.calls}")
    return {
        "read_calls": handle.calls,
        "bounded_read": True,
        "whole_document_read": True,
        "streaming_api_observed": False,
        "classification": "BOUNDED_WHOLE_DOCUMENT_NOT_STREAMING",
    }


def _oversize_file_probe() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="accessible-chess-pgn05-limit-") as directory:
        path = Path(directory) / "oversize.pgn"
        with path.open("wb") as handle:
            handle.seek(FILE_MAX_PGN_SOURCE_BYTES)
            handle.write(b"X")
        expected_size = FILE_MAX_PGN_SOURCE_BYTES + 1
        if path.stat().st_size != expected_size:
            raise AssertionError("could not create exact oversize boundary probe")

        started = time.perf_counter()
        with patch.object(Path, "open", side_effect=AssertionError("oversize payload was opened")):
            try:
                open_pgn(path)
            except PgnResourceLimitError:
                pass
            else:
                raise AssertionError("oversize real file was not rejected fail-closed")
        return {
            "bytes": expected_size,
            "limit_bytes": FILE_MAX_PGN_SOURCE_BYTES,
            "payload_opened": False,
            "status": "FAIL_CLOSED_BEFORE_PAYLOAD_READ",
            "seconds": round(time.perf_counter() - started, 3),
        }


def _lexical_limit_probe() -> dict[str, object]:
    # Compact adversarial text reaches the lexical-token ceiling far below the
    # 64 MiB source ceiling. This supplements, not replaces, real-corpus proof.
    text = '[Result "*"]\n\n' + ("e4 " * (MAX_PGN_LEXICAL_TOKENS + 4)) + "*\n"
    started = time.perf_counter()
    try:
        parse_pgn_text(text, strict=True)
    except PgnRoundTripError as exc:
        if exc.code is not PgnRoundTripErrorCode.TOKEN_COUNT_LIMIT:
            raise AssertionError(f"lexical bound returned {exc.code.value}") from exc
    else:
        raise AssertionError("lexical token ceiling did not fail closed")
    return {
        "source_bytes": len(text.encode("utf-8")),
        "configured_token_limit": MAX_PGN_LEXICAL_TOKENS,
        "status": PgnRoundTripErrorCode.TOKEN_COUNT_LIMIT.value,
        "seconds": round(time.perf_counter() - started, 3),
    }


def run(*, games: int, e2e_games: int) -> int:
    if MAX_PGN_SOURCE_BYTES != FILE_MAX_PGN_SOURCE_BYTES:
        raise AssertionError("D06 codec and file-service byte ceilings diverged")
    if games < max(CHECKPOINTS):
        raise AssertionError(f"--games must be at least {max(CHECKPOINTS)}")
    if e2e_games < MIN_E2E_REAL_GAMES:
        raise AssertionError(f"--e2e-games must be at least {MIN_E2E_REAL_GAMES}")

    with tempfile.TemporaryDirectory(prefix="accessible-chess-pgn05-corpus-") as directory:
        compressed = Path(directory) / "lichess-standard-2013-01.pgn.zst"
        download = _download_verified(compressed)
        with _open_zstd_text(compressed) as stream:
            records = list(iter_complete_records(stream, limit=games))
        if len(records) != games:
            raise AssertionError(f"real corpus yielded {len(records)} records, expected {games}")

        outcomes, largest_accepted = _probe_real_scalability(records)
        if e2e_games > largest_accepted:
            raise AssertionError(
                f"requested real E2E size {e2e_games} exceeds accepted checkpoint {largest_accepted}"
            )
        e2e = _real_document_e2e(records, e2e_games)

    io_model = _io_model_probe()
    oversize = _oversize_file_probe()
    lexical = _lexical_limit_probe()

    rejected = [item for item in outcomes if item["status"] == "resource_reject"]
    capability = {
        "real_multigame_document": f"SUPPORTED_AT_{largest_accepted}_GAME_CHECKPOINT",
        "oversize_fail_closed": "SUPPORTED",
        "streaming": "BLOCKED_NOT_IMPLEMENTED",
        "overall": "PARTIAL_BOUNDED_WHOLE_DOCUMENT",
    }
    report = {
        "schema": 1,
        "product_base": PRODUCT_BASE,
        "source": {
            "name": "Lichess standard rated 2013-01",
            "url": CORPUS_URL,
            "license": CORPUS_LICENSE,
            "published_games": CORPUS_PUBLISHED_GAMES,
            **download,
        },
        "configured_limits": {
            "source_bytes": MAX_PGN_SOURCE_BYTES,
            "lexical_tokens": MAX_PGN_LEXICAL_TOKENS,
        },
        "real_scalability": outcomes,
        "largest_accepted_checkpoint": largest_accepted,
        "resource_rejections": rejected,
        "real_document_e2e": e2e,
        "io_model": io_model,
        "oversize_file": oversize,
        "lexical_limit": lexical,
        "capability": capability,
        "product_mutation": "NONE",
    }
    print("PGN05_LARGE_RESOURCE_REPORT=" + json.dumps(report, sort_keys=True))
    print("PGN-05 LARGE RESOURCE PERFORMANCE PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", type=int, default=2000)
    parser.add_argument("--e2e-games", type=int, default=500)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        # Selftest avoids network/large allocations; CI focused tests cover the
        # Product APIs before the real campaign.
        model = _io_model_probe()
        if model["classification"] != "BOUNDED_WHOLE_DOCUMENT_NOT_STREAMING":
            raise AssertionError("I/O capability classification changed")
        print("PGN-05 ORACLE SELFTEST PASS")
        return 0
    return run(games=args.games, e2e_games=args.e2e_games)


if __name__ == "__main__":
    raise SystemExit(main())
